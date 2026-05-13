# AIX Platform — Critical Error Logs
## 20 Authentic AIX Oracle DBA Errors
## Temperature: 0.0 | Real AIX log formats

---

## AIX-01: DISK I/O ERROR (hdisk — SCSI Timeout Equivalent)

**ORA Code: ORA-27072**

```
# errpt -a output on AIX dbhost01
---------------------------------------------------------------------------
LABEL:          DISK_ERR7
IDENTIFIER:     B5757C89
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Sequence Number: 18821
Machine Id:     00F84C994C00
Node Id:        dbhost01
Class:          H
Type:           PERM
WPAR:           Global
Resource Name:  hdisk2
Resource Class: disk
Resource Type:  mpioosdisk

Description
DISK OPERATION ERROR

User Causes
NONE

Probable Causes
DASD DEVICE

Failure Causes
DISK DEVICE

Recommended Actions
PERFORM PROBLEM DETERMINATION PROCEDURES
CONTACT APPROPRIATE SERVICE REPRESENTATIVE

Detail Data
SENSE DATA
0070 0000 0300 0000 0000 001c 0000 0000
0000 0000 0000 0000 4400 0000 0000 0000
```

**Concurrent Oracle alert.log:**
```
Mon Apr 21 03:14:19 2024
ORA-27072: File I/O error
IBM AIX RISC System/6000 Error: 5: Input/output error
Additional information: 4
Additional information: 0
Additional information: 0
```

---

## AIX-02: MPIO PATH FAILURE (Multipath Equivalent)

**ORA Code: ORA-27072 / ORA-15080**

```
# lspath -l hdisk2 output showing failed path
name    state   connection                      parent
hdisk2  Failed  fscsi0/0x5006016844602155/0x0  fscsi0
hdisk2  Enabled fscsi1/0x5006016044602155/0x0  fscsi1

# errpt showing path failure
---------------------------------------------------------------------------
LABEL:          MPIO_PATH_ERR
IDENTIFIER:     FC4E2B21
Date/Time:      Mon Apr 21 03:14:17 IST 2024
Node Id:        dbhost01
Class:          H
Type:           PERM
Resource Name:  fscsi0

Description
MPIO PATH HAS FAILED
Path from fscsi0 to hdisk2 has failed.

Detail Data
PATH STATUS:    Failed
DEVICE:         hdisk2
PARENT:         fscsi0
LOCATION:       U78C3.001.WZS00L7-P1-C8-T1
```

**ORA Code in alert.log:**
```
Mon Apr 21 03:14:19 2024
ORA-15080: synchronous I/O request to a disk failed
IBM AIX RISC System/6000 Error: 5: Input/output error
ORA-15081: failed to submit an I/O operation to a disk
```

---

## AIX-03: FC HBA LINK RESET (qla2xxx AIX equivalent)

**ORA Code: ORA-27072**

```
# errpt showing FC adapter error
---------------------------------------------------------------------------
LABEL:          FC_LINK_DOWN
IDENTIFIER:     3EA21B47
Date/Time:      Mon Apr 21 03:14:16 IST 2024
Node Id:        dbhost01
Class:          H
Type:           PERM
Resource Name:  fcs0

Description
FIBRE CHANNEL LINK DOWN

Detail Data
LINK STATUS:  Down
ADAPTER:      fcs0
LOCATION:     U78C3.001.WZS00L7-P1-C8-T1
CURRENT SPEED: 0 Gbps
CONFIGURED SPEED: 8 Gbps

# fcstat fcs0 (FC stats showing errors)
FC STATISTICS for fcs0
  Frames recv: 18281921
  Frames xmit: 18100482
  Link Failure Count: 3         ← 3 link failures
  Loss of Sync Count: 127
  Loss of Signal Count: 127
  Invalid CRC Count: 0
```

---

## AIX-04: CPU ENTITLEMENT EXCEEDED (LPAR Capping — AIX Steal equivalent)

**ORA Code: Does Not Exist (AWR shows CPU wait, DB Time spike)**

