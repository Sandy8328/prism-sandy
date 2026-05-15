"""
report_builder.py — Assembles the final diagnostic report.

Output structure (from input_output_contract.md):
{
  "status":          "SUCCESS" | "NO_MATCH" | "ERROR",
  "confidence":      {"score": 87.5, "label": "HIGH"},
  "ora_code":        {"code": "ORA-27072", "description": "File I/O error", "layer": "OS_TRIGGERED"},
  "root_cause":      {"pattern": "SCSI_DISK_TIMEOUT", "category": "DISK", "device": "sdb", "description": "..."},
  "causal_chain":    ["ROOT: FC_HBA_RESET", "OS: SCSI_DISK_TIMEOUT", "DB: ORA-27072"],
  "cascade":         {...} | null,
  "evidence":        [{chunk_id, log_source, timestamp, raw_text, score}, ...],
  "fixes":           [{priority, fix_id, commands, risk, requires, downtime}, ...],
  "diagnostics":     ["dmesg | grep -i 'scsi\\|sd.*FAIL'", ...],
  "related_errors":  ["ORA-15080", "ORA-00353"],
  "platform":        "LINUX",
  "hostname":        "dbhost01",
  "query_mode":      "ora_code" | "log_paste" | "natural_language",
  "processing_ms":   142,
  "no_match_reason": null | "reason string"
}
"""

from __future__ import annotations
import os
import re
import yaml
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from typing import Dict, Any
from src.knowledge_graph.graph import get_layer_for_code, get_node_info
try:
    from src.agent.packager import IncidentPackager
except ModuleNotFoundError:  # optional in minimal bundles
    IncidentPackager = None  # type: ignore[misc, assignment]

# ── Load reporting limits from settings.yaml ──────────────────────────────
_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "settings.yaml"
)
try:
    with open(_SETTINGS_PATH) as _f:
        _full_cfg = yaml.safe_load(_f)
    _rep = _full_cfg.get("reporting", {})
    EVIDENCE_MAX_CHUNKS    = _rep.get("evidence_max_chunks", 5)
    RAW_TEXT_PREVIEW_CHARS = _rep.get("raw_text_preview_chars", 300)
    _AUTO_PACKAGE_INCIDENT = bool(_rep.get("auto_package_incident", False))
except Exception:
    EVIDENCE_MAX_CHUNKS    = 5
    RAW_TEXT_PREVIEW_CHARS = 300
    _AUTO_PACKAGE_INCIDENT = False
    _full_cfg = {}

FINAL_CONFIDENCE_THRESHOLD = 85.0


def _has_authoritative_rca_from_event_analysis(event_analysis: dict | None) -> bool:
    """
    When event_correlation already finalized a strong RCA, legacy retrieval gates
    must not downgrade the report to NO_MATCH (e.g. best_pattern not in direct_pattern_ids).
    """
    if not event_analysis:
        return False
    rca_score = float(event_analysis.get("correlation_model_score") or 0.0)
    rca_status = str(event_analysis.get("root_cause_evidence_status") or "").upper()
    return rca_status in {"CONFIRMED", "LIKELY"} and rca_score >= FINAL_CONFIDENCE_THRESHOLD


def _preserve_evidence_first_rca(event_analysis: dict | None) -> bool:
    """
    Correlation-only synthetic roots that must survive legacy NO_MATCH gates
    (DB redo triangle, locator-only) — not CONFIRMED, but not UNKNOWN either.
    """
    if not event_analysis:
        return False
    rc = event_analysis.get("root_cause_candidate") or {}
    return (rc.get("root_cause") or "").strip() in {
        "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE",
        "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT",
    }


def _get_ora_info(ora_code: str) -> dict:
    """
    Generic Lookup: Fetch ORA info from Knowledge Graph.
    No hardcoded descriptions.
    """
    info = get_layer_for_code(ora_code)
    return {
        "description": info.get("description", f"Oracle error {ora_code}"),
        "layer":       info.get("layer", "UNKNOWN")
    }


def _get_pattern_desc(pattern_id: str) -> str:
    """
    Generic Lookup: Fetch OS pattern description from Knowledge Graph.
    """
    if not pattern_id:
        return ""
    if pattern_id == "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE":
        return (
            "Database redo/file I/O failure indicated by ORA-27072/00353/00312 together; "
            "lower-layer (OS/ASM/storage) evidence is not in this bundle."
        )
    if pattern_id == "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT":
        return (
            "Only locator-style ORA evidence (for example ORA-00312) is present; "
            "finalize root cause after primary fault ORAs and host/storage logs are captured."
        )
    if pattern_id == "STORAGE_FLASH_IO_OR_MEDIA_FAILURE":
        return (
            "Storage flash or media I/O failure indicated by correlated storage/cell evidence "
            "(not a generic OS pattern label)."
        )
    if pattern_id == "OS_STORAGE_PATH_FAILURE":
        return (
            "Host multipath, HBA, or disk path failure corroborated by OS-layer signals with "
            "downstream database/ASM I/O symptoms."
        )
    if pattern_id.startswith("STORAGE_") or "FLASH" in pattern_id or "CELL" in pattern_id.upper():
        node = get_node_info(pattern_id)
        if node.get("description"):
            return node["description"]
        return f"Storage-layer evidence signal: {pattern_id}"
    node = get_node_info(pattern_id)
    return node.get("description", f"Evidence pattern: {pattern_id}")


