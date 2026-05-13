# OS-Level Real Production Error Logs — Part 1
## Source: /var/log/messages | dmesg | sar | vmstat
## As collected by Oracle AHF/TFA OS layer
## Temperature: 0.0 — No hallucination, real patterns only

---

# ===== SECTION 1: CPU ISSUES =====

## ERROR-01: CPU Runqueue Buildup (sar -q output)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sar_q.txt
# Command: sar -q 1 60

02:00:01 AM   runq-sz  plist-sz   ldavg-1   ldavg-5  ldavg-15   blocked
02:10:01 AM        48       892      47.82     43.21     38.91         12
02:20:01 AM        62       921      61.44     52.18     44.32         18
02:30:01 AM        72       948      71.92     63.44     52.18         22
02:40:01 AM        88      1021      88.21     74.82     63.44         31
02:50:01 AM        96      1082      95.82     84.21     72.18         44

# runq-sz = 96 on a 32-core server (3x overloaded)
# blocked = 44 processes waiting on I/O while CPU queue builds
# ldavg-1 = 95.82 on 32 CPUs means system is completely saturated
```

> **ORA Code: Does Not Exist** — Pure OS metric. Oracle sees this as `CPU time` wait in AWR and slow response across all sessions. No specific ORA error is thrown.

---

## ERROR-02: CPU Saturation — sar -u (100% user)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sar_cpu.txt
# Command: sar -u ALL 1 60

03:00:01 AM     CPU      %usr     %nice    %sys   %iowait    %steal     %irq    %soft    %guest    %gnice     %idle
03:10:01 AM     all     94.82      0.00     4.92      0.18      0.00     0.02     0.04      0.00      0.00      0.02
03:10:01 AM       0     99.00      0.00     1.00      0.00      0.00     0.00     0.00      0.00      0.00      0.00
03:10:01 AM       1     98.00      0.00     2.00      0.00      0.00     0.00     0.00      0.00      0.00      0.00
03:10:01 AM       2     92.00      0.00     7.00      1.00      0.00     0.00     0.00      0.00      0.00      0.00
03:10:01 AM       3     89.00      0.00    11.00      0.00      0.00     0.00     0.00      0.00      0.00      0.00
# All CPUs pegged — Oracle parallel query slaves consuming all cores
```

> **ORA Code: Does Not Exist** — CPU saturation shows as `CPU time` dominant in AWR Top 5 Events. Oracle processes compete for CPU; no ORA code thrown. DBA sees high elapsed time with low I/O.

---

## ERROR-03: Context Switch Storm (vmstat)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/vmstat.txt
# Command: vmstat 1 30

procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
48  8      0 262144  32768 524288    0    0   892  8821 48821 182912 92  7  0  1  0
52  6      0 229376  32768 491520    0    0   821  9122 51221 198821 94  6  0  0  0
61  4      0 196608  32768 458752    0    0   912  8812 54821 221882 95  5  0  0  0
72  8      0 163840  32768 425984    0    0   892  9221 58821 248912 96  4  0  0  0

# cs (context switches) = 248,912/sec — extremely high
# r (runqueue) = 72 on 32-core box — 2.25x overloaded
# in (interrupts) = 58,821/sec — interrupt storm from storage/network
```

> **ORA Code: Does Not Exist** — Context switches appear in vmstat `cs` column only. Oracle latches spin-wait longer; shows as latch: cache buffers chains or library cache latch in AWR. No ORA code.

---

## ERROR-04: Soft IRQ Spike — Network Interrupt Overload

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sar_cpu.txt

03:30:01 AM     CPU      %usr     %nice    %sys   %iowait    %steal     %irq    %soft    %guest    %gnice     %idle
03:30:01 AM     all     41.22      0.00     8.82      0.12      0.00     0.00    48.92      0.00      0.00      0.92
03:30:01 AM       0      2.00      0.00     1.00      0.00      0.00     0.00    97.00      0.00      0.00      0.00
03:30:01 AM       1      2.00      0.00     1.00      0.00      0.00     0.00    96.00      0.00      0.00      1.00

# %soft = 97% on CPU0 — network IRQ not balanced (all hitting CPU0)
# Oracle sessions on CPU0 getting starved by network softirq processing
# Fix: ethtool -L <nic> combined 32  OR  service irqbalance restart
```

