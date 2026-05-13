"""
normalized_event_schema.py — Common normalized evidence event schema for all parsers.

Parsers emit facts only; RCA lives in event_correlation.py.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

_ORA_CODE = re.compile(r"^ORA-\d{5}$", re.I)

NORMALIZED_EVENT_KEYS: tuple[str, ...] = (
    "event_id",
    "timestamp",
    "timestamp_raw",
    "timestamp_confidence",
    "source_file",
    "source_path",
    "source_type",
    "line_number",
    "line_start",
    "line_end",
    "host",
    "platform",
    "database",
    "instance",
    "layer",
    "component",
    "process",
    "pid",
    "thread",
    "code",
    "code_type",
    "mapped_code_hint",
    "message",
    "severity",
    "role_hint",
    "failure_family",
    "object_type",
    "object_name",
    "file_path",
    "trace_file",
    "device",
    "multipath_device",
    "diskgroup",
    "asm_group",
    "asm_disk",
    "asm_file",
    "au",
    "offset",
    "block",
    "size",
    "redo_group",
    "redo_thread",
    "redo_sequence",
    "os_errno",
    "linux_error",
    "cell",
    "flash_disk",
    "cell_disk",
    "grid_disk",
    "crs_resource",
    "raw",
    "preview",
    "parse_confidence",
    "parser_name",
    "tags",
    "details",
)


def empty_normalized_event() -> dict[str, Any]:
    return {k: None for k in NORMALIZED_EVENT_KEYS}


def new_event_id(parser_name: str, raw_snippet: str, line_no: int = 0) -> str:
    h = hashlib.sha256(f"{parser_name}|{line_no}|{raw_snippet[:200]}".encode()).hexdigest()[:16]
    return f"ev_{h}"


def ensure_normalized_event(
    partial: dict[str, Any],
    *,
    parser_name: str,
    raw: str,
    preview_max: int = 400,
) -> dict[str, Any]:
    """Merge partial fields into full schema; set event_id, preview, defaults."""
    out = empty_normalized_event()
    for k, v in (partial or {}).items():
        if k in out and v is not None:
            out[k] = v
    out["parser_name"] = parser_name
    out["raw"] = raw if raw is not None else ""
    prev = (raw or "")[:preview_max]
    out["preview"] = prev + ("…" if len(raw or "") > preview_max else "")
    if not out.get("event_id"):
        out["event_id"] = new_event_id(parser_name, raw or "", int(out.get("line_number") or 0))
    if out.get("severity") is None:
        out["severity"] = "UNKNOWN"
    if out.get("layer") is None:
        out["layer"] = "UNKNOWN"
    if out.get("parse_confidence") is None:
        out["parse_confidence"] = "MEDIUM"
    if out.get("tags") is None:
        out["tags"] = []
    if out.get("details") is None:
        out["details"] = {}
    return out


def dedupe_normalized_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Collapse duplicate evidence rows (e.g. same ORA emitted by alert + ASM snippet).
    Primary key: source_path + line_number + code + raw prefix.
    Secondary: same ORA code on same line from different parsers often differs only in
    raw whitespace — collapse on (source_path, line_number, ORA code).
    """
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for e in events or []:
        key = (
            (e.get("source_path") or "") or (e.get("source_file") or ""),
            int(e.get("line_number") or 0),
            (e.get("code") or "").upper(),
            (e.get("raw") or "")[:200],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)

    seen_ora: set[tuple] = set()
    out2: list[dict[str, Any]] = []
    for e in out:
        code = (e.get("code") or "").strip()
        if _ORA_CODE.match(code):
            k2 = (
                (e.get("source_path") or "") or (e.get("source_file") or ""),
                int(e.get("line_number") or 0),
                code.upper(),
            )
            if k2 in seen_ora:
                continue
            seen_ora.add(k2)
        out2.append(e)
    return out2


def normalize_parser_output(parser_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply ensure_normalized_event to each row from a legacy parser list."""
    out = []
    for i, row in enumerate(rows or []):
        raw = row.get("raw") or row.get("raw_text") or str(row.get("message", "")) or ""
        partial = dict(row)
        partial["line_number"] = partial.get("line_number", i + 1)
        out.append(ensure_normalized_event(partial, parser_name=parser_name, raw=raw))
    return out