def _extract_trace_analysis(fused_results: list[dict]) -> dict | None:
    """
    Phase B: Extract structured trace insights from TRACE_* chunks.
    """
    analysis = {"process_info": {}, "call_stack": [], "error_stack": []}
    found = False
    for r in fused_results:
        payload = r.get("payload", {})
        source = payload.get("log_source", "")
        if source == "TRACE_META":
            text = payload.get("raw_text", "")
            for line in text.splitlines():
                if ":" in line:
                    parts = line.split(":", 1)
                    analysis["process_info"][parts[0].strip()] = parts[1].strip()
            found = True
        elif source == "TRACE_CALL_STACK":
            analysis["call_stack"] = payload.get("raw_text", "").splitlines()[:10]
            found = True
        elif source == "TRACE_ERROR_STACK":
            analysis["error_stack"] = payload.get("raw_text", "").splitlines()[:10]
            found = True

    return analysis if found else None


def _extract_security_insights(fused_results: list[dict]) -> list[dict]:
    """
    Phase C: Extract security correlation events from evidence.
    """
    insights = []
    for r in fused_results:
        payload = r.get("payload", {})
        source = payload.get("log_source", "")
        if source in ("OS_SECURE", "DB_AUDIT"):
            insights.append({
                "source":   source,
                "event":    payload.get("sub_category", "UNKNOWN"),
                "text":     payload.get("raw_text", ""),
                "severity": payload.get("severity", "INFO"),
                "time":     payload.get("timestamp_start", "")
            })
    return insights


def _extract_hardware_health(fused_results: list[dict]) -> list[dict]:
    """
    Phase E: Extract Exadata hardware health events.
    """
    health = []
    for r in fused_results:
        payload = r.get("payload", {})
        if payload.get("category") == "HARDWARE":
            health.append({
                "source":   payload.get("log_source", "UNKNOWN"),
                "event":    payload.get("sub_category", "UNKNOWN"),
                "text":     payload.get("raw_text", ""),
                "severity": payload.get("severity", "INFO"),
                "time":     payload.get("timestamp_start", "")
            })
    return health


def _extract_trace_files(fused_results: list[dict]) -> dict | None:
    """
    Phase A: Scan top evidence chunks for trace_path fields set by alert_log_parser.
    Returns trace_files dict when found, None when no trace path is present.
    """
    for r in fused_results:
        payload = r.get("payload", {})
        trace_path = payload.get("trace_path", "")
        if trace_path:
            incident_id   = payload.get("incident_id", "")
            incident_path = payload.get("incident_path", "")
            action = "Review trace file for call stack and error context."
            if incident_id:
                action = f"Run: adrci> show incident -p {incident_id}"
            return {
                "trace_path":    trace_path,
                "incident_id":   incident_id or None,
                "incident_path": incident_path or None,
                "action":        action,
            }
    return None


def _normalized_session_source_tokens(normalized_events: list[dict] | None) -> set[str]:
    """Filenames/paths/log_source labels from evidence-first normalized events (upload turns)."""
    out: set[str] = set()
    for ev in normalized_events or []:
        if not isinstance(ev, dict):
            continue
        for k in ("source_file", "source_path", "log_source"):
            v = str(ev.get(k) or "").strip()
            if not v:
                continue
            out.add(v)
            base = os.path.basename(v.replace("\\", "/"))
            if base and base != v:
                out.add(base)
    return out


def _solicitation_already_covered(
    suggestion: str,
    provided_sources: set[str],
    normalized_events: list[dict] | None,
) -> bool:
    """
    True when retrieval evidence or session uploads already satisfy this checklist line.
    Evidence-first runs often have empty fused evidence; then we use normalized_events only.
    """
    n_events = list(normalized_events or [])
    tokens: set[str] = {str(x).strip() for x in provided_sources if str(x).strip()}
    tokens |= _normalized_session_source_tokens(n_events)
    tokens_upper = {t.upper() for t in tokens}

    sug = suggestion.strip()
    sug_u = sug.upper()
    hay = " | ".join(sorted(tokens_upper))
    prev_blob = ""
    for ev in n_events[:500]:
        for k in ("preview", "raw", "message"):
            blob = ev.get(k)
            if isinstance(blob, str) and blob:
                prev_blob += blob[:500].upper() + "\n"
    scan = hay + "\n" + prev_blob

    # ASM alert log (upload may be asm.log, +ASM path in preview, diag/asm, etc.)
    if "ASM ALERT" in sug_u or sug_u == "ASM ALERT LOG":
        if re.search(r"(DIAG/ASM|DIAG\\ASM|\+ASM|ASM/TRACE|ALERT_.*\+ASM|ASM.*ALERT)", scan, re.I):
            return True
        for ev in n_events:
            fn = str(ev.get("source_file") or "").lower()
            sp = str(ev.get("source_path") or "").lower()
            layer = str(ev.get("layer") or "").upper()
            if layer == "ASM" and (fn.endswith(".log") or "alert" in fn or "trace" in fn):
                return True
            if "asm" in fn and fn.endswith(".log"):
                return True
            if "asm" in sp and (".log" in sp or "alert" in sp or "trace" in sp):
                return True

    # OS / syslog
    if "MESSAGES" in sug_u or "DMESG" in sug_u or "SYSLOG" in sug_u:
        if re.search(r"(MESSAGES|DMESG|SYSLOG|/VAR/LOG)", scan, re.I):
            return True

    # Grid / CRS checklist
    if "CRSCTL" in sug_u or "OCRCHECK" in sug_u:
        if re.search(r"(CRS_|CRSD|CRS\.LOG|GI_|GRID|OCR|EVMD|CSSD)", scan, re.I):
            return True

    # Generic token overlap (retrieval log_source labels)
    for ps in tokens_upper:
        if len(ps) < 4:
            continue
        if ps in sug_u or sug_u in ps:
            return True
    return False


