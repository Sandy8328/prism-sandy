"""
enrich_graph_commands.py
========================
Populates the `remediation_commands` field in every `error_code` node
(type="error_code") in graph.json using the authoritative PDF runbook commands.

Also wires ORA_CODE nodes → FIX_COMMAND nodes via graph edges, so the
orchestrator can traverse: ORA code detected → graph edge → exact commands.

Run:
    python scripts/enrich_graph_commands.py
"""

import json
import os

GRAPH_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "knowledge_graph", "data", "graph.json"
)

# ──────────────────────────────────────────────────────────────────────────────
# MASTER RUNBOOK: ORA code → exact DBA commands
# Source: Oracle DBA Diagnostic Runbook PDF (13 pages)
# Three tiers per error: OS-Level, Database-Level, Infrastructure-Level
# ──────────────────────────────────────────────────────────────────────────────
ORA_RUNBOOK = {

    # ── ARCHIVER / DISK FULL ──────────────────────────────────────────────────
    "ORA-00257": {
        "title": "Archiver Error – Archivelog Destination Full",
        "fix_node": "FIX_CLEANUP_ARCH_LOGS",
        "tier": "OS + Database",
        "commands": [
            # OS-Level: check disk
            "df -h /arch",
            "du -sh /arch/* | sort -rh | head -20",
            # Database-Level: clear archive logs via RMAN
            "rman target /",
            "RMAN> DELETE ARCHIVELOG ALL COMPLETED BEFORE 'SYSDATE-1';",
            "RMAN> EXIT;",
            # Database-Level: check & increase DB_RECOVERY_FILE_DEST_SIZE
            "sqlplus / as sysdba",
            "SQL> SHOW PARAMETER db_recovery_file_dest_size;",
            "SQL> ALTER SYSTEM SET db_recovery_file_dest_size=50G SCOPE=BOTH;",
            "SQL> SELECT * FROM V$RECOVERY_FILE_DEST;",
            # Unblock archiver
            "SQL> ALTER SYSTEM ARCHIVE LOG ALL;",
            "SQL> EXIT;",
        ]
    },

    "ORA-19809": {
        "title": "Limit Exceeded for Recovery Files",
        "fix_node": "FIX_CLEANUP_ARCH_LOGS",
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            "SQL> SELECT * FROM V$RECOVERY_FILE_DEST;",
            "SQL> SHOW PARAMETER db_recovery_file_dest_size;",
            "SQL> ALTER SYSTEM SET db_recovery_file_dest_size=100G SCOPE=BOTH;",
            "rman target /",
            "RMAN> CROSSCHECK ARCHIVELOG ALL;",
            "RMAN> DELETE EXPIRED ARCHIVELOG ALL;",
            "RMAN> EXIT;",
        ]
    },

    "ORA-16038": {
        "title": "Log Writer Cannot Archive Log – Archiver Stuck",
        "fix_node": "FIX_CLEANUP_ARCH_LOGS",
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            "SQL> SELECT STATUS, SEQUENCE#, NAME FROM V$ARCHIVED_LOG ORDER BY SEQUENCE# DESC FETCH FIRST 10 ROWS ONLY;",
            "SQL> SELECT * FROM V$ARCHIVE_DEST_STATUS WHERE STATUS != 'INACTIVE';",
            "SQL> ALTER SYSTEM SWITCH LOGFILE;",
            "SQL> ALTER SYSTEM ARCHIVE LOG ALL;",
            "SQL> SELECT GROUP#, STATUS FROM V$LOG;",
            "SQL> EXIT;",
        ]
    },

    # ── I/O ERRORS (DISK / SCSI) ──────────────────────────────────────────────
    "ORA-27072": {
        "title": "File I/O Error – OS Disk Error",
        "fix_node": "FIX_ENABLE_MULTIPATH",
        "tier": "OS + Infrastructure",
        "commands": [
            # OS-Level
            "dmesg | grep -i 'i/o error\\|scsi\\|disk' | tail -30",
            "cat /proc/sys/kernel/dmesg_restrict",
            "smartctl -a /dev/sda",
            "iostat -xz 1 5",
            "multipath -ll",
            # Infrastructure-Level
            "systool -c fc_host -v | grep -i fw_rev",
            "cat /sys/class/fc_host/host*/port_state",
            # Database-Level: identify affected files
            "sqlplus / as sysdba",
            "SQL> SELECT FILE#, NAME, STATUS FROM V$DATAFILE WHERE STATUS='RECOVER';",
            "SQL> SELECT * FROM V$DATABASE_BLOCK_CORRUPTION;",
            "SQL> EXIT;",
        ]
    },

    "ORA-15080": {
        "title": "Synchronous I/O Request to ASM Disk Failed",
        "fix_node": "FIX_ENABLE_MULTIPATH",
        "tier": "OS + ASM",
        "commands": [
            "dmesg | grep -i 'i/o error\\|sd\\|multipath' | tail -30",
            "multipath -ll",
            "asmcmd lsdsk",
            "asmcmd lsof",
            "sqlplus / as sysdba",
            "SQL> SELECT GROUP_NUMBER, NAME, STATE FROM V$ASM_DISKGROUP;",
            "SQL> SELECT DISK_NUMBER, NAME, PATH, MODE_STATUS, MOUNT_STATUS FROM V$ASM_DISK ORDER BY GROUP_NUMBER;",
            "SQL> EXIT;",
        ]
    },

    "ORA-15130": {
        "title": "ASM Diskgroup Being Dismounted",
        "fix_node": "FIX_ENABLE_MULTIPATH",
        "tier": "ASM",
        "commands": [
            "asmcmd lsdg",
            "asmcmd lsdsk --discovery",
            "sqlplus / as sysdba",
            "SQL> SELECT GROUP_NUMBER, NAME, STATE, TYPE FROM V$ASM_DISKGROUP;",
            "SQL> ALTER DISKGROUP <DGNAME> MOUNT;",
            "SQL> EXIT;",
            # Check underlying paths
            "multipath -ll",
            "systemctl status multipathd",
        ]
    },

    "ORA-01578": {
        "title": "Oracle Data Block Corrupted",
        "fix_node": "FIX_ENABLE_MULTIPATH",
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            "SQL> SELECT FILE#, BLOCK#, BLOCKS, CORRUPTION_TYPE FROM V$DATABASE_BLOCK_CORRUPTION;",
            "SQL> SELECT NAME FROM V$DATAFILE WHERE FILE# = <FILE_NUMBER>;",
            "SQL> EXIT;",
            # RMAN block recovery
            "rman target /",
            "RMAN> BLOCKRECOVER DATAFILE <FILE_NUMBER> BLOCK <BLOCK_NUMBER>;",
            "RMAN> VALIDATE DATABASE;",
            "RMAN> EXIT;",
        ]
    },

    # ── SHARED MEMORY / MEMORY ────────────────────────────────────────────────
    "ORA-04031": {
        "title": "Unable to Allocate Bytes of Shared Memory",
        "fix_node": "FIX_SET_HUGEPAGES",
        "tier": "OS + Database",
        "commands": [
            # OS-Level
            "grep -i hugepage /proc/meminfo",
            "free -g",
            "ipcs -m | head -20",
            # Database-Level
            "sqlplus / as sysdba",
            "SQL> SHOW PARAMETER sga_target;",
            "SQL> SHOW PARAMETER pga_aggregate_target;",
            "SQL> SELECT POOL, NAME, BYTES FROM V$SGASTAT WHERE NAME='free memory' ORDER BY POOL;",
            "SQL> ALTER SYSTEM FLUSH SHARED_POOL;",
            "SQL> ALTER SYSTEM SET MEMORY_TARGET=0 SCOPE=SPFILE;",
            "SQL> EXIT;",
        ]
    },

    "ORA-27102": {
        "title": "Out of Memory – Cannot Allocate SGA",
        "fix_node": "FIX_SET_HUGEPAGES",
        "tier": "OS",
        "commands": [
            "grep -i 'hugepage\\|shm\\|mem' /proc/meminfo",
            "ipcs -lm",
            "cat /proc/sys/kernel/shmmax",
            "cat /proc/sys/kernel/shmall",
            # Fix shmmax
            "sysctl -w kernel.shmmax=68719476736",
            "sysctl -w kernel.shmall=16777216",
            "echo 'kernel.shmmax=68719476736' >> /etc/sysctl.conf",
            "echo 'kernel.shmall=16777216' >> /etc/sysctl.conf",
            "sysctl -p",
        ]
    },

    "ORA-27125": {
        "title": "Unable to Create Shared Memory Segment – HugePages",
        "fix_node": "FIX_SET_HUGEPAGES",
        "tier": "OS",
        "commands": [
            "grep -i hugepage /proc/meminfo",
            "grep -i hugepage /etc/sysctl.conf",
            "echo 49152 > /proc/sys/vm/nr_hugepages",
            "echo 'vm.nr_hugepages=49152' >> /etc/sysctl.conf",
            "sysctl -p",
            # Verify
            "grep -i hugepage /proc/meminfo",
        ]
    },

    # ── PROCESS / SEMAPHORE ────────────────────────────────────────────────────
    "ORA-27300": {
        "title": "OS System Call Error – Semaphore/FD Limit",
        "fix_node": "FIX_INCREASE_SEMMNI",
        "tier": "OS",
        "commands": [
            "ipcs -ls",
            "sysctl kernel.sem",
            "ulimit -n",
            "cat /proc/sys/fs/file-max",
            "echo 'kernel.sem=250 32000 100 4096' >> /etc/sysctl.conf",
            "sysctl -p",
            "echo 'oracle soft nofile 65536' >> /etc/security/limits.conf",
            "echo 'oracle hard nofile 65536' >> /etc/security/limits.conf",
        ]
    },

    # ── NETWORK / LISTENER ────────────────────────────────────────────────────
    "ORA-03113": {
        "title": "End-of-File on Communication Channel",
        "fix_node": "FIX_CHECK_BONDING",
        "tier": "Network + Database",
        "commands": [
            # Network-Level
            "ping -c 4 <db_host>",
            "traceroute <db_host>",
            "netstat -an | grep 1521",
            "ss -antp | grep 1521",
            # Listener
            "lsnrctl status",
            "lsnrctl reload",
            # Database-Level
            "sqlplus / as sysdba",
            "SQL> SELECT SID, USERNAME, STATUS, MACHINE, LOGON_TIME FROM V$SESSION WHERE STATUS='KILLED';",
            "SQL> SELECT EVENT, COUNT(*) FROM V$SESSION_WAIT GROUP BY EVENT ORDER BY COUNT(*) DESC FETCH FIRST 10 ROWS ONLY;",
            "SQL> SHOW PARAMETER sqlnet;",
            "SQL> EXIT;",
            # Check alert log for ORA-03113 context
            "tail -200 $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | grep -A5 'ORA-03113'",
        ]
    },

    "ORA-12541": {
        "title": "No Listener – TNS No Listener",
        "fix_node": "FIX_FLUSH_IPTABLES_1521",
        "tier": "Network + Database",
        "commands": [
            "lsnrctl status",
            "lsnrctl start",
            "cat $ORACLE_HOME/network/admin/listener.ora",
            "cat $ORACLE_HOME/network/admin/tnsnames.ora",
            "tnsping <service_name>",
            # Check firewall
            "iptables -L -n | grep 1521",
            "firewall-cmd --list-all",
            "firewall-cmd --zone=public --add-port=1521/tcp --permanent",
            "firewall-cmd --reload",
            # Verify service is registered
            "sqlplus / as sysdba",
            "SQL> SELECT VALUE FROM V$PARAMETER WHERE NAME='service_names';",
            "SQL> ALTER SYSTEM REGISTER;",
            "SQL> EXIT;",
        ]
    },

    "ORA-12170": {
        "title": "TNS Connect Timeout Occurred",
        "fix_node": "FIX_FLUSH_IPTABLES_1521",
        "tier": "Network",
        "commands": [
            "tnsping <service_name>",
            "ping -c 4 <db_host>",
            "netstat -s | grep -i 'failed connection\\|timeout'",
            "ss -antp | grep 1521",
            # Check sqlnet.ora timeouts
            "cat $ORACLE_HOME/network/admin/sqlnet.ora",
            # Check conntrack table
            "sysctl net.nf_conntrack_max",
            "cat /proc/sys/net/netfilter/nf_conntrack_count",
            "iptables -L -n | grep DROP",
        ]
    },

    # ── DATABASE CORE ─────────────────────────────────────────────────────────
    "ORA-00603": {
        "title": "Oracle Server Session Terminated by Fatal Error",
        "fix_node": None,
        "tier": "Database",
        "commands": [
            # Check alert log for root cause
            "tail -500 $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | grep -B10 'ORA-00603'",
            # Find and read trace file
            "ls -lt $ORACLE_BASE/diag/rdbms/*/*/trace/*.trc | head -5",
            "adrci",
            "ADRCI> SHOW INCIDENT;",
            "ADRCI> SHOW PROBLEM;",
            "ADRCI> EXIT;",
            # Database-Level
            "sqlplus / as sysdba",
            "SQL> SELECT INST_ID, STATUS, DATABASE_STATUS FROM GV$INSTANCE;",
            "SQL> SELECT COUNT(*) FROM V$SESSION WHERE STATUS='ACTIVE';",
            "SQL> EXIT;",
        ]
    },

    "ORA-00353": {
        "title": "Log Corruption Near Block – Redo Log Corruption",
        "fix_node": "FIX_REMOUNT_EXT4",
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            "SQL> SELECT GROUP#, MEMBER FROM V$LOGFILE;",
            "SQL> SELECT GROUP#, SEQUENCE#, STATUS, ARCHIVED FROM V$LOG;",
            # If log is INACTIVE or UNUSED, clear it
            "SQL> ALTER DATABASE CLEAR LOGFILE GROUP <GROUP_NUMBER>;",
            # If ACTIVE, must clear unarchived
            "SQL> ALTER DATABASE CLEAR UNARCHIVED LOGFILE GROUP <GROUP_NUMBER>;",
            "SQL> RECOVER DATABASE UNTIL CANCEL;",
            "SQL> ALTER DATABASE OPEN RESETLOGS;",
            "SQL> EXIT;",
        ]
    },

    "ORA-00470": {
        "title": "LGWR Process Terminated with Error",
        "fix_node": None,
        "tier": "Database",
        "commands": [
            "tail -200 $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | grep -B5 'ORA-00470'",
            "ls -lt $ORACLE_BASE/diag/rdbms/*/*/trace/orcl_lgwr_*.trc | head -3",
            "sqlplus / as sysdba",
            "SQL> SELECT GROUP#, STATUS, BYTES FROM V$LOG;",
            "SQL> SELECT GROUP#, MEMBER FROM V$LOGFILE;",
            "SQL> SELECT * FROM V$LOG WHERE STATUS='CURRENT';",
            "SQL> EXIT;",
            # OS-Level: disk space for redo
            "df -h /redolog",
            "iostat -xz 1 5",
        ]
    },

    "ORA-07445": {
        "title": "Exception Encountered – Core Dump (Internal Error)",
        "fix_node": None,
        "tier": "Database",
        "commands": [
            # Find the trace file
            "adrci",
            "ADRCI> SHOW INCIDENT;",
            "ADRCI> SHOW PROBLEM;",
            "ADRCI> IPS PACK INCIDENT <INCIDENT_ID> IN '/tmp';",
            "ADRCI> EXIT;",
            # Check alert log
            "tail -200 $ORACLE_BASE/diag/rdbms/*/*/trace/alert_*.log | grep -B10 'ORA-07445'",
            # Database-Level
            "sqlplus / as sysdba",
            "SQL> SELECT VALUE FROM V$DIAG_INFO WHERE NAME='Default Trace File';",
            "SQL> SHOW PARAMETER optimizer;",
            "SQL> EXIT;",
            # Apply patches (check MOS for specific bug)
            "opatch lsinventory | grep -i 'Patch'",
        ]
    },

    "ORA-29740": {
        "title": "Evicted by Member – RAC Node Eviction",
        "fix_node": "FIX_RESTORE_NTP",
        "tier": "Infrastructure + RAC",
        "commands": [
            # Check CRS/Clusterware
            "crsctl check crs",
            "crsctl stat res -t",
            "oifcfg getif",
            # Check cluster interconnect
            "ping -c 10 <private_interconnect_ip>",
            # Check NTP / time sync
            "chronyc tracking",
            "timedatectl status",
            # Check voting disk
            "crsctl query css votedisk",
            # Check alert log on evicted node
            "tail -200 $GRID_HOME/log/$(hostname)/alert$(hostname).log | grep -B10 'ORA-29740'",
            "sqlplus / as sysdba",
            "SQL> SELECT INST_ID, STATUS FROM GV$INSTANCE;",
            "SQL> EXIT;",
        ]
    },

    # ── NFS / REMOTE STORAGE ─────────────────────────────────────────────────
    "ORA-27054": {
        "title": "NFS File System Not Mounted with Required Options",
        "fix_node": "FIX_FREE_NFS_MOUNT",
        "tier": "OS + Infrastructure",
        "commands": [
            "mount | grep nfs",
            "showmount -e <nfshost>",
            "cat /etc/fstab | grep nfs",
            # Remount with correct options
            "umount -l /arch",
            "mount -o rw,hard,timeo=600,rsize=32768,wsize=32768 <nfshost>:/export/arch /arch",
            # Verify
            "mount | grep nfs",
            "df -h /arch",
        ]
    },

    # ── UNIQUE CONSTRAINT ─────────────────────────────────────────────────────
    "ORA-00001": {
        "title": "Unique Constraint Violated",
        "fix_node": None,
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            # Find the constraint and table
            "SQL> SELECT CONSTRAINT_NAME, TABLE_NAME, STATUS FROM DBA_CONSTRAINTS WHERE CONSTRAINT_TYPE='U' AND CONSTRAINT_NAME='<CONSTRAINT_NAME>';",
            "SQL> SELECT COLUMN_NAME FROM DBA_CONS_COLUMNS WHERE CONSTRAINT_NAME='<CONSTRAINT_NAME>';",
            # Find duplicates
            "SQL> SELECT <KEY_COLUMN>, COUNT(*) FROM <TABLE_NAME> GROUP BY <KEY_COLUMN> HAVING COUNT(*) > 1;",
            # Fix: either remove duplicate or disable constraint temporarily
            "SQL> ALTER TABLE <TABLE_NAME> DISABLE CONSTRAINT <CONSTRAINT_NAME>;",
            "SQL> DELETE FROM <TABLE_NAME> WHERE ROWID NOT IN (SELECT MIN(ROWID) FROM <TABLE_NAME> GROUP BY <KEY_COLUMN>);",
            "SQL> COMMIT;",
            "SQL> ALTER TABLE <TABLE_NAME> ENABLE CONSTRAINT <CONSTRAINT_NAME>;",
            "SQL> EXIT;",
        ]
    },

    # ── SESSIONS / PROCESSES ─────────────────────────────────────────────────
    "ORA-00018": {
        "title": "Maximum Number of Sessions Exceeded",
        "fix_node": None,
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            "SQL> SHOW PARAMETER sessions;",
            "SQL> SHOW PARAMETER processes;",
            "SQL> SELECT COUNT(*) FROM V$SESSION;",
            "SQL> SELECT USERNAME, COUNT(*) FROM V$SESSION GROUP BY USERNAME ORDER BY COUNT(*) DESC;",
            # Kill blocking or idle sessions
            "SQL> SELECT 'ALTER SYSTEM KILL SESSION '''||SID||','||SERIAL#||''' IMMEDIATE;' FROM V$SESSION WHERE STATUS='INACTIVE' AND LAST_CALL_ET > 3600;",
            # Increase limit
            "SQL> ALTER SYSTEM SET SESSIONS=500 SCOPE=SPFILE;",
            "SQL> ALTER SYSTEM SET PROCESSES=300 SCOPE=SPFILE;",
            "SQL> SHUTDOWN IMMEDIATE;",
            "SQL> STARTUP;",
            "SQL> EXIT;",
        ]
    },

    "ORA-00020": {
        "title": "Maximum Number of Processes Exceeded",
        "fix_node": None,
        "tier": "Database",
        "commands": [
            "sqlplus / as sysdba",
            "SQL> SHOW PARAMETER processes;",
            "SQL> SELECT COUNT(*) FROM V$PROCESS;",
            "SQL> SELECT PROGRAM, COUNT(*) FROM V$SESSION GROUP BY PROGRAM ORDER BY COUNT(*) DESC FETCH FIRST 10 ROWS ONLY;",
            "SQL> ALTER SYSTEM SET PROCESSES=500 SCOPE=SPFILE;",
            "SQL> SHUTDOWN IMMEDIATE;",
            "SQL> STARTUP;",
            "SQL> EXIT;",
        ]
    },

}

