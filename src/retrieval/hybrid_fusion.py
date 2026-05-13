"""
hybrid_fusion.py — Combines BM25 + Dense search scores using Reciprocal Rank Fusion (RRF).

RRF formula:
  rrf_score(d) = Σ  1 / (k + rank_i(d))

Where:
  k = 60  (smoothing constant, standard value)
  rank_i = rank of document d in result list i

Weights (from settings.yaml):
  BM25:  40%
  Dense: 60%

Returns top_k merged results with fused score.
"""

from __future__ import annotations
import yaml
import duckdb
from typing import Optional

# ── Config ──────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    _cfg = yaml.safe_load(f)

BM25_WEIGHT     = _cfg["retrieval"]["bm25_weight"]    # 0.40
DENSE_WEIGHT    = _cfg["retrieval"]["dense_weight"]   # 0.60
TOP_K           = _cfg["retrieval"]["top_k"]
DUCKDB_PATH     = _cfg["duckdb"]["db_path"]
TIME_WINDOW     = _cfg["retrieval"]["time_window_minutes"]
RRF_K           = _cfg["retrieval"]["rrf_k"]           # RRF smoothing constant
PREFILTER_LIMIT = _cfg["retrieval"]["prefilter_limit"] # SQL pre-filter row cap


def _rrf_score(rank: int, weight: float) -> float:
    """RRF score for a single result at given rank."""
    return weight * (1.0 / (RRF_K + rank + 1))


def reciprocal_rank_fusion(
    bm25_results: list[dict],
    dense_results: list[dict],
    top_k: int = TOP_K,
) -> list[dict]:
    """
    Merge BM25 and dense search results using weighted RRF.

    Args:
        bm25_results:  [{chunk_id, bm25_score}, ...]  sorted by bm25_score desc
        dense_results: [{chunk_id, score, payload}, ...] sorted by cosine desc

    Returns:
        [{chunk_id, rrf_score, bm25_rank, dense_rank, payload}, ...]
        sorted by rrf_score descending
    """
    scores: dict[str, dict] = {}

    # Process BM25 results
    for rank, result in enumerate(bm25_results):
        cid = result["chunk_id"]
        if cid not in scores:
            scores[cid] = {"chunk_id": cid, "rrf_score": 0.0,
                           "bm25_rank": None, "dense_rank": None, "payload": {}}
        scores[cid]["rrf_score"] += _rrf_score(rank, BM25_WEIGHT)
        scores[cid]["bm25_rank"] = rank + 1
        scores[cid]["bm25_score"] = result.get("bm25_score", 0.0)

    # Process Dense results
    for rank, result in enumerate(dense_results):
        cid = result["chunk_id"]
        if cid not in scores:
            scores[cid] = {"chunk_id": cid, "rrf_score": 0.0,
                           "bm25_rank": None, "dense_rank": None, "payload": {}}
        scores[cid]["rrf_score"] += _rrf_score(rank, DENSE_WEIGHT)
        scores[cid]["dense_rank"] = rank + 1
        scores[cid]["dense_score"] = result.get("score", 0.0)
        scores[cid]["payload"] = result.get("payload", {})

    # Sort by RRF score descending
    merged = sorted(scores.values(), key=lambda x: x["rrf_score"], reverse=True)
    return merged[:top_k]


# ── DuckDB pre-filter ───────────────────────────────────────────

def prefilter_chunks(
    hostname: Optional[str] = None,
    timestamp_str: Optional[str] = None,
    severity_list: Optional[list[str]] = None,
    platform: Optional[str] = None,
    ora_code: Optional[str] = None,
    time_window_minutes: int = TIME_WINDOW,
) -> list[str]:
    """
    Use DuckDB to return chunk_ids matching filter criteria.
    This narrows the search space before BM25 + Dense.

    Returns:
        List of chunk_id strings. Empty list = no filter applied (use all).
    """
    conditions = []
    params = []

    if hostname:
        conditions.append("hostname = ?")
        params.append(hostname)

    if platform:
        conditions.append("platform = ?")
        params.append(platform)

    if ora_code:
        conditions.append("ora_code = ?")
        params.append(ora_code)

    if severity_list:
        placeholders = ",".join("?" * len(severity_list))
        conditions.append(f"severity IN ({placeholders})")
        params.extend(severity_list)

    if timestamp_str:
        # Try to parse and apply ±time_window_minutes filter
        try:
            from dateutil import parser as dp
            ts = dp.parse(timestamp_str)
            from datetime import timedelta
            ts_low  = (ts - timedelta(minutes=time_window_minutes)).isoformat()
            ts_high = (ts + timedelta(minutes=time_window_minutes)).isoformat()
            conditions.append("timestamp_start BETWEEN ? AND ?")
            params.extend([ts_low, ts_high])
        except Exception:
            pass  # Ignore parse failures — no time filter

    if not conditions:
        return []   # No filter → caller searches everything

    sql = "SELECT chunk_id FROM chunks"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += f" ORDER BY timestamp_start LIMIT {PREFILTER_LIMIT}"

    try:
        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        return []   # Fail open — search without filter
