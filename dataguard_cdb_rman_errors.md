# Gaps B, C, D — Data Guard + CDB/PDB + RMAN Errors
## Temperature: 0.0

---

# PART 1: DATA GUARD ERRORS (Gap B)

## DG-01: Archive Gap — Standby Falling Behind Primary
**ORA Code: ORA-16401**
```
# alert.log on STANDBY (stdby01)
Mon Apr 21 03:14:18 2024
FAL[client]: Failed to request gap sequence, error is:
ORA-16401: archivelog rejected by RFS

FAL[client]: All defined FAL servers have been attempted.
-------------------------------------------------------------
Check that the CONTROL_FILES initialization parameter is defined
and points to the correct controlfile.
-------------------------------------------------------------

# Concurrent on PRIMARY (prod01):
Mon Apr 21 03:14:18 2024
ARC1: Standby redo logfile selected for thread 1 sequence 18821
LGWR: Primary and standby databases are out of sync by 82 logs

# OS cause: Network between primary and standby:
Apr 21 03:14:16 stdby01 kernel: bonding: bond0: link status definitely down for interface eth1

# Diagnosis:
# On standby:
SELECT THREAD#, LOW_SEQUENCE#, HIGH_SEQUENCE# FROM V$ARCHIVE_GAP;
# Shows gap: THREAD=1, LOW=18740, HIGH=18821 (82 logs missing)
```

## DG-02: Redo Transport Failure — Network Issue
**ORA Code: ORA-16198 / ORA-12170**
```
# alert.log on PRIMARY
Mon Apr 21 03:14:18 2024
PING[ARC1]: Heartbeat failed to connect to standby 'STDBY'. Error is 12170.
ARC1: Failed to archive log 18 thread 1 sequence 18821 (12170)

ORA-16198: Timeout incurred on internal channel during remote archival
Error 12170 received logging on to the standby

Mon Apr 21 03:14:19 2024
LGWR: network I/O slave exited with error. LGWR will handle network I/O.

# Data Guard Broker log (drcPROD.log):
2024-04-21 03:14:18 * (CONNECT_DATA=(SERVICE_NAME=STDBY_DGMGRL)) * 16198
DGM-17016: failed to modify property LogXptMode of database PROD
ORA-16778: redo transport service for at least one database is not running

# OS cause (on primary side — network to standby):
Apr 21 03:14:16 prod01 kernel: nf_conntrack: nf_conntrack: table full, dropping packet
# Conntrack full = redo transport packets being dropped
```

## DG-03: Apply Lag — Standby Disk Full
**ORA Code: ORA-19809 / ORA-16014**
```
# alert.log on STANDBY
Mon Apr 21 03:14:18 2024
MRP0: Background Media Recovery terminated with error 19809
ORA-19809: limit exceeded for recovery files
ORA-19804: cannot reclaim 218103808 bytes disk space from 107374182400 limit

Mon Apr 21 03:14:18 2024
ORA-16014: log 18821 sequence# 18821 not archived, no available destinations

# Standby FRA (Fast Recovery Area) full:
# df -h /fra on standby
/dev/mapper/vg01-fra  200G  200G     0 100% /fra

# MRP (Managed Recovery Process) stopped applying redo
# Standby is falling behind — apply lag growing

# Check lag:
SELECT NAME, VALUE, DATUM_TIME FROM V$DATAGUARD_STATS
WHERE NAME IN ('apply lag', 'transport lag');
# apply lag: +00 04:21:18 (4 hours behind!)
```

