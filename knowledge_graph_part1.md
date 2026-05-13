# Oracle DBA Agent — Knowledge Graph Documentation
## Part 1: Node Types, Edge Types, ORA Code Nodes
## This is the BRAIN of the agent — Temperature 0.0

---

## GRAPH OVERVIEW

```
The Knowledge Graph answers one question:
  "Given what I found in the logs, what is the root cause and fix?"

It is a DIRECTED GRAPH where:
  - Nodes = things that exist (ORA codes, OS errors, fixes, log sources)
  - Edges = relationships between them (caused_by, fixed_by, appears_in)

Query pattern:
  Start at ORA code node
  → follow "caused_by" edges → find OS error pattern nodes
  → match OS pattern against retrieved log chunks
  → follow "fixed_by" edges → get fix commands
  → follow "appears_in" edges → know which log file to look at
```

---

## NODE TYPES (6 types)

```
NODE TYPE 1: ORA_CODE
========================
  Represents an Oracle error code
  Properties:
    - id          (string)  e.g. "ORA-27072"
    - description (string)  e.g. "File I/O error"
    - errno_map   (list)    e.g. ["EIO=5", "EAGAIN=11", "ENOSPC=28"]
    - layer       (string)  "OS_TRIGGERED" | "DB_INTERNAL" | "NETWORK"
    - severity    (string)  "CRITICAL" | "ERROR" | "WARNING"
    - appears_in  (string)  "alert.log" | "trace_file" | "sqlnet.log"

NODE TYPE 2: OS_ERROR_PATTERN
================================
  Represents a specific OS-level error scenario
  Properties:
    - id           (string)  e.g. "SCSI_DISK_TIMEOUT"
    - category     (string)  "CPU" | "MEMORY" | "DISK" | "NETWORK" | "KERNEL"
    - sub_category (string)  e.g. "SCSI" | "MULTIPATH" | "FC_HBA"
    - log_keywords (list)    e.g. ["FAILED", "DRIVER_TIMEOUT", "sdb", "Stopping disk"]
    - log_source   (string)  "/var/log/messages" | "dmesg" | "iostat" | ...
    - severity     (string)  "CRITICAL" | "ERROR" | "WARNING"
    - errno        (string)  e.g. "EIO=5"

NODE TYPE 3: FIX_COMMAND
==========================
  Represents a remediation action
  Properties:
    - id          (string)  e.g. "FIX_MULTIPATH_ENABLE"
    - description (string)  e.g. "Enable device multipathing"
    - commands    (list)    e.g. ["systemctl start multipathd", "multipath -ll"]
    - requires    (string)  "root" | "oracle" | "grid"
    - risk        (string)  "LOW" | "MEDIUM" | "HIGH" (HIGH = needs maintenance window)
    - persistent  (bool)    True if fix survives reboot, False if temporary

NODE TYPE 4: LOG_SOURCE
=========================
  Represents a log file or OS tool output
  Properties:
    - id          (string)  e.g. "VAR_LOG_MESSAGES"
    - path        (string)  e.g. "/var/log/messages"
    - format      (string)  "SYSLOG" | "ORACLE_ALERT" | "CSV" | "PROC"
    - collected_by (string) "AHF" | "MANUAL" | "BOTH"
    - time_format (string)  e.g. "Mon DD HH:MM:SS" | "YYYY-MM-DD HH24:MI:SS"

NODE TYPE 5: DIAGNOSTIC_COMMAND
==================================
  Represents a command DBA runs to confirm the error
  Properties:
    - id          (string)  e.g. "DIAG_MULTIPATH_STATUS"
    - command     (string)  e.g. "multipath -ll"
    - what_to_look (string) e.g. "Look for 'failed' paths or '0:0' active paths"
    - requires    (string)  "root" | "oracle" | "grid"

NODE TYPE 6: ESCALATION_TARGET
================================
  Represents what Oracle error/incident follows if OS error is not fixed
  Properties:
    - id          (string)  e.g. "INSTANCE_CRASH"
    - description (string)  e.g. "Oracle instance terminates abnormally"
    - severity    (string)  "CRITICAL"
    - recovery    (string)  e.g. "Instance auto-restart, crash recovery runs"
```

---

## EDGE TYPES (7 types)

