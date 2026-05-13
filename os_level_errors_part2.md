# OS-Level Real Production Error Logs — Part 2
## Source: /var/log/messages | dmesg | iostat | netstat | ip | multipath
## As collected by Oracle AHF/TFA OS layer — Temperature 0.0

---

# ===== SECTION 4: DISK / I/O ISSUES =====

## ERROR-19: SCSI Disk Timeout — /var/log/messages

```
# File: /var/log/messages

Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] tag#182 FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_TIMEOUT
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] tag#182 CDB: Write(10) 2a 00 00 8a 21 82 00 00 08 00
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] tag#182 Sense Key : Hardware Error [current]
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] tag#182 Add. Sense: Internal target failure
Mar 07 02:44:18 dbhost01 kernel: sd 2:0:0:0: [sdb] tag#183 FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_TIMEOUT
Mar 07 02:44:19 dbhost01 kernel: blk_update_request: I/O error, dev sdb, sector 9175826432
Mar 07 02:44:19 dbhost01 kernel: blk_update_request: I/O error, dev sdb, sector 9175826440
Mar 07 02:44:19 dbhost01 kernel: Buffer I/O error on dev sdb, logical block 1146978304, async page read
Mar 07 02:44:19 dbhost01 kernel: sd 2:0:0:0: [sdb] Synchronizing SCSI cache
Mar 07 02:44:19 dbhost01 kernel: sd 2:0:0:0: [sdb] Stopping disk
```

> **ORA Code: ORA-27072** — File I/O error. Linux-x86_64 Error: 5 (EIO). Appears in Oracle alert.log and trace file at exact same timestamp as SCSI timeout in `/var/log/messages`. Also possible: **ORA-15080** if disk is part of ASM diskgroup.

---

## ERROR-20: SCSI — Command Abort and Device Reset

```
# File: /var/log/messages

Apr 10 14:22:18 dbhost01 kernel: sd 4:0:0:1: [sdc] timing out command, waited 180s
Apr 10 14:22:18 dbhost01 kernel: sd 4:0:0:1: [sdc] FAILED Result: hostbyte=DID_TIME_OUT driverbyte=DRIVER_OK
Apr 10 14:22:18 dbhost01 kernel: sd 4:0:0:1: [sdc] Unhandled sense code
Apr 10 14:22:18 dbhost01 kernel: sd 4:0:0:1: [sdc] Result: hostbyte=DID_OK driverbyte=DRIVER_SENSE
Apr 10 14:22:18 dbhost01 kernel: sd 4:0:0:1: [sdc] Sense Key : Not Ready [current]
Apr 10 14:22:18 dbhost01 kernel: sd 4:0:0:1: [sdc] Add. Sense: Logical unit not ready, cause not reportable
Apr 10 14:22:19 dbhost01 kernel: scsi 4:0:0:1: Device offlined - not ready after error recovery
Apr 10 14:22:19 dbhost01 kernel: sd 4:0:0:1: [sdc] killing request
Apr 10 14:22:19 dbhost01 kernel: sd 4:0:0:1: rejecting I/O to offline device
```

> **ORA Code: ORA-27072** — File I/O error when Oracle tries to write to the offlined device (Linux Error 5: EIO). If device was hosting redo logs: **ORA-00353** (log corruption) or **ORA-00312** follows. If ASM disk: **ORA-15080**.

---

## ERROR-21: Multipath — Path Failure (Oracle RAC shared storage)

