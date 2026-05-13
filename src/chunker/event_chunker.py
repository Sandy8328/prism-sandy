"""
event_chunker.py — Groups parsed log entries into event chunks for the vector store.

Chunking rules (from chunking_rules.md):
  - alert.log:          One chunk per timestamp block
  - /var/log/messages:  60-second time windows per hostname+severity
  - dmesg:              Related entries (same subsystem within 5 sec)
  - CRS logs:           One chunk per CRS event group
  - AIX errpt:          One chunk per errpt entry
  - iostat/vmstat/df:   One chunk per problematic device/row
  - Max chunk: 50 lines | Overlap: 3 lines

Each chunk becomes one Qdrant point + one DuckDB row.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

from src.parsers.alert_log_parser import _CLASSIC_TS

import yaml
import os
from src.parsers.trace_parser import TraceParser
from src.parsers.security_parser import SecurityParser
from src.parsers.audit_parser import OracleAuditParser
from src.parsers.cell_log_parser import CellLogParser

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
try:
    with open(_CONFIG_PATH, "r") as f:
        _config = yaml.safe_load(f)
except Exception:
    _config = {}

# ── Constants ───────────────────────────────────────────────────
MAX_CHUNK_LINES     = _config.get("chunking", {}).get("max_chunk_lines", 50)
CHUNK_OVERLAP_LINES = _config.get("chunking", {}).get("chunk_overlap_lines", 3)
TIME_WINDOW_SEC     = _config.get("chunking", {}).get("time_window_sec", 60)   # syslog grouping window
CRS_WINDOW_SEC      = _config.get("chunking", {}).get("crs_window_sec", 30)    # CRS event grouping window

# Metric log source → category mapping (extensible via settings.yaml)
_METRIC_CATEGORY_MAP: dict = _config.get("chunking", {}).get("metric_source_category_map", {
    "iostat":    "DISK",
    "df":        "DISK",
    "smartctl":  "DISK",
    "vmstat":    "MEMORY",
    "svmon":     "MEMORY",
    "meminfo":   "MEMORY",
    "sar_cpu":   "CPU",
    "sar_q":     "CPU",
    "lparstat":  "CPU",
    "network":   "NETWORK",
    "conntrack": "NETWORK",
})

def _category_for_metric_source(log_source: str) -> str:
    """Map a metric log source name to its diagnostic category."""
    ls_lower = log_source.lower()
    for key, category in _METRIC_CATEGORY_MAP.items():
        if key in ls_lower:
            return category
    return "OS"  # safe generic fallback instead of silently returning MEMORY


def _make_chunk_id(collection_id: str, source: str, index: int, ts: str = "") -> str:
    """Generate deterministic chunk ID from source material."""
    raw = f"{collection_id}:{source}:{index}:{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_chunk(
    chunk_id: str,
    collection_id: str,
    hostname: str,
    log_source: str,
    timestamp_start: Optional[datetime],
    timestamp_end: Optional[datetime],
    category: str,
    sub_category: str,
    severity: str,
    ora_code: str,
    os_pattern: str,
    platform: str,
    errno: str,
    device: str,
    lines: list,
    keywords: list = None,
    linked_chunks: list = None,
    # Phase A — trace file fields (optional, default empty)
    trace_path: str = "",
    incident_id: str = "",
    incident_path: str = "",
) -> dict:
    raw_text = "\n".join(lines)
    return {
        "chunk_id":        chunk_id,
        "collection_id":   collection_id,
        "hostname":        hostname or "unknown",
        "log_source":      log_source,
        "timestamp_start": timestamp_start.isoformat() if timestamp_start else None,
        "timestamp_end":   timestamp_end.isoformat() if timestamp_end else None,
        "category":        category,
        "sub_category":    sub_category,
        "severity":        severity,
        "ora_code":        ora_code or "",
        "os_pattern":      os_pattern or "",
        "platform":        platform or "UNKNOWN",
        "errno":           errno or "",
        "device":          device or "",
        "keywords":        keywords or [],
        "raw_text":        raw_text,
        "line_count":      len(lines),
        "linked_chunks":   linked_chunks or [],
        # Phase A — trace file fields
        "trace_path":      trace_path or "",
        "incident_id":     incident_id or "",
        "incident_path":   incident_path or "",
    }


# ── Alert.log chunker ───────────────────────────────────────────

def chunk_alert_log(entries: list, hostname: str, platform: str, collection_id: str) -> list:
    """
    One chunk per alert.log timestamp block.
    Each entry from alert_log_parser is already a block.
    """
    chunks = []
    for i, entry in enumerate(entries):
        if entry["severity"] == "INFO" and not entry["ora_codes"]:
            continue  # Skip pure informational blocks

        ora_code = entry["ora_codes"][0] if entry["ora_codes"] else ""
        lines = entry["lines"]
        
        # [Edge Case 9: Chunking Boundary Split]
        # Apply MAX_CHUNK_LINES but dynamically suspend if inside a stack trace
        current_chunk_lines = []
        in_stack_trace = False
        chunk_index = 0
        
        def flush_alert_chunk():
            nonlocal chunk_index, current_chunk_lines
            if not current_chunk_lines:
                return
            chunk_id = _make_chunk_id(collection_id, "alert_log", f"{i}_{chunk_index}",
                                       entry.get("timestamp_str", ""))
            chunks.append(_build_chunk(
                chunk_id=chunk_id,
                collection_id=collection_id,
                hostname=hostname,
                log_source="ALERT_LOG",
                timestamp_start=entry.get("timestamp"),
                timestamp_end=entry.get("timestamp"),
                category="ORACLE",
                sub_category="ALERT",
                severity=entry["severity"],
                ora_code=ora_code,
                os_pattern="",
                platform=platform,
                errno=str(entry["os_errno"][0]) if entry["os_errno"] else "",
                device="",
                lines=list(current_chunk_lines),
                keywords=entry["ora_codes"],
                # Phase A — pass trace fields from parsed alert entry
                trace_path=entry.get("trace_path") or "",
                incident_id=entry.get("incident_id") or "",
                incident_path=entry.get("incident_path") or "",
            ))
            chunk_index += 1

        for line in lines:
            # Detect start of stack trace
            if "Call Trace:" in line or "Caused by:" in line or "Exception in thread" in line or line.strip().startswith("at "):
                in_stack_trace = True
            # Detect end of stack trace (blank line or returning to normal log format)
            elif in_stack_trace and (not line.strip() or line.startswith("ORA-") or _CLASSIC_TS.match(line.strip())):
                in_stack_trace = False
                
            current_chunk_lines.append(line)
            
            # Flush if limit reached AND not inside an atomic block
            if len(current_chunk_lines) >= MAX_CHUNK_LINES and not in_stack_trace:
                flush_alert_chunk()
                current_chunk_lines = current_chunk_lines[-CHUNK_OVERLAP_LINES:]
                
        flush_alert_chunk()
        
    return chunks


# ── Syslog chunker ──────────────────────────────────────────────

def _severity_for_syslog_entry(entry: dict) -> str:
    msg = entry.get("message", "").lower()
    if any(k in msg for k in ["error", "fail", "fatal", "critical", "emerg", "alert"]):
        return "CRITICAL" if any(k in msg for k in ["fatal","emerg","panic"]) else "ERROR"
    if "warn" in msg:
        return "WARNING"
    return "INFO"


def _keywords_from_message(message: str) -> list:
    """Extract notable keywords from log message."""
    words = set()
    for pattern in [
        r"ORA-\d{5}", r"sd[a-z]+", r"hdisk\d+", r"bond\d+", r"qla2xxx",
        r"nf_conntrack", r"oom-killer", r"EXT4-fs", r"XFS", r"multipathd",
        r"nfs:.*server", r"kernel panic", r"soft lockup", r"hard lockup",
        r"FAILED|failed", r"ERROR|error", r"TIMEOUT|timeout",
    ]:
        import re
        for m in re.finditer(pattern, message, re.I):
            words.add(m.group(0)[:30])
    return list(words)[:10]


def chunk_syslog(entries: list, hostname: str, platform: str, collection_id: str) -> list:
    """
    Group syslog entries into 60-second time windows.
    Each window of entries on the same host with CRITICAL/ERROR severity = one chunk.
    INFO entries without any adjacent errors are skipped.
    """
    chunks = []
    if not entries:
        return chunks

    window_start = None
    window_entries = []

    def flush_window(idx: int):
        if not window_entries:
            return
        # Only emit if at least one entry is non-INFO
        severities = [_severity_for_syslog_entry(e) for e in window_entries]
        max_sev = ("CRITICAL" if "CRITICAL" in severities
                   else "ERROR" if "ERROR" in severities
                   else "WARNING" if "WARNING" in severities
                   else "INFO")
        if max_sev == "INFO":
            return

        lines = [e["raw"] for e in window_entries]
        all_msgs = " ".join(e.get("message","") for e in window_entries)
        ts_start = window_entries[0].get("timestamp")
        ts_end   = window_entries[-1].get("timestamp")
        host = hostname or window_entries[0].get("hostname") or "unknown"

        chunk_id = _make_chunk_id(collection_id, "syslog", idx,
                                   ts_start.isoformat() if ts_start else "")
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=host,
            log_source="VAR_LOG_MESSAGES",
            timestamp_start=ts_start,
            timestamp_end=ts_end,
            category="OS",
            sub_category="",
            severity=max_sev,
            ora_code="",
            os_pattern="",
            platform=platform,
            errno="",
            device="",
            lines=lines[:MAX_CHUNK_LINES],
            keywords=_keywords_from_message(all_msgs),
        ))

    in_stack_trace = False

    for i, entry in enumerate(entries):
        ts = entry.get("timestamp")
        raw_msg = entry.get("raw", "")
        
        # Detect start/end of stack trace block
        if "Call Trace:" in raw_msg or "Caused by:" in raw_msg or "Exception in thread" in raw_msg or raw_msg.strip().startswith("at "):
            in_stack_trace = True
        elif in_stack_trace and (not raw_msg.strip() or "]" in raw_msg and ":" in raw_msg):
            # Syslog normal line often has `] :` or similar
            in_stack_trace = False

        if window_start is None:
            window_start = ts
            window_entries = [entry]
        elif ts and window_start and (ts - window_start).total_seconds() > TIME_WINDOW_SEC:
            # If time gap > window, flush UNLESS we are in an atomic stack trace block
            if not in_stack_trace:
                flush_window(i)
                window_start = ts
                window_entries = [entry]
            else:
                window_entries.append(entry)
        else:
            window_entries.append(entry)

        # Flush if size limit reached UNLESS in atomic stack trace block
        if len(window_entries) >= MAX_CHUNK_LINES and not in_stack_trace:
            flush_window(i)
            # Keep last CHUNK_OVERLAP_LINES as overlap for next chunk
            window_entries = window_entries[-CHUNK_OVERLAP_LINES:]
            window_start = window_entries[0].get("timestamp") if window_entries else ts

    flush_window(len(entries))
    return chunks


# ── CRS chunker ─────────────────────────────────────────────────

def chunk_crs(entries: list, hostname: str, platform: str, collection_id: str) -> list:
    """
    Group CRS entries into event chunks.
    Eviction event + surrounding entries = one chunk.
    False positives are excluded.
    """
    chunks = []
    if not entries:
        return chunks

    # Filter false positives
    entries = [e for e in entries if not e.get("is_false_positive")]
    if not entries:
        return chunks

    # Group entries within 30-second windows
    window_entries = []
    window_start = None

    def flush_crs(idx):
        if not window_entries:
            return
        lines = [e["raw"] for e in window_entries]
        ts_start = window_entries[0].get("timestamp")
        ts_end   = window_entries[-1].get("timestamp")
        eviction = any(e.get("is_eviction") for e in window_entries)
        severity = "CRITICAL" if eviction else max(
            (e.get("severity","INFO") for e in window_entries),
            key=lambda s: {"CRITICAL":3,"ERROR":2,"WARNING":1,"INFO":0}.get(s,0),
            default="INFO"
        )
        os_pattern = next((e.get("os_pattern") for e in window_entries if e.get("os_pattern")), "")
        node = next((e.get("affected_node") for e in window_entries if e.get("affected_node")), "")
        crs_codes = list({e.get("crs_code") for e in window_entries if e.get("crs_code")})

        chunk_id = _make_chunk_id(collection_id, "crs", idx,
                                   ts_start.isoformat() if ts_start else "")
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=hostname or node or "unknown",
            log_source="CRS_LOG",
            timestamp_start=ts_start,
            timestamp_end=ts_end,
            category="NETWORK" if "BONDING" in (os_pattern or "") else "CRS",
            sub_category="RAC",
            severity=severity,
            ora_code="ORA-29740" if eviction else "",
            os_pattern=os_pattern,
            platform=platform,
            errno="",
            device="",
            lines=lines[:MAX_CHUNK_LINES],
            keywords=crs_codes,
        ))

    for i, entry in enumerate(entries):
        ts = entry.get("timestamp")
        if window_start is None:
            window_start = ts
            window_entries = [entry]
        elif ts and window_start and (ts - window_start).total_seconds() > CRS_WINDOW_SEC:
            flush_crs(i)
            window_entries = [entry]
            window_start = ts
        else:
            window_entries.append(entry)

    flush_crs(len(entries))
    return chunks


# ── AIX errpt chunker ──────────────────────────────────────────

def chunk_aix_errpt(entries: list, collection_id: str) -> list:
    """One chunk per errpt entry."""
    chunks = []
    for i, entry in enumerate(entries):
        chunk_id = _make_chunk_id(collection_id, "aix_errpt", i,
                                   str(entry.get("timestamp", "")))
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=entry.get("hostname", "unknown"),
            log_source="AIX_ERRPT",
            timestamp_start=entry.get("timestamp"),
            timestamp_end=entry.get("timestamp"),
            category=entry.get("category", "DISK"),
            sub_category="HARDWARE",
            severity=entry.get("severity", "ERROR"),
            ora_code="",
            os_pattern=entry.get("os_pattern", ""),
            platform="AIX",
            errno="",
            device=entry.get("resource", ""),
            lines=entry.get("raw", "").splitlines(),
            keywords=[entry.get("label",""), entry.get("identifier","")],
        ))
    return chunks


# ── Metric chunker (iostat, vmstat, df) ─────────────────────────

def chunk_metrics(metric_rows: list, log_source: str, hostname: str,
                  platform: str, collection_id: str) -> list:
    """One chunk per flagged metric row (severity != INFO)."""
    chunks = []
    for i, row in enumerate(metric_rows):
        if row.get("severity", "INFO") == "INFO":
            continue
        chunk_id = _make_chunk_id(collection_id, log_source.lower(), i)
        pattern = row.get("os_pattern") or (row.get("patterns", [None])[0])
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=hostname,
            log_source=log_source,
            timestamp_start=None,
            timestamp_end=None,
            category=_category_for_metric_source(log_source),
            sub_category="METRIC",
            severity=row.get("severity", "ERROR"),
            ora_code="",
            os_pattern=pattern or "",
            platform=platform,
            errno="",
            device=row.get("device", row.get("filesystem", "")),
            lines=[row.get("raw", str(row))],
            keywords=row.get("patterns", []),
        ))
    return chunks
# ── Trace File chunker ──────────────────────────────────────────

def chunk_trace_file(file_content: str, parent_chunk_id: str, hostname: str, platform: str, collection_id: str) -> list:
    """
    Parse an Oracle trace file and create chunks for its sections.
    All chunks are linked to the parent_chunk_id (the alert log entry).
    """
    parser = TraceParser()
    data = parser.parse_trace_text(file_content)
    chunks = []
    
    # 1. Process Metadata Chunk
    meta = data.get("metadata", {})
    if meta:
        meta_lines = [f"{k}: {v}" for k, v in meta.items()]
        chunk_id = _make_chunk_id(collection_id, "trace_meta", 0, meta.get("sid", "0"))
        print(f"  [CHUNKER] Creating Trace Metadata chunk: {chunk_id}")
        print(f"            Linked to Parent Alert Chunk: {parent_chunk_id}")
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=hostname,
            log_source="TRACE_META",
            timestamp_start=None,
            timestamp_end=None,
            category="ORACLE",
            sub_category="TRACE_HEADER",
            severity="INFO",
            ora_code="",
            os_pattern="",
            platform=platform,
            errno="",
            device="",
            lines=meta_lines,
            linked_chunks=[parent_chunk_id]
        ))

    # 2. Section Chunks (Call Stack, Error Stack, etc.)
    for name, content in data.get("sections", {}).items():
        if not content.strip():
            continue
            
        lines = content.splitlines()
        # Highlight interesting frames if it's a call stack
        keywords = []
        if name == "call_stack":
            keywords = parser.analyze_call_stack(content)
            
        chunk_id = _make_chunk_id(collection_id, f"trace_{name}", 0, parent_chunk_id)
        print(f"  [CHUNKER] Creating {name.upper()} chunk: {chunk_id}")
        if keywords:
            print(f"            Highlighted {len(keywords)} critical stack frames")
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=hostname,
            log_source=f"TRACE_{name.upper()}",
            timestamp_start=None,
            timestamp_end=None,
            category="ORACLE",
            sub_category=f"TRACE_{name.upper()}",
            severity="ERROR",
            ora_code="",
            os_pattern="",
            platform=platform,
            errno="",
            device="",
            lines=lines,
            keywords=keywords,
            linked_chunks=[parent_chunk_id]
        ))
        
    return chunks


# ── Security & Audit Correlation ────────────────────────────────

def chunk_security_log(entries: list, hostname: str, platform: str, collection_id: str) -> list:
    """
    Parse security logs and create chunks.
    """
    parser = SecurityParser()
    chunks = []
    
    # Simple grouping: one chunk per security event for high-fidelity correlation
    for i, entry in enumerate(entries):
        parsed = parser.parse_line(entry["raw"])
        if not parsed:
            continue
            
        chunk_id = _make_chunk_id(collection_id, "security", i, entry.get("timestamp_str", ""))
        print(f"  [CHUNKER] Creating Security chunk: {chunk_id} ({parsed['event_type']})")
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=hostname,
            log_source="OS_SECURE",
            timestamp_start=entry.get("timestamp"),
            timestamp_end=entry.get("timestamp"),
            category="SECURITY",
            sub_category=parsed["event_type"],
            severity=parsed["severity"],
            ora_code="",
            os_pattern="",
            platform=platform,
            errno="",
            device="",
            lines=[entry["raw"]],
            keywords=[parsed["event_type"]]
        ))
    return chunks

def chunk_audit_log(entries: list, hostname: str, platform: str, collection_id: str) -> list:
    """
    Parse Oracle audit logs and create chunks.
    """
    parser = OracleAuditParser()
    chunks = []
    
    for i, entry in enumerate(entries):
        parsed = parser.parse_audit_text(entry["raw"])
        if not parsed:
            continue
            
        chunk_id = _make_chunk_id(collection_id, "audit", i, entry.get("timestamp_str", ""))
        print(f"  [CHUNKER] Creating Audit chunk: {chunk_id} (RC: {parsed.get('returncode')})")
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=hostname,
            log_source="DB_AUDIT",
            timestamp_start=entry.get("timestamp"),
            timestamp_end=entry.get("timestamp"),
            category="SECURITY",
            sub_category="DB_AUDIT",
            severity=parsed["severity"],
            ora_code=parsed.get("returncode", ""),
            os_pattern="",
            platform=platform,
            errno="",
            device="",
            lines=[entry["raw"]],
            keywords=[parsed.get("action", "")]
        ))
    return chunks

def correlate_security_to_db(db_chunks: list, sec_chunks: list, window_sec: int = 60):
    """
    Temporal Correlation Logic:
    If a security event and a DB event happen on the same host within window_sec, link them.
    """
    for db in db_chunks:
        if not db.get("timestamp_start"): continue
        db_ts = datetime.fromisoformat(db["timestamp_start"])
        
        for sec in sec_chunks:
            if not sec.get("timestamp_start"): continue
            if sec["hostname"] != db["hostname"]: continue
            
            sec_ts = datetime.fromisoformat(sec["timestamp_start"])
            diff = abs((db_ts - sec_ts).total_seconds())
            
            print(f"  [CORRELATE] Checking DB {db['chunk_id']} vs SEC {sec['chunk_id']} (Gap: {diff}s)")
            if diff <= window_sec:
                print(f"  [LINK] >>> SUCCESS: Stitching security event to DB incident")
                # Bidirectional link
                if sec["chunk_id"] not in db["linked_chunks"]:
                    db["linked_chunks"].append(sec["chunk_id"])
                if db["chunk_id"] not in sec["linked_chunks"]:
                    sec["linked_chunks"].append(db["chunk_id"])

def chunk_cell_logs(entries: list, cell_name: str, platform: str, collection_id: str) -> list:
    """
    Parse Exadata Cell logs and create chunks.
    """
    parser = CellLogParser()
    chunks = []
    
    for i, entry in enumerate(entries):
        # The CellLogParser has already extracted the timestamp and message
        chunk_id = _make_chunk_id(collection_id, f"cell_{cell_name}", i, entry.get("timestamp_str", ""))
        
        # Ensure timestamp is a datetime object for _build_chunk
        ts = entry.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except:
                ts = None

        # We'll use the generic pattern matcher later, but for now we tag it
        chunks.append(_build_chunk(
            chunk_id=chunk_id,
            collection_id=collection_id,
            hostname=cell_name,
            log_source="CELL_ALERT_LOG",
            timestamp_start=ts,
            timestamp_end=ts,
            category="HARDWARE",
            sub_category="EXADATA_CELL",
            severity="INFO", # Will be overridden by scorer/pattern matcher
            ora_code="",
            os_pattern="",
            platform=platform,
            errno="",
            device=cell_name,
            lines=[entry["raw"]],
            keywords=[cell_name, "CELLSRV"]
        ))
    return chunks
