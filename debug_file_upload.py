
import os
import sys
# Add src to path
sys.path.append(os.getcwd())

from src.agent.agent import get_agent
from src.parsers.platform_detector import detect_from_filename, detect_platform

filename = "storage-nas-05_syslog.log"
content = """2024-03-12T10:15:00.000+05:30
WARNING: Read Failed. group:1 disk:0 AU:1000 offset:10000 size:8192
2024-03-12T10:15:22.000+05:30
ORA-15080: synchronous I/O operation to a disk failed
"""

print(f"Filename detection: {detect_from_filename(filename)}")
print(f"Content detection: {detect_platform(text=content[:2000])}")

agent = get_agent()

with open("test_syslog.log", "w") as f:
    f.write(content)

report = agent.diagnose_log_file(filepath="test_syslog.log", hostname="test", platform="")
print(f"Report platform: {report.get('platform')}")
print(f"Report confidence: {report.get('confidence_score')}")
print(f"Report root_cause: {report.get('root_cause', {}).get('root_pattern')}")
