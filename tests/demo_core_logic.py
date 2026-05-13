import json
import sys
import os

# Ensure imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent.orchestrator import DBAChatbotOrchestrator

def verify_core_logic():
    print("==================================================")
    print(" 🛠️  VERIFYING CORE LOGIC (Chunking, Regex, Correlation)")
    print("==================================================")

    # 1. Initialize Orchestrator
    orchestrator = DBAChatbotOrchestrator()
    session_id = orchestrator.session_manager.create_new_session()

    # 2. Create a realistic cascading failure log
    # OS SCSI timeout -> ASM Disk Drop -> DB Crash
    raw_syslog = (
        "2026-05-05T10:00:00 db01 kernel: end_request: I/O error, dev sdb, sector 1048576\n"
        "2026-05-05T10:00:01 db01 kernel: sd 0:0:0:0: [sdb] Unhandled error code\n"
    )
    raw_alert_log = (
        "2026-05-05T10:00:05.000000+00:00\n"
        "WARNING: Read Failed. group:1 disk:0 AU:200 offset:0 size:8192\n"
        "ORA-15080: synchronous I/O operation to a disk failed\n"
        "2026-05-05T10:00:10.000000+00:00\n"
        "Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_lgwr_1234.trc:\n"
        "ORA-00603: ORACLE server session terminated by fatal error\n"
        "ORA-01092: ORACLE instance terminated. Disconnection forced\n"
    )

    log_payloads = [
        {"file_source": "syslog", "content": raw_syslog, "hostname": "db01", "timestamp": "2026-05-05T10:00:00"},
        {"file_source": "alert.log", "content": raw_alert_log, "hostname": "db01", "timestamp": "2026-05-05T10:00:05"}
    ]

    print("\n[1] Chunking Logs (Log Ingester) ...")
    orchestrator.session_manager.upload_log_to_session(session_id, log_payloads)

    print("\n[2] Regex Matching, Correlation & Diagnosis (Evidence Aggregator & Graph) ...")
    result = orchestrator.handle_enriched_query(
        session_id, 
        "Why did the database crash?", 
        raw_log_text=raw_syslog
    )
    
    # Peek at the active signals to prove regex/correlation worked
    active_signals = result.get("active_signals", [])
    print(f"\n  ✅ Extracted Evidence Signals: {active_signals}")

    print("\n==================================================")
    print(" 📊 FINAL DIAGNOSIS OUTPUT")
    print("==================================================")
    print(f"Root Cause:       {result.get('root_cause')}")
    print(f"Risk Score:       {result.get('risk_score')} / 100")
    print(f"Confidence Label: {result.get('confidence_label')}")
    print(f"Issue Category:   {result.get('issue_category')}")
    print("\nResolution Plan:")
    print(result.get("resolution", "N/A"))

if __name__ == "__main__":
    verify_core_logic()
