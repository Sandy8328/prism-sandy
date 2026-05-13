# Oracle DBA Real Production Logs — Part 1
## ORA Errors (Alert Log Excerpts) — As Seen by DBAs in AHF/TFA Collections

> Temperature: 0.1 | Source: Real production patterns from Oracle Support MOS, TFA/AHF collections
> Purpose: RAG Vector Framework Training Data

---

## 1. ORA-00600 — Internal Error Code (ktsircinfo_num1)

```
Fri Feb 11 10:15:56 2024
Errors in file /u01/app/oracle/diag/rdbms/cdb19/cdb19/trace/cdb19_ora_28731.trc:
ORA-00600: internal error code, arguments: [ktsircinfo_num1], [7], [1024], [1921], [], [], [], [], [], [], [], []
Incident details in: /u01/app/oracle/diag/rdbms/cdb19/cdb19/incident/incdir_928471/cdb19_ora_28731_i928471.trc
Use ADRCI or Support Workbench to package the incident.
See Note 411.1 at My Oracle Support for error and packaging details.
```

---

## 2. ORA-00600 — kccpb_sanity_check_2

```
Mon Mar 04 03:22:11 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_ora_9812.trc:
ORA-00600: internal error code, arguments: [kccpb_sanity_check_2], [14398], [14399], [0x0], [], [], [], [], [], [], [], []
Incident details in: /u01/app/oracle/diag/rdbms/prod/PROD/incident/incdir_112233/PROD_ora_9812_i112233.trc
```

**Trace File Excerpt:**
```
*** 2024-03-04T03:22:11.482193+05:30
*** SESSION ID:(1782.49271) 2024-03-04T03:22:11.482213+05:30
*** CLIENT ID:() 2024-03-04T03:22:11.482220+05:30
*** SERVICE NAME:(SYS$BACKGROUND) 2024-03-04T03:22:11.482227+05:30
*** MODULE NAME:(LGWR) 2024-03-04T03:22:11.482234+05:30
ksedmp: internal or fatal error
ORA-00600: internal error code, arguments: [kccpb_sanity_check_2], [14398], [14399], [0x0]
----- Current SQL Statement for this session (sql_id=0) -----
(none)
----- PL/SQL Stack -----
----- PL/SQL Call Stack -----
No PL/SQL Call Stack
```

---

## 3. ORA-00600 — kcbz_check_objd_typ

```
Tue Apr 09 14:37:45 2024
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_14432.trc:
ORA-00600: internal error code, arguments: [kcbz_check_objd_typ], [0], [1], [1], [0], [], [], [], [], [], [], []
Incident details in: /u01/app/oracle/diag/rdbms/orcl/orcl/incident/incdir_774312/orcl_ora_14432_i774312.trc
Use ADRCI or Support Workbench to package the incident.
```

---

## 4. ORA-00600 — kewrose_1

```
Wed Jan 17 08:51:22 2024
Errors in file /u01/app/oracle/diag/rdbms/finprod/FINPROD/trace/FINPROD_mmon_3391.trc:
ORA-00600: internal error code, arguments: [kewrose_1], [1], [], [], [], [], [], [], [], [], [], []
Incident details in: /u01/app/oracle/diag/rdbms/finprod/FINPROD/incident/incdir_551782/FINPROD_mmon_3391_i551782.trc
```

---

## 5. ORA-04031 — Shared Pool Memory Exhausted

```
Thu Mar 21 02:14:09 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_ora_22147.trc:
ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","unknown object","sga heap(3,0)","KGLH0")
```

**Trace File Excerpt:**
```
*** 2024-03-21T02:14:09.871023+05:30
*** SESSION ID:(921.8723) 2024-03-21T02:14:09.871038+05:30
ORA-04031: unable to allocate 65560 bytes of shared memory ("shared pool",
"SELECT COUNT(*) FROM ORDERS WHERE STATUS=:B1","sga heap(3,0)","KGLH0")

Dump of Shared Pool:
CHUNK: 0x6000001a50 sz= 65552 R-free "               "  latch=0x600000b100
Total free space = 49152 bytes
Largest free chunk = 49152 bytes
```

---

## 6. ORA-04031 — Large Pool Allocation Failure