def _get_solicitation(
    layer: str,
    provided_sources: set[str],
    normalized_events: list[dict] | None = None,
) -> list[str]:
    """
    Chatbot Logic: Suggest missing logs based on the identified problem layer.
    """
    requests = {
        "OS_TRIGGERED": ["/var/log/messages", "dmesg", "multipath -ll", "iostat -xz"],
        "ASM":          ["ASM alert log", "asmcmd lsdg", "kfod status"],
        "CLUSTER":      ["crsctl check crs", "ocrcheck", "alert.log from other nodes"],
        "NETWORK":      ["lsnrctl status", "netstat -anp", "ping/traceroute"],
        "MEMORY":       ["/proc/meminfo", "ipcs -ma", "slabtop"],
    }

    suggested = requests.get(layer, [])
    final: list[str] = []
    for s in suggested:
        if not _solicitation_already_covered(s, provided_sources, normalized_events):
            final.append(s)
    return final


def _follow_up_from_mode(mode: str) -> str:
    """Targeted follow-up question for low-evidence / no-match flows."""
    if mode == "log_paste":
        return (
            "I could not confirm an incident from this snippet. Please upload related files "
            "from the same time window: alert.log, /var/log/messages, and any trace file."
        )
    if mode == "ora_code":
        return (
            "I found the ORA code, but not enough OS/infra evidence. Please share alert.log "
            "around the timestamp plus OS logs (messages/dmesg/iostat or OSWatcher)."
        )
    return (
        "I need more evidence to diagnose accurately. Please upload alert.log, syslog/messages, "
        "and trace snippets from the same incident window."
    )


def _missing_evidence_from_mode(mode: str) -> list[str]:
    """Checklist to explain why a diagnosis is not yet final."""
    if mode == "ora_code":
        return [
            "Alert log around the error timestamp (10-20 minutes window)",
            "OS logs from same window (/var/log/messages or dmesg)",
            "Host and platform confirmation for the affected node",
        ]
    if mode == "log_paste":
        return [
            "Matching host-level logs from the same incident window",
            "Trace file or ADR incident snippet linked to this ORA",
            "At least one corroborating source (DB + OS/infra)",
        ]
    return [
        "Raw incident logs (alert.log, syslog/messages, trace)",
        "Exact hostname/platform and approximate incident time",
        "Correlated DB + OS/infra evidence for the same event",
    ]


def _has_cross_source_evidence(fused_results: list[dict]) -> bool:
    """True when evidence includes at least two non-synthetic log sources."""
    real_sources = set()
    for r in fused_results:
        src = ((r.get("payload") or {}).get("log_source") or "").upper()
        if not src or src in {"DIRECT_INPUT", "DIRECT_ORA"}:
            continue
        real_sources.add(src)
    return len(real_sources) >= 2


def _has_multi_layer_corroboration(parsed_input: dict) -> bool:
    """
    Require corroboration across at least 2 layers (DB/OS/INFRA/RDBMS/STORAGE)
    observed in the uploaded/pasted evidence itself.
    """
    layers = set(parsed_input.get("observed_layers") or [])
    return len(layers) >= 2


def _needs_infra_confirmation(parsed_input: dict, best_pattern: str) -> bool:
    """
    Storage-path incidents should not finalize without infra/cell/storage evidence.
    """
    storage_patterns = {
        "FC_HBA_RESET",
        "SCSI_DISK_TIMEOUT",
        "MULTIPATH_ALL_PATHS_DOWN",
        "IO_QUEUE_TIMEOUT",
        "EXA_FLASH_FAIL",
        "EXA_CELL_IO_ERROR",
        "STORAGE_FLASH_IO_OR_MEDIA_FAILURE",
    }
    storage_oras = {"ORA-27072", "ORA-15080", "ORA-15130", "ORA-15081", "ORA-00353"}
    oras_seen = set(parsed_input.get("all_ora_codes") or [])
    is_storage_path = best_pattern in storage_patterns or bool(storage_oras & oras_seen)
    if not is_storage_path:
        return False
    obs = set(parsed_input.get("observed_layers") or [])
    if "INFRA" in obs or "STORAGE" in obs:
        return False
    return True