```
# lparstat 1 5 output — %entc exceeds 100% = CPU throttled
System configuration: type=Shared mode=Uncapped smt=4 lcpu=8 mem=32768MB ent=4.00

%user  %sys   %wait  %idle  physc  %entc  lbusy   app    vcsw   phint
 87.2   11.3    0.8    0.7   4.28  107.0   82.1    --    12821   1821
 89.1   10.2    0.5    0.2   4.41  110.3   84.2    --    14821   2021
 91.2    8.4    0.3    0.1   4.47  111.8   86.1    --    16821   2421
 93.1    6.7    0.1    0.1   4.49  112.3   88.2    --    18821   2821
 94.2    5.5    0.1    0.2   4.48  112.0   87.1    --    17821   2621

# entc > 100% means LPAR is consuming more than entitled capacity
# Hypervisor will throttle CPU — equivalent of %steal in Linux
```

**AWR evidence (no ORA code — silent degradation):**
```
Top 5 Timed Events (from AWR)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Event                       Waits    Time(s)  Avg Wait(ms)  % Total
CPU time                   182810    4821.2           --      71.2
db file sequential read      8821     821.2         93.1      12.1
log file sync               18821     421.0         22.3       6.2
```

---

## AIX-05: PAGING SPACE EXHAUSTION (AIX Swap Equivalent)

**ORA Code: ORA-04031 (indirect)**

```
# lsps -a showing paging space full
Page Space  Physical Volume   Volume Group    Size    %Used  Active  Auto  Type
hd6         hdisk0            rootvg          8192MB   94%     yes    yes    lv
paging00    hdisk2            oravg          16384MB   98%     yes    yes    lv

# svmon -G showing memory pressure
               size       inuse        free         pin    virtual
memory       8388608     8200121      188487     2821482    8288210
pg space    24576000    24099821      476179

# errpt showing paging space warning
LABEL:          PAGING_DEV_WARN
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Description
PAGING SPACE IS LOW
Paging space is 95% utilized. Processes may be killed.
```

**Oracle alert.log:**
```
Mon Apr 21 03:14:21 2024
WARNING: Shared memory is running low (84% used)
ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","unknown object","sga heap(1,0)","KKSSP^2")
```

---

## AIX-06: JFS2 FILESYSTEM ERROR (Equivalent of EXT4 Journal Abort)

**ORA Code: ORA-00257**

```
# errpt showing JFS2 error
---------------------------------------------------------------------------
LABEL:          JFS2_LOGERR
IDENTIFIER:     A59F2B82
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Node Id:        dbhost01
Class:          S
Type:           PERM
Resource Name:  /dev/lv_arch

Description
JFS2 FILE SYSTEM LOG ERROR
A hard error has occurred on a JFS2 log device.
The file system /arch has been force unmounted.

Detail Data
DEVICE:     /dev/lv_arch
ERRNO:      5
ACTION:     Filesystem unmounted, run fsck before remounting.
```

**Oracle alert.log:**
```
Mon Apr 21 03:14:19 2024
ARC1: Archival stopped, error occurred. Will continue retrying
ORA-16038: log 2 sequence# 18821 cannot be archived
ORA-00257: archiver error. Connect internal only, until freed.
```

---

## AIX-07: NETWORK LINK DOWN (EN_LINK_DOWN — Bond Failover Equivalent)

**ORA Code: ORA-03113**

```
# errpt showing NIC failure
---------------------------------------------------------------------------
LABEL:          EN_LINK_DOWN
IDENTIFIER:     6BF2EC71
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Node Id:        dbhost01
Class:          H
Type:           TEMP
Resource Name:  ent0

Description
ETHERNET ADAPTER LINK STATUS CHANGED TO DOWN
The Ethernet adapter ent0 detected that the link is no longer active.

Detail Data
ADAPTER:        ent0
LINK STATUS:    Down
SPEED:          0
DUPLEX:         Unknown

# AIX EtherChannel (bond equivalent) status
# entstat -d ent2 | grep -i "switch\|backup\|active"
  IEEE 802.3ad LACP EtherChannel
  Active Channel: ent1
  Backup Channel: ent0 (link down — using backup failed)
  Packets Dropped: 18821
```

