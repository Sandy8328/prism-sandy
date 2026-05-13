# Regex Pattern Library — Part 1
## Disk + Memory + CPU Patterns
## Oracle DBA RAG Agent | Temperature: 0.0
## These regexes are used in Stage 6 (Pattern Scoring) of the retrieval pipeline

---

## HOW THIS IS USED IN CODE

```python
# Each OS_ERROR_PATTERN has:
#   MATCH_ANY  → chunk matches pattern if ANY one regex matches (presence of error)
#   MATCH_ALL  → all regexes must match for HIGH confidence score
#   EXCLUDE    → if this regex matches, pattern is disqualified

PATTERN_REGEX = {
    "PATTERN_ID": {
        "match_any": [r"regex1", r"regex2"],   # 1 match = pattern detected
        "match_all": [r"regex_a", r"regex_b"], # all must match for 100% score
        "exclude":   [r"regex_x"],             # disqualifies if matched
        "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],  # which logs to search
        "severity": "CRITICAL"
    }
}
```

---

## SECTION 1: DISK / I-O PATTERNS

### SCSI_DISK_TIMEOUT
```python
"SCSI_DISK_TIMEOUT": {
    "match_any": [
        r"sd\s+\d+:\d+:\d+:\d+:.*FAILED Result:.*DRIVER_TIMEOUT",
        r"sd\s+\d+:\d+:\d+:\d+:.*FAILED Result:.*DID_TIME_OUT",
        r"blk_update_request: I/O error, dev sd[a-z]+",
        r"Buffer I/O error on dev sd[a-z]+, logical block",
        r"sd\s+\d+:\d+:\d+:\d+: \[sd[a-z]+\] Stopping disk",
        r"sd\s+\d+:\d+:\d+:\d+: \[sd[a-z]+\] timing out command, waited \d+s",
        r"sd\s+\d+:\d+:\d+:\d+: \[sd[a-z]+\] Sense Key\s*:\s*Hardware Error",
        r"sd\s+\d+:\d+:\d+:\d+: \[sd[a-z]+\] Add\. Sense: Internal target failure",
        r"sd\s+\d+:\d+:\d+:\d+: rejecting I/O to offline device",
        r"sd\s+\d+:\d+:\d+:\d+: Device offlined"
    ],
    "match_all": [
        r"sd\s+\d+:\d+:\d+:\d+:.*FAILED",
        r"I/O error"
    ],
    "exclude": [
        r"Synchronizing SCSI cache"   # recovery message, not an error
    ],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "device_extract": r"\[sd([a-z]+)\]",
    "ora_codes_triggered": ["ORA-27072", "ORA-15080", "ORA-00353"]
}
```

### FC_HBA_RESET
```python
"FC_HBA_RESET": {
    "match_any": [
        r"qla2xxx.*LOGO nexus reestablished",
        r"qla2xxx.*PLOGI IOCB timeout",
        r"qla2xxx.*Adapter reset issued nexus=",
        r"qla2xxx.*Adapter aborted all outstanding I/O",
        r"qla2xxx.*Abort ISP active.*Resetting",
        r"qla2xxx.*kill adapter.*command timeout",
        r"qla2xxx.*FW responded with invalid status",
        r"lpfc.*LOGO received from NPIV",
        r"lpfc.*Link Down Event",
        r"lpfc.*0x102 Lost connection",
        r"scsi host\d+: qla2xxx: Link Up"   # recovery — use to bound event
    ],
    "match_all": [
        r"qla2xxx|lpfc"    # must be FC HBA driver
    ],
    "exclude": [
        r"Ready to login"   # recovery only, no error
    ],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "device_extract": r"qla2xxx \[([0-9a-f:\.]+)\]",
    "ora_codes_triggered": ["ORA-27072", "ORA-15080", "ORA-00353"]
}
```

### MULTIPATH_ALL_PATHS_DOWN
```python
"MULTIPATH_ALL_PATHS_DOWN": {
    "match_any": [
        r"multipathd.*remaining active paths: 0",
        r"multipathd.*Fail all paths",
        r"multipathd.*path.*is down",
        r"multipathd.*Failing path \d+:\d+",
        r"multipathd.*Changing queueing policy to 'fail'",
        r"device-mapper: multipath: Failing path \d+:\d+",
        r"device-mapper: ioctl: error adding target to table",
        r"multipathd.*queue_if_no_path feature set, IO queued"
    ],
    "match_all": [
        r"multipathd|multipath"
    ],
    "exclude": [
        r"remaining active paths: [1-9]"   # still has active paths
    ],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "device_extract": r"(mpatha?\w*): remaining",
    "ora_codes_triggered": ["ORA-15080", "ORA-15040", "ORA-15130"]
}
```