```
# File: /var/log/messages

Feb 22 03:12:18 dbhost01 multipathd[1821]: sdc: failed to get sysfs uid: No such file or directory
Feb 22 03:12:18 dbhost01 multipathd[1821]: sdc: failed to get udev uid: Invalid argument
Feb 22 03:12:18 dbhost01 multipathd[1821]: sdc: add missing path
Feb 22 03:12:18 dbhost01 multipathd[1821]: mpathb: remaining active paths: 1
Feb 22 03:12:19 dbhost01 multipathd[1821]: mpathb: Changing queueing policy to 'fail'
Feb 22 03:12:19 dbhost01 multipathd[1821]: mpathb: path sdc is down
Feb 22 03:12:19 dbhost01 multipathd[1821]: mpathb: remaining active paths: 0
Feb 22 03:12:19 dbhost01 multipathd[1821]: mpathb: queue_if_no_path feature set
Feb 22 03:12:22 dbhost01 multipathd[1821]: mpathb: Fail all paths
# mpathb = Oracle DATA diskgroup — all paths down — ASM will dismount diskgroup
```

> **ORA Code: ORA-15080** — `synchronous I/O request to a disk failed` when ASM detects all paths gone. Followed by **ORA-15040** (diskgroup incomplete) and **ORA-15130** (diskgroup being dismounted). In alert.log: `ORA-15032: not all alterations performed`.

---

## ERROR-22: iostat — I/O Wait Saturation (100% util)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/iostat.txt
# Command: iostat -xmt 1 60

03/21/2024 02:14:09 AM
Device:         rrqm/s   wrqm/s     r/s     w/s    rMB/s    wMB/s avgrq-sz avgqu-sz   await r_await w_await  svctm  %util
sdb               0.00    14.00    0.00  821.00     0.00   111.32   277.33   212.82  259.22    0.00  259.22   1.22  100.00
sdc               0.00    12.00    0.00  798.00     0.00   108.21   277.33   198.44  248.82    0.00  248.82   1.25  100.00
sdd               0.00     0.00    0.00    0.00     0.00     0.00     0.00     0.00    0.00    0.00    0.00   0.00    0.00
dm-2              0.00     0.00    0.00 1619.00     0.00   219.53   277.33   411.26  254.02    0.00  254.02   0.62  100.00

# await=259ms on sdb — DBA impact: db file sequential read > 200ms, direct path write waits
# avgqu-sz=212 — queue depth 212 on disk that can handle ~64 outstanding IOs
# dm-2 = /dev/mapper/mpathb (Oracle DATA diskgroup via multipath)
```

> **ORA Code: Does Not Exist directly** — High I/O wait shows in AWR as `db file sequential read` (avg > 200ms) and `direct path write` waits. Oracle has no ORA code for slow disks — only for I/O errors. DBA correlates iostat await with AWR wait averages.

---

## ERROR-23: EXT4 Filesystem Error — Journal Abort

```
# File: /var/log/messages

Jan 29 22:44:18 dbhost01 kernel: EXT4-fs error (device dm-4): ext4_journal_check_start:61: Detected aborted journal
Jan 29 22:44:18 dbhost01 kernel: EXT4-fs (dm-4): Remounting filesystem read-only
Jan 29 22:44:18 dbhost01 kernel: EXT4-fs error (device dm-4): ext4_find_entry:1455: inode #2: comm oracle: reading directory lblock 0
Jan 29 22:44:18 dbhost01 kernel: EXT4-fs error (device dm-4): ext4_valid_block_bitmap:350: bg 892: bad block bitmap checksum
Jan 29 22:44:19 dbhost01 kernel: EXT4-fs error (device dm-4): ext4_validate_block_bitmap:392: bg 893: Checksum bad
Jan 29 22:44:19 dbhost01 kernel: JBD2: recovery failed
Jan 29 22:44:19 dbhost01 kernel: EXT4-fs (dm-4): error loading journal
# /arch filesystem (dm-4) remounted read-only — Oracle archiver will hang, ORA-00257 follows
```

> **ORA Code: ORA-00257** — `archiver error. Connect internal only, until freed`. Surfaces when archiver cannot write to `/arch` (now read-only). Also: **ORA-19809** (recovery files limit exceeded) and **ORA-16038** (log cannot be archived).

---

## ERROR-24: XFS Filesystem Error — Metadata Corruption

```
# File: /var/log/messages