```
Sat Feb 24 11:29:44 2024
ORA-04031: unable to allocate 4194312 bytes of shared memory
("large pool","unknown object","large pool","RMAN backup")
Errors in file /u01/app/oracle/diag/rdbms/dwhprod/DWHPROD/trace/DWHPROD_rman_7712.trc
```

---

## 7. ORA-00060 — Deadlock Detected

```
Mon Apr 01 16:43:12 2024
DEADLOCK DETECTED ( ORA-00060 )

[Transaction Deadlock]

The following deadlock is not an ORACLE error. It is a
deadlock due to user error in the design of an application
or from issuing incorrect ad-hoc SQL. The following
information may aid in determining the deadlock:

Deadlock graph:
                       ---------Blocker(s)--------  ---------Waiter(s)---------
Resource Name          process session holds waits  process session holds waits
TX-00090017-00001f3c       237     921    X          441    1034          X
TX-001a0014-0000ac12       441    1034    X          237     921          X

session 921: DID 0001-00ED-0000004B  session 1034: DID 0001-01B9-00000053
session 1034: DID 0001-01B9-00000053  session 921: DID 0001-00ED-0000004B

Rows waited on:
  Session 921: obj - rowid = 0009AF12 - AAAJvRAAHAAAAWjAAF
  (dictionary objn - 636690, file - 7, block - 22627, slot - 5)
  Session 1034: obj - rowid = 0009AF12 - AAAJvRAAHAAAAVbAAC
  (dictionary objn - 636690, file - 7, block - 21851, slot - 2)

Information on the OTHER waiting sessions:
Session 1034:
  pid=441 serial=18723 audsid=4428910 user: 87/APPUSER
  O/S info: user=appuser, term=UNKNOWN, ospid=19823
  image: jdbc thin client
  Short stack: ksedsts()+453<-ksdxfstk()+57
  waiting for 'enq: TX - row lock contention' blocking sess=921
```

---

## 8. ORA-07445 — Access Violation (kglic0)

```
Fri Mar 08 21:55:33 2024
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_30124.trc  (incident=882211):
ORA-07445: exception encountered: core dump [kglic0()+1342] [SIGSEGV] [ADDR:0x7F9AB82C3000] [PC:0x1C3D8DE] [Address not mapped to object] []
Incident details in: /u01/app/oracle/diag/rdbms/orcl/orcl/incident/incdir_882211/orcl_ora_30124_i882211.trc
Use ADRCI or Support Workbench to package the incident.
```

**Trace File Excerpt:**
```
Signal: 11 (SIGSEGV), PC: 0x1C3D8DE, ADDR: 0x7F9AB82C3000
kglic0()+1342 SIGSEGV
----- Call Stack Trace -----
kglic0          <- kglLockGetValue <- kglget <- opiexe <- opiosq0 <- kpooprx
----- End of Call Stack Trace -----
```

---

## 9. ORA-07445 — qkexrLoopJoinPred SIGBUS

```
Wed Jan 31 09:12:04 2024
Errors in file /u01/app/oracle/diag/rdbms/finprod/FINPROD/trace/FINPROD_ora_4491.trc (incident=449183):
ORA-07445: exception encountered: core dump [qkexrLoopJoinPred()+284] [SIGBUS] [ADDR:0x7FFE00000008] [PC:0x3F1A2C0] [Bus error] []
```

---

## 10. ORA-01555 — Snapshot Too Old

```
Tue Apr 16 07:28:33 2024
ORA-01555 caused by SQL statement below (SQL ID: 8f7vk9ahq3m2x, Query Duration=7291 sec, SCN: 0x0000.1fa8c912):
SELECT /*+ PARALLEL(T,8) */ T.ORDER_ID, T.CUST_ID, T.TOTAL_AMOUNT
FROM SALES.ORDERS T
WHERE T.ORDER_DATE BETWEEN :B2 AND :B1
Errors in file /u01/app/oracle/diag/rdbms/dwhprod/DWHPROD/trace/DWHPROD_ora_18812.trc
ORA-01555: snapshot too old: rollback segment number 18 with name "_SYSSMU18_3209471829$" too small
```

---

## 11. ORA-00257 — Archiver Stuck