## DG-04: Standby Redo Log Not Configured
**ORA Code: ORA-00313 / ORA-00312**
```
# alert.log on STANDBY (after switchover or fresh setup)
Mon Apr 21 03:14:18 2024
RFS[1]: Assigned to RFS process 18821
RFS[1]: No standby redo logfiles available for thread 1

ORA-00313: open failed for members of log group 4 of thread 2
ORA-00312: online log 4 thread 2: '/u01/oradata/STDBY/standby_redo04.log'
ORA-27037: unable to obtain file status

# Cause: Standby redo logs not created or wrong count
# Check:
SELECT GROUP#, TYPE, MEMBER FROM V$LOGFILE WHERE TYPE='STANDBY';
# Empty result = no standby redo logs = Data Guard cannot sync real-time

# Fix: Add standby redo logs
ALTER DATABASE ADD STANDBY LOGFILE THREAD 1
GROUP 10 ('/u01/oradata/STDBY/standby_redo10.log') SIZE 500M;
```

## DG-05: Switchover Failure — Primary Still Has Active Transactions
**ORA Code: ORA-16467 / ORA-10458**
```
# During planned switchover:
# On Primary:
SQL> ALTER DATABASE COMMIT TO SWITCHOVER TO STANDBY;
ALTER DATABASE COMMIT TO SWITCHOVER TO STANDBY
*
ERROR at line 1:
ORA-16467: switchover target is not synchronized

# Data Guard Broker:
DGMGRL> switchover to STDBY;
Performing switchover NOW, please wait...
Operation requires shutdown of instance "PROD" on database "PROD"
Error: ORA-10458: standby database requires recovery

ORA-01152: file 1 was not restored from a sufficiently old backup
ORA-01110: data file 1: '+DATA/PROD/DATAFILE/system.dbf'

# Cause: Apply lag > 0 at switchover time
# OS cause that created the lag:
Apr 21 03:14:16 stdby01 kernel: sd 2:0:0:0: [sdb] FAILED  ← disk issue on standby
# Standby fell behind because its disk had errors
```

---

# PART 2: CDB/PDB ERRORS (Gap C)

## PDB-01: PDB Storage Limit Exceeded
**ORA Code: ORA-65114 / ORA-01536**
```
# alert.log (CDB level — CDB$ROOT)
Mon Apr 21 03:14:18 2024
ORA-00604: error occurred at recursive SQL level 1
ORA-65114: space usage in container HRPDB is too high
ORA-01536: space quota exceeded for tablespace 'USERS' in HRPDB

# CDB alert.log shows which PDB:
Mon Apr 21 03:14:18 2024
PDB(HRPDB): ORA-01653: unable to extend table HR.EMPLOYEES by 128 in tablespace USERS

# Check PDB storage:
SELECT CON_ID, TABLESPACE_NAME, BYTES_USED, MAX_BYTES
FROM CDB_TS_QUOTAS WHERE CON_ID = (SELECT CON_ID FROM V$PDBS WHERE NAME='HRPDB');

# OS cause: datafile disk full
df -h /u01/oradata/  # check disk holding PDB datafiles
```

## PDB-02: PDB Cannot Open After CDB Restart
**ORA Code: ORA-01157 / ORA-65020**
```
# alert.log after CDB startup
Mon Apr 21 03:14:18 2024
Pluggable database HRPDB opening:
ORA-01157: cannot identify/lock data file 201 - see DBWR trace file
ORA-01110: data file 201: '/u01/oradata/HRPDB/users01.dbf'
ORA-27037: unable to obtain file status
Linux-x86_64 Error: 2: No such file or directory

# PDB stays MOUNTED not OPEN:
SELECT NAME, OPEN_MODE FROM V$PDBS;
# HRPDB    MOUNTED   ← should be READ WRITE

# OS cause: datafile accidentally deleted or disk not mounted
ls -la /u01/oradata/HRPDB/users01.dbf
# No such file or directory

# Or filesystem not mounted:
mount | grep /u01/oradata/HRPDB
# Nothing — mount point empty after OS restart
```

