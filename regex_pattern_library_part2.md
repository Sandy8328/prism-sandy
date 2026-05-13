# Regex Pattern Library — Part 2
## Kernel + Network Patterns + ORA Code Regex + Alert.log Regex
## Oracle DBA RAG Agent | Temperature: 0.0

---

## SECTION 4: KERNEL PATTERNS

### KERNEL_PANIC
```python
"KERNEL_PANIC": {
    "match_any": [
        r"Kernel panic - not syncing: Fatal exception",
        r"Kernel panic - not syncing: hung_task",
        r"Kernel panic - not syncing: softlockup",
        r"Marking controller dead, do not restart",
        r"megaraid_sas.*kill adapter.*command timeout",
        r"megaraid_sas.*DCMD timed out, aborting"
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "ora_codes_triggered": []   # server reboots — no ORA code written
}
```

### MCE_CORRECTED_MEMORY
```python
"MCE_CORRECTED_MEMORY": {
    "match_any": [
        r"EDAC MC\d+: \d+ CE memory read error on CPU_SrcID",
        r"mcelog: MCE.*Memory corrected error count.*CORE=\d+ CHANNEL=\d+",
        r"Hardware Error.*Corrected error, no action required",
        r"mce.*Corrected error"
    ],
    "match_all": [
        r"CE|Corrected error"
    ],
    "exclude": [
        r"UE|Uncorrected"
    ],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "WARNING",
    "ora_codes_triggered": []   # CE errors alone produce no ORA code
}
```

### MCE_UNCORRECTED_MEMORY
```python
"MCE_UNCORRECTED_MEMORY": {
    "match_any": [
        r"EDAC MC\d+: \d+ UE memory read error on CPU_SrcID",
        r"Machine Check Exception.*Uncorrected",
        r"Hardware Error.*Uncorrected",
        r"mce.*Uncorrected error"
    ],
    "match_all": [
        r"UE|Uncorrected"
    ],
    "exclude": [
        r"Corrected error, no action required"
    ],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27072", "ORA-01578", "ORA-00600"]
}
```

### KERNEL_NULL_PTR_DEREF
```python
"KERNEL_NULL_PTR_DEREF": {
    "match_any": [
        r"BUG: unable to handle kernel NULL pointer dereference",
        r"kernel NULL pointer dereference at 0x0+\d+",
        r"Oops: 0000 \[#\d+\] SMP",
        r"IP:.*qla2xxx_eh_abort",
        r"RIP:.*qla2xxx"
    ],
    "match_all": [
        r"BUG:|Oops:"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "module_extract": r"Modules linked in:.*?(qla2xxx|lpfc|bnx2)\w*",
    "ora_codes_triggered": ["ORA-27072"]   # indirect — HBA crash causes EIO
}
```

### SELINUX_BLOCKING
```python
"SELINUX_BLOCKING": {
    "match_any": [
        r"avc: denied \{ (read|write|open|connectto|execute) \}.*comm=\"oracle\"",
        r"avc: denied.*scontext=.*oracle_db_t",
        r"avc: denied.*tcontext=.*oracle",
        r"type=AVC.*oracle.*denied",
        r"avc: denied \{ read \}.*comm=\"tnslsnr\""
    ],
    "match_all": [
        r"avc: denied"
    ],
    "exclude": [
        r"permissive=1"   # permissive mode — logged but not blocked
    ],
    "log_sources": ["AUDIT_LOG"],
    "severity": "ERROR",
    "operation_extract": r"avc: denied \{ (\w+) \}",
    "ora_codes_triggered": ["ORA-27300", "ORA-27301", "ORA-27302"]
}
```

### SYSTEMD_LIMITS_OVERRIDE
```python
"SYSTEMD_LIMITS_OVERRIDE": {
    "match_any": [
        r"error: open: Too many open files.*errno: 24",
        r"oracle.*Too many open files",
        r"Could not open.*trace.*Too many open files"
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "ERROR",
    "confirm_by": "cat /proc/$(pgrep -f oracle)/limits | grep 'open files'",
    "ora_codes_triggered": ["ORA-27300", "ORA-27301"]
}
```

