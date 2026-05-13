"""
tests/test_phase_a_trace_extraction.py
=======================================
Phase A verification: alert_log_parser correctly extracts trace_path,
incident_id, incident_path from all 4 Oracle alert.log trace line formats.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.parsers.alert_log_parser import parse_alert_log_text

# ── Synthetic alert.log blocks (all 4 Oracle trace line formats) ──

_LOG_FORMAT_1 = """
Thu Apr 21 02:44:18 2024
ORA-07445: exception encountered: core dump [qmxeGetReturnType()+1120]
Incident details in: /u01/app/oracle/diag/rdbms/orcl/orcl1/incident/incdir_88321/orcl1_ora_88321_i88321.trc
"""

_LOG_FORMAT_2 = """
Thu Apr 21 02:50:00 2024
ORA-00600: internal error code, arguments: [13011], [5001]
Errors in file /u01/app/oracle/diag/rdbms/orcl/orcl1/trace/orcl1_ora_55432.trc (incident=55432):
"""

_LOG_FORMAT_3 = """
Thu Apr 21 03:10:00 2024
LGWR: terminating instance due to error 338
Dump file: /u01/app/oracle/diag/rdbms/orcl/orcl1/trace/orcl1_lgwr_7890.trc
"""

_LOG_FORMAT_4 = """
Thu Apr 21 03:15:00 2024
ORA-04031: unable to allocate 4096 bytes of shared memory
Trace file: /u01/app/oracle/diag/rdbms/orcl/orcl1/trace/orcl1_ora_99001.trc
"""

_LOG_NO_TRACE = """
Thu Apr 21 04:00:00 2024
ORA-00257: archiver error. Connect internal only, until freed.
"""


def _get_first_entry(log_text: str) -> dict:
    """
    Return the first MEANINGFUL entry — skips the blank INFO placeholder
    that the parser creates when the log text starts with a leading blank line.
    """
    entries = parse_alert_log_text(log_text)
    assert entries, "Parser returned no entries"
    for e in entries:
        # A meaningful entry has ORA codes, a trace path, or a bgproc death
        if e.get("ora_codes") or e.get("trace_path") or e.get("bgproc_died"):
            return e
    # Fallback: return last entry (for no-trace test case)
    return entries[-1]



def test_format1_incident_details():
    """'Incident details in:' line → trace_path, incident_id, incident_path all populated."""
    e = _get_first_entry(_LOG_FORMAT_1)
    assert e["trace_path"] is not None, "trace_path should not be None"
    assert "orcl1_ora_88321_i88321.trc" in e["trace_path"]
    assert e["incident_id"] == "88321", f"Expected 88321, got {e['incident_id']}"
    assert e["incident_path"] is not None
    assert "incdir_88321" in e["incident_path"]
    print(f"  ✅ Format 1 (Incident details): trace_path={e['trace_path']}")


def test_format2_errors_in_file():
    """'Errors in file <path> (incident=N):' line → all 3 fields populated."""
    e = _get_first_entry(_LOG_FORMAT_2)
    assert e["trace_path"] is not None, "trace_path should not be None"
    assert "orcl1_ora_55432.trc" in e["trace_path"]
    assert e["incident_id"] == "55432", f"Expected 55432, got {e['incident_id']}"
    print(f"  ✅ Format 2 (Errors in file): trace_path={e['trace_path']}")


def test_format3_dump_file():
    """'Dump file: <path>' line → trace_path populated."""
    e = _get_first_entry(_LOG_FORMAT_3)
    assert e["trace_path"] is not None, "trace_path should not be None"
    assert "orcl1_lgwr_7890.trc" in e["trace_path"]
    print(f"  ✅ Format 3 (Dump file): trace_path={e['trace_path']}")


def test_format4_trace_file():
    """'Trace file: <path>' line → trace_path populated."""
    e = _get_first_entry(_LOG_FORMAT_4)
    assert e["trace_path"] is not None, "trace_path should not be None"
    assert "orcl1_ora_99001.trc" in e["trace_path"]
    print(f"  ✅ Format 4 (Trace file): trace_path={e['trace_path']}")


def test_no_trace_returns_none():
    """Alert block with no trace reference → all 3 fields are None."""
    e = _get_first_entry(_LOG_NO_TRACE)
    assert e["trace_path"] is None, "trace_path should be None when not in log"
    assert e["incident_id"] is None
    assert e["incident_path"] is None
    print(f"  ✅ No trace: all fields correctly None")


def test_backward_compat_trace_file_key():
    """'trace_file' key still present for backward compatibility."""
    e = _get_first_entry(_LOG_FORMAT_1)
    assert "trace_file" in e, "'trace_file' key must remain for backward compat"
    assert e["trace_file"] == e["trace_path"], "trace_file and trace_path must match"
    print(f"  ✅ Backward compat: trace_file == trace_path")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Phase A — Trace File Path Extraction Tests")
    print("=" * 60)

    tests = [
        test_format1_incident_details,
        test_format2_errors_in_file,
        test_format3_dump_file,
        test_format4_trace_file,
        test_no_trace_returns_none,
        test_backward_compat_trace_file_key,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as ex:
            print(f"  ❌ {t.__name__}: {ex}")
            failed += 1

    print("=" * 60)
    print(f"  Result: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed:
        sys.exit(1)