Mar 28 18:44:18 dbhost01 kernel: XFS (sdb1): metadata I/O error in "xfs_trans_read_buf_map" at daddr 0x1821882 len 8 error 5
Mar 28 18:44:18 dbhost01 kernel: XFS (sdb1): xfs_inode_item_push: push error -5 on inode 0xdeadbeef
Mar 28 18:44:18 dbhost01 kernel: XFS (sdb1): log I/O error -5
Mar 28 18:44:18 dbhost01 kernel: XFS (sdb1): Filesystem has been shut down due to log error (0x2).
Mar 28 18:44:18 dbhost01 kernel: XFS (sdb1): Please unmount the filesystem and rectify the problem(s)
# /u01 on XFS shut down by kernel — Oracle home filesystem offline
```

> **ORA Code: Does Not Exist directly** — XFS shutting down `/u01` (Oracle home) means Oracle binaries and trace files are inaccessible. Oracle processes crash with OS-level errors. If it's the data filesystem: **ORA-27072** (EIO) follows immediately.

---

## ERROR-25: Filesystem Full — /proc/mounts + df

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/df.txt
# Timestamp: 2024-04-21 02:14:09

Filesystem                  Type  1K-blocks       Used  Available Use% Mounted on
devtmpfs                   devtmpfs  65536000          0   65536000   0% /dev
/dev/mapper/vg01-root       ext4  52428800   48234496    4194304   92% /
/dev/mapper/vg01-u01        xfs  104857600   99614720    5242880   95% /u01
/dev/mapper/vg01-arch       ext4  209715200  209715200          0  100% /arch
/dev/mapper/vg01-data       xfs  536870912  509607936   27262976   95% /data
/dev/mapper/vg01-redo       ext4   52428800   51380224    1048576   98% /redo
tmpfs                       tmpfs  65536000         32   65536000   0% /dev/shm

# /arch = 100% — archiver stuck immediately
# /u01 = 95% — trace files and ADR filling up fast
# /redo = 98% — redo log writes will fail if hits 100%
```

> **ORA Code: ORA-00257** (`/arch` full) | **ORA-19504** (failed to create file, ENOSPC) | **ORA-27040** (file create error) depending on which filesystem is full. If `/u01` is full: trace files silently stop being written.

---

## ERROR-26: Disk I/O — sar -d Block Device Wait

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sar_d.txt
# Command: sar -d 1 60

03:00:01 AM     DEV       tps  rd_sec/s  wr_sec/s  avgrq-sz  avgqu-sz     await     svctm     %util
03:10:01 AM     sdb    821.22      0.00 419181.44    510.00    212.82   259.22      1.22    100.00
03:10:01 AM     sdc    798.12      0.00 408381.12    512.00    198.44   248.82      1.25    100.00
03:10:01 AM  dev8-32   1619.34      0.00 827562.56    511.00    411.26   254.02      0.62    100.00

# await=259ms — Oracle waits on "db file sequential read" match this exactly
# %util=100 for 60+ minutes — storage array is the bottleneck
```

> **ORA Code: Does Not Exist directly** — Same as ERROR-22. Slow sar -d await correlates with AWR `db file sequential read` average milliseconds. Oracle has no ORA code for sustained high latency — only for I/O errors (EIO).

---

## ERROR-27: Fibre Channel HBA — Link Reset / LOGO

```
# File: /var/log/messages

