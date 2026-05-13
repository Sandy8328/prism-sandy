# Knowledge Graph — Part 2: OS Error Pattern Nodes
## All OS_ERROR_PATTERN nodes with properties and edges

---

## DISK / I-O PATTERNS

### SCSI_DISK_TIMEOUT
```
id:          "SCSI_DISK_TIMEOUT"
category:    "DISK"
sub_category: "SCSI"
log_keywords: ["FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_TIMEOUT",
               "Sense Key : Hardware Error",
               "Internal target failure",
               "blk_update_request: I/O error",
               "Buffer I/O error",
               "Stopping disk"]
log_source:  "/var/log/messages"
errno:       "EIO=5"
severity:    "CRITICAL"

triggered_by edges:
  → FC_HBA_RESET              probability=0.45  time_gap_sec=1
  → STORAGE_ARRAY_ERROR       probability=0.30  time_gap_sec=0
  → MULTIPATH_PATH_FAIL       probability=0.15  time_gap_sec=2
  → SMARTCTL_PENDING_SECTOR   probability=0.10  time_gap_sec=0

appears_in:
  → /var/log/messages          keywords=["sd [a-z]+.*FAILED", "DRIVER_TIMEOUT"]

escalates_to:
  → ORA_IO_ERROR              time_to_escalate="immediate"
  → ASM_DISK_OFFLINE          time_to_escalate="immediate"

fixed_by:
  → FIX_CHECK_HBA_FIRMWARE
  → FIX_ENABLE_MULTIPATH
  → FIX_CHECK_STORAGE_ARRAY

confirmed_by:
  → "dmesg | grep -i 'scsi\\|sd.*FAIL\\|I/O error'"
  → "cat /var/log/messages | grep 'kernel.*sd.*FAIL'"
```

### FC_HBA_RESET
```
id:          "FC_HBA_RESET"
category:    "DISK"
sub_category: "FC_HBA"
log_keywords: ["qla2xxx.*LOGO nexus",
               "PLOGI IOCB timeout",
               "Adapter reset issued",
               "Adapter aborted all outstanding I/O",
               "Abort ISP active -- Resetting",
               "Link Up -- F_Port"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

triggered_by:
  → HBA_CABLE_FAULT           probability=0.40
  → FC_SWITCH_ISSUE           probability=0.35
  → HBA_FIRMWARE_BUG          probability=0.25

appears_in:
  → /var/log/messages         keywords=["qla2xxx", "LOGO nexus", "ISP"]

escalates_to:
  → SCSI_DISK_TIMEOUT         time_to_escalate="immediate"
  → ORA_IO_ERROR              time_to_escalate="1-2 seconds"

co_occurs_with:
  → SCSI_DISK_TIMEOUT         time_window_sec=2

fixed_by:
  → FIX_CHECK_HBA_FIRMWARE
  → FIX_CHECK_FC_CABLE
  → FIX_ENABLE_MULTIPATH

confirmed_by:
  → "grep qla2xxx /var/log/messages"
  → "systool -c fc_host -v"
```

### MULTIPATH_ALL_PATHS_DOWN
```
id:          "MULTIPATH_ALL_PATHS_DOWN"
category:    "DISK"
sub_category: "MULTIPATH"
log_keywords: ["remaining active paths: 0",
               "Fail all paths",
               "multipathd.*path.*down",
               "device-mapper: multipath: Failing path"]
log_source:  "/var/log/messages"
errno:       "EIO=5"
severity:    "CRITICAL"

triggered_by:
  → FC_HBA_RESET              probability=0.40
  → SCSI_DISK_TIMEOUT         probability=0.30
  → STORAGE_ARRAY_ERROR       probability=0.20
  → ISCSI_SESSION_FAIL        probability=0.10

appears_in:
  → /var/log/messages         keywords=["multipathd", "remaining active paths: 0"]

escalates_to:
  → ASM_DISK_OFFLINE          time_to_escalate="immediate"
  → INSTANCE_CRASH            time_to_escalate="within 30 seconds"

fixed_by:
  → FIX_RESTORE_MULTIPATH_PATHS
  → FIX_CHECK_STORAGE_ARRAY
  → FIX_ENABLE_MULTIPATH

confirmed_by:
  → "multipath -ll | grep -i 'fail\\|0:0'"
```

