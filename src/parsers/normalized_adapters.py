"""
normalized_adapters.py — Convert legacy parser rows into normalized_event_schema dicts.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

from src.parsers.normalized_event_schema import ensure_normalized_event

# Message-driven OS evidence (per-line), not graph root cause.
_SYSLOG_SIGNALS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r"Abort command issued", re.I), "FC_HBA_ABORT", "OS", "OS_PATTERN", "WARNING"),
    (re.compile(r"Adapter reset issued", re.I), "FC_HBA_RESET", "OS", "OS_PATTERN", "ERROR"),
    (re.compile(r"lpfc.*link down", re.I), "FC_LINK_DOWN", "OS", "OS_PATTERN", "ERROR"),
    (re.compile(r"hostbyte=DID_TIME_OUT|DRIVER_TIMEOUT", re.I), "SCSI_DISK_TIMEOUT", "OS", "OS_PATTERN", "CRITICAL"),
    (re.compile(r"blk_update_request:.*I/O error", re.I), "OS_BLOCK_IO_ERROR", "OS", "OS_PATTERN", "ERROR"),
    (re.compile(r"Buffer I/O error on dev", re.I), "OS_BLOCK_IO_ERROR", "OS", "OS_PATTERN", "ERROR"),
    (re.compile(r"remaining active paths:\s*0|no active paths", re.I), "MULTIPATH_ALL_PATHS_DOWN", "OS", "OS_PATTERN", "CRITICAL"),
    (re.compile(r"Failing path", re.I), "MULTIPATH_PATH_FAILED", "OS", "OS_PATTERN", "WARNING"),
    (re.compile(r"rejecting I/O to offline device", re.I), "DEVICE_OFFLINE", "OS", "OS_PATTERN", "CRITICAL"),
    (re.compile(r"EXT4-fs error|XFS.*I/O error", re.I), "FILESYSTEM_IO_ERROR", "OS", "OS_PATTERN", "ERROR"),
    (re.compile(r"oom-killer|Out of memory", re.I), "OS_OOM_KILLER", "OS", "OS_PATTERN", "CRITICAL"),
    (re.compile(r"No space left on device", re.I), "FILESYSTEM_FULL", "OS", "OS_PATTERN", "CRITICAL"),
]

_SECTOR = re.compile(r"sector\s+(\d+)", re.I)
_SD = re.compile(r"\b(sd[a-z]+|dm-\d+)\b", re.I)
_MPATH = re.compile(r"\b(mpath[a-z0-9_]+)\b", re.I)


def syslog_entries_to_normalized_events(
    entries: list[dict[str, Any]],
    *,
    source_file: str = "",
    source_path: str = "",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, e in enumerate(entries or []):
        msg = e.get("message") or ""
        raw = e.get("raw") or msg
        ts = e.get("timestamp")
        ts_raw = e.get("timestamp_str")
        tc = e.get("timestamp_confidence", "MEDIUM")
        host = e.get("hostname")
        proc = e.get("process")
        pid = e.get("pid")
        for pat, code, layer, ctype, sev in _SYSLOG_SIGNALS:
            if pat.search(msg):
                dev_m = _SD.search(msg)
                mpath_m = _MPATH.search(msg)
                sec_m = _SECTOR.search(msg)
                partial = {
                    "timestamp": ts,
                    "timestamp_raw": ts_raw,
                    "timestamp_confidence": tc,
                    "source_file": source_file or None,
                    "source_path": source_path or None,
                    "source_type": "syslog",
                    "line_number": i + 1,
                    "host": host,
                    "layer": layer,
                    "component": proc,
                    "process": proc,
                    "pid": pid,
                    "code": code,
                    "code_type": ctype,
                    "message": msg[:2000],
                    "severity": sev,
                    "failure_family": "IO",
                    "device": dev_m.group(1) if dev_m else None,
                    "multipath_device": mpath_m.group(1) if mpath_m else None,
                    "block": sec_m.group(1) if sec_m else None,
                    "parse_confidence": "HIGH",
                    "tags": ["SYSLOG_LINE"],
                }
                out.append(
                    ensure_normalized_event(partial, parser_name="syslog_parser", raw=raw)
                )
    return out


def _parse_cell_timestamp(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return date_parser.parse(val, fuzzy=False)
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def cell_entries_to_normalized_events(
    entries: list[dict[str, Any]],
    *,
    source_file: str = "",
    source_path: str = "",
) -> list[dict[str, Any]]:
    out = []
    for i, e in enumerate(entries or []):
        raw = e.get("raw") or ""
        msg = e.get("message") or ""
        ts = _parse_cell_timestamp(e.get("timestamp"))
        ts_raw = e.get("timestamp_str") or (e.get("timestamp") if isinstance(e.get("timestamp"), str) else None)
        details: dict[str, Any] = {}
        if e.get("io_time_ms") is not None:
            details["io_time_ms"] = e.get("io_time_ms")
        sev = e.get("severity") or "ERROR"
        if (e.get("code") or "") == "FLASH_DISK_CRITICAL":
            sev = "CRITICAL"
        partial = {
            "timestamp": ts,
            "timestamp_raw": ts_raw,
            "timestamp_confidence": "HIGH" if ts else ("LOW" if ts_raw else "MEDIUM"),
            "source_file": source_file or None,
            "source_path": source_path or None,
            "source_type": "cell_alert",
            "line_number": i + 1,
            "layer": e.get("layer") or "STORAGE",
            "cell": e.get("cell"),
            "component": e.get("component"),
            "code": e.get("code"),
            "code_type": "STORAGE_PATTERN",
            "message": msg[:2000],
            "flash_disk": e.get("flash_disk"),
            "cell_disk": e.get("cell_disk"),
            "grid_disk": e.get("grid_disk"),
            "asm_group": e.get("asm_group"),
            "asm_disk": e.get("asm_disk"),
            "au": e.get("au"),
            "offset": e.get("offset"),
            "size": e.get("size"),
            "severity": sev,
            "failure_family": e.get("failure_family") or "IO",
            "parse_confidence": e.get("parse_confidence") or "HIGH",
            "tags": ["CELL_LOG"],
            "details": details,
        }
        out.append(ensure_normalized_event(partial, parser_name="cell_log_parser", raw=raw))
    return out
