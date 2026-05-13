# Do OS-Level Errors Produce ORA Codes?
## Definitive Answer — Temperature 0.0

---

## THE DIRECT ANSWER

**OS-level errors themselves have NO ORA codes.**
They appear in `/var/log/messages`, `dmesg`, `sar`, `iostat` — raw OS format only.

BUT — Oracle Engine **detects the OS failure** and surfaces a **secondary ORA code**
in the alert log / trace file as a SYMPTOM.

```
CHAIN:
  OS Error (Linux kernel/driver)
      ↓
  Oracle makes syscall (read/write/shmget/semget/mmap)
      ↓
  Syscall returns errno (ENOMEM / EIO / EAGAIN / ENOSPC)
      ↓
  Oracle translates errno → ORA code
      ↓
  ORA code appears in alert.log + trace file

DBA sees ORA code → must dig into OS logs to find root cause
```

---

## FULL MAPPING: OS Error → ORA Code

| OS Error | OS Source | errno | ORA Code Surfaced | Where ORA appears |
|---|---|---|---|---|
| aio-max-nr limit hit | /proc/sys/fs/aio-nr | EAGAIN | ORA-27072 | alert.log, trace |
| /dev/shm too small | df /dev/shm | EINVAL/ENOMEM | ORA-27102 | alert.log |
| shmget EINVAL (shmmax too low) | /var/log/messages | EINVAL | ORA-27102, ORA-27100 | alert.log |
| memlock ulimit too low | limits.conf | EPERM | ORA-27125 | alert.log |
| semget ENOSPC (semmni limit) | /var/log/messages | ENOSPC | ORA-27300, ORA-27301 | alert.log |
| OOM killer kills oracle | /var/log/messages | — | ORA-00603, ORA-07445 | alert.log |
| SCSI disk timeout | /var/log/messages | EIO | ORA-27072, ORA-15080(ASM) | alert.log |
| Multipath all paths fail | /var/log/messages | EIO | ORA-15080, ORA-15041 | alert.log |
| EXT4/XFS filesystem remount RO | /var/log/messages | EROFS | ORA-19504, ORA-16038 | alert.log |
| /arch filesystem full | df | ENOSPC | ORA-00257, ORA-19809 | alert.log |
| inode exhaustion | df -i | ENOSPC | ORA-19504 | alert.log |
| FC HBA reset / LOGO | /var/log/messages | EIO | ORA-27072 | trace file |
| nf_conntrack table full | /var/log/messages | ECONNREFUSED | ORA-03113, ORA-12170 | sqlnet.log |
| iptables blocking port 1521 | /var/log/messages | ECONNREFUSED | ORA-12541, ORA-12170 | sqlnet.log |
| NFS mount timeout | /var/log/messages | ETIMEDOUT | ORA-27054, ORA-27072 | alert.log |
| MTU mismatch (RAC) | ip link / dmesg | — | CRS-1618, gc block lost | CRS log |
| NTP time step >2s (RAC) | /var/log/messages | — | CRS-1618 | ocssd.log |
| SELinux denying Oracle | /var/log/audit/audit.log | EACCES | ORA-27300, ORA-27301, ORA-27302 | alert.log |
| fd limit (nofile too low) | /var/log/messages | EMFILE | ORA-27054, trace file open fails | alert.log |
| nproc limit hit | /etc/security/limits.conf | EAGAIN | ORA-00020 | alert.log |
| vm.swappiness SGA paged out | vmstat si/so | — | ORA-04031 (indirect) | alert.log |
| HugePages_Free=0 | /proc/meminfo | ENOMEM | ORA-27102 | alert.log |
| EDAC UE uncorrected memory | /var/log/messages | — | ORA-07445, ORA-00600 | trace file |
| Kernel panic | /var/log/messages | — | none (instance crash) | — |
| iSCSI session failure | /var/log/messages | EIO | ORA-27072 | alert.log |
| IO queue timeout 180s | /var/log/messages | EIO | ORA-27072, ORA-15080 | alert.log |
| dm-thin pool full | /var/log/messages | ENOSPC | ORA-19504, ORA-27040 | alert.log |
| RAID md0 degraded | /proc/mdstat | — | ORA-27072 (on write fail) | alert.log |

---

## OS ERRORS WITH NO ORA CODE (Performance Impact Only)

These are **silent killers** — Oracle runs but slowly. No ORA code in alert log.
DBA must look at AWR + OS metrics together.

| OS Error | OS Source | Oracle Symptom (AWR) | How DBA Finds It |
|---|---|---|---|
| CPU governor = powersave | /sys/devices/.../scaling_governor | All waits longer, no single dominant wait | cpupower frequency-info |
| BIOS C-states enabled | cpupower idle-info | log file sync spikes (sporadic) | cpupower idle-info |
| tuned profile = balanced | tuned-adm active | Everything slightly slower | tuned-adm active |
| IO scheduler = cfq | /sys/block/sdb/queue/scheduler | High await on random I/O | cat /sys/block/sdb/queue/scheduler |
| vm.swappiness=60 | /proc/sys/vm/swappiness | Occasional slow queries, si>0 | vmstat si column |
| MTU 1500 on RAC interconnect | ip link show | gc current/cr block busy high | ping -M do -s 8972 test |
| rp_filter=1 on interconnect | /proc/sys/net/ipv4/conf | Intermittent CRS warnings | sysctl net.ipv4.conf.all.rp_filter |
| tcp_keepalive_time=7200 | /proc/sys/net/ipv4/... | ORA-03113 after idle (not immediate) | sysctl net.ipv4.tcp_keepalive_time |
| THP enabled (khugepaged) | /sys/kernel/mm/transparent_hugepage | Random latency spikes | cat /sys/kernel/mm/transparent_hugepage/enabled |
| NUMA imbalance | numastat | Higher buffer cache miss rate | numastat -m |
| noatime not set on filesystem | /proc/mounts | Extra metadata I/O on reads | mount | grep relatime |

---

## KEY INSIGHT FOR YOUR RAG AGENT

```
When DBA searches by ORA code:
  ORA-27072 → agent must pull BOTH:
    1. Oracle alert.log trace (ORA code context)
    2. /var/log/messages at same timestamp (OS root cause)

When DBA searches by OS error:
  SCSI timeout on sdb → agent must pull BOTH:
    1. /var/log/messages kernel message
    2. Oracle alert.log ORA-27072 that followed

Your vector embeddings should link:
  OS error chunk ←→ ORA code chunk (same timestamp window)
  This is the core value of the RAG agent over plain log search
```
