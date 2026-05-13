# Oracle DBA Real Production Logs — Part 2
## CRS / Grid Infrastructure / ASM / RAC Logs

---

## 21. CRS-1605 — CSSD Daemon Restart (misscount exceeded)

```
2024-02-14 03:18:44.912 [cssd(3912)]CRS-1605:CSSD daemon restart.
2024-02-14 03:18:44.921 [cssd(3912)]CRS-1614:Aborting client OS pid 3991, client id:1782, client location: /u01/grid/bin/oraagent.bin
2024-02-14 03:18:44.935 [cssd(3912)]CRS-1614:Aborting client OS pid 4018, client id:1802, client location: /u01/grid/bin/orarootagent.bin
2024-02-14 03:18:45.019 [cssd(3912)]CRS-1601:CSSD Reconfiguration complete. Active nodes: node1 node2.
```

---

## 22. CRS-1618 — Node Eviction (network heartbeat lost)

```
2024-03-07 01:44:12.119 [cssd(3912)]CRS-1618:Node node2 is not responding to heartbeat. Will be evicted in approximately 27.130 seconds.
2024-03-07 01:44:39.249 [cssd(3912)]CRS-1632:Node node2 is not responding to Cluster Health Monitor heartbeat. CRS-1618 may follow.
2024-03-07 01:44:39.389 [cssd(3912)]CRS-1621:CSSD voting file read failed for disk number 1, voting file: '/dev/oracleasm/disks/VOTE01', error [6/0], detail [7: Bad network descriptor]
2024-03-07 01:44:39.401 [cssd(3912)]CRS-1656:The css daemon is exiting due to a fatal error; Details at (:CSSD00106:) in /u01/grid/log/node1/cssd/ocssd.log
```

---

## 23. CRS-2765 — Resource Failure and Restart

```
2024-01-29 08:22:33.412 [oraagent(4812)]CRS-2765:Resource 'ora.PROD.db' has become UNAVAILABLE on server 'node1'.
2024-01-29 08:22:33.812 [oraagent(4812)]CRS-5017:The resource action "ora.PROD.db start" encountered the following error:
ORA-01034: ORACLE not available
ORA-27101: shared memory realm does not exist
Linux-x86_64 Error: 2: No such file or directory
2024-01-29 08:22:34.021 [oraagent(4812)]CRS-2674:Start of 'ora.PROD.db' on 'node1' failed
```

---

## 24. CRS-1019 — Voting Disk Read Failure

```
2024-04-02 23:59:08.021 [cssd(3912)]CRS-1019:Cluster Ready Services daemon voting file I/O failed on disk /dev/oracleasm/disks/VOTE02
2024-04-02 23:59:08.022 [cssd(3912)]CRS-1019:Cluster Ready Services daemon voting file I/O failed on disk /dev/oracleasm/disks/VOTE03
2024-04-02 23:59:08.023 [cssd(3912)]CRS-1656:The css daemon is exiting due to a fatal error; Details at (:CSSD00106:) in /u01/grid/log/node1/cssd/ocssd.log
```

---

## 25. CRS-2307 — Cluster Database Cannot Start

```
2024-02-28 07:11:44.882 [orarootagent(5812)]CRS-2307:Could not start resource 'ora.DWHPROD.db' because a required resource 'ora.DATA.dg' failed to start.
2024-02-28 07:11:45.001 [orarootagent(5812)]CRS-5017:The resource action "ora.DATA.dg start" encountered the following error:
ORA-15032: not all alterations performed
ORA-15017: diskgroup "DATA" cannot be mounted
ORA-15040: diskgroup is incomplete
```

---

## 26. ASM ORA-15130 — Diskgroup Becoming Full

