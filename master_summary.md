# Oracle DBA RAG Diagnostic Agent — Master Summary Document
## Everything Discussed + Everything Planned
## Version: Final Pre-Coding | Date: April 2024

---

## 1. WHAT WE ARE BUILDING

```
A deterministic, offline, no-LLM diagnostic agent for Oracle DBAs.

Input:  ORA code / raw log paste / natural language question
Output: Root cause + confidence % + causal chain + fix commands

Key constraints (confirmed by you):
  ✅ No LLM (no OpenAI, no Claude, no Ollama)
  ✅ 100% offline — runs on DBA workstation
  ✅ Pure Python
  ✅ Deterministic — same input always gives same output
  ✅ Local deployment only
```

---

## 2. THE CORE PROBLEM WE ARE SOLVING

```
When Oracle shows ORA-27072, the DBA needs to know:
  → What OS event caused it?
  → Which disk/HBA/network component failed?
  → Is this a cascade (other ORA codes will follow)?
  → What exact commands fix it?

Current reality (without this agent):
  → DBA searches MOS (My Oracle Support) manually
  → Correlates alert.log, /var/log/messages, dmesg separately
  → Takes 30-60 minutes per incident

With this agent:
  → DBA pastes logs or types ORA code
  → Gets root cause + fix in < 500ms
```

---

## 3. TECH STACK (All Decided)

| Component | Technology | Why |
|---|---|---|
| Language | Python | Confirmed |
| Vector DB | Qdrant (local mode) | No API cost, offline |
| Embeddings | all-MiniLM-L6-v2 | No API cost, 384-dim |
| Keyword Search | rank_bm25 | Exact term matching |
| Metadata Filter | DuckDB | Embedded SQL, fast |
| Knowledge Graph | NetworkX | Graph traversal in Python |
| UI | Streamlit | Simple DBA-friendly UI |
| API | FastAPI | Optional REST layer |
| Config | settings.yaml | All thresholds centralized |

---

## 4. THE 7-STAGE RETRIEVAL PIPELINE

```
Stage 1: Input Parser
  → Detects: ORA code query / raw log paste / natural language
  → Extracts: ora_code, hostname, timestamp, keywords, intent
  → Detects: platform (Linux / AIX / Solaris / Windows / Exadata)

Stage 2: Metadata Pre-Filter (DuckDB)
  → SQL filter: hostname + time window (±30 min) + severity
  → Narrows: 10,000 chunks → ~500 candidates
  → Fast: < 10ms

Stage 3A: BM25 Search (rank_bm25)
  → Exact keyword matching on filtered candidates
  → Returns: (chunk_id, bm25_score) pairs

Stage 3B: Dense Vector Search (Qdrant)
  → Semantic similarity on same candidates
  → Returns: (chunk_id, cosine_score) pairs

Stage 4: Hybrid Fusion (RRF)
  → Combines BM25 + Dense using Reciprocal Rank Fusion
  → Weight: BM25=40%, Dense=60%
  → Returns: top 10 chunks

Stage 5: Temporal Correlation
  → Finds chunks from OTHER log sources within 60-second window
  → Links: /var/log/messages chunk ↔ alert.log chunk (same host, same time)
  → Detects cascade sequences

Stage 6: Pattern Matching + Graph Traversal (NetworkX)
  → Runs 45 regex patterns against retrieved chunks
  → Scores confidence using formula:
       keyword_match×40 + bm25×30 + dense×20 + temporal_bonus×10
  → Traverses knowledge graph to find root cause and fix commands

Stage 7: Report Builder
  → Assembles structured JSON output
  → Human-readable Streamlit display
  → Confidence levels: HIGH≥80% / MEDIUM 60-79% / LOW 40-59% / NO MATCH <40%
```

---

## 5. KNOWLEDGE DATASET (All Documented)

### Error Scenarios Documented

| Platform | Count |
|---|---|
| Linux (OEL / RHEL) | 85 errors |
| AIX | 20 errors |
| Solaris + HP-UX | 20 errors |
| Windows + Exadata + Middleware | 25 errors |
| Data Guard errors | 5 errors |
| CDB/PDB errors | 5 errors |
| RMAN errors | 5 errors |
| Cloud (OCI / AWS RDS) | 5 errors |
| Security / TDE / Vault | 5 errors |
| Multi-error Cascades | 7 cascades |
| **TOTAL** | **~182 scenarios** |

### Pattern Library

