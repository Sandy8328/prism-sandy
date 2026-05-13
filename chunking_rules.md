# Chunking Rules — How to Split Each Log Type Into Event Blocks
## Oracle DBA RAG Agent | Temperature: 0.0

---

## WHAT IS A CHUNK?

```
A CHUNK = One self-contained error event block.

Rules:
  - Contains ALL log lines belonging to ONE error incident
  - Has a single timestamp anchor (the first log line's time)
  - Has structured metadata extracted from its content
  - Is stored as ONE unit in the vector DB

BAD chunk (too small — loses context):
  "Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED"

GOOD chunk (complete event):
  "Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED...
   Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: Sense Key: Hardware Error
   Mar 07 02:44:19 dbhost01 kernel: blk_update_request: I/O error, dev sdb
   Mar 07 02:44:19 dbhost01 kernel: Buffer I/O error on dev sdb
   Mar 07 02:44:19 dbhost01 kernel: sd 2:0:0:0: [sdb] Stopping disk"
```

---

## GLOBAL CHUNKING RULES (Apply to ALL log types)

```
RULE 1: Time Window
  All log lines within 60 seconds of the anchor line = same chunk
  Exception: 30 seconds for network errors (faster events)
  Exception: 120 seconds for multipath recovery (slower events)

RULE 2: Same Host
  Lines must share the same hostname field
  Cross-host lines are NEVER merged into same chunk

RULE 3: Same Error Family
  Lines must belong to the same error device/process
  Example: sdb lines and sdc lines = SEPARATE chunks even if same time

RULE 4: Chunk Size Limit
  Maximum 50 lines per chunk
  If event produces > 50 lines, split at 50 with overlap of 5 lines

RULE 5: Overlap Between Adjacent Chunks
  Last 3 lines of chunk N = first 3 lines of chunk N+1
  Prevents missing an event that spans a chunk boundary

RULE 6: Metadata Extraction
  Every chunk MUST have these fields populated:
    timestamp_start  (ISO8601)
    timestamp_end    (ISO8601)
    hostname         (string)
    log_source       (enum)
    category         (enum: CPU|MEMORY|DISK|NETWORK|KERNEL)
    severity         (enum: CRITICAL|ERROR|WARNING|INFO)
    ora_code         (string or null)
    errno            (string or null)
    device           (string or null)
    keywords         (list of strings)
    raw_text         (full chunk text)
    chunk_id         (UUID)
```

---

## LOG TYPE 1: /var/log/messages (SYSLOG format)

### Line Format
```
Mon DD HH:MM:SS hostname process[pid]: message
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED Result: ...
```

### Chunk Boundary Rules
```
NEW CHUNK starts when ANY of these appear:
  1. A new ERROR/CRITICAL keyword appears after a gap > 60 seconds
  2. A different device appears (sdb → sdc = new chunk)
  3. A different process appears (kernel → multipathd = new chunk)
  4. A different error family appears (SCSI → OOM = new chunk)

SAME CHUNK continues when:
  - Same device mentioned (sdb stays sdb)
  - Time gap < 60 seconds
  - Lines are clearly continuation (Sense Key, Add. Sense, etc.)
  - Recovery messages follow the error (link up after link down)

EXAMPLE — Single chunk (SCSI timeout):
  Mar 07 02:44:18 kernel: sd 2:0:0:0: [sdb] FAILED...         ← anchor
  Mar 07 02:44:18 kernel: sd 2:0:0:0: [sdb] Sense Key...      ← same chunk
  Mar 07 02:44:18 kernel: sd 2:0:0:0: Add. Sense...           ← same chunk
  Mar 07 02:44:19 kernel: blk_update_request: I/O error, sdb  ← same chunk
  Mar 07 02:44:19 kernel: Buffer I/O error on dev sdb          ← same chunk
  Mar 07 02:44:19 kernel: sd 2:0:0:0: [sdb] Stopping disk     ← same chunk
  [60 second gap]
  Mar 07 02:45:28 kernel: sd 2:0:0:0: [sdb] Link Up           ← NEW chunk (recovery)
```

### Metadata Extraction — /var/log/messages
```
timestamp:   regex → r'(\w{3}\s+\d+\s+\d+:\d+:\d+)'
hostname:    regex → r'\d+:\d+:\d+\s+(\S+)\s+'
process:     regex → r'hostname\s+(\S+)\[?\d*\]?:'
device:      regex → r'\[(sd[a-z]+|dm-\d+|nvme\d+n\d+|mpatha?\w*)\]'
errno:       regex → r'errno[=:\s]+(\d+)' or 'Error: (\d+):'
severity:    rule  → if 'FAILED|panic|OOM|killed|error' → CRITICAL/ERROR
keywords:    extract top 10 non-stopword tokens from raw_text
```

---

## LOG TYPE 2: Oracle alert.log

