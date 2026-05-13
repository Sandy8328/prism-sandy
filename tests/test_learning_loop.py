import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from src.agent.orchestrator import DBAChatbotOrchestrator
from src.knowledge_graph.graph import get_commands_for_ora

def main():
    print("==================================================")
    print(" 🛠️  RUNNING PHASE 5: DYNAMIC LEARNING LOOP TEST")
    print("==================================================")

    agent = DBAChatbotOrchestrator()
    
    zero_day_error = "ORA-99999"
    log_snippet = "ORA-99999: internal zero-day memory corruption detected."
    runbook_commands = [
        "alter system flush shared_pool;",
        "alter system set events '99999 trace name context forever, level 1';"
    ]

    print(f"\n[TEST 1] Before Learning: Querying {zero_day_error}...")
    result_before = get_commands_for_ora(zero_day_error)
    print(f"Commands before: {result_before['commands']}")
    
    print("\n[TEST 2] Triggering DBA Feedback Loop...")
    agent.submit_dba_feedback(
        error_code=zero_day_error,
        log_snippet=log_snippet,
        runbook_commands=runbook_commands,
        platform="LINUX",
        category="DB",
        layer="DB",
        fix_tier="Database"
    )

    print(f"\n[TEST 3] After Learning: Querying {zero_day_error}...")
    result_after = get_commands_for_ora(zero_day_error)
    print(f"Commands after: {result_after['commands']}")
    
    if result_after['commands'] == runbook_commands:
        print("\n✅ SUCCESS: The Agent successfully learned a new zero-day error dynamically without a restart!")
    else:
        print("\n❌ FAILURE: Agent failed to learn the new commands!")

if __name__ == "__main__":
    main()