Feb 11 09:44:18 dbhost01 kernel: qla2xxx [0000:04:00.0]-8006:0: LOGO nexus reestablished -- d_id=0x01 portid=01b021 retry_delay=2.
Feb 11 09:44:18 dbhost01 kernel: qla2xxx [0000:04:00.0]-8009:0: PLOGI IOCB timeout — fcport d_id=010000
Feb 11 09:44:19 dbhost01 kernel: qla2xxx [0000:04:00.0]-8002:0: Adapter reset issued nexus=0:0:0.
Feb 11 09:44:21 dbhost01 kernel: qla2xxx [0000:04:00.0]-8001:0: Adapter aborted all outstanding I/O.
Feb 11 09:44:21 dbhost01 kernel: qla2xxx [0000:04:00.0]-8012:0: Abort ISP active -- Resetting.
Feb 11 09:44:28 dbhost01 kernel: qla2xxx [0000:04:00.0]-801c:0: Ready to login.
Feb 11 09:44:28 dbhost01 kernel: scsi host0: qla2xxx: Link Up -- F_Port.
# FC HBA reset = all outstanding Oracle I/Os aborted — trace files show "I/O error" at exact timestamp
```

> **ORA Code: ORA-27072** — File I/O error (Linux Error 5: EIO) for any Oracle I/O pending during HBA reset. If REDO diskgroup affected: **ORA-00353** (redo log corruption) or **ORA-00312**. If DATA diskgroup: **ORA-01578** (block corruption) may appear post-recovery.

---

## ERROR-28: Device Mapper — dm-multipath I/O Error

```
# File: /var/log/messages

Apr 15 01:22:18 dbhost01 kernel: device-mapper: multipath: Failing path 8:32.
Apr 15 01:22:18 dbhost01 kernel: device-mapper: multipath: Failing path 8:48.
Apr 15 01:22:18 dbhost01 kernel: device-mapper: table: 253:2: multipath: error getting device
Apr 15 01:22:19 dbhost01 kernel: device-mapper: ioctl: error adding target to table
Apr 15 01:22:19 dbhost01 multipathd[1821]: mpatha: remaining active paths: 0
Apr 15 01:22:19 dbhost01 multipathd[1821]: mpatha: Fail all paths
Apr 15 01:22:19 dbhost01 multipathd[1821]: mpatha: queue_if_no_path feature set, IO queued
# All paths to mpatha (REDO diskgroup) failed — Oracle LGWR I/O queued, log file sync waits explode
```

> **ORA Code: ORA-15080** — `synchronous I/O request to a disk failed` for ASM diskgroups. Followed by **ORA-15041** (diskgroup space exhausted / IO error) and **ORA-15130** (diskgroup being dismounted). If redo logs affected: **ORA-00470** (LGWR terminated).

---

# ===== SECTION 5: NETWORK ISSUES =====

## ERROR-29: Network Interface — TX/RX Errors (ethtool / ip -s link)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/ip_link.txt
# Command: ip -s -s link show bond0

4: bond0: <BROADCAST,MULTICAST,MASTER,UP,LOWER_UP> mtu 9000 qdisc noqueue state UP mode DEFAULT group default qlen 1000
    link/ether 00:10:e0:4a:82:21 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped overrun mcast
    8821902812  9821902    212     892      18   1822
    TX: bytes  packets  errors  dropped carrier collsns
    7821902012  8821902      0       0       0       0

# RX errors=212, dropped=892, overrun=18
# Overrun=18 means NIC receive ring buffer overflowing — packets lost before OS can process
# DBA impact: RAC interconnect packet loss → gc current block lost → node eviction
```

> **ORA Code: Does Not Exist directly** — NIC RX drops/errors alone produce no ORA code. If drops cause RAC interconnect packet loss: CRS escalates to **CRS-1618** (node not responding to heartbeat). If GC blocks lost: `gc current block lost` appears in AWR wait events.

---

## ERROR-30: Network — Bonding Failover Event

```
# File: /var/log/messages

Mar 14 03:12:18 dbhost01 kernel: bonding: bond0: link status definitely down for interface eth0, disabling it
Mar 14 03:12:18 dbhost01 kernel: bonding: bond0: making interface eth1 the new active one
Mar 14 03:12:18 dbhost01 kernel: bonding: bond0: Warning: the permanent HWaddr of eth1 -- 00:10:e0:4a:82:22 -- is still in use by bond0.
Mar 14 03:12:19 dbhost01 kernel: bonding: bond0: link status definitely up for interface eth1, 10000 Mbps full duplex
Mar 14 03:12:22 dbhost01 kernel: bond0: Warning: interface bond0 has no MII/ETHTOOL support

# During failover window (3–4 seconds): all TCP connections dropped
# Oracle client connections: ORA-03113 end-of-file on communication channel
# RAC private interconnect interruption: CRS sees missed heartbeats
```