def build_report(
    parsed_input: dict,
    best_candidate: dict | None,
    root_cause_chain: dict | None,
    fused_results: list[dict],
    cascades: list[dict],
    processing_ms: float = 0,
    event_analysis: dict | None = None,
) -> dict:
    """
    Assemble the final diagnostic report.
    """
    from src.agent.event_correlation import (
        annotate_fix_command_categories,
        build_event_correlation_analysis,
        downgrade_rca_for_no_match,
    )

    if event_analysis is None:
        event_analysis = build_event_correlation_analysis(
            parsed_input, fused_results, root_cause_chain, best_candidate
        )

    # ── NO MATCH case ───────────────────────────────────────────
    generic_only = bool(best_candidate and best_candidate.get("pattern_id") == "ORA_ANY_GENERIC")
    low_evidence_generic = generic_only and not _has_cross_source_evidence(fused_results)
    direct_pattern_ids = set(parsed_input.get("direct_pattern_ids") or [])
    best_pattern = (best_candidate or {}).get("pattern_id", "")
    not_in_uploaded_evidence = bool(
        parsed_input.get("mode") == "log_paste"
        and direct_pattern_ids
        and best_pattern
        and best_pattern not in direct_pattern_ids
    )
    below_final_threshold = bool(
        best_candidate and float(best_candidate.get("score", 0.0)) < FINAL_CONFIDENCE_THRESHOLD
    )
    no_multilayer_corroboration = not _has_multi_layer_corroboration(parsed_input)
    missing_infra_for_storage = _needs_infra_confirmation(parsed_input, best_pattern)

    has_authoritative_rca = _has_authoritative_rca_from_event_analysis(event_analysis)

    if (
        not has_authoritative_rca
        and not _preserve_evidence_first_rca(event_analysis)
        and (
        not best_candidate
        or best_candidate.get("label") == "NO_MATCH"
        or low_evidence_generic
        or not_in_uploaded_evidence
        or no_multilayer_corroboration
        or missing_infra_for_storage
        or below_final_threshold
    )
    ):
        reason = "No OS-level error pattern matched with sufficient confidence."
        if generic_only:
            reason = (
                "Only a generic ORA signal was detected. This is not enough to confirm "
                "root cause; please provide correlated DB + OS/infra logs."
            )
        elif not_in_uploaded_evidence:
            reason = (
                "Top matched pattern was not found in the uploaded/pasted evidence. "
                "Please upload logs from the same incident window to validate correlation."
            )
        elif below_final_threshold:
            reason = (
                f"Current confidence is {best_candidate.get('score', 0)}%, below the "
                f"finalization threshold of {int(FINAL_CONFIDENCE_THRESHOLD)}%. "
                "Please upload more correlated logs from the same host/time window."
            )
        elif missing_infra_for_storage:
            reason = (
                "Storage-path incident still needs infra evidence (cell/storage/OSWatcher/ExaWatcher) "
                "to confirm root cause before finalizing."
            )
        elif no_multilayer_corroboration:
            reason = (
                "Final answer requires corroboration across multiple layers "
                "(for example DB + OS, or DB + INFRA)."
            )
        elif parsed_input["primary_ora"] and not root_cause_chain:
            reason = (f"{parsed_input['primary_ora']} is not an OS-triggered error, "
                      "or insufficient log context was provided.")
        ora_info = {}
        if parsed_input["primary_ora"]:
            ora_info = {
                "code": parsed_input["primary_ora"],
                **_get_ora_info(parsed_input["primary_ora"]),
            }
        provisional_fixes = []
        if root_cause_chain:
            for i, fix in enumerate(root_cause_chain.get("fixes", [])):
                provisional_fixes.append({
                    "priority":          fix.get("priority", i + 1),
                    "fix_id":            fix.get("fix_id", ""),
                    "commands":          fix.get("commands", []),
                    "risk":              fix.get("risk", "MEDIUM"),
                    "requires":          fix.get("requires", "root"),
                    "downtime_required": fix.get("downtime_required", False),
                })
        provisional_fixes = annotate_fix_command_categories(provisional_fixes)
        rca_no = downgrade_rca_for_no_match(dict(event_analysis), reason)
        rca_no["diagnostics_to_run"] = []
        rca_no["observed_vs_inferred"] = {
            "observed_ora_codes": list(parsed_input.get("all_ora_codes") or []),
            "inferred_codes_not_allowed_in_output": [],
        }
        return {
            "status":          "NO_MATCH",
            "confidence":      {
                "score": round(float((best_candidate or {}).get("score", 0.0)), 1),
                "label": "NO_MATCH",
                "breakdown": (best_candidate or {}).get("breakdown", {}),
                "retrieval_note": (
                    "This score/label is retrieval fusion, not RCA correlation. "
                    "See rca_framework.correlation_model_score and root_cause_evidence_status."
                ),
                "correlation_model_score": rca_no.get("correlation_model_score"),
                "root_cause_evidence_status": rca_no.get("root_cause_evidence_status"),
            },
            "ora_code":        ora_info,
            "root_cause":      None,
            "causal_chain":    [],
            "cascade":         None,
            "evidence":        [],
            "fixes":           provisional_fixes,
            "rca_framework":   rca_no,
            "provisional_root_cause": (
                {
                    "pattern":     (root_cause_chain or {}).get("root_pattern", ""),
                    "category":    (root_cause_chain or {}).get("category", ""),
                    "severity":    (root_cause_chain or {}).get("severity", ""),
                    "description": _get_pattern_desc((root_cause_chain or {}).get("root_pattern", "")),
                }
                if root_cause_chain else None
            ),
            "diagnostics":     [],
            "related_errors":  [
                c for c in (parsed_input.get("all_ora_codes") or [])
                if c != parsed_input.get("primary_ora")
            ],
            "trace_files":     None,
            "trace_analysis":  None,
            "security_insights": [],
            "hardware_health": [],
            "platform":        parsed_input["platform"],
            "hostname":        parsed_input["hostname"],
            "query_mode":      parsed_input["mode"],
            "query":           (parsed_input.get("raw_input") or "")[:20000],
            "processing_ms":   round(processing_ms, 1),
            "no_match_reason": reason,
            "follow_up_question": _follow_up_from_mode(parsed_input["mode"]),
            "missing_evidence": _missing_evidence_from_mode(parsed_input["mode"]),
            "prism": {
                "signal": "No reliable incident signal detected",
                "correlation": "Insufficient cross-source evidence",
                "root_cause": "Undetermined",
                "action_plan": _follow_up_from_mode(parsed_input["mode"]),
                "confidence": "NO_MATCH",
            },
        }

    if not best_candidate and (
        has_authoritative_rca or _preserve_evidence_first_rca(event_analysis)
    ):
        rc = (event_analysis or {}).get("root_cause_candidate") or {}
        root_l = (rc.get("root_cause") or "UNKNOWN").strip()
        sc = float(event_analysis.get("correlation_model_score") or 0.0)
        best_candidate = {
            "pattern_id": root_l,
            "score": sc,
            "label": "HIGH" if rc.get("status") == "CONFIRMED" else "MEDIUM",
            "breakdown": {"correlation_model_score": sc},
        }

    # ── Build evidence list ─────────────────────────────────────
    evidence = []
    for r in fused_results[:EVIDENCE_MAX_CHUNKS]:
        payload = r.get("payload", {})
        evidence.append({
            "chunk_id":    payload.get("chunk_id", r.get("chunk_id")),
            "log_source":  payload.get("log_source", ""),
            "timestamp":   payload.get("timestamp_start", ""),
            "hostname":    payload.get("hostname", ""),
            "severity":    payload.get("severity", ""),
            "raw_text":    (payload.get("raw_text", "")[:RAW_TEXT_PREVIEW_CHARS] + "...")
                           if len(payload.get("raw_text","")) > RAW_TEXT_PREVIEW_CHARS
                           else payload.get("raw_text",""),
            "rrf_score":   round(r.get("rrf_score", 0), 4),
        })

    rca_root = (event_analysis or {}).get("root_cause_candidate") or {}
    rca_label = (rca_root.get("root_cause") or "").strip()
    pattern_id = (
        rca_label
        or (root_cause_chain or {}).get("root_pattern")
        or best_candidate.get("pattern_id", "")
    )
    device       = best_candidate.get("device", "")
    ora_code     = (root_cause_chain or {}).get("causal_chain", [""])[-1]
    if ora_code.startswith("DB: "):
        ora_code = ora_code[4:]
    if not ora_code:
        ora_code = parsed_input["primary_ora"]

    # ── Build fixes ─────────────────────────────────────────────
    fixes = []
    if root_cause_chain:
        for i, fix in enumerate(root_cause_chain.get("fixes", [])):
            fixes.append({
                "priority":         fix.get("priority", i+1),
                "fix_id":           fix.get("fix_id", ""),
                "commands":         fix.get("commands", []),
                "risk":             fix.get("risk", "MEDIUM"),
                "requires":         fix.get("requires", "root"),
                "downtime_required":fix.get("downtime_required", False),
            })
    observed_ora = _collect_observed_ora_set(parsed_input, root_cause_chain)
    db_layer_fixes = _build_db_layer_fixes(observed_ora)
    infra_layer_fixes = _build_infra_layer_fixes(
        pattern_id,
        parsed_input.get("observed_layers") or [],
    )
    fixes = _merge_layered_fixes(fixes, db_layer_fixes, infra_layer_fixes)
    fixes = annotate_fix_command_categories(fixes)

    # ── Diagnostic commands ─────────────────────────────────────
    diagnostics = _get_diagnostic_commands(pattern_id)

    # ── Cascade info ────────────────────────────────────────────
    cascade_info = None
    if cascades:
        top_cascade = cascades[0]
        if parsed_input.get("mode") != "log_paste" or top_cascade["root_pattern"] == pattern_id:
            cascade_info = {
                "cascade_id":   top_cascade["cascade_id"],
                "root_pattern": top_cascade["root_pattern"],
                "sequence":     top_cascade["sequence"],
                "match_pct":    top_cascade["match_pct"],
                "note":         ("Multiple errors detected — this appears to be a cascade. "
                                f"Root cause: {top_cascade['root_pattern']}")
            }

    # ── Solicitation (Chatbot Guidance) ─────────────────────────
    provided_sources = {e["log_source"] for e in evidence}
    solicitation = _get_solicitation(
        (root_cause_chain or {}).get("category") or _get_ora_info(ora_code)["layer"],
        provided_sources,
        parsed_input.get("normalized_events"),
    )

    # ── Final Report Assembly ───────────────────────────────────
    report = {
        "status":     "SUCCESS",
        "confidence": {
            "score": best_candidate["score"],
            "label": best_candidate["label"],
            "breakdown": best_candidate.get("breakdown", {}),
        },
        "ora_code": {
            "code":        ora_code,
            **_get_ora_info(ora_code),
        },
        "root_cause": {
            "pattern":     pattern_id,
            "category":    (root_cause_chain or {}).get("category", ""),
            "severity":    (root_cause_chain or {}).get("severity", ""),
            "device":      device,
            "description": _get_pattern_desc(pattern_id),
        },
        "causal_chain":   (root_cause_chain or {}).get("causal_chain", [pattern_id]),
        "cascade":        cascade_info,
        "evidence":       evidence,
        "fixes":          fixes,
        "diagnostics":    diagnostics,
        "solicitation":   solicitation,
        "related_errors": [
            c for c in (parsed_input.get("all_ora_codes") or [])
            if c != ora_code
        ],
        "trace_files":    _extract_trace_files(fused_results),
        "trace_analysis": _extract_trace_analysis(fused_results),
        "security_insights": _extract_security_insights(fused_results),
        "hardware_health": _extract_hardware_health(fused_results),
        "platform":       parsed_input["platform"],
        "hostname":       parsed_input["hostname"],
        "query_mode":     parsed_input["mode"],
        "processing_ms":  round(processing_ms, 1),
        "no_match_reason":None,
        "follow_up_question": "",
    }

    rca_fw = dict(event_analysis)
    rca_fw["diagnostics_to_run"] = diagnostics
    rca_fw["observed_vs_inferred"] = {
        "observed_ora_codes": list(parsed_input.get("all_ora_codes") or []),
        "inferred_codes_not_allowed_in_output": [],
    }
    report["rca_framework"] = rca_fw

    preserved_rca = _preserve_evidence_first_rca(event_analysis) and not has_authoritative_rca
    if preserved_rca:
        report["status"] = "NEEDS_MORE_INFO"
        report["confidence"]["score"] = float(
            event_analysis.get("correlation_model_score") or report["confidence"]["score"] or 0.0
        )
        report["confidence"]["label"] = "MEDIUM"
        report["confidence"]["retrieval_note"] = (
            "Evidence-first correlation produced a scoped hypothesis (see rca_framework.root_cause_candidate); "
            "not a CONFIRMED RCA — add OS/ASM/storage/network logs per additional_evidence_needed."
        )

    if has_authoritative_rca:
        report["confidence"]["retrieval_note"] = (
            "Top-level score/label reflect the evidence-first correlation model "
            f"(status={rca_fw.get('root_cause_evidence_status')}); retrieval fusion was not used for RCA."
        )
        report["confidence"]["label"] = "HIGH" if rca_fw.get("root_cause_evidence_status") == "CONFIRMED" else "MEDIUM"
        report["confidence"]["score"] = float(rca_fw.get("correlation_model_score") or report["confidence"]["score"])
    elif not preserved_rca:
        report["confidence"]["retrieval_note"] = (
            "Score/label above are from retrieval fusion (BM25/semantic/temporal), "
            "not the RCA correlation model."
        )
    report["confidence"]["correlation_model_score"] = rca_fw.get("correlation_model_score")
    report["confidence"]["root_cause_evidence_status"] = rca_fw.get("root_cause_evidence_status")

    # PRISM-formatted view for consistent incident reporting.
    safe_action = "Run diagnostic commands to collect more evidence."
    if report.get("fixes") and report["fixes"][0].get("commands"):
        fx0 = report["fixes"][0]
        cat0 = fx0.get("command_category", "")
        if cat0 == "DESTRUCTIVE_DBA_APPROVAL_REQUIRED":
            safe_action = (
                "Follow layered remediation direction in rca_framework "
                "(stabilize storage/OS before any destructive recovery)."
            )
        elif cat0 == "HIGH_RISK_REMEDIATION":
            safe_action = (
                "HIGH_RISK remediation present — review full bundle and backup/redo posture before execution."
            )
        else:
            safe_action = fx0["commands"][0]
    report["prism"] = {
        "signal": f"{report['ora_code'].get('code') or report['root_cause'].get('pattern')}",
        "correlation": " -> ".join(report.get("causal_chain", [])) if report.get("causal_chain") else "N/A",
        "root_cause": report["root_cause"].get("pattern", ""),
        "action_plan": safe_action,
        "confidence": f"{report['confidence']['label']} ({report['confidence']['score']}%)",
    }

    # ── Phase D/F: Optional incident packaging (off by default; may contain sensitive paths) ──
    if _AUTO_PACKAGE_INCIDENT and IncidentPackager is not None:
        try:
            packager = IncidentPackager(config_path=_SETTINGS_PATH)
            html_report = generate_html_report(report)
            trace_paths = []
            if report.get("trace_files"):
                trace_paths = [report["trace_files"]["trace_path"]]

            pkg_path = packager.create_package(report, trace_files=trace_paths, html_content=html_report)
            if pkg_path:
                report["package_info"] = packager.get_package_info(pkg_path)
            else:
                report["package_info"] = None
        except Exception:
            report["package_info"] = None
    else:
        report["package_info"] = None

    return report



