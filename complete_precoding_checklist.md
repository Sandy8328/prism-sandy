# Complete Pre-Coding Checklist — All Gaps Filled
## Every missing piece — answered and documented
## Oracle DBA RAG Agent | Temperature: 0.0

---

## WHAT WE HAVE vs WHAT WE STILL NEED

```
HAVE (documentation):
  ✅ 85 OS error log samples (markdown)
  ✅ ORA code mapping
  ✅ Knowledge graph (markdown)
  ✅ Chunking rules
  ✅ Input/Output contract
  ✅ Retrieval strategy
  ✅ Regex pattern library (45 patterns)

STILL MISSING (critical for coding):
  ❌ Seed data in machine-readable format (JSONL) — code cannot read markdown
  ❌ Knowledge graph in machine-readable format (JSON) — code cannot read markdown
  ❌ Python requirements.txt — packages + versions not defined
  ❌ Answers to Gap 3-13 from gap_analysis.md
  ❌ Feedback mechanism — what happens when agent is wrong?
  ❌ New pattern addition workflow — how does DBA add a new error?
  ❌ Unknown log handling — what if logs don't match any pattern?
  ❌ Pipeline orchestration flow — how all 7 stages connect in code
```

---

## MISSING PIECE 1: All Gap Answers (Filled Now)

### Gap 3 — Scoring Formula Weights (DECIDED)
```
keyword_match_weight = 40   (most important — exact keyword in log line)
bm25_weight          = 30   (exact term match score)
dense_weight         = 20   (semantic similarity)
temporal_bonus       = 10   (cross-log timestamp link found)

Total possible = 100

Rationale:
  Keywords weighted highest because ORA error diagnosis
  depends on exact error terms more than semantic meaning.
  Temporal bonus rewards the cross-log correlation 
  which is our key differentiator.
```

### Gap 4 — What Text Gets Embedded (DECIDED)
```
Embed this string (Option B — metadata prefix + raw text):

  f"CATEGORY:{category} SEVERITY:{severity} ORA:{ora_code} "
  f"PATTERN:{os_pattern} ERRNO:{errno} DEVICE:{device} "
  f"SOURCE:{log_source}\n{raw_text}"

Example:
  "CATEGORY:DISK SEVERITY:CRITICAL ORA:ORA-27072 
   PATTERN:SCSI_DISK_TIMEOUT ERRNO:EIO=5 DEVICE:sdb 
   SOURCE:VAR_LOG_MESSAGES
   Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED..."
```

### Gap 5 — Qdrant Config (DECIDED)
```yaml
collection_name:  "oracle_dba_logs"
vector_size:      384
distance:         Cosine
on_disk:          true
storage_path:     "./data/qdrant_storage"
payload_indexes:
  - field: hostname     type: keyword
  - field: ora_code     type: keyword
  - field: severity     type: keyword
  - field: category     type: keyword
  - field: log_source   type: keyword
  - field: os_pattern   type: keyword
  - field: timestamp_start type: datetime
```

### Gap 6 — DuckDB Schema (DECIDED)
```sql
-- 3 tables, confirmed:
CREATE TABLE chunks (
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
  errno           VARCHAR,
  device          VARCHAR,
  line_count      INTEGER,
  raw_text        TEXT
);
CREATE TABLE chunk_links (
  chunk_id        VARCHAR,
  linked_chunk_id VARCHAR,
  link_type       VARCHAR,
  time_diff_sec   INTEGER
);
CREATE TABLE feedback (
  feedback_id     VARCHAR PRIMARY KEY,
  query_id        VARCHAR,
  chunk_id        VARCHAR,
  was_correct     BOOLEAN,
  correct_pattern VARCHAR,
  timestamp       TIMESTAMP,
  notes           TEXT
);
-- Note: vector stored in Qdrant only, not duplicated in DuckDB
```

### Gap 7 — BM25 (DECIDED)
```
In-memory BM25 using rank_bm25 library.
Built at startup from all chunks in DuckDB.
For 425 seed chunks: rebuild takes < 0.5 seconds.
Persisted as pickle when chunk count > 10,000.
```

