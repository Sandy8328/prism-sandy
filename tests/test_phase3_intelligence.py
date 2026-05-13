"""
test_phase3_intelligence.py — Validates the Diagnostic Intelligence logic from Phase 3.

Tests:
1. Sudden Death Paradox (OS_KERNEL_PANIC -> 100% confidence).
2. Cry Wolf Threshold (ORA-3136 with low frequency suppressed, high frequency escalated).
3. AWR Symptom vs Disease (log file sync + CPU_SATURATION -> STARVED_IO_THREAD).
4. OOM Collateral Damage (OS_OOM_KILLER targeting multipathd).
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.agent.evidence_aggregator import compute_confidence

def run_tests():
    print("\n==================================================")
    print(" 🧠 RUNNING PHASE 3 INTELLIGENCE TESTS")
    print("==================================================")

    # ---------------------------------------------------------
    # TEST 1: Sudden Death Paradox
    # ---------------------------------------------------------
    print("\n[TEST 1] Edge Case 4: Sudden Death Paradox (Kernel Panic)")
    anchor_1 = {"root_cause": "OS_KERNEL_PANIC", "raw_content": "kernel panic - not syncing"}
    res_1 = compute_confidence(anchor_1, None, None, False)
    if res_1["confidence_score"] == 100 and "SUDDEN_DEATH_OVERRIDE" in res_1["active_signals"]:
        print("  ✅ SUCCESS: Kernel Panic automatically forced 100% confidence override.")
    else:
        print(f"  ❌ FAILED: Did not override confidence. Score: {res_1['confidence_score']}")

    # ---------------------------------------------------------
    # TEST 2: Cry Wolf Threshold
    # ---------------------------------------------------------
    print("\n[TEST 2] Edge Case 11: Cry Wolf Threshold (ORA-3136)")
    # Low frequency (should be suppressed)
    anchor_2_low = {"root_cause": "ORA-3136", "frequency": 5}
    res_2_low = compute_confidence(anchor_2_low, None, None, False)
    
    # High frequency (should be escalated)
    anchor_2_high = {"root_cause": "ORA-3136", "frequency": 150}
    res_2_high = compute_confidence(anchor_2_high, None, None, False)

    if "CRY_WOLF_SUPPRESSED" in res_2_low["active_signals"] and "CRY_WOLF_ESCALATED" in res_2_high["active_signals"]:
        print("  ✅ SUCCESS: Correctly suppressed low-frequency ORA-3136 and escalated high-frequency attack.")
    else:
        print("  ❌ FAILED: Did not apply volume-aware thresholds properly.")

    # ---------------------------------------------------------
    # TEST 3: AWR Symptom vs Disease
    # ---------------------------------------------------------
    print("\n[TEST 3] Edge Case 13: AWR Symptom vs Disease (Starved I/O)")
    # anchor isn't needed here, just AWR and OSW signals
    awr_result = {"awr_signals": ["LOG_FILE_SYNC"]}
    osw_result = {"osw_signals": ["CPU_SATURATION"]}
    res_3 = compute_confidence(None, awr_result, osw_result, False)
    
    if "STARVED_IO_THREAD" in res_3["active_signals"] and "LOG_FILE_SYNC" not in res_3["active_signals"]:
        print("  ✅ SUCCESS: Correctly diagnosed CPU starvation instead of blaming storage hardware.")
    else:
        print(f"  ❌ FAILED: Did not override log file sync. Signals: {res_3['active_signals']}")

    # ---------------------------------------------------------
    # TEST 4: OOM Collateral Damage
    # ---------------------------------------------------------
    print("\n[TEST 4] Edge Case 25: OOM Collateral Damage (multipathd)")
    anchor_4 = {
        "root_cause": "OS_OOM_KILLER", 
        "raw_content": "kernel: Out of memory: Kill process 14823 (multipathd) score 962"
    }
    res_4 = compute_confidence(anchor_4, None, None, False)
    
    if res_4["confidence_score"] == 100 and "CRITICAL_DAEMON_KILLED" in res_4["active_signals"]:
        print("  ✅ SUCCESS: Detected OOM Killer targeting critical storage daemon (multipathd).")
    else:
        print(f"  ❌ FAILED: Missed collateral damage. Signals: {res_4['active_signals']}")

    print("\nDone.")

if __name__ == "__main__":
    run_tests()