### AUDITD_SUSPEND
```python
"AUDITD_SUSPEND": {
    "match_any": [
        r"auditd.*Audit daemon is suspending logging due to low disk space",
        r"kernel: audit: audit_backlog=\d+ > audit_backlog_limit=",
        r"kernel: audit: audit_lost=\d+",
        r"kernel: audit: backlog limit exceeded"
    ],
    "match_all": [
        r"auditd|audit:"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "ERROR",
    "ora_codes_triggered": []   # no ORA code — OS-level only
}
```

### NUMA_IMBALANCE
```python
"NUMA_IMBALANCE": {
    "match_any": [
        r"NUMA: node \d+ has no memory.*cross-node allocation",
        r"page allocation failure: order:\d+.*nodemask=",
        r"warn_alloc.*cannot allocate.*nodemask"
    ],
    "match_all": [
        r"NUMA|nodemask"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "ERROR",
    "ora_codes_triggered": []   # performance only — no ORA code
}
```

### EDAC_CE_MEMORY
```python
"EDAC_CE_MEMORY": {
    "match_any": [
        r"EDAC MC\d+: \d+ CE memory read error",
        r"mcelog: Memory corrected error count.*\d{4,}"   # large CE count
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "WARNING",
    "ora_codes_triggered": []
}
```

---

## SECTION 5: NETWORK PATTERNS

### BONDING_FAILOVER_EVENT
```python
"BONDING_FAILOVER_EVENT": {
    "match_any": [
        r"bonding: bond\d+: link status definitely down for interface eth\d+, disabling it",
        r"bonding: bond\d+: making interface eth\d+ the new active one",
        r"bonding: bond\d+: link status definitely up for interface eth\d+",
        r"bond\d+: Warning: the permanent HWaddr"
    ],
    "match_all": [
        r"bonding.*bond\d+"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "ERROR",
    "interface_extract": r"bond(\d+)",
    "ora_codes_triggered": ["ORA-03113"]
}
```

### BOTH_NICS_DOWN
```python
"BOTH_NICS_DOWN": {
    "match_any": [
        r"bonding: bond\d+: Warning: No active slaves\. Using last resort",
        r"NIC.*Link is Down.*eth0",
        r"bnx2.*eth\d+: NIC Copper Link is Down"
    ],
    "match_all": [],
    "exclude": [
        r"link status definitely up"   # recovery
    ],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-03113", "ORA-12541"]
}
```

### NF_CONNTRACK_FULL
```python
"NF_CONNTRACK_FULL": {
    "match_any": [
        r"nf_conntrack: nf_conntrack: table full, dropping packet",
        r"nf_conntrack.*table full"
    ],
    "match_all": [
        r"nf_conntrack"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-12541", "ORA-12170", "ORA-03113"]
}
```

### IB_LINK_DEGRADED
```python
"IB_LINK_DEGRADED": {
    "match_any": [
        r"mlx4_en: mlx4_en_restart_port called for ib\d+",
        r"mlx4.*command 0x\w+ failed: fw status",
        r"ib\d+: Link Speed: 10 Gb/s \(disabled 40Gb\)",
        r"mlx4_core.*MSI-X vectors number.*allocated by OS"
    ],
    "match_all": [
        r"ib\d+|mlx4|InfiniBand"
    ],
    "exclude": [
        r"Link Speed: 40 Gb/s"   # full speed — not degraded
    ],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "ERROR",
    "interface_extract": r"(ib\d+)",
    "ora_codes_triggered": []   # gc wait increase — no ORA code
}
```

### NTP_TIME_JUMP
```python
"NTP_TIME_JUMP": {
    "match_any": [
        r"chronyd.*System clock wrong by \d+\.\d+ seconds",
        r"chronyd.*Forward time jump detected",
        r"chronyd.*System clock was stepped by \d+\.\d+ seconds",
        r"ntpd.*time stepped by \d+\.\d+",
        r"kernel:.*Clock: inserting leap second"
    ],
    "match_all": [
        r"chronyd|ntpd|time.*step|clock.*step"
    ],
    "exclude": [
        r"System clock wrong by 0\.\d+"   # sub-second adjustment is fine
    ],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "step_extract": r"stepped by (\d+\.\d+) seconds",
    "ora_codes_triggered": ["ORA-29740"]   # after CRS eviction
}
```

