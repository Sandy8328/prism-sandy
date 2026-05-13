"""
audit_parser.py — Oracle Standard Audit Log (.aud) Parser.

Manifest-driven extraction of user actions, terminals, and return codes.
Plain-text ACTION:/RETURNCODE: lines are merged when bracket-style fields are absent.
"""

import os
import re
import yaml
from typing import Any, Dict


class OracleAuditParser:
    def __init__(self, config_path: str = None):
        self.manifest: dict = {}
        self.field_patterns: dict[str, re.Pattern] = {}
        if not config_path:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "settings.yaml"
            )
        try:
            with open(config_path, "r") as f:
                full_config = yaml.safe_load(f) or {}
            self.manifest = full_config.get("audit_manifest", {}) or {}
            self.field_patterns = {
                name: re.compile(pat)
                for name, pat in (self.manifest.get("fields") or {}).items()
            }
        except (OSError, yaml.YAMLError, TypeError, re.error):
            self.manifest = {}
            self.field_patterns = {}

    def _merge_plain_audit(self, raw: str, results: Dict[str, Any]) -> None:
        """Fill gaps from unified / simplified audit text (no manifest required)."""
        # RETURNCODE: 0 | RETURNCODE : [4] '1017'
        rc_plain = re.search(
            r"\bRETURNCODE\s*:\s*(?:\[(\d+)\]\s*')?(\d+)(?:')?",
            raw,
            re.I,
        )
        if rc_plain:
            results["returncode"] = (rc_plain.group(2) or rc_plain.group(1) or "").strip()

        act_plain = re.search(r"\bACTION\s*:\s*([^\n\r]+?)(?=\s+RETURNCODE\s*:|$)", raw, re.I)
        if act_plain:
            act = act_plain.group(1).strip().strip("'\"")
            if act:
                results["action"] = results.get("action") or act

        act_u = (results.get("action") or "").upper()
        rc = str(results.get("returncode", "0")).strip() or "0"

        if re.search(r"\bGRANT\s+DBA\b|\bREVOKE\s+DBA\b", raw, re.I) or (
            "GRANT" in act_u and "DBA" in act_u
        ):
            results["event_type"] = "PRIVILEGE_CHANGE"
        elif re.search(
            r"\bACTION\s*:\s*(CREATE|DROP|ALTER)\s+USER\b", raw, re.I
        ) or re.search(r"\b(CREATE|DROP|ALTER)\s+USER\b", act_u):
            results["event_type"] = "PRIVILEGE_CHANGE"
        elif re.search(r"\bORA-01017\b|invalid\s+username/password", raw, re.I):
            results["event_type"] = "AUTH_FAILURE"
            results.setdefault("returncode", "1017")
        elif "LOGON" in act_u and rc not in ("0", ""):
            results["event_type"] = "AUTH_FAILURE"

    def parse_audit_text(self, text: str) -> Dict[str, Any]:
        """Parse an Oracle audit entry or multi-line audit fragment."""
        results: Dict[str, Any] = {}
        raw = text or ""

        for name, pattern in self.field_patterns.items():
            match = pattern.search(raw)
            if match:
                val = match.group(1).strip()
                results[name] = val

        self._merge_plain_audit(raw, results)

        if results:
            results["raw"] = raw.strip()
            rc = str(results.get("returncode", "0")).strip() or "0"
            results["severity"] = "ERROR" if rc != "0" else "INFO"

        return results
