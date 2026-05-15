"""
PRISM session merge helpers (Option C).

Merged raw text is rebuilt from all non-zip turns on every diagnosis run.
ZIP bundles are stored on disk under .prism_session_cache/<session_id>/ and referenced by turn metadata.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

TURN_BOUNDARY = "\n\n# --- PRISM session turn ---\n\n"
_ORA_RE = re.compile(r"\bORA-\d{5}\b", re.I)
_PIN_PATTERNS = [
    re.compile(r"\b(ORA-\d{5}|TNS-\d+|CRS-\d+|PRVG-\d+)\b", re.I),
    re.compile(r"\b(LGWR|terminating the instance|instance terminated)\b", re.I),
    re.compile(r"\b(FATAL|PANIC|I/O error|Input/output error|timeout|corrupt|dismount)\b", re.I),
    re.compile(r"\b(FLASH_IO_TIMEOUT|SCSI_DISK_TIMEOUT|MULTIPATH|FC_HBA_RESET)\b", re.I),
]


def _extract_pinned_signal_lines(turns: list[dict[str, Any]], max_lines: int = 220) -> list[str]:
    """
    Keep high-value lines across the full session so root signals survive text caps.
    """
    out: list[str] = []
    seen: set[str] = set()
    seen_ora: set[str] = set()
    for i, t in enumerate(turns):
        if t.get("kind") == "zip":
            continue
        body = (t.get("content") or "").strip()
        if not body:
            continue
        label = (t.get("label") or "").strip() or str(t.get("kind", "turn"))
        for ln in body.splitlines():
            line = (ln or "").strip()
            if not line:
                continue
            keep = any(p.search(line) for p in _PIN_PATTERNS)
            oras = [m.group(0).upper() for m in _ORA_RE.finditer(line)]
            if oras:
                # Guarantee first appearance of each ORA survives caps.
                if any(o not in seen_ora for o in oras):
                    keep = True
                    seen_ora.update(oras)
            if not keep:
                continue
            sig = line.lower()
            if sig in seen:
                continue
            seen.add(sig)
            out.append(f"[turn {i + 1}:{label}] {line}")
            if len(out) >= max_lines:
                return out
    return out


def load_prism_limits(cfg_path: str | None) -> tuple[int, int, int, int]:
    """
    Returns max_merged_chars, max_turn_chars, max_zip_bytes, max_zip_files.

    ``max_merged_chars`` / ``max_turn_chars``: use ``0`` or a negative value in YAML for **no limit**
    (full merged string or full per-turn paste/file/lab body). Large values use more RAM and time.
    """
    max_merged = 450_000
    max_turn = 400_000
    max_zip_bytes = 120 * 1024 * 1024
    max_zip_files = 120
    if cfg_path and Path(cfg_path).is_file():
        try:
            import yaml

            with open(cfg_path, encoding="utf-8") as f:
                y = yaml.safe_load(f) or {}
            ps = y.get("prism_session") or {}
            max_merged = int(ps.get("max_merged_chars", max_merged))
            max_turn = int(ps.get("max_turn_chars", max_turn))
            max_zip_bytes = int(ps.get("max_zip_bytes", max_zip_bytes))
            max_zip_files = int(ps.get("max_zip_files", max_zip_files))
        except Exception:
            pass
    return max_merged, max_turn, max_zip_bytes, max_zip_files


def _safe_filename(name: str) -> str:
    base = (name or "bundle").strip().replace(" ", "_")
    out = "".join(c for c in base if c.isalnum() or c in "._-")
    return (out[:120] or "bundle") + ".zip"


def merge_turns_to_raw(turns: list[dict[str, Any]], max_merged: int) -> str:
    """Concatenate all non-zip turn bodies with stable headers (full session raw)."""
    parts: list[str] = []
    for i, t in enumerate(turns):
        if t.get("kind") == "zip":
            continue
        label = (t.get("label") or "").strip() or str(t.get("kind", "turn"))
        hdr = f"# PRISM turn {i + 1} kind={t.get('kind')} label={label}\n"
        body = t.get("content") or ""
        parts.append(hdr + body)
    out = TURN_BOUNDARY.join(parts).strip()
    # max_merged <= 0 means no merged-session cap (entire concatenation is passed through).
    if max_merged and max_merged > 0 and len(out) > max_merged:
        pins = _extract_pinned_signal_lines(turns)
        pin_block = ""
        if pins:
            pin_block = (
                "\n\n# --- PRISM pinned signals (preserved across cap) ---\n"
                + "\n".join(f"- {x}" for x in pins)
            )
        marker = (
            "\n\n# [PRISM: merged session text size cap reached; using head/tail + pinned signals. "
            "Full turn content remains in session state/cache.]\n"
        )
        reserve = len(marker) + len(pin_block) + 64
        budget = max(0, max_merged - reserve)
        head_n = int(budget * 0.45)
        tail_n = max(0, budget - head_n)
        head = out[:head_n]
        tail = out[-tail_n:] if tail_n else ""
        out = head + marker + pin_block + ("\n\n# --- PRISM tail window ---\n" + tail if tail else "")
    return out


def turn_append_paste(turns: list[dict[str, Any]], text: str, max_turn: int) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return turns
    if max_turn and max_turn > 0:
        chunk = text[:max_turn]
        if len(text) > max_turn:
            chunk += "\n# [PRISM: this paste was truncated to max_turn_chars]\n"
    else:
        chunk = text
    out = list(turns)
    out.append({"kind": "paste", "label": "log_paste", "content": chunk})
    return out


def turn_append_file(turns: list[dict[str, Any]], filename: str, text: str, max_turn: int) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return turns
    fn = (filename or "uploaded.log").strip() or "uploaded.log"
    if max_turn and max_turn > 0:
        chunk = text[:max_turn]
        if len(text) > max_turn:
            chunk += "\n# [PRISM: this file body was truncated to max_turn_chars]\n"
    else:
        chunk = text
    out = list(turns)
    out.append({"kind": "file", "label": fn, "content": chunk})
    return out


def turn_append_lab(turns: list[dict[str, Any]], merged_lab_text: str, max_turn: int) -> list[dict[str, Any]]:
    """Forensic lab: one synthetic turn from concatenated lab panes."""
    merged_lab_text = (merged_lab_text or "").strip()
    if not merged_lab_text:
        return turns
    if max_turn and max_turn > 0:
        chunk = merged_lab_text[:max_turn]
        if len(merged_lab_text) > max_turn:
            chunk += "\n# [PRISM: lab bundle truncated to max_turn_chars]\n"
    else:
        chunk = merged_lab_text
    out = list(turns)
    out.append({"kind": "lab", "label": "forensic_lab", "content": chunk})
    return out


def turn_append_zip(
    turns: list[dict[str, Any]],
    cache_dir: Path,
    filename: str,
    zip_bytes: bytes,
    max_zip_bytes: int,
) -> list[dict[str, Any]]:
    if len(zip_bytes) > max_zip_bytes:
        raise ValueError(
            f"ZIP is too large for this session ({len(zip_bytes)} bytes). "
            f"Limit is {max_zip_bytes} bytes (prism_session.max_zip_bytes)."
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    idx = len(turns) + 1
    rel = f"turn_{idx:03d}_{_safe_filename(filename)}"
    dest = cache_dir / rel
    dest.write_bytes(zip_bytes)
    out = list(turns)
    out.append({"kind": "zip", "label": (filename or "bundle.zip").strip(), "relpath": rel, "content": ""})
    return out


def collect_zip_paths(turns: list[dict[str, Any]], cache_dir: Path) -> list[str]:
    paths: list[str] = []
    for t in turns:
        if t.get("kind") != "zip":
            continue
        rel = t.get("relpath")
        if not rel:
            continue
        p = (cache_dir / rel).resolve()
        if p.is_file():
            paths.append(str(p))
    return paths


def build_lab_merged_text(
    lab_db_log: str,
    lab_os_log: str,
    lab_cell_log: str,
    lab_trace_log: str,
) -> str:
    parts: list[str] = []
    if (lab_db_log or "").strip():
        parts.append("# LAB: database_alert\n" + lab_db_log.strip())
    if (lab_os_log or "").strip():
        parts.append("# LAB: syslog_dmesg\n" + lab_os_log.strip())
    if (lab_cell_log or "").strip():
        parts.append("# LAB: exadata_cell\n" + lab_cell_log.strip())
    if (lab_trace_log or "").strip():
        parts.append("# LAB: trace_snippet\n" + lab_trace_log.strip())
    return "\n\n".join(parts).strip()