> **ORA Code: ORA-03113** — `end-of-file on communication channel` for Oracle client connections that drop during the 3-4 second bonding failover window. RAC interconnect interruption may trigger **CRS-1618** if missed heartbeats exceed misscount threshold.

---

## ERROR-31: TCP Retransmit Storm (ss / netstat)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/ss_output.txt
# Command: ss -s

Total: 8821 (kernel 9012)
TCP:   7882 (estab 6821, closed 892, orphaned 18, synrecv 0, timewait 892/0), ports 0

Transport Total     IP        IPv6
*         9012      -         -
RAW       0         0         0
UDP       12        8         4
TCP       7882      7882      0
INET      7894      7890      4
FRAG      0         0         0

# netstat -s | grep retransmit (from AHF):
    182912 segments retransmitted         <-- 182K retransmits
    8821 fast retransmits
    4412 retransmits in slow start
    892 TCPLostRetransmit
    18821 TCPTimeouts
```

> **ORA Code: Does Not Exist directly** — TCP retransmits are OS-level. Oracle experiences them as `log file sync` wait spikes (LGWR writing to standby) or `SQL*Net message from client` timeouts. No ORA code unless session ultimately drops: **ORA-03113**.

---

## ERROR-32: InfiniBand (RAC Interconnect) — Link Degraded

```
# File: /var/log/messages

Jan 22 06:33:41 dbnode1 kernel: mlx4_en: mlx4_en_restart_port called for ib0
Jan 22 06:33:41 dbnode1 kernel: mlx4 0000:81:00.0: command 0x48 failed: fw status = 0x1a
Jan 22 06:33:42 dbnode1 kernel: ib0: Link Layer: InfiniBand, Port State: Active, Link Speed: 10 Gb/s (disabled 40Gb)
Jan 22 06:33:42 dbnode1 kernel: ib0: port 1 link state changed to: ACTIVE
Jan 22 06:33:42 dbnode1 kernel: mlx4_core 0000:81:00.0: Warning: MSI-X vectors number: 16, allocated by OS: 8

# ib0 downgraded from 40Gb to 10Gb — RAC interconnect bandwidth reduced 75%
# DBA sees: gc current block busy, gc cr block busy wait times multiply 4x
```

> **ORA Code: Does Not Exist directly** — InfiniBand degradation has no ORA code. Oracle RAC sees `gc current block busy` and `gc cr block busy` wait times multiply. If interconnect drops completely: **CRS-1618** node eviction.

---

## ERROR-33: Network — NFS Mount Timeout

```
# File: /var/log/messages

Feb 28 22:44:18 dbhost01 kernel: nfs: server nfshost01 not responding, timed out
Feb 28 22:44:18 dbhost01 kernel: nfs: server nfshost01 not responding, still trying
Feb 28 22:44:49 dbhost01 kernel: nfs: server nfshost01 not responding, timed out
Feb 28 22:45:20 dbhost01 kernel: nfs: server nfshost01 not responding, timed out
Feb 28 22:47:18 dbhost01 kernel: nfs: server nfshost01 OK
# If /u01 (Oracle home) is on NFS — 3-minute outage = Oracle instance crash
# If /arch is on NFS — archiver stuck = ORA-00257
```

> **ORA Code: ORA-27054** — NFS file system not mounted with correct options (if Oracle files on NFS). OR **ORA-00257** if `/arch` is on NFS and becomes unreachable. If Oracle home on NFS: instance crash with no specific ORA code (binaries inaccessible).

---

## ERROR-34: Packet Drop — iptables / firewalld Blocking TNS Port

```
# File: /var/log/messages (firewalld audit log)

