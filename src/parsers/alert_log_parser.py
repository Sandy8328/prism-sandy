"""
alert_log_parser.py — Parses Oracle alert.log files.

Alert.log formats:
  Classic (pre-12c):   "Tue Apr 21 03:14:18 2024\nORA-27072: File I/O error"
  XML (12c+):          <msg time='2024-04-21T03:14:18.000+05:30' ...>
  CDB (19c+):          includes PDB name in brackets [CDB$ROOT] or [PDBNAME]

Produces list of AlertEntry dicts grouped by timestamp blocks.
"""

import re
import os
from datetime import datetime
from typing import Optional

try:
    from src.knowledge_graph.graph import get_layer_for_code as _get_layer_for_code
except Exception:  # pragma: no cover — allow parser import without full graph

    def _get_layer_for_code(code: str) -> dict:
        return {"layer": "DB"}

# ── Timestamp patterns ──────────────────────────────────────────

# Classic alert.log timestamp line
_CLASSIC_TS = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4})$"
)

# XML alert.log timestamp (12c+)
_XML_TS = re.compile(
    r"<msg time='(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})'"
)

# Plain ISO 8601 timestamp line (ADR text version)
_ISO_TS = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})$"
)

# ORA error code line
_ORA_CODE = re.compile(r"(ORA-\d{5})")

# CDB/PDB context
_PDB_CONTEXT = re.compile(r"\[([A-Z][A-Z0-9_$#]{0,29})\]")

# Trace file reference — classic "Errors in file" style
_TRACE_FILE = re.compile(r"Errors in file (.+?\.trc)(?:\s+\(incident=\d+\))?(?::)?")

# Incident details line — printed for ORA-00600 / ORA-07445
_INCIDENT_DETAILS = re.compile(
    r"Incident details in:\s*(.+?\.trc)"
)

# Dump file line — printed for background process dumps
_DUMP_FILE = re.compile(
    r"(?:Dump file|Trace file):\s*(.+?\.trc)"
)

# Incident ID extractor — pulls numeric ID from path or line
_INCIDENT_ID = re.compile(r"(?:incident=|incdir_|_i)(\d{4,10})")

# OS errno lines (all platforms)
_OS_ERRNO = re.compile(
    r"(Linux-x86_64|IBM AIX RISC System/6000|Solaris-\w+|HP-UX|O/S) Error: (\d+): (.+)"
)

# Background process death
_BGPROC_DIED = re.compile(
    r"(LGWR|DBWR|MMON|PMON|SMON|CKPT|ARC\d+|LREG|DIAG|DBRM).*process \d+ died"
)

# Instance state messages
_INSTANCE_MSGS = re.compile(
    r"(Starting ORACLE instance|Shutting down instance|Instance terminated|"
    r"ORACLE instance shut down|ORACLE instance started)"
)


def _parse_classic_ts(line: str) -> Optional[datetime]:
    m = _CLASSIC_TS.match(line.strip())
    if m:
        try:
            return datetime.strptime(
                f"{m.group(2)} {m.group(3)} {m.group(4)} {m.group(5)}",
                "%b %d %H:%M:%S %Y"
            )
        except ValueError:
            return None
    return None


def _parse_xml_ts(line: str) -> Optional[datetime]:
    m = _XML_TS.search(line)
    if m:
        try:
            from dateutil import parser as dp
            return dp.parse(m.group(1))
        except Exception:
            return None
    return None


def _parse_iso_ts(line: str) -> Optional[datetime]:
    m = _ISO_TS.match(line.strip())
    if m:
        try:
            # fromisoformat handles '2024-03-12T10:15:00.000+05:30' in Python 3.7+
            return datetime.fromisoformat(m.group(1))
        except Exception:
            return None
    return None


def _extract_ora_codes(text: str) -> list:
    return list(dict.fromkeys(_ORA_CODE.findall(text)))  # unique, ordered


def _extract_pdb(text: str) -> Optional[str]:
    """Extract PDB/CDB container name if present."""
    m = _PDB_CONTEXT.search(text)
    if m:
        name = m.group(1)
        if name not in ("ROOT", "SEED"):
            return name
        if name == "ROOT":
            return "CDB$ROOT"
    return None


