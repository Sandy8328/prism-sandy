"""
load_seeds.py — One-time seed data loader
Reads data/seeds/errors.jsonl and loads every chunk into:
  1. Qdrant (vector + payload)
  2. DuckDB (metadata rows)
Run: python scripts/load_seeds.py
"""

import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import duckdb
import yaml
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    PayloadSchemaType, TokenizerType
)
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# ── Load config ────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    cfg = yaml.safe_load(f)

SEEDS_PATH      = cfg["seeds"]["jsonl_path"]
QDRANT_PATH     = cfg["qdrant"]["storage_path"]
QDRANT_COL      = cfg["qdrant"]["collection_name"]
DUCKDB_PATH     = cfg["duckdb"]["db_path"]
MODEL_NAME      = cfg["embedding"]["model_name"]
VECTOR_SIZE     = cfg["embedding"]["vector_size"]
EMBED_PREFIX    = cfg["embedding"]["embed_prefix"]
EMBED_BATCH_SIZE  = cfg["embedding"]["batch_size"]          # embedding batch
QDRANT_BATCH_SIZE = cfg["qdrant"]["upsert_batch_size"]      # qdrant upsert batch


def build_embed_text(chunk: dict) -> str:
    """Build the text that will be embedded. Prefix metadata for better retrieval."""
    if EMBED_PREFIX:
        prefix = (
            f"CATEGORY:{chunk.get('category','')} "
            f"SEVERITY:{chunk.get('severity','')} "
            f"ORA:{chunk.get('ora_code','')} "
            f"PLATFORM:{chunk.get('platform','')} "
            f"PATTERN:{chunk.get('os_pattern','')} "
        )
        return prefix + chunk.get("raw_text", "")
    return chunk.get("raw_text", "")


def init_duckdb(conn: duckdb.DuckDBPyConnection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id        VARCHAR PRIMARY KEY,
            collection_id   VARCHAR,
            hostname        VARCHAR,
            log_source      VARCHAR,
            timestamp_start TIMESTAMP,
            timestamp_end   TIMESTAMP,
            category        VARCHAR,
            sub_category    VARCHAR,
            severity        VARCHAR,
            ora_code        VARCHAR,
            os_pattern      VARCHAR,
            platform        VARCHAR,
            oracle_version  VARCHAR DEFAULT 'ALL',
            errno           VARCHAR,
            device          VARCHAR,
            line_count      INTEGER,
            raw_text        TEXT,
            keywords        TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hostname   ON chunks(hostname)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_severity   ON chunks(severity)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ora_code   ON chunks(ora_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_platform   ON chunks(platform)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts_start   ON chunks(timestamp_start)")


def init_qdrant(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COL not in existing:
        client.create_collection(
            collection_name=QDRANT_COL,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        # Create payload indexes for fast pre-filtering
        for field in ["hostname", "ora_code", "severity", "category", "platform", "os_pattern", "log_source"]:
            client.create_payload_index(
                collection_name=QDRANT_COL,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        print(f"Created Qdrant collection: {QDRANT_COL}")
    else:
        print(f"Qdrant collection '{QDRANT_COL}' already exists — skipping creation")


def load_seeds():
    print(f"Loading seeds from: {SEEDS_PATH}")

    # Load all chunks
    chunks = []
    with open(SEEDS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    print(f"Found {len(chunks)} chunks to load")

    # Init embedding model
    print(f"Loading embedding model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    # Init DuckDB
    conn = duckdb.connect(DUCKDB_PATH)
    init_duckdb(conn)

    # Init Qdrant
    client = QdrantClient(path=QDRANT_PATH)
    init_qdrant(client)

    # Check what's already loaded
    existing_ids = set()
    try:
        rows = conn.execute("SELECT chunk_id FROM chunks").fetchall()
        existing_ids = {r[0] for r in rows}
    except Exception:
        pass

    # Filter out already-loaded chunks
    new_chunks = [c for c in chunks if c["chunk_id"] not in existing_ids]
    if not new_chunks:
        print("All chunks already loaded. Nothing to do.")
        conn.close()
        return

    print(f"Embedding {len(new_chunks)} new chunks...")
    texts = [build_embed_text(c) for c in new_chunks]
    vectors = model.encode(texts, batch_size=EMBED_BATCH_SIZE, show_progress_bar=True)

    # Upsert into Qdrant
    points = []
    for chunk, vector in zip(new_chunks, vectors):
        payload = {k: v for k, v in chunk.items() if k not in ["linked_chunks"]}
        points.append(PointStruct(
            id=abs(hash(chunk["chunk_id"])) % (2**63),
            vector=vector.tolist(),
            payload=payload,
        ))

    print(f"Upserting {len(points)} points into Qdrant...")
    for i in tqdm(range(0, len(points), QDRANT_BATCH_SIZE), desc="Qdrant upsert"):
        client.upsert(collection_name=QDRANT_COL, points=points[i:i+QDRANT_BATCH_SIZE])

    # Insert into DuckDB
    print(f"Inserting {len(new_chunks)} rows into DuckDB...")
    for chunk in tqdm(new_chunks, desc="DuckDB insert"):
        ts_start = chunk.get("timestamp_start")
        ts_end   = chunk.get("timestamp_end", ts_start)
        try:
            conn.execute("""
                INSERT OR IGNORE INTO chunks
                (chunk_id, collection_id, hostname, log_source,
                 timestamp_start, timestamp_end, category, sub_category,
                 severity, ora_code, os_pattern, platform, oracle_version,
                 errno, device, line_count, raw_text, keywords)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                chunk.get("chunk_id"),
                chunk.get("collection_id", "seed"),
                chunk.get("hostname"),
                chunk.get("log_source"),
                ts_start,
                ts_end,
                chunk.get("category"),
                chunk.get("sub_category"),
                chunk.get("severity"),
                chunk.get("ora_code"),
                chunk.get("os_pattern"),
                chunk.get("platform"),
                chunk.get("oracle_version", "ALL"),
                chunk.get("errno"),
                chunk.get("device"),
                chunk.get("raw_text", "").count("\n") + 1,
                chunk.get("raw_text"),
                json.dumps(chunk.get("keywords", [])),
            ])
        except Exception as e:
            print(f"WARNING: DuckDB insert failed for {chunk.get('chunk_id')}: {e}")

    conn.commit()
    conn.close()

    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] if False else len(chunks)
    print(f"\n✅ Done! Loaded {len(new_chunks)} new chunks.")
    print(f"   Qdrant collection: {QDRANT_COL}")
    print(f"   DuckDB path:       {DUCKDB_PATH}")


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    load_seeds()