```
EDGE TYPE 1: caused_by
========================
  Direction: ORA_CODE ──caused_by──→ OS_ERROR_PATTERN
  Meaning:   "This ORA code can be triggered by this OS error"
  Properties:
    - probability (float)  0.0–1.0  (how often this cause applies)
    - conditions  (list)   additional conditions that must be true
    - errno       (string) specific Linux errno that links them

EDGE TYPE 2: triggered_by
==========================
  Direction: OS_ERROR_PATTERN ──triggered_by──→ OS_ERROR_PATTERN
  Meaning:   "This OS error is caused by a deeper OS error"
  Example:   SCSI_TIMEOUT ──triggered_by──→ FC_HBA_RESET
  Properties:
    - probability (float)  0.0–1.0
    - time_gap_sec (int)   typical seconds between trigger and effect

EDGE TYPE 3: appears_in
========================
  Direction: OS_ERROR_PATTERN ──appears_in──→ LOG_SOURCE
  Meaning:   "Look in this log file to find evidence of this error"
  Properties:
    - keywords    (list)   exact strings to grep for
    - time_offset (int)    seconds before/after the ORA code timestamp

EDGE TYPE 4: fixed_by
======================
  Direction: OS_ERROR_PATTERN ──fixed_by──→ FIX_COMMAND
  Meaning:   "This fix resolves this OS error pattern"
  Properties:
    - fix_type    (string) "IMMEDIATE" | "PERMANENT" | "WORKAROUND"
    - downtime    (bool)   True if Oracle must be stopped first

EDGE TYPE 5: confirmed_by
==========================
  Direction: OS_ERROR_PATTERN ──confirmed_by──→ DIAGNOSTIC_COMMAND
  Meaning:   "Run this command to confirm the error is this pattern"
  Properties:
    - expected_output (string) what to look for in command output

EDGE TYPE 6: escalates_to
===========================
  Direction: OS_ERROR_PATTERN ──escalates_to──→ ESCALATION_TARGET
  Meaning:   "If not fixed, this OS error leads to this Oracle impact"
  Properties:
    - time_to_escalate (string) e.g. "immediate" | "within 30 seconds" | "gradual"

EDGE TYPE 7: co_occurs_with
============================
  Direction: OS_ERROR_PATTERN ──co_occurs_with──→ OS_ERROR_PATTERN
  Meaning:   "These two OS errors often appear together (same incident)"
  Properties:
    - time_window_sec (int)  typical seconds between co-occurrence
```

---

## ORA CODE NODES (All ORA codes in our dataset)

### ORA-27072 — File I/O Error
```
id:          "ORA-27072"
description: "File I/O error — Oracle syscall returned I/O error from OS"
errno_map:   ["EIO=5"]
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log + trace_file"

caused_by (edges):
  → SCSI_DISK_TIMEOUT       probability=0.40  errno=EIO
  → FC_HBA_RESET            probability=0.25  errno=EIO
  → MULTIPATH_ALL_PATHS_DOWN probability=0.15 errno=EIO
  → IO_QUEUE_TIMEOUT        probability=0.10  errno=EIO
  → ISCSI_SESSION_FAIL      probability=0.05  errno=EIO
  → LVM_DEVICE_FAIL         probability=0.03  errno=EIO
  → SMARTCTL_PENDING_SECTOR probability=0.02  errno=EIO
```

### ORA-15080 — Synchronous I/O Request Failed (ASM)
```
id:          "ORA-15080"
description: "Synchronous I/O request to an ASM disk failed"
errno_map:   ["EIO=5"]
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log + ASM_alert.log"

caused_by:
  → MULTIPATH_ALL_PATHS_DOWN probability=0.45  errno=EIO
  → SCSI_DISK_TIMEOUT        probability=0.25  errno=EIO
  → FC_HBA_RESET             probability=0.20  errno=EIO
  → ISCSI_SESSION_FAIL       probability=0.05  errno=EIO
  → IO_QUEUE_TIMEOUT         probability=0.05  errno=EIO
```

