# Gap A — Multi-Error Cascade Sequences
## 7 Real Oracle Incident Cascades
## Temperature: 0.0 — These are the patterns that make the agent smart

---

## HOW CASCADES ARE USED BY THE AGENT

```
Single error detection (what we had before):
  Agent sees: ORA-27072 → says "disk issue, check multipath"

Cascade detection (what we now add):
  Agent sees: ORA-27072 + ORA-00353 + ORA-00470 + ORA-00603 within 5 seconds
  Agent says: "This is a DISK FAILURE CASCADE.
               Root cause = FC_HBA_RESET (at 02:44:16, 2 seconds before Oracle impact)
               ORA-00353/470/603 are ALL consequences of the same root cause.
               Fix: restore multipath paths, check HBA firmware."

The cascade pattern = ONE root cause → multiple ORA codes in sequence
```

---

## CASCADE 1: DISK FAILURE CHAIN (Most Common in Production)

### Trigger: FC HBA Reset or SCSI Timeout

```
TIMELINE:
  02:44:16  /var/log/messages  → FC HBA reset (root cause)
  02:44:18  /var/log/messages  → SCSI timeout on sdb
  02:44:19  alert.log          → ORA-27072 (1st Oracle signal)
  02:44:19  alert.log          → ORA-00353 (2nd Oracle signal)
  02:44:20  alert.log          → ORA-00470 LGWR terminated (3rd)
  02:44:21  alert.log          → ORA-00603 server terminated (4th)
  02:44:22  alert.log          → Instance crash
```

**Full Log Evidence:**
```
# /var/log/messages (ROOT CAUSE — first event)
Mar 07 02:44:16 dbhost01 kernel: qla2xxx [0000:04:00.0]-8006:0: LOGO nexus reestablished
Mar 07 02:44:16 dbhost01 kernel: qla2xxx [0000:04:00.0]-8001:0: Adapter aborted all I/O
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_TIMEOUT
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] Sense Key: Hardware Error [current]
Mar 07 02:44:19 dbhost01 kernel: blk_update_request: I/O error, dev sdb, sector 9175826432
Mar 07 02:44:19 dbhost01 kernel: Buffer I/O error on dev sdb, logical block 1146978304
Mar 07 02:44:19 dbhost01 kernel: sd 2:0:0:0: [sdb] Stopping disk

# alert.log (CONSEQUENCES — all caused by root above)
Wed Mar 07 02:44:19 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_lgwr_18821.trc:
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
Additional information: 4

Wed Mar 07 02:44:19 2024
ORA-00353: log corruption near block 18821 change 4821821 time 03/07/2024 02:44:18
ORA-00312: online log 2 thread 1: '/u01/oradata/PROD/redo02.log'

Wed Mar 07 02:44:20 2024
ORA-00470: LGWR process terminated with error
ORA-00312: online log 2 thread 1: '/u01/oradata/PROD/redo02.log'

Wed Mar 07 02:44:21 2024
ORA-00603: ORACLE server session terminated by fatal error

Wed Mar 07 02:44:22 2024
LGWR: terminating instance due to error 472
Instance terminated by LGWR, pid = 18821
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_DISK_FAIL_01
root_cause:     FC_HBA_RESET
root_time:      02:44:16
root_source:    /var/log/messages
ora_codes:      [ORA-27072, ORA-00353, ORA-00470, ORA-00603]
first_ora_time: 02:44:19
time_to_crash:  6 seconds from root cause
fix:            FIX_ENABLE_MULTIPATH + FIX_CHECK_HBA_FIRMWARE
```

---

## CASCADE 2: MEMORY PRESSURE → OOM → RESTART → FRAGMENTATION

### Trigger: Swap storm builds up over minutes, then OOM kills oracle

```
TIMELINE:
  03:05:00  vmstat         → si/so > 500 pages/sec (gradual)
  03:08:00  /proc/meminfo  → HugePages_Free: 0
  03:14:18  /var/log/msg   → OOM killer invoked (root cause peak)
  03:14:18  /var/log/msg   → oracle process killed
  03:14:19  alert.log      → ORA-00603
  03:14:45  alert.log      → CRS restarts DB
  03:15:02  alert.log      → ORA-04031 on restart
```

