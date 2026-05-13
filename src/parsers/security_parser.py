"""
security_parser.py — Generic OS Security Log Parser (/var/log/secure).

Manifest-driven detection of:
- SSH Brute Force (failures)
- Accepted Logins
- Sudo Execution
"""

import re
import os
import yaml
from datetime import datetime
from typing import List, Dict, Any

class SecurityParser:
    def __init__(self, config_path: str = None):
        self.manifest: dict = {}
        self.patterns: dict[str, re.Pattern] = {}
        self.threat_levels: dict = {}
        if not config_path:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "settings.yaml"
            )
        try:
            with open(config_path, "r") as f:
                full_config = yaml.safe_load(f) or {}
            self.manifest = full_config.get("security_manifest", {}) or {}
            self.patterns = {
                name: re.compile(pat)
                for name, pat in (self.manifest.get("syslog_patterns") or {}).items()
            }
            self.threat_levels = self.manifest.get("threat_levels", {}) or {}
        except (OSError, yaml.YAMLError, TypeError, re.error):
            self.manifest = {}
            self.patterns = {}
            self.threat_levels = {}

    def parse_line(self, line: str) -> Dict[str, Any]:
        """
        Identify security events in a single syslog line.
        """
        for name, pattern in self.patterns.items():
            match = pattern.search(line)
            if match:
                groups = match.group(0)
                return {
                    "event_type": name,
                    "severity":   self.threat_levels.get(name, "INFO"),
                    "details":    groups,
                    "raw":        line.strip()
                }
        # Built-in fallback when manifest/config patterns are absent.
        s = line.strip()
        sl = s.lower()
        if re.search(r"\bORA-01017\b|invalid username/password", s, re.I):
            return {"event_type": "AUTH_FAILURE", "severity": "ERROR", "details": s, "raw": s}
        # Manifest ssh_failed often requires "port … ssh2"; accept common syslog variants.
        if re.search(
            r"failed\s+password|authentication\s+failure|invalid\s+user",
            sl,
            re.I,
        ):
            return {"event_type": "AUTH_FAILURE", "severity": "WARNING", "details": s, "raw": s}
        if "sudo" in sl and ("fail" in sl or "incorrect password" in sl):
            return {"event_type": "AUTH_FAILURE", "severity": "WARNING", "details": s, "raw": s}
        if "sudo" in sl or re.search(r"\bGRANT\s+DBA\b", s, re.I):
            return {"event_type": "PRIVILEGE_CHANGE", "severity": "WARNING", "details": s, "raw": s}
        return None

    def parse_batch(self, lines: List[str]) -> List[Dict[str, Any]]:
        results = []
        for line in lines:
            parsed = self.parse_line(line)
            if parsed:
                results.append(parsed)
        return results