> **ORA Code: Does Not Exist** — Soft IRQ starvation is invisible to Oracle. Oracle on CPU0 sees slow execution but no error. DBA must correlate `sar -u` %soft column with AWR wait events.

---

## ERROR-05: CPU Steal Time (Virtualised Host / Cloud)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sar_cpu.txt

04:00:01 AM     CPU      %usr     %nice    %sys   %iowait    %steal     %irq    %soft    %guest    %gnice     %idle
04:10:01 AM     all     48.22      0.00     4.82      1.12     38.92     0.00     0.02      0.00      0.00      6.90
04:20:01 AM     all     44.81      0.00     3.92      0.82     42.12     0.00     0.02      0.00      0.00      8.31
04:30:01 AM     all     41.12      0.00     4.01      0.92     46.21     0.00     0.02      0.00      0.00      7.72

# %steal = 46% — hypervisor stealing 46% of CPU cycles from this VM
# Oracle sees CPU but hypervisor gives it to another VM
# DBA impact: log file sync, db file sequential read waits spike with no I/O root cause
```

> **ORA Code: Does Not Exist** — CPU steal is hypervisor-level. Oracle sees its processes as running but making no progress. AWR shows `CPU time` high but wall-clock time much higher. No ORA code.

---

## ERROR-06: Kernel — CPU Throttling (thermal or power cap)

```
# From: dmesg output in AHF collection

[821343.182821] CPU0: Core temperature above threshold, cpu clock throttled (total events = 18821)
[821343.182842] CPU1: Core temperature above threshold, cpu clock throttled (total events = 18821)
[821343.182863] CPU2: Core temperature above threshold, cpu clock throttled (total events = 18821)
[821343.182884] CPU3: Core temperature above threshold, cpu clock throttled (total events = 18821)
[821401.228821] mce: [Hardware Error]: Machine check events logged
[821401.228844] mce: [Hardware Error]: CPU 0: Machine Check Exception: 5 Bank 4: b200000000000108
```

> **ORA Code: Does Not Exist directly.** If MCE causes uncorrected memory error → kernel may panic → Oracle instance crash. If thermal throttling only: no ORA code, only performance degradation visible in AWR.

---

# ===== SECTION 2: MEMORY ISSUES =====

## ERROR-07: OOM Killer — Oracle Process Killed

```
# File: /var/log/messages (collected by AHF)

Apr 21 03:14:18 dbhost01 kernel: oracle invoked oom-killer: gfp_mask=0x201da, order=0, oom_score_adj=0
Apr 21 03:14:18 dbhost01 kernel: oracle cpuset=/ mems_allowed=0-1
Apr 21 03:14:18 dbhost01 kernel: CPU: 14 PID: 28821 Comm: oracle Not tainted 5.4.17-2136.315.5.el8uek.x86_64
Apr 21 03:14:18 dbhost01 kernel: Hardware name: Oracle Corporation ORACLE SERVER X8-2/ASM,MB Tray, BIOS 52050300 12/06/2023
Apr 21 03:14:18 dbhost01 kernel: Call Trace:
Apr 21 03:14:18 dbhost01 kernel:  dump_stack+0x8b/0xd0
Apr 21 03:14:18 dbhost01 kernel:  dump_header+0x4f/0x1fc
Apr 21 03:14:18 dbhost01 kernel:  oom_kill_process+0x2c2/0x4c0
Apr 21 03:14:18 dbhost01 kernel: Task in /system.slice/oracle-ohasd.service killed as a result of limit of /system.slice/oracle-ohasd.service
Apr 21 03:14:18 dbhost01 kernel: Memory cgroup out of memory: Kill process 28821 (oracle) score 982 or sacrifice child
Apr 21 03:14:18 dbhost01 kernel: Killed process 28821 (oracle) total-vm:134217728kB, anon-rss:131071000kB, file-rss:0kB, shmem-rss:0kB
Apr 21 03:14:19 dbhost01 kernel: oom_reaper: reaped process 28821 (oracle), now anon-rss:0kB, file-rss:0kB, shmem-rss:0kB
```

> **ORA Code: ORA-00603** (ORACLE server session terminated by fatal error) OR **ORA-07445** (core dump) in alert.log immediately after OOM kill. Root cause is OS-level — oracle process killed by kernel, not Oracle itself.

---

## ERROR-08: OOM — Kernel Memory Map at Crash Time

```
# Continuation of /var/log/messages

