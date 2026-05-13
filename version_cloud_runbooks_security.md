# Gaps G, H, I, J, K
## Version Differences + Cloud + Runbooks + Seasonal + Security Errors
## Temperature: 0.0

---

# PART 1: ORACLE VERSION DIFFERENCES (Gap G)

## Version Field Added to Chunk Metadata
```json
{
  "oracle_version": "19c",
  "oracle_full_version": "19.18.0.0.0",
  "version_range": "19c+"
}
```

## Same OS Error, Different Oracle Behavior

### OOM Killer Kills Oracle Process

```
ORACLE 11gR2 (11.2.0.4) response:
  alert.log:
    ORA-00604: error occurred at recursive SQL level 1
    ORA-04031: unable to allocate bytes of shared memory
    PMON: terminating instance due to error 4031
  Note: 11g does not write ORA-00603 on OOM kill — it writes ORA-04031

ORACLE 12c (12.1.0.2/12.2.0.1) response:
  alert.log:
    ORA-00603: ORACLE server session terminated by fatal error
    ORA-00600: internal error code [ksmgprem1]
    PMON: terminating instance due to error 603
  Note: 12c adds ORA-00600 internal error on OOM

ORACLE 19c (19.x) response:
  alert.log:
    ORA-00603: ORACLE server session terminated by fatal error
    ORA-00600: internal error code [LibraryCacheNotEmpty]
    Health Monitor: check ORA-603 root cause
    PMON: terminating instance due to error 603
  Note: 19c also triggers Health Monitor check automatically
```

### ASM Disk Failure Response

```
ORACLE 11g ASM:
  ORA-15130 → diskgroup dismounted
  Manual rebalance needed after path restored
  No automatic health check

ORACLE 12c ASM:
  ORA-15130 → diskgroup dismounted
  Automatic rebalance starts when paths restored
  ASM Fast Mirror Resync (AFMR) kicks in

ORACLE 19c ASM:
  ORA-15130 → diskgroup dismounted
  Automatic rebalance starts
  ADVM health check triggered
  Oracle ACFS may auto-unmount filesystems on ADVM
  alert.log will also show: "ADVM vol dismount for disk group DATA"
```

### HugePages Configuration Error

```
ORACLE 11g:
  No HugePages → SGA uses regular pages → ORA-04031 under memory pressure
  No explicit error for HugePages=0

ORACLE 12c:
  Adds warning to alert.log:
  "WARNING: HugePages are not enabled on this system"
  "Consider enabling HugePages for better performance"

ORACLE 19c:
  Same as 12c warning PLUS
  Automatic Memory Management (AMM) conflict:
  If MEMORY_TARGET set + HugePages enabled → conflict
  alert.log: "ORA-00845: MEMORY_TARGET not supported on this system"
```

---

# PART 2: ORACLE CLOUD (OCI) SPECIFIC ERRORS (Gap H)

## OCI-01: Block Volume NVMe Failure (Not SCSI — Different Device Name)
**ORA Code: ORA-27072**
```
# /var/log/messages on OCI Compute instance
# NOTE: OCI uses paravirtualized NVMe — NOT sdb/sdc naming
Apr 21 03:14:17 dbhost01 kernel: nvme nvme0: I/O timeout, reset controller
Apr 21 03:14:17 dbhost01 kernel: nvme nvme0: Device not ready; aborting reset, over 4 sec
Apr 21 03:14:17 dbhost01 kernel: nvme nvme0: controller is down; will reset: CSTS=0xffffffff
Apr 21 03:14:18 dbhost01 kernel: blk_update_request: I/O error, dev nvme0n1, sector 9175826432
Apr 21 03:14:18 dbhost01 kernel: Buffer I/O error on dev nvme0n1p1, logical block 1146978304

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
Additional information: 4

# OCI-specific diagnosis:
# Check OCI Console → Block Volumes → Volume Details → Performance Metrics
# Check OCI Events for "Block Volume I/O Error" events

# OCI Block Volume is resilient by default
# Unlike bare metal — no multipath needed
# Reset usually resolves in 30-60 seconds automatically
```

