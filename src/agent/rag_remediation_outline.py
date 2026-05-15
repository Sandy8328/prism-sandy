"""
RAG-grounded remediation outline: Gemini may only cite indices into a pool of
(graph runbook text + BM25/Qdrant chunk bodies). Expanded text is never model-invented.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from src.agent.llm_client import LlmClientError, call_gemini_rag_remediation_pick

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def _load_cfg() -> dict[str, Any]:
    try:
        import yaml

        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _oras_from_report_and_events(report: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    oc = (report.get("ora_code") or {}).get("code")
    if oc:
        seen.add(str(oc).strip().upper())
    for c in report.get("related_errors") or []:
        u = str(c).strip().upper()
        if u.startswith("ORA-"):
            seen.add(u)
    for ev in events or []:
        code = str(ev.get("code") or "").strip().upper()
        if code.startswith("ORA-"):
            seen.add(code)
        for blob in (ev.get("raw"), ev.get("preview"), ev.get("message")):
            if not isinstance(blob, str):
                continue
            for m in re.findall(r"\bORA-\d{5}\b", blob, flags=re.I):
                seen.add(m.upper())
    return sorted(seen)


def _session_retrieval_query(events: list[dict[str, Any]], cap: int = 16000) -> str:
    parts: list[str] = []
    for ev in (events or [])[:400]:
        blob = ev.get("raw") or ev.get("preview") or ev.get("message") or ""
        if isinstance(blob, str) and blob.strip():
            parts.append(blob.strip()[:1200])
    return "\n".join(parts)[:cap]


def _build_evidence_pool(
    report: dict[str, Any],
    events: list[dict[str, Any]],
    ora_codes: list[str],
    *,
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    """Ordered pool: graph entries first, then RAG chunks."""
    from src.knowledge_graph.graph import get_commands_for_ora

    pool: list[dict[str, Any]] = []
    for ora in ora_codes:
        info = get_commands_for_ora(ora)
        for cmd in info.get("commands") or []:
            t = str(cmd).strip()
            if len(t) < 2:
                continue
            pool.append(
                {
                    "id": f"graph_{len(pool)}",
                    "source": "graph",
                    "ora_code": ora,
                    "text": t[:8000],
                }
            )
            if len(pool) >= 18:
                break
        if len(pool) >= 18:
            break

    host = str(report.get("hostname") or "")[:240]
    plat = str(report.get("platform") or "")[:80]
    primary = ora_codes[0] if ora_codes else str((report.get("ora_code") or {}).get("code") or "")
    q = _session_retrieval_query(events)
    if len(q) < 120:
        q = (" ".join(ora_codes[:24]) + "\n" + (report.get("query") or ""))[:16000]

    note = ""
    try:
        from src.retrieval.pipeline import run_retrieval_pipeline

        rout = run_retrieval_pipeline(
            query=q,
            ora_code=str(primary or ""),
            hostname=host,
            timestamp_str=str(report.get("timestamp_str") or ""),
            platform=plat,
            top_k=top_k,
        )
    except Exception as e:
        return pool, f"retrieval_skipped:{e}"

    fused = rout.get("fused_results") or []
    for i, row in enumerate(fused):
        pay = row.get("payload") or {}
        txt = (pay.get("raw_text") or "").strip()
        if len(txt) < 50:
            continue
        cid = pay.get("chunk_id") or row.get("chunk_id") or i
        pool.append(
            {
                "id": f"rag_{cid}",
                "source": "rag",
                "ora_code": "",
                "text": txt[:8000],
            }
        )
        if len(pool) >= 32:
            break
    return pool, note


def _validate_indices(raw: dict[str, Any], pool_len: int) -> tuple[list[int], str]:
    summary = str(raw.get("summary") or "").strip()[:900]
    ix = raw.get("indices")
    if not isinstance(ix, list):
        return [], summary
    out: list[int] = []
    seen: set[int] = set()
    for v in ix:
        try:
            j = int(v)
        except (TypeError, ValueError):
            continue
        if j < 0 or j >= pool_len or j in seen:
            continue
        seen.add(j)
        out.append(j)
        if len(out) >= 14:
            break
    return out, summary


def attach_rag_remediation_outline(
    report: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    incident_id: str,
) -> None:
    cfg = _load_cfg()
    llm = cfg.get("llm") or {}
    rr = llm.get("rag_remediation") or {}
    if not bool(llm.get("enabled", False)) or not bool(rr.get("enabled", False)):
        report["rag_remediation_outline"] = {"used": False, "reason": "disabled"}
        return
    if not os.getenv("GEMINI_API_KEY", "").strip():
        report["rag_remediation_outline"] = {"used": False, "reason": "no_gemini_api_key"}
        return

    ora_codes = _oras_from_report_and_events(report, events)
    top_k = int(rr.get("top_k") or 12)
    pool, ret_note = _build_evidence_pool(report, events, ora_codes, top_k=top_k)
    if len(pool) < 2:
        report["rag_remediation_outline"] = {
            "used": False,
            "reason": "insufficient_evidence_pool",
            "retrieval_note": ret_note,
            "pool_size": len(pool),
        }
        return

    catalog = [
        {
            "i": i,
            "source": p.get("source"),
            "ora_code": p.get("ora_code") or "",
            "preview": (p.get("text") or "")[:520],
        }
        for i, p in enumerate(pool)
    ]
    root_pat = str((report.get("root_cause") or {}).get("pattern") or "")

    try:
        raw = call_gemini_rag_remediation_pick(
            incident_id=incident_id,
            observed_codes=ora_codes[:40],
            root_pattern=root_pat,
            catalog=catalog,
            model=str(llm.get("model") or "gemini-2.0-flash"),
            timeout_sec=int(llm.get("timeout_sec") or 25),
        )
    except LlmClientError as e:
        report["rag_remediation_outline"] = {
            "used": False,
            "reason": str(e),
            "pool_size": len(pool),
            "retrieval_note": ret_note,
        }
        return
    except Exception as e:
        report["rag_remediation_outline"] = {
            "used": False,
            "reason": f"rag_pick_failed:{e}",
            "pool_size": len(pool),
            "retrieval_note": ret_note,
        }
        return

    indices, summary = _validate_indices(raw, len(pool))
    expanded = [pool[i] for i in indices]

    report["rag_remediation_outline"] = {
        "used": True,
        "summary": summary,
        "indices": indices,
        "items": expanded,
        "pool_size": len(pool),
        "retrieval_note": ret_note,
    }
