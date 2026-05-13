# Windows + Exadata + Middleware — Critical Error Logs
## 25 Authentic Errors Across 3 Platforms
## Temperature: 0.0

---

## WINDOWS-01: DISK I/O ERROR (Event ID 11)
**ORA Code: ORA-27072**
```
# Windows System Event Log (exported CSV format)
Level,Date and Time,Source,Event ID,Task Category
Error,4/21/2024 3:14:18 AM,disk,11,None
"The driver detected a controller error on \Device\Harddisk1\DR1."

Error,4/21/2024 3:14:18 AM,Disk,7,None
"The device \Device\Harddisk1\DR1 has a bad block."

# Oracle alert.log on Windows
Mon Apr 21 03:14:19 2024
ORA-27072: File I/O error
OSD-04008: WriteFile() failure, unable to write to file
O/S-Error: (OS 5) Access is denied.
```

---

## WINDOWS-02: DISK FULL — Archive Destination
**ORA Code: ORA-00257**
```
# Windows Event Log
Error,4/21/2024 3:14:18 AM,NTFS,55,None
"The file system structure on the disk is corrupt and unusable.
Please run the chkdsk utility on the volume E:."

# Or simply — disk full:
Error,4/21/2024 3:14:18 AM,Application,1001,None
"Disk E: is full. Available: 0 bytes."

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-00257: archiver error. Connect internal only, until freed.
OSD-04018: unable to access file "E:\oracle\arch\1_18821_1234.arc"
O/S-Error: (OS 112) There is not enough space on the disk.
```

---

## WINDOWS-03: ORACLE SERVICE KILLED BY WINDOWS (OOM)
**ORA Code: ORA-00603**
```
# Windows System Event Log
Critical,4/21/2024 3:14:18 AM,Microsoft-Windows-Resource-Exhaustion-Detector,2004,None
"Windows successfully diagnosed a low virtual memory condition.
The following programs consumed the most virtual memory:
oracle.exe (PID 18821) consumed 98,304 MB of virtual memory."

Error,4/21/2024 3:14:19 AM,Application Error,1000,None
"Faulting application name: oracle.exe, version: 19.0.0.0.0
Exception code: 0xc0000005 (Access Violation)"

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-00603: ORACLE server session terminated by fatal error
ORA-27504: IPC error creating OSD context
```

---

## WINDOWS-04: SGA CREATION FAILURE (Windows large pages)
**ORA Code: ORA-27102**
```
# Oracle startup on Windows
Mon Apr 21 03:14:18 2024
Starting ORACLE instance (normal)
ORA-27102: out of memory
OSD-00022: Message 22 not found; product=RDBMS; facility=SOSD
O/S-Error: (OS 1450) Insufficient system resources exist to complete the requested service.

# Cause: "Lock Pages in Memory" privilege not granted to Oracle service account
# Fix via Local Security Policy → User Rights Assignment → Lock pages in memory
# Add: OracleServicePROD account

# Verify in Windows:
# whoami /priv | findstr SeLockMemoryPrivilege
SeLockMemoryPrivilege             Enabled   ← must be Enabled
```

---

## WINDOWS-05: NETWORK FAILURE (NIC Teaming down)
**ORA Code: ORA-03113**
```
# Windows System Event Log
Warning,4/21/2024 3:14:17 AM,Microsoft-Windows-NDIS,10317,None
"Miniport Microsoft Network Adapter Multiplexor Driver,
{GUID}, had its network link status changed to NotPresent."

Error,4/21/2024 3:14:18 AM,Microsoft-Windows-NdisImPlatform,10319,None
"Miniport Microsoft Network Adapter Multiplexor Driver,
{GUID}, had its network connection removed."

# Oracle sqlnet.log on Windows
***********************************************************************
Fatal NI connect error 12537, connecting to:
(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=dbhost01)(PORT=1521)))
VERSION INFORMATION:
TNS for MS Windows: Version 19.0.0.0.0
O/S Roles: Winnt
Time: 21-APR-2024 03:14:19
Tracing to file: C:\oracle\network\trace\sqlnet.trc
TNS-12537: TNS:connection closed
TNS-12560: TNS:protocol adapter error
TNS-00507: Connection closed
```

---

## WINDOWS-06: ORACLE TABLESPACE AUTOEXTEND HITS DISK LIMIT
**ORA Code: ORA-01653 / ORA-01654**
```
# Windows Event Log
Error,4/21/2024 3:14:18 AM,Application,1000,None
"oracle.exe failed to extend datafile C:\oracle\data\users01.dbf.
O/S-Error: (OS 112) There is not enough space on the disk."

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-01653: unable to extend table HR.EMPLOYEES by 128 in tablespace USERS
OSD-04008: WriteFile() failure, unable to write to file
O/S-Error: (OS 112) There is not enough space on the disk.
```

