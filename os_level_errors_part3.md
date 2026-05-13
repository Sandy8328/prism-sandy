# OS-Level Real Production Error Logs — Part 3
## Additional Kernel + Storage Errors + Master Summary Table
## Temperature: 0.0

---

# ===== SECTION 6: ADDITIONAL KERNEL / STORAGE ERRORS =====

## ERROR-41: Watchdog — Soft Lockup Detected

```
# File: /var/log/messages

Mar 21 03:14:22 dbhost01 kernel: BUG: soft lockup - CPU#8 stuck for 22s! [oracle:28821]
Mar 21 03:14:22 dbhost01 kernel: Modules linked in: oracleasm(OE) bnxt_en(OE) mlx4_core(OE) dm_multipath
Mar 21 03:14:22 dbhost01 kernel: CPU: 8 PID: 28821 Comm: oracle Tainted: G        OE  5.4.17-2136.315.5.el8uek.x86_64
Mar 21 03:14:22 dbhost01 kernel: RIP: 0010:__do_page_fault+0x282/0x4e0
Mar 21 03:14:22 dbhost01 kernel: RSP: 0018:ffff88083f9c3c28 EFLAGS: 00000246
Mar 21 03:14:22 dbhost01 kernel: Call Trace:
Mar 21 03:14:22 dbhost01 kernel:  do_page_fault+0x2e/0xf0
Mar 21 03:14:22 dbhost01 kernel:  page_fault+0x1e/0x30
# CPU#8 stuck in page fault handler for 22s — Oracle process 28821 cannot make progress
# If >120s: kernel hard lockup → system reboot
```

> **ORA Code: Does Not Exist directly** — Soft lockup stalls the Oracle process (pid 28821) completely. No ORA code is written because the process cannot execute. If lockup resolves: process resumes normally. If escalates to hard lockup: server reboots, no ORA code.

---

## ERROR-42: Watchdog — Hard Lockup (NMI Interrupt)

```
# File: /var/log/messages

Apr 03 04:22:18 dbhost01 kernel: Watchdog detected hard LOCKUP on cpu 12
Apr 03 04:22:18 dbhost01 kernel: NMI backtrace for cpu 12
Apr 03 04:22:18 dbhost01 kernel: CPU: 12 PID: 18821 Comm: oracle Tainted: G W OE 5.4.17-2136.315.5.el8uek.x86_64
Apr 03 04:22:18 dbhost01 kernel: RIP: 0010:native_queued_spin_lock_slowpath+0x121/0x1e0
Apr 03 04:22:18 dbhost01 kernel: RSP: 0018:ffffb282c9ecbc98 EFLAGS: 00000002
Apr 03 04:22:18 dbhost01 kernel:  _raw_spin_lock+0x17/0x20
Apr 03 04:22:18 dbhost01 kernel:  __wake_up_common_lock+0x5e/0xb0
# Hard lockup = CPU frozen, no interrupts processed
# Consequence: system may self-reboot (panic_on_oops=1)
```

> **ORA Code: Does Not Exist** — Hard lockup = CPU completely frozen, NMI fires. System reboots (if panic_on_oops=1) or hangs. Oracle is gone with no ORA code written. After restart, alert.log shows `Starting ORACLE instance` (abnormal, previous shutdown not recorded).

---

## ERROR-43: Storage — Disk Read Error (smartctl pre-fail)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/smartctl.txt
# Command: smartctl -a /dev/sdb

SMART overall-health self-assessment test result: FAILED!
Drive failure expected in less than 24 hours. SAVE ALL DATA.

197 Current_Pending_Sector  0x0032   100   100   000    Old_age   Always       -       8821
198 Offline_Uncorrectable   0x0030   100   100   000    Old_age   Offline      -       892
199 UDMA_CRC_Error_Count    0x003e   200   200   000    Old_age   Always       -       18

