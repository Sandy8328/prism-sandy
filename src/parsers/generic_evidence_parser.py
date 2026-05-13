"""
generic_evidence_parser.py — Fallback evidence extraction from arbitrary text.

Emits normalized-style dicts (partial) — caller runs ensure_normalized_event.
"""

from __future__ import annotations

import re
from typing import Any

_ORA = re.compile(r"\b(ORA-\d{5})\b", re.I)
_TNS = re.compile(r"\b(TNS-\d+)\b", re.I)
_CRS = re.compile(r"\b(CRS-\d+)\b", re.I)
_TRACE = re.compile(r"(\S+\.(?:trc|TRC))\b")
_DEV = re.compile(r"\b(sd[a-z]+|dm-\d+|nvme\d+n\d+|hdisk\d+)\b", re.I)
# ASM names start with a letter; avoid +00:00 style false positives.
_DG = re.compile(
    r"(?<![0-9.])\+([A-Za-z][A-Z0-9_$#]*)\b|diskgroup\s+['\"]?([A-Za-z][A-Z0-9_$#]*)['\"]?\b",
    re.I,
)


def extract_generic_events(
    text: str,
    *,
    source_file: str = "",
    source_path: str = "",
    parser_name: str = "generic_evidence_parser",
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        s = line.strip()
        if len(s) < 6:
            continue
        # Leave sshd/sudo/auth lines to security_parser + unified routing (avoid GENERIC_FAILURE_LINE).
        if re.search(
            r"\bsshd\b|\bsudo(?:\[|\b)|failed\s+password|authentication\s+failure|invalid\s+user",
            s,
            re.I,
        ):
            continue
        codes = []
        code_type = None
        for pat, typ in ((_ORA, "ORA"), (_TNS, "TNS"), (_CRS, "CRS")):
            for m in pat.finditer(s):
                codes.append(m.group(1))
                code_type = typ
        if not codes and not any(
            k in s.lower()
            for k in (
                "error",
                "failed",
                "failure",
                "timeout",
                "i/o",
                "offline",
                "kernel",
                "multipath",
            )
        ):
            continue
        tr = _TRACE.search(s)
        dv = _DEV.search(s)
        dg = _DG.search(s)
        dg_name = None
        if dg:
            dg_name = (dg.group(1) or dg.group(2) or "").strip() or None
        generic_code = codes[0] if codes else None
        if not generic_code:
            sl = s.lower()
            if tr:
                generic_code = "TRACE_FILE_REFERENCE"
            elif "timeout" in sl:
                generic_code = "GENERIC_TIMEOUT_LINE"
            elif "offline" in sl:
                generic_code = "GENERIC_OFFLINE_LINE"
            elif "fail" in sl or "failure" in sl:
                generic_code = "GENERIC_FAILURE_LINE"
            elif "error" in sl or "i/o" in sl:
                generic_code = "GENERIC_ERROR_LINE"
            else:
                generic_code = "GENERIC_EVIDENCE_LINE"
        events.append(
            {
                "line_number": i,
                "source_file": source_file or None,
                "source_path": source_path or None,
                "source_type": "generic_text",
                "layer": "UNKNOWN",
                "code": generic_code,
                "code_type": code_type or "GENERIC_PATTERN",
                "message": s[:2000],
                "trace_file": tr.group(1) if tr else None,
                "device": dv.group(1) if dv else None,
                "diskgroup": dg_name,
                "severity": "ERROR" if codes or "fail" in s.lower() else "WARNING",
                "parse_confidence": "LOW" if not codes else "MEDIUM",
                "raw": s,
                "tags": ["GENERIC_FALLBACK"],
            }
        )
    return events