---

## WINDOWS-07: ANTIVIRUS BLOCKING ORACLE FILES
**ORA Code: ORA-27041 / ORA-01157**
```
# Windows Security Event Log
Warning,4/21/2024 3:14:18 AM,Microsoft-Windows-Windows Defender,1116,None
"Microsoft Defender Antivirus has detected malware or other potentially
unwanted software. File: C:\oracle\oradata\PROD\SYSTEM01.DBF
Action: Quarantine."

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-01157: cannot identify/lock data file 1 - see DBWR trace file
ORA-01110: data file 1: 'C:\oracle\oradata\PROD\SYSTEM01.DBF'
OSD-04002: unable to open file
O/S-Error: (OS 32) The process cannot access the file because
it is being used by another process.
```

---

## WINDOWS-08: ORACLE RAC ON WINDOWS — CLUSTER NETWORK FAILURE
**ORA Code: ORA-29740**
```
# Windows Failover Cluster Event Log
Error,4/21/2024 3:14:18 AM,Microsoft-Windows-FailoverClustering,1127,None
"The cluster network 'Cluster Network 2' is down.
Node dbhost02 lost connectivity to cluster network."

Error,4/21/2024 3:14:21 AM,Microsoft-Windows-FailoverClustering,1069,None
"Cluster resource 'Oracle VSS Writer PROD' in clustered service or
application 'OraclePROD' failed."

# Oracle alert.log
Mon Apr 21 03:14:22 2024
ORA-29740: evicted by member 0, group incarnation 7
```

---

## WINDOWS-09: VIRTUAL DISK SERVICE ERROR (vDS)
**ORA Code: ORA-27072**
```
# Windows System Event Log
Error,4/21/2024 3:14:18 AM,volmgr,46,None
"Crash dump initialization failed."

Error,4/21/2024 3:14:18 AM,disk,51,None
"An error was detected on device \Device\Harddisk1\DR1 during a paging operation."

# iSCSI Initiator event
Error,4/21/2024 3:14:17 AM,Microsoft-Windows-iScsiPrt,70,None
"Initiator failed to connect to the target. Target IP address and
TCP Port number are given in the dump data."

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-27072: File I/O error
OSD-04008: WriteFile() failure, unable to write to file
O/S-Error: (OS 1117) The request could not be performed because of an I/O device error.
```

---

## WINDOWS-10: ORACLE LISTENER FAILS TO START (Port Conflict)
**ORA Code: ORA-12541**
```
# listener.log on Windows
21-APR-2024 03:14:18 * (CONNECT_DATA=...) * establish * PROD * 12541
TNS-12541: TNS:no listener
TNS-01106: Listener using listener name LISTENER has already been started

# Windows Event Log — port conflict
Error,4/21/2024 3:14:15 AM,Tcpip,4227,None
"TCP/IP has reached the security limit imposed on the number of concurrent
TCP connect attempts. Port 1521 is already in use by PID 4 (System)."

# Check: netstat -ano | findstr :1521
TCP    0.0.0.0:1521    0.0.0.0:0    LISTENING    18821
```

---

## EXADATA-01: CELL DISK FAILURE (Exadata Storage Cell)
**ORA Code: ORA-15080**
```
# cellcli -e list alerthistory where severity='critical' on cell01
       name:                   "AFR_2024-04-21T03:14:18_dbhost01"
       alertType:              Stateful
       examinedBy:             Oracle Support
       message:                "Flash disk FD_00_cell01 failed"
       metricObjectName:       FD_00_cell01
       notificationState:      0
       sequenceNumber:         18821
       severity:               critical
       alertShortName:         AFR

# cellcli -e list celldisk detail on cell01
       name:                   FD_00_cell01
       cellDiskType:           FlashDisk
       deviceName:             /dev/nvme0n1
       diskType:               FlashDisk
       errorCount:             182
       freeSpace:              0
       id:                     cell01_fd_00
       interDiskBandwidth:     0.000 MB/s
       physicalSize:           1.82 TB
       status:                 failed             ← FAILED

# Oracle ASM alert.log
Mon Apr 21 03:14:19 2024
ORA-15080: synchronous I/O request to a disk failed
ORA-15081: failed to submit an I/O operation to a disk
NOTE: initiating force dismount of group DATA
```

---

