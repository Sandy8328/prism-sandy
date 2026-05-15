"""
NO_MATCH grounded LLM advisory: model may only cite KB command bundle IDs;
command text is expanded server-side from the knowledge graph / report fixes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from src.knowledge_graph.graph import get_commands_for_ora
from src.agent.llm_client import LlmClientError, call_gemini_no_match_grounded
from src.agent.llm_policy import validate_no_match_grounded

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

_PROMPT_VERSION = "no_match_grounded_v1"

_CODE_TOKEN = re.compile(
    r"\b(?:ORA|CRS|IPC|TNS|DRG|OCR|ONS|CLSR|EVM|CSS|CRSD|GIPC)-\d+(?::\d+)?\b",
    re.I,
)


def _load_yaml_cfg() -> dict[str, Any]:
    try:
        import yaml

        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _sanitize_id_token(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", (s or "").strip())[:80]


def _collect_oracle_codes_from_events(events: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    dup: set[str] = set()

    def add(c: str) -> None:
        u = c.strip().upper()
        if not u or u in dup:
            return
        dup.add(u)
        seen.append(u)

    for ev in events or []:
        code = str(ev.get("code") or "").strip()
        if code:
            add(code)
        for blob in (ev.get("message"), ev.get("raw"), ev.get("preview")):
            if not isinstance(blob, str) or not blob:
                continue
            for m in _CODE_TOKEN.findall(blob):
                add(m)
    return seen


def _merge_ora_codes(report: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def push(c: str | None) -> None:
        if not c:
            return
        u = str(c).strip().upper()
        if not u.startswith("ORA-"):
            return
        if u in seen:
            return
        seen.add(u)
        out.append(u)

    oc = report.get("ora_code") or {}
    push(oc.get("code"))
    for c in report.get("related_errors") or []:
        push(c)
    rca = report.get("rca_framework") or {}
    ovs = (rca.get("observed_vs_inferred") or {}).get("observed_ora_codes") or []
    for c in ovs:
        push(c)
    ps = (report.get("prism_session") or {}).get("structured_memory") or {}
    for c in ps.get("ora_codes") or []:
        push(c)
    for c in _collect_oracle_codes_from_events(events):
        if c.startswith("ORA-"):
            push(c)
    return out


def _build_event_digest(events: list[dict[str, Any]], max_n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ev in (events or [])[:max_n]:
        prev = str(ev.get("preview") or ev.get("raw") or ev.get("message") or "")[:220]
        rows.append(
            {
                "source": (ev.get("source_file") or ev.get("source_path") or "")[:120],
                "code": (ev.get("code") or "")[:64],
                "layer": (ev.get("layer") or "")[:32],
                "preview": prev,
            }
        )
    return rows


def _observed_codes_for_policy(events: list[dict[str, Any]], max_scan: int = 400) -> set[str]:
    s: set[str] = set()
    for ev in (events or [])[:max_scan]:
        for blob in (ev.get("code"), ev.get("message"), ev.get("preview"), ev.get("raw")):
            if not isinstance(blob, str):
                continue
            for m in _CODE_TOKEN.findall(blob):
                s.add(m.upper())
    return s


def build_grounding_bundle(
    report: dict[str, Any],
    events: list[dict[str, Any]] | None,
    *,
    max_digest_events: int,
) -> dict[str, Any]:
    evs = list(events or [])
    ora_list = _merge_ora_codes(report, evs)
    allowed_entries: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    for ora in ora_list:
        info = get_commands_for_ora(ora)
        cmds = [str(c).strip() for c in (info.get("commands") or []) if str(c).strip()]
        if not cmds:
            continue
        eid = f"kb_{_sanitize_id_token(ora)}"
        # Deterministic de-dupe if graph returns duplicate ORA keys
        if eid in by_id:
            continue
        entry = {
            "id": eid,
            "ora_code": ora,
            "title": (info.get("title") or "")[:500],
            "source": info.get("source") or "graph",
            "command_count": len(cmds),
            "commands": cmds,
        }
        allowed_entries.append(entry)
        by_id[eid] = entry

    for fi, fix in enumerate(report.get("fixes") or []):
        cmds = [str(c).strip() for c in (fix.get("commands") or []) if str(c).strip()]
        if not cmds:
            continue
        fid = str(fix.get("fix_id") or fi).strip() or str(fi)
        eid = f"prov_{_sanitize_id_token(fid)}_{fi}"
        entry = {
            "id": eid,
            "ora_code": "",
            "title": f"provisional_fix:{fid}"[:500],
            "source": "report_fixes",
            "command_count": len(cmds),
            "commands": cmds,
        }
        allowed_entries.append(entry)
        by_id[eid] = entry

    digest = _build_event_digest(evs, max_digest_events)
    observed = sorted(_observed_codes_for_policy(evs))
    cache_payload = {
        "prompt_version": _PROMPT_VERSION,
        "no_match_reason": (report.get("no_match_reason") or "")[:2000],
        "ora_codes": ora_list,
        "allowed": [{"id": e["id"], "commands": e["commands"]} for e in allowed_entries],
        "digest": digest,
        "total_events": len(evs),
    }
    cache_key = hashlib.sha256(
        json.dumps(cache_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return {
        "prompt_version": _PROMPT_VERSION,
        "cache_key": cache_key,
        "no_match_reason": report.get("no_match_reason") or "",
        "event_digest": digest,
        "total_events": len(evs),
        "observed_codes": observed,
        "allowed_entries": allowed_entries,
        "allowed_by_id": by_id,
    }


def _read_cache(path: Path, key: str) -> dict[str, Any] | None:
    fp = path / f"{key}.json"
    if not fp.is_file():
        return None
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(path: Path, key: str, payload: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    fp = path / f"{key}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=0)


def compute_no_match_grounded_advisory(
    report: dict[str, Any],
    events: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    cfg = _load_yaml_cfg()
    llm = cfg.get("llm") or {}
    nmg = llm.get("no_match_grounded") or {}
    if report.get("status") != "NO_MATCH":
        return {"used": False, "reason": "not_no_match"}
    if not bool(llm.get("enabled", False)):
        return {"used": False, "reason": "llm_disabled"}
    if not bool(nmg.get("enabled", False)):
        return {"used": False, "reason": "no_match_grounded_disabled"}
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return {"used": False, "reason": "no_gemini_api_key"}

    max_digest = int(nmg.get("max_digest_events", 150))
    cache_enabled = bool(nmg.get("cache_enabled", True))
    cache_dir_s = str(nmg.get("cache_dir") or "./data/.no_match_llm_cache").strip()
    cache_path = (PROJECT_ROOT / cache_dir_s.lstrip("./")).resolve()

    bundle = build_grounding_bundle(report, events, max_digest_events=max_digest)
    allowed_ids = {e["id"] for e in bundle["allowed_entries"]}
    observed_set = _observed_codes_for_policy(list(events or []))

    if cache_enabled:
        cached = _read_cache(cache_path, bundle["cache_key"])
        if isinstance(cached, dict) and cached.get("advisory"):
            adv = dict(cached["advisory"])
            adv["cache_hit"] = True
            return adv

    llm_refs = [
        {
            "id": e["id"],
            "ora_code": e["ora_code"],
            "title": e["title"],
            "source": e["source"],
            "command_count": e["command_count"],
        }
        for e in bundle["allowed_entries"]
    ]
    try:
        raw = call_gemini_no_match_grounded(
            {
                "prompt_version": bundle["prompt_version"],
                "no_match_reason": bundle["no_match_reason"],
                "observed_codes": bundle["observed_codes"],
                "event_digest": bundle["event_digest"],
                "total_events": bundle["total_events"],
                "allowed_command_refs": llm_refs,
            },
            model=str(llm.get("model") or "gemini-2.0-flash"),
            timeout_sec=int(llm.get("timeout_sec") or 20),
        )
    except LlmClientError as e:
        return {"used": False, "reason": f"llm_error:{e}", "cache_key": bundle["cache_key"]}
    except Exception as e:
        return {"used": False, "reason": f"llm_failed:{e}", "cache_key": bundle["cache_key"]}

    ok, violations, cleaned = validate_no_match_grounded(
        raw,
        allowed_ids=allowed_ids,
        observed_codes=observed_set,
    )
    materialized = _materialize(cleaned.get("recommended_command_ids") or [], bundle["allowed_by_id"])

    out = {
        "used": True,
        "cache_hit": False,
        "cache_key": bundle["cache_key"],
        "prompt_version": bundle["prompt_version"],
        "policy_passed": ok,
        "violations": violations,
        "summary": cleaned.get("summary") or "",
        "recommended_command_ids": cleaned.get("recommended_command_ids") or [],
        "materialized_commands": materialized,
        "allowed_command_count": len(allowed_ids),
    }
    if cache_enabled:
        try:
            _write_cache(cache_path, bundle["cache_key"], {"advisory": out})
        except Exception:
            pass
    return out


def _materialize(ids: list[str], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        ent = by_id.get(i)
        if not ent:
            continue
        out.append(
            {
                "id": ent["id"],
                "ora_code": ent.get("ora_code"),
                "source": ent.get("source"),
                "title": ent.get("title"),
                "commands": list(ent.get("commands") or []),
            }
        )
    return out
