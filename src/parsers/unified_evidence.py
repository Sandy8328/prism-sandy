"""
unified_evidence.py — Single entry to produce normalized evidence events from mixed text.

Does not perform RCA. Safe to call from agents, ZIP ingest, or tests.
"""

from __future__ import annotations

import os
import json
import re
import shutil
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

from src.parsers.normalized_event_schema import (
    dedupe_normalized_events,
    ensure_normalized_event,
)
from src.parsers.generic_evidence_parser import extract_generic_events
from src.parsers.normalized_adapters import (
    cell_entries_to_normalized_events,
    syslog_entries_to_normalized_events,
)
from src.parsers.evidence_timestamp import parse_line_timestamp
from src.parsers.zip_evidence import _tar_open_mode, safe_extract_tar, safe_extract_zip

_READ_FAIL = re.compile(
    r"Read Failed\.\s*group:(\d+)\s+disk:(\d+)\s+AU:(\d+)\s+offset:(\d+)\s+size:(\d+)",
    re.I,
)
_MIRROR = re.compile(
    r"mirror side\s+(\d+)\s+of\s+virtual extent\s+(\d+)\s+logical extent\s+(\d+)\s+of\s+file\s+(\d+)\s+in\s+group\s+(\d+)",
    re.I,
)
_DISMOUNT = re.compile(r"cache\s+dismounting\s+group\s+(\d+)(?:\s*\(([^)]+)\))?", re.I)
_ORA_ASM = re.compile(r"\b(ORA-15\d{3})\b", re.I)

# Map normalized extraction codes → knowledge-graph pattern_id when names differ.
_NORM_TO_GRAPH: list[tuple[str, str, str]] = [
    # (code_type, normalized_code, graph_pattern_id)
    ("OS_PATTERN", "FC_HBA_ABORT", "FC_HBA_RESET"),
    ("OS_PATTERN", "OS_OOM_KILLER", "OOM_KILLER_ACTIVE"),
    ("STORAGE_PATTERN", "FLASH_IO_TIMEOUT", "EXA_FLASH_FAIL"),
    ("STORAGE_PATTERN", "FLASH_CACHE_READ_ERROR", "EXA_FLASH_FAIL"),
    ("STORAGE_PATTERN", "FLASH_DISK_CRITICAL", "EXA_FLASH_FAIL"),
    ("STORAGE_PATTERN", "STORAGE_BACKEND_LATENCY", "EXA_CELL_IO_ERROR"),
    ("STORAGE_PATTERN", "STORAGE_MEDIA_READ_FAILURE", "EXA_CELL_IO_ERROR"),
    ("STORAGE_PATTERN", "STORAGE_ASM_READ_FAILED", "EXA_CELL_IO_ERROR"),
]


def infer_incident_year_from_text(text: str) -> int | None:
    for line in (text or "").splitlines()[:80]:
        info = parse_line_timestamp(line.strip())
        ts = info.get("timestamp")
        if ts is not None:
            return ts.year
    return None


def graph_pattern_ids_from_normalized_events(
    events: list[dict[str, Any]],
    *,
    allowed: frozenset[str] | None = None,
) -> list[str]:
    """
    Derive pattern_id strings (must exist in patterns.json) from normalized evidence.
    Used to align regex graph matching with unified extraction.
    """
    if allowed is None:
        from src.knowledge_graph.pattern_matcher import list_pattern_definition_ids

        allowed = list_pattern_definition_ids()
    out: list[str] = []
    seen: set[str] = set()
    for e in events or []:
        code = (e.get("code") or "").strip()
        ctype = (e.get("code_type") or "").strip().upper()
        if not code:
            continue
        if code in allowed and code not in seen:
            seen.add(code)
            out.append(code)
            continue
        for ct, norm_c, graph_id in _NORM_TO_GRAPH:
            if ctype == ct and code == norm_c and graph_id in allowed and graph_id not in seen:
                seen.add(graph_id)
                out.append(graph_id)
                break
    return out


def _alert_ora_line_keys(events: list[dict[str, Any]]) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    for e in events or []:
        if (e.get("code_type") or "").upper() != "ORA":
            continue
        c = (e.get("code") or "").strip().upper()
        if not re.match(r"^ORA-15\d{3}$", c):
            continue
        keys.add((int(e.get("line_number") or 0), c))
    return keys


