# Gap E — False Positive Catalog
# Gap F — AWR/ASH Wait Event to OS Root Cause Mapping
## Temperature: 0.0

---

# PART 1: FALSE POSITIVE CATALOG (Gap E)
## Messages That Look Like Errors But Are NOT

---

## PURPOSE

```
Without this catalog, the agent will fire alerts on normal Oracle messages.
Every entry here = "DO NOT flag as an error"

Rule: If a log line matches an entry in this catalog,
      suppress it — do not include in diagnostic report.
```

---

## SECTION 1: Normal Oracle alert.log Messages

```
PATTERN: "Thread \d+ advanced to log sequence \d+"
EXAMPLE: Thread 1 advanced to log sequence 18821 (LGWR switch)
MEANING: Normal redo log switch — happens every few minutes
ACTION:  SUPPRESS — not an error

PATTERN: "Checkpoint not complete"
EXAMPLE: Checkpoint not complete
MEANING: DBWn cannot checkpoint fast enough — normal under heavy load
ACTION:  SUPPRESS if rare. Alert only if sustained > 10 occurrences in 1 hour.

PATTERN: "ARC\d+: Evaluating archive log \d+ of thread \d+"
EXAMPLE: ARC0: Evaluating archive log 2 of thread 1, sequence# 4821
MEANING: Archiver evaluating which logs to archive — normal work
ACTION:  SUPPRESS

PATTERN: "LGWR: STARTING LGWR ARCHIVAL"
EXAMPLE: LGWR: STARTING LGWR ARCHIVAL
MEANING: Log writer starting archival process — normal after log switch
ACTION:  SUPPRESS

PATTERN: "Completed checkpoint up to RBA"
EXAMPLE: Completed checkpoint up to RBA [0x12e5.0x3.0x10]
MEANING: Checkpoint completed successfully — normal
ACTION:  SUPPRESS

PATTERN: "db_recovery_file_dest_size of \d+ GB is \d+% used"
EXAMPLE: db_recovery_file_dest_size of 50 GB is 75% used
MEANING: FRA (Fast Recovery Area) usage warning — monitor but not error
ACTION:  WARNING only if >= 90%

PATTERN: "SMON: enabling cache recovery"
EXAMPLE: SMON: enabling cache recovery
MEANING: Normal startup sequence — SMON beginning recovery phase
ACTION:  SUPPRESS

PATTERN: "SMON: enabling tx recovery"
EXAMPLE: SMON: enabling tx recovery
MEANING: Normal startup — transaction recovery beginning
ACTION:  SUPPRESS

PATTERN: "Reconfiguration started \(old inc \d+, new inc \d+\)"
EXAMPLE: Reconfiguration started (old inc 1, new inc 2)
MEANING: RAC reconfiguration — normal when nodes join/leave
ACTION:  SUPPRESS unless followed by CRS-1618 or ORA-29740

PATTERN: "Beginning log switch checkpoint"
EXAMPLE: Beginning log switch checkpoint
MEANING: Log switch in progress — normal
ACTION:  SUPPRESS

PATTERN: "ARC\d+: Archive log written"
EXAMPLE: ARC2: Archive log written to /arch/1_18821_1234567890.arc
MEANING: Successful archival — normal
ACTION:  SUPPRESS

PATTERN: "alter database open"
EXAMPLE: alter database open
MEANING: DBA opened the database — normal startup step
ACTION:  SUPPRESS

PATTERN: "Database mounted."
EXAMPLE: Database mounted.
MEANING: Normal startup step
ACTION:  SUPPRESS

PATTERN: "db_recovery_file_dest_size of \d+ GB is \d+% used"
EXAMPLE: db_recovery_file_dest_size of 200 GB is 85% used
MEANING: Warning level — not critical until 95%
THRESHOLD: Alert at 95%, Critical at 100%

PATTERN: "Starting ORACLE instance \(normal\)"
EXAMPLE: Starting ORACLE instance (normal)
MEANING: Normal startup
ACTION:  SUPPRESS (but log the timestamp for uptime tracking)

PATTERN: "Shutting down instance \(normal\)"
EXAMPLE: Shutting down instance (normal)
MEANING: Planned shutdown by DBA — not an error
ACTION:  SUPPRESS (but log for audit purposes)
```

