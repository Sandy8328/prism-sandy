"""
pattern_matcher.py — Runs 45 regex patterns against retrieved log chunks.

For each chunk's raw_text, applies patterns from patterns.json:
  match_any:  ANY regex hit → pattern detected (presence score)
  match_all:  ALL regexes must hit → HIGH confidence
  exclude:    if this hits → disqualify pattern (false positive)

Returns:
  [{pattern_id, confidence, matched_any, matched_all, excluded, device, extract}, ...]
"""

from __future__ import annotations
import json
import os
import re
from functools import lru_cache

_PATTERNS_PATH = os.path.join(
    os.path.dirname(__file__), "data", "patterns.json"
)

# Keys that are not pattern entries
_META_KEYS = {"_metric_patterns", "_alert_log_patterns", "_false_positives"}
_ORA_CODE_RE = re.compile(r"(ORA-\d{5})", re.I)


@lru_cache(maxsize=1)
def _load_patterns() -> dict:
    with open(_PATTERNS_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def list_pattern_definition_ids() -> frozenset[str]:
    """Public: pattern_id keys from patterns.json (excludes meta sections)."""
    raw = _load_patterns()
    return frozenset(
        k for k in raw if k not in _META_KEYS and isinstance(raw.get(k), dict)
    )


def clear_pattern_cache():
    _compile_patterns.cache_clear()
    _get_false_positives.cache_clear()
    list_pattern_definition_ids.cache_clear()


def _extract_ora_codes(text: str) -> list[str]:
    """Return unique ORA codes found in text, preserving order."""
    if not text:
        return []
    seen = set()
    codes: list[str] = []
    for match in _ORA_CODE_RE.findall(text):
        normalized = match.upper()
        if normalized not in seen:
            seen.add(normalized)
            codes.append(normalized)
    return codes

@lru_cache(maxsize=1)
def _compile_patterns() -> dict:
    """
    Pre-compile all regex patterns for performance.
    Returns dict: pattern_id → {match_any: [compiled], match_all: [compiled], exclude: [compiled]}
    """
    raw = _load_patterns()
    compiled = {}
    for pid, pdata in raw.items():
        if pid in _META_KEYS or not isinstance(pdata, dict):
            continue
        compiled[pid] = {
            "match_any":  [re.compile(r, re.I | re.M | re.S) for r in pdata.get("match_any", [])],
            "match_all":  [re.compile(r, re.I | re.M | re.S) for r in pdata.get("match_all", [])],
            "exclude":    [re.compile(r, re.I | re.M | re.S) for r in pdata.get("exclude", [])],
            "log_sources":pdata.get("log_sources", []),
            "severity":   pdata.get("severity", "ERROR"),
            "device_extract": re.compile(pdata["device_extract"], re.I) if pdata.get("device_extract") else None,
            "ora_codes_triggered": pdata.get("ora_codes_triggered", []),
        }
    return compiled


@lru_cache(maxsize=1)
def _get_false_positives() -> list:
    raw = _load_patterns()
    fps = raw.get("_false_positives", [])
    return [re.compile(r, re.I | re.M) for r in fps]


def is_false_positive(text: str) -> bool:
    """
    Return True ONLY if the text is a SINGLE-LINE chunk
    and that line is a known false positive.

    For multi-line blobs, individual benign lines must NOT poison
    the entire blob — they are stripped by _strip_false_positive_lines().
    """
    if "\n" in text.strip():
        # Multi-line blob: not a false positive at the blob level
        return False
    for pattern in _get_false_positives():
        if pattern.search(text):
            return True
    return False


def _strip_false_positive_lines(text: str) -> str:
    """
    For a multi-line log blob, remove individual lines that are known
    false positives (benign noise). This prevents benign lines like
    'Thread 1 advanced to log sequence' from poisoning the whole blob.
    Critical error lines (ORA-XXXXX, WARNING, ERROR) are always kept.
    """
    fps = _get_false_positives()
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)   # keep blank lines (preserve structure)
            continue
        # Always keep lines with ORA codes, WARNINGs, ERRORs
        if any(kw in stripped.upper() for kw in ("ORA-", "WARNING", "ERROR", "FAILED", "CRITICAL", "FATAL", "KILLED", "TERMINATED", "DISMOUNT", "READ FAILED")):
            kept.append(line)
            continue
        # Drop if it matches a false positive pattern
        if any(fp.search(stripped) for fp in fps):
            continue
        kept.append(line)
    return "\n".join(kept)