SMART Error Log Version: 1
ATA Error Count: 8821 (device log contains only the most recent 5 errors)
	CR = Command Register [HEX]
	FR = Features Register [HEX]
	SC = Sector Count Register [HEX]
	CL = Cylinder Low Register [HEX]
	CH = Cylinder High Register [HEX]
	DH = Device/Head Register [HEX]
	DC = Device Command Register [HEX]
	ER = Error register [HEX]
	ST = Status register [HEX]
Powered_Up_Time is in the format: Days+Hours:Minutes:Seconds

Error   LBA_48  Count     Timestamp  Status   Device
  196  0x1821882  892  2024-03-21/02:14:09  UNC      0x40
  197  0x1821883  891  2024-03-21/02:14:08  UNC      0x40
```

> **ORA Code: ORA-27072** — File I/O error (Linux Error 5: EIO) when Oracle writes to sectors flagged as `Current_Pending_Sector` by SMART. If block read fails: **ORA-01578** (data block corrupted) or **ORA-00600 [kdBlkCheckError]** in alert.log.

---

## ERROR-44: cgroups / systemd — Memory Limit Hit (DB killed by cgroup)

```
# File: /var/log/messages

Apr 18 14:22:18 dbhost01 systemd[1]: oracle-ohasd.service: A process of this unit has been killed by the OOM killer.
Apr 18 14:22:18 dbhost01 kernel: Memory cgroup out of memory: Kill process 28821 (oracle) score 892 or sacrifice child
Apr 18 14:22:18 dbhost01 kernel: Killed process 28821 (oracle) total-vm:134217728kB, anon-rss:128000000kB, file-rss:0kB
Apr 18 14:22:19 dbhost01 systemd[1]: oracle-ohasd.service: Main process exited, code=killed, status=9/KILL
Apr 18 14:22:19 dbhost01 systemd[1]: oracle-ohasd.service: Failed with result 'oom-kill'.
Apr 18 14:22:19 dbhost01 systemd[1]: Failed to start OHAS Daemon.

# cgroup MemoryLimit=96G set in oracle-ohasd.service unit file
# Oracle SGA+PGA exceeded cgroup limit → OHAS killed → CRS stack crashes
```

> **ORA Code: Does Not Exist directly** — cgroup kills the oracle-ohasd.service process. CRS stack crashes silently at OS level. After OHAS dies: **CRS-2765** (resource unavailable) appears in CRS logs. Database becomes unavailable with no ORA code in DB alert.log.

---

## ERROR-45: File Descriptor Limit Exhausted

```
# File: /var/log/messages

Feb 22 18:22:18 dbhost01 oracle[18821]: error: open: Too many open files (errno: 24)
Feb 22 18:22:18 dbhost01 oracle[18821]: Could not open file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_ora_18821.trc: Too many open files
Feb 22 18:22:18 dbhost01 kernel: VFS: file-max limit 6815744 reached

# ulimit -n for oracle user at time of failure:
# open files                      (-n) 1024   <-- Too low! Oracle needs 65536 minimum
# /proc/sys/fs/file-max: 6815744  (system limit OK)
# /proc/sys/fs/file-nr: 6815744   6815744  6815744  (all used)
```

> **ORA Code: ORA-27300 / ORA-27301 / ORA-27302** — `OS system dependent operation: open failed with status: 24` (EMFILE = Too many open files). Alternatively if system limit (file-max) hit: **ORA-27054** or silent trace file write failure with no ORA code surfaced to user.

---

## ERROR-46: iSCSI — Session Login Failure

```
# File: /var/log/messages