---

## SECTION 2: Normal /var/log/messages Entries

```
PATTERN: "kernel: EXT4-fs.*: re-mounted.*Opts"
EXAMPLE: kernel: EXT4-fs (/dev/sda1): re-mounted. Opts: errors=remount-ro
MEANING: Filesystem remounted (often after mount option change) — normal
ACTION:  SUPPRESS unless read-only remount → that IS an error

PATTERN: "multipathd.*add missing path"
EXAMPLE: multipathd: sdb: add missing path
MEANING: Multipath RECOVERING a path — this is GOOD news, not an error
ACTION:  SUPPRESS — only alert on path failure, not path recovery

PATTERN: "multipathd.*bind_paths"
EXAMPLE: multipathd: sdb: bind_paths
MEANING: Multipath path binding — normal operation
ACTION:  SUPPRESS

PATTERN: "chronyd: Selected source"
EXAMPLE: chronyd: Selected source 192.168.1.1 (ntp.example.com)
MEANING: NTP server selection — normal
ACTION:  SUPPRESS

PATTERN: "kernel: SCSI device .* \d+ 512-byte"
EXAMPLE: kernel: SCSI device sdb: 976773168 512-byte hdwr sectors (500107 MB)
MEANING: Disk detected/identified — normal at boot or device add
ACTION:  SUPPRESS

PATTERN: "kernel: sd.*: Attached SCSI disk"
EXAMPLE: kernel: sd 2:0:0:0: Attached SCSI disk sdb
MEANING: Disk attached — normal at boot
ACTION:  SUPPRESS

PATTERN: "kernel: device .* entered 38400 sector"
EXAMPLE: kernel: device vda: entered 38400 sector size mode
MEANING: VM disk sector mode — normal for virtual machines
ACTION:  SUPPRESS

PATTERN: "kernel: NET: Registered protocol family"
EXAMPLE: kernel: NET: Registered protocol family 10
MEANING: Network stack initialization — normal at boot
ACTION:  SUPPRESS

PATTERN: "oracle-ohasd: Starting Oracle High Availability Services"
EXAMPLE: oracle-ohasd: Starting Oracle High Availability Services
MEANING: CRS starting — normal
ACTION:  SUPPRESS

PATTERN: "qla2xxx.*Link Up -- F_Port"
EXAMPLE: qla2xxx [0000:04:00.0]-2100: Link Up -- F_Port
MEANING: FC HBA link recovered — GOOD news after a link-down event
ACTION:  SUPPRESS (recovery message) — but log timestamp for SLA calculation
```

---

## SECTION 3: Normal CRS Log Entries

```
PATTERN: "CRS-1012: The OCR service started on node"
EXAMPLE: CRS-1012: The OCR service started on node dbhost01
MEANING: Normal CRS startup
ACTION:  SUPPRESS

PATTERN: "CRS-6011: The resource .* is online"
EXAMPLE: CRS-6011: The resource ora.LISTENER.lsnr is online on node dbhost01
MEANING: Resource came online — normal
ACTION:  SUPPRESS

PATTERN: "CRS-2765: Resource .* has been modified"
EXAMPLE: CRS-2765: Resource ora.dbhost01.vip has been modified
MEANING: Normal VIP or resource update
ACTION:  SUPPRESS

PATTERN: "CRS-1016: The disk timeout value is"
EXAMPLE: CRS-1016: The disk timeout value is 200. Sending I/O to voting disk.
MEANING: Normal CSS disk heartbeat
ACTION:  SUPPRESS

PATTERN: "CRS-2676: Start of .* on .* succeeded"
EXAMPLE: CRS-2676: Start of 'ora.prod.db' on 'dbhost01' succeeded
MEANING: Resource started successfully — normal
ACTION:  SUPPRESS
```

---

## SECTION 4: Threshold-Based False Positive Rules

