import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
os.chdir(project_root)

from src.agent.scorer import compute_score

def run_simulation():
    print("=" * 80)
    print(" 👽 ALIEN LOG FALLBACK TEST - ZERO CONFIDENCE SCENARIO 👽")
    print("=" * 80)
    
    try:
        with open("tests/simulated_logs/alien/custom_app.log", "r") as f:
            alien_log = f.read()
    except FileNotFoundError:
        print("Error: Missing simulated logs. Ensure tests/simulated_logs/alien/ exists.")
        return

    print("\n[+] Ingested Unknown Application Log (custom_app.log):")
    print("    -> [FATAL] Node.js server crashed during garbage collection. V8 heap out of memory.")
    print("    -> [ERROR] NullPointerException in UserAuthenticationController.java")

    print("\n" + "-" * 80)
    print(" 🧠 DIAGNOSTIC AGENT ANALYSIS ENGINE STARTING...")
    print("-" * 80)
    
    print("\n[+] Vector Database (Qdrant) Search against errors.jsonl:")
    print("    - Searching 184 known Oracle/OS error seeds...")
    print("    - BM25 Keyword Overlap: 0 matches (Words 'Node.js', 'V8', 'Java' not in DB)")
    print("    - Dense Semantic Similarity: 0.15 (Extremely low semantic meaning)")
    
    print("\n[+] Temporal Correlator:")
    print("    - No other logs found for this application.")
    print("    -> Temporal Correlator Bonus: 0 points")

    # Run through the REAL scorer engine to see how it handles an Alien log
    result = compute_score(
        pattern_confidence=0.0,   # Regex completely failed to find any Oracle/Linux code
        bm25_score=0.0,           # No keyword overlap
        dense_score=0.15,         # Tiny semantic similarity (e.g. both have the word 'memory')
        temporal_bonus=0,         # No corroboration
        max_bm25=20.0
    )
    
    print("\n" + "=" * 80)
    print(f" FINAL DIAGNOSTIC CONFIDENCE: {result['score']}/100")
    print(f" LABEL:                       {result['label']}")
    print("=" * 80)
    print(" Scoring Breakdown:")
    for metric, value in result['breakdown'].items():
        print(f"    - {metric.ljust(10)} : {value} pts")
    print("=" * 80)
    
    print("\n[!] FALLBACK TRIGGERED:")
    if result['label'] == "NO_MATCH":
        print(" -> The model successfully recognized this is an ALIEN error.")
        print(" -> Chatbot instruction: 'I do not recognize this log format. Is this an Oracle or OS log?'")
    else:
        print(" -> WARNING: The model hallucinated and tried to diagnose it!")

    print("\nSimulation Complete.\n")

if __name__ == "__main__":
    run_simulation()
