"""Evidence-first diagnostic agent orchestrator.

`agent.py` does not decide final RCA. It only:
1) gathers input,
2) extracts normalized evidence events,
3) routes evidence to `event_correlation.py`,
4) delegates response shaping to `report_builder.py`.
"""

from __future__ import annotations
import hashlib
import os
import time
import zipfile
import yaml
import re
from pathlib import Path
from typing import Any, Dict
from collections import Counter

from src.agent.report_builder import build_report, format_report_text
from src.agent.event_correlation import build_event_correlation_analysis
from src.agent.input_parser import parse_input
from src.parsers.platform_detector import detect_platform
# ZIP ingest + graph pattern bridge live in unified_evidence (zip_evidence is safe_extract_zip only).
from src.parsers.unified_evidence import (
    extract_normalized_events_unified,
    extract_normalized_events_from_zip,
    graph_pattern_ids_from_normalized_events,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"
_cfg_cache: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is not None:
        return _cfg_cache
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _cfg_cache = yaml.safe_load(f) or {}
    except Exception:
        _cfg_cache = {}
    return _cfg_cache


def _cfg_value(*path: str, default: Any = None) -> Any:
    cur: Any = _load_config()
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return default if cur is None else cur


def _default_platform() -> str:
    return str(_cfg_value("defaults", "platform", default="UNKNOWN"))


def _maybe_persist_evidence_store(
    parsed: dict[str, Any],
    report: dict[str, Any],
    source_summary: dict[str, Any] | None,
) -> None:
    """If evidence_store.enabled, append persistence ids under report['evidence_store']."""
    if not bool(_cfg_value("evidence_store", "enabled", default=False)):
        return
    try:
        from src.persistence.evidence_store import persist_evidence_first_diagnosis

        ids = persist_evidence_first_diagnosis(
            parsed_input=parsed,
            report=report,
            source_summary=source_summary,
        )
        report["evidence_store"] = {"persisted": True, **ids}
    except Exception as e:
        report["evidence_store"] = {"persisted": False, "error": str(e)}


def _is_ora(code: str, code_type: str) -> bool:
    return code_type.upper() == "ORA" and bool(re.match(r"^ORA-\d{5}$", code.upper()))


def _stable_event_key(ev: dict[str, Any]) -> tuple:
    return (
        (ev.get("source_path") or ev.get("source_file") or "").strip(),
        int(ev.get("line_number") or 0),
        str(ev.get("timestamp") or ev.get("timestamp_raw") or ""),
        (ev.get("code") or "").strip(),
        (ev.get("raw") or "").strip(),
    )


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for ev in events or []:
        k = _stable_event_key(ev)
        if k in seen:
            continue
        seen.add(k)
        out.append(ev)
    return out


def _collect_structured_session_memory(events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build durable signal memory from normalized events (independent from merged raw caps).
    """
    ora_codes: set[str] = set()
    layers: set[str] = set()
    hosts: set[str] = set()
    devices: set[str] = set()
    diskgroups: set[str] = set()
    patterns: Counter = Counter()
    for ev in events or []:
        code = str(ev.get("code") or "").strip().upper()
        ctype = str(ev.get("code_type") or "").strip().upper()
        if _is_ora(code, ctype):
            ora_codes.add(code)
        else:
            for raw in (ev.get("raw") or "", ev.get("preview") or ""):
                for m in re.findall(r"\bORA-\d{5}\b", raw, flags=re.I):
                    ora_codes.add(m.upper())
        layer = str(ev.get("layer") or "UNKNOWN").strip().upper()
        if layer:
            layers.add(layer)
        host = str(ev.get("hostname") or ev.get("host") or "").strip()
        if host:
            hosts.add(host)
        dev = str(ev.get("device") or "").strip()
        if dev:
            devices.add(dev)
        dg = str(ev.get("diskgroup") or "").strip()
        if dg:
            diskgroups.add(dg)
        p = str(ev.get("pattern_id") or "").strip().upper()
        if p:
            patterns[p] += 1
    return {
        "ora_codes": sorted(ora_codes),
        "layers": sorted(x for x in layers if x),
        "hosts": sorted(hosts),
        "devices": sorted(devices),
        "diskgroups": sorted(diskgroups),
        "pattern_ids": [k for k, _ in patterns.most_common(20)],
    }


def _build_bundle_candidates_from_events(events: list[dict]) -> list[dict]:
    """Deterministic candidate set for advisory LLM ranking from observed events only."""
    counts = Counter(
        (e.get("code") or "").upper()
        for e in events
        if (e.get("code") or "").strip() and not str(e.get("code")).startswith("GENERIC_")
    )
    total = max(1, sum(counts.values()))
    out: list[dict[str, Any]] = []
    for code, cnt in counts.most_common(8):
        out.append({"pattern_id": code, "score": round(min(0.95, cnt / total + 0.4), 2)})
    if not out:
        out.append({"pattern_id": "NEEDS_MORE_EVIDENCE", "score": 0.5})
    return out


def _compute_llm_advisory_for_bundle(
    *,
    events: list[dict],
    incident_id: str,
    root_pattern_hint: str = "",
) -> dict:
    llm_cfg = (_cfg_value("llm", default={}) or {})
    enabled = bool(llm_cfg.get("enabled", False))
    mode = str(llm_cfg.get("mode", "off")).lower()
    if not enabled or mode == "off":
        return {"used": False, "mode": mode, "reason": "disabled"}

    candidates_raw = _build_bundle_candidates_from_events(events)
    if root_pattern_hint and all(c["pattern_id"] != root_pattern_hint for c in candidates_raw):
        candidates_raw.insert(0, {"pattern_id": root_pattern_hint, "score": 0.95})
    if not candidates_raw:
        return {"used": False, "mode": mode, "reason": "no_candidates"}

    observed_codes = sorted(
        {(e.get("code") or "").upper() for e in events if (e.get("code") or "").strip()}
    )
    observed_layers = sorted(
        {(e.get("layer") or "UNKNOWN").upper() for e in events if e.get("layer")}
    )

    try:
        from src.agent.llm_schema import CandidateHypothesis, LlmAdvisoryInput
        from src.agent.llm_client import call_gemini_advisory
        from src.agent.llm_policy import validate_llm_advisory, advisory_to_dict
    except Exception as e:
        return {"used": False, "mode": mode, "reason": f"llm_import_error: {e}"}

    candidates = [
        CandidateHypothesis(
            pattern_id=c["pattern_id"],
            score=float(c["score"]),
            supporting_codes=observed_codes[:20],
            contradicting_codes=[],
        )
        for c in candidates_raw[: int(llm_cfg.get("max_candidates", 6))]
    ]
    payload = LlmAdvisoryInput(
        incident_id=incident_id,
        candidates=candidates,
        observed_codes=observed_codes[:500],
        observed_layers=observed_layers,
        constraints={
            "must_choose_from_candidates": True,
            "no_invented_codes": True,
            "mode": mode,
        },
    )
    try:
        advisory = call_gemini_advisory(
            payload,
            model=str(llm_cfg.get("model", "gemini-1.5-pro")),
            timeout_sec=int(llm_cfg.get("timeout_sec", 20)),
        )
        ok, violations = validate_llm_advisory(
            advisory,
            allowed_candidates={c.pattern_id for c in candidates},
            allowed_codes=set(observed_codes),
            can_confirm=False,
        )
        out = advisory_to_dict(advisory, policy_ok=ok, violations=violations)
        out["used"] = True
        out["mode"] = mode
        out["model"] = str(getattr(advisory, "_used_model", "") or llm_cfg.get("model", "gemini-1.5-pro"))
        return out
    except Exception as e:
        return {"used": False, "mode": mode, "reason": f"llm_call_failed: {e}"}


def _attach_llm_advisory_to_report(
    report: dict[str, Any],
    *,
    events: list[dict[str, Any]] | None,
    incident_id: str,
) -> None:
    """Same Gemini advisory rules as AHF ZIP: config llm.* + optional API key; never overrides RCA."""
    evs = list(events if events is not None else (report.get("normalized_events") or []))
    report["llm_advisory"] = _compute_llm_advisory_for_bundle(
        events=evs,
        incident_id=incident_id,
        root_pattern_hint=(report.get("root_cause") or {}).get("pattern", ""),
    )


class OracleDiagnosticAgent:
    """
    PRISM — evidence-first Oracle diagnostic agent.

    Core RCA is deterministic (normalized events → event_correlation → report_builder).
    Optional Gemini advisory runs only when enabled in config; it does not override facts.

    Usage:
        agent = OracleDiagnosticAgent()
        agent.initialize()
        report = agent.diagnose("ORA-27072 on dbhost01")
        print(agent.format(report))
    """

    def __init__(self):
        self._initialized = False
        self._retrieval_index_available = True

    def initialize(self):
        """Best-effort BM25 index load for legacy retrieval paths; evidence-first diagnosis still runs if this fails."""
        if not self._initialized:
            try:
                from src.knowledge_graph.pattern_matcher import clear_pattern_cache

                clear_pattern_cache()
            except Exception:
                pass

            try:
                from src.retrieval.bm25_search import build_index, index_size

                n = index_size()
                if n == 0:
                    build_index()  # loads from DuckDB
                self._retrieval_index_available = True
            except Exception:
                self._retrieval_index_available = False
            self._initialized = True

    def _build_evidence_first_report(
        self,
        events: list[dict[str, Any]],
        *,
        parsed_input: dict[str, Any] | None = None,
        source_summary: dict[str, Any] | None = None,
        ingest_diagnostics: dict[str, Any] | None = None,
        processing_ms: float = 0,
        retrieval_context: dict[str, Any] | None = None,
    ) -> dict:
        parsed = dict(parsed_input or {})
        evs = _dedupe_events(events or [])
        oras = list(
            dict.fromkeys(
                (e.get("code") or "").upper()
                for e in evs
                if _is_ora((e.get("code") or ""), (e.get("code_type") or ""))
            )
        )
        observed_layers = sorted(
            {(e.get("layer") or "UNKNOWN").upper() for e in evs if (e.get("layer") or "").strip()}
        )
        if "query" not in parsed:
            parsed["query"] = ""
        if "raw_input" not in parsed:
            parsed["raw_input"] = "\n".join((e.get("raw") or e.get("preview") or "") for e in evs[:200])
        parsed["normalized_events"] = evs
        parsed["all_ora_codes"] = oras
        parsed["primary_ora"] = parsed.get("primary_ora") or (oras[0] if oras else "")
        parsed["observed_layers"] = observed_layers
        parsed["direct_pattern_ids"] = graph_pattern_ids_from_normalized_events(evs)
        parsed.setdefault("hostname", "")
        parsed.setdefault("platform", _default_platform())
        parsed.setdefault("timestamp_str", "")
        parsed.setdefault("nl_ora_hints", [])
        parsed.setdefault("mode", "log_paste")

        # Signature: (parsed_input, fused_results, root_cause_chain, best_candidate) — fused/chain unused here.
        event_analysis = build_event_correlation_analysis(parsed, [], None, None)
        corr_score = float(event_analysis.get("correlation_model_score") or 0.0)
        status_hint = str(event_analysis.get("root_cause_evidence_status") or "UNKNOWN")
        root = (event_analysis.get("root_cause_candidate") or {}).get("root_cause") or ""
        if root and root not in {"UNKNOWN", "NEEDS_MORE_INFO"} and corr_score >= 85 and status_hint in {"CONFIRMED", "LIKELY"}:
            best_candidate = {
                "pattern_id": root,
                "score": round(corr_score, 1),
                "label": "HIGH" if corr_score >= 90 else "MEDIUM",
                "breakdown": {"correlation_model_score": round(corr_score, 1)},
            }
        elif root and root not in {"UNKNOWN", "NEEDS_MORE_INFO"} and corr_score >= 50:
            best_candidate = {
                "pattern_id": root,
                "score": round(corr_score, 1),
                "label": "LOW",
                "breakdown": {"correlation_model_score": round(corr_score, 1)},
            }
        else:
            best_candidate = None

        report = build_report(
            parsed_input=parsed,
            best_candidate=best_candidate,
            root_cause_chain=None,
            fused_results=[],
            cascades=[],
            processing_ms=processing_ms,
            event_analysis=event_analysis,
        )
        report["normalized_event_count"] = len(evs)
        report["normalized_events"] = evs
        report["ingest_diagnostics"] = ingest_diagnostics or {}
        report["source_summary"] = source_summary or {}
        if retrieval_context:
            report["supporting_context"] = retrieval_context
        _maybe_persist_evidence_store(parsed, report, source_summary)
        return report

    def diagnose(
        self,
        query: str,
        ora_code: str = "",
        hostname: str = "",
        timestamp_str: str = "",
        platform: str = "",
        top_k: int | None = None,
    ) -> dict:
        """
        Run the full diagnostic pipeline against a query.

        Args:
            query:         Any input (ORA code, log paste, natural language)
            ora_code:      Override ORA code if known
            hostname:      Override hostname if known
            timestamp_str: Override timestamp if known
            platform:      Override platform if known
            top_k:         Number of chunks to retrieve (default from settings)

        Returns:
            Structured report dict (see report_builder.py for schema)
        """
        self.initialize()
        start_ms = time.time() * 1000
        top_k = top_k or int(_cfg_value("retrieval", "top_k", default=8))
        parsed = parse_input(query)
        if ora_code:
            parsed["primary_ora"] = ora_code
            if ora_code not in parsed["all_ora_codes"]:
                parsed["all_ora_codes"].insert(0, ora_code)
        if hostname:
            parsed["hostname"] = hostname
        if timestamp_str:
            parsed["timestamp_str"] = timestamp_str
        if platform:
            parsed["platform"] = platform
        events = extract_normalized_events_unified(
            query,
            source_file="pasted_input",
            source_path="pasted_input",
        )
        retrieval_note = {
            "retrieval_note": f"Legacy retrieval top_k={top_k} retained as optional supporting context only.",
            "retrieval_index_available": self._retrieval_index_available,
        }
        report = self._build_evidence_first_report(
            events,
            parsed_input=parsed,
            source_summary={"source_type": "pasted_text"},
            processing_ms=0,
            retrieval_context=retrieval_note,
        )
        report["processing_ms"] = round(time.time() * 1000 - start_ms, 1)
        dig = hashlib.sha256((query or "").encode("utf-8", errors="replace")).hexdigest()[:12]
        _attach_llm_advisory_to_report(
            report,
            events=report.get("normalized_events"),
            incident_id=f"paste_{dig}",
        )
        return report

    def diagnose_multi(
        self,
        logs: Dict[str, str],
        hostname: str = "",
        platform: str = "",
    ) -> dict:
        """
        Phase E/F: Multi-log diagnostic for the Forensic Lab.
        Processes multiple log sources and fuses them into one session.
        """
        self.initialize()
        start_ms = time.time() * 1000
        
        merged_events: list[dict[str, Any]] = []
        normalized_sources = []
        inferred_platform = platform or _default_platform()
        for name, content in (logs or {}).items():
            if not (content or "").strip():
                continue
            source_name = name or "uploaded_log"
            ev = extract_normalized_events_unified(
                content,
                source_file=source_name,
                source_path=source_name,
            )
            merged_events.extend(ev)
            normalized_sources.append(source_name)
            if inferred_platform in ("", "UNKNOWN"):
                inferred_platform = detect_platform(text=content[:3000], filename=source_name, default="UNKNOWN")

        parsed_input = parse_input("MULTI_LOG_INPUT")
        parsed_input.update(
            {
                "mode": "multi_log",
                "hostname": hostname,
                "platform": inferred_platform or _default_platform(),
                "raw_input": "",
            }
        )
        report = self._build_evidence_first_report(
            merged_events,
            parsed_input=parsed_input,
            source_summary={"sources": normalized_sources, "source_type": "multi_log"},
            processing_ms=0,
        )
        report["processing_ms"] = round(time.time() * 1000 - start_ms, 1)
        keys = "_".join(sorted(normalized_sources)[:8]) or "multi_log"
        if len(keys) > 100:
            keys = hashlib.sha256(keys.encode("utf-8", errors="replace")).hexdigest()[:16]
        _attach_llm_advisory_to_report(
            report,
            events=report.get("normalized_events"),
            incident_id=f"multi_{keys}"[:220],
        )
        return report


    @staticmethod
    def format(report: dict) -> str:
        """Format report as human-readable text."""
        return format_report_text(report)

    def diagnose_log_file(
        self,
        filepath: str,
        hostname: str = "",
        platform: str = "",
        original_filename: str = "",
    ) -> dict:
        """
        Diagnose a log file directly.
        Auto-detects log type (alert.log, /var/log/messages, errpt, dmesg).
        """
        from src.parsers.platform_detector import detect_from_filename

        with open(filepath, "r", errors="replace") as f:
            content = f.read()

        fname = original_filename or Path(filepath).name
        detected_platform = detect_from_filename(fname) or \
                           detect_platform(text=content[:2000]) or platform or _default_platform()
        body = content if len(content) <= 500_000 else content[:500_000]
        start_ms = time.time() * 1000
        events = extract_normalized_events_unified(
            body,
            source_file=fname,
            source_path=filepath,
        )
        parsed = parse_input(body)
        parsed["mode"] = "log_file"
        parsed["hostname"] = hostname
        parsed["platform"] = detected_platform
        report = self._build_evidence_first_report(
            events,
            parsed_input=parsed,
            source_summary={"source_file": fname, "source_path": filepath, "source_type": "single_file"},
            processing_ms=0,
        )
        report["processing_ms"] = round(time.time() * 1000 - start_ms, 1)
        incident = (fname or Path(filepath).name)[:200]
        _attach_llm_advisory_to_report(
            report,
            events=report.get("normalized_events"),
            incident_id=incident or "log_file",
        )
        return report

    def diagnose_ahf_zip(
        self,
        zip_path: str,
        hostname: str = "",
        platform: str = "",
        max_files: int = 120,
    ) -> dict:
        """
        Diagnose an uploaded AHF-style ZIP bundle.

        Runs bundle-level normalized extraction and one evidence-first report; per-file rows are summaries only.
        """
        self.initialize()

        if not zipfile.is_zipfile(zip_path):
            return {
                "status": "NO_MATCH",
                "no_match_reason": "Uploaded file is not a valid ZIP archive.",
                "follow_up_question": (
                    "I could not read this archive. Please upload a valid AHF ZIP "
                    "or paste alert.log/syslog snippets around the incident time."
                ),
            }

        start_ms = time.time() * 1000
        try:
            znorm = extract_normalized_events_from_zip(zip_path, max_files=max_files)
        except Exception as e:
            znorm = {
                "events": [],
                "ingest_diagnostics": {"skipped": [{"path": zip_path, "reason": str(e)}], "parsed_files": []},
            }
        zip_events = znorm.get("events") or []
        ingest = znorm.get("ingest_diagnostics") or {}

        inferred_platform = platform or "UNKNOWN"
        for ev in zip_events:
            if inferred_platform not in ("", "UNKNOWN"):
                break
            sf = (ev.get("source_file") or "")
            raw = (ev.get("raw") or ev.get("preview") or "")
            inferred_platform = detect_platform(text=raw[:2000], filename=sf, default="UNKNOWN")

        parsed = parse_input("")
        parsed["mode"] = "ahf_zip"
        parsed["hostname"] = hostname
        parsed["platform"] = inferred_platform if inferred_platform != "UNKNOWN" else (platform or _default_platform())

        report = self._build_evidence_first_report(
            zip_events,
            parsed_input=parsed,
            source_summary={"source_type": "ahf_zip", "zip_path": zip_path},
            ingest_diagnostics=ingest,
            processing_ms=0,
        )

        code_counts = Counter(
            (e.get("code") or "").strip() for e in zip_events if (e.get("code") or "").strip()
        )
        meaningful_codes = [c for c, _ in code_counts.most_common(12) if c and c != "NA" and not c.startswith("GENERIC_")]
        bundle_layers = sorted({(e.get("layer") or "UNKNOWN").upper() for e in zip_events if e.get("layer")})
        parsed_files = ingest.get("parsed_files") or []
        skipped_extract = ingest.get("skipped_from_extract") or []
        skipped_parse = ingest.get("skipped") or []

        signal_map: dict[str, Counter] = {}
        for ev in zip_events:
            key = (ev.get("source_path") or "").strip() or (ev.get("source_file") or "").strip()
            code = (ev.get("code") or "").strip()
            if key and code:
                signal_map.setdefault(key, Counter())[code] += 1
        per_file_summaries = []
        for fname in sorted(signal_map.keys()):
            sig_counter = signal_map[fname]
            per_file_summaries.append(
                {
                    "file": fname,
                    "signal_count": int(sum(sig_counter.values())),
                    "signal_codes": [c for c, _ in sig_counter.most_common(6)],
                    "kb_pattern_hits": [],
                    "kb_ora_hits": [],
                    "kb_all_hits": [],
                    "kb_hit_count": 0,
                }
            )
        report["secondary_findings"] = per_file_summaries[:50]
        report["per_file_summaries"] = per_file_summaries[:100]
        report["zip_normalized_events"] = zip_events
        report["zip_event_count"] = len(zip_events)
        report["zip_ingest_diagnostics"] = ingest
        report["zip_skipped_files"] = skipped_extract + skipped_parse
        report["zip_sources"] = sorted(signal_map.keys())
        report["bundle_summary"] = {
            "analyzed_files": len(parsed_files),
            "platform_inferred": parsed["platform"],
            "total_extracted_files": len(parsed_files) + len(skipped_parse),
            "skipped_from_extract": len(skipped_extract),
            "candidate_files_found": len(parsed_files),
            "candidate_files_processed": len(parsed_files),
            "max_files_cap": max_files,
            "bundle_layers": bundle_layers,
            "meaningful_codes": meaningful_codes,
        }
        _attach_llm_advisory_to_report(
            report,
            events=zip_events,
            incident_id=Path(zip_path).name,
        )
        report["processing_ms"] = round(time.time() * 1000 - start_ms, 1)
        return report

    def diagnose_prism_session(
        self,
        *,
        merged_text: str,
        zip_paths: list[str] | None = None,
        hostname: str = "",
        platform: str = "",
        ora_code: str = "",
        timestamp_str: str = "",
        top_k: int | None = None,
        session_incident_id: str = "",
        max_zip_files: int = 120,
    ) -> dict:
        """
        One full evidence-first pass over the entire PRISM session.

        Option C: ``merged_text`` is the concatenation of all paste/file/lab turns; each ZIP path
        is normalized and merged into the same event list so correlation sees the whole incident.
        """
        self.initialize()
        start_ms = time.time() * 1000
        top_k = top_k or int(_cfg_value("retrieval", "top_k", default=8))
        merged_text = (merged_text or "").strip()
        zip_paths = [p for p in (zip_paths or []) if p and os.path.isfile(p) and zipfile.is_zipfile(p)]

        events: list[dict[str, Any]] = []
        zip_ingests: list[dict[str, Any]] = []

        if merged_text:
            events.extend(
                extract_normalized_events_unified(
                    merged_text,
                    source_file="prism_session_merged",
                    source_path="prism_session_merged",
                )
            )

        for zp in zip_paths:
            try:
                znorm = extract_normalized_events_from_zip(zp, max_files=max_zip_files)
            except Exception as e:
                znorm = {
                    "events": [],
                    "ingest_diagnostics": {"skipped": [{"path": zp, "reason": str(e)}], "parsed_files": []},
                }
            events.extend(znorm.get("events") or [])
            zip_ingests.append({"path": zp, "ingest": znorm.get("ingest_diagnostics") or {}})

        if not events:
            return {
                "status": "NO_MATCH",
                "no_match_reason": "No evidence text or valid ZIP content to analyze in this session.",
                "follow_up_question": (
                    "Add a log paste, upload a text log, or attach an AHF-style ZIP, then run Diagnose again."
                ),
            }

        parse_blob = merged_text if merged_text else "# PRISM_SESSION zip_only\n"
        parsed = parse_input(parse_blob)
        parsed["mode"] = "prism_session"
        if ora_code:
            parsed["primary_ora"] = ora_code
            ac = list(parsed.get("all_ora_codes") or [])
            if ora_code not in ac:
                ac.insert(0, ora_code)
            parsed["all_ora_codes"] = ac
        if hostname:
            parsed["hostname"] = hostname
        if timestamp_str:
            parsed["timestamp_str"] = timestamp_str
        if platform:
            parsed["platform"] = platform

        inferred_platform = platform or parsed.get("platform") or "UNKNOWN"
        if inferred_platform in ("", "UNKNOWN"):
            for ev in events:
                raw = (ev.get("raw") or ev.get("preview") or "")
                sf = (ev.get("source_file") or "")
                inferred_platform = detect_platform(text=raw[:2000], filename=sf, default="UNKNOWN")
                if inferred_platform not in ("", "UNKNOWN"):
                    break
        if inferred_platform and inferred_platform != "UNKNOWN":
            parsed["platform"] = inferred_platform
        mem = _collect_structured_session_memory(events)
        mem_oras = list(mem.get("ora_codes") or [])
        if mem_oras:
            current_oras = list(parsed.get("all_ora_codes") or [])
            merged_oras = list(dict.fromkeys(current_oras + mem_oras))
            parsed["all_ora_codes"] = merged_oras
            if not parsed.get("primary_ora"):
                parsed["primary_ora"] = merged_oras[0]
        mem_layers = list(mem.get("layers") or [])
        if mem_layers:
            curr_layers = list(parsed.get("observed_layers") or [])
            parsed["observed_layers"] = list(dict.fromkeys(curr_layers + mem_layers))

        ingest_out: dict[str, Any] = {
            "merged_text_chars": len(merged_text),
            "zip_path_count": len(zip_paths),
            "zip_ingests": zip_ingests,
        }

        source_summary: dict[str, Any] = {
            "source_type": "prism_session",
            "includes_zip": bool(zip_paths),
            "zip_basenames": [Path(z).name for z in zip_paths][:40],
        }

        retrieval_note = {
            "retrieval_note": f"Legacy retrieval top_k={top_k} (session-wide merged input).",
            "retrieval_index_available": self._retrieval_index_available,
        }

        report = self._build_evidence_first_report(
            events,
            parsed_input=parsed,
            source_summary=source_summary,
            ingest_diagnostics=ingest_out,
            processing_ms=0,
            retrieval_context=retrieval_note,
        )
        report["processing_ms"] = round(time.time() * 1000 - start_ms, 1)
        report["prism_session"] = {
            "session_incident_id": (session_incident_id or "")[:64],
            "merged_text_chars": len(merged_text),
            "zip_files_used": len(zip_paths),
            "merged_text_capped": "# [PRISM: merged session text size cap reached;" in merged_text,
            "structured_memory": {
                "ora_codes": mem.get("ora_codes", []),
                "layers": mem.get("layers", []),
                "hosts": mem.get("hosts", []),
                "devices": mem.get("devices", []),
                "diskgroups": mem.get("diskgroups", []),
            },
        }

        inc = (session_incident_id or "").strip() or hashlib.sha256(
            (merged_text[:8000] + "|".join(zip_paths)).encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        inc = f"prism_{inc}"[:220]
        _attach_llm_advisory_to_report(
            report,
            events=report.get("normalized_events"),
            incident_id=inc,
        )
        return report


# ── Convenience function ────────────────────────────────────────

_default_agent: OracleDiagnosticAgent | None = None


def get_agent() -> OracleDiagnosticAgent:
    """Return singleton agent instance."""
    global _default_agent
    if _default_agent is None:
        _default_agent = OracleDiagnosticAgent()
        _default_agent.initialize()
    return _default_agent


def diagnose(query: str, **kwargs) -> dict:
    """One-line diagnostic API."""
    return get_agent().diagnose(query, **kwargs)
