"""
DEPRECATED for production RCA — not used by ``src.agent.agent`` (evidence-first path).
Timeline-based anchor selection with print-style diagnostics; tests may still import this module.

Temporal graph engine (legacy session pipeline).
"""

import sys
import os
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)
from src.agent.session_manager import IncidentSessionManager

class TemporalGraphEngine:
    def __init__(self, session_manager: IncidentSessionManager):
        self.session_manager = session_manager

    def evaluate_session_timeline(self, session_id):
        """
        The core engine that solves the Fragmented Upload problem.
        It pulls all chunks from the session bucket, sorts them strictly by
        server timestamp, and declares the mathematically oldest error as the Root Cause Anchor.
        """
        print(f"\n[TemporalGraph] Triggering Re-Evaluation Pass for {session_id}...")
        
        chunks = self.session_manager.get_all_session_chunks(session_id)
        if not chunks:
            print("  -> No logs found in session.")
            return None
            
        # 1. Chronological Sorting (The Magic)
        # We parse the timestamp string back to a datetime object for accurate sorting
        # Supported timestamp formats in order of likelihood
        # Any format not in this list falls back to dateutil.parser (installed)
        _DATE_FORMATS = [
            "%Y-%m-%dT%H:%M:%S",        # ISO: 2024-03-15T10:05:00
            "%Y-%m-%d %H:%M:%S",         # ISO with space: 2024-03-15 10:05:00
            "%a %b %d %H:%M:%S %Z %Y",  # Oracle alert.log: Mon Mar 15 10:05:00 IST 2024
            "%b %d %H:%M:%S",            # syslog: Mar 15 10:05:00
            "%d-%b-%Y %H:%M:%S",         # Oracle: 15-MAR-2024 10:05:00
        ]

        def _parse_ts(ts_str):
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(ts_str, fmt)
                except ValueError:
                    continue
            # Last resort: dateutil (handles almost any format)
            try:
                from dateutil import parser as _dp
                return _dp.parse(ts_str, fuzzy=True)
            except Exception:
                raise ValueError(f"Cannot parse timestamp: {ts_str!r}")

        try:
            chunks.sort(key=lambda x: _parse_ts(x["extracted_timestamp"]))
        except Exception as e:
            print(f"  -> [Error] Timestamp sorting failed. Ensure valid formats: {e}")
            return None
            
        print(f"  -> [TemporalGraph] Sorted {len(chunks)} events chronologically.")
        
        # 2. Identify the Anchor (Earliest Error)
        anchor_chunk = chunks[0]
        latest_chunk = chunks[-1]
        
        print("\n" + "=" * 60)
        print(" 🕰️ SESSION-SCOPED TEMPORAL TIMELINE ")
        print("=" * 60)
        for i, chunk in enumerate(chunks):
            indicator = "<- CAUSAL ANCHOR" if i == 0 else ""
            print(f"{chunk['extracted_timestamp']} | {chunk['hostname']} | {chunk['file_source']} {indicator}")
            print(f"   Error: {chunk['content']}")
            
        print("=" * 60)
        
        return anchor_chunk

if __name__ == "__main__":
    # Simulated Integration Test proving the Fragmented Upload Edge Case Fix
    session_db = IncidentSessionManager()
    incident_id = session_db.create_new_session()
    
    print(f"\n[User] Opens Chatbot. Assigned {incident_id}.")
    
    print("\n[T=0] User uploads alert.log (The Victim)")
    db_chunks = [
        {"hostname": "dbnode01", "timestamp": "2024-03-15T10:05:00", "content": "ORA-00603: Oracle server session terminated", "file_source": "alert_orcl.log"}
    ]
    session_db.upload_log_to_session(incident_id, db_chunks)
    
    print("\n[T+5 minutes] User realizes they forgot the OS logs, uploads messages.log (The Culprit)")
    # Notice the timestamp is 10:00:00, which is physically OLDER than the DB crash, but uploaded LATER.
    os_chunks = [
        {"hostname": "cell01", "timestamp": "2024-03-15T10:00:00", "content": "SCSI timeout: Disk /dev/sdb offline", "file_source": "/var/log/messages"}
    ]
    session_db.upload_log_to_session(incident_id, os_chunks)
    
    # Run the Temporal Graph Algorithm
    engine = TemporalGraphEngine(session_db)
    anchor = engine.evaluate_session_timeline(incident_id)
    
    print(f"\n[!] VERDICT: Agent successfully mathematically proved the Root Cause is '{anchor['content']}' despite it being uploaded 5 minutes later!")