```
Thu Mar 14 17:55:22 2024
WARNING: Diskgroup DATA is 90% full.
Thu Mar 14 18:12:18 2024
ORA-15130: diskgroup "DATA" is being dismounted
Errors in file /u01/app/grid/diag/asm/+asm/+ASM1/trace/+ASM1_ora_18821.trc:
ORA-15130: diskgroup "DATA" is being dismounted
WARNING: Diskgroup DATA has no more free space for writing.
ORA-15041: diskgroup "DATA" space exhausted
```

---

## 27. ASM ORA-15080 — Synchronous I/O Failed

```
Mon Apr 15 02:22:41 2024
Errors in file /u01/app/grid/diag/asm/+asm/+ASM1/trace/+ASM1_ora_29912.trc:
ORA-15080: synchronous I/O request to a disk failed
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
Additional information: 4
Additional information: 1024
Additional information: 512
```

---

## 28. ORA-00445 — Background Process Died

```
Wed Jan 24 14:03:11 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_ora_8812.trc:
ORA-00445: background process "DBW0" did not start after 120 seconds
PMON failed to acquire latch, see PMON dump
```

---

## 29. ORA-00470 — LGWR Process Terminated

```
Tue Feb 06 22:09:44 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_lgwr_2012.trc:
ORA-00470: LGWR process terminated with error
LGWR: Error 470 encountred; archiving disabled
```

---

## 30. ORA-16038 / ORA-19504 / ORA-00312 — Log Write Error

```
Fri Mar 22 08:31:05 2024
LGWR: Error 16038 creating archive log file '/arch/PROD/arch_1_104821_1012847219.arc'
ORA-16038: log 2 sequence# 104821 cannot be archived
ORA-19504: failed to create file "/arch/PROD/arch_1_104821_1012847219.arc"
ORA-27040: file create error, unable to create file
Linux-x86_64 Error: 28: No space left on device
```

---

## 31. RAC — ORA-29740 (Instance Eviction)

```
Tue Apr 09 03:44:22 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD2/trace/PROD2_lmd0_18291.trc:
ORA-29740: evicted by member 1, group incarnation 8
LMDS: eviction requested for instance 2
Instance terminated by LMDT, pid = 18291
```

---

## 32. RAC — Block Transfer Timeout / GC Timeout

```
Wed Mar 06 11:22:09 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD1/trace/PROD1_lms0_10832.trc:
gc block lost
Dump of system resources acquired for current process (level=1):
  private strands               : 0
  ksllt  latch                  : 1
  kslatr latch                  : 1
  gc current block lost count   : 1
  gc cr block lost count        : 1
```

---

## 33. OS-Level — OOM Killer (from /var/log/messages)

```
Mar 21 03:14:22 dbhost01 kernel: oracle (pid 18821, task_comm_len 6) triggered OOM kill
Mar 21 03:14:22 dbhost01 kernel: Killed process 18821 (oracle) total-vm:134217728kB, anon-rss:131072000kB, file-rss:0kB, shmem-rss:0kB
Mar 21 03:14:22 dbhost01 kernel: oom_kill_process+0x2c2/0x4c0
Mar 21 03:14:22 dbhost01 kernel: Out of memory: Kill process 18821 (oracle) score 982 or sacrifice child
Mar 21 03:14:22 dbhost01 kernel: Mem-Info:
Mar 21 03:14:22 dbhost01 kernel: active_anon:31457280 inactive_anon:2097152 isolated_anon:0
Mar 21 03:14:22 dbhost01 kernel: active_file:131072 inactive_file:8192 isolated_file:0
Mar 21 03:14:22 dbhost01 kernel: unevictable:0 dirty:2048 writeback:4096 unstable:0
Mar 21 03:14:22 dbhost01 kernel: slab_reclaimable:892 slab_unreclaimable:14712
```

---