def _get_diagnostic_commands(pattern_id: str) -> list[str]:
    """Return diagnostic commands to confirm a pattern."""
    diag_map = {
        "SCSI_DISK_TIMEOUT":        ["dmesg | grep -i 'scsi\\|sd.*FAIL\\|I/O error' | tail -20",
                                     "cat /var/log/messages | grep 'kernel.*sd.*FAIL' | tail -20"],
        "FC_HBA_RESET":             ["grep qla2xxx /var/log/messages | tail -20",
                                     "systool -c fc_host -v | grep -i 'port_state\\|speed'"],
        "MULTIPATH_ALL_PATHS_DOWN": ["multipath -ll | grep -E 'fail|0:0'",
                                     "multipathd show paths"],
        "OS_STORAGE_PATH_FAILURE": [
            "multipath -ll",
            "dmesg | tail -80",
            "cat /var/log/messages | tail -120",
        ],
        "FILESYSTEM_ARCH_FULL":     ["df -h /arch",
                                     "du -sh /arch/* | sort -rh | head -10"],
        "OOM_KILLER_ACTIVE":        ["grep -i 'oom-killer\\|Killed process.*oracle' /var/log/messages | tail -10",
                                     "free -h", "cat /proc/meminfo | grep -i huge"],
        "HUGEPAGES_FREE_ZERO":      ["grep HugePages /proc/meminfo",
                                     "grep -i hugepage /etc/sysctl.conf"],
        "SEMAPHORE_LIMIT_EXHAUSTED":["ipcs -ls", "sysctl kernel.sem"],
        "NTP_TIME_JUMP":            ["chronyc tracking", "timedatectl status",
                                     "chronyc sources -v"],
        "NF_CONNTRACK_FULL":        ["sysctl net.nf_conntrack_max",
                                     "cat /proc/sys/net/netfilter/nf_conntrack_count"],
        "BONDING_FAILOVER_EVENT":   ["cat /proc/net/bonding/bond0",
                                     "ip link show bond0"],
        "SELINUX_BLOCKING":         ["getenforce",
                                     "ausearch -c oracle --raw | tail -20"],
        "NFS_MOUNT_TIMEOUT":        ["mount | grep nfs",
                                     "showmount -e <nfs_server>",
                                     "df -h | grep nfs"],
        "ISCSI_SESSION_FAIL":       ["iscsiadm -m session",
                                     "iscsiadm -m session -P 3"],
        "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE": [
            "tail -500 $ORACLE_BASE/diag/rdbms/*/*/trace/alert*.log",
            "dmesg | tail -80",
            "multipath -ll",
        ],
        "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT": [
            "tail -200 $ORACLE_BASE/diag/rdbms/*/*/trace/alert*.log",
            "adrci exec='show homes'",
        ],
    }
    return diag_map.get(pattern_id, [
        f"grep -i '{pattern_id.lower().replace('_', '\\|')}' /var/log/messages | tail -20",
        "dmesg | tail -30",
    ])


