import csv
import json
import sys
import io
import re
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from src.agent.orchestrator import DBAChatbotOrchestrator

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

def run_qa_matrix(
    input_csv  = os.path.join(_TESTS_DIR, "qa_matrix.csv"),
    output_csv = os.path.join(_TESTS_DIR, "qa_results_report.csv"),
):
    print("\n" + "=" * 80)
    print(" 🧪 PHASE 5: COMPREHENSIVE QA MATRIX EXECUTION (DATA-DRIVEN)")
    print("=" * 80)
    
    if not os.path.exists(input_csv):
        print(f"[!] Error: {input_csv} not found.")
        return

    orchestrator = DBAChatbotOrchestrator()
    
    total_tests = 0
    passed_tests = 0
    failed_tests = []
    
    results_data = []

    with open(input_csv, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + [
            "Actual_Agent_Output",
            "Remediation_Commands",
            "Fix_Node",
            "Issue_Category",
            "Confidence_Score",
            "Confidence_Label",
            "Risk_Score",
            "Knowledge_Stored",
            "QA_Status",
        ]
        
        for row in reader:
            total_tests += 1
            test_id = row['Test_ID']
            scenario_type = row['Scenario_Type']
            description = row['Description']
            logs_json = row['Log_Simulations']
            user_query = row['User_Query']
            expected_regex = row['Expected_Behavior_Regex']

            print(f"\n[Running] {test_id} ({scenario_type}): {description}")
            
            # Create a fresh session for each test
            session_id = orchestrator.session_manager.create_new_session()
            
            # Parse and upload the dynamic logs
            try:
                log_chunks = json.loads(logs_json)
                if log_chunks:
                    orchestrator.session_manager.upload_log_to_session(session_id, log_chunks)
            except Exception as e:
                print(f"  -> [Error] Failed to parse JSON logs for {test_id}: {e}")
                row["Actual_Agent_Output"] = f"SYSTEM ERROR: Invalid JSON Logs - {e}"
                row["QA_Status"] = "❌ FAIL"
                results_data.append(row)
                failed_tests.append((test_id, "JSON Parse Error"))
                continue

            # Intercept the stdout from the Chatbot Orchestrator
            old_stdout = sys.stdout
            new_stdout = io.StringIO()
            sys.stdout = new_stdout
            
            try:
                # Run full enriched pipeline (AWR/OSW default to None — alert log only)
                result_dict = orchestrator.handle_enriched_query(session_id, user_query)
            except Exception as e:
                print(f"Agent Crashed: {e}")
                result_dict = None
            
            # Restore stdout
            sys.stdout = old_stdout
            agent_output = new_stdout.getvalue()
            
            # Verify against Expected Regex
            if re.search(expected_regex, agent_output, re.IGNORECASE | re.DOTALL):
                print("  -> ✅ PASS")
                passed_tests += 1
                row["QA_Status"] = "✅ PASS"
            else:
                print("  -> ❌ FAIL")
                failed_tests.append((test_id, "Regex Mismatch"))
                row["QA_Status"] = "❌ FAIL"
                
            # Build Executive Summary and extract commands
            if result_dict and "root_cause" in result_dict:
                # Format resolution as bullet points
                res_text = result_dict['resolution'].strip()
                sentences = [s.strip() + "." for s in res_text.split(". ") if s.strip()]
                if not sentences:
                    sentences = [res_text]
                bullet_resolution = "\n  • " + "\n  • ".join(sentences)

                clean_output = f"🔴 ROOT CAUSE: {result_dict['root_cause']}\n"
                clean_output += f"🕒 TIMESTAMP: {result_dict['timestamp']}\n\n"
                clean_output += f"🛠️ RESOLUTION PLAN:{bullet_resolution}"

                # Format commands as a numbered list
                cmds = result_dict.get("commands", [])
                if cmds:
                    numbered_cmds = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(cmds))
                else:
                    numbered_cmds = "  (No commands available for this error code)"

                row["Remediation_Commands"] = numbered_cmds
                row["Fix_Node"]             = result_dict.get("fix_node_id") or "N/A"
                row["Issue_Category"]       = result_dict.get("issue_category", "N/A")
                row["Confidence_Score"]     = result_dict.get("confidence_score", "N/A")
                row["Confidence_Label"]     = result_dict.get("confidence_label", "N/A")
                row["Risk_Score"]           = result_dict.get("risk_score", "N/A")
                row["Knowledge_Stored"]     = result_dict.get("knowledge_stored", False)
            else:
                # Fallback for firewall rejections or crashes
                clean_output = re.sub(r'={20,}', '', agent_output).strip()
                row["Remediation_Commands"] = "  (Firewall blocked or agent crashed)"
                row["Fix_Node"]             = "N/A"
                row["Issue_Category"]       = "N/A"
                row["Confidence_Score"]     = "N/A"
                row["Confidence_Label"]     = "N/A"
                row["Risk_Score"]           = "N/A"
                row["Knowledge_Stored"]     = False

            row["Actual_Agent_Output"] = clean_output
            results_data.append(row)

    # Write the Final Audit Report CSV
    with open(output_csv, mode='w', newline='', encoding='utf-8-sig') as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results_data)

    # Final CLI Report
    print("\n" + "=" * 80)
    print(" 📊 QA MATRIX FINAL REPORT")
    print("=" * 80)
    print(f"Total Scenarios Run: {total_tests}")
    print(f"Total Passed:        {passed_tests}")
    print(f"Total Failed:        {len(failed_tests)}")
    print(f"\n[!] The full Audit Report has been saved to: {output_csv}")
    
    if failed_tests:
        print("\n[!] VERDICT: DO NOT DEPLOY TO PRODUCTION. Fix failing edge cases.")
    else:
        print("\n[!] VERDICT: 100% PASS RATE ACHIEVED. Architecture is Production-Ready.")

if __name__ == "__main__":
    run_qa_matrix()