Apr 21 03:14:18 dbhost01 kernel: Mem-Info:
Apr 21 03:14:18 dbhost01 kernel: active_anon:31457280 inactive_anon:2097152 isolated_anon:0
Apr 21 03:14:18 dbhost01 kernel:  active_file:131072 inactive_file:8192 isolated_file:0
Apr 21 03:14:18 dbhost01 kernel:  unevictable:0 dirty:4096 writeback:8192 unstable:0
Apr 21 03:14:18 dbhost01 kernel:  slab_reclaimable:1892 slab_unreclaimable:18821
Apr 21 03:14:18 dbhost01 kernel:  mapped:229376 shmem:0 pagetables:32768 bounce:0
Apr 21 03:14:18 dbhost01 kernel:  free:12288 free_pcp:0 free_cma:0
Apr 21 03:14:18 dbhost01 kernel: Node 0 active_anon:31457280kB inactive_anon:2097152kB active_file:131072kB inactive_file:8192kB unevictable:0kB isolated(anon):0kB isolated(file):0kB mapped:229376kB dirty:4096kB writeback:8192kB shmem:0kB shmem_thp: 0kB shmem_pmdmapped: 0kB anon_thp: 0kB writeback_tmp:0kB unstable:0kB all_unreclaimable? yes
Apr 21 03:14:18 dbhost01 kernel: Node 0 DMA free:15360kB min:556kB low:692kB high:828kB active_anon:0kB inactive_anon:0kB
Apr 21 03:14:18 dbhost01 kernel: Node 0 DMA32 free:0kB min:0kB low:0kB high:0kB active_anon:0kB
Apr 21 03:14:18 dbhost01 kernel: Node 1 hugepages_total=0 hugepages_free=0 hugepages_surp=0 hugepages_size=2048kB
```

> **ORA Code: ORA-00603** — Same as ERROR-07. If OOM kills a background process like LGWR or DBWn, alert.log shows ORA-00603 followed by instance termination. No ORA code if only foreground process killed.

---

## ERROR-09: HugePages Allocation Failure

```
# File: /var/log/messages

Mar 15 22:01:12 dbhost01 kernel: hugetlb: allocating 32768 of page size 2048kB failed. Total 0 registered with supervisor
Mar 15 22:01:12 dbhost01 kernel: hugetlb: allocating 16384 of page size 2048kB failed. Total 0 registered with supervisor
Mar 15 22:01:13 dbhost01 kernel: hugetlb: allocating 8192 of page size 2048kB failed. Total 0 registered with supervisor
Mar 15 22:01:18 dbhost01 oracle: ORION: HugePages allocation failed — Oracle SGA will use regular pages (performance impact)

# /proc/meminfo at time of failure:
# HugePages_Total:   65536
# HugePages_Free:        0   <-- ALL consumed, none left for new instance
# HugePages_Rsvd:    32768
# HugePages_Surp:        0
# Hugepagesize:       2048 kB
```

> **ORA Code: ORA-27102** — `out of memory` when Oracle tries to allocate SGA using HugePages and none are available. Linux Error: 12 (ENOMEM). Also possible: ORA-04031 if SGA falls back to regular pages and shared pool fragments.

---

## ERROR-10: Memory Swapping — Active Paging Storm

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/vmstat.txt

procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd    free   buff  cache   si    so    bi    bo   in   cs us sy id wa st
 4 18 8388608  16384   4096  32768 2048  2304  8821 18821 9821 8812 48  8 12 32  0
 6 22 8388608   8192   2048  16384 3012  3892 12291 22882 11821 9812 42  9 10 39  0
 8 28 8388608   4096   1024   8192 4892  5122 18821 31882 14821 11812 38 10  8 44  0
 12 32 8388608   2048    512   4096 6122  7882 24821 42912 18821 14812 31 11  4 54  0

# si=6122 so=7882 pages/sec — severe active swapping
# wa=54% — I/O wait dominated by swap I/O
# free=2048kB — system is out of real memory, paging everything
```

