import unittest
import os
import sys
import shutil
import json

# Ensure project root is in sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.agent.report_builder import generate_html_report
from src.agent.packager import IncidentPackager

class TestHTMLReport(unittest.TestCase):
    def setUp(self):
        self.report_data = {
            "hostname": "test-host",
            "collection_id": "test_coll_123",
            "summary": "ORA-04031: Shared Pool Memory Error",
            "rca": "Shared pool exhaustion due to SQL literal overuse.",
            "risk_score": "CRITICAL",
            "confidence": 95,
            "query_mode": "ora_code",
            "hardware_health": [
                {"event": "EXA_CELL_STOP", "text": "Cell Server stopped", "source": "CELL_LOG", "time": "10:00:00"}
            ],
            "trace_analysis": {
                "call_stack": ["kgh_alloc", "kghfnd"],
                "error_stack": ["ORA-04031"]
            },
            "recommendations": ["Increase shared_pool_size", "Use bind variables"]
        }

    def test_html_generation(self):
        html = generate_html_report(self.report_data)
        self.assertIsNotNone(html)
        self.assertIn("ORA-04031", html)
        self.assertIn("Exadata Hardware Health", html)
        self.assertIn("kgh_alloc", html)
        print("  [VERIFY] HTML Report rendered successfully and contains key tokens.")

    def test_packager_with_html(self):
        packager = IncidentPackager()
        html_content = "<html><body>Test Report</body></html>"
        
        # Mocking trace file
        dummy_trace = "dummy_f.trc"
        with open(dummy_trace, "w") as f: f.write("dummy")
        
        pkg_path = packager.create_package(self.report_data, trace_files=[dummy_trace], html_content=html_content)
        
        self.assertIsNotNone(pkg_path)
        self.assertTrue(os.path.exists(pkg_path))
        print(f"  [VERIFY] Incident Package created with HTML: {pkg_path}")
        
        # Cleanup
        if os.path.exists(pkg_path): os.remove(pkg_path)
        if os.path.exists(dummy_trace): os.remove(dummy_trace)
        if os.path.exists("./incidents"): shutil.rmtree("./incidents")

if __name__ == "__main__":
    unittest.main()