# ──────────────────────────────────────────────────────────────────────────────
# ORA_CODE node → FIX_COMMAND node mapping (for graph edges)
# ──────────────────────────────────────────────────────────────────────────────
ORA_TO_FIX_EDGE = {
    "ORA-00257":  "FIX_CLEANUP_ARCH_LOGS",
    "ORA-19809":  "FIX_CLEANUP_ARCH_LOGS",
    "ORA-16038":  "FIX_CLEANUP_ARCH_LOGS",
    "ORA-27072":  "FIX_ENABLE_MULTIPATH",
    "ORA-15080":  "FIX_ENABLE_MULTIPATH",
    "ORA-15130":  "FIX_ENABLE_MULTIPATH",
    "ORA-01578":  "FIX_ENABLE_MULTIPATH",
    "ORA-04031":  "FIX_SET_HUGEPAGES",
    "ORA-27102":  "FIX_INCREASE_SHMMAX",
    "ORA-27125":  "FIX_SET_HUGEPAGES",
    "ORA-27300":  "FIX_INCREASE_SEMMNI",
    "ORA-03113":  "FIX_CHECK_BONDING",
    "ORA-12541":  "FIX_FLUSH_IPTABLES_1521",
    "ORA-12170":  "FIX_CHECK_CONNTRACK",
    "ORA-00353":  "FIX_REMOUNT_EXT4",
    "ORA-29740":  "FIX_RESTORE_NTP",
    "ORA-27054":  "FIX_FREE_NFS_MOUNT",
}