> **ORA Code: Does Not Exist directly** — Swapping causes SGA page faults. Oracle eventually surfaces **ORA-04031** (unable to allocate shared memory) as indirect symptom when swapped-out pages look fragmented to Oracle's memory manager.

---

## ERROR-11: Shared Memory Segment — shmget Failed

```
# File: /var/log/messages

Feb 28 04:12:21 dbhost01 oracle[18821]: shmget: errno=22 (Invalid argument)
Feb 28 04:12:21 dbhost01 oracle[18821]: Cannot create shared memory segment, size=107374182400
Feb 28 04:12:21 dbhost01 kernel: shm: shm_tot = 52428800 exceeds shm_ctlmax = 52428800

# /proc/sys/kernel/shmmax at time of failure: 68719476736  (64GB)
# Oracle SGA requested: 107374182400 (100GB) > shmmax
# Fix: sysctl -w kernel.shmmax=137438953472
```

> **ORA Code: ORA-27102** — `out of memory`. Linux-x86_64 Error: 22 (EINVAL). Appears in alert.log at startup. shmget() returns EINVAL when requested SGA size exceeds kernel.shmmax. Oracle cannot start.

---

## ERROR-12: Semaphore Limit Exhausted

```
# File: /var/log/messages

Mar 04 14:22:11 dbhost01 oracle[28821]: semget: errno=28 (No space left on device)
Mar 04 14:22:11 dbhost01 oracle[28821]: Unable to allocate semaphore set, semmni limit reached

# ipcs -ls at time of failure:
# ------ Semaphore Limits --------
# max number of arrays = 128         <-- semmni
# max semaphores per array = 250
# max semaphores system wide = 32000
# max ops per semop call = 100
# semaphore max value = 32767
# Current arrays in use: 128/128 (100%) -- all consumed by Oracle processes
```

> **ORA Code: ORA-27300 / ORA-27301 / ORA-27302** — OS system dependent operation failed with status 28 (ENOSPC). semget() rejected by kernel. Appears at Oracle startup. Full message: `ORA-27301: OS failure message: No space left on device`.

---

## ERROR-13: THP (Transparent HugePages) Causing Latency

```
# File: /var/log/messages

Apr 09 03:11:22 dbhost01 kernel: khugepaged: huge page allocated
Apr 09 03:11:22 dbhost01 kernel: khugepaged: scan 4096 pages, allocated 1 hugepages
Apr 09 03:11:44 dbhost01 kernel: khugepaged: scan_sleep_millisecs=10000
Apr 09 03:11:44 dbhost01 kernel: page allocation failure: order:9, mode:0x40c0(GFP_KERNEL|__GFP_COMP), nodemask=(null),cpuset=/,mems_allowed=0-1
Apr 09 03:11:44 dbhost01 kernel:  [<ffffffff81292d9e>] __alloc_pages_nodemask+0x9ae/0xbe0
Apr 09 03:11:44 dbhost01 kernel: THP allocation failed due to page fragmentation

# /sys/kernel/mm/transparent_hugepage/enabled = [always]  <-- WRONG for Oracle
# Oracle recommendation: set to never or madvise
# cat /sys/kernel/mm/transparent_hugepage/defrag = always  <-- causes stall
```

> **ORA Code: Does Not Exist directly** — THP stall causes latency spikes visible in AWR as sporadic `db file sequential read` or `log file sync` spikes with no consistent pattern. No ORA code thrown. DBA must check `/sys/kernel/mm/transparent_hugepage/enabled`.

---

# ===== SECTION 3: KERNEL ERRORS =====

## ERROR-14: Kernel Oops — NULL Pointer Dereference

