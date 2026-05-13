"""
qdrant_client.py — Qdrant vector DB client wrapper.

Wraps qdrant-client with:
  - Collection init (cosine, 384-dim, payload indexes)
  - Upsert chunks with pre-built vectors
  - Filtered search (pre-filter by hostname/time/severity/platform)
  - Fetch by chunk_ids
  - Delete collection (for testing)
"""

from __future__ import annotations
import yaml
import atexit
from functools import lru_cache
from typing import Optional
from qdrant_client import QdrantClient as _QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny,
    HasIdCondition, PayloadSchemaType,
)

# ── Config ──────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    _cfg = yaml.safe_load(f)

STORAGE_PATH      = _cfg["qdrant"]["storage_path"]
COLLECTION_NAME   = _cfg["qdrant"]["collection_name"]
VECTOR_SIZE       = _cfg["embedding"]["vector_size"]
TOP_K             = _cfg["retrieval"]["top_k"]
UPSERT_BATCH_SIZE = _cfg["qdrant"]["upsert_batch_size"]  # chunk upsert batch size


import threading

_client_lock = threading.Lock()
_client_instance: Optional[_QdrantClient] = None

def _get_client() -> _QdrantClient:
    global _client_instance
    with _client_lock:
        if _client_instance is None:
            try:
                _client_instance = _QdrantClient(path=STORAGE_PATH)
                # Ensure we close it properly at exit
                atexit.register(_client_instance.close)
            except Exception as e:
                # If it's already locked, we might need to tell the user to kill other processes
                if "already accessed" in str(e):
                    raise RuntimeError(
                        f"Qdrant storage is locked. Please ensure no other diagnostic agents or "
                        f"indexing scripts are running. (Path: {STORAGE_PATH})"
                    )
                raise e
        return _client_instance


def ensure_collection():
    """Create collection and payload indexes if they don't exist."""
    client = _get_client()
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        for field in ["hostname", "ora_code", "severity", "category",
                      "platform", "os_pattern", "log_source"]:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )


def upsert_chunks(chunks: list[dict], vectors: list[list[float]]):
    """
    Upsert chunk dicts + their vectors into Qdrant.
    chunk_id is hashed to an integer for Qdrant's uint64 point ID.
    """
    client = _get_client()
    ensure_collection()

    points = []
    for chunk, vector in zip(chunks, vectors):
        point_id = abs(hash(chunk["chunk_id"])) % (2**63)
        payload = {k: v for k, v in chunk.items()
                   if k not in ("linked_chunks",) and v is not None}
        points.append(PointStruct(
            id=point_id,
            vector=vector,
            payload=payload,
        ))

    # Batch upsert
    for i in range(0, len(points), UPSERT_BATCH_SIZE):
        client.upsert(collection_name=COLLECTION_NAME, points=points[i:i+UPSERT_BATCH_SIZE])


def _build_filter(
    hostname: Optional[str] = None,
    severity_list: Optional[list[str]] = None,
    platform: Optional[str] = None,
    ora_code: Optional[str] = None,
    candidate_ids: Optional[list[str]] = None,
) -> Optional[Filter]:
    """Build Qdrant filter from optional parameters."""
    must = []

    if hostname:
        must.append(FieldCondition(key="hostname", match=MatchValue(value=hostname)))
    if platform:
        must.append(FieldCondition(key="platform", match=MatchValue(value=platform)))
    if ora_code:
        must.append(FieldCondition(key="ora_code", match=MatchValue(value=ora_code)))
    if severity_list:
        must.append(FieldCondition(key="severity", match=MatchAny(any=severity_list)))
    if candidate_ids:
        hashed = [abs(hash(cid)) % (2**63) for cid in candidate_ids]
        must.append(HasIdCondition(has_id=hashed))

    if not must:
        return None
    return Filter(must=must)


def dense_search(
    query_vector: list[float],
    top_k: int = TOP_K,
    hostname: Optional[str] = None,
    severity_list: Optional[list[str]] = None,
    platform: Optional[str] = None,
    ora_code: Optional[str] = None,
    candidate_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Perform cosine similarity search in Qdrant.
    Returns list of {chunk_id, score, payload} dicts.

    Uses query_points() — compatible with qdrant-client >= 1.7.
    """
    client = _get_client()

    query_filter = _build_filter(
        hostname=hostname,
        severity_list=severity_list,
        platform=platform,
        ora_code=ora_code,
        candidate_ids=candidate_ids,
    )

    # query_points() replaced search() in qdrant-client >= 1.7
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "chunk_id": r.payload.get("chunk_id", str(r.id)),
            "score":    round(r.score, 4),
            "payload":  r.payload,
        }
        for r in response.points
    ]


def fetch_by_chunk_ids(chunk_ids: list[str]) -> list[dict]:
    """Fetch full payloads for specific chunk IDs."""
    client = _get_client()
    hashed_ids = [abs(hash(cid)) % (2**63) for cid in chunk_ids]
    points = client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=hashed_ids,
        with_payload=True,
    )
    return [{"chunk_id": p.payload.get("chunk_id", str(p.id)), "payload": p.payload}
            for p in points]


def count_chunks() -> int:
    """Return total number of chunks in the collection."""
    client = _get_client()
    try:
        info = client.get_collection(COLLECTION_NAME)
        return info.points_count
    except Exception:
        return 0


def delete_collection():
    """Drop the collection (for testing/reset)."""
    client = _get_client()
    client.delete_collection(COLLECTION_NAME)