**Full Log Evidence:**
```
# vmstat 1 (collected over time — gradual build)
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa
48  8  524288  65536  32768 262144  621  589   892  8821 48821 182912 89  8  0  3  0
52  9  786432  32768  16384 196608  821  798  1021  9821 52821 192912 91  7  0  2  0
61 12 1048576   8192   8192 131072 1021  982  1182 11821 58821 212912 93  6  0  1  0

# /proc/meminfo at peak
MemTotal:       131072000 kB
MemFree:            32768 kB     ← 32MB free (critical)
HugePages_Total:    49152
HugePages_Free:         0        ← ZERO free huge pages

# /var/log/messages (root cause event)
Mar 07 03:14:18 dbhost01 kernel: oracle invoked oom-killer: gfp_mask=0x280da, order=0, oom_score_adj=0
Mar 07 03:14:18 dbhost01 kernel: oracle cpuset=/ mems_allowed=0
Mar 07 03:14:18 dbhost01 kernel: [ pid ]   uid  tgid total_vm      rss nr_ptes swapents oom_score_adj name
Mar 07 03:14:18 dbhost01 kernel: [18821] 54321 18821  9437184  9200182     182    182821             0 oracle
Mar 07 03:14:18 dbhost01 kernel: Out of memory: Kill process 18821 (oracle) score 899 or sacrifice child
Mar 07 03:14:18 dbhost01 kernel: Killed process 18821 (oracle) total-vm:37748736kB, anon-rss:36800728kB

# alert.log (consequences)
Thu Mar 07 03:14:19 2024
ORA-00603: ORACLE server session terminated by fatal error
ORA-00600: internal error code, arguments: [LibraryCacheNotEmpty], [], []
PMON: terminating instance due to error 603

# CRS restart (45 seconds later)
Thu Mar 07 03:14:45 2024
Starting ORACLE instance (normal)
Shared Memory Size=(4026531840) --- 4GB SGA

# First query after restart — shared pool fragmented
Thu Mar 07 03:15:02 2024
ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","SELECT * FROM HR.EMPLOYEES...","sga heap(1,0)","KKSSP^2")
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_MEMORY_OOM_01
root_cause:     MEMORY_SWAP_STORM → OOM_KILLER_ACTIVE
root_time:      03:05:00 (gradual), peak 03:14:18
ora_codes:      [ORA-00603, ORA-04031]
buildup_time:   ~9 minutes of swap storm before OOM
fix:            FIX_SET_HUGEPAGES + FIX_SET_SWAPPINESS + FIX_DISABLE_THP
```

---

## CASCADE 3: NETWORK FAILURE → RAC NODE EVICTION → CLIENT DISCONNECT

### Trigger: Primary NIC failure on RAC node

```
TIMELINE:
  02:44:15  /var/log/msg  → bonding failover (root cause)
  02:44:17  ocssd.log     → CRS-1618 node not responding
  02:44:19  ocssd.log     → CRS-1625 node being evicted
  02:44:20  alert.log     → ORA-29740 evicted
  02:44:20  sqlnet.log    → ORA-03113 client connections drop
  02:44:30  alert.log     → Failover to surviving node begins
  02:44:50  alert.log     → Surviving node opens for connections
```