### IO_QUEUE_TIMEOUT
```python
"IO_QUEUE_TIMEOUT": {
    "match_any": [
        r"blk_queue_timeout: request timeout \d+ ms for dev sd[a-z]+",
        r"blk_abort_request: blk abort request",
        r"scsi_abort_command: abort SCSI cmd",
        r"scsi: ABORT SUCCESS \[scsi target",
        r"sd\s+\d+:\d+:\d+:\d+: \[sd[a-z]+\].*uas_eh_abort_handler",
        r"sd\s+\d+:\d+:\d+:\d+: \[sd[a-z]+\] Aborting command"
    ],
    "match_all": [
        r"abort|timeout"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "device_extract": r"for dev (sd[a-z]+)",
    "ora_codes_triggered": ["ORA-27072", "ORA-15080"]
}
```

### EXT4_JOURNAL_ABORT
```python
"EXT4_JOURNAL_ABORT": {
    "match_any": [
        r"EXT4-fs error.*ext4_journal_check_start.*Detected aborted journal",
        r"EXT4-fs \(.*\): Remounting filesystem read-only",
        r"EXT4-fs error.*bad block bitmap checksum",
        r"EXT4-fs error.*Checksum bad",
        r"JBD2: recovery failed",
        r"EXT4-fs.*error loading journal",
        r"EXT4-fs error.*ext4_find_entry.*reading directory lblock"
    ],
    "match_all": [
        r"EXT4-fs"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "device_extract": r"EXT4-fs error \(device ([\w-]+)\)",
    "ora_codes_triggered": ["ORA-00257", "ORA-19809", "ORA-16038"]
}
```

### XFS_FILESYSTEM_SHUTDOWN
```python
"XFS_FILESYSTEM_SHUTDOWN": {
    "match_any": [
        r"XFS \([\w\d]+\): metadata I/O error in .* error \d+",
        r"XFS \([\w\d]+\): Filesystem has been shut down due to log error",
        r"XFS \([\w\d]+\): log I/O error",
        r"XFS \([\w\d]+\): Please unmount the filesystem",
        r"XFS \([\w\d]+\): xfs_inode_item_push: push error"
    ],
    "match_all": [
        r"XFS"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "device_extract": r"XFS \(([\w\d]+)\):",
    "ora_codes_triggered": ["ORA-27072"]
}
```

### FILESYSTEM_ARCH_FULL
```python
"FILESYSTEM_ARCH_FULL": {
    "match_any": [
        r"/arch\s+.*\s+100%",
        r"100%\s+/arch",
        r"/arch.*Available\s+0",
        r"Filesystem.*100%.*arch"
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["DF_OUTPUT"],
    "severity": "CRITICAL",
    "device_extract": r"(/\S*arch\S*)",
    "ora_codes_triggered": ["ORA-00257", "ORA-19504", "ORA-16038"]
}
```

### FILESYSTEM_ANY_FULL
```python
"FILESYSTEM_ANY_FULL": {
    "match_any": [
        r"\s+100%\s+/",
        r"\s+9[5-9]%\s+/"
    ],
    "match_all": [],
    "exclude": [
        r"tmpfs|devtmpfs|udev"   # ignore tmpfs
    ],
    "log_sources": ["DF_OUTPUT"],
    "severity": "ERROR",
    "device_extract": r"\d+%\s+(/\S+)",
    "threshold_field": "use_pct",
    "threshold_value": 95,
    "ora_codes_triggered": ["ORA-00257", "ORA-19504", "ORA-27040"]
}
```

### SMARTCTL_PENDING_SECTOR
```python
"SMARTCTL_PENDING_SECTOR": {
    "match_any": [
        r"SMART overall-health self-assessment test result: FAILED",
        r"Drive failure expected in less than 24 hours",
        r"197 Current_Pending_Sector.*[1-9]\d*$",
        r"198 Offline_Uncorrectable.*[1-9]\d*$",
        r"ATA Error Count: [1-9]\d*"
    ],
    "match_all": [
        r"SMART|smartctl"
    ],
    "exclude": [
        r"test result: PASSED"
    ],
    "log_sources": ["SMARTCTL_OUTPUT"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27072", "ORA-01578"]
}
```

