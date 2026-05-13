"""
embedder.py — Sentence-transformer embedding wrapper.

Wraps all-MiniLM-L6-v2 with:
  - Metadata prefix injection (CATEGORY + SEVERITY + ORA + PLATFORM + PATTERN)
  - Batch encoding with progress bar
  - Cached model load (singleton)
  - Deterministic output (no randomness)
"""

from __future__ import annotations
import yaml
from functools import lru_cache
from typing import Union
import numpy as np
from sentence_transformers import SentenceTransformer

# ── Config ──────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    _cfg = yaml.safe_load(f)

MODEL_NAME   = _cfg["embedding"]["model_name"]
VECTOR_SIZE  = _cfg["embedding"]["vector_size"]
BATCH_SIZE   = _cfg["embedding"]["batch_size"]
EMBED_PREFIX = _cfg["embedding"]["embed_prefix"]


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load model once, reuse across calls."""
    return SentenceTransformer(MODEL_NAME)


def build_embed_text(chunk: dict) -> str:
    """
    Construct the text string to embed for a chunk dict.
    Prepends structured metadata prefix to improve retrieval precision.

    Prefix format:
      CATEGORY:DISK SEVERITY:CRITICAL ORA:ORA-27072 PLATFORM:LINUX PATTERN:SCSI_DISK_TIMEOUT
    """
    if EMBED_PREFIX:
        prefix = (
            f"CATEGORY:{chunk.get('category', '')} "
            f"SEVERITY:{chunk.get('severity', '')} "
            f"ORA:{chunk.get('ora_code', '')} "
            f"PLATFORM:{chunk.get('platform', '')} "
            f"PATTERN:{chunk.get('os_pattern', '')} "
        )
        return (prefix + chunk.get("raw_text", "")).strip()
    return chunk.get("raw_text", "")


def build_query_text(query: str, ora_code: str = "", platform: str = "") -> str:
    """
    Construct the text to embed for a user query.
    Adds available context as prefix.
    """
    prefix = ""
    if ora_code:
        prefix += f"ORA:{ora_code} "
    if platform:
        prefix += f"PLATFORM:{platform} "
    return (prefix + query).strip()


def embed_texts(texts: list[str], show_progress: bool = False) -> np.ndarray:
    """
    Embed a list of strings. Returns numpy array shape (N, VECTOR_SIZE).
    Deterministic — no randomness, fixed model weights.
    """
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=show_progress,
        normalize_embeddings=True,   # L2-normalize for cosine similarity
        convert_to_numpy=True,
    )
    return vectors


def embed_single(text: str) -> list[float]:
    """Embed a single string. Returns list of floats (for Qdrant)."""
    return embed_texts([text])[0].tolist()


def embed_chunks(chunks: list[dict], show_progress: bool = True) -> list[list[float]]:
    """
    Embed a list of chunk dicts using metadata-prefixed text.
    Returns list of float vectors.
    """
    texts = [build_embed_text(c) for c in chunks]
    vectors = embed_texts(texts, show_progress=show_progress)
    return [v.tolist() for v in vectors]


def embed_query(
    query: str,
    ora_code: str = "",
    platform: str = "",
) -> list[float]:
    """
    Embed a user query with optional metadata prefix.
    Returns float vector for Qdrant search.
    """
    text = build_query_text(query, ora_code=ora_code, platform=platform)
    return embed_single(text)
