# Tier 1 Missing OS Errors — Real Log Samples
## 12 Critical OS Errors DBAs Hit Every Day
## Temperature: 0.0 | Source: Real production patterns

---

## TIER1-01: aio-max-nr Limit Hit — Oracle Async I/O Rejected

**OS Error (no ORA code at OS level):**
```
# /proc/sys/fs/aio-nr vs aio-max-nr — checked by AHF OS collection

# cat /proc/sys/fs/aio-nr
1048576

# cat /proc/sys/fs/aio-max-nr
1048576

# aio-nr = aio-max-nr — LIMIT REACHED. New async I/O requests will get EAGAIN.
```

**Kernel message in /var/log/messages:**
```
Apr 21 03:14:18 dbhost01 kernel: aio: aio_nr (1048576) is higher than aio_max_nr (1048576), io_setup will fail
Apr 21 03:14:18 dbhost01 kernel: aio: alloc_ioctx: pid=28821 aio_nr exceeded aio_max_nr
```

**ORA code that appears in Oracle alert.log (consequence):**
```
Tue Apr 21 03:14:19 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_dbw0_1821.trc:
ORA-27072: File I/O error
Linux-x86_64 Error: 11: Resource temporarily unavailable
Additional information: 4
Additional information: 0
Additional information: 0
# errno=11 = EAGAIN = aio-max-nr exhausted
```

**DBA Fix:**
```bash
# Check current values
cat /proc/sys/fs/aio-nr        # currently used
cat /proc/sys/fs/aio-max-nr    # current limit

# Increase (requires root)
sysctl -w fs.aio-max-nr=3145728
echo "fs.aio-max-nr = 3145728" >> /etc/sysctl.conf
```

---

## TIER1-02: CPU Governor = powersave — Oracle Running at Reduced Clock

**OS Error (no ORA code — silent performance kill):**
```
# From AHF OS collection: /u01/app/oracle.ahf/.../os/cpuinfo.txt

# cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
powersave

# cpupower frequency-info (from AHF)
analyzing CPU 0:
  driver: intel_pstate
  CPUs which run at the same hardware frequency: 0
  CPUs which need to have their frequency coordinated by software: 0
  maximum transition latency:  Cannot determine or is not supported.
  hardware limits: 1200 MHz - 3800 MHz
  available cpufreq governors: performance powersave
  current policy: frequency should be within 1200 MHz and 1200 MHz
                  The governor "powersave" may decide which speed to use
  current CPU frequency: 1200 MHz (asserted by call to hardware)
  boost state support:
    Supported: yes
    Active: no
    3800 MHz max turbo 4 active cores

# CPU pinned at 1.2GHz — should be 3.8GHz
# Oracle parallel query that takes 10s will take 31s
```

**AWR symptom (no single dominant wait, everything slow):**
```
Top 5 Timed Foreground Events (AWR — 1 hour interval)
Event                          Waits    Time(s)  Avg(ms) % DB time
db file sequential read       18821     48221     2562     52.1
CPU time                       —        28812      —       31.1
log file sync                  8821     12882     1460     13.9
# db file sequential read avg 2562ms on SSD — impossible unless CPU is slow processing
# CPU time is 31% but elapsed >> CPU — CPU frequency is the bottleneck
```

**DBA Fix:**
```bash
tuned-adm profile throughput-performance
# OR
cpupower frequency-set -g performance
# OR (persistent)
echo "governor=performance" > /etc/sysconfig/cpupower
systemctl restart cpupower
```

---

## TIER1-03: vm.swappiness=60 — Oracle SGA Being Paged Out

**OS state (from AHF collection):**
```
# cat /proc/sys/vm/swappiness
60
# Default Linux value — Oracle recommendation is 10 or less

# vmstat 1 5 (from AHF)
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 8  2 2097152 131072  16384 524288   82   48   892  2048 8821 7812 72  8 18  2  0
 6  4 2097152 114688  16384 491520  112   64  1092  2888 9821 8812 74  7 17  2  0
 4  2 2097152  98304  16384 458752  144   88  1228  3222 10821 9112 76  6 16  2  0

# si=144 so=88 — Oracle SGA pages being swapped in/out
# swpd=2097152 (2GB active swap) — SGA memory paged to disk
```