```
Mon Feb 19 22:41:05 2024
ARC3: Error 19809 Creating archive log file to '/arch/PROD/arch_1_98821_1012847219.arc'
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_arc3_2918.trc:
ORA-19809: limit exceeded for recovery files
ORA-19804: cannot reclaim 52428800 bytes disk space from 107374182400 limit
ARC3: STARTING ARCH PROCESSES FROM LGWR
Thu Feb 22 00:01:02 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_arc0_1182.trc:
ORA-00257: archiver error. Connect internal only, until freed.
```

---

## 12. ORA-00020 — Maximum Processes Exceeded

```
Sat Mar 16 14:22:18 2024
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_11291.trc:
ORA-00020: maximum number of processes (500) exceeded
Thu Mar 16 14:22:19 2024
Process monitor: terminating process with pid 499 (osp 0x2782)
```

---

## 13. ORA-00018 — Maximum Sessions Exceeded

```
Mon Apr 08 09:17:33 2024
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_8821.trc:
ORA-00018: maximum number of sessions exceeded
```

---

## 14. ORA-01122 — Control File Check Failed

```
Thu Feb 15 05:09:11 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_dbw0_1002.trc:
ORA-01122: database file 7 failed verification check
ORA-01110: data file 7: '/data/PROD/datafile/users01.dbf'
ORA-01251: Unknown File Header Version read for file number 7
DBWR: terminating instance due to error 1122
```

---

## 15. ORA-03113 — End of File on Communication Channel

```
Tue Mar 12 18:44:21 2024
Fatal NI connect error 12170.
  VERSION INFORMATION:
        TNS for Linux: Version 19.0.0.0.0
        Oracle Bequeath NT Protocol Adapter for Linux: Version 19.0.0.0.0
  Time: 12-MAR-2024 18:44:21
  Tracing not turned on.
  Tns error struct:
    ns main err code: 12535
    TNS-12535: TNS:operation timed out
    ns secondary err code: 12560
    nt main err code: 505
    TNS-00505: Operation timed out
    nt secondary err code: 110
    nt OS err code: 0
ORA-03113: end-of-file on communication channel
Process ID: 0
Session ID: 1021, Serial number: 44291
```

---

## 16. ORA-01578 / ORA-01110 — Block Corruption

```
Wed Apr 10 03:12:44 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_dbw1_1821.trc:
ORA-01578: ORACLE data block corrupted (file # 12, block # 88291)
ORA-01110: data file 12: '/data/PROD/datafile/app_data01.dbf'

Corrupt block relative dba: 0x03015923 (file 12, block 88323)
Fractured block found during buffer read
Data in bad block:
 type: 6 format: 2 rdba: 0x03015923
 last change scn: 0x0000.1fa8c118  seq: 0x1  flg: 0x06
 spare1: 0x0 spare2: 0x0 spare3: 0x0
 consistency value in tail: 0x8c120601
 check value in block header: 0x3f7a
 computed block check value: 0x9b2c
```

---

## 17. ORA-00353 / ORA-00312 — Redo Log Corruption

```
Mon Jan 22 06:34:21 2024
Errors in file /u01/app/oracle/diag/rdbms/prod/PROD/trace/PROD_lgwr_1122.trc:
ORA-00353: log corruption near block 88291 change 18827738192 time 01/22/2024 06:34:18
ORA-00312: online log 3 thread 1: '/redo/PROD/redo03.log'
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
Additional information: 4
Additional information: 88291
Additional information: 512
```

---

## 18. ORA-00845 — MEMORY_TARGET Not Supported

```
Fri Feb 09 11:03:18 2024
ORA-00845: MEMORY_TARGET not supported on this system
```

---

## 19. ORA-27102 — Out of Memory

```
Tue Mar 05 04:29:01 2024
ORA-27102: out of memory
Linux-x86_64 Error: 12: Cannot allocate memory
Additional information: 1
Additional information: 107374182400
Additional information: 107370086400
Additional information: -1
```

---

## 20. ORA-04030 — Out of Process Memory

```
Thu Apr 18 13:41:22 2024
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_28821.trc:
ORA-04030: out of process memory when trying to allocate 65560 bytes (sort subheap,sort key)
```

**Trace File Excerpt:**
```
----- Abridged Call Stack Trace -----
ksedmp <- kghalf <- kghfnd <- kghalo <- kghgex <- kghalf <- qersoFetch
----- End of Abridged Call Stack Trace -----
PGA Memory Used: 4,294,967,296 bytes
PGA Memory Allocated: 4,294,967,296 bytes
```