## PDB-03: CDB Shared Pool Exhausted by PDB Load
**ORA Code: ORA-04031**
```
# alert.log (CDB level)
Mon Apr 21 03:14:18 2024
ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","unknown object","CDB$ROOT sga heap(1,0)","KKSSP")

# CDB shares one shared pool across ALL PDBs
# HRPDB running heavy analytics consumed shared pool
# FINPDB suffered because shared pool exhausted

# Check PDB resource plan:
SELECT PLAN, STATUS FROM DBA_RSRC_PLANS WHERE STATUS='ACTIVE';
SELECT CON_NAME, SHARES, MEMORY_P1 FROM DBA_RSRC_PLAN_DIRECTIVES
WHERE PLAN='CDB_DEFAULT_PLAN';
# All PDBs getting equal share — no limit on HRPDB
# Fix: Add resource plan with memory_p1 limit per PDB

# OS cause: Shared pool contention + physical memory pressure
grep -i hugepage /proc/meminfo
# HugePages_Free: 0  ← SGA not using HugePages → fragmentation
```

## PDB-04: PDB Hit CPU Resource Plan Limit
**ORA Code: ORA-00054 / silent**
```
# alert.log in PDB (HRPDB alert log in PDB's trace dir)
Mon Apr 21 03:14:18 2024
ORA-00054: resource busy and acquire with NOWAIT specified or timeout expired

# AWR in CDB shows:
# HRPDB: CPU time = 100% of its allocation
# FINPDB: low CPU usage
# Total server CPU: 45% idle (plenty available!)

# CDB Resource Manager limiting HRPDB:
SELECT CONSUMER_GROUP_NAME, CPU_WAIT_TIME
FROM V$RSRC_CONSUMER_GROUP WHERE CON_ID > 2;
# HRPDB_GROUP: CPU_WAIT_TIME = 48821 centiseconds (4.8 seconds of CPU throttle)

# OS cause: CDB resource plan too restrictive
# Or: OS CPU steal (VMs stealing CPU from HRPDB's share)
sar -u 1 5 | grep -v '^$'
```

## PDB-05: PDB Unplugging Failure — Datafiles Active
**ORA Code: ORA-65142 / ORA-65145**
```
# DBA trying to unplug PDB for migration:
SQL> ALTER PLUGGABLE DATABASE HRPDB UNPLUG INTO '/tmp/hrpdb.xml';
ALTER PLUGGABLE DATABASE HRPDB UNPLUG INTO '/tmp/hrpdb.xml'
*
ERROR at line 1:
ORA-65142: user HRAPP has active sessions in pluggable database HRPDB

# After closing and trying again:
SQL> ALTER PLUGGABLE DATABASE HRPDB CLOSE IMMEDIATE;
SQL> ALTER PLUGGABLE DATABASE HRPDB UNPLUG INTO '/tmp/hrpdb.xml';

ERROR at line 1:
ORA-65145: pluggable database is not compatible with target CDB

# Compatibility check failure — version mismatch:
# Source CDB: 19.18.0.0.0
# Target CDB: 19.12.0.0.0 (older)
# Cannot plug 19.18 PDB into 19.12 CDB
```

---

# PART 3: RMAN BACKUP ERRORS (Gap D)

## RMAN-01: FRA Full — Backup Cannot Complete
**ORA Code: ORA-19809 / RMAN-03009**
```
RMAN> backup database plus archivelog delete input;

Starting backup at 21-APR-2024 03:14:18
using channel ORA_DISK_1
channel ORA_DISK_1: starting full datafile backup set
channel ORA_DISK_1: specifying datafile(s) in backup set
channel ORA_DISK_1: starting piece 1 at 21-APR-2024 03:14:18
RMAN-03009: failure of backup command on ORA_DISK_1 channel at 04/21/2024 03:30:18
ORA-19809: limit exceeded for recovery files
ORA-19804: cannot reclaim 218103808 bytes disk space from 107374182400 limit

# OS cause:
df -h /fra
/dev/mapper/vg01-fra   100G  100G     0 100% /fra
```

