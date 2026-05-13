# Multi-Platform Support Documentation
## Oracle DBA Agent — Platform Differences and Handling Strategy
## Temperature: 0.0 | No Code

---

## PLATFORMS ORACLE RUNS ON (All Need Support)

```
Platform 1: Oracle Enterprise Linux / RHEL (our current design)
Platform 2: AIX (IBM)                      ← user has this (dpump script)
Platform 3: Solaris (Oracle/Sun)
Platform 4: HP-UX (HP)
Platform 5: Windows Server
Platform 6: Oracle Exadata (specialized)
Platform 7: Oracle Cloud (OCI) / AWS RDS
Platform 8: Middleware hosts (WebLogic, Forms)
```

---

## PLATFORM DETECTION — How the Agent Knows Which OS

### From AHF/TFA Collection (automatic)
```
AHF ZIP always contains: os/uname.txt or os/osinfo.txt

Linux:   Linux dbhost01 5.4.17-2136.315.5.el8uek.x86_64 #2 SMP x86_64 GNU/Linux
AIX:     AIX dbhost01 3 7 00F84C994C00
Solaris: SunOS dbhost01 5.11 11.4.42.111.0 sun4v sparc sun4v

Detection regex:
  r'^Linux'    → PLATFORM = "LINUX"
  r'^AIX'      → PLATFORM = "AIX"
  r'^SunOS'    → PLATFORM = "SOLARIS"
  r'^HP-UX'    → PLATFORM = "HPUX"
  r'^Windows'  → PLATFORM = "WINDOWS"
```

### From Manual Log Paste (user declares or system infers)
```
If log line matches: "IBM AIX RISC System"  → AIX
If log line matches: "SunOS"                → Solaris
If log line matches: "Linux-x86_64 Error:"  → Linux
If log line matches: "Windows Error:"        → Windows
If cannot detect: ask DBA to select platform from dropdown
```

---

## PLATFORM 1: LINUX (OEL / RHEL) — Current Design

```
Log locations:        /var/log/messages, dmesg, /var/log/audit/audit.log
Disk naming:          sdb, sdc, nvme0n1, dm-2, mpatha
Memory commands:      free, /proc/meminfo, vmstat
CPU commands:         sar -u, top, /proc/cpuinfo
Storage commands:     iostat, multipath -ll, smartctl
Cluster:              CRS/Grid (ocssd.log, crsd.log)
Filesystem:           ext4, XFS, tmpfs
Errno format:         "Linux-x86_64 Error: 5: Input/output error"
ORA-27xxx:            "Linux-x86_64 Error: N: description"
FULLY DOCUMENTED:     YES
```

---

## PLATFORM 2: AIX — Critical Gaps

### Log Locations (completely different from Linux)
```
/var/adm/syslog/syslog.log      ← equivalent of /var/log/messages
/var/adm/ras/errlog             ← BINARY error log (need errpt to read)
/var/adm/wtmp                   ← login records
/var/log/syslog (AIX 7.2+)     ← newer AIX only

Read errlog with:
  errpt -a | head -200           ← full detailed errors
  errpt -aJ | grep -i oracle     ← oracle-related only
  errpt -a -s MMDDHHMMYY         ← since specific time
```

### AIX Disk Naming (different from Linux)
```
Linux:  sdb, sdc, sdd, nvme0n1, dm-2, mpatha
AIX:    hdisk0, hdisk1, hdisk2   ← raw disks
        /dev/rvg01/lvol1          ← LVM volumes
        /dev/rhdisk0              ← raw device

AIX MPIO paths (not device-mapper):
  lspath -l hdisk1               ← list paths to hdisk1
  lspath -l hdisk1 -F"name:state" ← path state
  lsvg -l datavg                 ← list LVM volume group
```

### AIX Memory (different concepts)
```
Linux:  swap, /proc/meminfo, vmstat si/so columns
AIX:    paging space (not swap — different concept)
        lsps -s                   ← paging space summary
        vmstat 1 5                ← similar format BUT field order differs!
        svmon -G                  ← system virtual memory overview
        topas                     ← AIX top equivalent

AIX vmstat output differs:
  Linux:  r  b   swpd   free   buff  cache   si   so    bi    bo
  AIX:    r  b   avm    fre     re   pi   po   fr   sr  cy
          ↑ different columns — si/so NOT same position
```

