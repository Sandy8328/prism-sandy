# This file contains massive, realistic log strings with noise, stack traces, and metadata.

ORA_00600_TEMPLATE = """
*** 2024-03-15T10:00:00.123456+00:00
*** SESSION ID:(1234.56789) 2024-03-15T10:00:00.123456+00:00
*** CLIENT ID:() 2024-03-15T10:00:00.123456+00:00
*** SERVICE NAME:(SYS$USERS) 2024-03-15T10:00:00.123456+00:00
*** MODULE NAME:(SQL*Plus) 2024-03-15T10:00:00.123456+00:00
*** ACTION NAME:() 2024-03-15T10:00:00.123456+00:00
*** CLIENT DRIVER:(SQL*PLUS) 2024-03-15T10:00:00.123456+00:00

Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_12345.trc  (incident=12345):
ORA-00600: internal error code, arguments: [1234], [2], [3], [4], [5], [6], [7], [8]
Incident details in: /u01/app/oracle/diag/rdbms/orcl/orcl/incident/incdir_12345/orcl_ora_12345_i12345.trc
========= Dump for incident 12345 (ORA 600 [1234]) ========
*** 2024-03-15T10:00:00.123456+00:00
dbkedDefDump(): Starting incident default dumps (flags=0x2, level=3, mask=0x0)
----- Current SQL Statement for this session (sql_id=g2u7p8y7z7m) -----
SELECT * FROM v$session WHERE status = 'ACTIVE';
----- Call Stack Trace -----
kgesinv <- ksesic0 <- ksesic1 <- opiexe <- opipls <- opifch2
"""

OS_SCSI_TIMEOUT_TEMPLATE = """
Mar 15 10:00:00 cell01 kernel: [123456.789012] sd 0:0:0:0: [sda] tag#0 FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_SENSE
Mar 15 10:00:00 cell01 kernel: [123456.789015] sd 0:0:0:0: [sda] tag#0 Sense Key : Aborted Command [current]
Mar 15 10:00:00 cell01 kernel: [123456.789018] sd 0:0:0:0: [sda] tag#0 Add. Sense: I/O process terminated
Mar 15 10:00:00 cell01 kernel: [123456.789020] sd 0:0:0:0: [sda] tag#0 CDB: Read(10) 28 00 00 00 00 00 00 00 08 00
Mar 15 10:00:00 cell01 kernel: [123456.789025] blk_update_request: I/O error, dev sda, sector 0 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 0
Mar 15 10:00:00 cell01 multipathd[1234]: sda: checker msg is "readsector0 checker reports path is down"
Mar 15 10:00:00 cell01 multipathd[1234]: mpatha: failing path sda
Mar 15 10:00:00 cell01 systemd[1]: OS_SCSI_TIMEOUT: Storage Array Unreachable
"""

JAVA_OOM_TEMPLATE = """
2024-03-15 10:00:00.123 ERROR [main] org.springframework.boot.SpringApplication: Application run failed
java.lang.OutOfMemoryError: Java heap space
Dumping heap to java_pid1234.hprof ...
Heap dump file created [1024345234 bytes in 5.312 secs]
Exception in thread "main" java.lang.OutOfMemoryError: Java heap space
        at java.base/java.util.Arrays.copyOf(Arrays.java:3537)
        at java.base/java.lang.AbstractStringBuilder.ensureCapacityInternal(AbstractStringBuilder.java:228)
        at java.base/java.lang.AbstractStringBuilder.append(AbstractStringBuilder.java:582)
        at java.base/java.lang.StringBuffer.append(StringBuffer.java:379)
"""

GENERIC_ORA_TEMPLATE = """
*** 2024-03-15T10:00:00.000000+00:00
*** SESSION ID:(99.99)
Thread 1 advanced to log sequence 1234 (LGWR switch)
  Current log# 1 seq# 1234 mem# 0: /u01/app/oracle/oradata/orcl/redo01.log
2024-03-15T10:00:00.500000+00:00
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_ora_999.trc:
{ERROR_CODE}: This is a realistic simulated error text with stack trace following.
ORA-06512: at "SYS.DBMS_SQL", line 123
ORA-06512: at line 1
"""