def parse_alert_log_text(text: str) -> list:
    """
    Parse alert.log content from a string.
    Returns list of AlertEntry dicts, each covering one timestamp block.

    AlertEntry structure:
      {
        "timestamp":   datetime | None,
        "timestamp_str": str,
        "ora_codes":   ["ORA-27072", ...],
        "os_errno":    ("5", "Input/output error") | None,
        "trace_file":  "/u01/.../trace.trc" | None,
        "pdb_name":    "MYPDB" | None,
        "bgproc_died": "LGWR" | None,
        "instance_msg": str | None,
        "severity":    "CRITICAL"|"ERROR"|"WARNING"|"INFO",
        "raw":         "full block text",
        "lines":       [str, ...]
      }
    """
    lines = text.splitlines()
    entries = []
    current_block_lines = []
    current_ts = None
    current_ts_str = ""

    def flush_block():
        if not current_block_lines:
            return
            
        # [Edge Case 29: Massive PL/SQL Dump]
        # Truncate large user SQL blocks so they don't break chunking limits
        truncated_lines = []
        in_sql_block = False
        sql_lines_count = 0
        
        for line in current_block_lines:
            if "Current SQL statement" in line or "SQL text:" in line or "SQL statement:" in line:
                in_sql_block = True
                truncated_lines.append(line)
                sql_lines_count = 0
                continue
                
            if in_sql_block:
                sql_lines_count += 1
                if sql_lines_count <= 5:
                    truncated_lines.append(line)
                elif sql_lines_count == 6:
                    truncated_lines.append("... [MASSIVE SQL BLOCK TRUNCATED BY AGENT] ...")
                    
                # End of SQL block is usually a blank line, an ORA- code, or a trace file pointer
                if not line.strip() or line.startswith("ORA-") or line.startswith("Errors in file"):
                    in_sql_block = False
                    if line.startswith("ORA-") or line.startswith("Errors in file"):
                        truncated_lines.append(line)
            else:
                truncated_lines.append(line)
                
        current_block_lines[:] = truncated_lines
        
        block_text = "\n".join(current_block_lines)
        ora_codes = _extract_ora_codes(block_text)
        os_errno_m = _OS_ERRNO.search(block_text)

        # ── Trace / Incident path extraction (Phase A) ─────────────
        # Oracle prints trace paths in 3 different formats — check all.
        trace_path    = None
        incident_path = None
        incident_id   = None

        inc_m = _INCIDENT_DETAILS.search(block_text)
        if inc_m:
            trace_path = inc_m.group(1).strip()
        if not trace_path:
            err_m = _TRACE_FILE.search(block_text)
            if err_m:
                trace_path = err_m.group(1).strip()
        if not trace_path:
            dump_m = _DUMP_FILE.search(block_text)
            if dump_m:
                trace_path = dump_m.group(1).strip()

        if trace_path:
            import os as _os
            incident_path = _os.path.dirname(trace_path)
            
        # Search the entire block for incident ID (Phase A)
        id_m = _INCIDENT_ID.search(block_text)
        if id_m:
            incident_id = id_m.group(1)
        # ────────────────────────────────────────────────────────────

        bgproc_m = _BGPROC_DIED.search(block_text)
        inst_m = _INSTANCE_MSGS.search(block_text)

        severity = "INFO"
        if ora_codes:
            # Generic Severity Logic: Ask the Knowledge Graph about the layer
            is_critical = False
            for code in ora_codes:
                info = _get_layer_for_code(code)
                if info.get("layer") in ("OS_TRIGGERED", "ASM", "STORAGE", "MEMORY", "CLUSTER"):
                    is_critical = True
                    break
            severity = "CRITICAL" if is_critical else "ERROR"
        elif bgproc_m:
            severity = "CRITICAL"

        entries.append({
            "timestamp":    current_ts,
            "timestamp_str": current_ts_str,
            "ora_codes":    ora_codes,
            "os_errno":     (os_errno_m.group(2), os_errno_m.group(3)) if os_errno_m else None,
            "trace_file":   trace_path,          # kept for backward compat
            "trace_path":   trace_path,          # Phase A: full path to .trc
            "incident_id":  incident_id,         # Phase A: numeric incident ID
            "incident_path": incident_path,      # Phase A: directory of trace file
            "pdb_name":     _extract_pdb(block_text),
            "bgproc_died":  bgproc_m.group(1) if bgproc_m else None,
            "instance_msg": inst_m.group(1) if inst_m else None,
            "severity":     severity,
            "raw":          block_text,
            "lines":        list(current_block_lines),
        })

    for line in lines:
        # Try classic timestamp
        ts = _parse_classic_ts(line)
        if ts:
            flush_block()
            current_block_lines = [line]
            current_ts = ts
            current_ts_str = line.strip()
            continue

        # Try XML timestamp
        ts = _parse_xml_ts(line)
        if ts:
            flush_block()
            current_block_lines = [line]
            current_ts = ts
            current_ts_str = line.strip()
            continue

        # Try Plain ISO timestamp (Phase E/F)
        ts = _parse_iso_ts(line)
        if ts:
            flush_block()
            current_block_lines = [line]
            current_ts = ts
            current_ts_str = line.strip()
            continue

        current_block_lines.append(line)

    flush_block()
    return entries


