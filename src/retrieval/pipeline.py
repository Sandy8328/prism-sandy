"""
pipeline.py — Orchestrates the 7-stage retrieval pipeline.

Stages:
  1. Input Parser     → extract ora_code, hostname, timestamp, platform, keywords
  2. DuckDB Pre-filter → narrow candidates by hostname/time/severity
  3A. BM25 Search     → keyword matching on candidates
  3B. Dense Search    → semantic similarity on candidates
  4. Hybrid Fusion    → RRF merge of BM25 + Dense (40/60 weights)
  5. Temporal Correlator → find correlated chunks from other log sources
  6. Pattern Match + Graph → regex scoring + knowledge graph traversal
  7. Report Builder   → structured output with confidence score

This module wires stages 1-5. Stages 6-7 are in the agent module.
"""

from __future__ import annotations
import yaml
from typing import Optional

from src.retrieval.hybrid_fusion import prefilter_chunks, reciprocal_rank_fusion
from src.retrieval.bm25_search import bm25_search
from src.retrieval.temporal_correlator import find_correlated_chunks, detect_cascade
from src.vectordb.qdrant_client import dense_search
from src.embeddings.embedder import embed_query

# ── Config ──────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    _cfg = yaml.safe_load(f)

TOP_K          = _cfg["retrieval"]["top_k"]
MIN_CONFIDENCE = _cfg["retrieval"]["min_confidence_pct"]
TIME_WINDOW    = _cfg["retrieval"]["time_window_minutes"]
CHUNK_TIME_WINDOW_S = _cfg["chunking"]["time_window_sec"]  # seconds for temporal correlation


def run_retrieval_pipeline(
    query: str,
    ora_code: str = "",
    hostname: str = "",
    timestamp_str: str = "",
    platform: str = "",
    top_k: int = TOP_K,
) -> dict:
    """
    Execute stages 1-5 of the pipeline.

    Args:
        query:         Raw query text (ORA code, log paste, natural language)
        ora_code:      Extracted ORA code if known (e.g. "ORA-27072")
        hostname:      Target hostname if known (e.g. "dbhost01")
        timestamp_str: Event timestamp if known (ISO or syslog format)
        platform:      Platform if known ("LINUX", "AIX", etc.)
        top_k:         Number of results to return

    Returns:
        {
          "query":           original query,
          "ora_code":        extracted ORA code,
          "hostname":        hostname used for filtering,
          "platform":        detected platform,
          "candidate_ids":   chunk_ids from DuckDB pre-filter,
          "bm25_results":    [{chunk_id, bm25_score}, ...],
          "dense_results":   [{chunk_id, score, payload}, ...],
          "fused_results":   [{chunk_id, rrf_score, payload, ...}, ...],
          "correlations":    {chunk_id: [correlated_chunks], ...},
          "cascades":        [matched cascade dicts],
          "top_chunks":      top_k fused chunks with payloads,
        }
    """
    # ── Stage 2: DuckDB Pre-filter ──────────────────────────────
    severity_filter = ["CRITICAL", "ERROR"]
    candidate_ids = prefilter_chunks(
        hostname=hostname or None,
        timestamp_str=timestamp_str or None,
        severity_list=severity_filter,
        platform=platform or None,
        ora_code=ora_code or None,
        time_window_minutes=TIME_WINDOW,
    )
    # If pre-filter returns nothing, search without restriction
    active_candidates = candidate_ids if candidate_ids else None

    # ── Stage 3A: BM25 Search ───────────────────────────────────
    bm25_query = query
    if ora_code:
        bm25_query = f"{ora_code} {query}"
    bm25_results = bm25_search(
        query=bm25_query,
        top_k=top_k,
        candidate_ids=active_candidates,
    )

    # ── Stage 3B: Dense Search ──────────────────────────────────
    query_vector = embed_query(
        query=query,
        ora_code=ora_code,
        platform=platform,
    )
    dense_results = dense_search(
        query_vector=query_vector,
        top_k=top_k,
        hostname=hostname or None,
        severity_list=severity_filter,
        platform=platform or None,
        ora_code=ora_code or None,
        candidate_ids=active_candidates,
    )

    # ── Stage 4: Hybrid Fusion (RRF) ────────────────────────────
    fused = reciprocal_rank_fusion(
        bm25_results=bm25_results,
        dense_results=dense_results,
        top_k=top_k,
    )

    # Enrich fused results with payloads from dense results
    payload_map = {r["chunk_id"]: r.get("payload", {}) for r in dense_results}
    for item in fused:
        if not item.get("payload"):
            item["payload"] = payload_map.get(item["chunk_id"], {})

    # ── Stage 5: Temporal Correlation ───────────────────────────
    top_payloads = [item["payload"] for item in fused if item.get("payload")]
    correlations = find_correlated_chunks(
        reference_chunks=top_payloads,
        time_window_sec=CHUNK_TIME_WINDOW_S,
    )

    # Collect all chunks (primary + correlated) for cascade detection
    all_payloads = list(top_payloads)
    for corr_list in correlations.values():
        all_payloads.extend(corr_list)

    # Load cascade library from graph.json
    cascades = []
    try:
        import json, os
        graph_path = os.path.join("src", "knowledge_graph", "data", "graph.json")
        with open(graph_path) as f:
            graph = json.load(f)
        cascade_library = graph.get("cascades", [])
        cascades = detect_cascade(all_payloads, cascade_library)
    except Exception:
        pass

    return {
        "query":          query,
        "ora_code":       ora_code,
        "hostname":       hostname,
        "platform":       platform,
        "candidate_ids":  candidate_ids,
        "bm25_results":   bm25_results,
        "dense_results":  dense_results,
        "fused_results":  fused,
        "correlations":   correlations,
        "cascades":       cascades,
        "top_chunks":     fused[:top_k],
    }
