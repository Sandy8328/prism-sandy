#!/usr/bin/env python3
"""
One-shot builder: extract ORA-xxxxx messages from Oracle Database Error Messages PDF
into data/runbooks/ora_meanings.json for runtime lookup.

Run from repo root:
  python scripts/build_ora_meanings_from_pdf.py

Requires: pypdf
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PDF = _ROOT / "data" / "runbooks" / "database-error-messages.pdf"
_DEFAULT_OUT = _ROOT / "data" / "runbooks" / "ora_meanings.json"

_ORA_START = re.compile(r"\b(ORA-\d{5}):")
_SUPPORT_SERVICES = re.compile(r"Contact Oracle Support Services", re.I)
_MAX_MEANING = 320


def _clip_meaning(text: str) -> str:
    """One or two short sentences; word-safe truncation to fit UI cells."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    if len(t) <= _MAX_MEANING:
        return t
    # Prefer end of first sentence if it fits
    for sep in (". ", "? ", "! "):
        i = t.find(sep)
        if 30 < i < _MAX_MEANING:
            return t[: i + 1].strip()
    cut = t[: _MAX_MEANING]
    sp = cut.rfind(" ")
    if sp > 40:
        return cut[:sp].rstrip() + "…"
    return cut.rstrip() + "…"


def _parse_block(block: str, code: str) -> dict:
    """Split ORA block into title, cause, action."""
    # block begins with ORA-nnnnn:
    i = block.find(":")
    if i < 0:
        return {"title": "", "cause": "", "action": ""}
    rest = block[i + 1 :]
    # Split on first Cause: (PDF uses newline before Cause:)
    c_idx = re.search(r"\n\s*Cause:\s*", rest, re.I)
    if not c_idx:
        title = re.sub(r"\s+", " ", rest).strip()
        return {"title": title, "cause": "", "action": ""}
    title = re.sub(r"\s+", " ", rest[: c_idx.start()]).strip()
    after = rest[c_idx.end() :]
    a_idx = re.search(r"\n\s*Action:\s*", after, re.I)
    if not a_idx:
        return {
            "title": title,
            "cause": re.sub(r"\s+", " ", after).strip(),
            "action": "",
        }
    cause = re.sub(r"\s+", " ", after[: a_idx.start()]).strip()
    action = re.sub(r"\s+", " ", after[a_idx.end() :]).strip()
    return {"title": title, "cause": cause, "action": action}


def _cause_usable(cause: str) -> bool:
    c = (cause or "").strip()
    if not c or c.upper() in ("N/A", "NONE", "N/A."):
        return False
    return len(c) >= 10


def _build_meaning_and_flag(title: str, cause: str, action: str) -> tuple[str, bool]:
    """
    Returns (display_meaning, use_llm).
    Prefer Cause text from the PDF. If Action says to contact Oracle Support Services
    and there is no usable Cause, mark for LLM one-liner at runtime.
    """
    cause = (cause or "").strip()
    action = (action or "").strip()
    title = (title or "").strip()

    if _cause_usable(cause):
        return (_clip_meaning(cause), False)

    if _SUPPORT_SERVICES.search(action):
        return ("", True)

    if title:
        return (_clip_meaning(title), False)

    return ("", True)


def extract_from_pdf(pdf_path: Path) -> dict[str, dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for p in reader.pages:
        parts.append(p.extract_text() or "")
    text = "\n".join(parts)

    matches = list(re.finditer(_ORA_START, text))
    by_code: dict[str, dict] = {}
    for i, m in enumerate(matches):
        code = m.group(1).upper()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        parsed = _parse_block(block, code)
        meaning, use_llm = _build_meaning_and_flag(
            parsed["title"], parsed["cause"], parsed["action"]
        )
        by_code[code] = {"m": meaning, "llm": use_llm}
    return by_code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=_DEFAULT_PDF)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = ap.parse_args()
    if not args.pdf.is_file():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    print(f"Reading {args.pdf} …", file=sys.stderr)
    data = extract_from_pdf(args.pdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "entries": data}, f, ensure_ascii=False)
    print(f"Wrote {len(data)} ORA entries → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
