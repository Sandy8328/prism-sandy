"""
Resolve human-readable ORA meanings for correlation tables.

Priority:
  1. Extracted text from data/runbooks/ora_meanings.json (built from Oracle PDF)
  2. Curated _ORA_ROLE_CATALOG strings from event_correlation
  3. Gemini one-liner when PDF marks llm or meaning missing / contact-support-only
  4. Short deterministic fallback
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_JSON = _PROJECT_ROOT / "data" / "runbooks" / "ora_meanings.json"

_PLACEHOLDER = "See Oracle error documentation / PDF runbook."

_entries: dict[str, dict[str, Any]] | None = None
_json_mtime: float | None = None


def _json_path() -> Path:
    try:
        import yaml

        cfg_path = _PROJECT_ROOT / "config" / "settings.yaml"
        if cfg_path.is_file():
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            p = (cfg.get("ora_meanings") or {}).get("json_path")
            if p:
                raw = Path(p)
                return raw if raw.is_absolute() else (_PROJECT_ROOT / raw).resolve()
    except Exception:
        pass
    return _DEFAULT_JSON


def _load_entries() -> dict[str, dict[str, Any]]:
    global _entries, _json_mtime
    path = _json_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _entries = {}
        _json_mtime = None
        return _entries
    if _entries is not None and _json_mtime == mtime:
        return _entries
    with open(path, encoding="utf-8") as f:
        root = json.load(f)
    raw = root.get("entries") if isinstance(root, dict) else root
    _entries = raw if isinstance(raw, dict) else {}
    _json_mtime = mtime
    return _entries


def _llm_enabled() -> bool:
    try:
        import yaml

        with open(_PROJECT_ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if not (cfg.get("llm") or {}).get("enabled"):
            return False
        return bool(os.getenv("GEMINI_API_KEY", "").strip())
    except Exception:
        return bool(os.getenv("GEMINI_API_KEY", "").strip())


_llm_cache: dict[str, str] = {}


def _ora_meaning_llm(ora: str) -> str | None:
    if ora in _llm_cache:
        return _llm_cache[ora]
    try:
        from src.agent.llm_client import call_gemini_ora_meaning_one_liner

        line = call_gemini_ora_meaning_one_liner(ora)
    except Exception:
        line = None
    if line:
        _llm_cache[ora] = line
        return line
    return None


def resolve_observed_ora_meaning(ora: str, catalog_meaning: str | None) -> str:
    """
    Meaning string for observed ORA correlation table rows.
    """
    code = (ora or "").strip().upper()
    cat = (catalog_meaning or "").strip()
    ent = _load_entries().get(code)

    if ent and isinstance(ent, dict):
        use_llm = bool(ent.get("llm"))
        m = (ent.get("m") or "").strip()
        if m and not use_llm:
            return m
        if use_llm or not m:
            if _llm_enabled():
                guess = _ora_meaning_llm(code)
                if guess:
                    return guess
            if m:
                return m

    if cat and cat != _PLACEHOLDER:
        return cat

    if _llm_enabled():
        guess = _ora_meaning_llm(code)
        if guess:
            return guess

    return f"{code}: definition not in bundled Oracle message extract — verify in My Oracle Support or database error messages reference."


def reset_cache_for_tests() -> None:
    global _entries, _json_mtime, _llm_cache
    _entries = None
    _json_mtime = None
    _llm_cache.clear()