**Full Log Evidence:**
```
# /var/log/messages (ROOT CAUSE)
Mar 07 02:44:15 dbhost02 kernel: bonding: bond0: link status definitely down for interface eth0, disabling it
Mar 07 02:44:15 dbhost02 kernel: bonding: bond0: making interface eth1 the new active one
Mar 07 02:44:16 dbhost02 kernel: bonding: bond0: Warning: No active slaves. Using last resort
# ← BOTH eth0 and eth1 are down — no active NIC

# ocssd.log on surviving node (dbhost01)
2024-03-07 02:44:17.821 [CSSD(18821)]CRS-1618: Node dbhost02 is not responding to heartbeat
2024-03-07 02:44:19.182 [CSSD(18821)]CRS-1625: Node dbhost02 is being evicted; details at
        (:CSSNM00018:) in /u01/grid/log/dbhost01/cssd/ocssd.log
2024-03-07 02:44:21.821 [CSSD(18821)]CRS-1632: Server dbhost02 is being stopped

# alert.log on dbhost02 (evicted node)
Thu Mar 07 02:44:20 2024
ORA-29740: evicted by member 0, group incarnation 7

# sqlnet.log on clients
***********************************************************************
Fatal NI connect error 12537
TNS-12537: TNS:connection closed
TNS-12560: TNS:protocol adapter error
Time: 07-MAR-2024 02:44:20

# alert.log on dbhost01 (surviving node, failover begins)
Thu Mar 07 02:44:30 2024
NOTE: initiating EXCLUSIVE recovery of thread 2 (of 2-thread cluster)
Thread 2 recovery: started
ARC2: Evaluating archive log 2 of thread 2, sequence# 4821
Thread 2 recovery: 100% complete
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_NETWORK_RAC_01
root_cause:     BOTH_NICS_DOWN
root_time:      02:44:15
ora_codes:      [ORA-29740, ORA-03113]
client_impact:  All sessions on dbhost02 dropped
time_to_failover: 35 seconds from root cause
fix:            FIX_CHECK_NIC_REDUNDANCY + FIX_MTU_JUMBO (for interconnect)
```

---

## CASCADE 4: ARCHIVE DESTINATION FULL → DB SUSPENDED

### Trigger: /arch filesystem hits 100%

```
TIMELINE:
  02:44:00  df              → /arch at 98% (warning)
  02:44:10  alert.log       → ORA-00257 first occurrence
  02:44:10  alert.log       → ORA-16038 archival stopped
  02:44:11  alert.log       → Database suspended (all writes stop)
  02:44:11  app servers     → ORA-00257 propagates to applications
  02:44:45  alert.log       → ORA-04031 processes timing out
  03:14:18  DBA action      → free space or add archive destination
```

**Full Log Evidence:**
```
# df output at 02:44:00
Filesystem             Size  Used Avail Use% Mounted on
/dev/mapper/vg01-arch  200G  196G     0 100% /arch

# alert.log
Thu Mar 07 02:44:10 2024
ARC1: Archival stopped, error occurred. Will continue retrying
ORA-16038: log 2 sequence# 18821 cannot be archived
ORA-19809: limit exceeded for recovery files
ORA-00257: archiver error. Connect internal only, until freed.

Thu Mar 07 02:44:10 2024
LGWR: Waiting for archivelog writer processes to archive redo logs
Beginning log switch checkpoint
LGWR: STARTING LGWR ARCHIVAL

# Database suspended — ALL transactions wait
Thu Mar 07 02:44:11 2024
WARNING: DB is fully suspended. Instance not available.

# 35 seconds later — processes timing out in shared pool
Thu Mar 07 02:44:45 2024
ORA-04031: unable to allocate 16384 bytes of shared memory
("shared pool","unknown object","sga heap(1,0)","free memory")
# ← applications waiting in shared pool → shared pool fragmented

# Applications show (propagated error):
ORA-00257: archiver error. Connect internal only, until freed.
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_ARCH_FULL_01
root_cause:     FILESYSTEM_ARCH_FULL
root_time:      02:44:00 (warning level)
ora_codes:      [ORA-00257, ORA-16038, ORA-19809, ORA-04031]
business_impact: ALL transactions suspended until space freed
fix:            FIX_CLEANUP_ARCH_LOGS (immediate) + FIX_ADD_ARCH_SPACE (permanent)
```

---

## CASCADE 5: ASM MULTIPATH DOWN → DISKGROUP DISMOUNT → INSTANCE CRASH

### Trigger: All multipath paths to ASM disk fail

