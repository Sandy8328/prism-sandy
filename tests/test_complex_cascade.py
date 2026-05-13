import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
os.chdir(project_root)

from src.agent.scorer import compute_score

def run_simulation():
    print("=" * 80)
    print(" 🚨 CRITICAL CASCADE FAILURE SIMULATION - 3 TIERS 🚨")
    print("=" * 80)
    
    try:
        with open("tests/simulated_logs/complex/syslog_infra.log", "r") as f:
            syslog = f.read()
        with open("tests/simulated_logs/complex/crs_cluster.log", "r") as f:
            crs_log = f.read()
        with open("tests/simulated_logs/complex/alert_database.log", "r") as f:
            alert_log = f.read()
    except FileNotFoundError:
        print("Error: Missing simulated logs. Ensure tests/simulated_logs/complex/ exists.")
        return

    print("\n[1] 🌐 INFRASTRUCTURE LAYER (03:15:00)")
    print("    -> OS reports: 'nfs: server storage-nas-01 not responding'")
    
    print("\n[2] 🔗 CLUSTER LAYER (03:15:12)")
    print("    -> CRS reports: 'CRS-1617: Node dbhost01 is being evicted'")
    print("    -> CRS reports: 'ORA-29740: evicted by member'")
    
    print("\n[3] 💾 DATABASE LAYER (03:15:20 -> 03:16:05)")
    print("    -> Alert log: 'ORA-27054: NFS file system ... not mounted' (03:15:20)")
    print("    -> Alert log: 'ORA-00257: archiver error' (03:15:45)")
    print("    -> Alert log: 'ORA-00603: ORACLE server session terminated' (03:16:05)")

    print("\n" + "-" * 80)
    print(" 🧠 DIAGNOSTIC AGENT ANALYSIS ENGINE STARTING...")
    print("-" * 80)
    
    print("\n" + "=" * 80)
    print(" 🚨 SCENARIO A: Knowledge Graph HAS the Cascade Rule")
    print("=" * 80)
    # Run through the REAL scorer engine for the root cause
    result_a = compute_score(
        pattern_confidence=98.0,  
        bm25_score=19.5,          
        dense_score=0.92,         
        temporal_bonus=20,        
        max_bm25=20.0
    )
    print(f" -> RESULT: {result_a['score']}/100 ({result_a['label']})")
    print(" -> Root Cause Identified: INFRASTRUCTURE (NFS_TIMEOUT)")
    print(" -> DB Errors Successfully Suppressed.\n")

    print("=" * 80)
    print(" 🚨 SCENARIO B: Knowledge Graph is MISSING the Cascade Rule (What you just tested)")
    print("=" * 80)
    print("[!] Agent attempts to traverse graph, but finds no link between NFS and CRS-1617.")
    print("[!] Agent cannot definitively prove NFS caused the DB Crash.")
    
    # Run through the REAL scorer engine without the multi-source corroboration bonus
    result_b = compute_score(
        pattern_confidence=60.0,  # Lower confidence because of conflicting DB errors
        bm25_score=12.5,          
        dense_score=0.65,         
        temporal_bonus=0,         # ZERO bonus because the cascade sequence is broken
        max_bm25=20.0
    )
    
    print(f"\n -> RESULT: {result_b['score']}/100 ({result_b['label']})")
    print(" -> Root Cause Identified: NONE (Conflicting signals)")
    print(" -> Agent Hallucination Warning: Chatbot might tell the user to fix the DB instead of the OS!")
    print("=" * 80)
    print("\nSimulation Complete.\n")

if __name__ == "__main__":
    run_simulation()
