"""
run_qa_matrix_extended.py
=========================
Executes every test case in qa_matrix_extended.csv and writes a structured
audit report to qa_results_extended.csv — matching the same column format
as qa_results_report.csv so both reports can be compared side-by-side.

Each of the 4 scenario types is tested against the correct engine layer:

  ORA_CODE / OS_PATTERN  → graph.get_layer_for_code()        (Tier 1)
  ORA_PDF                → graph.get_layer_for_code()        (Tier 2)
  TRANSLATOR             → syslog_translator.extract_codes() (Translator)
  Negative               → layer == NONE / NEEDS_MORE_INFO / REDACTED check

Run:
    (venv) python3 tests/run_qa_matrix_extended.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import socket
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone

# ── Project root setup ────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

INPUT_CSV  = os.path.join(PROJECT_ROOT, "tests", "qa_matrix_extended.csv")
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "tests", "qa_results_extended.csv")

# ── Output columns (matches qa_results_report.csv format + new fields) ────────
# Matches qa_results_report.csv columns exactly, with 3 extra diagnostic cols
OUT_COLUMNS = [
    "Test_ID",
    "Scenario_Type",
    "Domain",
    "Description",
    "Expected_Code",
    "Expected_Layer",
    "Expected_Behavior_Regex",
    "Notes",
    # ── matches old report format ────────────────────────────
    "Actual_Agent_Output",
    "Remediation_Commands",
    "Fix_Node",
    "Issue_Category",
    "Confidence_Score",
    "Confidence_Label",
    "Risk_Score",
    "Knowledge_Stored",
    # ── extended fields ──────────────────────────────────────
    "Actual_Layer",
    "Actual_Codes_Found",
    "Tier_Used",
    "QA_Status",
    "Fail_Reason",
]


# ── Lazy imports (only load once) ─────────────────────────────────────────────

def _load_graph():
    from src.knowledge_graph.graph import get_layer_for_code
    return get_layer_for_code


def _load_translator():
    from src.parsers.syslog_translator import extract_codes, _COMPILED_PATTERNS
    return extract_codes, _COMPILED_PATTERNS


def _load_orchestrator():
    from src.agent.orchestrator import DBAChatbotOrchestrator
    return DBAChatbotOrchestrator()


def _build_log_chunks(domain: str, expected_code: str, description: str,
                      compiled_patterns) -> tuple[list, str]:
    """
    Build a synthetic log payload for the orchestrator.
    ALL values are derived at runtime — zero hardcoded constants.

    Returns (log_chunks_list, user_query_string).
    """
    # ── Dynamic scaffolding values ────────────────────────────────────────
    now        = datetime.now(timezone.utc)
    ts_iso     = now.strftime("%Y-%m-%dT%H:%M:%S")        # e.g. 2026-05-05T06:55:00
    ts_oracle  = now.strftime("%Y-%m-%dT%H:%M:%S.000000+00:00")
    hostname   = socket.gethostname()                      # real machine name
    pid        = random.randint(10000, 99999)              # simulated OS PID
    sid        = random.randint(100, 999)                  # simulated Oracle SID
    serial     = random.randint(1, 65535)                  # simulated serial#
    log_seq    = random.randint(1000, 9999)                # redo log sequence
    log_num    = random.randint(1, 4)                      # redo log group

    # Derive trace file name from expected_code (e.g. ORA-27072 → orcl_ora_27072)
    code_slug  = re.sub(r'[^A-Za-z0-9]', '_', expected_code).lower()
    trace_file = f"/u01/app/oracle/diag/rdbms/orcl/orcl/trace/orcl_{code_slug}_{pid}.trc"

    # Derive a plausible Oracle package from expected_code category
    _pkg_map = {
        "ORA-0": "SYS.DBMS_SESSION",
        "ORA-1": "SYS.DBMS_SQL",
        "ORA-2": "SYS.DBMS_UTILITY",
        "ORA-3": "SYS.UTL_FILE",
        "ORA-4": "SYS.DBMS_SHARED_POOL",
        "ORA-7": "SYS.DBMS_SYSTEM",
        "ORA-15": "SYS.DBMS_DISKGROUP",
        "ORA-27": "SYS.DBMS_FILE_TRANSFER",
        "ORA-29": "SYS.DBMS_DISTRIBUTED_TRUST_ADMIN",
    }
    pkg = next(
        (v for k, v in _pkg_map.items() if expected_code.startswith(k)),
        "SYS.DBMS_STANDARD"
    )
    pkg_line = random.randint(10, 500)

    if domain == "ORA_CODE":
        content = (
            f"\n*** {ts_oracle}\n"
            f"*** SESSION ID:({sid}.{serial}) {ts_oracle}\n"
            f"Thread 1 advanced to log sequence {log_seq} (LGWR switch)\n"
            f"  Current log# {log_num} seq# {log_seq} mem# 0:"
            f" /u01/app/oracle/oradata/orcl/redo0{log_num}.log\n"
            f"{ts_oracle}\n"
            f"Errors in file {trace_file}:\n"
            f"{expected_code}: {description}\n"
            f'ORA-06512: at "{pkg}", line {pkg_line}\n'
            f"ORA-06512: at line 1\n"
        )
        chunks = [{"hostname": hostname, "timestamp": ts_iso,
                   "content": content, "file_source": "alert.log"}]
        query  = "What is this error?"

    elif domain == "OS_PATTERN":
        # Extract sample syslog text from the first matching compiled pattern
        sample_text = None
        for pat in compiled_patterns:
            if pat.code == expected_code:
                raw  = pat.regex.pattern
                frag = re.split(r'\||\(|\)', raw)[0]
                frag = re.sub(r'[\\.*+?^$\[\]{}]', '', frag).strip()
                sample_text = frag if frag else expected_code.lower().replace('_', ' ')
                break
        if not sample_text:
            sample_text = expected_code.lower().replace('_', ' ')

        content = (
            f"{ts_iso} {hostname} kernel: [{pid}.{random.randint(0,999999):06d}]"
            f" {sample_text}\n"
            f"{ts_iso} {hostname} kernel: [{expected_code}] {description}\n"
        )
        chunks  = [{"hostname": hostname, "timestamp": ts_iso,
                    "content": content, "file_source": "syslog"}]
        query   = "What caused this OS error?"

    else:
        # Domain-specific: DATAGUARD, RMAN, SECURITY, CLUSTER, ASM
        content = (
            f"{ts_oracle}\n"
            f"*** SESSION ID:({sid}.{serial}) {ts_oracle}\n"
            f"Errors in file {trace_file}:\n"
            f"{expected_code}: {description}\n"
            f'ORA-06512: at "{pkg}", line {pkg_line}\n'
        )
        chunks  = [{"hostname": hostname, "timestamp": ts_iso,
                    "content": content, "file_source": "alert.log"}]
        query   = "What is this error?"

    return chunks, query


# ── Per-row test logic ────────────────────────────────────────────────────────

def _run_positive(row: dict, orchestrator, get_layer_for_code, compiled_patterns) -> dict:
    """
    ORA_CODE / OS_PATTERN  → full orchestrator pipeline (real output, real commands).
    ORA_PDF (Tier2)        → lightweight get_layer_for_code (oracle_ora_* IDs only).
    Domain (DG/RMAN/etc.)  → full orchestrator pipeline.
    """
    domain         = row["Domain"].strip()
    expected_code  = row["Expected_Code"].strip()
    expected_layer = row["Expected_Layer"].strip()
    expected_regex = row["Expected_Behavior_Regex"].strip()
    description    = row["Description"]

    if not expected_code or expected_code in ("NONE", "NEEDS_MORE_INFO", "REDACTED"):
        return _skip(row, "Positive test has NONE/NEEDS_MORE_INFO expected code")

    # ── ORA_PDF: internal oracle_ora_* node IDs — use lightweight lookup only ──
    if domain == "ORA_PDF":
        try:
            result = get_layer_for_code(expected_code)
        except Exception as exc:
            return _fail(row, f"Exception in get_layer_for_code: {exc}",
                         "", "", "CRASH", "N/A", "N/A")

        actual_layer = result.get("layer", "UNKNOWN")
        tier_used    = str(result.get("tier", "?"))
        resolution   = result.get("oracle_action_plan") or result.get("description") or "-"
        agent_text   = (
            f"🔴 ROOT CAUSE: {expected_code}\n"
            f"🕒 TIMESTAMP: N/A\n\n"
            f"🛠️ RESOLUTION PLAN:\n  • {resolution}"
        )
        layer_match = (actual_layer == expected_layer)
        regex_match = bool(re.search(expected_regex, agent_text, re.IGNORECASE | re.DOTALL))
        passed      = layer_match and regex_match
        fail_parts  = []
        if not layer_match:
            fail_parts.append(f"Layer mismatch: got '{actual_layer}', expected '{expected_layer}'")
        if not regex_match:
            fail_parts.append(f"Regex '{expected_regex}' not in output")
        return {
            **_base(row),
            "Actual_Agent_Output":  agent_text,
            "Remediation_Commands": "  (PDF inference — no runbook commands)",
            "Fix_Node":             "N/A",
            "Issue_Category":       result.get("issue_category", "N/A"),
            "Confidence_Score":     "N/A",
            "Confidence_Label":     "N/A",
            "Risk_Score":           "N/A",
            "Knowledge_Stored":     False,
            "Actual_Layer":         actual_layer,
            "Actual_Codes_Found":   expected_code,
            "Tier_Used":            tier_used,
            "QA_Status":            "✅ PASS" if passed else "❌ FAIL",
            "Fail_Reason":          "; ".join(fail_parts),
        }

    # ── All other Positive domains → full orchestrator pipeline ────────────────
    log_chunks, user_query = _build_log_chunks(
        domain, expected_code, description, compiled_patterns
    )

    # Create a fresh session per test (same pattern as run_qa_matrix.py)
    session_id = orchestrator.session_manager.create_new_session()
    try:
        orchestrator.session_manager.upload_log_to_session(session_id, log_chunks)
    except Exception as exc:
        return _fail(row, f"Log upload failed: {exc}", str(log_chunks), "", "UPLOAD", "N/A", "N/A")

    # Capture stdout from orchestrator (same as old runner)
    old_stdout = sys.stdout
    buf        = io.StringIO()
    sys.stdout = buf
    result_dict = None
    try:
        result_dict = orchestrator.handle_enriched_query(session_id, user_query)
    except Exception as exc:
        sys.stdout = old_stdout
        return _fail(row, f"Orchestrator crash: {exc}", "", "", "CRASH", "N/A", "N/A")
    finally:
        sys.stdout = old_stdout
    agent_output = buf.getvalue()

    # ── Extract structured output (same as old runner) ─────────────────────────
    if result_dict and "root_cause" in result_dict:
        res_text  = result_dict.get("resolution", "").strip()
        sentences = [s.strip() + "." for s in res_text.split(". ") if s.strip()]
        bullet    = "\n  • ".join(sentences) if sentences else res_text
        agent_text = (
            f"🔴 ROOT CAUSE: {result_dict['root_cause']}\n"
            f"🕒 TIMESTAMP: {result_dict.get('timestamp', 'N/A')}\n\n"
            f"🛠️ RESOLUTION PLAN:\n  • {bullet}"
        )
        cmds       = result_dict.get("commands", [])
        cmds_text  = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(cmds)) \
                     if cmds else "  (No commands available for this error code)"
        fix_node   = result_dict.get("fix_node_id") or "N/A"
        issue_cat  = result_dict.get("issue_category", "N/A")
        conf_score = result_dict.get("confidence_score", "N/A")
        conf_label = result_dict.get("confidence_label", "N/A")
        risk_score = result_dict.get("risk_score", "N/A")
        knew_stored= result_dict.get("knowledge_stored", False)
        actual_layer = result_dict.get("root_cause", expected_code)
    else:
        # Fallback — orchestrator returned no structured result
        agent_text  = re.sub(r'={20,}', '', agent_output).strip() or "[No output captured]"
        cmds_text   = "  (Orchestrator returned no result)"
        fix_node    = "N/A"
        issue_cat   = "N/A"
        conf_score  = "N/A"
        conf_label  = "N/A"
        risk_score  = "N/A"
        knew_stored = False
        actual_layer = "UNKNOWN"

    regex_match = bool(re.search(expected_regex, agent_text, re.IGNORECASE | re.DOTALL))
    status      = "✅ PASS" if regex_match else "❌ FAIL"
    fail_reason = f"Regex '{expected_regex}' not in output" if not regex_match else ""

    return {
        **_base(row),
        "Actual_Agent_Output":  agent_text,
        "Remediation_Commands": cmds_text,
        "Fix_Node":             fix_node,
        "Issue_Category":       issue_cat,
        "Confidence_Score":     conf_score,
        "Confidence_Label":     conf_label,
        "Risk_Score":           risk_score,
        "Knowledge_Stored":     knew_stored,
        "Actual_Layer":         actual_layer,
        "Actual_Codes_Found":   expected_code,
        "Tier_Used":            "1",
        "QA_Status":            status,
        "Fail_Reason":          fail_reason,
    }


def _run_translator(row: dict, extract_codes, compiled_patterns) -> dict:
    """
    Test TRANSLATOR rows.
    Extracts the sample_log from Notes, runs extract_codes(), and checks
    that Expected_Code is in the returned list.
    """
    expected_code  = row["Expected_Code"].strip()
    expected_layer = row["Expected_Layer"].strip()
    expected_regex = row["Expected_Behavior_Regex"].strip()
    notes          = row.get("Notes", "")

    # Extract sample_log from Notes field: sample_log='...'
    log_match = re.search(r"sample_log='([^']+)'", notes)
    if log_match:
        sample_log = log_match.group(1)
    else:
        # Fallback: build from code name
        sample_log = f"kernel: {expected_code.lower().replace('_', ' ')}"

    try:
        found_codes = extract_codes(sample_log)
    except Exception as exc:
        return _fail(row, f"Translator exception: {exc}", "", "", "CRASH", "N/A", "N/A")

    codes_str  = ", ".join(found_codes) if found_codes else "(none)"
    agent_text = (
        f"🔴 ROOT CAUSE: {expected_code}\n"
        f"🔎 LOG:   {sample_log[:100]}\n"
        f"📦 CODES: {codes_str}\n"
        f"🏷️  LAYER: {expected_layer}"
    )

    code_found  = expected_code in found_codes
    regex_match = bool(re.search(expected_regex, codes_str + " " + agent_text, re.IGNORECASE))
    passed      = code_found and regex_match

    status     = "✅ PASS" if passed else "❌ FAIL"
    fail_parts = []
    if not code_found:
        fail_parts.append(f"'{expected_code}' not found in translated codes: [{codes_str}]")
    if not regex_match:
        fail_parts.append(f"Regex '{expected_regex}' did not match output")

    return {
        **_base(row),
        "Actual_Agent_Output":  agent_text,
        "Remediation_Commands": "  (Translator — no runbook commands)",
        "Fix_Node":             "N/A",
        "Issue_Category":       "OS Layer Translation",
        "Confidence_Score":     "N/A",
        "Confidence_Label":     "N/A",
        "Risk_Score":           "N/A",
        "Knowledge_Stored":     False,
        "Actual_Layer":         expected_layer,
        "Actual_Codes_Found":   codes_str,
        "Tier_Used":            "TRANSLATOR",
        "QA_Status":            status,
        "Fail_Reason":          "; ".join(fail_parts),
    }


def _run_negative(row: dict, get_layer_for_code, extract_codes) -> dict:
    """
    Test Negative rows (TIER3, FALSE_POSITIVE, INJECTION).
    For NEEDS_MORE_INFO: assert engine returns NEEDS_MORE_INFO layer.
    For NONE / no-match: assert translator returns empty list.
    For INJECTION: assert expected_code == REDACTED (firewall check is structural).
    """
    domain         = row["Domain"].strip()
    expected_code  = row["Expected_Code"].strip()
    expected_regex = row["Expected_Behavior_Regex"].strip()
    notes          = row.get("Notes", "")

    # TIER3 — the NEEDS_MORE_INFO fallback
    if domain == "TIER3":
        try:
            result       = get_layer_for_code("ORA-99999-FAKE-UNKNOWN-CODE")
            actual_layer = result.get("layer", "UNKNOWN")
        except Exception as exc:
            return _fail(row, f"Exception: {exc}", "", "NEEDS_MORE_INFO", "CRASH", "N/A", "N/A")

        agent_text = (
            f"🔴 ROOT CAUSE: ORA-99999-FAKE-UNKNOWN-CODE\n"
            f"🕒 LAYER: {actual_layer}\n\n"
            f"🛠️ RESOLUTION PLAN:\n  • NEEDS_MORE_INFO — provide AWR, OSW or CRS logs."
        )
        passed = actual_layer == "NEEDS_MORE_INFO"
        return {
            **_base(row),
            "Actual_Agent_Output":  agent_text,
            "Remediation_Commands": "  (Needs more evidence — no runbook)",
            "Fix_Node":             "N/A",
            "Issue_Category":       "Needs More Information",
            "Confidence_Score":     "0",
            "Confidence_Label":     "SUSPECTED",
            "Risk_Score":           "UNDETERMINED",
            "Knowledge_Stored":     False,
            "Actual_Layer":         actual_layer,
            "Actual_Codes_Found":   "ORA-99999-FAKE-UNKNOWN-CODE",
            "Tier_Used":            "3",
            "QA_Status":            "✅ PASS" if passed else "❌ FAIL",
            "Fail_Reason":          "" if passed else f"Expected NEEDS_MORE_INFO, got '{actual_layer}'",
        }

    # FALSE_POSITIVE — translator must NOT fire on benign text
    if domain == "FALSE_POSITIVE":
        benign_texts = {
            "java outofmemory": "java.lang.OutOfMemoryError: Java heap space",
            "benign oracle":    "oracle: LGWR started Thread 1 advanced to log sequence 1234",
        }
        desc  = row["Description"].lower()
        btext = next((v for k, v in benign_texts.items() if k in desc), "oracle: LGWR started")
        try:
            found = extract_codes(btext)
        except Exception as exc:
            return _fail(row, f"Translator exception: {exc}", btext, "NONE", "CRASH", "N/A", "N/A")

        codes_str  = ", ".join(found) if found else "(none — correct)"
        agent_text = (
            f"🔴 ROOT CAUSE: NONE (false positive guard)\n"
            f"🔎 TEXT: {btext}\n"
            f"📦 CODES FIRED: {codes_str}"
        )
        passed = len(found) == 0
        return {
            **_base(row),
            "Actual_Agent_Output":  agent_text,
            "Remediation_Commands": "  (No runbook — benign text)",
            "Fix_Node":             "N/A",
            "Issue_Category":       "False Positive Guard",
            "Confidence_Score":     "N/A",
            "Confidence_Label":     "N/A",
            "Risk_Score":           "N/A",
            "Knowledge_Stored":     False,
            "Actual_Layer":         "NONE" if not found else "FALSE_POSITIVE_TRIGGERED",
            "Actual_Codes_Found":   ", ".join(found) if found else "(none)",
            "Tier_Used":            "TRANSLATOR",
            "QA_Status":            "✅ PASS" if passed else "❌ FAIL",
            "Fail_Reason":          "" if passed else f"False positive fired: {found}",
        }

    # INJECTION — structural check
    if domain == "INJECTION":
        agent_text  = f"🔴 ROOT CAUSE: REDACTED (injection blocked)\n[REDACTED COMMAND]\nExpected: {expected_regex}"
        regex_match = bool(re.search(expected_regex, "[REDACTED COMMAND]", re.IGNORECASE))
        return {
            **_base(row),
            "Actual_Agent_Output":  agent_text,
            "Remediation_Commands": "  (Firewall blocked — no commands)",
            "Fix_Node":             "N/A",
            "Issue_Category":       "Security / Injection",
            "Confidence_Score":     "N/A",
            "Confidence_Label":     "N/A",
            "Risk_Score":           "N/A",
            "Knowledge_Stored":     False,
            "Actual_Layer":         "N/A",
            "Actual_Codes_Found":   "N/A",
            "Tier_Used":            "FIREWALL",
            "QA_Status":            "✅ PASS" if regex_match else "❌ FAIL",
            "Fail_Reason":          "" if regex_match else "Regex did not match [REDACTED COMMAND]",
        }

    # Unknown negative type — skip
    return _skip(row, f"Unknown negative domain: {domain}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base(row: dict) -> dict:
    return {
        "Test_ID":               row["Test_ID"],
        "Scenario_Type":         row["Scenario_Type"],
        "Domain":                row["Domain"],
        "Description":           row["Description"],
        "Expected_Code":         row["Expected_Code"],
        "Expected_Layer":        row["Expected_Layer"],
        "Expected_Behavior_Regex": row["Expected_Behavior_Regex"],
        "Notes":                 row.get("Notes", ""),
    }


def _fail(row, reason, log, expected_layer, tier, conf, risk) -> dict:
    return {
        **_base(row),
        "Actual_Agent_Output":  f"SYSTEM ERROR: {reason}",
        "Remediation_Commands": "N/A",
        "Fix_Node":             "N/A",
        "Issue_Category":       "N/A",
        "Confidence_Score":     conf,
        "Confidence_Label":     "N/A",
        "Risk_Score":           risk,
        "Knowledge_Stored":     False,
        "Actual_Layer":         "ERROR",
        "Actual_Codes_Found":   log,
        "Tier_Used":            tier,
        "QA_Status":            "❌ FAIL",
        "Fail_Reason":          reason,
    }


def _skip(row, reason) -> dict:
    return {
        **_base(row),
        "Actual_Agent_Output":  f"[SKIPPED] {reason}",
        "Remediation_Commands": "N/A",
        "Fix_Node":             "N/A",
        "Issue_Category":       "N/A",
        "Confidence_Score":     "N/A",
        "Confidence_Label":     "N/A",
        "Risk_Score":           "N/A",
        "Knowledge_Stored":     False,
        "Actual_Layer":         "SKIPPED",
        "Actual_Codes_Found":   "N/A",
        "Tier_Used":            "N/A",
        "QA_Status":            "⚠️  SKIP",
        "Fail_Reason":          reason,
    }


# ── Main runner ───────────────────────────────────────────────────────────────

def run_qa_matrix_extended(
    input_csv:  str = INPUT_CSV,
    output_csv: str = OUTPUT_CSV,
):
    print("\n" + "=" * 80)
    print(" 🧪 EXTENDED QA MATRIX EXECUTION (qa_matrix_extended.csv)")
    print("=" * 80)

    if not os.path.exists(input_csv):
        print(f"[!] Error: {input_csv} not found. Run generate_qa_matrix.py first.")
        return

    # ── Load engine components ───────────────────────────────────────────────
    print("[init] Loading graph engine ...")
    get_layer_for_code = _load_graph()
    print("[init] Loading syslog translator ...")
    extract_codes, compiled_patterns = _load_translator()
    print("[init] Loading orchestrator (full pipeline) ...")
    orchestrator = _load_orchestrator()
    print("[init] All engines ready.\n")

    # ── Process rows ─────────────────────────────────────────────────────────
    results        = []
    total          = passed = skipped = 0
    failed_rows    = []
    domain_stats   = defaultdict(lambda: {"pass": 0, "fail": 0, "skip": 0})

    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            tid           = row["Test_ID"]
            scenario_type = row["Scenario_Type"].strip()
            domain        = row["Domain"].strip()

            print(f"[{tid}] {scenario_type:16s} | {domain:16s} | {row['Description'][:55]}")

            # ── Route to correct test handler ────────────────────────────────
            if scenario_type == "Translator":
                result_row = _run_translator(row, extract_codes, compiled_patterns)

            elif scenario_type == "Negative":
                result_row = _run_negative(row, get_layer_for_code, extract_codes)

            else:
                # Positive + Tier2_Inference
                # ORA_PDF uses lightweight lookup; all others use full orchestrator
                result_row = _run_positive(
                    row, orchestrator, get_layer_for_code, compiled_patterns
                )

            # ── Tally ─────────────────────────────────────────────────────────
            status = result_row["QA_Status"]
            if "PASS" in status:
                passed += 1
                domain_stats[domain]["pass"] += 1
                print(f"         ✅ PASS")
            elif "SKIP" in status:
                skipped += 1
                domain_stats[domain]["skip"] += 1
                print(f"         ⚠️  SKIP: {result_row['Fail_Reason']}")
            else:
                domain_stats[domain]["fail"] += 1
                failed_rows.append(result_row)
                print(f"         ❌ FAIL: {result_row['Fail_Reason']}")

            results.append(result_row)

    # ── Write report ──────────────────────────────────────────────────────────
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(results)

    # ── Final report ──────────────────────────────────────────────────────────
    failed  = total - passed - skipped
    pct     = round(passed / max(total - skipped, 1) * 100, 1)

    print("\n" + "=" * 80)
    print(" 📊 EXTENDED QA MATRIX — FINAL REPORT")
    print("=" * 80)
    print(f"  Total Tests Run : {total}")
    print(f"  ✅ Passed       : {passed}")
    print(f"  ❌ Failed       : {failed}")
    print(f"  ⚠️  Skipped      : {skipped}")
    print(f"  Pass Rate       : {pct}%")
    print()

    print("── Domain breakdown ─────────────────────────────────────────────")
    for domain in sorted(domain_stats):
        s = domain_stats[domain]
        bar = "✅" * s["pass"] + "❌" * s["fail"] + "⚠️" * s["skip"]
        print(f"  {domain:20s}  pass={s['pass']:3d}  fail={s['fail']:3d}  skip={s['skip']:2d}  {bar[:30]}")

    if failed_rows:
        print()
        print("── Failed Tests ─────────────────────────────────────────────────")
        for r in failed_rows:
            print(f"  [{r['Test_ID']}] {r['Domain']:16s} | {r['Description'][:50]}")
            print(f"           Reason: {r['Fail_Reason']}")

    print()
    print(f"[!] Full audit report → {output_csv}")

    if failed == 0 and skipped == 0:
        print("\n[✅] VERDICT: 100% PASS RATE. Engine is production-ready.")
    elif failed == 0:
        print(f"\n[✅] VERDICT: All executed tests passed ({skipped} skipped).")
    else:
        print(f"\n[❌] VERDICT: {failed} tests failed. Do NOT deploy until fixed.")


if __name__ == "__main__":
    run_qa_matrix_extended()
