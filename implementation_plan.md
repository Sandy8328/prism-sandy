# Oracle DBA AI Agent — Framework Design
## RAG + Vector Search Architecture
## Status: Pre-Approval Design | No Code Written Yet

---

## 1. THE PROBLEM THIS SOLVES

A DBA sees this in alert.log at 3 AM:
```
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
```

Today the DBA must:
1. Search MOS (My Oracle Support) manually
2. SSH into the host and dig through /var/log/messages
3. Run iostat, sar, multipath commands
4. Cross-reference timestamps across 5+ log files
5. Figure out root cause (was it SCSI timeout? FC HBA reset? multipath?)

**The agent does all of this automatically and answers:**
> "ORA-27072 at 03:14:18 was caused by SCSI disk timeout on sdb (see /var/log/messages 03:14:18).
> Root cause: FC HBA link reset (qla2xxx LOGO). Storage path recovered after 10 seconds.
> Recommended action: Check HBA firmware, enable multipath, review storage array event log."

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                    DBA INPUT                                 │
│   "ORA-27072 on prod host at 3am"  OR  paste raw log        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   AGENT LAYER                                │
│   - Understands query intent                                 │
│   - Decides which logs to retrieve                           │
│   - Calls retrieval tools                                    │
│   - Synthesizes final answer                                 │
└────────┬────────────────┬────────────────┬───────────────────┘
         │                │                │
         ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐
│  VECTOR DB   │  │  STRUCTURED  │  │   LIVE AHF/TFA       │
│  (Semantic   │  │  METADATA DB │  │   LOG COLLECTOR      │
│   Search)    │  │  (Filter by  │  │   (Real-time logs    │
│              │  │  ORA code,   │  │   from the host)     │
│  Dense +     │  │  timestamp,  │  │                      │
│  Sparse      │  │  hostname,   │  │                      │
│  Hybrid      │  │  severity)   │  │                      │
└──────────────┘  └──────────────┘  └──────────────────────┘
         │                │                │
         └────────────────┴────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   RESPONSE LAYER                             │
│   - Root cause identified                                    │
│   - OS error ↔ ORA code correlation shown                   │
│   - Fix commands provided                                    │
│   - Confidence score given                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. DATA PIPELINE (How Logs Become Searchable)

### Step 1 — Log Collection (Input Sources)

```
AHF/TFA Collection ZIP
    │
    ├── alert_PROD.log          → Oracle Engine Errors
    ├── PROD_ora_28821.trc      → Trace Files
    ├── /var/log/messages       → OS Errors (our main dataset)
    ├── dmesg_output.txt        → Kernel Errors
    ├── iostat_output.txt       → Disk I/O Metrics
    ├── sar_cpu.txt             → CPU Metrics
    ├── vmstat.txt              → Memory/Swap Metrics
    ├── ocssd.log               → CRS Errors
    ├── crsd.log                → Clusterware Errors
    └── awrrpt_1_1082_1083.html → AWR Report
```

### Step 2 — Parsing (Structured Extraction)

Each log line is parsed into structured fields:

```json
{
  "timestamp": "2024-03-07T02:44:18+05:30",
  "hostname": "dbhost01",
  "source_file": "/var/log/messages",
  "log_type": "OS_KERNEL",
  "category": "DISK",
  "sub_category": "SCSI_TIMEOUT",
  "raw_message": "sd 2:0:0:0: [sdb] FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_TIMEOUT",
  "device": "sdb",
  "errno": "EIO",
  "errno_code": 5,
  "ora_code_triggered": "ORA-27072",
  "severity": "CRITICAL",
  "collection_id": "tfa_srdc_ora27072_Mon_Mar_07_2024"
}
```

### Step 3 — Chunking Strategy (Critical for RAG Quality)

**Bad chunking** = one line per chunk → loses context
**Good chunking** = one error event per chunk → preserves meaning

```
CHUNK UNIT = One Error Event Block
============================================
An "event" = all log lines within a 60-second 
window from the same source that belong to 
the same error incident.

Example — SCSI timeout event (one chunk):
------------------------------------------
[timestamp_start] kernel: sd 2:0:0:0: [sdb] FAILED...
[timestamp+0s]    kernel: sd 2:0:0:0: [sdb] Sense Key: Hardware Error
[timestamp+1s]    kernel: blk_update_request: I/O error, dev sdb
[timestamp+1s]    kernel: Buffer I/O error on dev sdb
[timestamp+1s]    kernel: sd 2:0:0:0: [sdb] Stopping disk
------------------------------------------
Chunk metadata: {category: DISK, ora_code: ORA-27072, severity: CRITICAL}

CROSS-LOG LINKING:
------------------------------------------
Same timestamp window also captures:
- Oracle alert.log: ORA-27072 (linked chunk)
- iostat: %util=100 on sdb (supporting chunk)
These three chunks are LINKED by timestamp + hostname
```

