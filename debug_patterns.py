
import os
import sys
# Add src to path
sys.path.append(os.getcwd())

from src.knowledge_graph.pattern_matcher import match_patterns
from src.agent.input_parser import parse_input

text = """2024-03-12T10:15:00.000+05:30
WARNING: Read Failed. group:1 disk:0 AU:1000 offset:10000 size:8192
2024-03-12T10:15:22.000+05:30
ORA-15080: synchronous I/O operation to a disk failed
2024-03-12T10:15:25.000+05:30
ORA-15130: diskgroup "DATA" is being dismounted
"""

parsed = parse_input(text)
print(f"Mode: {parsed['mode']}")
print(f"Platform: {parsed['platform']}")

patterns = match_patterns(text=text, log_source="", platform=parsed['platform'])
print(f"Matched patterns: {[p['pattern_id'] for p in patterns]}")

if not patterns:
    print("FAILED TO MATCH ANY PATTERN")
    # Debug individual patterns
    from src.knowledge_graph.pattern_matcher import _compile_patterns
    compiled = _compile_patterns()
    for pid in ["ORA_DISK_IO_ERROR", "ASM_DISMOUNT_CRITICAL", "EXA_CELL_IO_ERROR"]:
        if pid in compiled:
            pdata = compiled[pid]
            print(f"Checking {pid}...")
            for rx in pdata["match_any"]:
                if rx.search(text):
                    print(f"  - match_any HIT: {rx.pattern}")
                else:
                    print(f"  - match_any MISS: {rx.pattern}")