### IPTABLES_BLOCKING_1521
```python
"IPTABLES_BLOCKING_1521": {
    "match_any": [
        r"FINAL_REJECT:.*DPT=1521",
        r"FINAL_REJECT:.*DPT=1522",
        r"kernel:.*DROP.*DPT=1521",
        r"kernel:.*REJECT.*DPT=1521"
    ],
    "match_all": [
        r"DPT=152[12]"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "ERROR",
    "src_ip_extract": r"SRC=(\d+\.\d+\.\d+\.\d+)",
    "ora_codes_triggered": ["ORA-12541", "ORA-12170"]
}
```

### NFS_MOUNT_TIMEOUT
```python
"NFS_MOUNT_TIMEOUT": {
    "match_any": [
        r"kernel: nfs: server \S+ not responding, timed out",
        r"kernel: nfs: server \S+ not responding, still trying",
        r"kernel: nfs: server \S+ OK"   # recovery message
    ],
    "match_all": [
        r"nfs: server"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "server_extract": r"nfs: server (\S+) not responding",
    "ora_codes_triggered": ["ORA-27054", "ORA-00257", "ORA-03113"]
}
```

### UDP_BUFFER_OVERFLOW
```python
"UDP_BUFFER_OVERFLOW": {
    "match_any": [
        r"^\s+\d{3,} packet receive errors",
        r"^\s+\d{3,} receive buffer errors"
    ],
    "match_all": [],
    "exclude": [
        r"^\s+0 packet receive errors"
    ],
    "log_sources": ["NETSTAT_S_OUTPUT"],
    "severity": "ERROR",
    "threshold_value": 100,
    "ora_codes_triggered": []   # gc block loss — no ORA code
}
```

### SOCKET_EXHAUSTION
```python
"SOCKET_EXHAUSTION": {
    "match_any": [
        r"TCP:.*alloc (\d+)",   # compare to tcp_max_orphans
        r"TCP.*inuse (\d{4,})"
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["SOCKSTAT_OUTPUT"],
    "severity": "ERROR",
    "threshold_field": "tcp_alloc",
    "threshold_pct": 0.95,   # 95% of tcp_max_orphans
    "ora_codes_triggered": ["ORA-12519", "ORA-12520"]
}
```

### TCP_KEEPALIVE_FIREWALL
```python
"TCP_KEEPALIVE_FIREWALL": {
    "match_any": [],   # not directly visible in logs
    "match_all": [],
    "exclude": [],
    "log_sources": ["PROC_SYS"],
    "severity": "WARNING",
    "confirm_by": "sysctl net.ipv4.tcp_keepalive_time",
    "threshold_field": "tcp_keepalive_time",
    "threshold_value": 900,   # > 15 minutes = risk if firewall timeout < 15min
    "ora_codes_triggered": ["ORA-03113"]
}
```

### NIC_RX_DROPS_HIGH
```python
"NIC_RX_DROPS_HIGH": {
    "match_any": [
        r"RX:.*errors\s+\d{3,}",
        r"RX:.*dropped\s+\d{3,}",
        r"RX:.*overrun\s+\d{2,}"
    ],
    "match_all": [],
    "exclude": [
        r"errors\s+0\s+dropped\s+0"
    ],
    "log_sources": ["IP_LINK_OUTPUT"],
    "severity": "ERROR",
    "interface_extract": r"(\w+): <BROADCAST",
    "threshold_fields": ["rx_errors", "rx_dropped"],
    "threshold_value": 100,
    "ora_codes_triggered": []   # gc block lost — no ORA code directly
}
```

---

## SECTION 6: ORACLE ALERT.LOG REGEX PATTERNS

### These extract structured data FROM alert.log chunks