**No ORA code directly — but causes ORA-04031 indirectly:**
```
# When swapped-out SGA page is accessed:
Thu Mar 21 03:14:09 2024
ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","SELECT ...","sga heap(3,0)","KGLH0")
# Root cause: shared pool page was swapped out, looked like fragmentation
```

**DBA Fix:**
```bash
# Check current
sysctl vm.swappiness

# Set for Oracle
sysctl -w vm.swappiness=10
echo "vm.swappiness = 10" >> /etc/sysctl.conf

# Also lock SGA pages — prevents swapping entirely
# In Oracle: ALTER SYSTEM SET LOCK_SGA=TRUE SCOPE=SPFILE;
```

---

## TIER1-04: /dev/shm Too Small — Oracle SGA Startup Fails

**OS Error:**
```
# df -h /dev/shm (from AHF)
Filesystem      Size  Used Avail Use% Mounted on
tmpfs            16G   15G  1.0G 94% /dev/shm

# /etc/fstab entry (wrong):
tmpfs  /dev/shm  tmpfs  defaults  0 0
# No size= parameter — defaults to 50% of RAM = 16GB
# Oracle SGA configured for 96GB — cannot fit in /dev/shm
```

**ORA code in alert.log:**
```
Mon Feb 19 04:12:21 2024
ORA-27102: out of memory
Linux-x86_64 Error: 28: No space left on device
Additional information: 1
Additional information: 103079215104   <- SGA size requested (96GB)
Additional information: 1073741824     <- /dev/shm available (1GB)
Additional information: -1
```

**/var/log/messages at same time:**
```
Feb 19 04:12:21 dbhost01 oracle[18821]: shmget(key=0x..., size=103079215104, 03600) failed: errno = 28 (ENOSPC)
Feb 19 04:12:21 dbhost01 oracle[18821]: Cannot create SGA segment: No space left on device (/dev/shm)
```

**DBA Fix:**
```bash
# Check
df -h /dev/shm
cat /proc/mounts | grep shm

# Resize (no reboot needed)
mount -o remount,size=128G /dev/shm

# Persistent in /etc/fstab:
tmpfs  /dev/shm  tmpfs  defaults,size=128G  0 0
```

---

## TIER1-05: memlock ulimit Too Low — SGA Cannot Be Locked

**OS Error:**
```
# ulimit -l for oracle user (from AHF)
# ulimit -l
65536
# Value is in KB = 64MB. Oracle SGA = 96GB. Cannot lock SGA.

# /etc/security/limits.conf (wrong entry):
oracle   soft   memlock   65536
oracle   hard   memlock   65536
# Should be: unlimited (or >= SGA size in KB)
```

**ORA code in alert.log:**
```
Mon Mar 04 14:22:11 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_ora_18821.trc:
ORA-27125: unable to create shared memory segment
Linux-x86_64 Error: 1: Operation not permitted
Additional information: 1152
# errno=1 (EPERM) on mlock() syscall — OS refused to lock SGA pages
```

**/var/log/messages:**
```
Mar 04 14:22:11 dbhost01 oradism[18821]: ORADISM: mlock failed with errno=1 (EPERM)
Mar 04 14:22:11 dbhost01 oradism[18821]: Cannot lock SGA: Operation not permitted
Mar 04 14:22:11 dbhost01 oradism[18821]: SGA will not be memory-locked (performance impact)
```

**DBA Fix:**
```bash
# /etc/security/limits.conf
oracle   soft   memlock   unlimited
oracle   hard   memlock   unlimited

# Verify after re-login as oracle:
ulimit -l
# Should show: unlimited
```

---

## TIER1-06: SELinux Enforcing — Oracle Binary/File Access Blocked

