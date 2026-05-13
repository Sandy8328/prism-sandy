import unittest
import os
import sys
import yaml

# Ensure project root is in sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.parsers.trace_parser import TraceParser

class TestTraceParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use the actual settings.yaml for testing manifest compliance
        # Fix: Ensure we find the config relative to this test file
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
        cls.parser = TraceParser(config_path=config_path)

    def test_header_extraction(self):
        sample_trace = """
*** 2024-05-07T10:00:00.123456+05:30
ORACLE V19.0.0.0.0 - Production
DB Name: ORCL
Instance name: orcl1
Process name: PMON
Process ID: 12345
Session ID: 99
Serial #: 1
"""
        results = self.parser.parse_trace_text(sample_trace)
        meta = results["metadata"]
        
        self.assertEqual(meta.get("db_name"), "ORCL")
        self.assertEqual(meta.get("instance_name"), "orcl1")
        self.assertEqual(meta.get("pname"), "PMON")
        self.assertEqual(meta.get("pid"), "12345")
        self.assertEqual(meta.get("sid"), "99")

    def test_section_extraction(self):
        sample_trace = """
Dump file /u01/app/oracle/diag/rdbms/orcl/orcl1/trace/orcl1_ora_123.trc
----- Call Stack -----
ksedmp <- kcfis_read <- kcrf_read_file
0x123456
0x789012
----------------------
Some other text
----- Error Stack -----
ORA-00600: internal error code, arguments: [kxsf_read_1], [123]
-----------------------
"""
        results = self.parser.parse_trace_text(sample_trace)
        sections = results["sections"]
        
        self.assertIn("ksedmp <- kcfis_read", sections.get("call_stack", ""))
        self.assertIn("ORA-00600", sections.get("error_stack", ""))
        self.assertNotIn("Some other text", sections.get("call_stack", ""))

    def test_stack_highlights(self):
        stack_text = "ksedmp <- kcfis_read <- kcrf_read_file\nmain <- libc_start"
        highlights = self.parser.analyze_call_stack(stack_text)
        
        # Manifest has 'kcf' and 'ksedmp' as highlights
        self.assertEqual(len(highlights), 1)
        self.assertIn("kcfis_read", highlights[0])

    def test_full_extraction_flow(self):
        print("\n" + "="*60)
        print("  DEMONSTRATION: Full Generic Trace Extraction Flow")
        print("="*60)
        
        sample_trace = """
*** 2024-05-07T10:00:00.123
DB Name: ORCL_PROD
Process ID: 9999
Process name: LGWR
----- Call Stack -----
ksedmp <- kcfis_read
0xDEADBEEF
----------------------
"""
        from src.chunker.event_chunker import chunk_trace_file
        
        print("\nStep 1: Parsing Trace File...")
        # The prints inside TraceParser will trigger here
        results = self.parser.parse_trace_text(sample_trace)
        
        print("\nStep 2: Generating Linked Chunks...")
        # The prints inside chunk_trace_file will trigger here
        chunks = chunk_trace_file(
            file_content=sample_trace,
            parent_chunk_id="parent_alert_123",
            hostname="dbnode01",
            platform="LINUX",
            collection_id="test_run"
        )
        
        print(f"\nFinal Result: Created {len(chunks)} linked chunks.")
        print("="*60 + "\n")

if __name__ == "__main__":
    unittest.main()