### IO_QUEUE_TIMEOUT
```
id:          "IO_QUEUE_TIMEOUT"
category:    "DISK"
sub_category: "BLOCK_LAYER"
log_keywords: ["blk_queue_timeout: request timeout",
               "blk_abort_request",
               "scsi_abort_command",
               "ABORT SUCCESS",
               "Aborting command"]
log_source:  "/var/log/messages"
errno:       "EIO=5"
severity:    "CRITICAL"

triggered_by:
  → STORAGE_ARRAY_SLOW        probability=0.50
  → FC_HBA_RESET              probability=0.30
  → MULTIPATH_PATH_FAIL       probability=0.20

confirmed_by:
  → "dmesg | grep 'blk_queue_timeout\\|request timeout'"
```

### EXT4_JOURNAL_ABORT
```
id:          "EXT4_JOURNAL_ABORT"
category:    "DISK"
sub_category: "FILESYSTEM"
log_keywords: ["EXT4-fs error.*ext4_journal_check_start",
               "Detected aborted journal",
               "Remounting filesystem read-only",
               "ext4_valid_block_bitmap.*bad block bitmap",
               "JBD2: recovery failed"]
log_source:  "/var/log/messages"
errno:       "EROFS=30"
severity:    "CRITICAL"

triggered_by:
  → SCSI_DISK_TIMEOUT         probability=0.50
  → IO_QUEUE_TIMEOUT          probability=0.30
  → LVM_DEVICE_FAIL           probability=0.20

escalates_to:
  → ORA_ARCHIVER_STUCK        time_to_escalate="immediate"

confirmed_by:
  → "dmesg | grep 'EXT4-fs error\\|aborted journal'"
  → "mount | grep ro"
```

### XFS_FILESYSTEM_SHUTDOWN
```
id:          "XFS_FILESYSTEM_SHUTDOWN"
category:    "DISK"
sub_category: "FILESYSTEM"
log_keywords: ["XFS.*metadata I/O error",
               "Filesystem has been shut down due to log error",
               "xfs_inode_item_push: push error"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

triggered_by:
  → SCSI_DISK_TIMEOUT         probability=0.60
  → IO_QUEUE_TIMEOUT          probability=0.40

escalates_to:
  → ORACLE_HOME_OFFLINE       time_to_escalate="immediate"

confirmed_by:
  → "dmesg | grep 'XFS.*shut down'"
```

### FILESYSTEM_ARCH_FULL
```
id:          "FILESYSTEM_ARCH_FULL"
category:    "DISK"
sub_category: "FILESYSTEM_CAPACITY"
log_keywords: ["Use% = 100%", "/arch.*100%"]
log_source:  "df_output"
errno:       "ENOSPC=28"
severity:    "CRITICAL"

appears_in:
  → /u01/app/oracle.ahf/.../os/df.txt   keywords=["100%", "/arch"]

escalates_to:
  → ORA_ARCHIVER_STUCK        time_to_escalate="immediate"

fixed_by:
  → FIX_CLEANUP_ARCH_LOGS
  → FIX_ADD_ARCH_SPACE

confirmed_by:
  → "df -h /arch"
```

### SMARTCTL_PENDING_SECTOR
```
id:          "SMARTCTL_PENDING_SECTOR"
category:    "DISK"
sub_category: "HARDWARE"
log_keywords: ["SMART overall-health.*FAILED",
               "Current_Pending_Sector",
               "Offline_Uncorrectable",
               "Drive failure expected"]
log_source:  "smartctl_output"
severity:    "CRITICAL"

escalates_to:
  → SCSI_DISK_TIMEOUT         time_to_escalate="within 24 hours"
  → DATA_CORRUPTION           time_to_escalate="within 24 hours"

fixed_by:
  → FIX_REPLACE_DISK_IMMEDIATELY

confirmed_by:
  → "smartctl -a /dev/sdX | grep -i 'health\\|pending\\|uncorrectable'"
```

### ISCSI_SESSION_FAIL
```
id:          "ISCSI_SESSION_FAIL"
category:    "DISK"
sub_category: "ISCSI"
log_keywords: ["iscsid.*connection timed out",
               "iscsid: detected conn error",
               "scsi.*rejecting I/O to dead device",
               "ping timeout.*expired"]
log_source:  "/var/log/messages"
errno:       "EIO=5"
severity:    "CRITICAL"

confirmed_by:
  → "iscsiadm -m session"
  → "iscsiadm -m session -P 3"
```