**OS Error (in /var/log/audit/audit.log):**
```
# From AHF OS collection: audit.log

type=AVC msg=audit(1713894138.821:18821): avc: denied { read } for pid=28821 comm="oracle"
name="prod_ora_28821.trc" dev="dm-4" ino=8821882
scontext=system_u:system_r:oracle_db_t:s0
tcontext=unconfined_u:object_r:var_t:s0
tclass=file permissive=0

type=AVC msg=audit(1713894138.822:18822): avc: denied { write } for pid=28821 comm="oracle"
name="alert_prod.log" dev="dm-4" ino=9821882
scontext=system_u:system_r:oracle_db_t:s0
tcontext=system_u:object_r:var_log_t:s0
tclass=file permissive=0

type=AVC msg=audit(1713894138.823:18823): avc: denied { connectto } for pid=28821 comm="tnslsnr"
path="/var/run/oracle/listener.sock"
scontext=system_u:system_r:oracle_db_t:s0
tcontext=system_u:system_r:init_t:s0
tclass=unix_stream_socket permissive=0
```

**ORA codes surfaced:**
```
Mon Apr 22 18:22:18 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_ora_28821.trc:
ORA-27300: OS system dependent operation: open failed with status: 13
ORA-27301: OS failure message: Permission denied
ORA-27302: failure occurred at: sskgfcre
# errno=13 = EACCES = SELinux denied the file open
```

**DBA Fix:**
```bash
# Check SELinux status
getenforce
# Output: Enforcing  <-- problem

# Temporary disable (not recommended for prod)
setenforce 0

# Proper fix: create SELinux policy for Oracle
ausearch -c oracle --raw | audit2allow -M oracle_policy
semodule -i oracle_policy.pp

# Or set correct context on Oracle files:
chcon -R -t oracle_db_t /u01/app/oracle/
restorecon -Rv /u01/app/oracle/
```

---

## TIER1-07: systemd Overriding limits.conf — Oracle ulimits Ignored

**OS Error (very common post-RHEL7, most DBAs miss this):**
```
# DBA sets limits.conf correctly:
# /etc/security/limits.conf
oracle   soft   nofile   65536
oracle   hard   nofile   65536
oracle   soft   nproc    16384
oracle   hard   nproc    16384

# But Oracle process still shows wrong limits:
# cat /proc/28821/limits
Limit                     Soft Limit   Hard Limit   Units
Max open files            1024         4096         files  <- WRONG, should be 65536
Max processes             3818         3818         processes <- WRONG

# WHY: systemd overrides pam limits for services
# systemctl show oracle-ohasd.service | grep -i limit
LimitNOFILE=1024      <- systemd default overrides limits.conf
LimitNPROC=3818       <- systemd default overrides limits.conf
```

**/var/log/messages showing consequence:**
```
Apr 18 14:22:18 dbhost01 oracle[28821]: error: open: Too many open files (errno: 24)
Apr 18 14:22:18 dbhost01 oracle[28821]: Could not open trace file: Too many open files
```

**ORA code in alert.log:**
```
Mon Apr 18 14:22:19 2024
ORA-27054: NFS file system where the file is created or resides is not mounted with correct options
# OR:
Errors in file /u01/app/oracle/.../trace/PROD_ora_28821.trc:
ORA-27300: OS system dependent operation: open failed with status: 24
ORA-27301: OS failure message: Too many open files
ORA-27302: failure occurred at: sskgfcre
```

**DBA Fix:**
```bash
# Edit oracle-ohasd.service:
systemctl edit oracle-ohasd.service
# Add under [Service]:
[Service]
LimitNOFILE=65536
LimitNPROC=16384
LimitMEMLOCK=infinity

systemctl daemon-reload
systemctl restart oracle-ohasd
```

---

## TIER1-08: nf_conntrack Table Full — Oracle Connections Silently Dropped

