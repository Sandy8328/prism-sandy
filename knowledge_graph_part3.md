# Knowledge Graph — Part 3: Fix Nodes, Log Sources, Escalation Targets + Full Graph Summary
## Temperature: 0.0

---

## FIX_COMMAND NODES

### FIX_ENABLE_MULTIPATH
```
id:          "FIX_ENABLE_MULTIPATH"
description: "Enable device multipathing to eliminate single point of failure"
commands:
  - "systemctl enable multipathd --now"
  - "mpathconf --enable --with_multipathd y"
  - "multipath -ll"
requires:    "root"
risk:        "MEDIUM"
persistent:  true
downtime:    false
```

### FIX_RESTORE_MULTIPATH_PATHS
```
id:          "FIX_RESTORE_MULTIPATH_PATHS"
description: "Restore failed multipath paths"
commands:
  - "multipath -ll                          # check current state"
  - "multipathd reconfigure                 # reload config"
  - "multipathd add path <dev>              # re-add specific path"
  - "systemctl restart multipathd"
requires:    "root"
risk:        "MEDIUM"
persistent:  false
downtime:    false
```

### FIX_CHECK_HBA_FIRMWARE
```
id:          "FIX_CHECK_HBA_FIRMWARE"
description: "Check and update FC HBA firmware"
commands:
  - "systool -c fc_host -v | grep -i 'fw_rev\\|speed\\|port_state'"
  - "cat /sys/class/fc_host/host*/port_state"
  - "cat /sys/class/fc_host/host*/speed"
requires:    "root"
risk:        "HIGH"
persistent:  true
downtime:    true
```

### FIX_INCREASE_SHMMAX
```
id:          "FIX_INCREASE_SHMMAX"
description: "Increase kernel shared memory maximum for Oracle SGA"
commands:
  - "sysctl -w kernel.shmmax=137438953472   # 128GB example"
  - "sysctl -w kernel.shmall=33554432"
  - "echo 'kernel.shmmax = 137438953472' >> /etc/sysctl.conf"
  - "echo 'kernel.shmall = 33554432'    >> /etc/sysctl.conf"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_INCREASE_CGROUP_LIMIT
```
id:          "FIX_INCREASE_CGROUP_LIMIT"
description: "Increase or remove systemd cgroup memory limit for Oracle"
commands:
  - "systemctl edit oracle-ohasd.service"
  - "# Add under [Service]:"
  - "# MemoryLimit=0"
  - "# LimitMEMLOCK=infinity"
  - "systemctl daemon-reload"
  - "systemctl restart oracle-ohasd"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    true
```

### FIX_SET_HUGEPAGES
```
id:          "FIX_SET_HUGEPAGES"
description: "Configure HugePages for Oracle SGA"
commands:
  - "grep -i hugepage /proc/meminfo"
  - "sysctl -w vm.nr_hugepages=<N>          # N = SGA_size_MB / 2"
  - "echo 'vm.nr_hugepages = <N>' >> /etc/sysctl.conf"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_FIX_DEVSHM_SIZE
```
id:          "FIX_FIX_DEVSHM_SIZE"
description: "Resize /dev/shm tmpfs to accommodate Oracle SGA"
commands:
  - "df -h /dev/shm"
  - "mount -o remount,size=<SGA+20%>G /dev/shm"
  - "# Persistent in /etc/fstab:"
  - "# tmpfs /dev/shm tmpfs defaults,size=128G 0 0"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_SET_SWAPPINESS
```
id:          "FIX_SET_SWAPPINESS"
description: "Set vm.swappiness to Oracle-recommended value"
commands:
  - "sysctl -w vm.swappiness=10"
  - "echo 'vm.swappiness = 10' >> /etc/sysctl.conf"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_SET_MEMLOCK_ULIMIT
```
id:          "FIX_SET_MEMLOCK_ULIMIT"
description: "Set memlock ulimit to unlimited for oracle user"
commands:
  - "# /etc/security/limits.conf:"
  - "oracle   soft   memlock   unlimited"
  - "oracle   hard   memlock   unlimited"
  - "# Also in systemd service:"
  - "LimitMEMLOCK=infinity"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_DISABLE_SELINUX
```
id:          "FIX_DISABLE_SELINUX"
description: "Set SELinux permissive or create Oracle-specific policy"
commands:
  - "getenforce"
  - "# Temporary:"
  - "setenforce 0"
  - "# Permanent (Oracle way):"
  - "ausearch -c oracle --raw | audit2allow -M oracle_policy"
  - "semodule -i oracle_policy.pp"
  - "# Or set permissive in /etc/selinux/config: SELINUX=permissive"
