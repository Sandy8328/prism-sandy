"""
packager.py — Generic ADR Incident Evidence Packager.

Bundles trace files, audit logs, and diagnostic metadata into a single ZIP/TARGZ.
"""

import os
import json
import shutil
import yaml
import zipfile
import tarfile
from datetime import datetime
from typing import List, Dict, Any, Optional

class IncidentPackager:
    def __init__(self, config_path: str = None):
        if not config_path:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "settings.yaml"
            )
        
        with open(config_path, "r") as f:
            full_config = yaml.safe_load(f)
            self.manifest = full_config.get("packaging_manifest", {})
            
        self.base_dir = self.manifest.get("incident_base_dir", "./incidents")
        self.format = self.manifest.get("compression_format", "zip")
        self.meta_name = self.manifest.get("metadata_filename", "findings.json")

    def create_package(self, report_data: Dict[str, Any], trace_files: List[str] = None, html_content: str = None) -> Optional[str]:
        """
        Creates a diagnostic bundle for the current incident.
        """
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

        # 1. Create a unique incident folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ora_code = report_data.get("ora_code", {}).get("code", "UNKNOWN")
        incident_id = f"incident_{ora_code}_{timestamp}"
        temp_dir = os.path.join(self.base_dir, incident_id)
        os.makedirs(temp_dir)
        print(f"  [PACKAGER] Step 1: Created temporary staging area: {temp_dir}")

        try:
            # 2. Add metadata (Findings JSON)
            meta_path = os.path.join(temp_dir, self.meta_name)
            with open(meta_path, "w") as f:
                json.dump(report_data, f, indent=2)
            print(f"  [PACKAGER] Step 2: Exported findings metadata to {self.meta_name}")

            # 2b. Add HTML Report (Phase F)
            if html_content:
                html_path = os.path.join(temp_dir, "incident_report.html")
                with open(html_path, "w") as f:
                    f.write(html_content)
                print(f"  [PACKAGER] Step 2b: Included standalone HTML report")

            # 3. Add Trace Files (if configured and present)
            if self.manifest.get("include_trace_files") and trace_files:
                trace_dir = os.path.join(temp_dir, "trace")
                os.makedirs(trace_dir)
                print(f"  [PACKAGER] Step 3: Harvesting trace files...")
                for tf in trace_files:
                    if os.path.exists(tf):
                        shutil.copy2(tf, trace_dir)
                        print(f"            + Copied: {os.path.basename(tf)}")
                    else:
                        print(f"            - SKIP: {tf} (File not found on disk)")

            # 4. Compress
            print(f"  [PACKAGER] Step 4: Compressing package using {self.format}...")
            archive_name = os.path.join(self.base_dir, incident_id)
            if self.format == "zip":
                shutil.make_archive(archive_name, 'zip', temp_dir)
                final_path = archive_name + ".zip"
            else:
                shutil.make_archive(archive_name, 'gztar', temp_dir)
                final_path = archive_name + ".tar.gz"

            print(f"  [PACKAGER] Created incident package: {final_path}")
            return final_path

        finally:
            # Cleanup temp directory
            shutil.rmtree(temp_dir)

    def get_package_info(self, file_path: str) -> Dict[str, Any]:
        """Returns size and basic info about the package."""
        if not os.path.exists(file_path):
            return {}
        
        size_bytes = os.path.getsize(file_path)
        return {
            "path": file_path,
            "filename": os.path.basename(file_path),
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "created_at": datetime.now().isoformat()
        }