### LVM_DEVICE_FAIL
```
id:          "LVM_DEVICE_FAIL"
category:    "DISK"
sub_category: "LVM"
log_keywords: ["device-mapper: table.*dm-linear: Device lookup failed",
               "delayed block allocation failed.*error -5",
               "This should not happen!! Data will be lost"]
log_source:  "/var/log/messages"
errno:       "EIO=5"
severity:    "CRITICAL"

confirmed_by:
  → "lvs --all"
  → "pvs"
  → "dmesg | grep 'device-mapper'"
```

---

## MEMORY PATTERNS

### OOM_KILLER_ACTIVE
```
id:          "OOM_KILLER_ACTIVE"
category:    "MEMORY"
log_keywords: ["oracle invoked oom-killer",
               "Memory cgroup out of memory: Kill process",
               "Killed process.*oracle",
               "oom_reaper: reaped process.*oracle",
               "Out of memory: Kill process"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

triggered_by:
  → MEMORY_SWAP_STORM         probability=0.40
  → HUGEPAGES_FREE_ZERO       probability=0.30
  → CGROUP_MEMORY_LIMIT       probability=0.20
  → VM_OVERCOMMIT_MISS        probability=0.10

escalates_to:
  → INSTANCE_CRASH            time_to_escalate="immediate"

confirmed_by:
  → "grep -i 'oom-killer\\|Killed process.*oracle' /var/log/messages"
  → "dmesg | grep -i 'oom\\|kill'"
```

### CGROUP_OOM_KILL
```
id:          "CGROUP_OOM_KILL"
category:    "MEMORY"
log_keywords: ["oracle-ohasd.service: A process.*killed by the OOM killer",
               "Memory cgroup out of memory",
               "oracle-ohasd.service: Failed with result 'oom-kill'",
               "Failed to start OHAS Daemon"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

triggered_by:
  → CGROUP_MEMORY_LIMIT       probability=1.0

escalates_to:
  → CRS_STACK_CRASH           time_to_escalate="immediate"

fixed_by:
  → FIX_INCREASE_CGROUP_LIMIT
  → FIX_REMOVE_CGROUP_LIMIT

confirmed_by:
  → "systemctl show oracle-ohasd.service | grep MemoryLimit"
```

### SHMGET_EINVAL
```
id:          "SHMGET_EINVAL"
category:    "MEMORY"
log_keywords: ["shmget: errno=22",
               "Cannot create shared memory segment",
               "shm_tot.*exceeds shm_ctlmax"]
log_source:  "/var/log/messages"
errno:       "EINVAL=22"
severity:    "CRITICAL"

triggered_by:
  → KERNEL_SHMMAX_TOO_LOW     probability=1.0

fixed_by:
  → FIX_INCREASE_SHMMAX
confirmed_by:
  → "cat /proc/sys/kernel/shmmax"
  → "sysctl kernel.shmmax"
```

### HUGEPAGES_FREE_ZERO
```
id:          "HUGEPAGES_FREE_ZERO"
category:    "MEMORY"
log_keywords: ["HugePages_Free:        0",
               "hugetlb: allocating.*failed",
               "HugePages allocation failed"]
log_source:  "/proc/meminfo + /var/log/messages"
errno:       "ENOMEM=12"
severity:    "ERROR"

confirmed_by:
  → "grep HugePages /proc/meminfo"
```

### MEMORY_SWAP_STORM
```
id:          "MEMORY_SWAP_STORM"
category:    "MEMORY"
log_keywords: ["si=", "so="]
log_source:  "vmstat_output"
severity:    "ERROR"

confirmed_by:
  → "vmstat 1 5 | awk '{print $7, $8}'"
  → "cat /proc/sys/vm/swappiness"
```

### SEMAPHORE_LIMIT_EXHAUSTED
```
id:          "SEMAPHORE_LIMIT_EXHAUSTED"
category:    "MEMORY"
log_keywords: ["semget: errno=28",
               "Unable to allocate semaphore set",
               "semmni limit reached"]
log_source:  "/var/log/messages"
errno:       "ENOSPC=28"
severity:    "CRITICAL"

confirmed_by:
  → "ipcs -ls"
  → "sysctl kernel.sem"
```