### ORA-15130 / ORA-15041 / ORA-15040 — ASM Diskgroup Issues
```
id:          "ORA-15130"
description: "Diskgroup being dismounted"
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log + ASM_alert.log"

caused_by:
  → MULTIPATH_ALL_PATHS_DOWN probability=0.60
  → ASM_DISK_FULL            probability=0.30
  → SCSI_DISK_TIMEOUT        probability=0.10

id:          "ORA-15041"
description: "Diskgroup space exhausted / I/O error"
caused_by:
  → ASM_DISK_FULL            probability=0.70
  → MULTIPATH_ALL_PATHS_DOWN probability=0.30

id:          "ORA-15040"
description: "Diskgroup incomplete"
caused_by:
  → MULTIPATH_ALL_PATHS_DOWN probability=0.80
  → FC_HBA_RESET             probability=0.20
```

### ORA-27102 — Out of Memory
```
id:          "ORA-27102"
description: "Out of memory — OS refused memory allocation for SGA/PGA"
errno_map:   ["ENOMEM=12", "EINVAL=22", "ENOSPC=28"]
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log"

caused_by:
  → SHMGET_EINVAL            probability=0.35  errno=EINVAL   condition="shmmax too low"
  → DEVSHM_TOO_SMALL         probability=0.30  errno=ENOSPC   condition="/dev/shm full"
  → HUGEPAGES_FREE_ZERO      probability=0.25  errno=ENOMEM   condition="HugePages exhausted"
  → OOM_KILLER_ACTIVE        probability=0.10  errno=ENOMEM   condition="system OOM"
```

### ORA-27125 — Unable to Create Shared Memory Segment
```
id:          "ORA-27125"
description: "Unable to create shared memory segment — memlock failed"
errno_map:   ["EPERM=1", "ENOMEM=12"]
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log"

caused_by:
  → MEMLOCK_ULIMIT_TOO_LOW   probability=0.70  errno=EPERM
  → SHMGET_EINVAL            probability=0.20  errno=EINVAL
  → OOM_KILLER_ACTIVE        probability=0.10  errno=ENOMEM
```

### ORA-27300 / ORA-27301 / ORA-27302 — OS Primitive Failed
```
id:          "ORA-27300"
description: "OS system dependent operation failed"
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log"

caused_by:
  → SEMAPHORE_LIMIT_EXHAUSTED probability=0.30  errno=ENOSPC
  → FD_LIMIT_EXHAUSTED        probability=0.25  errno=EMFILE
  → SELINUX_BLOCKING          probability=0.25  errno=EACCES
  → SHMGET_EINVAL             probability=0.20  errno=EINVAL
```

### ORA-00257 — Archiver Error
```
id:          "ORA-00257"
description: "Archiver error — cannot archive redo log"
errno_map:   ["ENOSPC=28", "EROFS=30"]
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log"

caused_by:
  → FILESYSTEM_ARCH_FULL      probability=0.55  errno=ENOSPC
  → EXT4_JOURNAL_ABORT        probability=0.25  errno=EROFS    condition="/arch remounted RO"
  → NFS_MOUNT_TIMEOUT         probability=0.15  errno=ETIMEDOUT condition="/arch on NFS"
  → LVM_DEVICE_FAIL           probability=0.05  errno=EIO
```

### ORA-19809 / ORA-19504 / ORA-16038 — Archive/Recovery File Errors
```
id: "ORA-19809" description: "Limit exceeded for recovery files"
id: "ORA-19504" description: "Failed to create file — ENOSPC"
id: "ORA-16038" description: "Log cannot be archived"

All caused_by:
  → FILESYSTEM_ARCH_FULL      probability=0.70
  → EXT4_JOURNAL_ABORT        probability=0.20
  → NFS_MOUNT_TIMEOUT         probability=0.10
```

### ORA-00603 — Server Session Terminated by Fatal Error
```
id:          "ORA-00603"
description: "Oracle server session terminated by fatal error (often OS kill)"
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log"

caused_by:
  → OOM_KILLER_ACTIVE         probability=0.60
  → CGROUP_OOM_KILL           probability=0.30
  → KERNEL_PANIC              probability=0.10
```

