
import re

text = "2024-03-12T10:15:00.000+05:30\r\nWARNING: Read Failed. group:1 disk:0 AU:1000 offset:10000 size:8192\r\n2024-03-12T10:15:22.000+05:30\r\nORA-15080: synchronous I/O operation to a disk failed"

# ORA_DISK_IO_ERROR: ["ORA-15080: synchronous I/O operation to a disk failed","ORA-15080.*failed"]
p1 = re.compile("ORA-15080: synchronous I/O operation to a disk failed", re.I | re.M)
p2 = re.compile("ORA-15080.*failed", re.I | re.M)

print(f"Match 1: {bool(p1.search(text))}")
print(f"Match 2: {bool(p2.search(text))}")

# EXA_CELL_IO_ERROR: ["Read Failed. group:\\d+ disk:\\d+ AU:\\d+","WARNING: Read Failed.*group:\\d+"]
p3 = re.compile("Read Failed. group:\\d+ disk:\\d+ AU:\\d+", re.I | re.M)
p4 = re.compile("WARNING: Read Failed.*group:\\d+", re.I | re.M)

print(f"Match 3: {bool(p3.search(text))}")
print(f"Match 4: {bool(p4.search(text))}")

# With DOTALL
p4_s = re.compile("WARNING: Read Failed.*group:\\d+", re.I | re.M | re.S)
print(f"Match 4 (DOTALL): {bool(p4_s.search(text))}")
