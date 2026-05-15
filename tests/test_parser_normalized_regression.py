"""Regression tests for unified normalized evidence extraction (parser layer)."""

import json
import os
import shutil
import tempfile
import zipfile

from src.parsers.unified_evidence import (
    extract_normalized_events_from_zip,
    extract_normalized_events_unified,
)
from src.parsers.zip_evidence import safe_extract_zip


ALERT_REDO_IO = """
2024-03-16T07:08:10.000+00:00
ORA-27072: File I/O error
Linux-x86_64 Error: 5: Input/output error
ORA-00353: log corruption near block 1024 change 19726233 time 03/16/2024 07:08:10
ORA-00312: online log 3 thread 1: '/u01/app/oracle/oradata/PRD/redo03.log'
LGWR (ospid: 22011): terminating the instance due to error 353
""".strip()

ASM_SNIP = """
Read Failed. group:3 disk:1 AU:781244 offset:8192 size:8192
failed to read mirror side 1 of virtual extent 92 logical extent 0 of file 258 in group 3
cache dismounting group 3 (DATA)
ORA-15080: synchronous I/O operation to a disk failed
ORA-15130: diskgroup "DATA" is being dismounted
ORA-15081: failed to submit an I/O operation to a disk
""".strip()

SYSLOG_SNIP = """
Mar 16 07:30:10 dbhost07 kernel: qla2xxx [0000:03:00.0]-801c: Abort command issued
Mar 16 07:30:11 dbhost07 kernel: qla2xxx [0000:03:00.0]-8020: Adapter reset issued
Mar 16 07:30:12 dbhost07 kernel: sd 3:0:0:1: [sdd] FAILED Result: hostbyte=DID_TIME_OUT driverbyte=DRIVER_TIMEOUT
Mar 16 07:30:12 dbhost07 kernel: blk_update_request: I/O error, dev sdd, sector 11922304 op READ
Mar 16 07:30:14 dbhost07 multipathd: mpatha: remaining active paths: 0
Mar 16 07:30:16 dbhost07 kernel: sdd rejecting I/O to offline device
""".strip()

CELL_SNIP = """
2024-03-16T07:36:20.000+00:00 cell01 CELLSRV: flashCache read error at griddisk DATA_CD_05 offset 28311552 io_time=612ms
2024-03-16T07:36:21.000+00:00 cell01 CELLSRV: Read Failed. group:3 disk:5 AU:781244 offset:8192 size:8192
2024-03-16T07:36:22.000+00:00 cell01 CELLSRV: warningCode=FLASH_IO_TIMEOUT flashDisk=FD_02 cellDisk=CD_05
2024-03-16T07:36:23.000+00:00 cell01 MS: FD_02 critical
2024-03-16T07:36:24.000+00:00 cell01 CELLSRV: repeated media read retries exhausted for DATA_CD_05
""".strip()

CELL_METRIC_CRIT = """
2024-03-16T07:36:23.000+00:00 cell01 MS: alertType: Stateful metricObjectName: FD_02 metricValue: critical
""".strip()


def _codes(ev):
    return [e.get("code") for e in ev if e.get("code_type") == "ORA"]


def test_alert_errno_gets_source_file_from_path_only():
    ev = extract_normalized_events_unified(ALERT_REDO_IO, source_path="diag/rdbms/p/p/trace/alert_p.log")
    errno = next(e for e in ev if e.get("code") == "OS_ERRNO_5")
    assert errno.get("source_path") == "diag/rdbms/p/p/trace/alert_p.log"
    assert errno.get("source_file") == "alert_p.log"


def test_json_single_object_preserves_inner_source_and_wrapper():
    inner = "2024-03-16T07:08:10.000+00:00\nORA-27072: File I/O error"
    payload = json.dumps({"filename": "alert.log", "content": inner})
    ev = extract_normalized_events_unified(
        payload, source_file="payload.json", source_path="outer/payload.json"
    )
    ora = next(e for e in ev if e.get("code") == "ORA-27072")
    assert ora.get("source_file") == "alert.log"
    assert ora.get("source_path") == "alert.log"
    d = ora.get("details") or {}
    assert d.get("wrapper_source") == "payload.json"
    assert d.get("wrapper_source_path") == "outer/payload.json"