## OCI-02: OCI Instance Principal Auth Failure (Cloud backup)
**ORA Code: ORA-19554 / ORA-27023**
```
# RMAN backup to OCI Object Storage fails:
RMAN> backup database plus archivelog;

RMAN-03009: failure of backup command on ORA_SBT_TAPE_1 channel
ORA-19554: error allocating device, device type: SBT_TAPE, device name:
ORA-27023: skgfqsbi: sbtinfo2 returned error
RMAN-11003: failure during parse/execution of SQL statement: begin dbms_backup_restore.deviceAllocate ...

# OCI-specific: Instance Principal token expired or misconfigured
# Check OCI Agent log:
tail -100 /var/log/oracle-cloud-agent/oracle-cloud-agent.log
# [ERROR] Failed to refresh instance principal credentials: 401 Unauthorized

# Check dynamic group policy in OCI IAM:
# The instance's dynamic group must have policy:
# Allow dynamic-group <name> to manage object-family in compartment <name>

# Fix:
# 1. Verify instance is in the correct dynamic group
# 2. Verify IAM policy grants object storage access
# 3. Restart OCI cloud agent: systemctl restart oracle-cloud-agent
```

## OCI-03: OCI FSS (NFS) Performance Degradation
**ORA Code: ORA-27054 / ORA-00257 (if /arch on FSS)**
```
# /var/log/messages on OCI instance using FSS for /arch
Apr 21 03:14:18 dbhost01 kernel: nfs: server fs-821.fss.oci.oraclecloud.com not responding, timed out
Apr 21 03:14:48 dbhost01 kernel: nfs: server fs-821.fss.oci.oraclecloud.com still trying

# FSS throughput limit hit (OCI FSS has throughput limits per mount target)
# OCI Console → File Systems → Mount Target → Throughput Used: 100%

# Oracle alert.log
Mon Apr 21 03:14:49 2024
ARC2: Archival stopped, error occurred. Will continue retrying
ORA-00257: archiver error. Connect internal only, until freed.
ORA-27054: NFS file system where the file is created or resides is not mounted

# Fix: Scale up FSS mount target, or move archive to block volume
```

## OCI-04: OCI Compute Shape Interruption (Preemptible Instance)
**ORA Code: None — server reboots**
```
# /var/log/oracle-cloud-agent/oracle-cloud-agent.log
[2024-04-21 03:14:18] [INFO] Received preemption notice from instance metadata service
[2024-04-21 03:14:18] [WARN] Instance will be terminated in 30 seconds due to preemption
[2024-04-21 03:14:18] [INFO] Sending shutdown notification to Oracle DB

# /var/log/messages
Apr 21 03:14:18 dbhost01 systemd: Stopping Oracle Database 19c...
Apr 21 03:14:21 dbhost01 shutdown: Shutting down for system reboot

# Oracle does NOT write to alert.log — shutdown too fast
# After preemption, instance may restart on different physical host
# RAC: other node takes over
# Non-RAC: must restart manually or use OCI Instance Recovery

# This is an OCI-ONLY scenario — no on-prem equivalent
# Detection: Check /var/log/oracle-cloud-agent/ for "preemption notice"
```

## AWS RDS Oracle Specific Errors (No OS Access)

```
# AWS RDS has no /var/log/messages — DBA cannot SSH to host
# Only access: RDS Enhanced Monitoring (JSON) + CloudWatch + RDS Events

# RDS Event via AWS Console / CloudWatch:
{
  "sourceIdentifier": "prod-oracle",
  "sourceType": "db-instance",
  "message": "Automated backup failed for DB instance prod-oracle. Please check Enhanced Monitoring metrics.",
  "eventCategories": ["backup"],
  "date": "2024-04-21T03:14:18.821Z",
  "sourceArn": "arn:aws:rds:ap-south-1:821821821821:db:prod-oracle"
}

# alert.log IS accessible via:
# AWS Console → RDS → Databases → prod-oracle → Logs & events → alert_PROD.log

# RDS Oracle alert.log (same format as on-prem):
Mon Apr 21 03:14:18 2024
ORA-00257: archiver error. Connect internal only, until freed.
# But cannot check OS — must use RDS metrics instead:
# CloudWatch → RDS → FreeStorageSpace → drops to 0 → cause of ORA-00257
```

---

# PART 3: DIAGNOSTIC RUNBOOKS (Gap I)

## RUNBOOK-01: ORA-27072 Investigation Procedure

