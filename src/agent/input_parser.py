"""
input_parser.py — Parses 3 input modes into a normalized query dict.

Mode 1: ORA code query
  "ORA-27072 on dbhost01 at 2024-03-07 02:44:18"
  "why does ORA-00257 happen"

Mode 2: Raw log paste
  Alert.log block, /var/log/messages lines, dmesg, errpt output

Mode 3: Natural language question
  "What ORA code appears when disk is full?"
  "Which errors happen when archiver stops?"
"""

from __future__ import annotations
import json
import re
from datetime import datetime
from typing import Optional
from dateutil import parser as dp

# ── Patterns ────────────────────────────────────────────────────

_ORA_CODE      = re.compile(r"(ORA-\d{5})", re.I)
_HOSTNAME      = re.compile(r"on\s+(\S+host\S*|\w+\d+\w*)", re.I)
_IP_ADDRESS    = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_TIMESTAMP_STR = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?|\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\b"
)
_SYSLOG_TS     = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"
)
_ALERT_LOG_TS  = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
_ISO_TS        = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})"
)
_AIX_ERRPT     = re.compile(r"^LABEL:\s+\w+", re.M)
_DMESG_LINE    = re.compile(r"^\[\s*[\d.]+\]")
_CELLCLI       = re.compile(r"alertType:|cellDiskType:", re.I)
_WINDOWS_EVT   = re.compile(r"Event ID:\s*\d+|Source:\s+\w+", re.I)

# Natural language question patterns → ORA codes resolved dynamically from graph.json
# Keywords searched against ORA_CODE node description + runbook_title fields.
# Adding a new ORA code to graph.json auto-populates here — no hardcoding needed.
from src.knowledge_graph.graph import get_ora_codes_by_description_keywords as _ora_for

_NL_PATTERNS = [
    (re.compile(r"disk\s+full|archive.*full|arch.*full",    re.I), _ora_for("archiv", "archivelog destination", "limit exceeded for recovery")),
    (re.compile(r"OOM|out.of.memory|memory.*kill",          re.I), _ora_for("unable to allocate", "shared memory", "process memory")),
    (re.compile(r"disk.*fail|I/O.*error|storage",           re.I), _ora_for("i/o error", "synchronous i/o", "file i/o")),
    (re.compile(r"shared.memory|SGA|shmget",                re.I), _ora_for("shared memory", "sga", "shmget")),
    (re.compile(r"semaphore|sem.*limit",                    re.I), _ora_for("semaphore")),
    (re.compile(r"network.*drop|connection.*lost|listener", re.I), _ora_for("connection", "listener", "tns", "network")),
    (re.compile(r"RAC.*evict|node.*evict|cluster.*fail",    re.I), _ora_for("evict", "node evict", "cluster")),
    (re.compile(r"NFS|network.*file",                       re.I), _ora_for("nfs", "network file")),
    (re.compile(r"hugepage|huge.*page",                     re.I), _ora_for("hugepage", "huge page")),
    (re.compile(r"archiver|redo.*log.*arch",                re.I), _ora_for("archiv", "redo log")),
    (re.compile(r"ASM|disk.*group",                         re.I), _ora_for("diskgroup", "asm disk")),
    (re.compile(r"NTP|time.*jump|clock.*step",              re.I), _ora_for("ntp", "time jump", "clock")),
    (re.compile(r"kernel.*panic|soft.*lockup|hang",         re.I), _ora_for("terminated", "fatal error")),
    (re.compile(r"disk\s+full|archive.*full|arch.*full",    re.I | re.S), _ora_for("archiv", "archivelog destination", "limit exceeded for recovery")),
    (re.compile(r"OOM|out.of.memory|memory.*kill",          re.I | re.S), _ora_for("unable to allocate", "shared memory", "process memory")),
    (re.compile(r"disk.*fail|I/O.*error|storage",           re.I | re.S), _ora_for("i/o error", "synchronous i/o", "file i/o")),
    (re.compile(r"shared.memory|SGA|shmget",                re.I | re.S), _ora_for("shared memory", "sga", "shmget")),
    (re.compile(r"semaphore|sem.*limit",                    re.I | re.S), _ora_for("semaphore")),
    (re.compile(r"network.*drop|connection.*lost|listener", re.I | re.S), _ora_for("connection", "listener", "tns", "network")),
    (re.compile(r"RAC.*evict|node.*evict|cluster.*fail",    re.I | re.S), _ora_for("evict", "node evict", "cluster")),
    (re.compile(r"NFS|network.*file",                       re.I | re.S), _ora_for("nfs", "network file")),
    (re.compile(r"hugepage|huge.*page",                     re.I | re.S), _ora_for("hugepage", "huge page")),
    (re.compile(r"archiver|redo.*log.*arch",                re.I | re.S), _ora_for("archiv", "redo log")),
    (re.compile(r"ASM|disk.*group",                         re.I | re.S), _ora_for("diskgroup", "asm disk")),
    (re.compile(r"NTP|time.*jump|clock.*step",              re.I | re.S), _ora_for("ntp", "time jump", "clock")),
    (re.compile(r"kernel.*panic|soft.*lockup|hang",         re.I | re.S), _ora_for("terminated", "fatal error")),
]