### Step 4 — Embedding (Making Chunks Searchable)

```
Each chunk → Embedding Model → 1536-dimension vector

Model options (in order of preference):
1. text-embedding-3-large (OpenAI) — best quality
2. BGE-M3 (open source) — good for technical text
3. nomic-embed-text (local) — privacy, no API cost

What gets embedded:
- The raw log text
- The structured metadata fields (concatenated)
- The ORA code annotation
- The fix command

Result: chunk can be found by searching for:
- "ORA-27072" → finds SCSI timeout chunks
- "disk timeout" → finds same chunks
- "sdb stopped" → finds same chunks
- "FC HBA reset" → finds same AND related chunks
```

### Step 5 — Storage (Vector Database)

```
PRIMARY: Qdrant (recommended)
- Runs locally or as Docker container
- Supports payload filtering (filter by ORA code, hostname, date)
- Supports hybrid search (dense + sparse BM25)
- Free, open source

ALTERNATIVE: ChromaDB (simpler, good for MVP)

COLLECTIONS (like tables):
┌──────────────────────────────┐
│  oracle_os_errors            │  ← Our 50+ OS error chunks
│  oracle_alert_log            │  ← ORA-600, ORA-07445 chunks
│  oracle_awr_reports          │  ← AWR wait event chunks
│  oracle_crs_logs             │  ← CRS/Grid error chunks
│  oracle_trace_files          │  ← Trace file excerpts
└──────────────────────────────┘

Each vector has:
- The 1536-dim embedding
- The full metadata payload
- The raw text (for display)
```

---

## 4. RETRIEVAL LOGIC (How the Agent Finds the Right Answer)

### Two-Stage Retrieval

```
STAGE 1 — FILTER (Metadata Pre-filter)
=======================================
Before semantic search, filter by:
- hostname (only search logs from dbhost01)
- time_range (only ±30 min from error time)
- log_type (OS only, or DB only, or ALL)
- severity (CRITICAL only, or all)

This reduces search space from 100,000 chunks → 500 chunks

STAGE 2 — HYBRID SEARCH
========================
Run TWO searches in parallel on filtered chunks:

A. Dense Vector Search (semantic meaning)
   Query: "disk IO error SCSI timeout"
   Finds: chunks about disk failures even if exact words differ

B. Sparse BM25 Search (exact keyword match)
   Query: "ORA-27072 EIO sdb"
   Finds: chunks with exact ORA code and device name

COMBINE with RRF (Reciprocal Rank Fusion):
   Final score = 0.6 × dense_score + 0.4 × sparse_score

Return top 5-10 chunks → pass to Agent LLM
```

### Cross-Log Correlation (Key Differentiator)

```
When ORA-27072 is found in alert.log chunk:
  → Agent automatically retrieves linked OS chunks 
    from /var/log/messages at same timestamp
  → Agent automatically retrieves iostat chunk 
    showing %util=100 at same time
  → Agent shows the complete causal chain:

  /var/log/messages 02:44:18 → SCSI timeout on sdb
       ↓ (same timestamp)
  alert.log 02:44:19         → ORA-27072 File I/O error
       ↓ (same timestamp)
  iostat 02:44:09            → sdb %util=100, await=259ms
       ↓ (CONCLUSION)
  ROOT CAUSE: Storage I/O saturation → disk queue timeout → Oracle I/O error
```

---

## 5. AGENT DESIGN (The Intelligence Layer)

### Agent Type: ReAct (Reason + Act)

```
DBA Query: "Why did ORA-27072 happen at 3am on prod?"

Agent thinks step by step:

THOUGHT 1: "ORA-27072 = File I/O error. Need to find OS logs at same time."
ACTION 1: search_vector_db(query="ORA-27072 prod", time="03:14:18", type="OS")
RESULT 1: SCSI timeout on sdb, FC HBA LOGO event found

THOUGHT 2: "FC HBA reset caused SCSI timeout. Need context — was it one-time or recurring?"
ACTION 2: search_vector_db(query="qla2xxx HBA reset prod", time="last 7 days")
RESULT 2: Same HBA reset happened 3 times this week

THOUGHT 3: "Recurring FC HBA resets = hardware issue. Check if multipath was active."
ACTION 3: search_vector_db(query="multipath paths prod sdb")
RESULT 3: multipath not configured, single path only

FINAL ANSWER:
"ORA-27072 caused by FC HBA link reset (qla2xxx LOGO at 02:44:18).
 This is the 3rd occurrence this week.
 Root cause: No multipath configured — single point of failure on HBA.
 Fix: Enable multipath (dm-multipath), check HBA cable/SFP, review switch logs."
```

