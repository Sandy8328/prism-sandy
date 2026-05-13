"""
bm25_search.py — In-memory BM25 keyword search using rank_bm25.

BM25 is used for exact keyword matching (ORA codes, device names, error strings).
The index is built once at startup from all chunk raw_texts.
Weight in hybrid fusion: 40% (keyword exact match matters most).

Index is rebuilt from DuckDB on startup — takes < 500ms for 200 chunks.
"""

from __future__ import annotations
import re
import duckdb
import yaml
from rank_bm25 import BM25Okapi
from functools import lru_cache

# ── Config ──────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    _cfg = yaml.safe_load(f)

DUCKDB_PATH = _cfg["duckdb"]["db_path"]
TOP_K       = _cfg["retrieval"]["top_k"]

# ── Tokenizer ───────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")

def _tokenize(text: str) -> list[str]:
    """
    Tokenize log text for BM25.
    Preserves Oracle-specific tokens: ORA-27072, sdb, qla2xxx, hdisk0
    """
    return [t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 2]


# ── Index state (module-level singleton) ────────────────────────
_index: BM25Okapi | None = None
_chunk_ids: list[str] = []
_chunk_texts: list[str] = []


def build_index(chunks: list[dict] | None = None):
    """
    Build BM25 index from chunk dicts or from DuckDB.
    Call once at startup.
    """
    global _index, _chunk_ids, _chunk_texts

    if chunks is None:
        # Load from DuckDB
        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        rows = conn.execute(
            "SELECT chunk_id, raw_text FROM chunks ORDER BY timestamp_start"
        ).fetchall()
        conn.close()
        chunks = [{"chunk_id": r[0], "raw_text": r[1]} for r in rows]

    _chunk_ids = [c["chunk_id"] for c in chunks]
    _chunk_texts = [c.get("raw_text", "") or "" for c in chunks]
    tokenized = [_tokenize(t) for t in _chunk_texts]
    _index = BM25Okapi(tokenized)


def _ensure_index():
    if _index is None:
        build_index()


def bm25_search(
    query: str,
    top_k: int = TOP_K,
    candidate_ids: list[str] | None = None,
) -> list[dict]:
    """
    Search the BM25 index for the query.
    Returns list of {chunk_id, bm25_score} dicts sorted by score descending.

    If candidate_ids provided, only those IDs are considered.
    """
    _ensure_index()

    tokens = _tokenize(query)
    if not tokens:
        return []

    scores = _index.get_scores(tokens)

    # Build results
    results = []
    for i, score in enumerate(scores):
        if score <= 0:
            continue
        chunk_id = _chunk_ids[i]
        if candidate_ids and chunk_id not in candidate_ids:
            continue
        results.append({"chunk_id": chunk_id, "bm25_score": round(float(score), 4)})

    # Sort by score descending
    results.sort(key=lambda x: x["bm25_score"], reverse=True)
    return results[:top_k]


def add_chunks_to_index(new_chunks: list[dict]):
    """
    Add new chunks to the BM25 index (in-memory update).
    Rebuilds index since rank_bm25 is immutable after creation.
    """
    global _chunk_ids, _chunk_texts
    _ensure_index()
    _chunk_ids.extend(c["chunk_id"] for c in new_chunks)
    _chunk_texts.extend(c.get("raw_text", "") or "" for c in new_chunks)
    all_chunks = [{"chunk_id": cid, "raw_text": txt}
                  for cid, txt in zip(_chunk_ids, _chunk_texts)]
    build_index(all_chunks)


def index_size() -> int:
    """Return number of chunks in BM25 index."""
    return len(_chunk_ids)