# Platform hints from log content
_PLATFORM_HINTS = [
    (re.compile(r"LABEL:\s+\w+\nIDENTIFIER:", re.M | re.S), "AIX"),
    # Oracle alert/catalog: "Linux x86_64", paths "Linux-x86_64", TNS banners, or O/S error lines
    (
        re.compile(
            r"Linux-x86_64(?:\s+Error:)?|Linux\s+x86_64|Linux\s+aarch64|"
            r"TNS\s*:\s*for\s+Linux|TNS\s+for\s+Linux",
            re.I | re.S,
        ),
        "LINUX",
    ),
    (re.compile(r"IBM AIX RISC", re.I | re.S),                     "AIX"),
    (re.compile(r"SunOS-\d+\.\d+ Error:|fmadm", re.I | re.S),"SOLARIS"),
    (re.compile(r"O/S-Error: \(OS \d+\)", re.I | re.S),            "WINDOWS"),
    (re.compile(r"cellDiskType:|cellcli", re.I | re.S),      "EXADATA"),
    (re.compile(r"cloud-agent|oci-metadata", re.I | re.S),   "OCI"),
    (re.compile(r"vCenter|esx", re.I | re.S),                "VMWARE"),
    # Word-boundary match only: bare "rds" matched substrings in "records", "ORDS", etc.
    (re.compile(r"\bAWS\b|\bec2\b|\brds\b", re.I | re.S),   "AWS"),
]


def _observed_layers(text: str) -> list[str]:
    """
    Infer broad evidence layers from raw pasted/uploaded text.
    Used to require corroboration before final answers.
    """
    t = text.upper()
    layers = set()
    if "ORA-" in t or "ERRORS IN FILE" in t or "LGWR" in t or "PMON" in t:
        layers.add("DB")
    if "KERNEL:" in t or "DMESG" in t or "BLK_UPDATE_REQUEST" in t or "MULTIPATHD" in t:
        layers.add("OS")
    if "CELLSRV" in t or "EXAWATCHER" in t or "IORM" in t or "CELLCLI" in t:
        layers.add("INFRA")
    if "FLASH_IO_TIMEOUT" in t or "FLASHDISK" in t or "GRIDDISK" in t or "CELLDISK" in t:
        layers.add("STORAGE")
    if "TRACE/" in t or ".TRC" in t or "CALL STACK" in t:
        layers.add("RDBMS")
    return sorted(layers)


def _detect_input_mode(text: str) -> str:
    """
    Detect which of 3 input modes this is.
    Returns: "ora_code" | "log_paste" | "natural_language"
    """
    stripped = text.strip()

    # Mode 1: starts with ORA code or is purely an ORA code lookup
    if _ORA_CODE.match(stripped) or re.match(r"^ORA-\d{5}", stripped, re.I):
        return "ora_code"

    # Mode 2: looks like a log paste (has timestamps, kernel:, LABEL:, etc.)
    if (
        _SYSLOG_TS.search(stripped)
        or _ALERT_LOG_TS.search(stripped)
        or _ISO_TS.search(stripped)
        or _DMESG_LINE.search(stripped)
        or _AIX_ERRPT.search(stripped)
        or _CELLCLI.search(stripped)
        or _WINDOWS_EVT.search(stripped)
        or "kernel:" in stripped
        or "ORA-" in stripped and "\n" in stripped
    ):
        return "log_paste"

    return "natural_language"


def _extract_from_text(text: str) -> dict:
    """Extract structured fields from any text."""
    ora_codes = list(dict.fromkeys(_ORA_CODE.findall(text)))   # unique, ordered

    # Hostname: prefer explicit "on hostname" mention, else first FQDN-like token
    hostname = None
    m = _HOSTNAME.search(text)
    if m:
        hostname = m.group(1)
    if not hostname:
        # Try syslog hostname (3rd field after timestamp)
        for line in text.splitlines()[:5]:
            parts = line.split()
            if len(parts) >= 4 and _SYSLOG_TS.match(line):
                hostname = parts[3]
                break

    # Timestamp
    timestamp_str = None
    m = _TIMESTAMP_STR.search(text)
    if m:
        timestamp_str = m.group(1)
    elif _SYSLOG_TS.search(text):
        # Use first syslog timestamp
        first_line = text.strip().splitlines()[0]
        ts_m = _SYSLOG_TS.match(first_line)
        if ts_m:
            timestamp_str = ts_m.group(0)

    # Platform
    platform = "UNKNOWN"
    for pattern, plat in _PLATFORM_HINTS:
        if pattern.search(text):
            platform = plat
            break

    return {
        "ora_codes":     ora_codes,
        "primary_ora":   ora_codes[0] if ora_codes else "",
        "hostname":      hostname or "",
        "timestamp_str": timestamp_str or "",
        "platform":      platform,
    }


