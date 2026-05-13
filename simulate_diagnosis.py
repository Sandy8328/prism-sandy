
import os
import sys
# Add src to path
sys.path.append(os.getcwd())

from src.agent.agent import get_agent
from src.agent.scorer import score_all_candidates

text = """2024-03-12T10:15:00.000+05:30
WARNING: Read Failed. group:1 disk:0 AU:1000 offset:10000 size:8192
2024-03-12T10:15:22.000+05:30
ORA-15080: synchronous I/O operation to a disk failed
2024-03-12T10:15:25.000+05:30
ORA-15130: diskgroup "DATA" is being dismounted
"""

with open("test_upload.log", "w") as f:
    f.write(text)

agent = get_agent()
# Call diagnose directly to avoid any filename loss issues in this debug
report = agent.diagnose(query=text, platform="LINUX", hostname="test-host")

print(f"Report status: {report['status']}")
print(f"Confidence score: {report['confidence']['score']}")
print(f"Confidence label: {report['confidence']['label']}")
print(f"No match reason: {report.get('no_match_reason')}")

if "confidence" in report and "breakdown" in report["confidence"]:
    print(f"Breakdown: {report['confidence']['breakdown']}")

# Debug fused results
print(f"Fused results count: {len(report.get('evidence', []))}")
for ev in report.get('evidence', []):
    print(f"  - Chunk: {ev['chunk_id']}, Source: {ev['log_source']}")