### FD_LIMIT_EXHAUSTED
```
id:          "FD_LIMIT_EXHAUSTED"
category:    "KERNEL"
log_keywords: ["Too many open files",
               "VFS: file-max limit.*reached",
               "error: open: Too many open files"]
log_source:  "/var/log/messages"
errno:       "EMFILE=24"
severity:    "CRITICAL"

confirmed_by:
  → "cat /proc/sys/fs/file-nr"
  → "ulimit -n (as oracle user)"
  → "cat /proc/PID/limits | grep 'open files'"
```

### MEMLOCK_ULIMIT_TOO_LOW
```
id:          "MEMLOCK_ULIMIT_TOO_LOW"
category:    "MEMORY"
log_keywords: ["ORADISM.*mlock failed.*EPERM",
               "ORADISM: shmctl(SHM_LOCK) failed with errno=12",
               "Cannot lock SGA: Operation not permitted"]
log_source:  "/var/log/messages"
errno:       "EPERM=1"
severity:    "ERROR"

confirmed_by:
  → "ulimit -l (as oracle user)"
  → "grep memlock /etc/security/limits.conf"
  → "systemctl show oracle-ohasd.service | grep LimitMEMLOCK"
```

### DEVSHM_TOO_SMALL
```
id:          "DEVSHM_TOO_SMALL"
category:    "MEMORY"
log_keywords: ["Cannot create SGA segment.*No space left.*dev/shm",
               "shmget.*errno = 28.*ENOSPC"]
log_source:  "/var/log/messages"
errno:       "ENOSPC=28"
severity:    "CRITICAL"

confirmed_by:
  → "df -h /dev/shm"
  → "cat /proc/mounts | grep shm"
```

---

## CPU PATTERNS

### CPU_RUNQUEUE_SATURATION
```
id:          "CPU_RUNQUEUE_SATURATION"
category:    "CPU"
log_keywords: ["runq-sz", "ldavg-1", "ldavg-5"]
log_source:  "sar_q_output"
severity:    "ERROR"

detection_threshold:
  runq-sz > (2 × CPU_COUNT)

confirmed_by:
  → "sar -q 1 10"
  → "uptime"
  → "top -b -n1 | head -5"
```

### CPU_STEAL_TIME
```
id:          "CPU_STEAL_TIME"
category:    "CPU"
log_keywords: ["%steal"]
log_source:  "sar_cpu_output"
severity:    "ERROR"

detection_threshold:
  %steal > 20%

confirmed_by:
  → "sar -u ALL 1 10 | grep steal"
```

### SOFT_LOCKUP
```
id:          "SOFT_LOCKUP"
category:    "CPU / KERNEL"
log_keywords: ["BUG: soft lockup - CPU#.*stuck for",
               "oracle.*stuck for.*s"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

confirmed_by:
  → "dmesg | grep 'soft lockup'"
```

### HARD_LOCKUP
```
id:          "HARD_LOCKUP"
category:    "KERNEL"
log_keywords: ["Watchdog detected hard LOCKUP on cpu",
               "NMI backtrace for cpu"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

escalates_to:
  → KERNEL_PANIC              time_to_escalate="immediate"
```

### KERNEL_PANIC
```
id:          "KERNEL_PANIC"
category:    "KERNEL"
log_keywords: ["Kernel panic - not syncing",
               "Marking controller dead",
               "Fatal exception"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

escalates_to:
  → INSTANCE_CRASH            time_to_escalate="immediate"
  → SERVER_REBOOT             time_to_escalate="immediate"
```

### MCE_UNCORRECTED_MEMORY
```
id:          "MCE_UNCORRECTED_MEMORY"
category:    "KERNEL"
log_keywords: ["EDAC MC0.*UE memory read error",
               "Hardware Error.*Machine Check Exception",
               "MCE.*Uncorrected"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

escalates_to:
  → KERNEL_PANIC              time_to_escalate="possible"
  → DATA_CORRUPTION           time_to_escalate="possible"
```

### SELINUX_BLOCKING
```
id:          "SELINUX_BLOCKING"
category:    "KERNEL"
log_keywords: ["avc: denied",
               "scontext=.*oracle_db_t",
               "tclass=file permissive=0"]
log_source:  "/var/log/audit/audit.log"
errno:       "EACCES=13"
severity:    "ERROR"

confirmed_by:
  → "getenforce"
  → "ausearch -c oracle --raw | tail -20"
```

### SYSTEMD_LIMITS_OVERRIDE
```
id:          "SYSTEMD_LIMITS_OVERRIDE"
category:    "KERNEL"
log_keywords: ["LimitNOFILE=1024",
               "LimitNPROC=3818",
               "Too many open files"]
log_source:  "/proc/PID/limits"
severity:    "ERROR"

confirmed_by:
  → "systemctl show oracle-ohasd.service | grep -i limit"
  → "cat /proc/$(pgrep -f oracle)/limits"
```

