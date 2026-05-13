"""
cell_log_parser.py — Exadata Storage Cell alert style logs (CELLSRV / MS / RS).

Extracts structured fields only; no RCA.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List

from dateutil import parser as date_parser

# Optional cell host between timezone and CELLSRV|MS|RS (some sites omit host in line).
_TS_START = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*(?:([-+]\d{2}:\d{2}|Z)\s+)?"
    r"(?:(?P<host>\S+)\s+)?(?P<comp>CELLSRV|MS|RS):\s*(?P<msg>.*)$",
    re.I,
)
_WARNING_CODE = re.compile(r"warningCode=(\w+)", re.I)
_FLASH_DISK = re.compile(r"flashDisk=(FD_[^,\s]+)", re.I)
_CELL_DISK = re.compile(r"cellDisk=(CD_[^,\s]+)", re.I)
_GRID_DISK = re.compile(r"(?:at\s+)?griddisk\s+(\S+)|\b(DATA_CD_[^,\s]+)\b", re.I)
_READ_FAIL = re.compile(
    r"Read Failed\.\s*group:(\d+)\s+disk:(\d+)\s+AU:(\d+)\s+offset:(\d+)\s+size:(\d+)",
    re.I,
)
_IO_TIME = re.compile(r"io_time=(\d+)\s*ms", re.I)
_MEDIA_EX = re.compile(r"media read retries exhausted for\s+(\S+)", re.I)
_METRIC_FD_CRIT = re.compile(
    r"metricObjectName:\s*(FD_[^\s,]+).*metricValue:\s*critical",
    re.I,
)
_CELL_BENIGN = re.compile(
    r"no\s+flash\s+disk\s+alerts|no\s+alerts\s+in\s+this\s+interval|"
    r"normal\s+operation|completed\s+successfully|no\s+errors\s+found",
    re.I,
)
_CELL_HW_REPLACE = re.compile(
    r"requires\s+replacement|repeated\s+read\s+retries|Hardware\s+alert:|"
    r"FD_\d+\s+on\s+CD_\d+\s+requires",
    re.I,
)


class CellLogParser:
    def parse_cell_log_text(self, text: str, cell_name: str = "unknown") -> List[dict[str, Any]]:
        entries: List[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for line in (text or "").splitlines():
            m = _TS_START.match(line.strip())
            if m:
                if current:
                    entries.append(current)
                tz = (m.group(2) or "").strip()
                ts_raw = m.group(1) + (f" {tz}" if tz else "")
                ts_for_parse = m.group(1)
                if tz:
                    if tz.upper() == "Z":
                        ts_for_parse = m.group(1) + "Z"
                    elif tz[0] in "+-":
                        ts_for_parse = m.group(1) + tz
                    else:
                        ts_for_parse = m.group(1) + tz
                host_cell = (m.group("host") or "").strip() or cell_name
                comp = m.group("comp").upper()
                rest = m.group("msg")
                ts_dt: datetime | None = None
                ts_parse = ts_for_parse.replace("Z", "+00:00")
                try:
                    ts_dt = date_parser.isoparse(ts_parse)
                except (ValueError, TypeError, OverflowError):
                    try:
                        ts_dt = date_parser.parse(ts_raw.strip(), fuzzy=False)
                    except (ValueError, TypeError, OverflowError):
                        ts_dt = None
                wc = _WARNING_CODE.search(rest)
                fd = _FLASH_DISK.search(rest)
                cd = _CELL_DISK.search(rest)
                gd_m = _GRID_DISK.search(rest)
                grid_disk = (gd_m.group(1) or gd_m.group(2) or "").strip() if gd_m else ""
                rf = _READ_FAIL.search(rest)
                iot = _IO_TIME.search(rest)
                med = _MEDIA_EX.search(rest)
                mfd = _METRIC_FD_CRIT.search(rest)
                flash_crit = bool(mfd) or bool(
                    re.search(
                        r"\bFD_\d+\s+critical\b|^MS:.*\bFD_\d+.*critical", rest, re.I
                    )
                )
                # Prefer concrete IO / flash-critical codes over generic warningCode= labels
                # (a line can carry both warningCode=… and metricObjectName FD_* critical).
                code = None
                if rf:
                    code = "STORAGE_ASM_READ_FAILED"
                elif med:
                    code = "STORAGE_MEDIA_READ_FAILURE"
                elif re.search(r"flashcache\s+read\s+error", rest, re.I):
                    code = "FLASH_CACHE_READ_ERROR"
                elif flash_crit:
                    code = "FLASH_DISK_CRITICAL"
                elif re.search(
                    r"\bIORM\b.*throttl|backend\s+latency\s+spike|IORM\s+throttling", rest, re.I
                ):
                    code = "STORAGE_BACKEND_LATENCY"
                elif wc:
                    code = wc.group(1)
                if code is None and _CELL_BENIGN.search(rest):
                    current = None
                    continue
                if code is None:
                    if _CELL_HW_REPLACE.search(rest):
                        code = "STORAGE_MEDIA_READ_FAILURE"
                    else:
                        code = "CELL_INFORMATIONAL"
                sev = "ERROR"
                if code == "FLASH_DISK_CRITICAL":
                    sev = "CRITICAL"
                elif med or (code and "TIMEOUT" in (code or "").upper()):
                    sev = "CRITICAL"
                elif code == "STORAGE_MEDIA_READ_FAILURE" and _CELL_HW_REPLACE.search(rest):
                    sev = "CRITICAL"
                elif code == "CELL_INFORMATIONAL":
                    sev = "INFO"
                current = {
                    "timestamp_str": ts_raw,
                    "timestamp": ts_dt.isoformat() if ts_dt else None,
                    "cell": host_cell or cell_name,
                    "cell_name": host_cell or cell_name,
                    "component": comp,
                    "message": rest.strip(),
                    "raw": line,
                    "layer": "STORAGE",
                    "code": code,
                    "flash_disk": fd.group(1) if fd else (mfd.group(1) if mfd else None),
                    "cell_disk": cd.group(1) if cd else None,
                    "grid_disk": grid_disk or None,
                    "asm_group": rf.group(1) if rf else None,
                    "asm_disk": rf.group(2) if rf else None,
                    "au": rf.group(3) if rf else None,
                    "offset": rf.group(4) if rf else None,
                    "size": rf.group(5) if rf else None,
                    "io_time_ms": iot.group(1) if iot else None,
                    "severity": sev,
                    "failure_family": "IO",
                    "parse_confidence": "HIGH",
                }
            elif current:
                current["message"] += " " + line.strip()
                current["raw"] += "\n" + line
                rf2 = _READ_FAIL.search(line)
                if rf2 and not current.get("asm_group"):
                    current["asm_group"] = rf2.group(1)
                    current["asm_disk"] = rf2.group(2)
                    current["au"] = rf2.group(3)
                    current["offset"] = rf2.group(4)
                    current["size"] = rf2.group(5)

        if current:
            entries.append(current)
        return entries