### ISCSI_SESSION_FAIL
```python
"ISCSI_SESSION_FAIL": {
    "match_any": [
        r"iscsid:.*connection timed out",
        r"iscsid: detected conn error \(\d+\)",
        r"iscsid.*initiator reported error.*8",
        r"kernel:.*ping timeout of \d+ secs expired",
        r"kernel: scsi \d+:\d+:\d+:\d+: rejecting I/O to dead device",
        r"kernel: sd \d+:\d+:\d+:\d+: \[sd[a-z]+\] killing request"
    ],
    "match_all": [
        r"iscsid|iscsi"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27072", "ORA-15080"]
}
```

### LVM_DEVICE_FAIL
```python
"LVM_DEVICE_FAIL": {
    "match_any": [
        r"device-mapper: table:.*dm-linear: Device lookup failed",
        r"device-mapper: ioctl: error adding target to table",
        r"EXT4-fs error.*delayed block allocation failed.*error -5",
        r"EXT4-fs.*This should not happen!! Data will be lost",
        r"EXT4-fs error.*unable to read itable block"
    ],
    "match_all": [
        r"device-mapper|dm-"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "device_extract": r"device (dm-\d+)",
    "ora_codes_triggered": ["ORA-27072", "ORA-00257"]
}
```

### DM_MULTIPATH_IO_ERROR
```python
"DM_MULTIPATH_IO_ERROR": {
    "match_any": [
        r"device-mapper: multipath: Failing path \d+:\d+\.",
        r"multipathd.*mpatha?: remaining active paths: 0",
        r"multipathd.*IO queued"
    ],
    "match_all": [],
    "exclude": [
        r"remaining active paths: [1-9]"
    ],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-15080", "ORA-15041", "ORA-00470"]
}
```

---

## SECTION 2: MEMORY PATTERNS

### OOM_KILLER_ACTIVE
```python
"OOM_KILLER_ACTIVE": {
    "match_any": [
        r"oracle invoked oom-killer",
        r"oom-killer: gfp_mask=.*oracle",
        r"Memory cgroup out of memory: Kill process \d+ \(oracle\)",
        r"Killed process \d+ \(oracle\) total-vm:",
        r"oom_reaper: reaped process \d+ \(oracle\)",
        r"Out of memory: Kill process.*oracle"
    ],
    "match_all": [
        r"oracle"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "pid_extract": r"Kill(?:ed)? process (\d+)",
    "ora_codes_triggered": ["ORA-00603", "ORA-07445"]
}
```

### CGROUP_OOM_KILL
```python
"CGROUP_OOM_KILL": {
    "match_any": [
        r"oracle-ohasd\.service: A process.*killed by the OOM killer",
        r"oracle-ohasd\.service: Failed with result 'oom-kill'",
        r"systemd.*oracle-ohasd\.service: Main process exited.*status=9/KILL",
        r"Failed to start OHAS Daemon"
    ],
    "match_all": [
        r"oracle-ohasd"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": []   # CRS crash — no ORA code in DB alert.log
}
```

### SHMGET_EINVAL
```python
"SHMGET_EINVAL": {
    "match_any": [
        r"shmget.*errno=22.*Invalid argument",
        r"Cannot create shared memory segment.*size=\d+",
        r"kernel: shm: shm_tot.*exceeds shm_ctlmax",
        r"shmget.*failed.*errno = 28.*ENOSPC"
    ],
    "match_all": [
        r"shmget"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27102"]
}
```

### HUGEPAGES_FREE_ZERO
```python
"HUGEPAGES_FREE_ZERO": {
    "match_any": [
        r"HugePages_Free:\s+0",
        r"hugetlb: allocating \d+ of page size.*failed",
        r"HugePages allocation failed",
        r"ORION: HugePages allocation failed"
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "PROC_MEMINFO"],
    "severity": "ERROR",
    "ora_codes_triggered": ["ORA-27102", "ORA-04031"]
}
```

### MEMORY_SWAP_STORM
```python
"MEMORY_SWAP_STORM": {
    "match_any": [
        r"^\s*\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+[5-9]\d{2,}\s+[5-9]\d{2,}"
        # vmstat: si or so column > 500
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VMSTAT_OUTPUT"],
    "severity": "CRITICAL",
    "threshold_fields": ["si", "so"],
    "threshold_value": 500,
    "ora_codes_triggered": ["ORA-04031"]   # indirect
}
```