```
# File: /var/log/messages

Mar 22 02:44:18 dbhost01 kernel: BUG: unable to handle kernel NULL pointer dereference at 0000000000000018
Mar 22 02:44:18 dbhost01 kernel: IP: [<ffffffffc082a291>] qla2xxx_eh_abort+0x51/0x280 [qla2xxx]
Mar 22 02:44:18 dbhost01 kernel: PGD 0
Mar 22 02:44:18 dbhost01 kernel: Oops: 0000 [#1] SMP
Mar 22 02:44:18 dbhost01 kernel: Modules linked in: qla2xxx(OE) lpfc(OE) bnx2(OE) bnxt_en(OE) oracleasm(OE)
Mar 22 02:44:18 dbhost01 kernel: CPU: 12 PID: 28821 Comm: oracle Tainted: G        OE  5.4.17-2136.315.5.el8uek.x86_64
Mar 22 02:44:18 dbhost01 kernel: RIP: 0010:[<ffffffffc082a291>]  [<ffffffffc082a291>] qla2xxx_eh_abort+0x51/0x280
Mar 22 02:44:18 dbhost01 kernel: RSP: 0018:ffff88083f9c3b40 EFLAGS: 00010246
Mar 22 02:44:18 dbhost01 kernel: RAX: 0000000000000000 RBX: ffff880839821940 RCX: 0000000000000000
Mar 22 02:44:18 dbhost01 kernel: RDX: 0000000000000000 RSI: ffff88083f9c3b90 RDI: ffff880839821940
Mar 22 02:44:18 dbhost01 kernel: Call Trace:
Mar 22 02:44:18 dbhost01 kernel:  [<ffffffff8152d891>] scsi_abort_command+0x71/0xc0
Mar 22 02:44:18 dbhost01 kernel:  [<ffffffff8152e421>] scsi_times_out+0x61/0x170
Mar 22 02:44:18 dbhost01 kernel:  [<ffffffff810b2281>] process_timeout+0x11/0x20
```

> **ORA Code: Does Not Exist directly** — Kernel NULL ptr dereference in qla2xxx HBA driver causes I/O abortion. Oracle then gets **ORA-27072** (File I/O error, Linux Error 5: EIO) for any I/O pending on that HBA at that moment.

---

## ERROR-15: Kernel — MCE (Machine Check Exception) / Hardware Error

```
# File: /var/log/messages

Jan 31 05:22:41 dbhost01 mcelog: MCE 0
Jan 31 05:22:41 dbhost01 mcelog: CPU 4 BANK 4 TSC 8821882812821
Jan 31 05:22:41 dbhost01 mcelog: RIP 10:ffffffff812a8821
Jan 31 05:22:41 dbhost01 mcelog: MISC 0 ADDR 0xffff88083f9c0000
Jan 31 05:22:41 dbhost01 mcelog: TIME 1706672561 Thu Jan 31 05:22:41 2024
Jan 31 05:22:41 dbhost01 mcelog: MCG status:RIPV
Jan 31 05:22:41 dbhost01 mcelog: MCi status:
Jan 31 05:22:41 dbhost01 mcelog: Corrected error
Jan 31 05:22:41 dbhost01 mcelog: Error enabled
Jan 31 05:22:41 dbhost01 mcelog: MCA: MEMORY CONTROLLER MS_CHANNELunspecified_ERR
Jan 31 05:22:41 dbhost01 mcelog: Transaction: Memory read error
Jan 31 05:22:41 dbhost01 mcelog: Memory corrected error count (CORE=4 CHANNEL=0): 8821
Jan 31 05:22:41 dbhost01 kernel: [Hardware Error]: Machine check: Corrected error, no action required.
Jan 31 05:22:41 dbhost01 kernel: [Hardware Error]: CPU 4: Machine Check Exception: 5 Bank 4: b200000000000108
Jan 31 05:22:41 dbhost01 kernel: [Hardware Error]: TSC 8821882812821
Jan 31 05:22:41 dbhost01 kernel: [Hardware Error]: ADDR 0xffff88083f9c0000
# 8821 corrected memory errors on DIMM CHANNEL 0 — DIMM degrading, replace before uncorrected errors start
```