```python
ALERT_LOG_PATTERNS = {

    # Standalone timestamp line (chunk boundary marker)
    "TIMESTAMP_LINE": r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\d{4}$",

    # ORA error code
    "ORA_CODE": r"(ORA-\d{5})",

    # Linux errno line
    "LINUX_ERRNO": r"Linux-x86_64 Error: (\d+): (.+)",

    # Additional info lines
    "ADDITIONAL_INFO": r"Additional information: (\d+)",

    # Trace file reference
    "TRACE_FILE": r"Errors in file (.+\.trc):",

    # Instance startup/shutdown
    "INSTANCE_START": r"Starting ORACLE instance \((\w+)\)",
    "INSTANCE_SHUTDOWN": r"Shutting down instance \((\w+)\)",
    "INSTANCE_ABNORMAL": r"Instance terminated by (ORADISM|MMON|USER|PMON|LGWR)",

    # Archiver messages
    "ARCHIVER_STUCK": r"ARC\d+: Archival stopped, error occurred\. Will continue retrying",
    "ARCHIVER_ERROR": r"ARCH: Archival Error, archivelog dest \d+ has become inactive",
    "ARCHIVER_SPACE": r"ORA-00257.*archiver error",

    # ASM messages
    "ASM_DISMOUNT": r"ORA-15130.*diskgroup.*being dismounted",
    "ASM_PATH_FAIL": r"ASM: disk.*path.*failed",

    # CRS related in alert.log
    "INSTANCE_EVICTED": r"ORA-29740.*Evicted by member",

    # Background process death
    "BGPROCESS_DIED": r"(LGWR|DBWR|MMON|PMON|SMON|CKPT|ARC\d+).*process \d+ died"
}
```

---

## SECTION 7: METRIC THRESHOLD PATTERNS (No Regex — Numeric Comparison)

### For iostat, sar, vmstat, df — pattern matched by field value comparison

```python
METRIC_PATTERNS = {

    "IOSTAT_HIGH_AWAIT": {
        "source": "IOSTAT_OUTPUT",
        "field": "await_ms",
        "operator": ">",
        "threshold": 100,
        "severity_map": {
            100: "WARNING",
            200: "ERROR",
            500: "CRITICAL"
        },
        "ora_codes_triggered": []   # slow I/O — no ORA code unless timeout
    },

    "IOSTAT_FULL_UTIL": {
        "source": "IOSTAT_OUTPUT",
        "field": "util_pct",
        "operator": ">=",
        "threshold": 95,
        "severity": "CRITICAL",
        "ora_codes_triggered": []
    },

    "SAR_CPU_IDLE_ZERO": {
        "source": "SAR_CPU_OUTPUT",
        "field": "idle_pct",
        "operator": "<",
        "threshold": 5,
        "severity": "CRITICAL",
        "ora_codes_triggered": []
    },

    "SAR_STEAL_HIGH": {
        "source": "SAR_CPU_OUTPUT",
        "field": "steal_pct",
        "operator": ">",
        "threshold": 20,
        "severity": "ERROR",
        "ora_codes_triggered": []
    },

    "SAR_RUNQUEUE_HIGH": {
        "source": "SAR_Q_OUTPUT",
        "field": "runq_sz",
        "threshold_formula": "runq_sz > 2 * cpu_count",
        "severity": "CRITICAL",
        "ora_codes_triggered": []
    },

    "VMSTAT_SWAP_ACTIVE": {
        "source": "VMSTAT_OUTPUT",
        "fields": ["si", "so"],
        "operator": ">",
        "threshold": 500,
        "severity": "CRITICAL",
        "ora_codes_triggered": ["ORA-04031"]
    },

    "VMSTAT_IOWAIT_HIGH": {
        "source": "VMSTAT_OUTPUT",
        "field": "wa",
        "operator": ">",
        "threshold": 30,
        "severity": "ERROR",
        "ora_codes_triggered": []
    },

    "DF_FILESYSTEM_FULL": {
        "source": "DF_OUTPUT",
        "field": "use_pct",
        "operator": ">=",
        "threshold": 100,
        "severity": "CRITICAL",
        "ora_codes_triggered": ["ORA-00257"]
    }
}
```

---

## SECTION 8: COMPLETE PATTERN INDEX (Quick Reference)