def test_plain_audit_grant_dba():
    from src.parsers.audit_parser import OracleAuditParser

    text = "ACTION: GRANT DBA\nRETURNCODE: 0"
    a = OracleAuditParser().parse_audit_text(text)
    assert a.get("event_type") == "PRIVILEGE_CHANGE"
    assert a.get("returncode") == "0"


def test_security_failed_password_without_port_unified():
    line = "Mar 16 07:00:00 host sshd[1]: Failed password for invalid user oracle from 1.2.3.4"
    ev = extract_normalized_events_unified(line, source_path="messages")
    sec = [e for e in ev if e.get("layer") == "SECURITY"]
    assert sec and sec[0].get("code") == "AUTH_FAILURE"
    assert not any(e.get("code") == "GENERIC_FAILURE_LINE" for e in ev)


def test_asm_snippet_source_file_from_path_only():
    ev = extract_normalized_events_unified(ASM_SNIP, source_path="trace/asm_alert.log")
    rf = next(e for e in ev if e.get("code") == "ASM_READ_FAILED")
    assert rf.get("source_path") == "trace/asm_alert.log"
    assert rf.get("source_file") == "asm_alert.log"


def test_cell_flash_critical_beats_warning_code_severity():
    line = (
        "2024-03-16T07:36:23.000+00:00 cell01 MS: warningCode=FOO "
        "metricObjectName: FD_02 metricValue: critical"
    )
    ev = extract_normalized_events_unified(line, source_file="c.log", source_path="c.log")
    hit = [e for e in ev if e.get("code") == "FLASH_DISK_CRITICAL"]
    assert hit and hit[0].get("severity") == "CRITICAL" and hit[0].get("flash_disk") == "FD_02"


def test_alert_redo_io_chain():
    ev = extract_normalized_events_unified(ALERT_REDO_IO, source_path="alert.log")
    oras = set(_codes(ev))
    assert "ORA-27072" in oras and "ORA-00353" in oras and "ORA-00312" in oras
    lgwr = [e for e in ev if e.get("code") == "LGWR_INSTANCE_TERMINATION"]
    assert lgwr and lgwr[0].get("code_type") == "PROCESS_EVENT"
    assert lgwr[0].get("mapped_code_hint") == "ORA-00353"
    o312 = next(e for e in ev if e.get("code") == "ORA-00312")
    assert o312.get("redo_group") == "3" and o312.get("redo_thread") == "1"
    assert "redo03" in (o312.get("file_path") or "")
    o270 = next(e for e in ev if e.get("code") == "ORA-27072")
    assert o270.get("os_errno") == "5"


def test_asm_coordinates_and_oras():
    ev = extract_normalized_events_unified(ASM_SNIP, source_file="asm_alert.log", source_path="asm_alert.log")
    oras = set(_codes(ev))
    assert {"ORA-15080", "ORA-15081", "ORA-15130"}.issubset(oras)
    assert sum(1 for e in ev if e.get("code") == "ORA-15080") == 1
    rf = [e for e in ev if e.get("code") == "ASM_READ_FAILED"]
    assert rf and rf[0].get("asm_group") == "3" and rf[0].get("au") == "781244"
    assert rf[0].get("source_file") == "asm_alert.log"
    dis = [e for e in ev if e.get("code") == "ASM_DISMOUNT_PROGRESS"]
    assert dis and dis[0].get("diskgroup") == "DATA"


def test_syslog_os_signals():
    ev = extract_normalized_events_unified(SYSLOG_SNIP, source_path="messages")
    codes = {e.get("code") for e in ev if e.get("code_type") == "OS_PATTERN"}
    assert "MULTIPATH_ALL_PATHS_DOWN" in codes
    assert "SCSI_DISK_TIMEOUT" in codes or "OS_BLOCK_IO_ERROR" in codes
    assert "FC_HBA_ABORT" in codes and "FC_HBA_RESET" in codes
    hosts = {e.get("host") for e in ev if e.get("host")}
    assert "dbhost07" in hosts


def test_cell_storage_fields():
    ev = extract_normalized_events_unified(CELL_SNIP, cell_name="cell01")
    assert any(e.get("layer") == "STORAGE" for e in ev)
    assert not any(e.get("code") == "ASM_READ_FAILED" for e in ev), (
        "cell logs must not emit asm_snippet ASM_READ_FAILED duplicate"
    )
    flash = [e for e in ev if e.get("code") == "FLASH_IO_TIMEOUT"]
    assert flash
    assert flash[0].get("flash_disk") == "FD_02" or flash[0].get("flash_disk")
    assert flash[0].get("timestamp") is not None
    fc = [e for e in ev if e.get("code") == "FLASH_CACHE_READ_ERROR"]
    assert fc


