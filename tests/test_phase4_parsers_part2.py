"""
test_phase4_parsers_part2.py — Validates the remaining parsers and handlers from Phase 4.

Tests:
3. ASM Self-Inflicted DoS (ASM Rebalance logic via syslog translation).
4. Desynced Reality (FRA ORA-19815 triggers RMAN crosscheck recommendation).
5. Observer Split-Brain (ORA-166* triggers Data Guard drc*.log recommendation).
6. Kill-9 Murder / SELinux (auditd log parsing triggers security warning).
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.orchestrator import DBAChatbotOrchestrator

def run_tests():
    print("\n==================================================")
    print(" 🛠️  RUNNING PHASE 4 PARSER TESTS (PART 2)")
    print("==================================================")

    orchestrator = DBAChatbotOrchestrator()
    session_id = orchestrator.session_manager.create_new_session()

    # ---------------------------------------------------------
    # TEST 3: ASM Self-Inflicted DoS
    # ---------------------------------------------------------
    print("\n[TEST 3] Edge Case 21: ASM Self-Inflicted DoS (Rebalance Power)")
    
    session_id_3 = orchestrator.session_manager.create_new_session()
    raw_asm_log = "GROUP_NUMBER OPERATION STATE POWER\n1 REBAL RUN 11"
    res_3 = orchestrator.handle_enriched_query(session_id_3, "Storage is slow.", raw_log_text=raw_asm_log)
    
    asm_passed = any("ASM rebalance operation" in rec for rec in res_3.get("recommendations", []))
    if "ASM_HIGH_POWER_REBALANCE" in res_3["active_signals"] and asm_passed:
        print("  ✅ SUCCESS: Detected high-power ASM rebalance and warned against blaming storage.")
    else:
        print(f"  ❌ FAILED: Did not catch ASM rebalance. Signals: {res_3['active_signals']}")

    # ---------------------------------------------------------
    # TEST 4: Desynced Reality (FRA Split Brain)
    # ---------------------------------------------------------
    print("\n[TEST 4] Edge Case 31: Desynced Reality (FRA vs OS)")
    
    session_id_4 = orchestrator.session_manager.create_new_session()
    orchestrator.session_manager.upload_log_to_session(session_id_4, [
        {"hostname": "db01", "timestamp": "2024-04-21T10:00:00", "content": "ORA-19815: WARNING: db_recovery_file_dest_size is 100.00% used", "file_source": "alert_orcl.log"}
    ])
    
    res_4 = orchestrator.handle_enriched_query(session_id_4, "Backups are failing because FRA is full, but df -h says it is empty.")
    
    fra_passed = any("CROSSCHECK ARCHIVELOG ALL" in rec for rec in res_4.get("recommendations", []))
    if fra_passed:
        print("  ✅ SUCCESS: Recommended RMAN Crosscheck to resolve FRA split-brain.")
    else:
        print("  ❌ FAILED: Did not recommend RMAN crosscheck for ORA-19815.")

    # ---------------------------------------------------------
    # TEST 5: Observer Split-Brain (Data Guard)
    # ---------------------------------------------------------
    print("\n[TEST 5] Edge Case 23: Observer Split-Brain")
    
    session_id_5 = orchestrator.session_manager.create_new_session()
    orchestrator.session_manager.upload_log_to_session(session_id_5, [
        {"hostname": "db01", "timestamp": "2024-04-21T10:00:00", "content": "ORA-16625: cannot reach database", "file_source": "alert_orcl.log"}
    ])
    
    res_5 = orchestrator.handle_enriched_query(session_id_5, "Data Guard is failing to failover.")
    
    dg_passed = any("drc*.log" in rec for rec in res_5.get("recommendations", []))
    if dg_passed:
        print("  ✅ SUCCESS: Mandated Data Guard Broker log (drc*.log) analysis for ORA-16625.")
    else:
        print("  ❌ FAILED: Did not mandate drc*.log analysis.")

    # ---------------------------------------------------------
    # TEST 6: Kill -9 Murder
    # ---------------------------------------------------------
    print("\n[TEST 6] Edge Case 17: Kill -9 Murder (Auditd)")
    
    session_id_6 = orchestrator.session_manager.create_new_session()
    raw_audit_log = "type=OBJ_PID msg=audit(1610000000.000:1): opid=1234 op=kill sig=9"
    res_6 = orchestrator.handle_enriched_query(session_id_6, "Database crashed suddenly.", raw_log_text=raw_audit_log)
    
    kill_passed = any("kill -9" in rec for rec in res_6.get("recommendations", []))
    if "AUDITD_KILL_9" in res_6["active_signals"] and kill_passed:
        print("  ✅ SUCCESS: Parsed audit.log and identified user-initiated Kill -9 murder of Oracle process.")
    else:
        print(f"  ❌ FAILED: Did not detect Kill -9. Signals: {res_6['active_signals']}")

    print("\nDone.")

if __name__ == "__main__":
    run_tests()