| Pattern ID | Type | Log Source | ORA Codes Triggered |
|---|---|---|---|
| SCSI_DISK_TIMEOUT | REGEX | /var/log/messages | ORA-27072, ORA-15080 |
| FC_HBA_RESET | REGEX | /var/log/messages | ORA-27072, ORA-15080 |
| MULTIPATH_ALL_PATHS_DOWN | REGEX | /var/log/messages | ORA-15080, ORA-15130 |
| IO_QUEUE_TIMEOUT | REGEX | /var/log/messages | ORA-27072, ORA-15080 |
| EXT4_JOURNAL_ABORT | REGEX | /var/log/messages | ORA-00257, ORA-19809 |
| XFS_FILESYSTEM_SHUTDOWN | REGEX | /var/log/messages | ORA-27072 |
| FILESYSTEM_ARCH_FULL | REGEX | df output | ORA-00257, ORA-19504 |
| FILESYSTEM_ANY_FULL | REGEX | df output | ORA-00257, ORA-27040 |
| SMARTCTL_PENDING_SECTOR | REGEX | smartctl output | ORA-27072, ORA-01578 |
| ISCSI_SESSION_FAIL | REGEX | /var/log/messages | ORA-27072, ORA-15080 |
| LVM_DEVICE_FAIL | REGEX | /var/log/messages | ORA-27072, ORA-00257 |
| DM_MULTIPATH_IO_ERROR | REGEX | /var/log/messages | ORA-15080, ORA-00470 |
| OOM_KILLER_ACTIVE | REGEX | /var/log/messages | ORA-00603, ORA-07445 |
| CGROUP_OOM_KILL | REGEX | /var/log/messages | None (CRS crash) |
| SHMGET_EINVAL | REGEX | /var/log/messages | ORA-27102 |
| HUGEPAGES_FREE_ZERO | REGEX | /proc/meminfo | ORA-27102, ORA-04031 |
| MEMORY_SWAP_STORM | METRIC | vmstat | ORA-04031 |
| SEMAPHORE_LIMIT_EXHAUSTED | REGEX | /var/log/messages | ORA-27300/27301/27302 |
| FD_LIMIT_EXHAUSTED | REGEX | /var/log/messages | ORA-27300/27301/27302 |
| MEMLOCK_ULIMIT_TOO_LOW | REGEX | /var/log/messages | ORA-27125 |
| DEVSHM_TOO_SMALL | REGEX | /var/log/messages | ORA-27102 |
| THP_LATENCY_STALL | REGEX | /var/log/messages | None |
| CPU_RUNQUEUE_SATURATION | METRIC | sar -q | None |
| CPU_STEAL_TIME | METRIC | sar -u | None |
| SOFT_LOCKUP | REGEX | /var/log/messages | None |
| HARD_LOCKUP | REGEX | /var/log/messages | None |
| KERNEL_PANIC | REGEX | /var/log/messages | None |
| MCE_CORRECTED_MEMORY | REGEX | /var/log/messages | None |
| MCE_UNCORRECTED_MEMORY | REGEX | /var/log/messages | ORA-27072, ORA-01578 |
| KERNEL_NULL_PTR_DEREF | REGEX | /var/log/messages | ORA-27072 |
| SELINUX_BLOCKING | REGEX | audit.log | ORA-27300/27301/27302 |
| SYSTEMD_LIMITS_OVERRIDE | REGEX | /var/log/messages | ORA-27300/27301 |
| AUDITD_SUSPEND | REGEX | /var/log/messages | None |
| NUMA_IMBALANCE | REGEX | /var/log/messages | None |
| BONDING_FAILOVER_EVENT | REGEX | /var/log/messages | ORA-03113 |
| BOTH_NICS_DOWN | REGEX | /var/log/messages | ORA-03113, ORA-12541 |
| NF_CONNTRACK_FULL | REGEX | /var/log/messages | ORA-12541, ORA-12170 |
| IB_LINK_DEGRADED | REGEX | /var/log/messages | None |
| NTP_TIME_JUMP | REGEX | /var/log/messages | ORA-29740 |
| IPTABLES_BLOCKING_1521 | REGEX | /var/log/messages | ORA-12541, ORA-12170 |
| NFS_MOUNT_TIMEOUT | REGEX | /var/log/messages | ORA-27054, ORA-00257 |
| UDP_BUFFER_OVERFLOW | METRIC | netstat -su | None |
| SOCKET_EXHAUSTION | METRIC | /proc/net/sockstat | ORA-12519, ORA-12520 |
| TCP_KEEPALIVE_FIREWALL | METRIC | sysctl | ORA-03113 |
| NIC_RX_DROPS_HIGH | METRIC | ip -s link | None |

**Total: 45 patterns (35 regex + 10 metric threshold)**
