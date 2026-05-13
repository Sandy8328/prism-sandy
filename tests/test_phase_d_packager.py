import unittest
import os
import sys
import json
import zipfile
import shutil

# Ensure project root is in sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.agent.packager import IncidentPackager

class TestIncidentPackager(unittest.TestCase):
    def setUp(self):
        self.config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
        self.packager = IncidentPackager(config_path=self.config_path)
        # Create a dummy trace file
        self.dummy_trace = "/tmp/dummy_test_ora_123.trc"
        with open(self.dummy_trace, "w") as f:
            f.write("Dummy trace content for testing")

    def tearDown(self):
        if os.path.exists(self.dummy_trace):
            os.remove(self.dummy_trace)
        # Cleanup incidents dir if it was created during test
        if os.path.exists("./incidents"):
            pass # We can keep it or clean it up

    def test_package_creation(self):
        print("\n" + "="*60)
        print("  DEMONSTRATION: Automated Incident Packaging Flow")
        print("="*60)
        
        report_data = {
            "status": "SUCCESS",
            "ora_code": {"code": "ORA-00600"},
            "root_cause": {"pattern": "MEMORY_CORRUPTION"},
            "summary": "Sample findings for incident packaging test."
        }
        
        # We need a real file to copy for Step 3 to succeed in logs
        dummy_trace_path = self.dummy_trace
        
        print("\n[START] Triggering Incident Packager...")
        pkg_path = self.packager.create_package(report_data, trace_files=[dummy_trace_path])
        
        self.assertIsNotNone(pkg_path)
        self.assertTrue(os.path.exists(pkg_path))
        
        info = self.packager.get_package_info(pkg_path)
        print(f"\n[COMPLETE] Package Ready: {info['filename']} ({info['size_mb']} MB)")
        print(f"           Path: {info['path']}")

        # Verify ZIP internal structure
        with zipfile.ZipFile(pkg_path, 'r') as z:
            names = z.namelist()
            print(f"\n[VERIFY] Internal ZIP Manifest:")
            for name in names:
                print(f"  - {name}")
            
            self.assertTrue(any("findings.json" in n for n in names))
            self.assertTrue(any("dummy_test_ora_123.trc" in n for n in names))

        print("="*60 + "\n")
        
        # Cleanup
        if os.path.exists(pkg_path):
            os.remove(pkg_path)

if __name__ == "__main__":
    unittest.main()
