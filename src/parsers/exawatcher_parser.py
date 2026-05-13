"""
exawatcher_parser.py — Parses ExaWatcher metric snapshots for InfiniBand and RoCE health.
"""

import re
from typing import List, Dict, Any

class ExaWatcherParser:
    def __init__(self):
        # Header for IB metrics
        self.ib_header = re.compile(r"Port\s+SymbolError\s+LinkRecov\s+LinkDown", re.I)
        # Port metrics: ib0 0 0 0 ...
        self.ib_row = re.compile(r"^(?P<port>ib\d+)\s+(?P<errors>\d+)\s+(?P<recov>\d+)\s+(?P<down>\d+)")

    def parse_exawatcher_text(self, text: str, hostname: str = "unknown") -> List[Dict[str, Any]]:
        """
        Parse ExaWatcher metric output (simplified for pattern matching).
        """
        results = []
        lines = text.splitlines()
        
        for line in lines:
            # Look for InfiniBand link down events
            ib_match = self.ib_row.match(line.strip())
            if ib_match:
                errors = int(ib_match.group("errors"))
                down = int(ib_match.group("down"))
                
                if errors > 0 or down > 0:
                    results.append({
                        "hostname": hostname,
                        "component": "INFINIBAND",
                        "port": ib_match.group("port"),
                        "errors": errors,
                        "link_down_count": down,
                        "severity": "CRITICAL" if down > 0 else "WARNING",
                        "message": f"InfiniBand port {ib_match.group('port')} has {errors} symbol errors and {down} link down events",
                        "raw": line.strip()
                    })
        return results