## EXADATA-02: EXADATA SMART SCAN FAILURE (Cell Offload Error)
**ORA Code: ORA-12801**
```
# alert.log on Exadata DB node
Mon Apr 21 03:14:18 2024
ORA-12801: error signaled in parallel query server P004, instance prod1:1
ORA-12805: parallel query server died unexpectedly

# Exadata cell log
# tail -100 /opt/oracle/cell/log/diag/asm/cell/cell01/alert/log.xml
<msg time='2024-04-21T03:14:17.821+05:30' org_id='oracle' comp_id='cell'
     msg_id='821' type='INCIDENT_ERROR' group='Automatic_Storage_Management'
     level='1' host_id='cell01' host_addr='192.168.10.11'>
<txt>Cell SMART SCAN operation failed: ORA-03113 received from compute node</txt>
</msg>

# cellcli showing failed offload
cellcli -e list iormplan
  status: active
  objective: latency
  # cell01 not participating — compute node lost connectivity to cell
```

---

## EXADATA-03: EXADATA INFINIBAND FAILURE (Compute to Cell)
**ORA Code: ORA-15080 (I/O to ASM)**
```
# /var/log/messages on Exadata DB node
Apr 21 03:14:16 dbnode01 kernel: mlx4_en: mlx4_en_restart_port called for ib0
Apr 21 03:14:16 dbnode01 kernel: mlx4_core: command 0x26 failed GEN HW failure
Apr 21 03:14:17 dbnode01 ibacm: addr_preload: ibacm_enum_ep failed for ib0

# rdma cm connection to cell01 lost
Apr 21 03:14:17 dbnode01 kernel: RDMA/cm: addr_resolve failed to cell01
Apr 21 03:14:18 dbnode01 oracleasm: ASM disk /dev/oracleasm/disks/DATA_0001
       I/O failed: connection to cell01 unavailable

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-15080: synchronous I/O request to a disk failed
ORA-15081: failed to submit an I/O operation to a disk
NOTE: all I/O to disk group DATA is failing
```

---

## EXADATA-04: EXADATA IORM THROTTLING (I/O Resource Manager)
**ORA Code: Does Not Exist (silent degradation)**
```
# cellcli showing IORM throttling
cellcli -e list iormplan detail
       name:             default
       objective:        latency
       status:           active

cellcli -e list iormplan -xml
  databasePlan: prod_db: share=8 limit=50    ← PROD limited to 50% I/O
                dev_db:  share=2 limit=20

# IORM limiting PROD to 50% cell I/O bandwidth — no ORA code raised
# AWR shows: "cell smart table scan" wait time > 500ms
# DBA must check cellcli, not Oracle alert.log

# Exadata-specific AWR wait events:
  cell smart table scan          8821    4821.2    547.3   ← high avg wait
  cell single block physical read 18821   821.2     44.1
```

---

## EXADATA-05: EXADATA ROLLING PATCH FAILURE
**ORA Code: CRS-2674 / ORA-29740**
```
# During Exadata rolling patch on dbnode02:
2024-04-21 03:14:18 [CRSD]CRS-2674: Start of 'ora.dbnode02.vip' on 'dbnode02' failed
2024-04-21 03:14:19 [CRSD]CRS-2632: There are no more servers to try to place
       resource 'ora.prod.db' on that would satisfy its placement policy
2024-04-21 03:14:21 [CSSD]CRS-1618: Node dbnode02 is not responding to heartbeat.

# Oracle alert.log on surviving node
Mon Apr 21 03:14:22 2024
ORA-29740: evicted by member 1, group incarnation 12
```

---

## MIDDLEWARE-01: WEBLOGIC JDBC CONNECTION POOL EXHAUSTED
**ORA Code: ORA-12519 (inside WLS error)**
```
# WebLogic server.log ($DOMAIN_HOME/servers/AdminServer/logs/AdminServer.log)
####<Apr 21, 2024 3:14:18,821 AM IST> <Error> <JDBC> <dbhost01> <AdminServer>
<[ACTIVE] ExecuteThread: '8' for queue: 'weblogic.kernel.Default'>
<<WLS Kernel>> <> <> <1713666858821> <BEA-001112>
<Test "PRODDataSource" JDBC connection test failed with the following exception:
java.sql.SQLRecoverableException: ORA-12519: TNS:no appropriate service handler found>

####<Apr 21, 2024 3:14:21,821 AM IST> <Error> <JDBC> <dbhost01> <AdminServer>
<<WLS Kernel>> <> <> <1713666861821> <BEA-001137>
<Failed to get a connection from the WebLogic connection pool "PRODDataSource".>

# WLS admin console shows:
  DataSource: PRODDataSource
  State: Running
  Active Connections: 100 / 100 (pool exhausted)
  Waiting Requests: 248
```