### Line Format
```
DDD Mon DD HH:MM:SS YYYY         ← timestamp line (standalone)
ORA-27072: File I/O error         ← error line (no timestamp prefix)
Linux-x86_64 Error: 5: EIO       ← continuation
Additional information: 4         ← continuation
```

### Chunk Boundary Rules
```
CRITICAL DIFFERENCE from syslog:
  alert.log timestamps appear ALONE on a line, not prefixed per line

NEW CHUNK starts when:
  1. A standalone timestamp line appears AND next line has ORA- code
  2. A new standalone timestamp line appears after any ORA- block ends

SAME CHUNK continues when:
  - Lines after ORA- code continue the same incident
  - "Errors in file ... .trc" line belongs to same chunk as the ORA code
  - "Additional information:" lines belong to same chunk

EXAMPLE — Single chunk:
  Tue Apr 21 03:14:19 2024                          ← timestamp anchor
  Errors in file .../PROD_dbw0_1821.trc:            ← same chunk
  ORA-27072: File I/O error                         ← same chunk
  Linux-x86_64 Error: 5: Input/output error         ← same chunk
  Additional information: 4                          ← same chunk
  Additional information: 0                          ← same chunk
  Additional information: 0                          ← same chunk
  [next standalone timestamp = NEW chunk]
```

### Metadata Extraction — alert.log
```
timestamp:   regex → r'^\w{3}\s+\w{3}\s+\d+\s+\d+:\d+:\d+\s+\d{4}$'
ora_code:    regex → r'ORA-(\d{5})'
errno:       regex → r'Linux-x86_64 Error: (\d+):'
trace_file:  regex → r'Errors in file (.+\.trc)'
category:    lookup → ORA code → category from knowledge graph
severity:    rule   → all ORA codes in alert.log = ERROR or CRITICAL
```

---

## LOG TYPE 3: dmesg

### Line Format
```
[seconds.microseconds] message
[821343.182821] sd 2:0:0:0: [sdb] FAILED Result: ...
```

### Chunk Boundary Rules
```
Time is in seconds since boot, not wall-clock time
Must convert to wall-clock by: boot_time + dmesg_seconds = wall_clock

NEW CHUNK starts when:
  1. Time gap > 60 seconds (in dmesg seconds)
  2. Different hardware device mentioned

SAME CHUNK continues when:
  - Same device mentioned
  - Time gap < 60 seconds
  - Lines are clearly continuation (Call Trace lines belong together)

SPECIAL: Call Trace blocks
  All lines from "Call Trace:" until blank line = same chunk
  These are stack traces — never split a Call Trace
```

### Metadata Extraction — dmesg
```
timestamp:   regex → r'^\[(\d+\.\d+)\]'  → convert to wall-clock
module:      regex → r'\[(\w+)\]' (kernel module name)
device:      regex → r'(sd[a-z]+|nvme\d+|eth\d+|bond\d+|ib\d+)'
severity:    rule  → 'BUG:|panic|LOCKUP|MCE|Hardware Error' = CRITICAL
```

---

## LOG TYPE 4: iostat (-xmt format)

### Line Format
```
MM/DD/YYYY HH:MM:SS AM            ← timestamp block header
Device: rrqm/s wrqm/s r/s w/s ... await svctm %util
sdb     0.00   14.00  0.00 821.00 ... 259.22 1.22  100.00
sdc     0.00   12.00  0.00 798.00 ... 248.82 1.25  100.00
```

### Chunk Boundary Rules
```
Each timestamp block = ONE chunk per DEVICE
Reason: sdb and sdc have different await/util values = separate events

EXAMPLE:
  Timestamp 02:14:09 → sdb row → ONE chunk (metadata: device=sdb)
  Timestamp 02:14:09 → sdc row → SEPARATE chunk (metadata: device=sdc)
  Timestamp 02:15:09 → sdb row → NEW chunk (new time interval)

THRESHOLD for severity:
  %util > 95%  AND  await > 100ms → severity=CRITICAL
  %util > 80%  AND  await > 50ms  → severity=ERROR
  %util > 50%                     → severity=WARNING
```

### Metadata Extraction — iostat
```
timestamp:   regex → r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\s+[AP]M)'
device:      field → column 1 of data rows
await_ms:    field → await column (float)
util_pct:    field → %util column (float)
severity:    rule  → based on thresholds above
category:    always "DISK"
```

---

## LOG TYPE 5: sar output (sar -u, sar -q, sar -d, sar -n)

### Line Format
```
HH:MM:SS AM/PM  CPU    %usr  %nice  %sys  %iowait  %steal  %idle
03:10:01 AM     all    94.82  0.00   4.92   0.18    0.00    0.02
```