```
45 OS error patterns defined with:
  match_any:  1 regex hit = pattern detected
  match_all:  all must hit = HIGH confidence
  exclude:    disqualifies false positives (recovery messages)

Pattern categories:
  12 Disk/I-O patterns     (SCSI, FC HBA, multipath, ext4, XFS, NFS)
  10 Memory patterns       (OOM, shmget, HugePages, semaphore, FD limit)
  4  CPU patterns          (run queue, steal, soft lockup, hard lockup)
  9  Kernel patterns       (panic, MCE, null ptr, SELinux, NUMA)
  11 Network patterns      (bonding, conntrack, IB, NTP, iptables, socket)
  Plus: alert.log patterns + metric threshold patterns (iostat, sar, vmstat)
```

### Knowledge Graph Structure

```
Nodes: 3 types
  ORA_CODE node      → e.g. ORA-27072
  OS_ERROR_PATTERN   → e.g. SCSI_DISK_TIMEOUT
  FIX_COMMAND        → e.g. FIX_ENABLE_MULTIPATH

Edges: 3 types
  ORA_CODE  --caused_by-->   OS_ERROR_PATTERN  (with probability %)
  OS_PATTERN --triggered_by-> another pattern   (with time gap)
  OS_PATTERN --fixed_by-->    FIX_COMMAND       (with priority order)

Graph traversal:
  Input: ORA-27072 found + SCSI_DISK_TIMEOUT matched
  Traverse: ORA-27072 → SCSI_DISK_TIMEOUT → FC_HBA_RESET → FIX_ENABLE_MULTIPATH
  Output: root cause + fix priority order
```

---

## 6. MULTI-PLATFORM SUPPORT

### Platform Detection

```
Agent auto-detects platform from:
  → uname.txt in AHF ZIP
  → ORA error format: "Linux-x86_64 Error" vs "IBM AIX" vs "SunOS"
  → Log format (errpt output = AIX, fmadm output = Solaris)
  → If cannot detect: ask DBA from dropdown
```

### Platform-Specific Differences Documented

| Platform | Log Source | Disk Name | ORA errno line |
|---|---|---|---|
| Linux | /var/log/messages | sdb, sdc | Linux-x86_64 Error: 5 |
| AIX | errpt -a (binary) | hdisk0, hdisk1 | IBM AIX RISC System/6000 Error: 5 |
| Solaris | /var/adm/messages + fmadm | c0t0d0 | SunOS-5.11 Error: 5 |
| HP-UX | /var/adm/syslog | /dev/disk/disk3 | HP-UX Error: 5 |
| Windows | Event Viewer (Event ID) | PhysicalDisk0 | O/S-Error: (OS 5) |
| Exadata | cellcli alerthistory | FD_00_cell01 | Linux (cell runs OEL) |
| OCI | /var/log/messages + cloud-agent | nvme0n1 | Linux-x86_64 Error: 5 |

---

## 7. CASCADE SEQUENCE DETECTION

```
What makes this agent smart (not just a lookup table):

7 cascade patterns documented:
  CASCADE 1: Disk failure → ORA-27072 → ORA-00353 → ORA-00470 → ORA-00603
  CASCADE 2: Swap storm → OOM → ORA-00603 → CRS restart → ORA-04031
  CASCADE 3: NIC failure → CRS-1618 → ORA-29740 → ORA-03113 clients drop
  CASCADE 4: /arch full → ORA-00257 → DB suspended → ORA-04031
  CASCADE 5: FC HBA → multipath down → ORA-15080 → ORA-15130 → crash
  CASCADE 6: Cgroup kills ohasd → CRS dies → ORA-29701 → DB orphaned
  CASCADE 7: Soft lockup → Kernel panic → reboot → crash recovery

Agent rule:
  If 2+ ORA codes appear within 60 seconds on same host
  → Check cascade pattern library
  → Report ONE root cause for ALL ORA codes
  → Not separate incidents
```

---

## 8. FALSE POSITIVE SUPPRESSION

```
30+ normal Oracle messages that agent will NOT flag:
  "Thread 1 advanced to log sequence"   → normal log switch
  "Checkpoint not complete"             → normal under heavy load
  "ARC0: Evaluating archive log"        → normal archiver work
  "multipathd: add missing path"        → path RECOVERY (good news)
  "qla2xxx: Link Up"                    → HBA recovered (good news)
  "CRS-6011: resource is online"        → normal CRS event
  "db_recovery_file_dest_size 75% used" → warning, not error

Threshold rules:
  "Checkpoint not complete":  < 5/hour = normal, > 20/hour = error
  FRA usage:                  < 90% = normal, > 95% = critical
  log file sync avg wait:     < 10ms = normal, > 30ms = error
```

---

## 9. INPUT / OUTPUT CONTRACT

### 3 Input Modes