---

## MIDDLEWARE-02: WEBLOGIC NODE MANAGER FAILURE
**ORA Code: Does Not Exist (WLS-level, not DB-level)**
```
# NodeManager.log ($DOMAIN_HOME/nodemanager/nodemanager.log)
<Apr 21, 2024 3:14:18 AM IST> <Info> <weblogic.nodemanager.server>
<Server failed. Reason: Server output: Apr 21, 2024 3:14:18 AM
weblogic.server.AbstractServerService postInit
SEVERE: Failed to listen on channel "Default" on port 7001>

<Apr 21, 2024 3:14:19 AM IST> <Warning> <weblogic.nodemanager.server>
<Exception during server status check: Connection refused>

# Managed server ManagedServer1 failed to start
# WLS connections to Oracle DB dropped
# OS-level: port 7001 already in use
Apr 21 03:14:17 dbhost01 kernel: TCP: request_sock_TCP: Possible SYN flooding on port 7001
```

---

## MIDDLEWARE-03: WEBLOGIC JVM OUT OF MEMORY
**ORA Code: ORA-03113 (connections drop when JVM dies)**
```
# WLS server.log
####<Apr 21, 2024 3:14:18,821 AM IST> <Critical> <WebLogicServer> <dbhost01>
<ManagedServer1> <[STUCK] ExecuteThread: '0'> <<WLS Kernel>> <> <>
<1713666858821> <BEA-000337>
<[STUCK] ExecuteThread: '0' for queue: 'weblogic.kernel.Default'
has been busy for "600" seconds working on the request>

# JVM crash in native stderr log
# OutOfMemoryError
java.lang.OutOfMemoryError: Java heap space
        at java.util.Arrays.copyOf(Arrays.java:3210)
        at weblogic.jdbc.wrapper.ResultSet.getString(ResultSet.java:821)

# JVM crash causes all JDBC connections to drop
# Clients get ORA-03113 or ORA-17410 from JDBC driver
```

---

## MIDDLEWARE-04: WEBLOGIC STUCK THREAD — DB QUERY TIMEOUT
**ORA Code: ORA-01013 (user requested cancel)**
```
# WLS server.log
####<Apr 21, 2024 3:14:18,821 AM IST> <Warning> <WebLogicServer> <dbhost01>
<ManagedServer1> <Timer-3> <<WLS Kernel>> <> <> <1713666858821> <BEA-000337>
<[STUCK] ExecuteThread: '3' for queue: 'weblogic.kernel.Default'
has been busy for "600" seconds working on the request>

# Thread stack dump shows SQL wait:
"[STUCK] ExecuteThread: '3'" daemon prio=5 tid=0x00007f821 nid=0x18821
       waiting for monitor entry [0x00007f8218821000]
   java.lang.Thread.State: BLOCKED (on object monitor)
        at oracle.jdbc.driver.T4CStatement.executeForDescribe(T4CStatement.java:821)

# Oracle session shows:
SELECT * FROM V$SESSION WHERE STATUS='ACTIVE' AND USERNAME='APPUSER';
-- Session 821 running for 600 seconds on full-table-scan
-- No ORA code yet, but WLM will cancel with ORA-01013
```

---

## MIDDLEWARE-05: ORACLE FORMS — DATABASE CONNECTION FAILURE
**ORA Code: ORA-12541 / ORA-01017**
```
# Oracle Forms application server log
# $ORACLE_HOME/network/log/sqlnet.log
***********************************************************************
Fatal NI connect error 12541, connecting to:
(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=dbhost01)(PORT=1521))
(CONNECT_DATA=(SERVICE_NAME=PROD)))

VERSION INFORMATION:
TNS for Linux: Version 19.0.0.0.0
Time: 21-APR-2024 03:14:18
Tracing not turned on.
Tns error struct:
  ns main err code: 12541
  TNS-12541: TNS:no listener
  ns secondary err code: 12560
  TNS-12560: TNS:protocol adapter error

# /u01/oracle/network/log/listener.log
21-APR-2024 03:14:18 * (CONNECT_DATA=(SERVICE_NAME=PROD)) * 12518
TNS-12518: TNS:listener could not hand off client connection
TNS-12549: TNS:operating system resource quota exceeded
TNS-12560: TNS:protocol adapter error
TNS-00519: Operating system resource quota exceeded
Linux Error: 11: Resource temporarily unavailable   ← EMFILE — FD limit hit
```

---

