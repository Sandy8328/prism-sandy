"""
evidence_timestamp.py — Shared timestamp extraction for parser layer.

Does not assign wall-clock year for syslog-style dates without explicit policy.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

_TS_SPECS: list[tuple[str, re.Pattern, str]] = [
    (
        "ISO_TZ",
        re.compile(
            r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2}))\b"
        ),
        "HIGH",
    ),
    (
        "ISO_SPACE",
        re.compile(r"\b(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\b"),
        "HIGH",
    ),
    (
        "ORACLE_ALERT_CLASSIC",
        re.compile(
            r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
            r"(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4})\s*$"
        ),
        "HIGH",
    ),
    (
        "DMY_DASH_UPPER",
        re.compile(r"\b(\d{2}-[A-Z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})\b", re.I),
        "HIGH",
    ),
    (
        "MDY_SLASH",
        re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4}\s+\d{2}:\d{2}:\d{2})\b"),
        "HIGH",
    ),
    (
        "YMD_SLASH",
        re.compile(r"\b(\d{4}/\d{1,2}/\d{1,2}\s+\d{2}:\d{2}:\d{2})\b"),
        "HIGH",
    ),
]


def parse_line_timestamp(
    line: str,
    *,
    incident_year: int | None = None,
) -> dict[str, Any]:
    """
    Return dict: timestamp (datetime|None), timestamp_raw, timestamp_confidence,
    inferred_year (bool).
    """
    line = line.strip()
    for name, pat, conf in _TS_SPECS:
        m = pat.search(line)
        if not m:
            continue
        if name == "ORACLE_ALERT_CLASSIC":
            raw = m.group(0).strip()
        else:
            raw = (m.group(1) if m.lastindex else m.group(0)).strip()
        try:
            if name == "ORACLE_ALERT_CLASSIC":
                dt = datetime.strptime(
                    f"{m.group(2)} {m.group(3)} {m.group(4)} {m.group(5)}",
                    "%b %d %H:%M:%S %Y",
                )
                return {
                    "timestamp": dt,
                    "timestamp_raw": raw,
                    "timestamp_confidence": conf,
                    "inferred_year": False,
                }
            dt = date_parser.parse(raw, fuzzy=False)
            return {
                "timestamp": dt,
                "timestamp_raw": raw,
                "timestamp_confidence": conf,
                "inferred_year": False,
            }
        except (ValueError, TypeError, OverflowError):
            continue

    # Syslog without year: "Mar 16 07:30:12"
    m2 = re.match(
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})(?:\.(\d+))?\b",
        line,
        re.I,
    )
    if m2 and incident_year is not None:
        try:
            raw = f"{m2.group(1)} {m2.group(2)} {m2.group(3)} {incident_year}"
            dt = datetime.strptime(raw, "%b %d %H:%M:%S %Y")
            return {
                "timestamp": dt,
                "timestamp_raw": m2.group(0),
                "timestamp_confidence": "MEDIUM",
                "inferred_year": True,
            }
        except ValueError:
            pass
    if m2:
        return {
            "timestamp": None,
            "timestamp_raw": m2.group(0),
            "timestamp_confidence": "LOW",
            "inferred_year": False,
        }

    return {
        "timestamp": None,
        "timestamp_raw": None,
        "timestamp_confidence": "LOW",
        "inferred_year": False,
    }