def _extract_asm_fragment_events(
    text: str,
    source_file: str,
    source_path: str,
    *,
    skip_asm_ora_keys: set[tuple[int, str]] | None = None,
) -> list[dict[str, Any]]:
    sp = (source_path or "").strip()
    sf = (source_file or "").strip() or (os.path.basename(sp) if sp else "")
    events: list[dict[str, Any]] = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        if _line_is_cell_storage(s):
            # Cell lines are handled by cell parser as STORAGE_* evidence.
            continue
        m = _READ_FAIL.search(s)
        if m:
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "asm_log",
                "layer": "ASM",
                "code": "ASM_READ_FAILED",
                "code_type": "ASM_PATTERN",
                "asm_group": m.group(1),
                "asm_disk": m.group(2),
                "au": m.group(3),
                "offset": m.group(4),
                "size": m.group(5),
                "failure_family": "IO",
                "severity": "CRITICAL",
                "message": s[:2000],
                "parse_confidence": "HIGH",
                "tags": ["ASM_COORD"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="asm_snippet_parser", raw=s)
            )
        m2 = _MIRROR.search(s)
        if m2:
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "asm_log",
                "layer": "ASM",
                "code": "ASM_MIRROR_READ_FAIL",
                "code_type": "ASM_PATTERN",
                "details": {
                    "mirror_side": m2.group(1),
                    "virtual_extent": m2.group(2),
                    "logical_extent": m2.group(3),
                    "asm_file": m2.group(4),
                    "asm_group": m2.group(5),
                },
                "asm_file": m2.group(4),
                "asm_group": m2.group(5),
                "failure_family": "IO",
                "severity": "ERROR",
                "message": s[:2000],
                "parse_confidence": "HIGH",
                "tags": ["ASM_MIRROR"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="asm_snippet_parser", raw=s)
            )
        m3 = _DISMOUNT.search(s)
        if m3:
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "asm_log",
                "layer": "ASM",
                "code": "ASM_DISMOUNT_PROGRESS",
                "code_type": "ASM_PATTERN",
                "asm_group": m3.group(1),
                "diskgroup": m3.group(2),
                "severity": "WARNING",
                "message": s[:2000],
                "tags": ["ASM_DISMOUNT"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="asm_snippet_parser", raw=s)
            )
        for om in _ORA_ASM.finditer(s):
            ora = om.group(1).upper()
            if skip_asm_ora_keys and (i, ora) in skip_asm_ora_keys:
                continue
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "asm_log",
                "layer": "ASM",
                "code": ora,
                "code_type": "ORA",
                "message": s[:2000],
                "severity": "ERROR",
                "tags": ["ASM_ORA"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="asm_snippet_parser", raw=s)
            )
    return events


_CELL_STORAGE_BODY = re.compile(
    r"CELLSRV|\bMS:\s|\bRS:\s|flashdisk|griddisk|celldisk|warningCode=",
    re.I,
)


def _looks_like_cell_storage_text(t: str) -> bool:
    """True when text is dominated by Exadata cell log lines (not ASM instance alert)."""
    return bool(_CELL_STORAGE_BODY.search(t or ""))


def _line_is_cell_storage(line: str) -> bool:
    return bool(_CELL_STORAGE_BODY.search(line or ""))