### SEMAPHORE_LIMIT_EXHAUSTED
```python
"SEMAPHORE_LIMIT_EXHAUSTED": {
    "match_any": [
        r"semget.*errno=28.*No space left on device",
        r"Unable to allocate semaphore set.*semmni limit reached",
        r"semget.*failed.*ENOSPC"
    ],
    "match_all": [
        r"semget"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27300", "ORA-27301", "ORA-27302"]
}
```

### FD_LIMIT_EXHAUSTED
```python
"FD_LIMIT_EXHAUSTED": {
    "match_any": [
        r"error: open: Too many open files.*errno: 24",
        r"Could not open.*trace.*Too many open files",
        r"VFS: file-max limit \d+ reached",
        r"open.*failed.*status: 24",
        r"Too many open files \(errno: 24\)"
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27300", "ORA-27301", "ORA-27302"]
}
```

### MEMLOCK_ULIMIT_TOO_LOW
```python
"MEMLOCK_ULIMIT_TOO_LOW": {
    "match_any": [
        r"ORADISM.*mlock failed with errno=1.*EPERM",
        r"ORADISM: shmctl\(SHM_LOCK\) failed with errno=12",
        r"Cannot lock SGA: Operation not permitted",
        r"oradism.*SGA will not be memory-locked"
    ],
    "match_all": [
        r"ORADISM|oradism"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "ERROR",
    "ora_codes_triggered": ["ORA-27125"]
}
```

### DEVSHM_TOO_SMALL
```python
"DEVSHM_TOO_SMALL": {
    "match_any": [
        r"shmget.*errno = 28.*ENOSPC.*dev.shm",
        r"Cannot create SGA segment.*No space left on device.*dev.shm",
        r"oracle.*shmget.*failed.*errno = 28",
        r"ORA-27102.*Additional information:.*103079"  # 96GB SGA in bytes
    ],
    "match_all": [],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "CRITICAL",
    "ora_codes_triggered": ["ORA-27102"]
}
```

### THP_LATENCY_STALL
```python
"THP_LATENCY_STALL": {
    "match_any": [
        r"khugepaged: huge page allocated",
        r"page allocation failure: order:9.*GFP_KERNEL.*__GFP_COMP",
        r"THP allocation failed due to page fragmentation",
        r"khugepaged: scan_sleep_millisecs="
    ],
    "match_all": [
        r"khugepaged|THP|transparent_hugepage"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES"],
    "severity": "WARNING",
    "ora_codes_triggered": []   # no direct ORA code — AWR impact only
}
```

---

## SECTION 3: CPU PATTERNS

### CPU_RUNQUEUE_SATURATION
```python
"CPU_RUNQUEUE_SATURATION": {
    "match_any": [],   # No log message — detected from metrics only
    "match_all": [],
    "exclude": [],
    "log_sources": ["SAR_Q_OUTPUT"],
    "severity": "ERROR",
    "threshold_fields": ["runq-sz"],
    "threshold_formula": "runq_sz > 2 * cpu_count",
    "ora_codes_triggered": []   # AWR impact only — no ORA code
}
```

### CPU_STEAL_TIME
```python
"CPU_STEAL_TIME": {
    "match_any": [],
    "match_all": [],
    "exclude": [],
    "log_sources": ["SAR_CPU_OUTPUT"],
    "severity": "ERROR",
    "threshold_fields": ["%steal"],
    "threshold_value": 20,
    "ora_codes_triggered": []
}
```

### SOFT_LOCKUP
```python
"SOFT_LOCKUP": {
    "match_any": [
        r"BUG: soft lockup - CPU#\d+ stuck for \d+s! \[oracle:\d+\]",
        r"BUG: soft lockup - CPU#\d+ stuck for \d+s!.*oracle",
        r"soft lockup.*oracle.*stuck"
    ],
    "match_all": [
        r"soft lockup"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "pid_extract": r"\[oracle:(\d+)\]",
    "ora_codes_triggered": []   # process hangs — no ORA code unless escalates
}
```

### HARD_LOCKUP
```python
"HARD_LOCKUP": {
    "match_any": [
        r"Watchdog detected hard LOCKUP on cpu \d+",
        r"NMI backtrace for cpu \d+",
        r"native_queued_spin_lock_slowpath"
    ],
    "match_all": [
        r"hard LOCKUP|LOCKUP on cpu"
    ],
    "exclude": [],
    "log_sources": ["VAR_LOG_MESSAGES", "DMESG"],
    "severity": "CRITICAL",
    "ora_codes_triggered": []
}
```
