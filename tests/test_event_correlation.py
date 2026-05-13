"""Regression tests for evidence-first event extraction and ORA role assignment."""

from src.agent.event_correlation import (
    build_event_correlation_analysis,
    extract_events,
    _collect_merged_layer_set,
    _layer_for_pattern,
    merge_extract_events_with_normalized,
)


def test_extract_events_finds_ora_and_trace():
    text = """
2024-03-16T07:30:00+00:00 Errors in file /u01/app/oracle/diag/rdbms/prd/prd/trace/prd_lgwr_123.trc:
ORA-00353: log corruption near block 1
ORA-00312: online log 3 thread 1: '/redo03.log'
""".strip()
    ev = extract_events(text)
    assert any("ORA-00353" in (e.get("oracle_codes") or []) for e in ev)
    assert any("prd_lgwr_123.trc" in (e.get("trace_file") or "") for e in ev)


def test_ora_27072_role_db_io_symptom():
    text = "Mar 16 07:31:01 db01 kernel: qla2xxx: Adapter reset issued\nORA-27072: Linux Error: 5: Input/output error\n"
    parsed = {
        "raw_input": text,
        "all_ora_codes": ["ORA-27072"],
        "primary_ora": "ORA-27072",
        "hostname": "db01",
        "observed_layers": ["DB", "OS"],
        "direct_pattern_ids": ["FC_HBA_RESET"],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, {"pattern_id": "FC_HBA_RESET", "score": 90})
    rows = {r["error"]: r["role"] for r in rca["correlated_error_table"]}
    assert rows["ORA-27072"] == "DB_IO_SYMPTOM"


