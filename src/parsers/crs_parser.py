"""
crs_parser.py — Parses Oracle CRS/Grid Infrastructure log files.

CRS log format (ocssd.log, crsd.log, alert_<SID>.log CRS section):
  2024-03-21 02:44:17.821 [CSSD(18821)]CRS-1618: Node dbhost02 is not responding to heartbeat.
  2024-03-21 02:44:19.182 [CSSD(18821)]CRS-1625: Node dbhost02 is being evicted.

Also parses alerthistory from Exadata cellcli.
"""

import re
from datetime import datetime
from typing import Optional

# ── CRS timestamp + message pattern ───────────────────────────
_CRS_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)"
    r"\s+\[(?P<component>[^\]]+)\]"
    r"(?P<crs_code>CRS-\d+)?:?\s*"
    r"(?P<message>.+)$"
)

# ── CRS code to OS_PATTERN mapping ─────────────────────────────
_CRS_CODE_MAP = {
    "CRS-1618": "BONDING_FAILOVER_EVENT",  # Node not responding to heartbeat
    "CRS-1625": "BONDING_FAILOVER_EVENT",  # Node being evicted
    "CRS-1632": "BONDING_FAILOVER_EVENT",  # Server being stopped
    "CRS-5011": "NTP_TIME_JUMP",           # Clock offset too large
    "CRS-1009": "CGROUP_OOM_KILL",         # Resource out of memory
    "CRS-2674": None,                       # Start of resource — informational
    "CRS-2676": None,                       # Start succeeded — informational
    "CRS-6011": None,                       # Resource online — informational
}

# CRS codes that indicate node eviction
_EVICTION_CODES = {"CRS-1618", "CRS-1625", "CRS-1632", "CRS-2999", "CRS-5017"}

# CRS codes that indicate resource failures
_RESOURCE_FAIL_CODES = {"CRS-2674", "CRS-5011", "CRS-1009"}

# Severity based on CRS code
_CRS_SEVERITY = {
    "CRS-1618": "CRITICAL",
    "CRS-1625": "CRITICAL",
    "CRS-1632": "CRITICAL",
    "CRS-5011": "CRITICAL",
    "CRS-1009": "CRITICAL",
    "CRS-2674": "ERROR",
    "CRS-2676": "INFO",
    "CRS-6011": "INFO",
}

# Informational CRS codes — false positives
_CRS_FALSE_POSITIVES = {
    "CRS-2676", "CRS-6011", "CRS-2672", "CRS-5702",
    "CRS-0215", "CRS-2791"
}

# Node name extract from CRS messages
_NODE_NAME = re.compile(r"[Nn]ode (\S+)\s+(?:is|being|has)")
_RESOURCE_NAME = re.compile(r"resource '([^']+)'")


def _parse_crs_ts(ts_str: str) -> Optional[datetime]:
    ts_str = ts_str.strip()
    for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(ts_str[:len(fmt.replace("%f","000000"))], fmt)
        except ValueError:
            continue
    return None


def parse_crs_line(line: str) -> Optional[dict]:
    """Parse a single CRS log line."""
    m = _CRS_LINE.match(line.strip())
    if not m:
        return None

    crs_code = m.group("crs_code")
    if not crs_code:
        # Try to extract from message
        code_m = re.search(r"(CRS-\d+)", m.group("message"))
        crs_code = code_m.group(1) if code_m else None

    ts = _parse_crs_ts(m.group("ts"))
    message = m.group("message")

    is_false_positive = crs_code in _CRS_FALSE_POSITIVES
    severity = _CRS_SEVERITY.get(crs_code, "ERROR")
    os_pattern = _CRS_CODE_MAP.get(crs_code)

    node_m = _NODE_NAME.search(message)
    res_m = _RESOURCE_NAME.search(message)

    return {
        "timestamp":       ts,
        "timestamp_str":   m.group("ts"),
        "component":       m.group("component"),
        "crs_code":        crs_code,
        "message":         message,
        "severity":        severity,
        "os_pattern":      os_pattern,
        "is_eviction":     crs_code in _EVICTION_CODES,
        "is_false_positive": is_false_positive,
        "affected_node":   node_m.group(1) if node_m else None,
        "resource_name":   res_m.group(1) if res_m else None,
        "raw":             line.rstrip(),
        "log_source":      "CRS_LOG",
        "platform":        "LINUX",
    }


def parse_crs_text(text: str) -> list:
    """Parse CRS log content from string. Returns list of parsed line dicts."""
    entries = []
    for line in text.splitlines():
        parsed = parse_crs_line(line)
        if parsed:
            entries.append(parsed)
    return entries


def parse_crs_file(filepath: str) -> list:
    """Parse CRS log from filesystem."""
    with open(filepath, "r", errors="replace") as f:
        return parse_crs_text(f.read())


# ── Exadata cellcli alerthistory parser ───────────────────────

_CELL_ENTRY_START = re.compile(r"^name:\s+\S+")
_CELL_FIELD = re.compile(r"^(\w+):\s+(.+)$")


def parse_cellcli_text(text: str) -> list:
    """
    Parse Exadata cellcli alerthistory output.
    Returns list of cell alert dicts.
    """
    entries = []
    current = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue

        m = _CELL_FIELD.match(line)
        if m:
            current[m.group(1)] = m.group(2).strip()

    if current:
        entries.append(current)

    result = []
    for entry in entries:
        severity_raw = entry.get("severity", "").lower()
        severity = "CRITICAL" if "critical" in severity_raw else "ERROR" if "warning" in severity_raw else "INFO"
        msg = entry.get("message", "")
        os_pattern = None
        if "Flash disk" in msg and "failed" in msg.lower():
            os_pattern = "SCSI_DISK_TIMEOUT"
        elif "Hard disk" in msg and "failed" in msg.lower():
            os_pattern = "SCSI_DISK_TIMEOUT"
        elif "Interconnect" in msg:
            os_pattern = "BONDING_FAILOVER_EVENT"

        result.append({
            "name":       entry.get("name"),
            "alert_type": entry.get("alertType"),
            "message":    msg,
            "severity":   severity,
            "device":     entry.get("metricObjectName"),
            "os_pattern": os_pattern,
            "log_source": "EXADATA_CELLCLI",
            "platform":   "EXADATA",
            "raw":        str(entry),
        })

    return result