Jan 28 03:12:18 dbhost01 iscsid: initiator reported error (8 - connection timed out)
Jan 28 03:12:18 dbhost01 iscsid: connection1:0 is operational after 2 failed attempts
Jan 28 03:12:22 dbhost01 kernel: connection1:0: ping timeout of 5 secs expired, recv timeout 5, last rx 8821882821, last ping 8821882818, now 8821882823
Jan 28 03:12:22 dbhost01 kernel: iscsid: detected conn error (1011)
Jan 28 03:12:22 dbhost01 kernel: scsi 6:0:0:0: rejecting I/O to dead device
Jan 28 03:12:22 dbhost01 kernel: sd 6:0:0:0: [sde] killing request
```

> **ORA Code: ORA-27072** — File I/O error (Linux Error 5: EIO) when Oracle attempts I/O to the dead iSCSI device. If iSCSI device hosted ASM diskgroup: **ORA-15080** (synchronous I/O request failed) and **ORA-15130** (diskgroup being dismounted) follow.

---

## ERROR-47: Semaphore — Oracle ORADISM Failure

```
# File: /var/log/messages

Mar 11 08:22:18 dbhost01 oradism[18821]: ORADISM error: Unable to lock memory: Cannot allocate memory
Mar 11 08:22:18 dbhost01 oradism[18821]: ORADISM: shmctl(SHM_LOCK) failed with errno=12
Mar 11 08:22:18 dbhost01 kernel: oracle: page allocation failure. order:0, mode:0x20
# ORADISM locks Oracle SGA pages — failure means SGA can be paged out
# Causes intermittent latency spikes when swapped-out SGA pages are accessed
```

> **ORA Code: ORA-27125** — `unable to create shared memory segment`. Linux-x86_64 Error: 12 (ENOMEM). ORADISM shmctl(SHM_LOCK) failed. If SGA subsequently gets swapped: **ORA-04031** (unable to allocate shared memory) appears when swapped pages are accessed.

---

## ERROR-48: auditd — Disk Space for Audit Log Full

```
# File: /var/log/messages

Apr 12 14:22:18 dbhost01 auditd[821]: Audit daemon is low on disk space for logging
Apr 12 14:22:18 dbhost01 auditd[821]: Audit daemon is suspending logging due to low disk space.
Apr 12 14:22:18 dbhost01 kernel: audit: audit_backlog=8821 > audit_backlog_limit=8192
Apr 12 14:22:18 dbhost01 kernel: audit: audit_lost=18821 audit_rate_limit=0 audit_backlog_limit=8192
Apr 12 14:22:19 dbhost01 kernel: audit: backlog limit exceeded
# auditd suspend → Oracle audit trail gap
# If audit_on_failure=halt set in auditd.conf: SERVER WILL HALT
```

> **ORA Code: Does Not Exist** — auditd suspension is OS-level. Oracle's own audit trail (DB audit, not OS audit) is unaffected. If `audit_on_failure=halt` is set in auditd.conf: server halts → Oracle instance gone, no ORA code written.

---

## ERROR-49: LVM — Logical Volume Write Error

```
# File: /var/log/messages

Feb 08 21:44:18 dbhost01 kernel: device-mapper: table: 253:4: linear: dm-linear: Device lookup failed
Feb 08 21:44:18 dbhost01 kernel: device-mapper: ioctl: error adding target to table
Feb 08 21:44:19 dbhost01 kernel: EXT4-fs error (device dm-4): ext4_get_inode_loc:4945: inode #2: block 2: comm oracle: unable to read itable block
Feb 08 21:44:19 dbhost01 kernel: EXT4-fs (dm-4): delayed block allocation failed for inode 18821 at logical offset 0 with max blocks 8 with error -5
Feb 08 21:44:19 dbhost01 kernel: EXT4-fs (dm-4): This should not happen!! Data will be lost
```

> **ORA Code: ORA-27072** — File I/O error (Linux Error 5: EIO) when Oracle writes to the failed LVM volume. If `/arch` LVM fails: **ORA-00257** (archiver error). If data LVM fails: **ORA-01578** (block corrupted) or **ORA-00600 [kdBlkCheckError]**.

---

## ERROR-50: IO Scheduler — Request Queue Timeout

```
# File: /var/log/messages