## RMAN-02: Datafile Block Corruption Found During Backup
**ORA Code: ORA-01578 / RMAN-06056**
```
RMAN> backup validate database;

Starting backup at 21-APR-2024 03:14:18
RMAN-06056: could not access datafile 5
RMAN-06054: media recovery requesting unknown archived log: thread 1 seq 18821 lowscn 182182182

ORA-01578: ORACLE data block corrupted (file # 5, block # 18821)
ORA-01110: data file 5: '/u01/oradata/PROD/users01.dbf'

# RMAN shows corruption list:
RMAN> list failure;
List of Database Failures
=========================
Failure ID Priority Status    Time Detected Summary
---------- -------- --------- ------------- -------
182        HIGH     OPEN      21-APR-2024   Datafile 5 has corrupt data

# OS cause: Previous disk error introduced corruption
# Check alert.log for ORA-27072 before this backup
grep 'ORA-27072' /u01/app/oracle/diag/rdbms/prod/PROD/trace/alert_PROD.log | tail -5
```

## RMAN-03: Archived Log Missing (Deleted Too Aggressively)
**ORA Code: RMAN-06059 / ORA-19625**
```
RMAN> recover database until time "to_date('2024-04-21 02:00:00','YYYY-MM-DD HH24:MI:SS')";

RMAN-06059: expected archived log not found, lost of archived log compromises recoverability
archiving is disabled
ORA-19625: error identifying file /arch/1_18820_1234567890.arc
ORA-27037: unable to obtain file status
Linux-x86_64 Error: 2: No such file or directory

# Cause: Cron job deleted archivelogs before RMAN applied retention policy
# /etc/cron.d/oracle_arch_cleanup:
# 0 2 * * * oracle find /arch -name "*.arc" -mtime +3 -delete
# ← deleted log 18820 which RMAN still needed for recovery

# RMAN crosscheck shows the problem:
RMAN> crosscheck archivelog all;
validation failed for archived log
  archive log filename=/arch/1_18820_1234567890.arc recid=18820 stamp=1234567890
# EXPIRED in catalog but file gone from disk
```

## RMAN-04: Backup Piece Corruption — Hardware Error
**ORA Code: RMAN-06026 / ORA-19505**
```
RMAN> restore database;

RMAN-06026: some targets not found - aborting restore
ORA-19870: error while restoring backup piece /backup/PROD_db_18821.bkp
ORA-19505: failed to identify file "/backup/PROD_db_18821.bkp"
ORA-27048: skgfprd: memory mapped file I/O error
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error

# Backup disk itself has an error!
# Check backup disk:
smartctl -a /dev/sdc | grep -i 'health\|pending\|uncorrectable'
# SMART overall-health self-assessment: FAILED!
# 197 Current_Pending_Sector: 182   ← 182 pending sectors on backup disk

# This is why backups should be on separate storage from production
```

## RMAN-05: Standby Database Recovery Behind — MRP Process Died
**ORA Code: ORA-16401 / ORA-16145**
```
# RMAN used to recover standby gap:
RMAN> recover database;

# But MRP died first:
# alert.log on standby:
Mon Apr 21 03:14:18 2024
MRP0: Background Media Recovery process shutdown (ORA-16401)
ORA-16401: archivelog rejected by RFS

# RMAN recovery:
RMAN> recover standby database;
Starting recover at 21-APR-2024 03:14:18
ORA-16145: archivelog for thread 1, sequence# 18820 has not been received.

# Manual check:
SELECT THREAD#, SEQUENCE#, APPLIED FROM V$ARCHIVED_LOG
WHERE THREAD#=1 AND SEQUENCE# > 18819 ORDER BY SEQUENCE#;
# Sequence 18820 missing — network gap during primary peak

# Fix: Ship missing log from primary manually
RMAN> (on primary) backup archivelog sequence between 18820 and 18821 thread 1;
# Transfer to standby and register:
RMAN> (on standby) catalog archivelog '/tmp/arch/1_18820_1234567890.arc';
```