### Chunk Boundary Rules
```
Each sar row = ONE chunk
Adjacent rows with same metric type grouped into ONE chunk 
if they show a sustained problem (> 3 consecutive rows over threshold)

Threshold rules:
  sar -u: %idle < 5%        → severity=CRITICAL (CPU saturation)
  sar -u: %steal > 20%      → severity=ERROR
  sar -u: %soft > 50%       → severity=ERROR
  sar -q: runq-sz > 2×cores → severity=CRITICAL
  sar -d: await > 100ms     → severity=ERROR
  sar -d: %util > 95%       → severity=CRITICAL
  sar -n: rxkB/s near link speed → severity=ERROR (saturation)
```

### Metadata Extraction — sar
```
timestamp:   regex → r'(\d{2}:\d{2}:\d{2}\s+[AP]M)'
metric_type: from filename/command (sar_cpu, sar_q, sar_d, sar_n)
severity:    rule  → based on thresholds above
category:    sar_cpu/sar_q → CPU | sar_d → DISK | sar_n → NETWORK
```

---

## LOG TYPE 6: vmstat

### Line Format
```
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
48  8      0 262144  32768 524288    0    0   892  8821 48821 182912 92  7  0  1  0
```

### Chunk Boundary Rules
```
Multiple consecutive vmstat rows = ONE chunk (they tell the story together)
Group all rows from a single vmstat collection run = one chunk

Threshold rules:
  si or so > 500 pages/sec → severity=CRITICAL (active swapping)
  wa > 30%                 → severity=ERROR (I/O wait)
  r > 2×CPU_count          → severity=CRITICAL (CPU runqueue)
  cs > 100000/sec          → severity=ERROR (context switch storm)
```

---

## LOG TYPE 7: CRS Logs (ocssd.log, crsd.log)

### Line Format
```
2024-03-21 02:44:18.821 [CSSD(18821)]CRS-1618: Node dbnode2 is not responding
2024-03-21 02:44:21.182 [CSSD(18821)]CRS-1625: Node dbnode2 is being evicted
```

### Chunk Boundary Rules
```
NEW CHUNK starts when:
  1. A new CRS error code (CRS-XXXX) appears
  2. Time gap > 30 seconds between CRS events

SAME CHUNK continues when:
  - CRS messages are sequential escalation of same incident
  - Example: CRS-1618 → CRS-1625 → CRS-1632 = same eviction event

SEVERITY:
  CRS-1618 (not responding) → ERROR
  CRS-1625 (being evicted)  → CRITICAL
  CRS-1632 (eviction done)  → CRITICAL
```

### Metadata Extraction — CRS logs
```
timestamp:   regex → r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)'
crs_code:    regex → r'CRS-(\d{4})'
node_name:   regex → r'Node\s+(\S+)'
category:    always "NETWORK" or "KERNEL" depending on trigger
```

---

## LOG TYPE 8: df (disk space snapshot)

### Line Format
```
Filesystem          Type  1K-blocks     Used  Available Use% Mounted on
/dev/mapper/vg01-arch ext4  209715200 209715200        0  100% /arch
```

### Chunk Boundary Rules
```
df is a SNAPSHOT not a stream — entire df output = ONE chunk
No time window needed — it represents state at collection time

Severity per mount:
  Use% = 100%  → severity=CRITICAL, category=DISK
  Use% >= 95%  → severity=ERROR
  Use% >= 90%  → severity=WARNING

Each filesystem that breaches threshold = separate chunk
  (so /arch full and /u01 95% = two separate chunks)
```

---

## CHUNK METADATA SCHEMA (Final — all log types)

```json
{
  "chunk_id": "uuid-v4",
  "collection_id": "tfa_collection_2024_03_07",
  "hostname": "dbhost01",
  "log_source": "VAR_LOG_MESSAGES",
  "log_file_path": "/var/log/messages",
  "timestamp_start": "2024-03-07T02:44:18+05:30",
  "timestamp_end":   "2024-03-07T02:44:19+05:30",
  "category": "DISK",
  "sub_category": "SCSI",
  "severity": "CRITICAL",
  "ora_code": "ORA-27072",
  "os_pattern": "SCSI_DISK_TIMEOUT",
  "errno": "EIO=5",
  "device": "sdb",
  "process": "kernel",
  "keywords": ["FAILED", "DRIVER_TIMEOUT", "sdb", "Hardware Error", "Stopping disk"],
  "line_count": 6,
  "raw_text": "Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED...",
  "linked_chunks": [],
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_version": "1.0"
}
```

---

## CROSS-LOG LINKING RULES

```
After chunking ALL log types, run a linking pass:

For each chunk C with timestamp T and hostname H:
  Find all OTHER chunks where:
    hostname = H
    AND timestamp within ±60 seconds of T
    AND log_source != C.log_source

  Add their chunk_ids to C.linked_chunks list

This creates the temporal correlation network that enables:
  /var/log/messages chunk at 02:44:18
    linked_to → alert.log chunk at 02:44:19
    linked_to → iostat chunk at 02:44:09
```