### Agent Tools (Functions the Agent Can Call)

```
Tool 1: search_logs(query, time_range, log_type, hostname)
  → Searches vector DB with hybrid retrieval

Tool 2: get_ora_code_info(ora_code)
  → Returns known causes and fixes for an ORA code

Tool 3: correlate_timestamps(timestamp, hostname, window_minutes)
  → Finds all log chunks within time window across ALL log types

Tool 4: get_fix_commands(error_type)
  → Returns OS fix commands for a given error category

Tool 5: check_recurrence(error_pattern, hostname, days)
  → Checks if same error has occurred before
```

---

## 6. TECHNOLOGY STACK (What Will Be Used)

```
COMPONENT          TECHNOLOGY         WHY
─────────────────────────────────────────────────────────
Log Parser         Python             Custom parsers per log type
Chunker            LangChain          TextSplitter with overlap
Embedding Model    text-embedding-3-large / BGE-M3    Quality
Vector Database    Qdrant             Hybrid search, payload filter
Metadata Store     SQLite / DuckDB    Fast timestamp filtering
Agent LLM          GPT-4o / Claude    Reasoning over retrieved chunks
Agent Framework    LangGraph          ReAct agent with tools
API Layer          FastAPI            REST API for DBA queries
UI (optional)      Streamlit          Simple DBA chat interface
Orchestration      Docker Compose     Single-command deployment
```

---

## 7. WHAT THE DBA EXPERIENCE LOOKS LIKE

### Input Option 1 — Paste ORA code + timestamp
```
DBA: "ORA-27072 on dbhost01 at 2024-03-07 02:44:18"
```

### Input Option 2 — Upload AHF ZIP file
```
DBA uploads: tfa_srdc_ora27072_Mon_Mar_07_2024.zip
Agent: Automatically parses all files in ZIP
       Indexes into vector DB
       Answers immediately
```

### Input Option 3 — Natural language question
```
DBA: "Why does LGWR keep dying on the prod server?"
DBA: "What is causing the node eviction every Tuesday at 3am?"
DBA: "Is the HugePages config correct on dbhost01?"
```

### Output Format
```
ROOT CAUSE:     SCSI disk timeout → FC HBA link reset
EVIDENCE:       /var/log/messages [02:44:18] — qla2xxx LOGO event
                alert.log [02:44:19]         — ORA-27072 EIO
                iostat [02:44:09]            — sdb %util=100
ORA CODE:       ORA-27072 (Linux Error 5: EIO)
RECURRENCE:     3 times this week
FIX COMMANDS:   [shown here]
CONFIDENCE:     94%
```

---

## 8. PHASED BUILD PLAN

```
PHASE 1 — Data Foundation (Build first)
=========================================
✓ All log samples documented (DONE)
✓ ORA code mapping documented (DONE)
→ Build log parsers (one per log type)
→ Build chunker with metadata extraction
→ Load all 85 error scenarios into vector DB
→ Test retrieval quality

PHASE 2 — Retrieval Engine
============================
→ Implement hybrid search (dense + sparse)
→ Implement cross-log timestamp correlation
→ Implement metadata pre-filtering
→ Test: given ORA-27072 → does it find sdb SCSI timeout?

PHASE 3 — Agent Layer
=======================
→ Build ReAct agent with 5 tools
→ Connect agent to retrieval engine
→ Test multi-step reasoning scenarios

PHASE 4 — Interface
=====================
→ FastAPI REST endpoint
→ Streamlit chat UI
→ AHF ZIP file upload support
→ Docker Compose packaging
```

---

## 9. OPEN QUESTIONS FOR YOUR REVIEW

> [!IMPORTANT]
> **Q1: Deployment Target**
> Do you want this to run:
> - Locally on the DBA's Mac/Linux workstation?
> - As a server that multiple DBAs connect to?
> - Both (local dev + server deployment)?

> [!IMPORTANT]
> **Q2: LLM Choice**
> Do you want to use:
> - OpenAI GPT-4o (requires API key, best reasoning)
> - Claude (requires API key, good for long context)
> - Local LLM like Ollama/Llama3 (no API key, runs on your machine, slower)
> - Start with OpenAI, then add local option?

> [!IMPORTANT]
> **Q3: Real-time vs Batch**
> Should the agent:
> - Work only on uploaded AHF ZIP files (batch mode)?
> - Also connect live to a running Oracle host via SSH?
> - Both?

> [!NOTE]
> **Q4: Scope of Phase 1**
> Should Phase 1 use only our documented 85 errors as training data,
> or do you also have real AHF ZIP files you want to ingest?

> [!NOTE]
> **Q5: Language**
> All code in Python? Or do you prefer a specific language?
```
