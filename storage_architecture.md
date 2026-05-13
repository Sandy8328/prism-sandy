# How Chunk Data Is Stored
## Vector DB vs SQL DB — Complete Storage Plan
## Temperature: 0.0 | No Code

---

## THE SHORT ANSWER

```
Chunks are stored in TWO places simultaneously:

  PLACE 1: Qdrant (Vector Database)
    → Stores: the vector number array + JSON metadata
    → Used for: semantic similarity search
    → NOT rows/columns — it is "points" in high-dimensional space

  PLACE 2: DuckDB (SQL Database)
    → Stores: all metadata fields as rows and columns
    → Used for: fast pre-filtering (hostname, time, severity, ora_code)
    → YES rows/columns — traditional SQL table

  Linked by: chunk_id (same ID in both systems)
```

---

## WHAT IS A "VECTOR" — THE FOUNDATION

```
When we embed this log line:

  "CATEGORY:DISK SEVERITY:CRITICAL ORA:ORA-27072
   Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED..."

The sentence-transformer model converts it to:

  [0.0821, -0.1234, 0.4521, 0.0012, -0.3821, 0.1821, ...]
   ←                     384 numbers                   →

This is the VECTOR.

Every chunk becomes one vector = 384 numbers.
These 384 numbers REPRESENT the meaning of the log chunk.
Two similar log lines will have similar number arrays (close in space).
Two different log lines will have different number arrays (far in space).
```

---

## PLACE 1: QDRANT STORAGE — NOT ROWS/COLUMNS

### What Qdrant Stores (One "Point" per Chunk)

```
Qdrant calls each entry a "POINT" — not a row.

A point has two parts:
  PART A: The vector     → 384 numbers (the meaning)
  PART B: The payload    → JSON metadata (the facts)

Example point stored in Qdrant:

  POINT ID:  "seed_001"

  VECTOR:    [0.0821, -0.1234, 0.4521, 0.0012, -0.3821, 0.1821,
              0.2134, -0.0821, 0.3312, 0.1234, ... (384 total numbers)]

  PAYLOAD:   {
               "chunk_id":        "seed_001",
               "hostname":        "dbhost01",
               "log_source":      "VAR_LOG_MESSAGES",
               "timestamp_start": "2024-03-07T02:44:18",
               "category":        "DISK",
               "severity":        "CRITICAL",
               "ora_code":        "ORA-27072",
               "os_pattern":      "SCSI_DISK_TIMEOUT",
               "platform":        "LINUX",
               "errno":           "EIO=5",
               "device":          "sdb",
               "raw_text":        "Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED..."
             }
```

### How Search Works in Qdrant

```
DBA query: "ORA-27072 on dbhost01"
Agent embeds query → [0.0799, -0.1198, 0.4488, ...]  (384 numbers)

Qdrant does:
  "Find me the 10 points whose vectors are CLOSEST to this query vector"

Closeness = cosine similarity (angle between vectors)
  score = 1.0  means identical meaning
  score = 0.9  means very similar
  score = 0.5  means somewhat related
  score = 0.0  means completely unrelated

Qdrant returns:
  chunk_id="seed_001"  score=0.94  ← very similar to query
  chunk_id="seed_042"  score=0.89
  chunk_id="seed_018"  score=0.81
  ...
```

### Physical Storage on Disk (Qdrant)

```
Qdrant saves its data as binary files:
  ./data/qdrant_storage/
    └── collections/
        └── oracle_dba_logs/
            ├── segments/
            │   └── segment_0/
            │       ├── vector_storage.dat    ← all 384-number arrays (binary)
            │       ├── payload_storage.dat   ← all JSON metadata (binary)
            │       └── id_mapper.dat         ← chunk_id → internal ID map
            └── collection.json              ← collection config

NOT human-readable files. Qdrant manages this internally.
You never read these files directly — only via Qdrant API.
```

---

## PLACE 2: DUCKDB STORAGE — YES ROWS AND COLUMNS

### What DuckDB Stores (Traditional SQL Table)

```
DuckDB stores the same metadata as a proper SQL table.
This is WHERE rows and columns exist.

TABLE: chunks
┌──────────┬───────────┬─────────────────────┬──────────┬──────────┬──────────┐
│ chunk_id │ hostname  │ timestamp_start      │ category │ severity │ ora_code │
├──────────┼───────────┼─────────────────────┼──────────┼──────────┼──────────┤
│ seed_001 │ dbhost01  │ 2024-03-07 02:44:18 │ DISK     │ CRITICAL │ ORA-27072│
│ seed_002 │ dbhost01  │ 2024-04-21 03:14:18 │ MEMORY   │ CRITICAL │ ORA-04031│
│ seed_003 │ dbhost02  │ 2024-03-21 02:44:18 │ NETWORK  │ CRITICAL │ ORA-29740│
│ seed_042 │ dbhost01  │ 2024-03-07 02:44:18 │ DISK     │ CRITICAL │ ORA-15080│
│ ...      │ ...       │ ...                 │ ...      │ ...      │ ...      │
└──────────┴───────────┴─────────────────────┴──────────┴──────────┴──────────┘

Full columns in chunks table:
  chunk_id        VARCHAR   (unique ID — links to Qdrant point)
  collection_id   VARCHAR   (seed vs ingested log batch)
  hostname        VARCHAR   (e.g. dbhost01)
  log_source      VARCHAR   (VAR_LOG_MESSAGES, ALERT_LOG, DMESG...)
  timestamp_start TIMESTAMP (start of event)
  timestamp_end   TIMESTAMP (end of event)
  category        VARCHAR   (DISK, MEMORY, CPU, NETWORK, KERNEL)
  sub_category    VARCHAR   (SCSI, FC, NFS, OOM, SEMAPHORE...)
  severity        VARCHAR   (CRITICAL, ERROR, WARNING, INFO)
  ora_code        VARCHAR   (ORA-27072, ORA-04031, ORA-00257...)
  os_pattern      VARCHAR   (SCSI_DISK_TIMEOUT, FC_HBA_RESET...)
  platform        VARCHAR   (LINUX, AIX, SOLARIS, WINDOWS...)
  oracle_version  VARCHAR   (11g, 12c, 19c, ALL)
  errno           VARCHAR   (EIO=5, ENOMEM=12, ENOSPC=28...)
  device          VARCHAR   (sdb, hdisk1, ib0, bond0...)
  line_count      INTEGER   (number of log lines in this chunk)
  raw_text        TEXT      (full raw log lines)
```