### Gap 8 — Multiple ORA Codes (DECIDED)
```
Priority order (lower number = closer to OS root cause):
  Priority 1 (OS layer):    ORA-27072, ORA-27102, ORA-27125, ORA-27300
  Priority 2 (ASM layer):   ORA-15080, ORA-15130, ORA-15041, ORA-15040
  Priority 3 (DB layer):    ORA-00257, ORA-00353, ORA-00470, ORA-00603
  Priority 4 (Network):     ORA-03113, ORA-12541, ORA-12170, ORA-12519
  Priority 5 (Memory):      ORA-04031, ORA-07445

Rule: In compound incident, report Priority 1 code as PRIMARY.
      Report others as SECONDARY consequences.
```

### Gap 9 — Confidence Thresholds (DECIDED)
```
>= 80%  → HIGH confidence   → Show root cause + fix commands
60–79%  → MEDIUM confidence → Show probable cause + warn "verify manually"
40–59%  → LOW confidence    → Show possible match + "manual review required"
< 40%   → NO MATCH          → Return no_match_found=true

Fix commands shown only when confidence >= 60%.
HIGH risk fixes shown only when confidence >= 80%.
```

### Gap 10 — Timezone (DECIDED)
```
Default: Asia/Kolkata (IST, +05:30)
All timestamps normalized to UTC internally.
Displayed in source host's local timezone.
At ingestion: if AHF ZIP contains timezone info → use it.
              if not → use default IST.
```

### Gap 11 — Project Directory Structure (DECIDED)
```
oracle_dba_agent/
├── config/
│   └── settings.yaml
├── data/
│   ├── seeds/
│   │   └── errors.jsonl       ← machine-readable seed data
│   ├── qdrant_storage/        ← Qdrant persistence
│   └── duckdb/
│       └── metadata.duckdb
├── src/
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── syslog_parser.py
│   │   ├── alert_log_parser.py
│   │   ├── dmesg_parser.py
│   │   ├── iostat_parser.py
│   │   ├── sar_parser.py
│   │   ├── vmstat_parser.py
│   │   ├── df_parser.py
│   │   └── crs_parser.py
│   ├── chunker/
│   │   ├── __init__.py
│   │   └── event_chunker.py
│   ├── embeddings/
│   │   ├── __init__.py
│   │   └── embedder.py
│   ├── vectordb/
│   │   ├── __init__.py
│   │   └── qdrant_client.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── bm25_search.py
│   │   ├── dense_search.py
│   │   ├── hybrid_fusion.py
│   │   ├── temporal_correlator.py
│   │   └── pipeline.py        ← orchestrates all 7 stages
│   ├── knowledge_graph/
│   │   ├── __init__.py
│   │   ├── graph.py           ← NetworkX graph builder
│   │   ├── pattern_matcher.py ← regex matching engine
│   │   └── data/
│   │       ├── graph.json     ← machine-readable knowledge graph
│   │       └── patterns.json  ← machine-readable regex library
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── input_parser.py    ← parse ORA code / raw log / NL query
│   │   ├── scorer.py          ← confidence scoring formula
│   │   ├── report_builder.py  ← build structured output report
│   │   └── agent.py           ← main orchestrator
│   ├── api/
│   │   ├── __init__.py
│   │   └── app.py             ← FastAPI
│   └── ui/
│       ├── __init__.py
│       └── streamlit_app.py
├── tests/
│   ├── test_parsers.py
│   ├── test_retrieval.py
│   ├── test_agent.py
│   └── golden_test_cases.json ← 6 test cases
├── scripts/
│   └── load_seeds.py          ← one-time seed loader
├── requirements.txt
├── docker-compose.yml         ← Qdrant only
└── README.md
```

### Gap 12 — Test Cases (DECIDED)
```
6 test cases confirmed. Stored in tests/golden_test_cases.json
See gap_analysis.md for full definitions.
```