```
Mode 1: ORA code query
  "ORA-27072 on dbhost01 at 2024-03-07 02:44:18"

Mode 2: Raw log paste
  Paste from alert.log / /var/log/messages / dmesg / CRS / errpt

Mode 3: Natural language
  "Why does ORA-27072 happen?"
  "What ORA code appears when disk is full?"
```

### Output Always Contains

```
→ Root cause (pattern name + label)
→ Confidence % (HIGH/MEDIUM/LOW/NO MATCH)
→ ORA code (code + errno + layer)
→ Causal chain (step-by-step what happened)
→ Evidence (ranked chunks from retrieved logs)
→ Fix commands (priority ordered, with risk level)
→ Diagnostic commands (run now to confirm)
→ Related errors (other ORA codes that may also appear)
```

### Response Time Targets

```
ORA code query:         < 500ms
Raw log paste (<20 ln): < 500ms
Natural language:       < 800ms
AHF ZIP ingestion:      < 60 seconds (background)
```

---

## 10. PROJECT DIRECTORY STRUCTURE

```
oracle_dba_agent/
├── config/
│   └── settings.yaml              ← all thresholds, paths, model names
├── data/
│   ├── seeds/errors.jsonl         ← 182 scenarios (machine-readable)
│   ├── qdrant_storage/            ← vector DB on disk
│   └── duckdb/metadata.duckdb    ← metadata SQL DB
├── src/
│   ├── parsers/                   ← 8 log type parsers + platform detector
│   ├── chunker/                   ← event_chunker.py
│   ├── embeddings/                ← sentence-transformers wrapper
│   ├── vectordb/                  ← Qdrant client wrapper
│   ├── retrieval/                 ← 7-stage pipeline
│   ├── knowledge_graph/           ← NetworkX + pattern regex
│   │   └── data/
│   │       ├── graph.json         ← machine-readable knowledge graph
│   │       └── patterns.json      ← machine-readable regex library
│   ├── agent/                     ← orchestration (calls all stages)
│   ├── api/                       ← FastAPI REST endpoints
│   └── ui/                        ← Streamlit app
├── tests/
│   ├── test_parsers.py
│   ├── test_retrieval.py
│   ├── test_agent.py
│   └── golden_test_cases.json     ← 6 golden tests
├── scripts/
│   └── load_seeds.py              ← one-time seed data loader
├── requirements.txt
└── README.md
```

---

## 11. CODING BUILD ORDER (Planned Phases)

```
PHASE 1 — Foundation (Day 1)
  → Create project directory structure
  → Write requirements.txt
  → Write settings.yaml
  → Initialize Qdrant collection
  → Initialize DuckDB with schema
  → Create errors.jsonl from our 182 documented scenarios
  → Create graph.json from our knowledge graph docs
  → Create patterns.json from our regex library

PHASE 2 — Data Pipeline (Day 2)
  → Platform detector (detect Linux/AIX/Solaris/Windows)
  → 8 log parsers (syslog, alert_log, dmesg, iostat, sar, vmstat, df, crs)
  → AIX parser (errpt format)
  → Event chunker (apply chunking rules)
  → Seed data loader (load_seeds.py)

PHASE 3 — Retrieval Engine (Day 3)
  → Embedder (sentence-transformers wrapper)
  → BM25 index builder (in-memory)
  → Qdrant search client
  → Hybrid fusion (RRF algorithm)
  → Temporal correlator (cross-log linking)
  → Metadata pre-filter (DuckDB queries)

PHASE 4 — Agent Logic (Day 4)
  → Pattern matcher (45 regex patterns)
  → Knowledge graph loader (NetworkX from graph.json)
  → Graph traverser (root cause finding)
  → Confidence scorer (formula: 40/30/20/10 weights)
  → Cascade detector (7 cascade patterns)
  → False positive filter (suppress normal messages)
  → Report builder (structured JSON + human-readable)

PHASE 5 — Interface (Day 5)
  → Input parser (3 modes: ORA/log/NL)
  → FastAPI endpoints (POST /diagnose)
  → Streamlit UI (paste logs, ORA code, question)
  → Feedback mechanism (thumbs up/down per report)
  → New pattern addition UI (DBA adds unknown errors)

PHASE 6 — Testing (Day 6)
  → Run 6 golden test cases
  → Validate confidence scores
  → Test false positive suppression
  → Test cascade detection
  → Test each platform parser
```

---

## 12. ALL DOCUMENTATION FILES CREATED

