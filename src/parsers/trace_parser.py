"""
trace_parser.py — Generic, Manifest-Driven Oracle Trace File Parser.

Following the PRISM hardening mandate:
- 0% Hardcoded logic.
- 100% Manifest-driven extraction.
- State-machine architecture for section extraction.
"""

import re
import os
import yaml
from typing import Dict, Any, List, Optional

class TraceParser:
    def __init__(self, config_path: Optional[str] = None):
        if not config_path:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "settings.yaml"
            )

        self.manifest: dict = {}
        try:
            with open(config_path, "r") as f:
                full_config = yaml.safe_load(f) or {}
            self.manifest = full_config.get("trace_parsing_manifest") or {}
        except (OSError, yaml.YAMLError, TypeError):
            self.manifest = {}

        # Pre-compile header patterns from manifest
        self.header_patterns = {
            field: re.compile(pattern)
            for field, pattern in (self.manifest.get("header_patterns") or {}).items()
        }

        # Pre-compile section markers
        self.sections_config = self.manifest.get("sections") or {}
        self.section_starters = {
            name: re.compile(re.escape(cfg["start_marker"]))
            for name, cfg in self.sections_config.items()
        }
        self.section_enders = {
            name: re.compile(re.escape(cfg["end_marker"]))
            for name, cfg in self.sections_config.items()
        }

    def parse_trace_text(self, text: str) -> Dict[str, Any]:
        """
        Parses trace file content using the manifest rules.
        """
        lines = text.splitlines()
        results = {
            "metadata": {},
            "sections": {name: [] for name in self.sections_config.keys()}
        }

        current_section = None
        
        for line in lines:
            line_stripped = line.strip()

            # 1. Check for header metadata (if not currently inside a multi-line section)
            if not current_section:
                for field, pattern in self.header_patterns.items():
                    match = pattern.search(line)
                    if match:
                        val = match.group(1) if match.groups() else match.group(0)
                        val = val.strip()
                        results["metadata"][field] = val

            # 2. Check for section transitions
            if not current_section:
                # Look for section starters
                for name, starter in self.section_starters.items():
                    if starter.search(line):
                        current_section = name
                        break
            else:
                # We are inside a section — check for ender
                ender = self.section_enders[current_section]
                if ender.search(line):
                    current_section = None
                    continue

                # Collect section content
                cfg = self.sections_config[current_section]
                if len(results["sections"][current_section]) < cfg.get("max_lines", 100):
                    results["sections"][current_section].append(line)

        # Post-process: Join lines
        for name in results["sections"]:
            results["sections"][name] = "\n".join(results["sections"][name])

        return results

    def analyze_call_stack(self, call_stack_text: str) -> List[str]:
        """
        Generic frame highlighting based on manifest stack_highlights.
        """
        highlights = self.manifest.get("stack_highlights", [])
        highlighted_frames = []
        
        for line in call_stack_text.splitlines():
            # If any highlight keyword is in the line, it's significant
            if any(h.lower() in line.lower() for h in highlights):
                highlighted_frames.append(line.strip())
                
        return highlighted_frames


def parse_trace_text_safe(text: str) -> Dict[str, Any]:
    """Parse trace without raising if manifest is missing or malformed."""
    try:
        return TraceParser().parse_trace_text(text)
    except Exception:
        return {
            "metadata": {},
            "sections": {},
            "parse_warning": "trace_parse_failed",
        }