---

## AIX-08: SEMAPHORE LIMIT (AIX IPC Limits)

**ORA Code: ORA-27300 / ORA-27301 / ORA-27302**

```
# Oracle startup failure on AIX
Mon Apr 21 03:14:18 IST 2024
Starting ORACLE instance (normal)
ORA-27154: post/wait create failed
ORA-27300: OS system dependent operation: semget failed with status: 28
ORA-27301: OS failure message: No space left on device
ORA-27302: failure occurred at: sskgpsemsper

# Check AIX semaphore limits
# lsattr -El sys0 | grep sem
semmni 131072  Maximum number of semaphore identifiers  True
semmns 262144  Maximum number of semaphores             True
semmsl 250     Maximum number of semaphores per id      True
semvmx 32767   Maximum value of semaphore               True

# Current semaphore usage
# ipcs -ls
Semaphore status on dbhost01
IPC ID    Owner      Mode      Create time    Key
131070    oracle     --rw-rw-rw  03:10:01    0x3e218821
131071    oracle     --rw-rw-rw  03:10:02    0x3e218822
# semmni limit reached — no more semaphore IDs available
```

---

## AIX-09: ORACLE SGA CREATION FAILED (AIX shmget)

**ORA Code: ORA-27102**

```
Mon Apr 21 03:14:18 IST 2024
Starting ORACLE instance (normal)
ORA-27102: out of memory
IBM AIX RISC System/6000 Error: 12: Not enough space
Additional information: 18821

# AIX shared memory limits
# lsattr -El sys0 | grep shm
shmmni  4096     Maximum number of shared memory IDs    True
shmmax  107374182400  Maximum shared memory segment size True
shmmin  1        Minimum shared memory segment size     True
shmseg  256      Maximum segments per process           True

# Check current SGA attempt vs available
# Oracle tried to allocate 96GB SGA
# shmmax = 96GB  ←  exactly equals SGA size, should be LARGER
# Rule: shmmax must be >= SGA_TARGET + PGA_AGGREGATE_TARGET
```

---

## AIX-10: ORACLE PROCESS KILLED BY AIX WORKLOAD MANAGER

**ORA Code: ORA-00603**

```
# errpt showing WLM action
---------------------------------------------------------------------------
LABEL:          WLM_PROC_KILLED
IDENTIFIER:     2C71A821
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Node Id:        dbhost01
Class:          S
Type:           PERM
Resource Name:  oracle

Description
WORKLOAD MANAGER KILLED PROCESS
WLM killed process oracle (PID 18821) due to memory limit enforcement.
Memory tier 'DatabaseTier' exceeded configured limit of 28672 MB.

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-00603: ORACLE server session terminated by fatal error
ORA-00600: internal error code, arguments: [LibraryCacheNotEmpty], [], [], []
PMON: terminating instance due to error 603
```

---

## AIX-11: DISK FULL — /arch on AIX LVM

**ORA Code: ORA-00257**

```
# df showing AIX filesystem full (note: AIX df shows 512-byte blocks)
Filesystem    512-blocks      Free %Used Iused %Iused Mounted on
/dev/lv_arch   419430400         0  100%  8821     2% /arch

# Converting: 419430400 × 512 = 200GB total, 0 free = 100% full

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ARC2: Archival stopped, error occurred. Will continue retrying
ORA-16038: log 3 sequence# 18821 cannot be archived
ORA-19504: failed to create file "+DATA/PROD/ARCHIVELOG/2024_04_21/arch1_18821_1234567890.dbf"
ORA-00257: archiver error. Connect internal only, until freed.
```

---

## AIX-12: LPAR MEMORY BALLOON (AIX-specific — no Linux equivalent)

**ORA Code: Does Not Exist (ORA-04031 indirect)**