```
STEP 1: CONFIRM THE PROBLEM (30 seconds)
  grep 'ORA-27072' $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | tail -5
  → Note: exact timestamp, any "Additional information" lines

STEP 2: CORRELATE WITH OS (1 minute)
  grep "$(date -d '5 minutes ago' +'%b %e %H')" /var/log/messages | grep -iE 'scsi|sd[a-z]|I/O error|FAIL|qla2xxx|multipath'
  → Look for SCSI/HBA/multipath errors within 2 seconds of ORA-27072

STEP 3: CHECK DISK HEALTH NOW (1 minute)
  multipath -ll | grep -iE 'fail|0:0|status'
  iostat -xmt 1 3 | grep -E 'Device|await|%util'
  → If multipath paths: 0 → go to STEP 5
  → If await > 100ms → go to STEP 6

STEP 4: IDENTIFY AFFECTED DEVICE (1 minute)
  # Find which device Oracle was writing to:
  grep 'ORA-27072' /var/log/messages || dmesg | grep -i 'I/O error' | tail -10
  # Note device name: sdb, sdc, dm-2, etc.
  ls -la /dev/mapper/ | grep mpath

STEP 5: RESTORE MULTIPATH PATHS (immediate fix)
  multipathd reconfigure
  multipath -ll | grep -iE 'fail|status'
  # If paths restored → Oracle I/O resumes automatically

STEP 6: CHECK HBA IF MULTIPATH OK
  dmesg | grep -i 'qla2xxx\|lpfc\|HBA\|LOGO' | tail -10
  cat /sys/class/fc_host/host*/port_state
  → "Linkdown" = HBA issue → contact storage team

STEP 7: VERIFY ORACLE RECOVERY
  # Check if DB recovered automatically:
  grep 'ORA-27072\|ORA-00603\|Instance terminated' $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | tail -5
  → If instance crashed → restart required
  → If instance still running → I/O error was transient

STEP 8: DOCUMENT AND PREVENT
  multipath -ll (confirm all paths active)
  smartctl -a /dev/sdX (confirm disk health)
  → If recurrence risk → open ticket with storage team
```

## RUNBOOK-02: ORA-00257 Investigation Procedure

```
STEP 1: CONFIRM ARCHIVE STATUS (30 seconds)
  sqlplus / as sysdba
  SQL> archive log list;
  SQL> SELECT DEST_ID, STATUS, TARGET, ARCHIVER, DEST_NAME, ERROR
       FROM V$ARCHIVE_DEST WHERE STATUS != 'INACTIVE';

STEP 2: CHECK DISK SPACE (30 seconds)
  df -h /arch /u01 /fra
  → If /arch = 100% → STEP 3
  → If FRA full → STEP 4

STEP 3: FREE ARCH SPACE IMMEDIATELY
  # Option A (safest): Use RMAN
  rman target /
  RMAN> DELETE ARCHIVELOG ALL COMPLETED BEFORE 'SYSDATE-1';
  # Option B (if RMAN catalog unavailable):
  find /arch -name "*.arc" -mtime +2 -exec ls -lh {} \;   # verify first
  # After space freed:
  SQL> ALTER SYSTEM ARCHIVE LOG ALL;

STEP 4: FREE FRA SPACE
  rman target /
  RMAN> DELETE OBSOLETE;
  RMAN> DELETE EXPIRED ARCHIVELOG ALL;
  SQL> ALTER SYSTEM ARCHIVE LOG ALL;

STEP 5: CONFIRM ARCHIVER RESUMED
  SQL> SELECT STATUS FROM V$INSTANCE;
  SQL> archive log list;
  grep 'ARC.*resumed' $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | tail -3

STEP 6: ROOT CAUSE AND PREVENT
  # Was it sudden spike in redo generation?
  SQL> SELECT BEGIN_TIME, BLOCKS*BLOCK_SIZE/1024/1024/1024 "GB_Generated"
       FROM V$ARCHIVED_LOG WHERE COMPLETION_TIME > SYSDATE-1
       ORDER BY BEGIN_TIME;
  → If spike: investigate what query/batch caused redo spike
  → Add monitoring: alert when /arch > 80%
```

## RUNBOOK-03: Node Eviction (ORA-29740) Investigation

```
STEP 1: IDENTIFY EVICTED NODE (30 seconds)
  grep 'ORA-29740\|CRS-1618\|CRS-1625\|evict' /u01/grid/log/*/cssd/ocssd.log | tail -20
  → Note: which node evicted, at what time

STEP 2: CHECK NETWORK AT EVICTION TIME (1 minute)
  grep "$(date -d '10 minutes ago' +'%b %e %H')" /var/log/messages | grep -iE 'bond|link|down|eth'
  → Bonding failover = NIC issue
  → "No active slaves" = both NICs down

STEP 3: CHECK NTP (1 minute)
  chronyc tracking
  chronyc sources -v
  → If "System time" offset > 1 second → NTP issue caused eviction

STEP 4: CHECK INTERCONNECT (1 minute)
  ibstat | grep -i 'state\|speed\|error'
  ip -s link show bond0 | grep -i 'error\|drop'
  → IB errors or degraded speed = interconnect issue

STEP 5: CHECK CSS DISK (voting disk) (1 minute)
  crsctl query css votedisk
  dd if=/dev/mapper/ocrvote01 of=/dev/null bs=512 count=1
  → If dd fails → voting disk path issue

STEP 6: REJOIN EVICTED NODE
  # On evicted node (if it's up):
  crsctl start crs
  # On surviving node, verify:
  crsctl stat res -t
```