def test_storage_signal_prefers_storage_root_label():
    text = """
FLASH_IO_TIMEOUT warningCode=FLASH_IO_TIMEOUT flashDisk=FD_02
ORA-15080: synchronous I/O operation failed
""".strip()
    parsed = {
        "raw_input": text,
        "all_ora_codes": ["ORA-15080"],
        "primary_ora": "ORA-15080",
        "hostname": "",
        "observed_layers": ["STORAGE", "DB"],
        "direct_pattern_ids": ["EXA_FLASH_FAIL"],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(
        parsed,
        [],
        {"root_pattern": "EXA_FLASH_FAIL", "causal_chain": ["ROOT: EXA_FLASH_FAIL", "DB: ORA-15080"]},
        {"pattern_id": "EXA_FLASH_FAIL", "score": 90},
    )
    assert "STORAGE" in rca["root_cause_candidate"]["root_cause"].upper() or "FLASH" in rca["root_cause_candidate"]["root_cause"].upper()


def test_annotate_fix_marks_destructive():
    from src.agent.event_correlation import annotate_fix_command_categories

    fixes = [
        {
            "fix_id": "x",
            "commands": ["alter database recover database until cancel"],
            "risk": "HIGH",
            "requires": "dba",
            "downtime_required": True,
        }
    ]
    out = annotate_fix_command_categories(fixes)
    assert out[0]["command_category"] == "DESTRUCTIVE_DBA_APPROVAL_REQUIRED"


def test_multipath_bundle_is_diagnostic():
    from src.agent.event_correlation import annotate_fix_command_categories

    fixes = [
        {
            "fix_id": "checks",
            "commands": ["multipath -ll", "dmesg -T | tail -50"],
            "risk": "LOW",
            "requires": "root",
            "downtime_required": False,
        }
    ]
    out = annotate_fix_command_categories(fixes)
    assert out[0]["command_category"] == "DIAGNOSTIC"


def test_non_ora_table_separate_from_ora_table():
    text = "ORA-00353: corruption\nLGWR terminating the instance due to error 353\n"
    parsed = {
        "raw_input": text,
        "all_ora_codes": ["ORA-00353"],
        "primary_ora": "ORA-00353",
        "hostname": "",
        "observed_layers": ["DB"],
        "direct_pattern_ids": [],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    ora_codes_in_ora_tbl = {r["error"] for r in rca["observed_ora_correlation_table"]}
    assert "ORA-00353" in ora_codes_in_ora_tbl
    events_non_ora = {r.get("event") for r in rca["non_ora_correlated_events"]}
    assert "LGWR_INSTANCE_TERMINATION" in events_non_ora
    assert "LGWR_INSTANCE_TERMINATION" not in ora_codes_in_ora_tbl


def test_os_path_patterns_root_not_ora_27072_when_asm_present():
    """DB+ASM+OS without cell/storage: deepest root is OS path, not ORA-27072."""
    text = """
2024-03-16T08:00:01+00:00 kernel: scsi 0:0:1:2: SCSI_DISK_TIMEOUT on /dev/sdb
2024-03-16T08:00:02+00:00 multipathd: mpath4: all paths down
2024-03-16T08:00:03+00:00 +DATA ORA-15080: synchronous I/O operation failed for disk /dev/mpath4
2024-03-16T08:00:04+00:00 ORA-15130: diskgroup +DATA dismounted
2024-03-16T08:00:05+00:00 Errors in file /u01/app/oracle/diag/rdbms/x/x/trace/x_lgwr_1.trc:
ORA-27072: file I/O error; Linux Error: 5 Input/output error
ORA-00353: log corruption near block 1
ORA-00312: online log 1 thread 1: '/redo01.log'
""".strip()
    parsed = {
        "raw_input": text,
        "all_ora_codes": [
            "ORA-15080",
            "ORA-15130",
            "ORA-27072",
            "ORA-00353",
            "ORA-00312",
        ],
        "primary_ora": "ORA-27072",
        "hostname": "db01",
        "observed_layers": ["OS", "ASM", "DB"],
        "direct_pattern_ids": ["SCSI_DISK_TIMEOUT", "MULTIPATH_ALL_PATHS_DOWN"],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    root = rca["root_cause_candidate"]["root_cause"]
    assert root != "ORA-27072"
    assert root == "OS_STORAGE_PATH_FAILURE"
    assert rca["root_cause_candidate"]["layer"] == "OS"
    cascade = "\n".join(rca["cascade_chain_marked"])
    assert "NEEDS_EVIDENCE" in cascade
    assert "MULTIPATH_ALL_PATHS_DOWN" in cascade
    assert "SCSI_DISK_TIMEOUT" in cascade
    assert "ORA-15080" in cascade and "ORA-27072" in cascade and "ORA-00353" in cascade
    # Bridge symptom after ASM ORAs, before redo fatals
    lines = rca["cascade_chain_marked"]
    idx_150 = next(i for i, s in enumerate(lines) if "ORA-15080" in s)
    idx_270 = next(i for i, s in enumerate(lines) if "ORA-27072" in s)
    idx_353 = next(i for i, s in enumerate(lines) if "ORA-00353" in s)
    assert idx_150 < idx_270 < idx_353


def test_pattern_desc_avoids_misleading_os_error_for_storage_root():
    from src.agent.report_builder import _get_pattern_desc

    s = _get_pattern_desc("STORAGE_FLASH_IO_OR_MEDIA_FAILURE")
    assert "os error pattern" not in s.lower()
    assert "storage" in s.lower()


def test_ora_00312_never_root_alone():
    text = "ORA-00312: online log 1 thread 1: '/redo01.log'"
    parsed = {
        "raw_input": text,
        "all_ora_codes": ["ORA-00312"],
        "primary_ora": "ORA-00312",
        "hostname": "",
        "observed_layers": ["DB"],
        "direct_pattern_ids": [],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    assert rca["root_cause_candidate"]["root_cause"] == "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT"
    assert rca["root_cause_evidence_status"] == "NEEDS_MORE_INFO"


def test_db_only_redo_triangle_uses_synthetic_root():
    text = """
ORA-27072: file I/O error
ORA-00353: log corruption near block 1
ORA-00312: online log 1 thread 1: '/redo01.log'
""".strip()
    parsed = {
        "raw_input": text,
        "all_ora_codes": ["ORA-27072", "ORA-00353", "ORA-00312"],
        "primary_ora": "ORA-27072",
        "hostname": "db01",
        "observed_layers": ["DB"],
        "direct_pattern_ids": [],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    assert rca["root_cause_candidate"]["root_cause"] == "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE"
    assert rca["root_cause_candidate"]["layer"] == "DB"
    assert rca["root_cause_candidate"]["root_cause"] != "ORA-27072"


def test_network_pattern_resolves_to_network_layer_not_os_default():
    parsed = {
        "raw_input": "iptables DROP dst=1521",
        "all_ora_codes": [],
        "hostname": "",
        "observed_layers": ["NETWORK"],
        "direct_pattern_ids": ["IPTABLES_BLOCKING_1521"],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    assert rca["root_cause_candidate"]["root_cause"] == "IPTABLES_BLOCKING_1521"
    assert rca["root_cause_candidate"]["layer"] == "NETWORK"


def test_unmapped_pattern_never_implies_os_layer():
    assert _layer_for_pattern("TOTALLY_UNMAPPED_PATTERN_XYZ999") == "UNKNOWN"
    parsed = {
        "raw_input": "",
        "all_ora_codes": [],
        "hostname": "",
        "observed_layers": [],
        "direct_pattern_ids": ["TOTALLY_UNMAPPED_PATTERN_XYZ999"],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    assert rca["root_cause_candidate"]["layer"] == "UNKNOWN"
    assert rca["root_cause_candidate"]["root_cause"] == "NEEDS_MORE_INFO"
    assert rca["correlation_model_score"] <= 45.0


def test_asm_pattern_id_maps_to_asm_layer():
    assert _layer_for_pattern("ASM_DISMOUNT_CRITICAL") == "ASM"
    parsed = {
        "raw_input": "",
        "all_ora_codes": [],
        "hostname": "",
        "observed_layers": ["ASM"],
        "direct_pattern_ids": ["ASM_DISMOUNT_CRITICAL"],
        "mode": "log_paste",
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    assert rca["root_cause_candidate"]["root_cause"] == "ASM_DISMOUNT_CRITICAL"
    assert rca["root_cause_candidate"]["layer"] == "ASM"


def test_tns_code_maps_to_network_layer():
    from src.agent.event_correlation import _event_layer, _collect_merged_layer_set

    assert (
        _event_layer({"code": "TNS-12535", "code_type": "TNS", "preview": "TNS-12535: timeout", "source_layer": "UNKNOWN"})
        == "NETWORK"
    )
    ev = [{"code": "TNS-12535", "code_type": "TNS", "preview": "TNS-12535", "source_layer": "UNKNOWN"}]
    assert "NETWORK" in _collect_merged_layer_set([], ev, [])


def test_direct_os_patterns_merge_os_into_layers_without_parser_os_flag():
    """Direct path patterns contribute OS to merged layers even if observed_layers omits OS."""
    raw = "kernel: scsi timeout\nmultipathd: all paths down\n"
    ev = merge_extract_events_with_normalized(raw, None)
    ls = _collect_merged_layer_set(["DB"], ev, ["SCSI_DISK_TIMEOUT", "MULTIPATH_ALL_PATHS_DOWN"])
    assert "OS" in ls