### Gap 13 — settings.yaml (DECIDED)
```yaml
embedding:
  model_name: "all-MiniLM-L6-v2"
  vector_size: 384
  batch_size: 32

qdrant:
  collection_name: "oracle_dba_logs"
  storage_path: "./data/qdrant_storage"
  distance_metric: "Cosine"

duckdb:
  db_path: "./data/duckdb/metadata.duckdb"

retrieval:
  top_k: 10
  bm25_weight: 0.40
  dense_weight: 0.60
  time_window_minutes: 30
  min_confidence_pct: 40

scoring:
  keyword_match_weight: 40
  bm25_weight: 30
  dense_weight: 20
  temporal_bonus: 10

thresholds:
  high_confidence: 80
  medium_confidence: 60
  low_confidence: 40

defaults:
  timezone: "Asia/Kolkata"
  max_chunk_lines: 50
  chunk_overlap_lines: 3
  time_window_sec: 60
```

---

## MISSING PIECE 2: Python Requirements (Filled Now)

```
# requirements.txt

# Core RAG pipeline
sentence-transformers==2.7.0   # local embeddings, no API needed
qdrant-client==1.9.1           # vector database client
rank-bm25==0.2.2               # BM25 exact keyword search
duckdb==0.10.3                 # metadata SQL filtering
networkx==3.3                  # knowledge graph traversal

# Log parsing
python-dateutil==2.9.0         # flexible timestamp parsing
pytz==2024.1                   # timezone handling
regex==2024.4.28               # advanced regex (better than re)

# API layer
fastapi==0.111.0
uvicorn==0.29.0
pydantic==2.7.1

# UI
streamlit==1.34.0

# Utilities
PyYAML==6.0.1                  # settings.yaml loading
python-dotenv==1.0.1           # .env file support
rich==13.7.1                   # pretty terminal output
tqdm==4.66.4                   # progress bars during ingestion
loguru==0.7.2                  # structured logging

# Testing
pytest==8.2.0
pytest-asyncio==0.23.6
```

---

## MISSING PIECE 3: Feedback Mechanism (Filled Now)

### The Problem
When the agent says "root cause = FC_HBA_RESET" but the DBA knows it was actually a storage array firmware bug — we need to capture this.

### Solution — Simple Thumbs Up/Down in UI
```
After each diagnostic report, DBA sees:

  Was this diagnosis correct?
  [✅ Yes, correct]  [❌ No, wrong]  [⚠️ Partially correct]

If DBA clicks ❌:
  → A text field appears: "What was the actual root cause?"
  → DBA types: "Storage array firmware bug on EMC VNX"
  → This is saved to the feedback table in DuckDB

Feedback record stored:
  feedback_id:     uuid
  query_id:        <original query>
  chunk_id:        <chunk that was returned>
  was_correct:     false
  correct_pattern: "STORAGE_ARRAY_FIRMWARE" (new, unknown pattern)
  timestamp:       now
  notes:           "Storage array firmware bug on EMC VNX"

This builds a TRAINING QUEUE — new patterns to add to the knowledge graph.
```

### What Happens With Feedback
```
Phase 1 (now):   Feedback saved to DB, reviewed manually
Phase 2 (later): Admin reviews feedback weekly, adds new patterns
Phase 3 (future): Feedback automatically updates BM25 weights
```

---

## MISSING PIECE 4: New Pattern Addition Workflow (Filled Now)

### When a DBA Finds a New Error Not in Our Library

```
Workflow:
  Step 1: DBA pastes new log → agent returns "NO MATCH FOUND"
  Step 2: DBA clicks "Add to Knowledge Base"
  Step 3: DBA fills in a simple form:
    - Pattern name (e.g. "STORAGE_ARRAY_FIRMWARE_BUG")
    - Category (DISK / MEMORY / CPU / NETWORK / KERNEL)
    - ORA code triggered (e.g. ORA-27072)
    - Fix commands
  Step 4: System auto-extracts keywords from the pasted log
  Step 5: New pattern saved to patterns.json
  Step 6: New chunk embedded and added to Qdrant
  Step 7: BM25 index rebuilt (< 1 second for small additions)

No restart required — live addition supported.
```

---

## MISSING PIECE 5: Unknown Log Handling (Filled Now)