### How DuckDB is Used (Pre-Filtering)

```
Before vector search, DuckDB narrows candidates with SQL:

DBA query: "ORA-27072 on dbhost01 at 2024-03-07 02:44:18"

DuckDB query:
  SELECT chunk_id FROM chunks
  WHERE hostname = 'dbhost01'
    AND timestamp_start BETWEEN '2024-03-07 02:14:18'
                             AND '2024-03-07 03:14:18'
    AND severity IN ('CRITICAL', 'ERROR')

Result: 12 chunk_ids (from 182 total)

Then Qdrant searches ONLY those 12 chunks — not all 182.
This makes Qdrant search faster AND more precise.
```

### Physical Storage on Disk (DuckDB)

```
DuckDB saves as a SINGLE file:
  ./data/duckdb/metadata.duckdb    ← one file, all tables inside

This file IS a database — not CSV, not JSON.
You open it with DuckDB Python library.
It behaves exactly like SQLite but faster for analytical queries.
```

---

## PLACE 3: errors.jsonl — THE SOURCE FILE

```
Before loading into Qdrant or DuckDB,
all 182 scenarios exist in a JSONL file (JSON Lines).

JSONL = one JSON object per line.

File: ./data/seeds/errors.jsonl

Line 1: {"chunk_id":"seed_001","hostname":"dbhost01","log_source":"VAR_LOG_MESSAGES","timestamp_start":"2024-03-07T02:44:18","category":"DISK","severity":"CRITICAL","ora_code":"ORA-27072","os_pattern":"SCSI_DISK_TIMEOUT","platform":"LINUX","errno":"EIO=5","device":"sdb","keywords":["FAILED","DRIVER_TIMEOUT","sdb","Hardware Error"],"raw_text":"Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED..."}
Line 2: {"chunk_id":"seed_002","hostname":"dbhost01","log_source":"VAR_LOG_MESSAGES","timestamp_start":"2024-04-21T03:14:18","category":"MEMORY","severity":"CRITICAL","ora_code":"ORA-00603","os_pattern":"OOM_KILLER_ACTIVE","platform":"LINUX","errno":"","device":"","keywords":["oom-killer","oracle","Kill process"],"raw_text":"Apr 21 03:14:18 dbhost01 kernel: oracle invoked oom-killer..."}
...
Line 182: {...AIX-20 data...}

This file is the MASTER SOURCE.
load_seeds.py reads it and loads into BOTH Qdrant and DuckDB.
```

---

## COMPLETE PICTURE — HOW ALL 3 STORAGE LAYERS WORK TOGETHER

```
QUERY: "ORA-27072 on dbhost01 at 2024-03-07 02:44:18"
         │
         ▼
  ┌─────────────────┐
  │  Input Parser   │  Extracts: ora_code, hostname, timestamp, keywords
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │    DuckDB       │  SQL pre-filter → returns 12 matching chunk_ids
  │  (rows/cols)    │  "WHERE hostname='dbhost01' AND time BETWEEN..."
  └────────┬────────┘
           │  12 chunk_ids
           ▼
  ┌──────────────────────────┐
  │         Qdrant           │  Vector search among ONLY those 12 chunks
  │  (points: vector+payload)│  Returns top 5 by cosine similarity
  └────────┬─────────────────┘
           │  5 chunks (with raw_text, metadata, score)
           ▼
  ┌─────────────────┐
  │ Pattern Matcher │  Runs 45 regexes on raw_text of 5 chunks
  │  + Graph        │  Traverses NetworkX graph → finds root cause
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Report Builder │  Assembles final output
  └─────────────────┘
           │
           ▼
  ROOT CAUSE: FC_HBA_RESET
  CONFIDENCE: 94%
  FIX: systemctl enable multipathd --now
```

---

## SUMMARY TABLE — 3 STORAGE LAYERS

| What | Where | Format | Purpose |
|---|---|---|---|
| Raw log text + metadata | errors.jsonl | JSON Lines | Source file, loaded once |
| Vector (384 numbers) + JSON payload | Qdrant | Binary points | Semantic search |
| Metadata fields | DuckDB | SQL rows and columns | Pre-filter by hostname/time/severity |
| Knowledge graph (nodes + edges) | graph.json → NetworkX | In-memory graph | Root cause traversal |
| Regex patterns | patterns.json → dict | Python dict | Pattern matching |

---

## ONE-LINE ANSWER TO YOUR QUESTION

```
The chunks are stored in TWO formats simultaneously:

  Qdrant → "points" format (vector + JSON) — NOT rows/columns
              used for: "find me similar logs"

  DuckDB → rows and columns (traditional SQL table)
              used for: "filter by hostname, time, severity"

Both are needed. Neither alone is enough.
  → Qdrant without DuckDB = searches ALL chunks (slow, noisy)
  → DuckDB without Qdrant = can filter, but cannot find similar meaning
  → Together = fast + precise + semantic
```