```
# lparstat showing memory ballooning from hypervisor
System configuration: type=Shared mode=Uncapped smt=4 mem=32768MB

# svmon -G showing sudden memory reduction
               size       inuse        free
memory       8388608     8352121       36487   ← only 36487 free pages (144MB)

# AIX hypervisor reclaimed memory from LPAR (ballooning)
# DBA must check:
# lssrad -av  ← NUMA/memory placement
# vmstat -v   ← virtual memory detail

# Oracle alert.log evidence
Mon Apr 21 03:14:18 2024
WARNING: Shared memory is running low (97% used)
WARNING: Large number of shared pool contention events
ORA-04031: unable to allocate 16384 bytes of shared memory
("shared pool","unknown object","sga heap(1,0)","free memory")
```

---

## AIX-13: ODM CORRUPTION (AIX device database — no Linux equivalent)

**ORA Code: Does Not Exist (Oracle cannot start)**

```
# errpt showing ODM error
LABEL:          ODM_CORR_LCK
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Class:          S
Type:           PERM
Description
OBJECT DATA MANAGER OBJECT CORRUPTED OR LOCKED
The ODM database is corrupted. Device configuration may be unavailable.

# Impact: Oracle ASM cannot discover disks because ASMLib uses ODM
# lsdev -Cc disk   ← shows no disks available
# Oracle startup fails silently with:
ORA-15072: command requires at least 1 PST-disks in group, only 0 present
ORA-15032: not all alterations performed
ORA-15017: diskgroup "DATA" cannot be mounted
```

---

## AIX-14: CRS VOTING DISK TIMEOUT ON AIX

**ORA Code: ORA-29740**

```
# ocssd.log on AIX
2024-04-21 03:14:18.821 [CSSD(18821)]CRS-1618: Node dbhost02 is not responding
2024-04-21 03:14:19.182 [CSSD(18821)]CRS-1625: Node dbhost02 is being evicted
2024-04-21 03:14:21.821 [CSSD(18821)]CRS-1632: Server dbhost02 is being stopped

# Concurrent errpt on dbhost01 showing interconnect issue
LABEL:          IB_LINK_ERROR
Date/Time:      Mon Apr 21 03:14:16 IST 2024
Description
INFINIBAND LINK ERROR ON ib0
Excessive bit error rate detected on IB port.

# Oracle alert.log
Mon Apr 21 03:14:22 2024
ORA-29740: evicted by member 0, group incarnation 7
```

---

## AIX-15: ORACLE BINARY PERMISSION ISSUE AFTER AIX PATCH

**ORA Code: ORA-27300 / ORA-27301**

```
# After AIX OS patching, setuid bit lost on Oracle binaries
# errpt
LABEL:          PRIV_ERR
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Description
PRIVILEGE ERROR
Process attempted privileged operation without required privileges.
Process: oracle (PID 18821)
Operation: shmget (shared memory creation)

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-27300: OS system dependent operation:shmget failed with status: 1
ORA-27301: OS failure message: Operation not permitted
ORA-27302: failure occurred at: sskgmsmat

# Diagnosis
# ls -l $ORACLE_HOME/bin/oracle
-rwsr-s--x 1 oracle oinstall 421890821 Apr 20 22:00 oracle
# setuid bit present ✓

# Check AIX security policy
# lssecattr -c oracle
oracle:
  auth = oracle
# AIX security may be blocking shmget despite setuid
```

---

## AIX-16: LARGE PAGE ALLOCATION FAILURE ON AIX

**ORA Code: ORA-27102**

```
# AIX uses 64KB pages by default; Oracle needs large pages
# errpt showing allocation failure
LABEL:          LARGE_PAGE_ALLOC_FAIL
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Description
LARGE PAGE ALLOCATION FAILED
System could not allocate large pages for process oracle (PID 18821).

# Check AIX large page config
# vmo -o lgpg_size
lgpg_size = 16777216          ← 16MB large pages configured
# vmo -o lgpg_regions
lgpg_regions = 0              ← 0 large page regions = PROBLEM

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-27102: out of memory
IBM AIX RISC System/6000 Error: 12: Not enough space
Additional information: 12 (lgpg_regions = 0, SGA not using large pages)
```