### AIX CPU (different concepts)
```
Linux:  sar -u, %steal, %idle
AIX:    lparstat 1 5              ← LPAR CPU statistics
        topas                     ← like top
        sar -u (available but output differs)

LPAR-specific concept (no Linux equivalent):
  %entc = entitled capacity used  ← AIX equivalent of %steal
  If %entc > 100% = CPU capped by hypervisor (like Linux %steal)
  
lparstat output:
  System configuration: type=Shared mode=Uncapped smt=4 lcpu=8 mem=32768
  %user %sys %wait %idle physc %entc lbusy  app  vcsw phint
   82.1   8.2   1.2   8.5  3.98  99.5  73.4   --  9821   812
```

### AIX Error Log Format (errpt output)
```
LABEL:          DISK_ERR7
IDENTIFIER:     B5757C89
Date/Time:      Mon Apr 21 03:14:18 IST 2024
Sequence Number: 18821
Machine Id:     00F84C994C00
Node Id:        dbhost01
Class:          H                     ← H=Hardware S=Software O=Operator
Type:           PERM                  ← PERM=permanent TEMP=temporary
Resource Name:  hdisk1

Description
DISK OPERATION ERROR

Probable Causes
DASD DEVICE

Failure Causes
DISK DEVICE

Recommended Actions
PERFORM PROBLEM DETERMINATION PROCEDURES

Detail Data
SENSE DATA
0000 0000 0000 0000 0000 0000 0000 0000
```

### AIX ORA Code Format (different from Linux)
```
Linux format:
  ORA-27072: File I/O error
  Linux-x86_64 Error: 5: Input/output error

AIX format:
  ORA-27072: File I/O error
  IBM AIX RISC System/6000 Error: 5: Input/output error
  ↑ Same ORA code, DIFFERENT OS label

AIX errno values (mostly same as Linux but confirm):
  EIO=5, ENOMEM=12, EACCES=13, EINVAL=22, ENOSPC=28 — SAME as Linux
  But AIX has additional errno codes Linux doesn't have:
  ENOTREADY=16 → device not ready (AIX-specific)
  EFORMAT=71   → bad format (AIX-specific)
```

### AIX Storage Error Patterns (different regex needed)
```
SCSI/disk errors in errpt (not in /var/log/messages):

Label: DISK_ERR7 → disk I/O error (AIX equivalent of SCSI_DISK_TIMEOUT)
Label: DISK_ERR1 → disk operation error
Label: SC_DISK_ERR2 → SCSI disk error

Path failure (MPIO):
  lspath shows: hdisk1 path /dev/fscsi0/XXXXXXXX Enabled → Failed

Log keywords to match in errpt output:
  "DISK OPERATION ERROR"
  "PATH HAS FAILED"
  "DISK ERR"
  "SCSI COMMAND FAILED"
```

### AIX Filesystem
```
Linux:  ext4, XFS
AIX:    JFS (Journaled File System)
        JFS2 (Enhanced JFS — most common in modern AIX)

JFS2 errors appear in errlog:
  Label: JFS_ERROR → journal error
  Label: JFS2_ERROR → JFS2 error

df output on AIX (different):
  Filesystem    512-blocks      Free %Used Iused %Iused Mounted on
  /dev/hd4          262144    196608   25%  4322    10% /
  ← Block size is 512 bytes (not 1K like Linux df -h)
```

### AIX Network (similar to Linux but different commands)
```
Linux:  ip link show, ethtool, netstat
AIX:    netstat -i                    ← interface stats
        entstat -d en0 | grep Error  ← NIC errors (like ethtool)
        ifconfig en0                  ← interface config
        no -o udp_recvspace          ← UDP buffer (like sysctl)
        no -o tcp_keepalive          ← keepalive (like sysctl)
        
AIX network error format in errpt:
  Label: CHRP_PCI_ERR9 → PCIe adapter error (like bnx2 errors in Linux)
  Label: EN_LINK_DOWN  → network link down
```

---

## PLATFORM 3: SOLARIS

### Log Locations
```
/var/adm/messages               ← similar to Linux /var/log/messages
/var/log/syslog                 ← syslog (Solaris 11)
fmadm faulty                   ← Fault Management (hardware faults)
fmdump -e                      ← FMA event dump

Solaris has FMA (Fault Management Architecture):
  Hardware faults go to FMA, not to /var/adm/messages
  DBA must check BOTH /var/adm/messages AND fmadm faulty
```

