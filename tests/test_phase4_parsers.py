"""
test_phase4_parsers.py — Validates the specific parsers and handlers from Phase 4.

Tests:
1. Inode Exhaustion (ORA-27040 triggers df -i recommendation).
2. Unkillable Zombie (vmstat 'b' column > 0 triggers PROCESS_D_STATE_ZOMBIE and recommendation).
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.orchestrator import DBAChatbotOrchestrator
from src.parsers.osw_parser import parse_osw_text

def run_tests():
    print("\n==================================================")
    print(" 🛠️  RUNNING PHASE 4 PARSER TESTS (PART 1)")
    print("==================================================")

    orchestrator = DBAChatbotOrchestrator()
    session_id = orchestrator.session_manager.create_new_session()

    # ---------------------------------------------------------
    # TEST 1: Inode Exhaustion (ORA-27040)
    # ---------------------------------------------------------
    print("\n[TEST 1] Edge Case 14: Inode Exhaustion (df -i requirement)")
    
    # Upload ORA-27040 to session
    orchestrator.session_manager.upload_log_to_session(session_id, [
        {"hostname": "db01", "timestamp": "2024-04-21T10:00:00", "content": "ORA-27040: file create error, unable to create file", "file_source": "alert_orcl.log"}
    ])
    
    res_1 = orchestrator.handle_enriched_query(session_id, "Database is failing to create files.")
    
    inode_passed = False
    for rec in res_1.get("recommendations", []):
        if "MANDATORY: Run `df -i`" in rec:
            inode_passed = True
            
    if inode_passed:
        print("  ✅ SUCCESS: Engine proactively demanded an inode check for ORA-27040.")
    else:
        print("  ❌ FAILED: Engine did not recommend df -i.")

    # ---------------------------------------------------------
    # TEST 2: Unkillable Zombie (D State)
    # ---------------------------------------------------------
    print("\n[TEST 2] Edge Case 20: Unkillable Zombie (D State in OSWatcher)")
    
    # OSWatcher vmstat output where the 'b' column (blocked processes) is 3
    osw_text = """
zzz ***Mon Mar 07 03:14:01 IST 2024
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa
 2  3  51200 102400  12800 409600  500 1200  2400  3600 1200 2400 85  8  2  5
"""
    # Write to a temp file to pass to orchestrator
    temp_osw_path = "/tmp/test_osw.dat"
    with open(temp_osw_path, "w") as f:
        f.write(osw_text)
        
    res_2 = orchestrator.handle_enriched_query(session_id, "Processes are hanging and kill -9 doesn't work.", osw_filepath=temp_osw_path)
    
    zombie_passed = False
    for rec in res_2.get("recommendations", []):
        if "stuck in 'D' state" in rec:
            zombie_passed = True
            
    if "PROCESS_D_STATE_ZOMBIE" in res_2["active_signals"] and zombie_passed:
        print("  ✅ SUCCESS: Detected processes stuck in D state (I/O hang) from vmstat 'b' column.")
    else:
        print(f"  ❌ FAILED: Did not detect D state zombies. Signals: {res_2['active_signals']}")

    # Cleanup
    if os.path.exists(temp_osw_path):
        os.remove(temp_osw_path)

    print("\nDone.")

if __name__ == "__main__":
    run_tests()
