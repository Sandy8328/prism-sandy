import unittest
import os
import sys
from datetime import datetime

# Ensure project root is in sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.parsers.cell_log_parser import CellLogParser
from src.parsers.exawatcher_parser import ExaWatcherParser
from src.chunker.event_chunker import chunk_cell_logs

class TestExadataDiagnostics(unittest.TestCase):
    def test_cell_log_parsing(self):
        parser = CellLogParser()
        log_text = "2024-05-07T10:00:00 -07:00 CELLSRV: Cell Server stopped unexpectedly\n"
        entries = parser.parse_cell_log_text(log_text, cell_name="cell01")
        
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["cell_name"], "cell01")
        self.assertIn("stopped unexpectedly", entries[0]["message"])
        print(f"  [VERIFY] Cell Log Parsed: {entries[0]['timestamp_str']} -> {entries[0]['message']}")

    def test_exawatcher_parsing(self):
        parser = ExaWatcherParser()
        # Mocking ib row from ExaWatcher
        text = "ib0 50 0 1" # port errors down
        results = parser.parse_exawatcher_text(text, hostname="dbnode01")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["port"], "ib0")
        self.assertEqual(results[0]["severity"], "CRITICAL")
        self.assertIn("link down", results[0]["message"])
        print(f"  [VERIFY] ExaWatcher Parsed: {results[0]['port']} -> {results[0]['message']}")

    def test_cell_chunking(self):
        entries = [{"timestamp": datetime.now(), "timestamp_str": "10:00:00", "raw": "Cell Server stopped"}]
        chunks = chunk_cell_logs(entries, "cell01", "LINUX", "coll_123")
        
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["category"], "HARDWARE")
        self.assertEqual(chunks[0]["log_source"], "CELL_ALERT_LOG")
        print(f"  [VERIFY] Cell Chunk Created: ID {chunks[0]['chunk_id']} Category: {chunks[0]['category']}")

if __name__ == "__main__":
    unittest.main()