def test_cell_metric_object_critical_maps_flash_disk():
    ev = extract_normalized_events_unified(CELL_METRIC_CRIT, source_file="cell.log", source_path="cell.log")
    hit = [e for e in ev if e.get("code") == "FLASH_DISK_CRITICAL"]
    assert hit
    assert hit[0].get("flash_disk") == "FD_02"
    assert hit[0].get("source_file") == "cell.log"
    assert hit[0].get("severity") == "CRITICAL"


def test_mixed_paste_keeps_asm_coordinates_and_cell_storage():
    mixed = "\n".join([ALERT_REDO_IO, ASM_SNIP, SYSLOG_SNIP, CELL_SNIP])
    ev = extract_normalized_events_unified(mixed, source_path="mixed.log")
    assert any(e.get("code") == "ASM_READ_FAILED" for e in ev)
    assert any(e.get("code") == "STORAGE_ASM_READ_FAILED" for e in ev)


def test_unified_direct_json_unwrap():
    payload = json.dumps(
        {
            "logs": [
                {"name": "alert.log", "content": ALERT_REDO_IO},
                {"name": "messages", "text": SYSLOG_SNIP},
            ]
        }
    )
    ev = extract_normalized_events_unified(payload, source_path="payload.json")
    assert any(e.get("code") == "ORA-27072" for e in ev)
    assert any(e.get("code") == "SCSI_DISK_TIMEOUT" for e in ev)
    alert_events = [e for e in ev if e.get("code") == "ORA-27072"]
    assert alert_events and alert_events[0].get("source_file") == "alert.log"


def test_zip_extract_normalized_roundtrip():
    td = tempfile.mkdtemp()
    try:
        zpath = os.path.join(td, "b.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("cell/foo.log", CELL_SNIP)
        out = extract_normalized_events_from_zip(zpath)
        assert out["events"]
        assert any(e.get("code") == "FLASH_IO_TIMEOUT" for e in out["events"])
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_zip_nested_inner_zip_expands():
    td = tempfile.mkdtemp()
    try:
        inner_path = os.path.join(td, "inner.zip")
        with zipfile.ZipFile(inner_path, "w") as iz:
            iz.writestr("diag/alert.log", "ORA-00060: deadlock detected while waiting for resource\n")
        outer = os.path.join(td, "outer.zip")
        with zipfile.ZipFile(outer, "w") as oz:
            oz.write(inner_path, "srdc/bundle/inner.zip")
        out = extract_normalized_events_from_zip(outer, max_files=50)
        assert out["events"]
        assert any((e.get("code") or "").upper() == "ORA-00060" for e in out["events"])
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_no_match_generic_low_confidence():
    ev = extract_normalized_events_unified("random text with no known Oracle pattern")
    assert isinstance(ev, list)
    if ev:
        assert all((e.get("parse_confidence") or "").upper() in ("LOW", "MEDIUM") for e in ev)


def test_zip_safe_extract_and_paths():
    td = tempfile.mkdtemp()
    try:
        zpath = os.path.join(td, "t.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("diag/rdbms/x/x/trace/alert_x.log", "ORA-07445: exception encountered\n")
            zf.writestr("../../outside.log", "bad")
        outd = os.path.join(td, "out")
        paths = safe_extract_zip(zpath, outd)["extracted"]
        assert any("alert_x.log" in p for p in paths)
        assert not any("outside.log" in p for p in paths)
    finally:
        for root, _, files in os.walk(td, topdown=False):
            for f in files:
                os.unlink(os.path.join(root, f))
            os.rmdir(root)


def test_input_json_logs_array_unwraps():
    from src.agent.input_parser import parse_input

    raw = json.dumps(
        {
            "logs": [
                {"name": "a.log", "text": "ORA-04031: out of memory\n"},
                {"name": "b.log", "text": "ORA-00060: deadlock\n"},
            ]
        }
    )
    p = parse_input(raw)
    assert "ORA-04031" in p["raw_input"] and "ORA-00060" in p["raw_input"]
    assert isinstance(p.get("normalized_events"), list)
    assert "ORA-04031" in str(p.get("normalized_events"))