def _collect_observed_ora_set(parsed_input: dict, root_cause_chain: dict | None) -> set[str]:
    observed = set(parsed_input.get("all_ora_codes") or [])
    for step in (root_cause_chain or {}).get("causal_chain", []):
        if isinstance(step, str) and "ORA-" in step:
            for token in step.replace(":", " ").split():
                if token.startswith("ORA-"):
                    observed.add(token.strip())
    return observed


def _build_db_layer_fixes(observed_ora: set[str]) -> list[dict]:
    fixes: list[dict] = []
    db_cmds: list[str] = []
    if "ORA-00312" in observed_ora or "ORA-00353" in observed_ora:
        db_cmds.extend([
            "sqlplus / as sysdba",
            "SELECT group#, status, archived, members FROM v$log ORDER BY group#;",
            "SELECT * FROM v$logfile ORDER BY group#;",
            "ALTER SYSTEM CHECK DATAFILES;",
        ])
    if "ORA-27072" in observed_ora:
        db_cmds.extend([
            "adrci exec='show incident -mode detail'",
            "tail -200 $ORACLE_BASE/diag/rdbms/*/*/trace/alert*.log",
        ])
    if "ORA-15130" in observed_ora or "ORA-15080" in observed_ora or "ORA-15081" in observed_ora:
        db_cmds.extend([
            "asmcmd lsdg",
            "sqlplus / as sysasm",
            "SELECT name, state, type, total_mb, free_mb FROM v$asm_diskgroup;",
        ])
    if db_cmds:
        fixes.append({
            "priority": 1,
            "fix_id": "DB_LAYER_RECOVERY_VALIDATION",
            "commands": list(dict.fromkeys(db_cmds)),
            "risk": "MEDIUM",
            "requires": "oracle",
            "downtime_required": False,
        })
    return fixes