def parse_alert_log_file(filepath: str) -> list:
    """Parse alert.log from filesystem."""
    with open(filepath, "r", errors="replace") as f:
        return parse_alert_log_text(f.read())


_ORA_LINE_SINGLE = re.compile(r"(ORA-\d{5})\s*:\s*(.*)$", re.I)
_ORA_00312_LINE = re.compile(
    r"ORA-00312:\s*online\s+log\s+(\d+)\s+thread\s+(\d+):\s*['\"]?(.*?)['\"]?\s*$",
    re.I,
)
_ORA_00353_LINE = re.compile(r"ORA-00353:.*?near\s+block\s+(\d+)", re.I)
_CORRUPTION_TIME_IN_ORA = re.compile(
    r"\btime\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{2}:\d{2}:\d{2})\b",
    re.I,
)
_LGWR_TERM_LINE = re.compile(
    r"(LGWR|DBWR|CKPT|ARC\d+|SMON|PMON)\s*\(\s*ospid:\s*(\d+)\):\s*terminating\s+the\s+instance"
    r"(?:\s+due\s+to\s+error\s+(\d+))?",
    re.I,
)
_ORA_ROLE_HINT = {
    "ORA-27072": "DB_IO_SYMPTOM",
    "ORA-00312": "OBJECT_LOCATOR",
    "ORA-00353": "FATAL_DB_SYMPTOM",
    "ORA-15080": "ASM_CONSEQUENCE",
    "ORA-15081": "ASM_CONSEQUENCE",
    "ORA-15130": "ASM_CONSEQUENCE",
    "ORA-01017": "AUTHENTICATION_FAILURE",
    "ORA-00257": "ARCHIVER_STUCK",
    "ORA-00600": "INTERNAL_ERROR",
    "ORA-07445": "INTERNAL_ERROR",
}