```
TIMELINE:
  02:44:14  /var/log/msg   → FC HBA reset (root cause)
  02:44:16  /var/log/msg   → multipathd: remaining active paths: 0
  02:44:17  ASM alert.log  → ORA-15080 ASM I/O failed
  02:44:18  ASM alert.log  → ORA-15130 diskgroup dismounted
  02:44:18  DB alert.log   → ORA-15080 (DB sees ASM failure)
  02:44:19  DB alert.log   → ORA-00603 DBWR terminated
  02:44:20  DB alert.log   → Instance crash
```

**Full Log Evidence:**
```
# /var/log/messages
Mar 07 02:44:14 dbhost01 kernel: qla2xxx: Adapter aborted all outstanding I/O
Mar 07 02:44:16 dbhost01 multipathd: mpatha: remaining active paths: 0
Mar 07 02:44:16 dbhost01 multipathd: mpatha: Fail all paths
Mar 07 02:44:16 dbhost01 kernel: device-mapper: multipath: Failing path 8:32

# ASM alert.log (+grid/diag/asm/+asm/+ASM/trace/alert_+ASM.log)
Thu Mar 07 02:44:17 2024
ORA-15080: synchronous I/O request to a disk failed
ORA-15081: failed to submit an I/O operation to a disk
NOTE: initiating force dismount of group DATA with 821 exts free...

Thu Mar 07 02:44:18 2024
ORA-15130: diskgroup "DATA" is being dismounted
NOTE: LGWR offlining disk DATA_0000 in group 1 (DATA)
NOTE: stopping instance recovery for diskgroup DATA

# DB alert.log (consequence)
Thu Mar 07 02:44:18 2024
ORA-15080: synchronous I/O request to a disk failed
ORA-15081: failed to submit an I/O operation to a disk

Thu Mar 07 02:44:19 2024
ORA-00603: ORACLE server session terminated by fatal error
DBWR: terminating instance due to error 15080

Thu Mar 07 02:44:20 2024
Instance terminated by DBWR, pid = 18821
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_ASM_MULTIPATH_01
root_cause:     FC_HBA_RESET → MULTIPATH_ALL_PATHS_DOWN
root_time:      02:44:14
ora_codes:      [ORA-15080, ORA-15081, ORA-15130, ORA-00603]
time_to_crash:  6 seconds from root cause
fix:            FIX_RESTORE_MULTIPATH_PATHS + FIX_ENABLE_MULTIPATH
```

---

## CASCADE 6: CGROUP KILLS CRS → CRS STACK DEATH → DB ORPHANED

### Trigger: Systemd cgroup memory limit kills ohasd

```
TIMELINE:
  03:14:18  /var/log/msg   → systemd OOM kills oracle-ohasd (root cause)
  03:14:18  crsd.log       → CRS resources going offline
  03:14:19  ocssd.log      → CSS daemon stopping
  03:14:20  alert.log      → DB instance loses CRS contact
  03:14:21  alert.log      → ORA-29701 unable to connect to Cluster Mgr
  03:14:22  alert.log      → Instance shutdown (no CRS = no RAC)
  03:14:45  /var/log/msg   → ohasd restart attempt fails (loop)
```

**Full Log Evidence:**
```
# /var/log/messages
Mar 07 03:14:18 dbhost01 systemd: oracle-ohasd.service: A process of this unit has been
        killed by the OOM killer.
Mar 07 03:14:18 dbhost01 systemd: oracle-ohasd.service: Failed with result 'oom-kill'.
Mar 07 03:14:18 dbhost01 systemd: oracle-ohasd.service: Scheduled restart job, restart counter is at 1.

# crsd.log
2024-03-07 03:14:18.821 [CRSD(18821)]CRS-2765: Resource 'ora.LISTENER.lsnr' has been modified.
2024-03-07 03:14:18.822 [CRSD(18821)]CRS-5011: All resources are offline, shutting down

# ocssd.log
2024-03-07 03:14:19.182 [CSSD(18821)]CRS-1656: The CSS daemon is terminating due to a fatal error

# alert.log on DB
Thu Mar 07 03:14:21 2024
ORA-29701: unable to connect to Cluster Manager

Thu Mar 07 03:14:22 2024
NOTE: LGWR: initiating node eviction of nodes (0) in incarnation 7
Instance shutdown due to CRS failure

# ohasd restart loop
Mar 07 03:14:45 dbhost01 systemd: oracle-ohasd.service: Start request repeated too quickly.
Mar 07 03:14:45 dbhost01 systemd: Failed to start OHAS Daemon.
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_CRS_CGROUP_01
root_cause:     CGROUP_OOM_KILL (systemd memory limit on ohasd)
root_time:      03:14:18
ora_codes:      [ORA-29701]
fix:            FIX_INCREASE_CGROUP_LIMIT + FIX_SYSTEMD_ULIMITS
note:           "No ORA code in DB alert.log — check /var/log/messages first"
```