def match_patterns(
    text: str,
    log_source: str = "",
    platform: str = "UNKNOWN",
) -> list[dict]:
    """
    Run all 45 patterns against a text chunk.

    Args:
        text:        raw_text of the chunk
        log_source:  log source ID for source-specific filtering
        platform:    platform for platform-aware patterns

    Returns:
        List of matched pattern results, sorted by confidence descending.
        Only returns patterns with confidence > 0.
    """
    if not text:
        return []

    # For multi-line blobs, strip benign false-positive lines first
    # so they don't poison the entire input
    is_multiline = "\n" in text.strip()
    if is_multiline:
        working_text = _strip_false_positive_lines(text)
        if not working_text.strip():
            return []   # nothing left after stripping — all benign
    else:
        # Single-line chunk: apply full false positive check
        if is_false_positive(text):
            return []
        working_text = text

    compiled = _compile_patterns()
    detected_ora_codes = _extract_ora_codes(working_text)
    results = []

    for pid, pdata in compiled.items():
        # Skip if pattern is not applicable to this log source
        if pdata["log_sources"] and log_source:
            # Normalize log source for comparison
            applicable = any(
                ls.upper() in log_source.upper() or log_source.upper() in ls.upper()
                for ls in pdata["log_sources"]
            )
            if not applicable and pdata["match_any"]:
                continue

        # Check exclude patterns first
        excluded = any(p.search(working_text) for p in pdata["exclude"])
        if excluded:
            continue

        # Check match_any
        any_hits = [p.pattern for p in pdata["match_any"] if p.search(working_text)]
        matched_any = len(any_hits) > 0

        if not matched_any and pdata["match_any"]:
            continue   # Pattern not present at all

        # Check match_all
        all_hits = [p.pattern for p in pdata["match_all"] if p.search(working_text)]
        matched_all = len(all_hits) == len(pdata["match_all"]) if pdata["match_all"] else False

        # Compute pattern confidence
        # Logic:
        #   match_all is EMPTY → any match_any hit is definitive → HIGH (85)
        #   match_all ALL fire → very high confidence → 100
        #   match_all defined but not all fire → proportional (partial match)
        if pdata["match_all"]:
            if matched_all:
                pattern_conf = 100
            elif matched_any:
                # match_all required but didn't fire — partial match
                total = len(pdata["match_any"])
                pattern_conf = int((len(any_hits) / total) * 65) if total > 0 else 40
            else:
                pattern_conf = 0
        else:
            # No match_all requirement — any match_any hit is enough
            if matched_any:
                total = len(pdata["match_any"])
                # Boost: 1 hit = 85, more hits = higher up to 95
                hit_ratio = len(any_hits) / total
                pattern_conf = int(85 + hit_ratio * 10)   # 85–95
            else:
                pattern_conf = 0


        if pattern_conf == 0:
            continue

        # Extract device name if extractor defined
        device = ""
        if pdata["device_extract"]:
            m = pdata["device_extract"].search(working_text)
            if m:
                device = m.group(1) if m.lastindex else m.group(0)

        configured_codes = [c.upper() for c in pdata["ora_codes_triggered"]]
        # Keep configured "likely" ORA impacts, but always include
        # ORA codes directly detected in the current text chunk.
        combined_codes = list(dict.fromkeys(configured_codes + detected_ora_codes))

        results.append({
            "pattern_id":         pid,
            "confidence":         pattern_conf,
            "matched_any":        any_hits[:3],    # top 3 matched regexes
            "matched_all":        matched_all,
            "excluded":           False,
            "device":             device,
            "severity":           pdata["severity"],
            "ora_codes_triggered":combined_codes,
            "log_sources":        pdata["log_sources"],
        })

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


def match_patterns_across_chunks(chunks: list[dict]) -> dict[str, list[dict]]:
    """
    Run pattern matching across all retrieved chunks.
    Returns dict: chunk_id → [matched pattern results]
    """
    results = {}
    for chunk in chunks:
        payload = chunk if "raw_text" in chunk else chunk.get("payload", {})
        chunk_id = payload.get("chunk_id", "")
        text     = payload.get("raw_text", "")
        src      = payload.get("log_source", "")
        plat     = payload.get("platform", "UNKNOWN")
        if chunk_id and text:
            results[chunk_id] = match_patterns(text, log_source=src, platform=plat)
    return results


def aggregate_matched_patterns(
    chunk_pattern_map: dict[str, list[dict]]
) -> list[dict]:
    """
    Aggregate pattern results across all chunks.
    Returns unique patterns sorted by max confidence seen.
    """
    pattern_scores: dict[str, dict] = {}

    for chunk_id, patterns in chunk_pattern_map.items():
        for p in patterns:
            pid = p["pattern_id"]
            if pid not in pattern_scores:
                pattern_scores[pid] = dict(p)
                pattern_scores[pid]["seen_in_chunks"] = [chunk_id]
            else:
                # Keep highest confidence
                if p["confidence"] > pattern_scores[pid]["confidence"]:
                    pattern_scores[pid]["confidence"] = p["confidence"]
                    pattern_scores[pid]["matched_any"] = p["matched_any"]
                    pattern_scores[pid]["matched_all"] = p["matched_all"]
                    pattern_scores[pid]["device"] = p["device"] or pattern_scores[pid]["device"]
                pattern_scores[pid]["seen_in_chunks"].append(chunk_id)

    results = list(pattern_scores.values())
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results