---

# PART 4: SEASONAL / TIME-TRIGGERED ERRORS (Gap J)

## DST Daylight Saving Time — Oracle Impact
**ORA Code: ORA-29740 (if large jump)**
```
# /var/log/messages at DST transition (clocks spring forward 1 hour)
Mar 10 02:00:00 dbhost01 chronyd: System clock was stepped by 3600.000 seconds
Mar 10 02:00:00 dbhost01 chronyd: Forward time jump detected

# CRS eviction (3600 second jump = way above CSS miscount threshold):
2024-03-10 02:00:01.821 [CSSD(18821)]CRS-1618: Node dbhost02 is not responding
2024-03-10 02:00:03.182 [CSSD(18821)]CRS-1625: Node dbhost02 is being evicted

# Prevention:
# Set NTP to slew mode (gradual adjustment, not step):
# /etc/chrony.conf:
makestep 0.5 3        ← only step if offset > 0.5s AND in first 3 updates
# After that: use slew (gradual) only — Oracle CRS survives gradual changes
```

## Certificate Expiry — Oracle Wallet/TDE
**ORA Code: ORA-28860 / ORA-28868**
```
# Symptoms appearing in sqlnet.log:
Fatal NI connect error 29,
  TNS-12560: TNS:protocol adapter error
  TNS-00583: Valid node checking: unable to get hostname

# Or in alert.log when TDE wallet auto-login fails:
Mon Apr 21 03:14:18 2024
ORA-28860: Fatal SSL error
ORA-28862: SSL connection failed
ORA-29024: Certificate validation failure
# Cause: Oracle Wallet certificate expired

# Check wallet certificate:
orapki wallet display -wallet $ORACLE_BASE/admin/PROD/wallet
# Output will show: Certificate expiry date
# If expired → renew with:
orapki wallet remove -wallet $WALLET_LOC -dn "CN=PROD,OU=IT,O=Company"
orapki wallet add -wallet $WALLET_LOC -dn "CN=PROD" -self_signed -validity 3650
```

## Year-End Batch — Stats Collection Overload
**ORA Code: Does Not Exist (AWR shows CPU/I/O spike)**
```
# /var/log/messages (year-end: December 31, 11 PM)
Dec 31 23:00:00 dbhost01 kernel: CPU0 performance throttled (100%)
Dec 31 23:00:01 dbhost01 kernel: EXT4-fs warning: mounting unchecked fs

# AWR at year-end shows:
Top 5 Timed Events:
  db file sequential read  182821  4821.2s  (stats collection full scan)
  CPU time                 82821   1821.2s
  db file scattered read   42821   821.2s   (gathering stats on big tables)

# DBMS_SCHEDULER jobs (stats collection) triggered at midnight
# + business batch jobs at year-end
# = dual peak → 100% CPU, disk saturation

# Alert.log shows:
Tue Dec 31 23:00:00 2024
WARNING: db_recovery_file_dest_size of 200 GB is 94% used
# Redo generation spike from massive stats collection
```

---

# PART 5: SECURITY / ENCRYPTION ERRORS (Gap K)

## SEC-01: TDE Wallet Not Opened After Restart
**ORA Code: ORA-28417 / ORA-01157**
```
# After DB restart — DBA forgot to open TDE keystore:
Mon Apr 21 03:14:18 2024
ORA-01157: cannot identify/lock data file 5 - see DBWR trace file
ORA-01110: data file 5: '+DATA/PROD/DATAFILE/users01.dbf'
ORA-28417: password-based keystore is not open

# DB starts but encrypted datafiles cannot be opened
# DB is in RESTRICTED mode — cannot serve users

# Check keystore status:
SQL> SELECT STATUS, WALLET_TYPE FROM V$ENCRYPTION_WALLET;
# CLOSED  PASSWORD   ← keystore closed

# Fix:
SQL> ADMINISTER KEY MANAGEMENT SET KEYSTORE OPEN
     IDENTIFIED BY "wallet_password" CONTAINER=ALL;

# Permanent fix (auto-open wallet):
SQL> ADMINISTER KEY MANAGEMENT CREATE AUTO_LOGIN KEYSTORE
     FROM KEYSTORE '$WALLET_LOC' IDENTIFIED BY "wallet_password";
```

