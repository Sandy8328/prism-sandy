import unittest
import os
import sys
from datetime import datetime, timedelta

# Ensure project root is in sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.parsers.security_parser import SecurityParser
from src.parsers.audit_parser import OracleAuditParser
from src.chunker.event_chunker import correlate_security_to_db

class TestSecurityCorrelation(unittest.TestCase):
    def test_security_parsing(self):
        parser = SecurityParser()
        line = "May  7 10:00:00 dbnode01 sshd[1234]: Failed password for root from 192.168.1.50 port 54321 ssh2"
        parsed = parser.parse_line(line)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["event_type"], "ssh_failed")
        self.assertEqual(parsed["severity"], "WARNING")
        self.assertIn("root", parsed["details"])
        self.assertIn("192.168.1.50", parsed["details"])

    def test_audit_parsing(self):
        parser = OracleAuditParser()
        text = """
ACTION : [7] 'CONNECT'
USERID : [3] 'SYS'
TERMINAL : [11] 'pts/0'
RETURNCODE : [4] '1017'
"""
        results = parser.parse_audit_text(text)
        self.assertEqual(results.get("action"), "CONNECT")
        self.assertEqual(results.get("returncode"), "1017")
        self.assertEqual(results.get("severity"), "ERROR")

    def test_temporal_correlation(self):
        # Create a DB chunk and a Security chunk with same timestamp
        ts = datetime(2024, 5, 7, 10, 0, 0)
        
        db_chunk = {
            "chunk_id": "db_1",
            "hostname": "dbnode01",
            "timestamp_start": ts.isoformat(),
            "linked_chunks": []
        }
        
        sec_chunk = {
            "chunk_id": "sec_1",
            "hostname": "dbnode01",
            "timestamp_start": (ts + timedelta(seconds=10)).isoformat(),
            "linked_chunks": []
        }
        
        # Correlate
        correlate_security_to_db([db_chunk], [sec_chunk], window_sec=60)
        
        self.assertIn("sec_1", db_chunk["linked_chunks"])
        self.assertIn("db_1", sec_chunk["linked_chunks"])

    def test_brute_force_demo(self):
        print("\n" + "="*60)
        print("  DEMONSTRATION: Security Correlation (Brute Force)")
        print("="*60)
        
        ts = datetime(2024, 5, 7, 10, 0, 0)
        
        print("\nStep 1: Ingesting Database Error (ORA-03136)...")
        db_chunk = {
            "chunk_id": "db_ora_03136",
            "hostname": "dbnode01",
            "timestamp_start": ts.isoformat(),
            "linked_chunks": [],
            "raw_text": "ORA-03136: inbound connection timeout"
        }
        
        print("\nStep 2: Ingesting Security Logs (/var/log/secure)...")
        sec_logs = [
            {"timestamp": ts - timedelta(seconds=10), "raw": "sshd[123]: Failed password for root from 1.2.3.4 port 12345 ssh2", "timestamp_str": "10:00:00"},
            {"timestamp": ts - timedelta(seconds=5),  "raw": "sshd[123]: Failed password for root from 1.2.3.4 port 12346 ssh2", "timestamp_str": "10:00:05"},
            {"timestamp": ts + timedelta(seconds=2),  "raw": "sshd[123]: Failed password for root from 1.2.3.4 port 12347 ssh2", "timestamp_str": "10:00:12"},
        ]
        from src.chunker.event_chunker import chunk_security_log
        sec_chunks = chunk_security_log(sec_logs, "dbnode01", "LINUX", "demo_coll")
        
        print("\nStep 3: Running Temporal Correlation...")
        correlate_security_to_db([db_chunk], sec_chunks, window_sec=60)
        
        print(f"\nFinal Result: DB Chunk '{db_chunk['chunk_id']}' now has {len(db_chunk['linked_chunks'])} linked security events.")
        print("="*60 + "\n")

if __name__ == "__main__":
    unittest.main()