### ORA-00603 / ORA-07445 — Core Dump / Signal
```
id:          "ORA-07445"
description: "Exception encountered — core dump"
layer:       "OS_TRIGGERED + DB_INTERNAL"
severity:    "CRITICAL"
appears_in:  "alert.log + trace_file"

caused_by:
  → OOM_KILLER_ACTIVE         probability=0.30
  → EDAC_UE_MEMORY_ERROR      probability=0.25  condition="memory bit flip corrupts Oracle heap"
  → KERNEL_NULL_PTR_DEREF     probability=0.20  condition="HBA driver crash"
  → HUGEPAGES_NONE            probability=0.15  condition="SGA using regular pages, fragmentation"
  → THP_LATENCY_STALL         probability=0.10
```

### ORA-03113 — End of File on Communication Channel
```
id:          "ORA-03113"
description: "End-of-file on communication channel — TCP connection dropped"
layer:       "NETWORK"
severity:    "ERROR"
appears_in:  "sqlnet.log + alert.log"

caused_by:
  → BONDING_FAILOVER_EVENT    probability=0.30
  → BOTH_NICS_DOWN            probability=0.20
  → NF_CONNTRACK_FULL         probability=0.20
  → TCP_KEEPALIVE_FIREWALL    probability=0.20  condition="idle connection dropped by firewall"
  → NFS_MOUNT_TIMEOUT         probability=0.10
```

### ORA-12541 / ORA-12170 — TNS Errors
```
id:          "ORA-12541"
description: "TNS: no listener"
id:          "ORA-12170"
description: "TNS: Connect timeout occurred"

caused_by:
  → IPTABLES_BLOCKING_1521    probability=0.50
  → NF_CONNTRACK_FULL         probability=0.25
  → BONDING_FAILOVER_EVENT    probability=0.15
  → BOTH_NICS_DOWN            probability=0.10
```

### ORA-12519 / ORA-12520 — No Handler Available
```
id:          "ORA-12519"
description: "TNS: no appropriate service handler found"

caused_by:
  → SOCKET_EXHAUSTION         probability=0.60
  → FD_LIMIT_EXHAUSTED        probability=0.30
  → NPROC_LIMIT_HIT           probability=0.10
```

### ORA-29740 — Evicted by Member
```
id:          "ORA-29740"
description: "Evicted by member — RAC node was evicted from cluster"
layer:       "OS_TRIGGERED"
severity:    "CRITICAL"
appears_in:  "alert.log + ocssd.log"

caused_by:
  → NTP_TIME_JUMP             probability=0.30
  → BONDING_FAILOVER_EVENT    probability=0.20
  → IB_LINK_DEGRADED          probability=0.20
  → UDP_BUFFER_OVERFLOW        probability=0.15
  → NIC_RX_DROPS_HIGH         probability=0.15
```

### ORA-27054 — NFS Mount Error
```
id:          "ORA-27054"
description: "NFS file system not mounted with correct options"

caused_by:
  → NFS_MOUNT_TIMEOUT         probability=0.80
  → IPTABLES_BLOCKING_1521    probability=0.20  condition="NFS port blocked"
```

### ORA-04031 — Unable to Allocate Shared Memory
```
id:          "ORA-04031"
description: "Unable to allocate bytes of shared memory (shared pool)"
layer:       "OS_TRIGGERED (indirect)"
severity:    "ERROR"
appears_in:  "alert.log"

caused_by:
  → MEMORY_SWAP_STORM         probability=0.40  condition="SGA pages swapped out"
  → HUGEPAGES_FREE_ZERO       probability=0.35  condition="SGA using regular pages, fragments"
  → ORADISM_MEMLOCK_FAIL      probability=0.25  condition="SGA not locked, pages swapped"
```

### ORA-00353 / ORA-00312 — Redo Log Corruption
```
id:          "ORA-00353"
description: "Log corruption — redo log block check failed"

caused_by:
  → SCSI_DISK_TIMEOUT         probability=0.35
  → FC_HBA_RESET              probability=0.30
  → IO_QUEUE_TIMEOUT          probability=0.20
  → DM_MULTIPATH_FAIL         probability=0.15
```

### ORA-00470 — LGWR Process Terminated
```
id:          "ORA-00470"
description: "LGWR process terminated with error"

caused_by:
  → DM_MULTIPATH_FAIL         probability=0.50
  → FILESYSTEM_REDO_FULL      probability=0.30
  → SCSI_DISK_TIMEOUT         probability=0.20
```