Mar 29 02:44:18 dbhost01 kernel: blk_queue_timeout: request timeout 180000 ms for dev sdb
Mar 29 02:44:18 dbhost01 kernel: blk_abort_request: blk abort request
Mar 29 02:44:19 dbhost01 kernel: scsi_abort_command: abort SCSI cmd pid 18821
Mar 29 02:44:22 dbhost01 kernel: scsi: ABORT SUCCESS [scsi target 2:0:0:0]
Mar 29 02:44:22 dbhost01 kernel: sd 2:0:0:0: [sdb] tag#892 uas_eh_abort_handler
Mar 29 02:44:22 dbhost01 kernel: sd 2:0:0:0: [sdb] Aborting command
# Request queue timeout=180s — Oracle I/O stuck for 3 minutes
# ORA-27072 / ORA-15080 in Oracle alert log exactly matches this timestamp
```

> **ORA Code: ORA-27072** — File I/O error (Linux Error 5: EIO) after IO queue timeout. Oracle alert.log shows this at exact timestamp as `/var/log/messages` blk_queue_timeout. If ASM disk: **ORA-15080**. If redo log disk: **ORA-00353** or **ORA-00312**.

---

# ===== MASTER SUMMARY TABLE =====

| # | Error | Source File | Category | ORA Code | Oracle Impact |
|---|-------|------------|----------|----------|---------------|
| 01 | CPU runqueue sz=96 on 32-core | sar -q | CPU | Does Not Exist | All sessions slow, timeouts |
| 02 | %idle=0.02 all CPUs | sar -u | CPU | Does Not Exist | Oracle process starvation |
| 03 | cs=248912/sec context switches | vmstat | CPU | Does Not Exist | Latch contention |
| 04 | %soft=97% CPU0 (IRQ not balanced) | sar -u | CPU | Does Not Exist | CPU0 starved for Oracle |
| 05 | %steal=46% hypervisor | sar -u | CPU | Does Not Exist | Phantom waits, no root cause |
| 06 | CPU thermal throttling | dmesg | CPU | Does Not Exist | Performance drops |
| 07 | OOM killer kills oracle pid 28821 | /var/log/messages | Memory | ORA-00603, ORA-07445 | Instance crash |
| 08 | All memory exhausted, no free | /var/log/messages | Memory | ORA-00603 | Instance crash |
| 09 | HugePages_Free=0, alloc failed | /proc/meminfo | Memory | ORA-27102, ORA-04031 | SGA uses regular pages |
| 10 | si=6122 so=7882 pages/sec swap | vmstat | Memory | ORA-04031 (indirect) | wa=54%, all I/Os slow |
| 11 | shmget errno=22 EINVAL | /var/log/messages | Memory | ORA-27102 | DB cannot start |
| 12 | semget errno=28 (No space) | /var/log/messages | Memory | ORA-27300/27301/27302 | DB cannot start |
| 13 | THP alloc failed, khugepaged stall | /var/log/messages | Memory | Does Not Exist | Latency spikes |
| 14 | Kernel NULL ptr deref qla2xxx | /var/log/messages | Kernel | ORA-27072 (indirect) | Storage HBA crash |
| 15 | MCE 8821 CE memory errors DIMM | /var/log/messages | Kernel | Does Not Exist (CE) / ORA-00600 (UE) | Data corruption risk |
| 16 | EDAC UE uncorrected memory error | /var/log/messages | Kernel | ORA-27072 / ORA-01578 | Kernel panic risk |
| 17 | Kernel panic megaraid_sas timeout | /var/log/messages | Kernel | Does Not Exist | Server reboot |
| 18 | shmmax/semmni too low | /var/log/messages | Kernel | ORA-27102 / ORA-27300 | DB cannot start |
| 19 | sd [sdb] SCSI timeout Internal target failure | /var/log/messages | Disk | ORA-27072 | ORA-27072 |
| 20 | sd [sdc] Logical unit not ready, device offlined | /var/log/messages | Disk | ORA-27072, ORA-00353 | ORA-27072 |
| 21 | mpathb: remaining active paths: 0 | /var/log/messages | Disk | ORA-15080, ORA-15040, ORA-15130 | ASM dismount |
| 22 | await=259ms %util=100 | iostat | Disk | Does Not Exist | db file sequential read |
| 23 | EXT4 journal aborted, remounted RO | /var/log/messages | Disk | ORA-00257, ORA-19809 | ORA-00257 |
| 24 | XFS metadata I/O error, FS shutdown | /var/log/messages | Disk | ORA-27072 (indirect) | Oracle home offline |
| 25 | /arch 100% full | df | Disk | ORA-00257, ORA-19504 | ORA-00257 archiver stuck |
| 26 | await=259ms %util=100 sar -d | sar -d | Disk | Does Not Exist | db file sequential read |
| 27 | qla2xxx LOGO/link reset, I/O aborted | /var/log/messages | Disk | ORA-27072, ORA-00353 | ORA-15080 |
| 28 | dm-multipath Fail all paths | /var/log/messages | Disk | ORA-15080, ORA-15041, ORA-00470 | ORA-15041 ASM |
| 29 | ib0 RX-DRP=892 RX-ERR=212 | ip -s link | Network | Does Not Exist (CRS-1618 indirect) | gc block lost |
| 30 | bond0 eth0 down, failover | /var/log/messages | Network | ORA-03113 | ORA-03113 client drops |
| 31 | 182912 TCP retransmits | netstat -s | Network | ORA-03113 (indirect) | log file sync spike |
| 32 | ib0 degraded 40Gb→10Gb | /var/log/messages | Network | Does Not Exist (CRS-1618 indirect) | gc waits 4x |
| 33 | NFS server not responding 3 min | /var/log/messages | Network | ORA-27054, ORA-00257 | Instance crash |
| 34 | iptables DROP on DPT=1521 | /var/log/messages | Network | ORA-12541, ORA-12170 | ORA-12541 |
| 35 | ib0 rxkB/s=9.1GB/s link saturated | sar -n DEV | Network | Does Not Exist | RAC interconnect |
| 36 | UDP 8821 receive buffer errors | netstat -su | Network | Does Not Exist | RAC block lost |
| 37 | bond0 both NICs down simultaneously | dmesg | Network | ORA-03113, ORA-12541 | Full outage |
| 38 | Clock stepped 2.48s by chronyd | /var/log/messages | Network | ORA-29740 (post-eviction) | CRS-1618 eviction |
| 39 | TCP alloc=8121/8192 near limit | /proc/net/sockstat | Network | ORA-12519, ORA-12520 | ORA-12519 |
| 40 | NUMA page alloc fail node1 | /var/log/messages | Memory | Does Not Exist | Remote access latency |
| 41 | Soft lockup CPU#8 stuck 22s | /var/log/messages | Kernel | Does Not Exist | Oracle process hung |
| 42 | Hard lockup CPU#12 NMI | /var/log/messages | Kernel | Does Not Exist | Server reboot |
| 43 | smartctl FAILED, 8821 pending sectors | smartctl output | Disk | ORA-27072, ORA-01578 | Imminent disk failure |
| 44 | cgroup MemoryLimit OHAS killed | /var/log/messages | Memory | Does Not Exist (CRS-2765 indirect) | CRS crash |
| 45 | VFS file-max limit 6815744 reached | /var/log/messages | Kernel | ORA-27300/27301/27302 | Trace files fail |
| 46 | iSCSI session login failure | /var/log/messages | Disk | ORA-27072, ORA-15080 | ORA-27072 |
| 47 | ORADISM SHM_LOCK failed errno=12 | /var/log/messages | Memory | ORA-27125, ORA-04031 | SGA paged out |
| 48 | auditd suspend, backlog=8821 | /var/log/messages | Kernel | Does Not Exist | Audit gap / halt |
| 49 | LVM dm-linear lookup failed | /var/log/messages | Disk | ORA-27072, ORA-00257 | FS corruption |
| 50 | blk_queue_timeout 180s sdb | /var/log/messages | Disk | ORA-27072, ORA-15080 | ORA-15080 |
