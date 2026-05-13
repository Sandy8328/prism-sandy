"""
aix_errpt_parser.py — Parses IBM AIX errpt -a output.

AIX errpt format (from 'errpt -a' command):
  LABEL:          DISK_ERR7
  IDENTIFIER:     B5757C89
  Date/Time:      Mon Apr 21 03:14:18 IST 2024
  Node Id:        dbhost01
  Class:          H
  Type:           PERM
  Resource Name:  hdisk2
  Description
  DISK OPERATION ERROR
  Detail Data
  SENSE DATA
  00 00 00 00 70 00 03 ...

Multiple entries separated by dashes or blank lines.
"""

import re
from datetime import datetime
from typing import Optional

# ── Patterns ────────────────────────────────────────────────────

_LABEL       = re.compile(r"^LABEL:\s+(.+)$", re.M)
_IDENTIFIER  = re.compile(r"^IDENTIFIER:\s+([0-9A-F]+)$", re.M)
_DATETIME    = re.compile(r"^Date/Time:\s+(.+)$", re.M)
_NODE_ID     = re.compile(r"^Node Id:\s+(.+)$", re.M)
_CLASS       = re.compile(r"^Class:\s+(.+)$", re.M)
_TYPE        = re.compile(r"^Type:\s+(.+)$", re.M)
_RESOURCE    = re.compile(r"^Resource Name:\s+(.+)$", re.M)
_DESCRIPTION = re.compile(r"^Description\s*\n(.+)$", re.M)

# Separator between errpt entries
_ENTRY_SEP = re.compile(r"^-{10,}$", re.M)

# AIX error type -> severity mapping
_TYPE_SEVERITY = {
    "PERM": "CRITICAL",   # Permanent hardware error
    "TEMP": "ERROR",      # Temporary error
    "PERF": "WARNING",    # Performance degradation
    "UNKN": "WARNING",    # Unknown
    "INFO": "INFO",
}

# AIX error label -> OS_PATTERN mapping
_LABEL_PATTERN_MAP = {
    "DISK_ERR7":          "SCSI_DISK_TIMEOUT",
    "DISK_ERR1":          "SCSI_DISK_TIMEOUT",
    "DISK_ERR6":          "IO_QUEUE_TIMEOUT",
    "MPIO_PATH_ERR":      "MULTIPATH_PATH_FAILED",
    "MPIO_PATH_DEGRADED": "MULTIPATH_DEGRADED",
    "MPIO_ALL_PATHS_DOWN": "MULTIPATH_ALL_PATHS_DOWN",
    "FS_FULL":            "FILESYSTEM_ARCH_FULL",
    "FC_LINK_DOWN":       "FC_HBA_RESET",
    "FC_PORT_LINK_DOWN":  "FC_HBA_RESET",
    "MEM_EPOW":           "ENVIRONMENTAL_POWER_WARNING",
    "LPAR_CAPACITY":      "CPU_STEAL_TIME",
    "NET_ERR_FAIL":       "BONDING_FAILOVER_EVENT",
    "NFS_ERR":            "NFS_MOUNT_TIMEOUT",
}


def _parse_aix_datetime(ts_str: str) -> Optional[datetime]:
    """Parse AIX date/time: 'Mon Apr 21 03:14:18 IST 2024'"""
    ts_str = ts_str.strip()
    # Remove timezone abbreviation (IST, EST, UTC...)
    cleaned = re.sub(r"\s+[A-Z]{2,4}\s+", " ", ts_str)
    for fmt in ["%a %b %d %H:%M:%S %Y", "%c"]:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _get_field(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def parse_errpt_entry(entry_text: str) -> Optional[dict]:
    """Parse a single errpt -a entry block."""
    if not entry_text.strip():
        return None

    label      = _get_field(_LABEL, entry_text)
    identifier = _get_field(_IDENTIFIER, entry_text)
    ts_str     = _get_field(_DATETIME, entry_text)
    node_id    = _get_field(_NODE_ID, entry_text)
    aix_class  = _get_field(_CLASS, entry_text)
    aix_type   = _get_field(_TYPE, entry_text)
    resource   = _get_field(_RESOURCE, entry_text)
    desc       = _get_field(_DESCRIPTION, entry_text)

    if not label:
        return None

    ts = _parse_aix_datetime(ts_str) if ts_str else None
    severity = _TYPE_SEVERITY.get(aix_type, "ERROR")
    os_pattern = _LABEL_PATTERN_MAP.get(label)

    # Determine category from class
    category_map = {
        "H": "DISK",     # Hardware
        "S": "MEMORY",   # Software
        "O": "KERNEL",   # Operator
        "U": "KERNEL",   # Undetermined
    }
    category = category_map.get(aix_class, "DISK") if aix_class else "DISK"

    return {
        "label":       label,
        "identifier":  identifier,
        "timestamp":   ts,
        "timestamp_str": ts_str,
        "hostname":    node_id,
        "aix_class":   aix_class,
        "aix_type":    aix_type,
        "resource":    resource,   # e.g. "hdisk2", "fscsi0"
        "description": desc,
        "severity":    severity,
        "category":    category,
        "os_pattern":  os_pattern,
        "platform":    "AIX",
        "raw":         entry_text.strip(),
    }


def parse_errpt_text(text: str) -> list:
    """
    Parse full errpt -a output (multiple entries).
    Returns list of parsed entry dicts.
    """
    # Split on separator lines
    entries_raw = _ENTRY_SEP.split(text)
    entries = []
    for raw in entries_raw:
        parsed = parse_errpt_entry(raw)
        if parsed:
            entries.append(parsed)
    return entries


def parse_errpt_file(filepath: str) -> list:
    """Parse errpt output file."""
    with open(filepath, "r", errors="replace") as f:
        return parse_errpt_text(f.read())