requires:    "root"
risk:        "MEDIUM"
persistent:  true
downtime:    false
```

### FIX_SYSTEMD_ULIMITS
```
id:          "FIX_SYSTEMD_ULIMITS"
description: "Override systemd default limits for Oracle services"
commands:
  - "systemctl edit oracle-ohasd.service"
  - "# Add:"
  - "[Service]"
  - "LimitNOFILE=65536"
  - "LimitNPROC=16384"
  - "LimitMEMLOCK=infinity"
  - "LimitSTACK=unlimited"
  - "systemctl daemon-reload"
  - "systemctl restart oracle-ohasd"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    true
```

### FIX_CONNTRACK_LIMIT
```
id:          "FIX_CONNTRACK_LIMIT"
description: "Increase nf_conntrack table size"
commands:
  - "sysctl -w net.nf_conntrack_max=524288"
  - "echo 'net.nf_conntrack_max = 524288' >> /etc/sysctl.conf"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_MTU_JUMBO
```
id:          "FIX_MTU_JUMBO"
description: "Set consistent jumbo frames on RAC interconnect"
commands:
  - "ip link set bond0 mtu 9000"
  - "ping -M do -s 8972 <other_node_ip>     # test end-to-end"
  - "# /etc/sysconfig/network-scripts/ifcfg-bond0:"
  - "MTU=9000"
requires:    "root"
risk:        "MEDIUM"
persistent:  true
downtime:    false
```

### FIX_TCP_KEEPALIVE
```
id:          "FIX_TCP_KEEPALIVE"
description: "Reduce TCP keepalive time below firewall idle timeout"
commands:
  - "sysctl -w net.ipv4.tcp_keepalive_time=600"
  - "sysctl -w net.ipv4.tcp_keepalive_intvl=60"
  - "sysctl -w net.ipv4.tcp_keepalive_probes=10"
  - "echo 'net.ipv4.tcp_keepalive_time = 600'  >> /etc/sysctl.conf"
  - "# Also in Oracle sqlnet.ora:"
  - "SQLNET.EXPIRE_TIME=10"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_CLEANUP_ARCH_LOGS
```
id:          "FIX_CLEANUP_ARCH_LOGS"
description: "Free space on /arch filesystem"
commands:
  - "df -h /arch"
  - "# As Oracle:"
  - "rman target /"
  - "RMAN> DELETE ARCHIVELOG ALL COMPLETED BEFORE 'SYSDATE-3';"
  - "# Or delete from OS (risky if not backed up):"
  - "find /arch -name '*.arc' -mtime +7 -delete"
requires:    "oracle"
risk:        "HIGH"
persistent:  false
downtime:    false
```

### FIX_SET_IO_SCHEDULER
```
id:          "FIX_SET_IO_SCHEDULER"
description: "Set disk scheduler to deadline for Oracle disks"
commands:
  - "cat /sys/block/sdb/queue/scheduler"
  - "echo deadline > /sys/block/sdb/queue/scheduler"
  - "# Persistent udev rule:"
  - "echo 'ACTION==\"add|change\", KERNEL==\"sd[a-z]\", ATTR{queue/scheduler}=\"deadline\"' > /etc/udev/rules.d/60-oracle-scheduler.rules"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_TUNED_PROFILE
```
id:          "FIX_TUNED_PROFILE"
description: "Set tuned profile to throughput-performance for Oracle"
commands:
  - "tuned-adm active"
  - "tuned-adm profile throughput-performance"
  - "tuned-adm active                        # verify"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_CPU_GOVERNOR
```
id:          "FIX_CPU_GOVERNOR"
description: "Set CPU frequency governor to performance"
commands:
  - "cpupower frequency-info | grep governor"
  - "tuned-adm profile throughput-performance  # sets governor automatically"
  - "# Or manually:"
  - "cpupower frequency-set -g performance"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_DISABLE_THP
```
id:          "FIX_DISABLE_THP"
description: "Disable Transparent HugePages for Oracle"
commands:
  - "cat /sys/kernel/mm/transparent_hugepage/enabled"
  - "echo never > /sys/kernel/mm/transparent_hugepage/enabled"
  - "echo never > /sys/kernel/mm/transparent_hugepage/defrag"
  - "# Persistent in /etc/rc.local or grub:"
  - "# transparent_hugepage=never"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_AIO_MAX_NR
```
id:          "FIX_AIO_MAX_NR"
description: "Increase async I/O limit for Oracle"
commands:
  - "cat /proc/sys/fs/aio-nr"
  - "cat /proc/sys/fs/aio-max-nr"
  - "sysctl -w fs.aio-max-nr=3145728"
  - "echo 'fs.aio-max-nr = 3145728' >> /etc/sysctl.conf"