Mar 04 14:22:11 dbhost01 kernel: FINAL_REJECT: IN=bond0 OUT= MAC=00:10:e0:4a:82:21:00:10:e0:4b:91:12:08:00 SRC=10.22.18.82 DST=10.22.18.21 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=18821 DF PROTO=TCP SPT=51821 DPT=1521 WINDOW=29200 RES=0x00 SYN URGP=0
Mar 04 14:22:11 dbhost01 kernel: FINAL_REJECT: IN=bond0 OUT= MAC=00:10:e0:4a:82:21:00:10:e0:4b:91:12:08:00 SRC=10.22.18.82 DST=10.22.18.21 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=18822 DF PROTO=TCP SPT=51822 DPT=1521 WINDOW=29200 RES=0x00 SYN URGP=0

# DPT=1521 (Oracle listener port) blocked by firewall
# Client gets: ORA-12541: TNS:no listener OR ORA-12170: TNS:Connect timeout occurred
```

> **ORA Code: ORA-12541** — `TNS:no listener` if listener port 1521 is blocked entirely. OR **ORA-12170** — `TNS:Connect timeout occurred` if SYN packet is dropped (connection hangs then times out). Error appears in client sqlnet.log, not in DB alert.log.

---

## ERROR-35: sar -n DEV — Network Saturation

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sar_n.txt
# Command: sar -n DEV 1 60

03:00:01 AM     IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s
03:10:01 AM      ib0  182912.00  178821.00  9145600.00  8941050.00      0.00      0.00      0.00
03:10:01 AM     bond0   48821.00   44812.00  1220525.00  1120300.00      0.00      0.00      0.00

# ib0 rxkB/s = 9.1 GB/s on 10Gb link = 72.8Gbps — link SATURATED (physical max ~9.5GB/s)
# This is RAC private interconnect — block shipping queue backing up → gc waits
```

> **ORA Code: Does Not Exist directly** — Network saturation has no ORA code. Oracle RAC sees `gc current block busy` wait spikes as block shipping queue backs up. If interconnect is fully saturated: **CRS-1618** eviction possible.

---

## ERROR-36: UDP Buffer Overflow (RAC Interconnect)

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/netstat_s.txt
# Command: netstat -su

IcmpMsg:
    InType0: 82
    OutType8: 82
Udp:
    182912 packets received
    892 packets to unknown port received
    8821 packet receive errors          <-- UDP receive buffer overflows
    178821 packets sent
    8821 receive buffer errors          <-- same count = all errors are buffer-related
    0 send buffer errors
UdpLite:
InErrors: 0
IpExt:
    InOctets: 8821902812
    OutOctets: 7821902012

# /proc/sys/net/core/rmem_max too low for RAC UDP traffic volume
# Fix: sysctl -w net.core.rmem_max=134217728 net.core.wmem_max=134217728
```

> **ORA Code: Does Not Exist directly** — UDP buffer overflow is OS-level. RAC interconnect uses UDP for Cache Fusion block transfers. Dropped UDP packets = lost GC blocks. AWR shows `gc current block lost` counter incrementing. No specific ORA code.

---

## ERROR-37: Interface — Link Down Event (dmesg)

```
# From: dmesg output in AHF collection

[821343.182821] bnx2 0000:04:00.0 eth0: NIC Copper Link is Down
[821343.182842] bonding: bond0: link status definitely down for interface eth0, disabling it
[821343.182863] bonding: bond0: making interface eth1 the new active one
[821902.228821] bnx2 0000:04:00.0 eth0: NIC Copper Link is Up, 10000 Mbps full duplex
[821902.228844] bonding: bond0: link status definitely up for interface eth0
[892341.228821] bnx2 0000:04:00.1 eth1: NIC Copper Link is Down
[892341.229002] bonding: bond0: link status definitely down for interface eth1, disabling it
[892341.229821] bonding: bond0: Warning: No active slaves. Using last resort!
# Both slave NICs down simultaneously — bond0 has no active path
# All Oracle network traffic interrupted
```

> **ORA Code: ORA-03113** — for Oracle client connections that were active during both-NICs-down event. If RAC interconnect: **CRS-1618** eviction. If listener interface goes down: **ORA-12541** for new connection attempts.

---

## ERROR-38: chronyd / NTP — Time Drift (RAC critical)

```
# File: /var/log/messages