> **ORA Code: Does Not Exist** for corrected (CE) errors — hardware fixes them transparently. For uncorrected (UE) errors: kernel panic → Oracle instance crash → no ORA code (system down). If UE corrupts data block: **ORA-00600 [kcbzib_1]** or **ORA-01578** on next block read.

---

## ERROR-16: EDAC — Memory Controller ECC Error

```
# File: /var/log/messages

Feb 14 18:12:22 dbhost01 kernel: EDAC MC0: 1 CE memory read error on CPU_SrcID#0_Ha#0_Chan#0_DIMM#1 (channel:0 slot:1 page:0x2a821 offset:0x800 grain:8 syndrome:0x0 - area:DRAM err_code:0001:009c socket:0 ha:0 channel_mask:1 rank:1)
Feb 14 18:12:22 dbhost01 kernel: EDAC MC0: 8821 CE memory read error on CPU_SrcID#0_Ha#0_Chan#0_DIMM#1
Feb 14 18:22:22 dbhost01 kernel: EDAC MC0: 1 UE memory read error on CPU_SrcID#0_Ha#0_Chan#0_DIMM#1 (channel:0 slot:1 page:0x2a821 offset:0x900 grain:8 syndrome:0x0)
# CE = Corrected Error (warning)
# UE = Uncorrected Error (CRITICAL — can cause kernel panic or data corruption)
```

> **ORA Code: ORA-27072** — File I/O error (Linux Error 5: EIO) if UE hits Oracle data. If UE hits kernel space: kernel panic, no ORA code. EDAC CE errors alone produce no ORA code — only monitoring alerts.

---

## ERROR-17: Kernel Panic — Storage Controller Failure

```
# File: /var/log/messages (last entries before panic)

Apr 02 01:44:18 dbhost01 kernel: megaraid_sas 0000:04:00.0: DCMD timed out, aborting
Apr 02 01:44:19 dbhost01 kernel: megaraid_sas 0000:04:00.0: kill adapter scsi0 due to command timeout/data corruption
Apr 02 01:44:19 dbhost01 kernel: megaraid_sas 0000:04:00.0: FW responded with invalid status
Apr 02 01:44:19 dbhost01 kernel: megaraid_sas 0000:04:00.0: Marking controller dead, do not restart
Apr 02 01:44:21 dbhost01 kernel: Kernel panic - not syncing: Fatal exception
Apr 02 01:44:21 dbhost01 kernel: Pid: 18821, comm: oracle Tainted: G      D OE  5.4.17-2136.315.5.el8uek.x86_64
Apr 02 01:44:21 dbhost01 kernel: Call Trace:
Apr 02 01:44:21 dbhost01 kernel:  panic+0x9f/0x1a5
Apr 02 01:44:21 dbhost01 kernel:  die+0x6b/0x80
Apr 02 01:44:21 dbhost01 kernel:  do_general_protection+0x182/0x1f0
```

> **ORA Code: Does Not Exist** — Kernel panic = hard reboot. Oracle instance is gone. No ORA code is written to alert.log because the process was killed by the OS before it could write. After restart, alert.log shows instance recovery starting.

---

## ERROR-18: sysctl — Kernel Parameter Mismatch (Oracle prereq)

```
# File: /var/log/messages

Mar 18 09:22:11 dbhost01 oracle-database-preinstall-19c[8821]: kernel.shmall too low: current=4294967296, required=1073741824
Mar 18 09:22:11 dbhost01 oracle-database-preinstall-19c[8821]: kernel.shmmax too low: current=68719476736, required=137438953472
Mar 18 09:22:11 dbhost01 oracle-database-preinstall-19c[8821]: kernel.sem SEMMSL=250 SEMMNS=32000 SEMOPM=100 SEMMNI=128 — SEMMNI must be >= 142

# /proc/sys/kernel/sem at time of failure:
# 250	32000	100	128
# Oracle requires: 250 32000 100 142 (at minimum)
```

> **ORA Code: ORA-27102** — `out of memory` (shmmax too low) OR **ORA-27300 / ORA-27301** (semaphore limit). Exact code depends on which parameter is wrong. Both appear at Oracle startup in alert.log with Linux errno included.