def _nl_to_ora_hints(text: str) -> list[str]:
    """For natural language questions, suggest related ORA codes."""
    hints = []
    for pattern, codes in _NL_PATTERNS:
        if pattern.search(text):
            hints.extend(codes)
    return list(dict.fromkeys(hints))   # unique, ordered


def _unwrap_structured_log_json(text: str) -> tuple[str, bool]:
    """
    If `text` is JSON (array or object) of log payloads with a `content` field
    (e.g. collector / API export), return joined alert text for parsing and
    pattern matching. Otherwise return (text, False).
    """
    s = text.strip()
    if len(s) < 2 or s[0] not in "[{":
        return text, False
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return text, False

    def row_text(obj: dict) -> str | None:
        if not isinstance(obj, dict):
            return None
        c = obj.get("content") or obj.get("text") or obj.get("log")
        if not isinstance(c, str) or not c.strip():
            return None
        hn = obj.get("hostname") or obj.get("host")
        ts = obj.get("timestamp")
        src = obj.get("file_source") or obj.get("source") or obj.get("filename")
        parts = []
        if hn:
            parts.append(f"host={hn}")
        if ts:
            parts.append(f"time={ts}")
        if src:
            parts.append(f"source={src}")
        head = ("# " + " ".join(parts) + "\n") if parts else ""
        return head + c.strip()

    chunks: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                t = row_text(item)
                if t:
                    chunks.append(t)
    elif isinstance(data, dict):
        logs = data.get("logs")
        if isinstance(logs, list):
            for item in logs:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("filename") or "unknown"
                    body = item.get("text") or item.get("content")
                    if isinstance(body, str) and body.strip():
                        chunks.append(f"# file={name}\n{body.strip()}")
        if not chunks:
            t = row_text(data)
            if t:
                chunks.append(t)

    if not chunks:
        return text, False
    return "\n\n---\n\n".join(chunks), True


def parse_input(raw_input: str) -> dict:
    """
    Main entry point. Parse any user input into a normalized query dict.

    Returns:
    {
      "mode":          "ora_code" | "log_paste" | "natural_language",
      "query":         cleaned query string for embedding,
      "primary_ora":   "ORA-27072" or "",
      "all_ora_codes": ["ORA-27072", ...],
      "hostname":      "dbhost01" or "",
      "timestamp_str": "2024-03-07T02:44:18" or "",
      "platform":      "LINUX" | "AIX" | "SOLARIS" | "WINDOWS" | "EXADATA" | "OCI" | "VMWARE" | "AWS" | "UNKNOWN",
      "nl_ora_hints":  ["ORA-00257", ...],  # only for natural_language mode
      "raw_input":     effective log text (JSON log exports are unwrapped to `content`),
    }
    """
    text = raw_input.strip().replace("\r\n", "\n").replace("\r", "\n")
    unwrapped, used_json = _unwrap_structured_log_json(text)
    if used_json:
        text = unwrapped.replace("\r\n", "\n").replace("\r", "\n")
    mode = _detect_input_mode(text)
    extracted = _extract_from_text(text)

    nl_hints = []
    query = text

    if mode == "natural_language":
        nl_hints = _nl_to_ora_hints(text)
        # For NL queries, enrich query with ORA code hints for better embedding
        if nl_hints:
            query = f"{text} {' '.join(nl_hints)}"

    elif mode == "ora_code":
        # For short ORA code queries, expand with description if available
        primary = extracted["primary_ora"]
        query = text

    elif mode == "log_paste":
        # For log pastes, use the full text — chunker handles it
        query = text

    normalized_events: list = []
    evidence_graph_pattern_ids: list[str] = []
    if mode in ("log_paste", "ora_code") or (
        mode == "natural_language" and len(text) > 500
    ):
        from src.parsers.unified_evidence import (
            extract_normalized_events_unified,
            graph_pattern_ids_from_normalized_events,
        )

        normalized_events = extract_normalized_events_unified(
            text,
            source_file="pasted_input",
            source_path="pasted_input",
        )
        evidence_graph_pattern_ids = graph_pattern_ids_from_normalized_events(
            normalized_events
        )

    return {
        "mode":          mode,
        "query":         query,
        "primary_ora":   extracted["primary_ora"],
        "all_ora_codes": extracted["ora_codes"],
        "hostname":      extracted["hostname"],
        "timestamp_str": extracted["timestamp_str"],
        "platform":      extracted["platform"],
        "observed_layers": _observed_layers(text),
        "nl_ora_hints":  nl_hints,
        "raw_input":     text,
        "normalized_events": normalized_events,
        "evidence_graph_pattern_ids": evidence_graph_pattern_ids,
    }