**OS Error in /var/log/messages:**
```
Mar 14 03:12:18 dbhost01 kernel: nf_conntrack: nf_conntrack: table full, dropping packet
Mar 14 03:12:18 dbhost01 kernel: nf_conntrack: nf_conntrack: table full, dropping packet
Mar 14 03:12:18 dbhost01 kernel: nf_conntrack: nf_conntrack: table full, dropping packet
Mar 14 03:12:19 dbhost01 kernel: nf_conntrack: nf_conntrack: table full, dropping packet
# Thousands of these per second during peak connection load

# sysctl net.nf_conntrack_max
net.nf_conntrack_max = 65536

# cat /proc/sys/net/netfilter/nf_conntrack_count
65536
# AT LIMIT — all new connections dropped by kernel silently
```

**No ORA code on DB side — client sees:**
```
# sqlnet.log on application server:
Fatal NI connect error 12170.
  TNS-12535: TNS:operation timed out
  TNS-12560: TNS:protocol adapter error
  TNS-00505: Operation timed out
# Client gets ORA-12170 or ORA-03113 — DB never logged anything
```

**DBA Fix:**
```bash
# Increase conntrack limit
sysctl -w net.nf_conntrack_max=524288
sysctl -w net.netfilter.nf_conntrack_max=524288
echo "net.nf_conntrack_max = 524288" >> /etc/sysctl.conf

# Or disable conntrack for Oracle port (if firewalld allows):
iptables -t raw -A PREROUTING -p tcp --dport 1521 -j NOTRACK
iptables -t raw -A OUTPUT -p tcp --sport 1521 -j NOTRACK
```

---

## TIER1-09: MTU Mismatch — RAC Interconnect Fragmentation

**OS Error (no ORA code — silent RAC performance kill):**
```
# ip link show bond0 (from AHF node1)
4: bond0: <BROADCAST,MULTICAST,MASTER,UP,LOWER_UP> mtu 1500 ...

# ip link show bond0 (from AHF node2)
4: bond0: <BROADCAST,MULTICAST,MASTER,UP,LOWER_UP> mtu 9000 ...

# MTU MISMATCH between node1 (1500) and node2 (9000)

# Fragmentation test (from AHF):
ping -M do -s 8972 -c 5 192.168.10.12
PING 192.168.10.12 (192.168.10.12) 8972(9000) bytes of data.
ping: local error: Message too long, mtu=1500
# Cannot send 9000-byte packets — Oracle block shipping truncated
```

**dmesg showing fragmentation:**
```
[821343.182821] bond0: error -90 sending ICMP message to 192.168.10.12: probably loopback problem
[821343.182842] net_ratelimit: 182 callbacks suppressed
[821343.182863] bond0: NETDEV WATCHDOG: bond0 (bonding): transmit queue 0 timed out
```

**AWR symptom (no direct ORA code):**
```
Top 5 Timed Foreground Events
gc current block busy     48821    98212    2011ms    41.2%    Cluster
gc cr block busy          28821    71882    2494ms    30.1%    Cluster
# gc waits 2000ms+ when they should be <1ms on local interconnect
# Root cause: every Oracle block transfer being fragmented by MTU mismatch
```

**DBA Fix:**
```bash
# Set jumbo frames consistently on ALL nodes
ip link set bond0 mtu 9000
# Switch ports must also support jumbo frames

# Persistent:
# /etc/sysconfig/network-scripts/ifcfg-bond0
MTU=9000

# Verify end-to-end:
ping -M do -s 8972 <other_node_ip>  # must succeed
```

---

## TIER1-10: tuned Profile = balanced — All Oracle Settings Wrong

**OS Error (no ORA code — baseline performance degraded):**
```
# tuned-adm active (from AHF OS collection)
Current active profile: balanced

# What 'balanced' sets that hurts Oracle:
# /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor = powersave
# /sys/kernel/mm/transparent_hugepage/enabled = [always]
# /sys/kernel/mm/transparent_hugepage/defrag = defer+madvise
# /sys/block/sdb/queue/scheduler = [mq-deadline] cfq  <- wrong
# /proc/sys/net/core/busy_read = 0                     <- off
# /proc/sys/net/core/busy_poll = 0                     <- off
# /proc/sys/kernel/numa_balancing = 1                  <- wrong for Oracle

# tuned-adm recommend (what AHF shows it should be)
throughput-performance

# tuned-adm profile throughput-performance sets:
# scaling_governor = performance
# transparent_hugepage = never
# scheduler = deadline
# kernel.numa_balancing = 0
```

