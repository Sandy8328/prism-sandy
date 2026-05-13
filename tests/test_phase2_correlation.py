"""
test_phase2_correlation.py — Validates the Temporal Graph logic from Phase 2.

Tests:
1. Cross-Node RAC Evictions (Exadata mapping dbnode01 <-> cell01).
2. Domino Delay (Detecting an OS disk drop 4 hours before the DB crash).
3. Coincidental Outage Rule (Preventing physical infrastructure link to logical ORA-00942).
"""

import sys
import os
from datetime import datetime
import duckdb
import unittest.mock as mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.retrieval.temporal_correlator import find_correlated_chunks

def setup_in_memory_db():
    conn = duckdb.connect(':memory:')
    conn.execute("""
        CREATE TABLE chunks (
            chunk_id VARCHAR,
            hostname VARCHAR,
            log_source VARCHAR,
            timestamp_start VARCHAR,
            category VARCHAR,
            severity VARCHAR,
            ora_code VARCHAR,
            os_pattern VARCHAR,
            raw_text VARCHAR
        )
    """)
    return conn

def run_test_1():
    print("\n[TEST 1] Edge Cases 1 & 2: Cross-Node RAC & Exadata Corroboration")
    conn = setup_in_memory_db()
    conn.execute("INSERT INTO chunks VALUES ('CHUNK-CELL-01', 'cell01', 'VAR_LOG_MESSAGES', '2024-04-21T10:00:00', 'OS', 'CRITICAL', '', 'SCSI_TIMEOUT', 'Disk failed')")
    
    with mock.patch('src.retrieval.temporal_correlator.duckdb.connect', return_value=conn):
        ref_chunk_1 = {"chunk_id": "REF-1", "hostname": "dbnode01", "log_source": "ALERT_LOG", "timestamp_start": "2024-04-21T10:00:15", "ora_code": "ORA-27072"}
        res_1 = find_correlated_chunks([ref_chunk_1])
        if res_1.get("REF-1") and any(c["chunk_id"] == "CHUNK-CELL-01" for c in res_1["REF-1"]):
            print("  ✅ SUCCESS: Successfully correlated 'dbnode01' Oracle error with 'cell01' OS crash.")
        else:
            print("  ❌ FAILED: Did not correlate across cluster topology.")

def run_test_2():
    print("\n[TEST 2] Edge Case 10: Domino Delay (4 Hour lookback)")
    conn = setup_in_memory_db()
    conn.execute("INSERT INTO chunks VALUES ('CHUNK-DOMINO-01', 'dbnode02', 'VAR_LOG_MESSAGES', '2024-04-21T06:00:00', 'DISK', 'CRITICAL', '', 'EXT4-fs error', 'Read-only file system')")
    
    with mock.patch('src.retrieval.temporal_correlator.duckdb.connect', return_value=conn):
        ref_chunk_2 = {"chunk_id": "REF-2", "hostname": "dbnode02", "log_source": "ALERT_LOG", "timestamp_start": "2024-04-21T10:00:00", "ora_code": "ORA-01578"}
        res_2 = find_correlated_chunks([ref_chunk_2])
        if res_2.get("REF-2") and any(c["chunk_id"] == "CHUNK-DOMINO-01" for c in res_2["REF-2"]):
            print("  ✅ SUCCESS: Found stateful disk drop 4 hours prior, overriding strict 60s window.")
        else:
            print(f"  ❌ FAILED: Missed the domino delay. Results: {res_2}")

def run_test_3():
    print("\n[TEST 3] Edge Case 30: Independent Layer Rule (Logical vs Physical)")
    conn = setup_in_memory_db()
    conn.execute("INSERT INTO chunks VALUES ('CHUNK-COINCIDENCE-01', 'stg-db-01', 'VAR_LOG_MESSAGES', '2024-04-21T12:00:00', 'DISK', 'CRITICAL', '', 'SAN_DROPPED', 'SAN disconnected')")
    
    with mock.patch('src.retrieval.temporal_correlator.duckdb.connect', return_value=conn):
        ref_chunk_3 = {"chunk_id": "REF-3", "hostname": "stg-db-01", "log_source": "ALERT_LOG", "timestamp_start": "2024-04-21T12:00:10", "ora_code": "ORA-00942"}
        res_3 = find_correlated_chunks([ref_chunk_3])
        if not res_3.get("REF-3"):
            print("  ✅ SUCCESS: Correctly ignored physical SAN crash because ORA-00942 is a purely logical error.")
        else:
            print("  ❌ FAILED: Incorrectly linked logical ORA-00942 to physical SAN crash.")

def run_tests():
    print("\n==================================================")
    print(" 🧪 RUNNING PHASE 2 VALIDATION TESTS")
    print("==================================================")
    run_test_1()
    run_test_2()
    run_test_3()
    print("\nDone.")

if __name__ == "__main__":
    run_tests()