---

## NETWORK PATTERNS

### BONDING_FAILOVER_EVENT
```
id:          "BONDING_FAILOVER_EVENT"
category:    "NETWORK"
log_keywords: ["bonding.*link status definitely down for interface",
               "bonding.*making interface.*new active one",
               "bonding.*link status definitely up"]
log_source:  "/var/log/messages"
severity:    "ERROR"

escalates_to:
  → ORA_SESSION_DROP          time_to_escalate="3-4 seconds"
  → CRS_HEARTBEAT_MISS        time_to_escalate="3-4 seconds"

confirmed_by:
  → "cat /proc/net/bonding/bond0"
  → "ip link show bond0"
```

### BOTH_NICS_DOWN
```
id:          "BOTH_NICS_DOWN"
category:    "NETWORK"
log_keywords: ["Warning: No active slaves. Using last resort",
               "NIC Copper Link is Down.*eth0",
               "NIC Copper Link is Down.*eth1"]
log_source:  "dmesg"
severity:    "CRITICAL"

escalates_to:
  → INSTANCE_CRASH            time_to_escalate="immediate"

confirmed_by:
  → "ip link show"
  → "cat /proc/net/bonding/bond0"
```

### NF_CONNTRACK_FULL
```
id:          "NF_CONNTRACK_FULL"
category:    "NETWORK"
log_keywords: ["nf_conntrack: nf_conntrack: table full, dropping packet"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

confirmed_by:
  → "sysctl net.nf_conntrack_max"
  → "cat /proc/sys/net/netfilter/nf_conntrack_count"
```

### IB_LINK_DEGRADED
```
id:          "IB_LINK_DEGRADED"
category:    "NETWORK"
log_keywords: ["mlx4.*command.*failed",
               "Link Speed: 10 Gb/s (disabled 40Gb)",
               "ib0.*downgraded"]
log_source:  "/var/log/messages"
severity:    "ERROR"

escalates_to:
  → CRS_HEARTBEAT_MISS        time_to_escalate="gradual"

confirmed_by:
  → "ibstat | grep -i 'speed\\|state'"
```

### NTP_TIME_JUMP
```
id:          "NTP_TIME_JUMP"
category:    "NETWORK"
log_keywords: ["System clock wrong by.*seconds",
               "Forward time jump detected",
               "System clock was stepped by"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

escalates_to:
  → CRS_NODE_EVICTION         time_to_escalate="within 30 seconds"

confirmed_by:
  → "chronyc tracking"
  → "timedatectl status"
```

### IPTABLES_BLOCKING_1521
```
id:          "IPTABLES_BLOCKING_1521"
category:    "NETWORK"
log_keywords: ["FINAL_REJECT.*DPT=1521",
               "FINAL_REJECT.*DPT=1522"]
log_source:  "/var/log/messages"
severity:    "ERROR"

confirmed_by:
  → "iptables -L -n | grep 1521"
  → "firewall-cmd --list-all"
```

### NFS_MOUNT_TIMEOUT
```
id:          "NFS_MOUNT_TIMEOUT"
category:    "NETWORK"
log_keywords: ["nfs: server.*not responding, timed out",
               "nfs: server.*still trying",
               "nfs: server.*OK"]
log_source:  "/var/log/messages"
severity:    "CRITICAL"

confirmed_by:
  → "showmount -e <nfs_server>"
  → "mount | grep nfs"
```

### UDP_BUFFER_OVERFLOW
```
id:          "UDP_BUFFER_OVERFLOW"
category:    "NETWORK"
log_keywords: ["packet receive errors",
               "receive buffer errors"]
log_source:  "netstat_s_output"
severity:    "ERROR"

confirmed_by:
  → "netstat -su | grep -i 'error\\|overflow'"
  → "sysctl net.core.rmem_max"
```

### SOCKET_EXHAUSTION
```
id:          "SOCKET_EXHAUSTION"
category:    "NETWORK"
log_keywords: ["TCP.*alloc.*near limit",
               "tcp_max_orphans"]
log_source:  "/proc/net/sockstat"
severity:    "ERROR"

confirmed_by:
  → "cat /proc/net/sockstat"
  → "ss -s"
```