def _build_infra_layer_fixes(root_pattern: str, observed_layers: list[str]) -> list[dict]:
    infra_patterns = {"EXA_FLASH_FAIL", "EXA_CELL_IO_ERROR", "STORAGE_FLASH_IO_OR_MEDIA_FAILURE"}
    ol = set(observed_layers or [])
    if "INFRA" not in ol and "STORAGE" not in ol and root_pattern not in infra_patterns:
        return []
    cmds = [
        "cellcli -e list celldisk attributes name,status,errors",
        "cellcli -e list griddisk attributes name,asmmodestatus,asmdeactivationoutcome",
        "cellcli -e list flashcachecontent where status != 'normal'",
        "exachk -a || true",
    ]
    return [{
        "priority": 1,
        "fix_id": "INFRA_LAYER_STORAGE_VALIDATION",
        "commands": cmds,
        "risk": "HIGH",
        "requires": "root",
        "downtime_required": False,
    }]


def _merge_layered_fixes(base_fixes: list[dict], db_fixes: list[dict], infra_fixes: list[dict]) -> list[dict]:
    merged = []
    # Infra first for storage-backed incidents, then OS/base, then DB validation.
    for group in (infra_fixes, base_fixes, db_fixes):
        for f in group:
            merged.append(f)
    out = []
    seen = set()
    for i, fix in enumerate(merged, start=1):
        key = fix.get("fix_id", f"fix_{i}")
        if key in seen:
            continue
        seen.add(key)
        row = dict(fix)
        row["priority"] = i
        out.append(row)
    return out