## MIDDLEWARE-06: SOA SUITE — DB ADAPTER FAILURE
**ORA Code: ORA-04031 / ORA-04030**
```
# Oracle SOA Suite / OSB log
# $DOMAIN_HOME/servers/soa_server1/logs/soa_server1.log

####<Apr 21, 2024 3:14:18 AM IST> <Error> <oracle.soa.adapter>
<BEA-000000> <[DBAdapter] Database transaction rollback. SQL state: 72000.
Error: ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","unknown object","sga heap(1,0)","KKSSP")>

# SOA adapter retries 3 times then raises fault:
####<Apr 21, 2024 3:14:21 AM IST> <Error> <oracle.bpel.engine>
<BEA-000000> <Invoke activity "CallDB" raised a fault: DatabaseException:
ORA-04031 unable to allocate 65560 bytes of shared memory>
```

---

## MIDDLEWARE-07: ORACLE HTTP SERVER — PROCESS LIMIT HIT
**ORA Code: ORA-12519**
```
# Oracle HTTP Server (OHS) error log
# $ORACLE_HOME/ohs/logs/error_log
[Sun Apr 21 03:14:18.821 2024] [mpm_prefork:error] [pid 821] AH00161:
server reached MaxRequestWorkers setting, consider raising the MaxRequestWorkers
setting. Current: 256

[Sun Apr 21 03:14:19.821 2024] [proxy_http:error] [pid 18821] [client 192.168.1.100:821]
AH01099: header line too long, removing: (forwarded for)
AH00898: Error reading from remote server returned by /forms/frmservlet

# OHS cannot accept new requests
# All new client connections fail with "Service Unavailable"
# Oracle Forms DB connections then show stale → ORA-03113

# OS evidence:
Apr 21 03:14:18 dbhost01 kernel: nf_conntrack: table full, dropping packet
```

---

## MIDDLEWARE-08: OBIEE PRESENTATION SERVICE — DB TIMEOUT
**ORA Code: ORA-12170 (Connect timeout)**
```
# OBIEE Presentation Services log
# $ORACLE_INSTANCE/diagnostics/logs/OracleBIPS/obips1/nqserver.log
[2024-04-21 03:14:18] [OracleBIEEBase] [ERROR] [] [ecid: 821] 
nQSError: 17001: Oracle Error code: 12170, message:
ORA-12170: TNS:Connect timeout occurred
Physical Query Failed:
SELECT a.employee_id, a.salary FROM hr.employees a
Connection to physical DB PROD timed out after 60 seconds.

# OS cause: DB host under extreme CPU load (load avg 48.2 on 8-core system)
# Kernel cannot schedule Oracle listener process fast enough to respond
```

---

## MIDDLEWARE-09: ORACLE GOLDENGATE — EXTRACT ABEND
**ORA Code: ORA-01291 / ORA-00600**
```
# GoldenGate ggserr.log
2024-04-21 03:14:18 ERROR OGG-00519 Oracle GoldenGate Capture for Oracle,
ext1.prm: Fatal error at position 18821 in log file 18821, RBA 182182182.
Error fetching logminer record from online redo log:
ORA-01291: missing logfile

2024-04-21 03:14:18 ERROR OGG-01668 PROCESS ABENDED.

# Cause: Archivelog deleted before GoldenGate extracted it
# OS evidence:
find /arch -name "*.arc" -mtime +1 -delete   ← overly aggressive cleanup script
# /arch was at 95%, cron job deleted archivelogs GoldenGate still needed
```

---

## MIDDLEWARE-10: ORACLE DATA INTEGRATOR — DATABASE FULL DURING ETL
**ORA Code: ORA-01653 / ORA-00257**
```
# ODI Agent log
# $ODI_HOME/oracledi/agent/log/odiagent.log
2024-04-21 03:14:18 ERROR ODI-1217: Session LOAD_DIM_CUSTOMER (18821) fails with return code 7001.
ODI-1226: Step LOAD_DIM_CUSTOMER fails after 1 attempt(s).
ODI-1240: Flow LOAD_DIM_CUSTOMER FLOW fails.
Caused By: java.sql.SQLException: ORA-01653: unable to extend table ODI.SNP_LOC_TBL
by 128 in tablespace ODI_WORK

# Concurrent Oracle alert.log:
Mon Apr 21 03:14:18 2024
ORA-01653: unable to extend table ODI.SNP_LOC_TBL by 128 in tablespace ODI_WORK
ORA-01654: unable to extend index ODI.I_SNP_LOC_TBL by 64 in tablespace ODI_WORK

# OS cause: disk full — /u02/oradata mounted point at 100%
```
