"""Integration: strong mixed evidence must not be downgraded to NO_MATCH by legacy report gates."""

from __future__ import annotations

import pytest

from src.agent.agent import OracleDiagnosticAgent


MIXED_STORAGE_CASCADE = """
2024-03-16T07:08:10.000+00:00
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
ORA-00353: log corruption near block 1024 change 19726233 time 03/16/2024 07:08:10
ORA-00312: online log 3 thread 1: '/u01/app/oracle/oradata/PRD/redo03.log'
LGWR (ospid: 22011): terminating the instance due to error 353
2024-03-16T07:18:02.000+00:00 Read Failed. group:3 disk:1 AU:781244 offset:8192 size:8192
ORA-15080: synchronous I/O operation to a disk failed
ORA-15130: diskgroup "DATA" is being dismounted
Mar 16 07:30:12 dbhost07 kernel: sd 3:0:0:1: [sdd] FAILED Result: hostbyte=DID_TIME_OUT driverbyte=DRIVER_TIMEOUT
Mar 16 07:30:14 dbhost07 multipathd[921]: mpatha: remaining active paths: 0
2024-03-16T07:36:22.000+00:00 cell01 CELLSRV: warningCode=FLASH_IO_TIMEOUT flashDisk=FD_02 cellDisk=CD_05
"""


@pytest.fixture
def agent():
    a = OracleDiagnosticAgent()
    a.initialize()
    return a


def test_full_storage_cascade_not_downgraded_to_no_match(agent: OracleDiagnosticAgent):
    report = agent.diagnose(MIXED_STORAGE_CASCADE)

    assert report.get("status") == "SUCCESS", (
        f"expected SUCCESS, got {report.get('status')}: {report.get('no_match_reason')}"
    )
    rca = report.get("rca_framework") or {}
    root = rca.get("root_cause_candidate") or {}
    assert root.get("root_cause") == "STORAGE_FLASH_IO_OR_MEDIA_FAILURE"
    assert root.get("status") in {"CONFIRMED", "LIKELY"}
    assert float(rca.get("correlation_model_score") or 0) >= 85.0
    assert report.get("root_cause") and report["root_cause"].get("pattern")