### Solaris Disk Naming
```
Linux:  sdb, sdc
Solaris SPARC: c0t0d0, c0t1d0   ← controller/target/disk
Solaris x86:   c3t0d0, c4t0d0
Solaris with ZFS: /dev/dsk/c3t0d0s0

Multipath (Solaris MPxIO):
  luxadm probe              ← list storage devices
  mpathadm show initiator-port ← path status
```

### Solaris ORA Code Format
```
ORA-27072: File I/O error
Solaris-x86 Error: 5: Input/output error
  OR
SunOS-5.11 Error: 5: Input/output error
  ↑ Different OS label again
```

### Solaris-Specific Errors
```
FMA fault detected:
  fmadm: ereport.io.scsi.disk.cksum         ← disk checksum error
  fmadm: ereport.io.scsi.cmd.disk.dev.rqs   ← SCSI request sense
  fmadm: fault.io.scsi.disk.predictive-failure ← disk pre-fail

These are equivalent to AIX errpt DISK_ERR labels.
Must extract these patterns for Solaris platform.
```

### Solaris Memory
```
Linux:  /proc/meminfo, vmstat si/so
Solaris: vmstat (similar format)
         swap -l                   ← swap space
         prtconf | grep Memory     ← total memory
         mdb -k ::memstat          ← detailed memory stats
```

---

## PLATFORM 4: HP-UX (Less Common Now)

### Key Differences
```
Log:     /var/adm/syslog/syslog.log
Errors:  /var/adm/crash/*           ← crash dumps
Disk:    /dev/dsk/c0t0d0            ← similar to Solaris
Memory:  vmstat, swapinfo -tam
CPU:     sar, top, glance           ← HP-UX specific tool
Network: netstat, lanscan, lanadmin
FibreChannel: ioscan -fnC tape      ← HBA listing

ORA code format:
  HP-UX Error: 5: I/O error
```

---

## PLATFORM 5: WINDOWS SERVER

### Key Differences
```
Log:    Windows Event Viewer (NOT text files)
        Event IDs, not syslog format at all
        Exportable to .evtx or .csv

Disk:   Event ID 7 in System log = disk error
        Event ID 11 = driver detected a controller error
        diskpart, Get-Disk (PowerShell)

Memory: Event ID 1001 = crash dump
        Performance Monitor (perfmon)

Network: Event ID 4226 = TCP connection limit

ORA code format (Windows):
  ORA-27072: File I/O error
  OSD-04008: WriteFile() failure, unable to write to file
  O/S-Error: (OS 5) Access is denied.
  O/S-Error: (OS 112) There is not enough space on the disk.
  ↑ Completely different format! "O/S-Error" not "Linux-x86_64 Error"
  ↑ Windows error codes (not Unix errno)
```

### Windows-Specific ORA Codes
```
ORA-27069: skgfdisp: attempt to do I/O beyond the range of the file
ORA-27071: unable to seek to block in file
OSD-04006: ReadFile() failure, unable to read from file
OSD-04008: WriteFile() failure, unable to write to file
OSD-04018: unable to access file
```

---

## PLATFORM 6: ORACLE EXADATA

### Architecture
```
Exadata has TWO types of nodes:
  1. Database nodes  → run Oracle DB (standard OEL Linux)
  2. Storage cells   → run Oracle Linux with cell software

Database nodes: same as standard Linux — our current design works
Storage cells:  completely different log location and format
```

### Exadata Cell Node Logs
```
/opt/oracle/cell/log/diag/asm/cell/<hostname>/alert/log.xml
/opt/oracle/cell/log/diag/asm/cell/<hostname>/trace/

Cell errors accessed via cellcli:
  cellcli -e list celldisk detail
  cellcli -e list griddisk attributes name,status,asmDiskgroupName
  cellcli -e list alerthistory where severity='critical'

Exadata-specific ORA codes:
  ORA-15750: ... (Exadata smart scan)
  ORA-12801: error signaled in parallel query server
  Cell offload errors appear in alert.log as ORA-12805
```