requires:    "root"
risk:        "LOW"
persistent:  true
downtime:    false
```

### FIX_REPLACE_DISK_IMMEDIATELY
```
id:          "FIX_REPLACE_DISK_IMMEDIATELY"
description: "Disk pre-fail — replace before data loss"
commands:
  - "smartctl -a /dev/sdX | grep -i 'health\\|pending'"
  - "# Evacuate ASM diskgroup before pulling disk:"
  - "# alter diskgroup DATA drop disk DISK01;"
  - "# Schedule emergency disk replacement with hardware team"
requires:    "root + hardware team"
risk:        "HIGH"
persistent:  true
downtime:    true
```

---

## LOG SOURCE NODES

| id | path | format | time_format | AHF collected |
|---|---|---|---|---|
| VAR_LOG_MESSAGES | /var/log/messages | SYSLOG | "Mon DD HH:MM:SS hostname" | Yes |
| DMESG | dmesg output | DMESG | "[seconds.usec]" | Yes |
| ORACLE_ALERT_LOG | $ORACLE_BASE/diag/rdbms/.../alert_SID.log | ORACLE | "DDD Mon DD HH:MM:SS YYYY" | Yes |
| IOSTAT | iostat -xmt output | CSV-like | "MM/DD/YYYY HH:MM:SS AM" | Yes |
| SAR_CPU | sar -u output | SAR | "HH:MM:SS AM/PM" | Yes |
| SAR_DISK | sar -d output | SAR | "HH:MM:SS AM/PM" | Yes |
| VMSTAT | vmstat output | SPACE | N/A (relative) | Yes |
| DF | df -h output | SPACE | N/A (snapshot) | Yes |
| OCSSD_LOG | /u01/grid/log/node/cssd/ocssd.log | CRS | "YYYY-MM-DD HH:MM:SS.mmm" | Yes |
| CRSD_LOG | /u01/grid/log/node/crsd/crsd.log | CRS | "YYYY-MM-DD HH:MM:SS.mmm" | Yes |
| AUDIT_LOG | /var/log/audit/audit.log | AUDIT | "audit(epoch:serial)" | Yes |
| SMARTCTL | smartctl -a /dev/sdX | TEXT | N/A (snapshot) | Yes |
| MULTIPATH | multipath -ll output | TEXT | N/A (snapshot) | Yes |
| SOCKSTAT | /proc/net/sockstat | PROC | N/A (snapshot) | Yes |
| NETSTAT_S | netstat -su output | TEXT | N/A (snapshot) | Yes |

---

## ESCALATION TARGET NODES

| id | description | severity | Oracle recovery |
|---|---|---|---|
| INSTANCE_CRASH | Oracle instance terminates abnormally | CRITICAL | Crash recovery on restart |
| CRS_STACK_CRASH | CRS/OHAS daemon dies | CRITICAL | CRS restart, DB unavailable |
| CRS_NODE_EVICTION | RAC node evicted from cluster | CRITICAL | Failover to surviving node |
| ASM_DISK_OFFLINE | ASM disk removed from diskgroup | CRITICAL | IO error on diskgroup |
| ORA_ARCHIVER_STUCK | Archiver cannot write, DB in restricted mode | CRITICAL | Free /arch space to resume |
| ORA_IO_ERROR | Oracle gets EIO on datafile/redo | CRITICAL | Depends on which file |
| ORA_SESSION_DROP | Client connections dropped | ERROR | Reconnect required |
| DATA_CORRUPTION | Oracle data block corrupted | CRITICAL | RMAN restore/recover |
| SERVER_REBOOT | Host reboots due to kernel panic/lockup | CRITICAL | Full instance restart |
| ORACLE_HOME_OFFLINE | /u01 filesystem unavailable | CRITICAL | Cannot start Oracle |
| CRS_HEARTBEAT_MISS | CRS misses heartbeat on interconnect | WARNING | May lead to eviction |
| ORA_PERFORMANCE_DEGRADED | Oracle slow, no error code | WARNING | AWR analysis needed |

---

## COMPLETE EDGE SUMMARY (Graph Edges Quick Reference)

### ORA Code → OS Pattern (caused_by edges)

| ORA Code | OS Pattern | Probability |
|---|---|---|
| ORA-27072 | SCSI_DISK_TIMEOUT | 0.40 |
| ORA-27072 | FC_HBA_RESET | 0.25 |
| ORA-27072 | MULTIPATH_ALL_PATHS_DOWN | 0.15 |
| ORA-27072 | IO_QUEUE_TIMEOUT | 0.10 |
| ORA-27072 | ISCSI_SESSION_FAIL | 0.05 |
| ORA-15080 | MULTIPATH_ALL_PATHS_DOWN | 0.45 |
| ORA-15080 | SCSI_DISK_TIMEOUT | 0.25 |
| ORA-15080 | FC_HBA_RESET | 0.20 |
| ORA-27102 | SHMGET_EINVAL | 0.35 |
| ORA-27102 | DEVSHM_TOO_SMALL | 0.30 |
| ORA-27102 | HUGEPAGES_FREE_ZERO | 0.25 |
| ORA-27125 | MEMLOCK_ULIMIT_TOO_LOW | 0.70 |
| ORA-27300 | SEMAPHORE_LIMIT_EXHAUSTED | 0.30 |
| ORA-27300 | FD_LIMIT_EXHAUSTED | 0.25 |
| ORA-27300 | SELINUX_BLOCKING | 0.25 |
| ORA-00257 | FILESYSTEM_ARCH_FULL | 0.55 |
| ORA-00257 | EXT4_JOURNAL_ABORT | 0.25 |
| ORA-00257 | NFS_MOUNT_TIMEOUT | 0.15 |
| ORA-00603 | OOM_KILLER_ACTIVE | 0.60 |
| ORA-00603 | CGROUP_OOM_KILL | 0.30 |
| ORA-03113 | BONDING_FAILOVER_EVENT | 0.30 |
| ORA-03113 | NF_CONNTRACK_FULL | 0.20 |
| ORA-03113 | TCP_KEEPALIVE_FIREWALL | 0.20 |
| ORA-12541 | IPTABLES_BLOCKING_1521 | 0.50 |
| ORA-12541 | NF_CONNTRACK_FULL | 0.25 |
| ORA-12519 | SOCKET_EXHAUSTION | 0.60 |
| ORA-12519 | FD_LIMIT_EXHAUSTED | 0.30 |
| ORA-29740 | NTP_TIME_JUMP | 0.30 |
| ORA-29740 | BONDING_FAILOVER_EVENT | 0.20 |
| ORA-29740 | IB_LINK_DEGRADED | 0.20 |
| ORA-04031 | MEMORY_SWAP_STORM | 0.40 |
| ORA-04031 | HUGEPAGES_FREE_ZERO | 0.35 |
| ORA-07445 | OOM_KILLER_ACTIVE | 0.30 |
| ORA-07445 | MCE_UNCORRECTED_MEMORY | 0.25 |
| ORA-00353 | SCSI_DISK_TIMEOUT | 0.35 |
| ORA-00353 | FC_HBA_RESET | 0.30 |

### OS Pattern → OS Pattern (triggered_by edges)

| Pattern | Triggered By | Probability | Time Gap |
|---|---|---|---|
| SCSI_DISK_TIMEOUT | FC_HBA_RESET | 0.45 | 1s |
| SCSI_DISK_TIMEOUT | STORAGE_ARRAY_ERROR | 0.30 | 0s |
| MULTIPATH_ALL_PATHS_DOWN | FC_HBA_RESET | 0.40 | 2s |
| MULTIPATH_ALL_PATHS_DOWN | SCSI_DISK_TIMEOUT | 0.30 | 3s |
| EXT4_JOURNAL_ABORT | SCSI_DISK_TIMEOUT | 0.50 | 0s |
| OOM_KILLER_ACTIVE | MEMORY_SWAP_STORM | 0.40 | gradual |
| CGROUP_OOM_KILL | CGROUP_MEMORY_LIMIT | 1.0 | 0s |
| SHMGET_EINVAL | KERNEL_SHMMAX_TOO_LOW | 1.0 | 0s |
| SELINUX_BLOCKING | SELINUX_ENFORCING | 1.0 | 0s |
| HARD_LOCKUP | SOFT_LOCKUP | 0.50 | >120s |
| KERNEL_PANIC | HARD_LOCKUP | 0.70 | 0s |
| CRS_NODE_EVICTION | NTP_TIME_JUMP | 0.80 | 30s |
| CRS_NODE_EVICTION | IB_LINK_DEGRADED | 0.40 | gradual |