def enrich_graph():
    print(f"[*] Loading graph from: {GRAPH_PATH}")
    with open(GRAPH_PATH, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    updated_error_code = 0
    updated_ora_code   = 0

    # ── STEP 1: Enrich `error_code` nodes (oracle_ora_XXXXX) ─────────────────
    for node in nodes:
        if node.get("type") == "error_code":
            label = node.get("label", "")           # e.g. "ORA-00257"
            if label in ORA_RUNBOOK:
                runbook    = ORA_RUNBOOK[label]
                node["remediation_commands"] = runbook["commands"]
                node["runbook_title"]        = runbook["title"]
                node["fix_tier"]             = runbook["tier"]
                node["fix_command_ref"]      = runbook.get("fix_node") or "N/A"
                updated_error_code += 1
                print(f"  [ENRICHED error_code] {label} → {len(runbook['commands'])} commands")

    # ── STEP 2: Enrich early `ORA_CODE` nodes (id="ORA-XXXXX") ───────────────
    for node in nodes:
        if node.get("type") == "ORA_CODE":
            code = node.get("id", "")               # e.g. "ORA-27072"
            if code in ORA_RUNBOOK:
                runbook = ORA_RUNBOOK[code]
                node["remediation_commands"] = runbook["commands"]
                node["runbook_title"]        = runbook["title"]
                node["fix_tier"]             = runbook["tier"]
                node["fix_command_ref"]      = runbook.get("fix_node") or "N/A"
                updated_ora_code += 1
                print(f"  [ENRICHED ORA_CODE]   {code} → {len(runbook['commands'])} commands")

    # ── STEP 3: Add missing edges (ORA code → FIX_COMMAND) ───────────────────
    # Collect existing edge pairs to avoid duplicates
    existing_edges = graph.get("edges", [])
    existing_pairs = {(e.get("source"), e.get("target")) for e in existing_edges}
    new_edges = []

    for ora_code, fix_id in ORA_TO_FIX_EDGE.items():
        pair = (ora_code, fix_id)
        if pair not in existing_pairs:
            new_edges.append({
                "source":        ora_code,
                "target":        fix_id,
                "relation":      "HAS_FIX_COMMAND",
                "weight":        1.0,
                "auto_added":    True
            })
            # Also add from oracle_ora_XXXXX id style
            alt_id = "oracle_" + ora_code.lower().replace("-", "_")
            alt_pair = (alt_id, fix_id)
            if alt_pair not in existing_pairs:
                new_edges.append({
                    "source":    alt_id,
                    "target":    fix_id,
                    "relation":  "HAS_FIX_COMMAND",
                    "weight":    1.0,
                    "auto_added": True
                })

    if new_edges:
        graph["edges"] = existing_edges + new_edges
        print(f"\n  [EDGES ADDED] {len(new_edges)} new ORA → FIX_COMMAND edges")
    else:
        print("\n  [EDGES] All edges already exist — no duplicates added")

    # ── STEP 4: Write back ────────────────────────────────────────────────────
    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=4, ensure_ascii=False)

    print(f"\n✅ ENRICHMENT COMPLETE")
    print(f"   error_code nodes updated : {updated_error_code}")
    print(f"   ORA_CODE nodes updated   : {updated_ora_code}")
    print(f"   New edges added          : {len(new_edges)}")
    print(f"   Graph saved to           : {GRAPH_PATH}")


if __name__ == "__main__":
    enrich_graph()