### Exadata InfiniBand (different from RAC InfiniBand)
```
Exadata uses InfiniBand between compute and storage cells.
Errors here = storage access errors, not just interconnect slowness.

ibstat shows: Active, but cell communication errors in:
  /var/log/oracle-validated
  cellcli alerthistory
```

---

## PLATFORM 7: MIDDLEWARE (WebLogic, Oracle Forms, etc.)

### WebLogic Server Logs
```
Location: $DOMAIN_HOME/servers/<server_name>/logs/
Files:
  <server_name>.log   ← main server log
  access.log          ← HTTP access log
  <server_name>.out   ← stdout/stderr

Log format (different from Oracle alert.log):
  ####<Apr 21, 2024 3:14:18,821 AM IST> <Error> <JDBC>
  <dbhost01> <AdminServer> <[ACTIVE] ExecuteThread: '0'>
  <<WLS Kernel>> <> <> <1713667458821>
  <BEA-001112> <Test "TestDS" JDBC connection failed.>
  ↑ WLS error code BEA-XXXXXX (not ORA-XXXXX)

WLS JDBC errors that surface ORA codes:
  BEA-001112 → wraps ORA-12541 (cannot connect to listener)
  BEA-001128 → wraps ORA-01033 (Oracle initializing/shutting down)
  BEA-000628 → wraps ORA-03113 (connection dropped)
```

### Connection Pool Exhaustion (Middleware-specific)
```
WebLogic connection pool errors:
  BEA-001112: Could not obtain connection from datasource: oracle.jdbc.pool...
  Caused by: java.sql.SQLRecoverableException: ORA-12541: TNS:no listener

These appear in WLS log, NOT in Oracle alert.log.
The ORA code is buried inside WLS error message.
Regex needed:
  r'BEA-\d{6}.*ORA-\d{5}'  ← extract both WLS and ORA codes
```

---

## PLATFORM ADAPTATION STRATEGY FOR OUR AGENT

### Layer 1: Platform Detector (new module needed)
```
New file: src/parsers/platform_detector.py

Input: log line sample OR uname.txt content
Output: {
  platform: "LINUX" | "AIX" | "SOLARIS" | "HPUX" | "WINDOWS" | "EXADATA" | "MIDDLEWARE"
  os_version: "8.6" | "7.2" | "11.4" | ...
  arch: "x86_64" | "RISC" | "SPARC" | "PA-RISC" | "x86"
}
```

### Layer 2: Platform-Specific Parser (existing parsers extended)
```
Instead of one syslog_parser.py, we need:

syslog_parser.py      → Linux /var/log/messages
aix_errpt_parser.py   → AIX errpt output (new)
solaris_log_parser.py → Solaris /var/adm/messages + FMA (new)
windows_event_parser.py → Windows Event Log CSV export (new)
exadata_cell_parser.py  → cellcli alerthistory output (new)
wls_log_parser.py       → WebLogic server.log (new)
```

### Layer 3: Platform-Specific Patterns (regex library extended)
```
Each OS_ERROR_PATTERN needs platform variants:

SCSI_DISK_TIMEOUT:
  linux:   r"sd\s+\d+:\d+:\d+:\d+:.*FAILED Result:.*DRIVER_TIMEOUT"
  aix:     r"DISK_ERR7.*DISK OPERATION ERROR"   (from errpt)
  solaris: r"ereport.io.scsi.disk|scsi.*cmd.*disk.*dev"  (from fmadm)
  windows: r"Event ID 11.*controller error"

ORA_CODE_ERRNO_LINE:
  linux:   r"Linux-x86_64 Error: (\d+): (.+)"
  aix:     r"IBM AIX RISC System/6000 Error: (\d+): (.+)"
  solaris: r"SunOS-\S+ Error: (\d+): (.+)"
  hpux:    r"HP-UX Error: (\d+): (.+)"
  windows: r"O/S-Error: \(OS (\d+)\) (.+)"
```