### Three Unknown Cases

```
CASE 1: ORA code not in our knowledge graph
  Input:    "ORA-03174 on dbhost01"
  Behaviour:
    → Dense search still runs (may find similar patterns)
    → If dense score > 0.70: show as LOW confidence match
    → If dense score < 0.70: return NO MATCH
    → Always show: "This ORA code is not in the knowledge base"
    → Show closest match + similarity score
    → Offer "Add to Knowledge Base" button

CASE 2: Log format not recognized (new log type)
  Input:    paste from exadata cell log (unknown format)
  Behaviour:
    → Parser returns: parse_result = {"success": false, "reason": "unknown_format"}
    → System falls back to raw text dense search only (no BM25, no metadata filter)
    → Returns top 3 semantic matches with low confidence flag
    → Shows: "Log format not recognized — showing closest semantic matches only"

CASE 3: Log recognized but no pattern matches
  Input:    normal syslog format, but error not in pattern library
  Behaviour:
    → All 45 patterns checked → all score < 40%
    → Return no_match_found = true
    → Show raw chunk that was closest (for DBA context)
    → Offer "Add to Knowledge Base"
```

---

## MISSING PIECE 6: Pipeline Orchestration Flow (Filled Now)

### How All 7 Stages Connect — Function Call Chain

```python
# This is the LOGICAL flow (not actual code — just the design)

def diagnose(user_input: str) -> DiagnosticReport:

    # Stage 1: Parse input
    parsed = input_parser.parse(user_input)
    # Returns: {ora_code, hostname, timestamp, keywords, intent, log_type}

    # Stage 2: SQL pre-filter (DuckDB)
    candidate_chunk_ids = metadata_db.filter(
        hostname   = parsed.hostname,
        time_range = (parsed.timestamp - 30min, parsed.timestamp + 30min),
        severity   = ["CRITICAL", "ERROR"]
    )
    # Returns: list of chunk_ids (narrows from 10,000 → ~500)

    # Stage 3A: BM25 search (on filtered candidates only)
    bm25_results = bm25_engine.search(
        query    = parsed.keywords,
        doc_ids  = candidate_chunk_ids
    )
    # Returns: [(chunk_id, bm25_score), ...]

    # Stage 3B: Dense vector search (Qdrant with payload filter)
    dense_results = qdrant.search(
        query_vector = embedder.embed(parsed.embed_text),
        filter       = {"chunk_id": {"$in": candidate_chunk_ids}},
        top_k        = 10
    )
    # Returns: [(chunk_id, cosine_score), ...]

    # Stage 4: Hybrid fusion (RRF)
    fused_results = hybrid_fuser.fuse(bm25_results, dense_results)
    # Returns: [(chunk_id, final_score), ...] top 10

    # Stage 5: Temporal correlation
    top_chunks = db.get_chunks(fused_results[:5])
    for chunk in top_chunks:
        chunk.linked_chunks = temporal_correlator.find_links(
            hostname  = chunk.hostname,
            timestamp = chunk.timestamp_start,
            window_sec = 60
        )
    # Adds linked chunks from other log sources

    # Stage 6: Pattern matching + graph traversal
    for chunk in top_chunks:
        chunk.matched_pattern = pattern_matcher.match(chunk.raw_text)
        chunk.confidence = scorer.calculate(chunk, parsed)
        chunk.causal_chain = knowledge_graph.traverse(
            ora_code = parsed.ora_code,
            pattern  = chunk.matched_pattern
        )
        chunk.fix_commands = knowledge_graph.get_fixes(chunk.matched_pattern)

    # Stage 7: Build report
    report = report_builder.build(
        query   = parsed,
        chunks  = top_chunks,
        graph   = knowledge_graph
    )
    return report
```

---

## MISSING PIECE 7: Machine-Readable Knowledge Graph Format

### The knowledge graph needs to be loadable by NetworkX in code.
### This is what graph.json must look like:

```json
{
  "nodes": [
    {
      "id": "ORA-27072",
      "type": "ORA_CODE",
      "description": "File I/O error",
      "errno_map": ["EIO=5"],
      "layer": "OS_TRIGGERED",
      "severity": "CRITICAL"
    },
    {
      "id": "SCSI_DISK_TIMEOUT",
      "type": "OS_ERROR_PATTERN",
      "category": "DISK",
      "severity": "CRITICAL"
    },
    {
      "id": "FIX_ENABLE_MULTIPATH",
      "type": "FIX_COMMAND",
      "commands": [
        "systemctl enable multipathd --now",
        "mpathconf --enable --with_multipathd y",
        "multipath -ll"
      ],
      "risk": "MEDIUM",
      "requires": "root",
      "downtime_required": false
    }
  ],
  "edges": [
    {
      "source": "ORA-27072",
      "target": "SCSI_DISK_TIMEOUT",
      "type": "caused_by",
      "probability": 0.40,
      "errno": "EIO=5"
    },
    {
      "source": "SCSI_DISK_TIMEOUT",
      "target": "FC_HBA_RESET",
      "type": "triggered_by",
      "probability": 0.45,
      "time_gap_sec": 1
    },
    {
      "source": "SCSI_DISK_TIMEOUT",
      "target": "FIX_ENABLE_MULTIPATH",
      "type": "fixed_by",
      "priority": 1
    }
  ]
}
```

### This file needs to be created (graph.json) — all 84 nodes + 80 edges.

---

## MISSING PIECE 8: Seed Data Format (Most Critical)

### The 85 errors must exist as errors.jsonl to be loaded into Qdrant.

### Each line = one chunk. Example:
```json
{"chunk_id":"seed_001","collection_id":"seed","hostname":"dbhost01","log_source":"VAR_LOG_MESSAGES","timestamp_start":"2024-03-07T02:44:18","timestamp_end":"2024-03-07T02:44:19","category":"DISK","sub_category":"SCSI","severity":"CRITICAL","ora_code":"ORA-27072","os_pattern":"SCSI_DISK_TIMEOUT","errno":"EIO=5","device":"sdb","keywords":["FAILED","DRIVER_TIMEOUT","sdb","Hardware Error","Stopping disk"],"raw_text":"Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_TIMEOUT\nMar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] Sense Key : Hardware Error [current]\nMar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] Add. Sense: Internal target failure\nMar 07 02:44:19 dbhost01 kernel: blk_update_request: I/O error, dev sdb, sector 9175826432\nMar 07 02:44:19 dbhost01 kernel: Buffer I/O error on dev sdb, logical block 1146978304\nMar 07 02:44:19 dbhost01 kernel: sd 2:0:0:0: [sdb] Stopping disk","linked_chunks":[]}
```

### 85 of these records need to be created — one per documented error.

---

## FINAL STATUS — Complete Document List

| # | Document | Status |
|---|---|---|
| 1 | OS error logs (85 errors) markdown | ✅ Done |
| 2 | ORA code mapping | ✅ Done |
| 3 | OS tier 1 missing errors | ✅ Done |
| 4 | Retrieval strategy | ✅ Done |
| 5 | Implementation plan | ✅ Done |
| 6 | Knowledge graph parts 1-3 (markdown) | ✅ Done |
| 7 | Chunking rules | ✅ Done |
| 8 | Input/output contract | ✅ Done |
| 9 | Gap analysis | ✅ Done |
| 10 | Regex pattern library parts 1-2 | ✅ Done |
| 11 | All gap answers + missing pieces | ✅ Done (this file) |
| 12 | **errors.jsonl** (seed data) | ⏳ Needs to be created |
| 13 | **graph.json** (machine-readable KG) | ⏳ Needs to be created |
| 14 | **patterns.json** (machine-readable regex) | ⏳ Needs to be created |
| 15 | **settings.yaml** | ⏳ Created during coding |
| 16 | **requirements.txt** | ⏳ Created during coding |
| 17 | **golden_test_cases.json** | ⏳ Created during coding |

Items 12, 13, 14 = machine-readable data files that must exist BEFORE coding starts.
Items 15, 16, 17 = created IN coding Phase 1.
