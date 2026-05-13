import sys
import os

# Add root directory to python path to import src
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
os.chdir(project_root)  # Ensure we are in the root so config/settings.yaml is found

from src.agent.scorer import compute_score

def run_simulation():
    print("=" * 60)
    print(" ORACLE DBA DIAGNOSTIC AGENT - CONFIDENCE SCORE SIMULATION")
    print("=" * 60)
    
    # Simulate reading the files
    try:
        with open("tests/simulated_logs/alert_dbhost01.log", "r") as f:
            alert_log = f.read()
        with open("tests/simulated_logs/messages_dbhost01", "r") as f:
            syslog = f.read()
    except FileNotFoundError:
        print("Error: Run this script from the dba_agent root directory.")
        return

    print("\n[+] Ingested Alert Log (dbhost01):")
    print("    Detected ORA-27072 at 02:44:19")
    print("\n[+] Ingested OS Syslog (dbhost01):")
    print("    Detected scsi timeout at 02:44:04")
    
    print("\n[+] Temporal Correlator Analysis:")
    print("    - Same Hostname? YES (dbhost01)")
    print("    - Within 60 Seconds? YES (15s gap)")
    print("    -> Awarding Temporal Correlator Bonus: 10 points")

    # The actual retrieval pipeline would output these metrics for the top candidate
    pattern_conf = 95.0   # Regex matched ORA-27072 perfectly
    bm25_raw = 18.2       # High BM25 score
    max_bm25 = 20.0       # Max query BM25
    dense_score = 0.89    # Semantic similarity is 89%
    temporal_bonus = 10   # Awarded from correlation
    
    # Run through the REAL scorer engine
    result = compute_score(
        pattern_confidence=pattern_conf,
        bm25_score=bm25_raw,
        dense_score=dense_score,
        temporal_bonus=temporal_bonus,
        max_bm25=max_bm25
    )
    
    print("\n" + "=" * 60)
    print(f" FINAL DIAGNOSTIC CONFIDENCE: {result['score']}/100")
    print(f" LABEL:                       {result['label']}")
    print("=" * 60)
    print(" Scoring Breakdown:")
    for metric, value in result['breakdown'].items():
        print(f"    - {metric.ljust(10)} : {value} pts")
    print("=" * 60)
    
    # Simulate the Missing Correlation edge case
    print("\n\n[!] SIMULATING EDGE CASE: Missing OS Log (Fragmented Upload)")
    print("    User only uploads alert.log, no syslog provided.")
    
    result_no_os = compute_score(
        pattern_confidence=pattern_conf,
        bm25_score=bm25_raw,
        dense_score=dense_score,
        temporal_bonus=0, # ZERO bonus because no corroboration
        max_bm25=max_bm25
    )
    
    print(f"\n -> NEW CONFIDENCE SCORE: {result_no_os['score']}/100 ({result_no_os['label']})")
    print(" -> Because Temporal Bonus is 0, confidence drops from HIGH to MEDIUM.")
    print(" -> The Chatbot must now ask the user to upload /var/log/messages!")
    print("\nSimulation Complete.\n")

if __name__ == "__main__":
    run_simulation()