def parse_alert_log_normalized_events(
    text: str,
    *,
    source_file: str = "",
    source_path: str = "",
    incident_year: int | None = None,
) -> list:
    """
    Line-oriented normalized evidence events for alert/trace style text.
    Does not replace parse_alert_log_text (block parser); use for unified evidence pipeline.
    """
    from src.parsers.normalized_event_schema import ensure_normalized_event
    from src.parsers.evidence_timestamp import parse_line_timestamp

    sp = (source_path or "").strip()
    sf = (source_file or "").strip() or (os.path.basename(sp) if sp else "")

    events: list[dict] = []
    all_lines = (text or "").splitlines()
    cur_ts = None
    cur_ts_raw = None
    cur_tc = "LOW"

    for i, line in enumerate(all_lines, start=1):
        s = line.strip()
        if not s:
            continue
        tsinfo = parse_line_timestamp(s, incident_year=incident_year)
        ts_hit = tsinfo.get("timestamp")
        if ts_hit is not None:
            traw = str(tsinfo.get("timestamp_raw") or "")
            skip_block_ts = False
            if re.match(r"^ORA-\d{5}\b", s, re.I):
                pos = s.find(traw) if traw else -1
                if pos > 12 or _CORRUPTION_TIME_IN_ORA.search(s):
                    skip_block_ts = True
            if not skip_block_ts:
                cur_ts = ts_hit
                cur_ts_raw = tsinfo.get("timestamp_raw")
                cur_tc = tsinfo.get("timestamp_confidence") or "HIGH"

        mlg = _LGWR_TERM_LINE.search(s)
        if mlg:
            err = mlg.group(3)
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "alert_log",
                "timestamp": cur_ts,
                "timestamp_raw": cur_ts_raw,
                "timestamp_confidence": cur_tc,
                "layer": "DB",
                "process": mlg.group(1),
                "pid": mlg.group(2),
                "code": "LGWR_INSTANCE_TERMINATION",
                "code_type": "PROCESS_EVENT",
                "mapped_code_hint": "ORA-00353" if err == "353" else (f"ORA-{int(err):05d}" if err and err.isdigit() else None),
                "role_hint": "FINAL_IMPACT",
                "severity": "CRITICAL",
                "failure_family": "INSTANCE_TERMINATION",
                "message": s[:2000],
                "parse_confidence": "HIGH",
                "tags": ["ALERT_LOG", "NON_ORA"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="alert_log_parser", raw=s)
            )
            continue

        m312 = _ORA_00312_LINE.search(s)
        if m312:
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "alert_log",
                "timestamp": cur_ts,
                "timestamp_raw": cur_ts_raw,
                "timestamp_confidence": cur_tc,
                "layer": "DB",
                "code": "ORA-00312",
                "code_type": "ORA",
                "role_hint": _ORA_ROLE_HINT.get("ORA-00312"),
                "redo_group": m312.group(1),
                "redo_thread": m312.group(2),
                "file_path": m312.group(3).strip(),
                "severity": "ERROR",
                "failure_family": "REDO",
                "message": s[:2000],
                "parse_confidence": "HIGH",
                "tags": ["ALERT_LOG"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="alert_log_parser", raw=s)
            )
            continue

        m353 = _ORA_00353_LINE.search(s)
        if m353:
            details: dict = {}
            ctm = _CORRUPTION_TIME_IN_ORA.search(s)
            if ctm:
                details["corruption_time"] = ctm.group(1)
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "alert_log",
                "timestamp": cur_ts,
                "timestamp_raw": cur_ts_raw,
                "timestamp_confidence": cur_tc,
                "layer": "DB",
                "code": "ORA-00353",
                "code_type": "ORA",
                "role_hint": _ORA_ROLE_HINT.get("ORA-00353"),
                "block": m353.group(1),
                "severity": "CRITICAL",
                "failure_family": "REDO_CORRUPTION",
                "message": s[:2000],
                "parse_confidence": "HIGH",
                "tags": ["ALERT_LOG"],
                "details": details,
            }
            events.append(
                ensure_normalized_event(partial, parser_name="alert_log_parser", raw=s)
            )
            continue

        mlinux = _OS_ERRNO.search(s)
        if mlinux and "ORA-" not in s[:20]:
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "alert_log",
                "timestamp": cur_ts,
                "timestamp_raw": cur_ts_raw,
                "timestamp_confidence": cur_tc,
                "layer": "OS",
                "os_errno": mlinux.group(2),
                "linux_error": mlinux.group(3).strip()[:500],
                "code": f"OS_ERRNO_{mlinux.group(2)}",
                "code_type": "OS_PATTERN",
                "severity": "ERROR",
                "failure_family": "IO",
                "message": s[:2000],
                "parse_confidence": "HIGH",
                "tags": ["ALERT_LOG", "LINUX_ERRNO"],
            }
            events.append(
                ensure_normalized_event(partial, parser_name="alert_log_parser", raw=s)
            )
            continue

        mora = _ORA_LINE_SINGLE.match(s)
        if mora:
            code = mora.group(1).upper()
            partial = {
                "line_number": i,
                "source_file": sf or None,
                "source_path": sp or None,
                "source_type": "alert_log",
                "timestamp": cur_ts,
                "timestamp_raw": cur_ts_raw,
                "timestamp_confidence": cur_tc,
                "layer": "ASM" if code.startswith("ORA-15") else "DB",
                "code": code,
                "code_type": "ORA",
                "role_hint": _ORA_ROLE_HINT.get(code),
                "message": mora.group(2).strip()[:2000],
                "severity": "CRITICAL" if code in ("ORA-00353", "ORA-00600", "ORA-07445") else "ERROR",
                "failure_family": "IO" if code == "ORA-27072" else ("ASM" if code.startswith("ORA-15") else "DB"),
                "parse_confidence": "HIGH",
                "tags": ["ALERT_LOG"],
            }
            if code == "ORA-27072":
                win = "\n".join(all_lines[max(0, i - 6) : i + 2])
                em = _OS_ERRNO.search(win)
                if em:
                    partial["os_errno"] = em.group(2)
                    partial["linux_error"] = em.group(3).strip()[:500]
            events.append(
                ensure_normalized_event(partial, parser_name="alert_log_parser", raw=s)
            )

    return events


def extract_hostname_from_alert(entries: list, fallback_path: str = "") -> Optional[str]:
    """
    Try to extract hostname from alert.log path.
    Alert.log is typically at:
      $ORACLE_BASE/diag/rdbms/<db_name>/<instance_name>/trace/alert_<instance>.log
    """
    if fallback_path:
        m = re.search(r"/diag/rdbms/\w+/(\w+)/trace/", fallback_path)
        if m:
            return m.group(1)
    return None