## 34. OS-Level — High I/O Wait (from iostat captured in AHF)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/iostat_output.txt
Device:         rrqm/s   wrqm/s     r/s     w/s    rkB/s    wkB/s avgrq-sz avgqu-sz   await r_await w_await  svctm  %util
sdb               0.00    12.00    0.00  892.00     0.00 114176.00   256.00   184.22  206.53    0.00  206.53   1.12  100.00
sdc               0.00     8.00    0.00  844.00     0.00 108032.00   256.00   192.18  227.81    0.00  227.81   1.18  100.00
sdd               0.00     0.00    0.00    0.00     0.00     0.00     0.00     0.00    0.00    0.00    0.00   0.00    0.00

# I/O wait above 200ms (sdb, sdc at 100% util) — DBA concern: storage bottleneck
```

---

## 35. OS-Level — CPU Saturation (from sar captured in AHF)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/sar_output.txt
03:00:01 AM     CPU     %user     %nice   %system   %iowait    %steal     %idle
03:10:01 AM     all     91.22      0.00      7.88      0.82      0.00      0.08
03:20:01 AM     all     98.77      0.00      1.19      0.02      0.00      0.02
03:30:01 AM     all     99.81      0.00      0.18      0.01      0.00      0.00
03:40:01 AM     all     97.92      0.00      2.01      0.07      0.00      0.00

# CPU idle near 0% for 30+ minutes — run queue buildup confirmed by vmstat
```

---

## 36. OS-Level — Swap Utilization (vmstat from AHF)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/vmstat_output.txt
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
12  4 8388608  49152  12288 131072  892 1024   892  2048 9821 8812 91  8  0  1  0
18  8 8388608  24576   8192  98304 1092 1288  1092  2888 12891 11204 93  7  0  0  0
22  6 8388608  12288   4096  65536 2048 2304  2048  4096 18821 17912 97  3  0  0  0

# si/so > 1000 pages/sec — active swapping, memory under severe pressure
```

---

## 37. OS-Level — Disk Full (/arch filesystem)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/df_output.txt
Filesystem              1K-blocks       Used Available Use% Mounted on
/dev/mapper/vg01-arch   107374182400 107374182400        0 100% /arch
/dev/mapper/vg01-data   536870912000 498075074560 38795837440   93% /data
/dev/mapper/vg01-u01     53687091200  50503065600  3184025600   95% /u01

# /arch at 100% — archiver will be stuck, ORA-00257 imminent
```

---

## 38. OS-Level — Network Packet Drops (netstat from AHF)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/netstat_output.txt
Kernel Interface table
Iface    MTU  RX-OK RX-ERR RX-DRP RX-OVR TX-OK TX-ERR TX-DRP TX-OVR Flg
bond0   9000 8821902    0      0      0  7812441      0      0      0 BMRU
eth0    9000 4412918    0      0      0  3912814      0      0      0 BMRU
eth1    9000 4408984    0      0      0  3899627      0      0      0 BMRU
ib0     2044 1288421  212    892     18   921882    412      8      2 BMRU

# ib0 (InfiniBand / RAC interconnect): RX-ERR=212, RX-DRP=892 — interconnect degraded
```

---

## 39. OS-Level — Kernel NFS Error (dmesg from AHF)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/dmesg_output.txt
[821843.281823] nfs: server nfsserver01 not responding, timed out
[821843.281841] nfs: server nfsserver01 not responding, still trying
[821901.338821] nfs: server nfsserver01 OK
[892341.228821] EXT4-fs error (device sdb1): ext4_find_entry:1455: inode #2: comm oracle: reading directory lblock 0
[892341.229002] EXT4-fs error (device sdb1): ext4_find_entry:1455: inode #2: comm oracle: reading directory lblock 1
```

---

## 40. OS-Level — NUMA Imbalance (numastat from AHF)

```
# From: /u01/app/oracle.ahf/data/repository/collection/node1/os/numastat_output.txt
                           node0           node1
numa_hit              8821902812      121892912
numa_miss               8821892       8219821
numa_foreign            8219821         8821892
internode_hit           9821012        8821012
local_node            8821782812      118912821
other_node              8821892       8219821

# node0 handles 98%+ of memory operations; node1 starved — NUMA imbalance
```
