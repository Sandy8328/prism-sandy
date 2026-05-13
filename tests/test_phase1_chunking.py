"""
test_phase1_chunking.py — Validates the fixes implemented in Phase 1.

Run this script to prove that:
1. Java stack traces > 50 lines are NOT split (Edge Case 9).
2. Massive PL/SQL dumps are truncated (Edge Case 29).
3. Rotated log files are stitched (Edge Case 5).
4. >3 Device failures are merged into a SYSTEM_BUS_RESET (Edge Case 6).
"""

import sys
import os
from datetime import datetime

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.parsers.alert_log_parser import parse_alert_log_text
from src.chunker.event_chunker import chunk_alert_log
from src.pipeline.log_ingester import _merge_shared_bus_failures, group_rotated_files

def test_edge_case_29_massive_sql():
    print("\n[TEST 1] Edge Case 29: Massive PL/SQL Dump Truncation")
    # Simulate an alert.log with a massive 100-line SQL dump
    alert_text = "Tue Apr 21 03:14:18 2024\n"
    alert_text += "Current SQL statement for this session:\n"
    for i in range(100):
        alert_text += f"SELECT * FROM table_{i} WHERE something = 'value';\n"
    alert_text += "ORA-00603: ORACLE server session terminated by fatal error\n"
    
    entries = parse_alert_log_text(alert_text)
    lines = entries[0]["lines"]
    
    # It should have 5 lines of SQL, 1 truncation message, the ORA code, and the timestamp.
    # Total lines should be strictly less than 15.
    if len(lines) < 15 and "... [MASSIVE SQL BLOCK TRUNCATED BY AGENT] ..." in "\n".join(lines):
        print(f"  ✅ SUCCESS: 100-line SQL dump was safely truncated to {len(lines)} lines.")
    else:
        print(f"  ❌ FAILED: SQL dump was not truncated properly. Line count: {len(lines)}")

def test_edge_case_9_atomic_stack_trace():
    print("\n[TEST 2] Edge Case 9: Atomic Blocks for Stack Traces")
    # Simulate an alert.log with a 70-line Java stack trace
    alert_text = "Tue Apr 21 04:00:00 2024\n"
    alert_text += "ORA-29532: Java call terminated by uncaught Java exception:\n"
    alert_text += "Exception in thread \"main\" java.lang.OutOfMemoryError: Java heap space\n"
    for i in range(70):
        alert_text += f"        at com.oracle.example.BadCode.method{i}(BadCode.java:123)\n"
    
    entries = parse_alert_log_text(alert_text)
    chunks = chunk_alert_log(entries, "db01", "LINUX", "TEST")
    
    # Even though the limit is 50 lines, because it's a stack trace, it should NOT be split.
    if len(chunks) == 1:
        print(f"  ✅ SUCCESS: 70-line stack trace remained in exactly 1 chunk (Size: {chunks[0]['line_count']} lines).")
    else:
        print(f"  ❌ FAILED: Stack trace was incorrectly split into {len(chunks)} chunks.")

def test_edge_case_5_rotated_files():
    print("\n[TEST 3] Edge Case 5: Log File Rotation Grouping")
    # Simulate physical file paths
    files = [
        "/var/log/messages",
        "/var/log/messages.1",
        "/var/log/messages-20240421.gz",
        "/u01/app/oracle/diag/alert_orcl.log",
        "/u01/app/oracle/diag/alert_orcl.log.1"
    ]
    groups = group_rotated_files(files)
    
    if len(groups["messages"]) == 3 and len(groups["alert_orcl"]) == 2:
        print(f"  ✅ SUCCESS: Correctly grouped 5 physical files into 2 logical streams (messages, alert).")
    else:
        print(f"  ❌ FAILED: Grouping logic failed. Output: {groups}")

def test_edge_case_6_shared_bus():
    print("\n[TEST 4] Edge Case 6: Shared Bus Failures (Super Chunking)")
    # Simulate 4 different devices failing at the exact same second
    ts = "2024-04-21T10:00:00"
    simulated_chunks = [
        {"chunk_id": "111", "timestamp_start": ts, "category": "OS", "device": "sdb", "raw_text": "sdb failed"},
        {"chunk_id": "222", "timestamp_start": ts, "category": "OS", "device": "sdc", "raw_text": "sdc failed"},
        {"chunk_id": "333", "timestamp_start": ts, "category": "OS", "device": "sdd", "raw_text": "sdd failed"},
        {"chunk_id": "444", "timestamp_start": ts, "category": "OS", "device": "eth0", "raw_text": "eth0 down"}
    ]
    
    merged = _merge_shared_bus_failures(simulated_chunks)
    
    if len(merged) == 1 and merged[0]["os_pattern"] == "SYSTEM_BUS_RESET":
        print(f"  ✅ SUCCESS: 4 independent device failures were merged into a single SYSTEM_BUS_RESET super-chunk.")
    else:
        print(f"  ❌ FAILED: Chunks were not merged properly. Result size: {len(merged)}")

if __name__ == "__main__":
    print("==================================================")
    print(" 🧪 RUNNING PHASE 1 VALIDATION TESTS")
    print("==================================================")
    test_edge_case_29_massive_sql()
    test_edge_case_9_atomic_stack_trace()
    test_edge_case_5_rotated_files()
    test_edge_case_6_shared_bus()
    print("\nDone.")