---

## CASCADE 7: KERNEL PANIC → SERVER REBOOT → CRASH RECOVERY

### Trigger: HBA driver kernel crash

```
TIMELINE:
  02:44:00  /var/log/msg   → soft lockup building (early warning)
  02:46:00  /var/log/msg   → hard lockup detected
  02:46:01  /var/log/msg   → Kernel panic (root cause)
  02:46:02                  → Server reboots (no Oracle log written)
  02:51:00  alert.log      → DB restarted by CRS
  02:51:01  alert.log      → Beginning crash recovery
  02:54:00  alert.log      → Crash recovery complete
  02:54:01  alert.log      → DB open, available
```

**Full Log Evidence:**
```
# /var/log/messages (early warning — often missed)
Mar 07 02:44:00 dbhost01 kernel: BUG: soft lockup - CPU#8 stuck for 22s! [oracle:18821]
Mar 07 02:44:00 dbhost01 kernel: Modules linked in: qla2xxx(O) ...
Mar 07 02:44:00 dbhost01 kernel: CPU: 8 PID: 18821 Comm: oracle Tainted: OE
Mar 07 02:44:00 dbhost01 kernel: Call Trace:
Mar 07 02:44:00 dbhost01 kernel:  [<ffffffff8108d7f2>] ? __wake_up_common+0x52/0x90
Mar 07 02:44:00 dbhost01 kernel:  [<ffffffffc04a2182>] qla2xxx_eh_abort+0x182/0x290 [qla2xxx]

# Hard lockup
Mar 07 02:46:00 dbhost01 kernel: Watchdog detected hard LOCKUP on cpu 8
Mar 07 02:46:00 dbhost01 kernel: NMI backtrace for cpu 8
Mar 07 02:46:00 dbhost01 kernel: Kernel panic - not syncing: Hard LOCKUP

# Kernel panic and reboot
Mar 07 02:46:01 dbhost01 kernel: Kernel panic - not syncing: Fatal exception
Mar 07 02:46:01 dbhost01 kernel: Marking controller dead, do not restart, we have IO in flight

# DB restarted by CRS (new log file after reboot)
Thu Mar 07 02:51:00 2024
Starting ORACLE instance (normal)
LGWR: STARTING LGWR ARCHIVAL
Beginning crash recovery of 1 threads
 parallel recovery started with 8 processes
Started redo application at
 Thread 1: logseq 18821, block 182
Recovery of Online Redo Log: Thread 1 Group 2 Seq 18821 Reading mem 0

Thu Mar 07 02:54:01 2024
Completed crash recovery at
 Thread 1: logseq 18821, block 4821, scn 182182182
2 data blocks read, 2 data blocks written, 8 redo blocks read
SMON: enabling tx recovery
Database Characterset is AL32UTF8
```

**Cascade Metadata:**
```
cascade_id:     CASCADE_KERNEL_PANIC_01
root_cause:     SOFT_LOCKUP → HARD_LOCKUP → KERNEL_PANIC (HBA driver bug)
root_time:      02:44:00 (soft lockup) → 02:46:01 (panic)
ora_codes:      [] (no ORA code — server reboots before Oracle can log)
downtime:       ~8 minutes (02:46 crash to 02:54 DB open)
fix:            Update qla2xxx HBA firmware/driver + FIX_ENABLE_MULTIPATH
note:           "No ORA code visible. Check /var/log/messages for soft lockup first."
```