```
RULE 1: "Checkpoint not complete" frequency
  1-5 per hour:  NORMAL — suppress
  6-20 per hour: WARNING — mention in report (DBWn I/O speed issue)
  > 20 per hour: ERROR — flag (redo logs too small or I/O too slow)

RULE 2: FRA usage
  < 90%:  NORMAL
  90-95%: WARNING
  > 95%:  CRITICAL (will cause ORA-00257 soon)

RULE 3: "db file scattered read" wait event
  avg < 10ms:   NORMAL
  avg 10-50ms:  WARNING (disk slowing)
  avg > 50ms:   ERROR (disk problem)

RULE 4: "log file sync" wait event
  avg < 10ms:   NORMAL (good redo I/O)
  avg 10-30ms:  WARNING
  avg > 30ms:   ERROR (redo disk latency)
```

---

# PART 2: AWR/ASH WAIT EVENT CORRELATION (Gap F)
## OS Root Cause → AWR Wait Event Mapping

---

## PURPOSE

```
When there is NO ORA code, the agent uses AWR wait events to diagnose.
This mapping connects: AWR wait event → probable OS root cause

A DBA asks: "No ORA code, but DB is slow. What's wrong?"
Agent checks AWR, finds "gc buffer busy acquire" high wait.
Agent maps: gc buffer busy acquire → RAC interconnect degraded
Agent checks: IB link stats, NIC drops, NTP sync
Agent reports: "InterConnect issue — check ib0 bandwidth and NTP"
```

---

## WAIT EVENT TO OS CAUSE MAPPING

### CPU-Related Waits

```
WAIT EVENT: "CPU time" dominates top 5 (> 60% of DB time)
  OS ROOT CAUSE:
    → CPU_RUNQUEUE_SATURATION (run queue > 2× CPU count)
    → CPU_STEAL_TIME (%steal > 20%)
    → SOFT_LOCKUP (one CPU stuck, others overloaded)
  DIAGNOSTIC:
    sar -u 1 10           (check %idle, %steal)
    sar -q 1 10           (check runq-sz)
    uptime                (check load average)
  ORA CODE: Does Not Exist (performance only)

WAIT EVENT: "latch: shared pool"
WAIT EVENT: "latch free"
  OS ROOT CAUSE:
    → MEMORY_SWAP_STORM (SGA pages swapping)
    → HUGEPAGES_FREE_ZERO (SGA fragmented without huge pages)
    → THP_LATENCY_STALL (THP defrag stalling Oracle)
  DIAGNOSTIC:
    grep HugePages /proc/meminfo
    vmstat 1 5 (check si/so columns)
    cat /sys/kernel/mm/transparent_hugepage/enabled
  ORA CODE: ORA-04031 (if severe enough)
```

### Disk I/O Waits

```
WAIT EVENT: "db file sequential read"    (single block read — index lookup)
  HIGH AVG WAIT > 50ms:
    OS ROOT CAUSE:
      → IOSTAT_HIGH_AWAIT (disk await > 50ms)
      → SCSI_DISK_TIMEOUT (intermittent)
      → IO_QUEUE_TIMEOUT (disk queue backing up)
    DIAGNOSTIC:
      iostat -xmt 1 10 | grep -E "sdb|await"
      sar -d 1 10 (check await column)
  ORA CODE: None directly (but may escalate to ORA-27072 if severe)

WAIT EVENT: "db file scattered read"    (multiblock read — FTS)
  HIGH AVG WAIT > 50ms:
    OS ROOT CAUSE: Same as above (disk latency)

WAIT EVENT: "log file sync"             (commit wait — LGWR latency)
  HIGH AVG WAIT > 10ms:
    OS ROOT CAUSE:
      → IOSTAT_HIGH_AWAIT on redo log disk
      → IO_QUEUE_TIMEOUT on redo log volume
      → MULTIPATH_PATH_FAIL (redo on multipath)
    DIAGNOSTIC:
      iostat -xmt 1 10 (identify redo log device)
      multipath -ll (check redo log device paths)
  ORA CODE: None directly (but severe → ORA-00353 log corruption)

WAIT EVENT: "direct path read"          (parallel query, temp I/O)
  HIGH AVG WAIT > 100ms:
    OS ROOT CAUSE:
      → Temp tablespace disk saturated
      → IOSTAT_FULL_UTIL on temp disk
    DIAGNOSTIC:
      iostat -xmt 1 5 (find saturated disk)
      df -h (check temp space available)

WAIT EVENT: "cell smart table scan"     (Exadata only)
  HIGH AVG WAIT > 200ms:
    OS ROOT CAUSE:
      → EXADATA IORM throttling
      → Cell disk failure (cellcli shows failed disk)
      → InfiniBand degraded
    DIAGNOSTIC:
      cellcli -e list celldisk detail
      cellcli -e list alerthistory where severity='critical'
      ibstat (check link speed and errors)
```