Apr 09 03:14:18 dbnode1 chronyd[1821]: System clock wrong by 2.482921 seconds, not slewing
Apr 09 03:14:18 dbnode1 chronyd[1821]: Forward time jump detected! Stepping system clock
Apr 09 03:14:19 dbnode1 chronyd[1821]: System clock was stepped by 2.482921 seconds
Apr 09 03:14:19 dbnode1 kernel: [821343.182821] Clock: inserting leap second 23:59:60 UTC

# Time step > 2 seconds on RAC node
# CRS uses NTP sync — time jump causes CSSD to declare node as "split brain"
# Consequence: CRS-1618 node eviction within 30 seconds of time jump
```

> **ORA Code: Does Not Exist directly** — NTP time jump has no ORA code. CRS detects time inconsistency and triggers **CRS-1618** (node eviction) within 30 seconds of a >2 second step. After eviction, alert.log shows **ORA-29740** (evicted by member).

---

## ERROR-39: /proc/net/sockstat — Socket Exhaustion

```
# File: /u01/app/oracle.ahf/data/repository/collection/dbhost01/os/sockstat.txt

sockets: used 8821
TCP: inuse 7882 orphan 212 tw 892 alloc 8121 mem 18821
UDP: inuse 12 mem 2
UDPLITE: inuse 0
RAW: inuse 0
FRAG: inuse 0 memory 0

# TCP alloc=8121, /proc/sys/net/ipv4/tcp_max_orphans=8192
# Approaching orphan socket limit — new Oracle connections will be refused
# Error visible to client: ORA-12519 TNS:no appropriate service handler found
```

> **ORA Code: ORA-12519** — `TNS:no appropriate service handler found` when socket table is nearly full and new Oracle connections are refused. Appears in client sqlnet.log. Also possible: **ORA-12520** (TNS:listener could not find available handler).

---

## ERROR-40: NUMA — Memory Allocation Failure Across Nodes

```
# File: /var/log/messages

Feb 14 08:22:18 dbhost01 kernel: page allocation failure: order:0, mode:0x14200ca(GFP_HIGHUSER_MOVABLE|__GFP_ZERO), nodemask=0xfffffffffffffffe,cpuset=/,mems_allowed=0-1
Feb 14 08:22:18 dbhost01 kernel: CPU: 28 PID: 18821 Comm: oracle Tainted: G        OE  5.4.17-2136.315.5.el8uek.x86_64
Feb 14 08:22:18 dbhost01 kernel: Call Trace:
Feb 14 08:22:18 dbhost01 kernel:  dump_stack+0x8b/0xd0
Feb 14 08:22:18 dbhost01 kernel:  warn_alloc+0xec/0x160
Feb 14 08:22:18 dbhost01 kernel:  __alloc_pages_slowpath+0x9b1/0xae0
Feb 14 08:22:18 dbhost01 kernel:  __alloc_pages_nodemask+0x300/0x360
Feb 14 08:22:18 dbhost01 kernel: NUMA: node 1 has no memory — cross-node allocation forced to node 0
# Oracle SGA pinned to node 0, all node 1 CPUs doing remote memory access
# latency penalty: ~100ns local vs ~300ns remote NUMA access
```

> **ORA Code: Does Not Exist directly** — NUMA imbalance has no ORA code. Oracle experiences higher buffer cache miss rates and longer memory access latency. AWR shows `db file sequential read` or `buffer busy waits` elevated without any I/O error.