def format_report_text(report: dict) -> str:
    """Format report as human-readable text for CLI/Streamlit display."""
    lines = []
    sep = "═" * 60

    lines.append(sep)
    lines.append("  ORACLE DBA DIAGNOSTIC REPORT")
    lines.append(sep)
    lines.append(f"  Status:     {report['status']}")
    lines.append(f"  Confidence: {report['confidence']['label']} ({report['confidence']['score']}%)")
    lines.append(f"  Platform:   {report['platform']}  |  Host: {report['hostname'] or 'unknown'}")
    lines.append(f"  Query Mode: {report['query_mode']}")
    lines.append("")

    if report["status"] == "NO_MATCH":
        lines.append(f"  ⚠ {report['no_match_reason']}")
        _append_rca_framework_text(lines, report.get("rca_framework"))
        lines.append(sep)
        return "\n".join(lines)

    ora = report.get("ora_code", {})
    if ora.get("code"):
        lines.append(f"  ORA Code:   {ora['code']} — {ora.get('description','')}")
        lines.append(f"  Layer:      {ora.get('layer','')}")
        lines.append("")

    rc = report.get("root_cause", {})
    lines.append("  ROOT CAUSE")
    lines.append(f"  Pattern:    {rc.get('pattern','')}")
    lines.append(f"  Category:   {rc.get('category','')}  |  Severity: {rc.get('severity','')}")
    if rc.get("device"):
        lines.append(f"  Device:     {rc['device']}")
    lines.append(f"  Desc:       {rc.get('description','')}")
    lines.append("")

    chain = report.get("causal_chain", [])
    if chain:
        lines.append("  CAUSAL CHAIN")
        for step in chain:
            lines.append(f"    → {step}")
        lines.append("")

    cascade = report.get("cascade")
    if cascade:
        lines.append("  ⚡ CASCADE DETECTED")
        lines.append(f"    {cascade['note']}")
        lines.append(f"    Sequence: {' → '.join(cascade['sequence'])}")
        lines.append("")

    fixes = report.get("fixes", [])
    if fixes:
        lines.append("  FIX COMMANDS")
        for fix in fixes:
            lines.append(f"  [{fix['priority']}] {fix['fix_id']}  "
                        f"[risk={fix['risk']} requires={fix['requires']}]")
            for cmd in fix["commands"]:
                lines.append(f"      $ {cmd}")
        lines.append("")

    diag = report.get("diagnostics", [])
    if diag:
        lines.append("  DIAGNOSTIC COMMANDS (run to confirm)")
        for cmd in diag:
            lines.append(f"    $ {cmd}")
        lines.append("")

    related = report.get("related_errors", [])
    if related:
        lines.append(f"  RELATED ORA CODES: {', '.join(related)}")
        lines.append("")

    bd = report["confidence"].get("breakdown", {})
    if bd:
        lines.append(f"  Score breakdown: keyword={bd.get('keyword',0)} "
                    f"bm25={bd.get('bm25',0)} "
                    f"dense={bd.get('dense',0)} "
                    f"temporal={bd.get('temporal',0)}")

    _append_rca_framework_text(lines, report.get("rca_framework"))

    lines.append(f"  Processed in {report['processing_ms']} ms")
    lines.append(sep)
    return "\n".join(lines)


def _append_rca_framework_text(lines: list[str], rca: dict | None) -> None:
    if not rca:
        return
    lines.append("")
    lines.append("  ── RCA FRAMEWORK (evidence-first) ──")
    if rca.get("executive_summary"):
        lines.append("  1. Executive summary")
        for para in (rca["executive_summary"] or "").split(". "):
            if para.strip():
                lines.append(f"     {para.strip()}.")
    rc = rca.get("root_cause_candidate") or {}
    if rc:
        lines.append("  2. Root cause candidate")
        lines.append(f"     Root: {rc.get('root_cause','')} | Layer: {rc.get('layer','')} | Status: {rc.get('status','')}")
        lines.append(f"     Correlation model score: {rc.get('correlation_score','')}")
    cc = rca.get("cascade_chain_marked") or []
    if cc:
        lines.append("  3. Cascade chain (marked)")
        for step in cc:
            lines.append(f"     → {step}")
    ora_tbl = rca.get("observed_ora_correlation_table") or rca.get("correlated_error_table") or []
    if ora_tbl:
        lines.append("  4a. Observed ORA codes (roles)")
        for row in ora_tbl[:12]:
            lines.append(
                f"     {row.get('error','')} | {row.get('role','')} | {(row.get('meaning','') or '')[:70]}"
            )
    non_ora = rca.get("non_ora_correlated_events") or []
    if non_ora:
        lines.append("  4b. Non-ORA correlated events / patterns (not ORA codes)")
        for row in non_ora[:12]:
            ev = row.get("event") or row.get("error", "")
            lines.append(
                f"     {ev} | {row.get('role','')} | {(row.get('meaning','') or '')[:70]}"
            )
    aff = rca.get("affected_objects") or {}
    if any(aff.get(k) for k in ("devices", "diskgroups", "trace_files", "processes")):
        lines.append("  5. Affected objects (extracted)")
        if aff.get("devices"):
            lines.append(f"     devices: {', '.join(aff['devices'])}")
        if aff.get("diskgroups"):
            lines.append(f"     diskgroups: {', '.join(aff['diskgroups'])}")
        if aff.get("trace_files"):
            lines.append(f"     traces: {', '.join(aff['trace_files'][:5])}")
    if rca.get("confidence_explanation"):
        lines.append("  7. Confidence (correlation model)")
        lines.append(f"     {rca['confidence_explanation'][:400]}")
    diag = rca.get("diagnostics_to_run") or []
    if diag:
        lines.append("  8. Diagnostics to run (safe checks)")
        for cmd in diag[:8]:
            lines.append(f"     $ {cmd}")
    rd = rca.get("remediation_direction") or {}
    if rd:
        lines.append("  9. Remediation direction (layered)")
        for k, v in rd.items():
            lines.append(f"     {k}: {v}")
    need = rca.get("additional_evidence_needed") or []
    if need:
        lines.append("  10. Additional evidence")
        for n in need[:6]:
            lines.append(f"     - {n}")


def generate_html_report(report_dict: Dict[str, Any]) -> str:
    """
    Phase F: Render the report dictionary into a standalone HTML file using Jinja2.
    """
    try:
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template("report_template.html")
        return template.render(report=report_dict)
    except Exception as e:
        print(f"  [REPORT_BUILDER] Error generating HTML report: {e}")
        return f"<html><body><h1>Error generating report</h1><p>{e}</p></body></html>"