---

## AIX-17: RMAN BACKUP FAILURE — TAPE DEVICE ON AIX

**ORA Code: ORA-27072**

```
# RMAN output on AIX with tape backup
RMAN> backup database plus archivelog;

Starting backup at 21-APR-2024 03:14:18
using channel ORA_SBT_TAPE_1
RMAN-03009: failure of backup command on ORA_SBT_TAPE_1 channel
ORA-19506: failed to create sequential file, name="/dev/rmt0", params=""
ORA-27072: File I/O error
IBM AIX RISC System/6000 Error: 16: Device busy
Additional information: 17

# Check tape device
# lsdev -Cc tape
rmt0      Available  05-08-00-8,0    IBM 3592 Tape Drive
# tctl -f /dev/rmt0 status
/dev/rmt0: Input/output error  ← tape drive not ready
```

---

## AIX-18: NFS MOUNT TIMEOUT ON AIX

**ORA Code: ORA-27054 / ORA-00257**

```
# /var/adm/syslog/syslog.log on AIX
Apr 21 03:14:18 dbhost01 nfsd[18821]: NFS server nfshost01 not responding, still trying
Apr 21 03:14:48 dbhost01 nfsd[18821]: NFS server nfshost01 not responding, timed out
Apr 21 03:14:48 dbhost01 kern: NFS3 server nfshost01: not responding

# mount showing hung NFS mount
# mount | grep nfs
nfshost01:/export/arch   /arch    nfs  rw,hard,bg,timeo=600  0 0
#  ← hard mount = hangs indefinitely if NFS down

# Oracle alert.log
Mon Apr 21 03:14:49 2024
ORA-27054: NFS file system where the file is created or resides is not mounted
           with correct options
IBM AIX RISC System/6000 Error: 110: Connection timed out
```

---

## AIX-19: ORACLE LISTENER CRASH — AIX PORT CONFLICT

**ORA Code: ORA-12541 / ORA-12519**

```
# listener.log on AIX
21-APR-2024 03:14:18 * (CONNECT_DATA=...) * (ADDRESS=(PROTOCOL=tcp)(HOST=dbhost01)(PORT=1521)) * establish * PROD * 12541
TNS-12541: TNS:no listener
TNS-12560: TNS:protocol adapter error
TNS-00511: No listener

# errpt showing port conflict
LABEL:          SOCKET_ERR
Date/Time:      Mon Apr 21 03:14:15 IST 2024
Description
TCP SOCKET BIND FAILURE
Process tnslsnr (PID 18821) failed to bind to port 1521.
Error: EADDRINUSE (Address already in use)

# Another process grabbed port 1521
# netstat -Aan | grep 1521
f100000000a82b58 tcp4  0  0  *.1521  *.*  LISTEN    ← but which PID?
# rmsock f100000000a82b58 tcpcb   ← AIX command to find socket owner
```

---

## AIX-20: CPU HARD PARTITION FAILURE (AIX LPAR — no Linux equivalent)

**ORA Code: Does Not Exist (instance crash)**

```
# errpt showing LPAR hardware fault
LABEL:          LPAR_CPU_ERR
IDENTIFIER:     8B21A782
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Class:          H
Type:           PERM
Resource Name:  PROC00

Description
PROCESSOR ERROR
A permanent error was detected in processor unit PROC00.
The processor has been deconfigured by the hypervisor.
Remaining CPUs: 6 of 8

# Oracle sees sudden CPU loss mid-operation
# No ORA code written — LGWR cannot get CPU → instance aborts

# Oracle alert.log
Mon Apr 21 03:14:19 2024
LGWR: terminating instance due to error 472
ORA-00472: PMON process terminated with error
Instance terminated by LGWR, pid = 18821
```