### Layer 4: Platform-Specific Diagnostic Commands
```
Each FIX_COMMAND needs platform variants:

FIX_CHECK_DISK_HEALTH:
  linux:   "smartctl -a /dev/sdb"
  aix:     "errpt -a | grep -A20 DISK_ERR"
  solaris: "fmadm faulty; fmdump -e | grep disk"
  windows: "Get-WmiObject -Query 'SELECT * FROM MSFT_StorageDiagnosticRecord'"

FIX_CHECK_MEMORY:
  linux:   "grep -i hugepage /proc/meminfo; vmstat 1 5"
  aix:     "svmon -G; lsps -s; lparstat 1 5"
  solaris: "prtconf | grep Memory; swap -l; vmstat 1 5"
  windows: "Get-WMIObject Win32_PhysicalMemory"

FIX_CHECK_PATHS:
  linux:   "multipath -ll"
  aix:     "lspath -l hdisk1; lsvg -l datavg"
  solaris: "mpathadm show initiator-port"
  windows: "Get-MPIOAvailableHW"
```

---

## WHAT THIS MEANS FOR OUR ARCHITECTURE

### New Required Components

```
1. Platform Detector Module (NEW)
   src/parsers/platform_detector.py

2. Platform-Specific Parser Modules (NEW)
   src/parsers/aix_errpt_parser.py
   src/parsers/solaris_log_parser.py
   src/parsers/windows_event_parser.py
   src/parsers/exadata_cell_parser.py
   src/parsers/wls_log_parser.py

3. Platform Variants in Pattern Library (EXTEND existing)
   patterns.json needs "platform_variants" per pattern

4. Platform Variants in Fix Commands (EXTEND existing)
   graph.json needs platform-specific commands per fix node

5. Platform field in chunk metadata (EXTEND schema)
   Add "platform": "LINUX|AIX|SOLARIS|..." to chunk JSON

6. Platform filter in DuckDB (EXTEND schema)
   Add "platform" column to chunks table
   Pre-filter: WHERE platform = 'AIX' for AIX queries
```

### Seed Data Needs Platform Coverage
```
Currently: 85 errors, all Linux format
Needed:    + AIX format equivalents
           + Solaris format equivalents
           (Windows and HP-UX lower priority)

AIX seed data to add:
  - errpt DISK_ERR7 output (= SCSI timeout on AIX)
  - errpt MPIO path failure (= multipath fail on AIX)
  - lparstat showing CPU entitlement exceeded
  - svmon showing paging space exhausted
  - ORA-27072 with "IBM AIX RISC System/6000 Error: 5"
  Estimated: ~20 additional AIX-specific chunks

Solaris seed data to add:
  - fmadm ereport.io.scsi.disk output
  - Solaris vmstat paging output
  - ORA-27072 with "SunOS-5.11 Error: 5"
  Estimated: ~15 additional Solaris-specific chunks
```

---

## PRIORITY ORDER FOR PLATFORM SUPPORT

```
Phase 1 (now):   Linux OEL/RHEL — FULLY DOCUMENTED
Phase 2 (next):  AIX             — user has this, needs documentation
Phase 3 (later): Solaris         — less common but Oracle-owned
Phase 4 (later): Exadata         — Oracle-specific hardware
Phase 5 (later): Windows         — completely different stack
Phase 6 (later): Middleware      — separate concern (WLS not OS)
Phase 7 (later): HP-UX           — very rare now, declining
```

---

## AIX-SPECIFIC SEED DATA NEEDED (Top Priority)

| # | AIX Error | Equivalent Linux Error | ORA Code |
|---|---|---|---|
| AIX-01 | errpt: DISK_ERR7 on hdisk1 | SCSI_DISK_TIMEOUT | ORA-27072 |
| AIX-02 | lspath: hdisk1 path Failed | MULTIPATH_PATH_FAIL | ORA-27072 |
| AIX-03 | lparstat: %entc > 100% | CPU_STEAL_TIME | Does Not Exist |
| AIX-04 | svmon: paging space > 90% | MEMORY_SWAP_STORM | ORA-04031 |
| AIX-05 | errpt: EN_LINK_DOWN en0 | BONDING_FAILOVER | ORA-03113 |
| AIX-06 | errpt: AIX OOM (no direct equiv) | OOM_KILLER | ORA-00603 |
| AIX-07 | lsps -s: PP SIZE 100% | FILESYSTEM_PAGING_FULL | ORA-04031 |
| AIX-08 | errpt: JFS2_ERROR | EXT4_JOURNAL_ABORT | ORA-00257 |
| AIX-09 | ORA-27072 "IBM AIX RISC" | All DISK patterns | ORA-27072 |
| AIX-10 | fcstat fcs0: link errors | FC_HBA_RESET | ORA-27072 |