## SEC-02: Oracle Audit Trail Full — DB Suspended
**ORA Code: ORA-00604 / ORA-46263**
```
# Oracle Unified Auditing writing to SYSAUX
# SYSAUX tablespace 100% full because of massive audit records:

Mon Apr 21 03:14:18 2024
ORA-00604: error occurred at recursive SQL level 1
ORA-01653: unable to extend table AUDSYS.AUD$UNIFIED by 128 in tablespace SYSAUX
ORA-46263: The audit trail overflow action is SUSPEND.
# ← Database suspended all operations because audit trail full

# Check SYSAUX:
SQL> SELECT TABLESPACE_NAME, BYTES_USED/1024/1024/1024 GB_USED,
     BYTES_FREE/1024/1024/1024 GB_FREE FROM V$SYSAUX_OCCUPANTS
     WHERE OCCUPANT_NAME='AUDSYS';

# Fix immediately:
SQL> EXEC DBMS_AUDIT_MGMT.CLEAN_AUDIT_TRAIL(
     AUDIT_TRAIL_TYPE => DBMS_AUDIT_MGMT.AUDIT_TRAIL_UNIFIED,
     USE_LAST_ARCH_TIMESTAMP => TRUE);
```

## SEC-03: SELinux Blocks Oracle After OS Patch
**ORA Code: ORA-27300 / ORA-27301**
```
# After OS security patch, SELinux policy updated → blocks Oracle
Mon Apr 21 03:14:18 2024
ORA-27300: OS system dependent operation:semget failed with status: 13
ORA-27301: OS failure message: Permission denied
ORA-27302: failure occurred at: sskgpsemsper

# /var/log/audit/audit.log (concurrent):
type=AVC msg=audit(1713666858.821:18821): avc: denied { write }
for pid=18821 comm="oracle" name="shm" dev="tmpfs" ino=182
scontext=system_u:system_r:oracle_db_t:s0
tcontext=system_u:object_r:tmpfs_t:s0
tclass=file permissive=0

# SELinux denied Oracle writing to shared memory after policy update

# Fix:
ausearch -c oracle --raw | audit2allow -M oracle_policy
semodule -i oracle_policy.pp
# Or temporarily:
setenforce 0   ← only temporary, make proper policy
```

## SEC-04: Oracle Listener SSL Handshake Failure
**ORA Code: ORA-12170 / ORA-28860**
```
# listener.log
21-APR-2024 03:14:18 * (CONNECT_DATA=...(SECURITY=(SSL_SERVER_CERT_DN=...))) *
(ADDRESS=(PROTOCOL=tcps)(HOST=dbhost01)(PORT=2484)) * establish * PROD * 12170
TNS-12170: TNS:Connect timeout occurred

# sqlnet.log on client:
Fatal NI connect error 12537
  TNS-12537: TNS:connection closed
  TNS-12560: TNS:protocol adapter error
  TNS-00507: Connection closed

# Certificate subject mismatch:
# DB certificate CN=dbhost01.internal.company.com
# Client connecting to: dbhost01 (short hostname)
# SSL_SERVER_CERT_DN doesn't match → SSL rejected

# Check certificate:
orapki wallet display -wallet $ORACLE_HOME/network/admin/wallet
# Verify: Subject: CN=dbhost01.internal.company.com
# Client must use FQDN not short hostname in tnsnames.ora
```

## SEC-05: Oracle Vault — DBA Blocked From Own Database
**ORA Code: ORA-01031 / ORA-28101**
```
# Oracle Database Vault enabled — DBA cannot access protected schemas
Mon Apr 21 03:14:18 2024
ORA-28101: policy does not exist
ORA-01031: insufficient privileges

# DBA trying to query HR schema:
SQL> SELECT * FROM HR.EMPLOYEES;
ORA-01031: insufficient privileges
# Oracle Vault realm protecting HR schema — DBA excluded

# Check Vault status:
SQL> SELECT STATUS FROM V$OPTION WHERE PARAMETER='Oracle Database Vault';
# TRUE — Vault enabled

SQL> SELECT REALM_NAME, STATUS FROM DVSYS.DBA_DV_REALM WHERE REALM_NAME='HR Data';
# HR Data  ENABLED ← DBA is not a realm owner, so blocked

# Fix: Add DBA as realm participant (requires Vault owner account):
SQL> (as vault owner) EXEC DVSYS.DBMS_MACADM.ADD_AUTH_TO_REALM(
     REALM_NAME=>'HR Data', GRANTEE=>'SYS', RULE_SET_NAME=>null,
     AUTH_OPTIONS=>DVSYS.DBMS_MACADM.G_REALM_AUTH_PARTICIPANT);
```