**DBA Fix:**
```bash
tuned-adm profile throughput-performance
# Verify:
tuned-adm active
# Current active profile: throughput-performance
```

---

## TIER1-11: IO Scheduler = cfq — Oracle Random I/O Serialized

**OS Error (no ORA code — storage performance degraded):**
```
# cat /sys/block/sdb/queue/scheduler (from AHF)
noop deadline [cfq]
# cfq is active (in brackets) — WRONG for Oracle

# cfq serializes I/O per process — Oracle multiprocess I/O suffers
# deadline/noop allows Oracle to submit concurrent I/Os properly

# iostat -x 1 5 showing cfq behavior:
Device:  rrqm/s wrqm/s  r/s   w/s  rkB/s  wkB/s  avgrq-sz avgqu-sz await  svctm %util
sdb        0.0    1.0  0.0  892.0   0.0  114176.0  256.0     1.2   1.4   1.1  98.0
# avgqu-sz=1.2 — cfq keeps queue shallow → high await even on fast SSD
# With deadline: avgqu-sz would be 8-16, await would drop to 0.2ms
```

**DBA Fix:**
```bash
# Check all Oracle disks:
for d in sdb sdc sdd; do
  echo "$d: $(cat /sys/block/$d/queue/scheduler)"
done

# Change scheduler:
echo deadline > /sys/block/sdb/queue/scheduler
echo deadline > /sys/block/sdc/queue/scheduler

# For NVMe:
echo none > /sys/block/nvme0n1/queue/scheduler

# Persistent (add to /etc/rc.local or udev rule):
echo 'ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/scheduler}="deadline"' \
  > /etc/udev/rules.d/60-oracle-scheduler.rules
```

---

## TIER1-12: tcp_keepalive_time=7200 — Firewall Drops Idle Oracle Connections

**OS Error (no ORA code at drop time — appears 2 hours later):**
```
# sysctl net.ipv4.tcp_keepalive_time (from AHF)
net.ipv4.tcp_keepalive_time = 7200
# 7200 seconds = 2 hours before Oracle sends TCP keepalive probe

# Firewall/load balancer idle timeout = 900 seconds (15 min)
# Result: firewall drops connection at 15min, Oracle doesn't know until 2 hours later

# netstat showing ESTABLISHED connections that are actually dead:
# netstat -an | grep 1521 | grep ESTABLISHED | wc -l
892
# All 892 appear ESTABLISHED — but 782 of them are dead (firewall dropped)
```

**ORA code DBA sees (2 hours after firewall drop):**
```
Tue Apr 09 10:44:21 2024
Fatal NI connect error 12170.
  TNS-12535: TNS:operation timed out
ORA-03113: end-of-file on communication channel
Process ID: 0
Session ID: 921, Serial number: 44291
# Happens 2 hours after firewall dropped the connection
# Application thinks session is active — gets ORA-03113 on next query
```

**DBA Fix:**
```bash
# Reduce keepalive to below firewall timeout:
sysctl -w net.ipv4.tcp_keepalive_time=600    # 10 minutes
sysctl -w net.ipv4.tcp_keepalive_intvl=60    # probe every 60s
sysctl -w net.ipv4.tcp_keepalive_probes=10   # 10 probes before giving up

echo "net.ipv4.tcp_keepalive_time = 600"    >> /etc/sysctl.conf
echo "net.ipv4.tcp_keepalive_intvl = 60"   >> /etc/sysctl.conf
echo "net.ipv4.tcp_keepalive_probes = 10"  >> /etc/sysctl.conf

# Also set in Oracle sqlnet.ora:
# SQLNET.EXPIRE_TIME=10  (minutes)
```