| # | File | Contents |
|---|---|---|
| 1 | implementation_plan.md | Tech stack, constraints, build strategy |
| 2 | retrieval_strategy.md | 7-stage pipeline design |
| 3 | knowledge_graph_part1.md | KG schema, ORA nodes, disk/memory patterns |
| 4 | knowledge_graph_part2.md | CPU, kernel, network patterns + edges |
| 5 | knowledge_graph_part3.md | Fix command nodes + graph summary |
| 6 | chunking_rules.md | How each log type is split into event chunks |
| 7 | input_output_contract.md | Exact input formats + full output schema |
| 8 | os_level_errors_part1.md | 30 Linux CPU/Memory/Kernel errors |
| 9 | os_level_errors_part2.md | 30 Linux Disk/Network errors |
| 10 | os_level_errors_part3.md | 25 Linux remaining errors + master table |
| 11 | oracle_real_logs_part1.md | Real ORA-00600, ORA-04031, ORA-00060 logs |
| 12 | oracle_real_logs_part2.md | Real CRS, ASM, RAC, OS metric logs |
| 13 | oracle_real_logs_part3.md | AWR excerpts, incident traces, ORA-00600 variants |
| 14 | os_ora_code_mapping.md | OS error → ORA code mapping table |
| 15 | os_tier1_missing_errors.md | 12 Tier 1 missing OS errors |
| 16 | os_error_gap_analysis.md | OS error gap analysis |
| 17 | gap_analysis.md | 13 pre-coding gaps (all filled) |
| 18 | complete_precoding_checklist.md | All 8 missing pieces + answers |
| 19 | regex_pattern_library_part1.md | Disk + Memory + CPU regex patterns |
| 20 | regex_pattern_library_part2.md | Kernel + Network + metric patterns |
| 21 | platform_support.md | Multi-platform architecture |
| 22 | platform_aix_errors.md | 20 AIX errors (errpt, lspath, lparstat) |
| 23 | platform_solaris_hpux_errors.md | 15 Solaris + 5 HP-UX errors |
| 24 | platform_windows_exadata_middleware_errors.md | 25 Windows+Exadata+Middleware |
| 25 | final_gap_analysis.md | 11 remaining gaps found + recommendations |
| 26 | cascade_sequences.md | 7 multi-error cascade patterns (full logs) |
| 27 | false_positive_and_awr_correlation.md | 30+ false positives + AWR wait mapping |
| 28 | dataguard_cdb_rman_errors.md | Data Guard + CDB/PDB + RMAN errors |
| 29 | version_cloud_runbooks_security.md | Version diffs + Cloud + Runbooks + Security |

**Total: 29 documentation files**

---

## 13. KEY DESIGN DECISIONS (All Confirmed)

| Decision | Choice | Reason |
|---|---|---|
| LLM | None | Deterministic, offline, no hallucination |
| Embedding text | Metadata prefix + raw text | Best retrieval quality |
| Scoring weights | Keyword=40, BM25=30, Dense=20, Temporal=10 | Exact terms matter most |
| Confidence thresholds | 80/60/40/0 | Practical DBA usage |
| Timezone default | Asia/Kolkata (IST) | User's environment |
| BM25 storage | In-memory | Only 182 chunks, < 0.5s rebuild |
| Qdrant distance | Cosine | Best for text similarity |
| Vector size | 384 | all-MiniLM-L6-v2 output |
| Multi-ORA priority | OS layer ORA code = primary | Closest to root cause |
| Platform priority | Linux first, AIX second | User's environment |

---

## 14. WHAT STILL NEEDS TO BE CREATED DURING CODING

```
Before ingestion can happen (Phase 1):
  errors.jsonl  ← convert 182 markdown scenarios to machine-readable JSONL
  graph.json    ← convert knowledge graph docs to NetworkX-loadable JSON
  patterns.json ← convert regex library docs to Python-loadable dict

These are created in Phase 1 of coding as the very first step.
```

---

## 15. HOW WE KNOW IT WORKS — 6 GOLDEN TEST CASES

```
Test 1: ORA-27072 on dbhost01
  Expected: root_cause = SCSI_DISK_TIMEOUT or FC_HBA_RESET, confidence >= 80%

Test 2: ORA-00257
  Expected: root_cause = FILESYSTEM_ARCH_FULL, fix contains RMAN DELETE

Test 3: "OOM killer killed oracle"
  Expected: ora_code = ORA-00603, root_cause = OOM_KILLER_ACTIVE

Test 4: ORA-00001 unique constraint
  Expected: no_match_found = true (not an OS error)

Test 5: "What ORA code appears when disk is full?"
  Expected: ORA-00257 in top 2 results

Test 6: Paste AIX errpt DISK_ERR7 output
  Expected: platform = AIX, root_cause = SCSI_DISK_TIMEOUT (AIX variant)
```

---

## READY TO CODE

```
Documentation phase:  COMPLETE ✅
All gaps filled:      COMPLETE ✅
All decisions made:   COMPLETE ✅

Awaiting: "proceed" from DBA
```