### Network/RAC Waits

```
WAIT EVENT: "gc buffer busy acquire"    (RAC — waiting for remote block)
WAIT EVENT: "gc cr request"            (RAC — cross-node block request)
  HIGH AVG WAIT > 50ms:
    OS ROOT CAUSE:
      → IB_LINK_DEGRADED (InfiniBand speed degraded)
      → NIC_RX_DROPS_HIGH (packet drops on interconnect)
      → NTP_TIME_JUMP (clock skew affecting RAC timing)
      → UDP_BUFFER_OVERFLOW (interconnect packets dropped)
    DIAGNOSTIC:
      ibstat | grep -i 'speed\|error'
      ip -s link show bond0 (check rx errors/drops)
      chronyc tracking
      netstat -su | grep 'errors\|overflow'
  ORA CODE: None directly (performance only)

WAIT EVENT: "global enqueue"
WAIT EVENT: "DFS lock handle"
  HIGH COUNT:
    OS ROOT CAUSE:
      → Network latency between RAC nodes
      → IB_LINK_DEGRADED
    DIAGNOSTIC: Same as gc buffer busy above

WAIT EVENT: "SQL*Net message from client"   (idle wait — client think time)
  UNEXPECTEDLY HIGH:
    OS ROOT CAUSE:
      → NF_CONNTRACK_FULL (packets being dropped)
      → TCP_KEEPALIVE_FIREWALL (firewall dropping idle connections)
    DIAGNOSTIC:
      sysctl net.nf_conntrack_max
      cat /proc/sys/net/netfilter/nf_conntrack_count
      netstat -an | grep -c ESTABLISHED
```

### Memory Waits

```
WAIT EVENT: "library cache lock"
WAIT EVENT: "library cache pin"
WAIT EVENT: "row cache lock"
  UNEXPECTED HIGH:
    OS ROOT CAUSE:
      → MEMORY_SWAP_STORM (library cache pages swapped out)
      → HUGEPAGES_FREE_ZERO (SGA not using huge pages)
    DIAGNOSTIC:
      vmstat 1 5 (check si/so)
      grep HugePages_Free /proc/meminfo
  ORA CODE: ORA-04031 (if escalates)

WAIT EVENT: "free buffer waits"
WAIT EVENT: "write complete waits"
  HIGH COUNT:
    OS ROOT CAUSE:
      → IOSTAT_HIGH_AWAIT (DBWn cannot flush buffers fast enough)
      → SCSI_DISK_TIMEOUT (intermittent disk issues)
    DIAGNOSTIC:
      iostat -xmt 1 10 (check DBWn target disks)
```

---

## COMPLETE MAPPING TABLE (Quick Reference)

| AWR Wait Event | OS Root Cause | Diagnostic Command |
|---|---|---|
| CPU time dominates | CPU_RUNQUEUE / CPU_STEAL | sar -u, sar -q |
| db file sequential read > 50ms | SCSI_DISK_TIMEOUT / IO_QUEUE | iostat -xmt |
| log file sync > 10ms | Redo disk latency | iostat on redo device |
| gc buffer busy acquire > 50ms | IB_LINK_DEGRADED / NIC_DROPS | ibstat, ip -s link |
| gc cr request > 50ms | RAC interconnect | Same as above |
| latch: shared pool | MEMORY_SWAP / HUGEPAGES=0 | vmstat, /proc/meminfo |
| library cache lock | MEMORY_SWAP | vmstat si/so |
| free buffer waits | IOSTAT_HIGH_AWAIT | iostat on data disks |
| cell smart table scan | EXADATA IORM / Cell disk | cellcli alerthistory |
| SQL*Net from client spikes | NF_CONNTRACK_FULL | sysctl nf_conntrack |
| direct path read > 100ms | Temp disk saturated | iostat on temp disk |
| enq: CF - contention | Controlfile on slow disk | iostat on cf disk |