def _unwrap_json_logs(text: str) -> list[tuple[str, str]]:
    """
    Normalize JSON payloads into [(name, content)].
    Supported:
      {"filename": "...", "content": "..."}
      {"logs":[{"name":"...","text":"..."}, ...]}
      [{"filename":"...","content":"..."}, ...]
    """
    s = (text or "").strip()
    if len(s) < 2 or s[0] not in "[{":
        return []
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []

    def _row(obj: dict[str, Any]) -> tuple[str, str] | None:
        body = obj.get("content") or obj.get("text") or obj.get("log")
        if not isinstance(body, str) or not body.strip():
            return None
        name = (
            obj.get("name")
            or obj.get("filename")
            or obj.get("source")
            or obj.get("file_source")
            or "json_payload.log"
        )
        return str(name), body

    out: list[tuple[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                row = _row(item)
                if row:
                    out.append(row)
    elif isinstance(data, dict):
        logs = data.get("logs")
        if isinstance(logs, list):
            for item in logs:
                if isinstance(item, dict):
                    row = _row(item)
                    if row:
                        out.append(row)
        if not out:
            row = _row(data)
            if row:
                out.append(row)
    return out


def _append_auxiliary_routed_events(
    out: list[dict[str, Any]],
    text: str,
    *,
    source_file: str,
    source_path: str,
) -> None:
    """
    Heuristic routes: CRS, AIX errpt, iostat, OSWatcher, AWR, trace, audit,
    security, and ExaWatcher snippets. All outputs are evidence-only.
    """
    t = text or ""
    if not t.strip():
        return

    if re.search(r"\bCRS-\d+\b|\[CSSD|\[CRSD|\bOHASD\b|\bEVMD\b", t, re.I):
        from src.parsers.crs_parser import parse_crs_text

        for j, row in enumerate(parse_crs_text(t)):
            if row.get("is_false_positive"):
                continue
            cc = row.get("crs_code") or ""
            partial = {
                "line_number": j + 1,
                "timestamp": row.get("timestamp"),
                "timestamp_raw": row.get("timestamp_str"),
                "source_file": source_file or None,
                "source_path": source_path or None,
                "source_type": "crs_log",
                "layer": "CRS",
                "component": row.get("component"),
                "code": cc,
                "code_type": "CRS_PATTERN",
                "message": (row.get("message") or "")[:2000],
                "severity": row.get("severity") or "ERROR",
                "host": row.get("affected_node"),
                "crs_resource": row.get("resource_name"),
                "parse_confidence": "HIGH",
                "tags": ["CRS_LOG"],
            }
            out.append(
                ensure_normalized_event(
                    partial, parser_name="crs_parser", raw=row.get("raw", "")
                )
            )

    if re.search(r"^LABEL:\s+\w+", t, re.M):
        from src.parsers.aix_errpt_parser import parse_errpt_text

        for j, row in enumerate(parse_errpt_text(t)):
            partial = {
                "line_number": j + 1,
                "timestamp": row.get("timestamp"),
                "timestamp_raw": row.get("timestamp_str"),
                "source_file": source_file or None,
                "source_path": source_path or None,
                "source_type": "aix_errpt",
                "layer": "OS",
                "code": row.get("os_pattern") or row.get("label") or "AIX_ERRPT",
                "code_type": "OS_PATTERN",
                "message": (row.get("description") or row.get("raw", ""))[:2000],
                "severity": row.get("severity") or "ERROR",
                "device": row.get("resource"),
                "parse_confidence": "HIGH",
                "tags": ["AIX_ERRPT"],
            }
            out.append(
                ensure_normalized_event(
                    partial, parser_name="aix_errpt_parser", raw=row.get("raw", "")
                )
            )

    head = t[:8000]
    if "Device" in head and "r_await" in head and "%util" in head:
        from src.parsers.iostat_parser import parse_iostat_text

        for j, row in enumerate(parse_iostat_text(t)):
            util = float(row.get("util_pct") or 0)
            await_ms = float(row.get("await_ms") or 0)
            dev = row.get("device") or ""
            if util >= 95:
                code = "HIGH_DEVICE_UTILIZATION"
            elif await_ms >= 100:
                code = "HIGH_AWAIT"
            else:
                code = "IOSTAT_DEVICE_ROW"
            partial = {
                "line_number": j + 1,
                "source_file": source_file or None,
                "source_path": source_path or None,
                "source_type": "iostat",
                "layer": "OS",
                "code": code,
                "code_type": "GENERIC_PATTERN",
                "device": dev,
                "message": row.get("raw", "")[:2000],
                "severity": row.get("severity") or "INFO",
                "parse_confidence": "MEDIUM",
                "tags": ["IOSTAT"],
            }
            out.append(
                ensure_normalized_event(
                    partial, parser_name="iostat_parser", raw=row.get("raw", "")
                )
            )

    if re.search(r"zzz\s+\*\*\*", t, re.I):
        from src.parsers.osw_parser import parse_osw_text

        osw = parse_osw_text(t)
        for j, sig in enumerate(osw.get("osw_signals") or []):
            partial = {
                "line_number": j + 1,
                "source_file": source_file or None,
                "source_path": source_path or None,
                "source_type": "oswatcher",
                "layer": "OS",
                "code": sig,
                "code_type": "GENERIC_PATTERN",
                "message": (osw.get("parse_error") or sig)[:500],
                "severity": "WARNING",
                "parse_confidence": "MEDIUM",
                "tags": ["OSWATCHER"],
            }
            out.append(
                ensure_normalized_event(partial, parser_name="osw_parser", raw=sig)
            )

    if re.search(
        r"AWR\s+Report|Workload\s+Repository|DB\s+Time.*\(mins\)|Top\s+\d+\s+Foreground\s+Events",
        t,
        re.I,
    ):
        import tempfile
        from src.parsers.awr_parser import parse_awr_report

        suf = ".html" if "<html" in t[:4000].lower() else ".txt"
        apath = None
        try:
            fd, apath = tempfile.mkstemp(suffix=suf)
            with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as tf:
                tf.write(t)
            awr = parse_awr_report(apath)
            for j, sig in enumerate(awr.get("awr_signals") or []):
                partial = {
                    "line_number": j + 1,
                    "source_file": source_file or None,
                    "source_path": source_path or None,
                    "source_type": "awr",
                    "layer": "AWR",
                    "code": sig,
                    "code_type": "AWR_PATTERN",
                    "message": ",".join(awr.get("wait_signals") or [])[:2000],
                    "severity": "INFO",
                    "parse_confidence": "MEDIUM",
                    "tags": ["AWR"],
                }
                out.append(
                    ensure_normalized_event(
                        partial, parser_name="awr_parser", raw=sig
                    )
                )
        except Exception:
            pass
        finally:
            if apath:
                try:
                    os.unlink(apath)
                except OSError:
                    pass

    if re.search(r"Trace file|^\*\*\*.*SESSION ID:|Incident Id:", t, re.I | re.M):
        from src.parsers.trace_parser import parse_trace_text_safe

        tr = parse_trace_text_safe(t)
        meta = tr.get("metadata") or {}
        ora_found = False
        for ln, line in enumerate(t.splitlines(), start=1):
            for om in re.finditer(r"\b(ORA-\d{5})\b", line, re.I):
                ora_found = True
                partial = {
                    "line_number": ln,
                    "source_file": source_file or None,
                    "source_path": source_path or None,
                    "source_type": "trace",
                    "layer": "DB",
                    "code": om.group(1).upper(),
                    "code_type": "ORA",
                    "message": line.strip()[:2000],
                    "severity": "ERROR",
                    "parse_confidence": "MEDIUM",
                    "tags": ["TRACE_SNIPPET"],
                    "details": meta,
                }
                out.append(
                    ensure_normalized_event(
                        partial, parser_name="trace_parser", raw=line.strip()
                    )
                )
        if tr.get("parse_warning") and not ora_found:
            out.append(
                ensure_normalized_event(
                    {
                        "line_number": 1,
                        "layer": "UNKNOWN",
                        "code": tr.get("parse_warning"),
                        "code_type": "GENERIC_PATTERN",
                        "severity": "WARNING",
                        "parse_confidence": "LOW",
                        "tags": ["TRACE_PARSE_WARNING"],
                    },
                    parser_name="trace_parser",
                    raw=t[:2000],
                )
            )

    if re.search(
        r"\bACTION\s*:\s+|\bRETURNCODE\s*:\s*\d|\bRETURNCODE\s*:\s*\[|^AUDIT|\bGRANT\s+DBA\b",
        t,
        re.I | re.M,
    ):
        from src.parsers.audit_parser import OracleAuditParser

        ap = OracleAuditParser()
        a = ap.parse_audit_text(t)
        if a:
            et = str(a.get("event_type") or "").strip()
            if et:
                code = et
            elif re.search(r"\bORA-01017\b", a.get("raw") or t, re.I):
                code = "AUTH_FAILURE"
            elif str(a.get("returncode", "0")) != "0":
                code = "AUTH_FAILURE"
            else:
                code = "AUDIT_EVENT"
            out.append(
                ensure_normalized_event(
                    {
                        "line_number": 1,
                        "source_file": source_file or None,
                        "source_path": source_path or None,
                        "source_type": "audit_log",
                        "layer": "AUDIT",
                        "code": code,
                        "code_type": "AUDIT_PATTERN",
                        "severity": a.get("severity") or "INFO",
                        "message": (a.get("raw") or "")[:2000],
                        "details": a,
                        "parse_confidence": "MEDIUM",
                        "tags": ["AUDIT"],
                    },
                    parser_name="audit_parser",
                    raw=a.get("raw", t[:2000]),
                )
            )

    if re.search(r"sshd|sudo|failed password|invalid user|authentication failure", t, re.I):
        from src.parsers.security_parser import SecurityParser

        sp = SecurityParser()
        rows = sp.parse_batch(t.splitlines())
        for j, row in enumerate(rows):
            et = str(row.get("event_type") or "").upper()
            if et in ("AUTH_FAILURE", "SUSPICIOUS_LOGIN", "SSH_FAILED") or "FAILED" in et:
                code = "AUTH_FAILURE"
            elif "SUDO" in et or et == "PRIVILEGE_CHANGE" or "PRIVILEGE" in et:
                code = "PRIVILEGE_CHANGE"
            elif "AUTH" in et:
                code = "AUTH_FAILURE"
            else:
                code = "SECURITY_POLICY_EVENT"
            out.append(
                ensure_normalized_event(
                    {
                        "line_number": j + 1,
                        "source_file": source_file or None,
                        "source_path": source_path or None,
                        "source_type": "security_log",
                        "layer": "SECURITY",
                        "code": code,
                        "code_type": "SECURITY_PATTERN",
                        "severity": row.get("severity") or "WARNING",
                        "message": (row.get("details") or row.get("raw") or "")[:2000],
                        "parse_confidence": "MEDIUM",
                        "tags": ["SECURITY"],
                        "details": row,
                    },
                    parser_name="security_parser",
                    raw=row.get("raw", ""),
                )
            )

    if re.search(r"\bib\d+\b", t, re.I):
        from src.parsers.exawatcher_parser import ExaWatcherParser

        ex = ExaWatcherParser()
        rows = ex.parse_exawatcher_text(t, hostname="unknown")
        for j, row in enumerate(rows):
            out.append(
                ensure_normalized_event(
                    {
                        "line_number": j + 1,
                        "source_file": source_file or None,
                        "source_path": source_path or None,
                        "source_type": "exawatcher",
                        "layer": "STORAGE",
                        "code": "EXAWATCHER_IB_LINK_ISSUE",
                        "code_type": "STORAGE_PATTERN",
                        "severity": row.get("severity") or "WARNING",
                        "message": row.get("message", "")[:2000],
                        "host": row.get("hostname"),
                        "component": row.get("component"),
                        "parse_confidence": "MEDIUM",
                        "tags": ["EXAWATCHER"],
                        "details": row,
                    },
                    parser_name="exawatcher_parser",
                    raw=row.get("raw", ""),
                )
            )


def extract_normalized_events_unified(
    text: str,
    *,
    source_file: str = "",
    source_path: str = "",
    incident_year: int | None = None,
    cell_name: str = "unknown",
) -> list[dict[str, Any]]:
    """
    Run alert, syslog, ASM fragment, cell, generic extractors; concatenate + dedupe.

    Generic fallback always runs so mixed pastes still surface weak evidence; duplicates
    are removed via dedupe_normalized_events.
    """
    from src.parsers.alert_log_parser import parse_alert_log_normalized_events
    from src.parsers.syslog_parser import parse_syslog_text
    from src.parsers.cell_log_parser import CellLogParser

    if not (text or "").strip():
        return []

    unwrapped = _unwrap_json_logs(text)
    if unwrapped:
        combined: list[dict[str, Any]] = []
        wrapper_src = (source_file or "").strip() or (
            os.path.basename(source_path) if (source_path or "").strip() else ""
        )
        wrapper_path = (source_path or "").strip() or (source_file or "").strip()
        for name, body in unwrapped:
            # Inner log identity wins for evidence rows; outer bundle path is preserved in details.
            sub_file = str(name).strip() or "json_payload.log"
            sub_path = sub_file
            sub_events = extract_normalized_events_unified(
                body,
                source_file=sub_file,
                source_path=sub_path,
                incident_year=incident_year,
                cell_name=cell_name,
            )
            if wrapper_src or wrapper_path:
                for ev in sub_events:
                    details = dict(ev.get("details") or {})
                    if wrapper_src:
                        details.setdefault("wrapper_source", wrapper_src)
                    if wrapper_path:
                        details.setdefault("wrapper_source_path", wrapper_path)
                    ev["details"] = details
            combined.extend(sub_events)
        return dedupe_normalized_events(combined)

    iy = incident_year if incident_year is not None else infer_incident_year_from_text(text)
    sp = (source_path or "").strip()
    sf = (source_file or "").strip() or (os.path.basename(sp) if sp else "")

    out: list[dict[str, Any]] = []
    alert_events = parse_alert_log_normalized_events(
        text,
        source_file=sf,
        source_path=sp,
        incident_year=iy,
    )
    out.extend(alert_events)

    # Broad trigger: kernel/multipathd with optional [pid], SCSI timeouts, multipath path loss
    if re.search(
        r"kernel(?:\[\d+\])?:|"
        r"multipathd(?:\[\d+\])?:|"
        r"qla2xxx|lpfc|"
        r"blk_update_request|"
        r"DID_TIME_OUT|DRIVER_TIMEOUT|"
        r"remaining\s+active\s+paths:\s*0|"
        r"no\s+active\s+paths|"
        r"rejecting\s+I/O\s+to\s+offline\s+device",
        text,
        re.I,
    ):
        sy = parse_syslog_text(text, hostname=None, default_year=iy)
        out.extend(
            syslog_entries_to_normalized_events(
                sy, source_file=sf, source_path=sp
            )
        )

    asm_candidate = bool(
        "Read Failed." in text
        or "cache dismounting" in text.lower()
        or re.search(r"ORA-15\d{3}", text, re.I)
    )
    if asm_candidate:
        out.extend(
            _extract_asm_fragment_events(
                text,
                sf,
                sp,
                skip_asm_ora_keys=_alert_ora_line_keys(alert_events),
            )
        )

    if re.search(r"CELLSRV|\bMS:|\bRS:|flashdisk|griddisk|celldisk", text, re.I):
        cp = CellLogParser()
        cent = cp.parse_cell_log_text(text, cell_name=cell_name)
        out.extend(
            cell_entries_to_normalized_events(
                cent,
                source_file=sf,
                source_path=sp,
            )
        )

    _append_auxiliary_routed_events(
        out,
        text,
        source_file=sf,
        source_path=sp,
    )

    seen_raw: set[str] = {(e.get("raw") or "").strip() for e in out if e.get("raw")}
    for g in extract_generic_events(text, source_file=sf, source_path=sp):
        raw_g = (g.get("raw") or "").strip()
        if raw_g in seen_raw:
            continue
        seen_raw.add(raw_g)
        out.append(
            ensure_normalized_event(
                {k: v for k, v in g.items() if k != "parser_name"},
                parser_name="generic_evidence_parser",
                raw=g.get("raw", ""),
            )
        )

    return dedupe_normalized_events(out)


def _zip_evidence_cfg() -> dict[str, Any]:
    try:
        import yaml

        p = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
        with open(p, encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        z = y.get("zip_evidence") or {}
        return z if isinstance(z, dict) else {}
    except Exception:
        return {}


def _leaf_archive_kind(path: str) -> str | None:
    pl = (path or "").lower()
    if pl.endswith(".zip"):
        return "zip"
    if _tar_open_mode(path):
        return "tar"
    return None


def _expand_archive_tree(
    initial_paths: list[str],
    temp_root: str,
    *,
    max_uncompressed_zip: int,
    max_zip_members: int,
    max_tar_members: int,
    max_tar_member_bytes: int,
    max_depth: int,
    max_nested_ops: int,
    diagnostics: dict[str, Any],
) -> list[str]:
    """
    Flatten nested .zip and tar.* bundles into leaf file paths for text parsing.
    Archives beyond max_depth or max_nested_ops are skipped with diagnostics only.
    """
    leaves: list[str] = []
    seen_leaf: set[str] = set()
    ops_used = 0
    q: deque[tuple[str, int]] = deque((p, 0) for p in initial_paths)

    while q:
        path, depth = q.popleft()
        if not os.path.isfile(path):
            continue
        kind = _leaf_archive_kind(path)
        if kind == "zip" and depth < max_depth:
            if ops_used >= max_nested_ops:
                diagnostics.setdefault("skipped_nested", []).append(
                    {"path": path, "reason": "max_nested_archive_expansions"}
                )
                continue
            ops_used += 1
            nest_dir = tempfile.mkdtemp(prefix="nested_zip_", dir=temp_root)
            out = safe_extract_zip(
                path,
                nest_dir,
                max_uncompressed_bytes=max_uncompressed_zip,
                max_members=max_zip_members,
            )
            for s in out.get("skipped") or []:
                diagnostics.setdefault("skipped_from_nested_zip", []).append({"parent": path, **s})
            for child in out.get("extracted") or []:
                ck = _leaf_archive_kind(child)
                if ck and (depth + 1) < max_depth:
                    q.append((child, depth + 1))
                elif ck:
                    diagnostics.setdefault("skipped_nested", []).append(
                        {"path": child, "reason": "max_nesting_depth"}
                    )
                else:
                    ap = os.path.abspath(child)
                    if ap not in seen_leaf:
                        seen_leaf.add(ap)
                        leaves.append(ap)
            continue
        if kind == "tar" and depth < max_depth:
            if ops_used >= max_nested_ops:
                diagnostics.setdefault("skipped_nested", []).append(
                    {"path": path, "reason": "max_nested_archive_expansions"}
                )
                continue
            ops_used += 1
            nest_dir = tempfile.mkdtemp(prefix="nested_tar_", dir=temp_root)
            out = safe_extract_tar(
                path,
                nest_dir,
                max_member_bytes=max_tar_member_bytes,
                max_members=max_tar_members,
            )
            for s in out.get("skipped") or []:
                diagnostics.setdefault("skipped_from_nested_tar", []).append({"parent": path, **s})
            for child in out.get("extracted") or []:
                ck = _leaf_archive_kind(child)
                if ck and (depth + 1) < max_depth:
                    q.append((child, depth + 1))
                elif ck:
                    diagnostics.setdefault("skipped_nested", []).append(
                        {"path": child, "reason": "max_nesting_depth"}
                    )
                else:
                    ap = os.path.abspath(child)
                    if ap not in seen_leaf:
                        seen_leaf.add(ap)
                        leaves.append(ap)
            continue
        if kind in ("zip", "tar") and depth >= max_depth:
            diagnostics.setdefault("skipped_nested", []).append(
                {"path": path, "reason": "max_nesting_depth_unopened"}
            )
            continue
        ap = os.path.abspath(path)
        if ap not in seen_leaf:
            seen_leaf.add(ap)
            leaves.append(ap)
    return leaves


def _diag_file_priority_score(rel: str, fname_lower: str) -> int:
    """
    Higher = parse first for AHF/TFA ZIP bundles (before max_files cap).
    Order aligns with diagnostic value: DB alert → traces → ASM/CRS → OS → cell → metrics → rest.
    """
    r = (rel or "").lower()
    f = (fname_lower or "").lower()
    s = 0
    if f.endswith((".log", ".trc", ".txt", ".out", ".html", ".xml", ".json", ".csv")):
        s += 2
    if "alert" in f or "/trace/" in r or "trace/" in r or "_alert" in f:
        s += 100
    if any(p in f for p in ("lgwr", "dbwr", "ckpt", "smon", "pmon", "arc", "mmon")):
        s += 70
    if "asm" in f or "+asm" in r or "/asm/" in r:
        s += 65
    if any(x in r for x in ("crs", "css", "ohasd", "crsctl", "grid")):
        s += 60
    if f in ("messages", "syslog", "secure", "auth.log") or "messages" in f or "syslog" in f or "dmesg" in f:
        s += 55
    if "cellsrv" in f or "cellalert" in f or "ms_" in f or "rs_" in f or "/cell" in r:
        s += 52
    if "cellcli" in f or "dcli" in f:
        s += 48
    if "osw" in r or "oswatcher" in r or f.startswith("iostat") or "vmstat" in f or "mpstat" in f or "sar" in f:
        s += 42
    if "awr" in f or "ash" in f or "addm" in f:
        s += 38
    if "audit" in f or "adump" in r:
        s += 35
    if any(x in r for x in ("orachk", "exachk", "ahf", "tfa", "insights")):
        s += 32
    return s


def _prioritize_zip_abs_paths(written: list[str], temp_dir: str, max_files: int) -> list[str]:
    """Sort extracted members by diagnostic priority, then relative path (stable)."""
    temp_abs = os.path.abspath(temp_dir)
    scored: list[tuple[int, str, str]] = []
    for abs_path in written or []:
        try:
            rel = os.path.relpath(abs_path, temp_abs).replace("\\", "/")
        except ValueError:
            rel = os.path.basename(abs_path)
        fname = os.path.basename(abs_path)
        pr = _diag_file_priority_score(rel, fname.lower())
        scored.append((pr, rel, abs_path))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [x[2] for x in scored[:max_files]]


def extract_normalized_events_from_zip(
    zip_path: str,
    *,
    max_files: int = 120,
    max_text_bytes: int | None = None,
    cell_name: str = "unknown",
) -> dict[str, Any]:
    """
    Safe extract → optional nested archive expansion → sniff text → infer incident year
    across bundle → per-file unified extraction.
    Returns {"events": [...], "ingest_diagnostics": {...}}.
    """
    cfg = _zip_evidence_cfg()
    max_uncompressed = int(cfg.get("max_uncompressed_bytes_per_member", 200 * 1024 * 1024))
    max_zip_members = int(cfg.get("max_zip_members", 8000))
    max_tar_members = int(cfg.get("max_tar_members", 250_000))
    max_tar_member_bytes = int(cfg.get("max_tar_member_bytes", max_uncompressed))
    max_depth = int(cfg.get("max_nesting_depth", 6))
    max_nested_ops = int(cfg.get("max_nested_archive_expansions", 80))
    max_parse_files = int(cfg.get("max_parse_files", 3000))
    if max_text_bytes is None:
        max_text_bytes = int(cfg.get("max_text_bytes_per_file", 12 * 1024 * 1024))

    parse_budget = max(max_files, max_parse_files) if max_parse_files else max_files

    temp_dir = tempfile.mkdtemp(prefix="zip_evidence_")
    diagnostics: dict[str, Any] = {
        "skipped": [],
        "parsed_files": [],
        "skipped_from_extract": [],
        "skipped_from_nested_zip": [],
        "skipped_from_nested_tar": [],
        "skipped_nested": [],
    }
    all_events: list[dict[str, Any]] = []
    try:
        zip_out = safe_extract_zip(
            zip_path,
            temp_dir,
            max_uncompressed_bytes=max_uncompressed,
            max_members=max_zip_members,
        )
        written = zip_out.get("extracted") or []
        diagnostics["skipped_from_extract"] = list(zip_out.get("skipped") or [])

        expanded = _expand_archive_tree(
            written,
            temp_dir,
            max_uncompressed_zip=max_uncompressed,
            max_zip_members=max_zip_members,
            max_tar_members=max_tar_members,
            max_tar_member_bytes=max_tar_member_bytes,
            max_depth=max_depth,
            max_nested_ops=max_nested_ops,
            diagnostics=diagnostics,
        )
        diagnostics["expanded_leaf_count"] = len(expanded)

        staged: list[tuple[str, str, str]] = []
        for abs_path in _prioritize_zip_abs_paths(expanded, temp_dir, parse_budget):
            rel = os.path.relpath(abs_path, temp_dir).replace("\\", "/")
            try:
                sz = os.path.getsize(abs_path)
            except OSError as e:
                diagnostics["skipped"].append({"path": rel, "reason": str(e)})
                continue
            if sz > max_text_bytes:
                diagnostics["skipped"].append({"path": rel, "reason": "file_too_large"})
                continue
            try:
                with open(abs_path, "rb") as bf:
                    sample = bf.read(8192)
                if b"\x00" in sample[:4096]:
                    diagnostics["skipped"].append({"path": rel, "reason": "binary_sniff"})
                    continue
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(max_text_bytes)
            except OSError as e:
                diagnostics["skipped"].append({"path": rel, "reason": str(e)})
                continue
            if not (text or "").strip():
                continue
            fname = os.path.basename(abs_path)
            staged.append((rel, fname, text))

        bundle_sample = "\n".join(t for _, _, t in staged[:40])
        iy_global = infer_incident_year_from_text(bundle_sample)

        for rel, fname, text in staged:
            ev = extract_normalized_events_unified(
                text,
                source_file=fname,
                source_path=rel,
                incident_year=iy_global,
                cell_name=cell_name,
            )
            all_events.extend(ev)
            diagnostics["parsed_files"].append(rel)
        return {
            "events": dedupe_normalized_events(all_events),
            "ingest_diagnostics": diagnostics,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
