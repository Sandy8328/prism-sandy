"""
scorer.py — Computes confidence score for a diagnostic result.

Scoring formula (from implementation_plan.md):
  score = keyword_match × 40  +  bm25 × 30  +  dense × 20  +  temporal_bonus × 10

Where each component is normalized 0-1:
  keyword_match: pattern confidence / 100
  bm25:          bm25_score / max_bm25_score (normalized across results)
  dense:         cosine similarity score (already 0-1)
  temporal_bonus: 1 if correlated, 0.5 if single source, 0 if none

Confidence levels:
  HIGH   ≥ 80%   — reliable root cause, proceed with fix
  MEDIUM 60-79%  — probable root cause, verify first
  LOW    40-59%  — possible root cause, investigate
  NO_MATCH < 40% — cannot determine root cause
"""

from __future__ import annotations
import os
import yaml

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "settings.yaml"
)

with open(_SETTINGS_PATH) as f:
    _cfg = yaml.safe_load(f)

_W_KEYWORD  = _cfg["scoring"]["keyword_match_weight"]   # 40
_W_BM25     = _cfg["scoring"]["bm25_weight"]             # 30
_W_DENSE    = _cfg["scoring"]["dense_weight"]            # 20
_W_TEMPORAL = _cfg["scoring"]["temporal_bonus"]          # 10

_HIGH   = _cfg["thresholds"]["high_confidence"]    # 80
_MEDIUM = _cfg["thresholds"]["medium_confidence"]  # 60
_LOW    = _cfg["thresholds"]["low_confidence"]     # 40


def _confidence_label(score: float) -> str:
    if score >= _HIGH:
        return "HIGH"
    elif score >= _MEDIUM:
        return "MEDIUM"
    elif score >= _LOW:
        return "LOW"
    return "NO_MATCH"


def _normalize_bm25(bm25_score: float, max_bm25: float) -> float:
    """Normalize BM25 score to 0-1 range."""
    if max_bm25 <= 0:
        return 0.0
    return min(bm25_score / max_bm25, 1.0)


def compute_score(
    pattern_confidence: float,   # 0-100 from pattern_matcher
    bm25_score: float,           # raw BM25 score
    dense_score: float,          # cosine similarity 0-1
    temporal_bonus: int,         # 0, 10, or 20
    max_bm25: float = 10.0,      # max BM25 score seen in this query
) -> dict:
    """
    Compute the final confidence score for one pattern match.

    Returns:
    {
      score:      0-100 float
      label:      "HIGH" | "MEDIUM" | "LOW" | "NO_MATCH"
      breakdown:  {keyword, bm25, dense, temporal}
    }
    """
    kw_norm     = pattern_confidence / 100.0
    bm25_norm   = _normalize_bm25(bm25_score, max_bm25)
    dense_norm  = max(0.0, min(dense_score, 1.0))
    temp_norm   = temporal_bonus / (_W_TEMPORAL * 2)   # max bonus = 20 points

    keyword_contrib  = kw_norm    * _W_KEYWORD
    bm25_contrib     = bm25_norm  * _W_BM25
    dense_contrib    = dense_norm * _W_DENSE
    temporal_contrib = temp_norm  * _W_TEMPORAL

    score = keyword_contrib + bm25_contrib + dense_contrib + temporal_contrib
    score = round(min(score, 100.0), 1)

    return {
        "score":   score,
        "label":   _confidence_label(score),
        "breakdown": {
            "keyword":  round(keyword_contrib, 1),
            "bm25":     round(bm25_contrib, 1),
            "dense":    round(dense_contrib, 1),
            "temporal": round(temporal_contrib, 1),
        }
    }


def score_all_candidates(
    fused_results: list[dict],
    chunk_pattern_map: dict[str, list[dict]],
    correlations: dict[str, list[dict]],
) -> list[dict]:
    """
    Score all retrieved chunks and their matched patterns.

    Returns:
        List of scored candidates sorted by score descending:
        [{chunk_id, pattern_id, score, label, breakdown, payload}, ...]
    """
    # Find max BM25 for normalization
    max_bm25 = max(
        (r.get("bm25_score", 0.0) for r in fused_results),
        default=1.0
    )

    # Build lookup maps
    bm25_map   = {r["chunk_id"]: r.get("bm25_score", 0.0) for r in fused_results}
    dense_map  = {r["chunk_id"]: r.get("dense_score", 0.0) for r in fused_results}
    payload_map = {r["chunk_id"]: r.get("payload", {}) for r in fused_results}

    candidates = []

    for chunk_id, patterns in chunk_pattern_map.items():
        if not patterns:
            continue

        bm25_s   = bm25_map.get(chunk_id, 0.0)
        dense_s  = dense_map.get(chunk_id, 0.0)
        payload  = payload_map.get(chunk_id, {})

        # Temporal bonus from correlator
        from src.retrieval.temporal_correlator import compute_temporal_bonus
        temp_bonus = compute_temporal_bonus(correlations, chunk_id)

        # Score top matched pattern for this chunk
        top_pattern = patterns[0]
        scored = compute_score(
            pattern_confidence=top_pattern["confidence"],
            bm25_score=bm25_s,
            dense_score=dense_s,
            temporal_bonus=temp_bonus,
            max_bm25=max_bm25,
        )

        # Evidence-gated confidence policy:
        # ORA_ANY_GENERIC is a catch-all hint, not a final root cause signal.
        # Keep it below the LOW threshold so follow-up evidence is required.
        if top_pattern["pattern_id"] == "ORA_ANY_GENERIC":
            scored["score"] = min(scored["score"], 39.0)
            scored["label"] = _confidence_label(scored["score"])

        candidates.append({
            "chunk_id":   chunk_id,
            "pattern_id": top_pattern["pattern_id"],
            "device":     top_pattern.get("device", ""),
            "score":      scored["score"],
            "label":      scored["label"],
            "breakdown":  scored["breakdown"],
            "payload":    payload,
            "all_patterns": patterns,
            "temporal_bonus": temp_bonus,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def pick_best_candidate(candidates: list[dict]) -> dict | None:
    """
    Pick the single best candidate from scored results.
    Prefers CRITICAL severity chunks when scores are close (within 5 points).
    """
    if not candidates:
        return None

    best = candidates[0]
    # If top two are within 5 points, prefer CRITICAL severity
    if len(candidates) > 1:
        second = candidates[1]
        if best["score"] - second["score"] < 5:
            best_sev   = best["payload"].get("severity", "")
            second_sev = second["payload"].get("severity", "")
            if second_sev == "CRITICAL" and best_sev != "CRITICAL":
                best = second

    return best
