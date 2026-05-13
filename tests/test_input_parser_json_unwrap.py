"""Structured JSON log exports (hostname/timestamp/content) normalize to alert text."""

from src.agent.input_parser import parse_input, _unwrap_structured_log_json, _detect_input_mode


def test_unwrap_json_array_extracts_content():
    raw = (
        '[{"hostname": "db01", "timestamp": "2024-03-15T10:00:00", '
        '"content": "Errors in file x.trc:\\nORA-01555: snapshot too old\\n", '
        '"file_source": "alert.log"}]'
    )
    text, ok = _unwrap_structured_log_json(raw)
    assert ok is True
    assert "host=db01" in text
    assert "ORA-01555" in text
    assert _detect_input_mode(text) == "log_paste"


def test_parse_input_unwraps_and_sets_raw_input():
    raw = (
        '[{"hostname": "db01", "content": "ORA-01555: test\\nORA-06512: at line 1\\n"}]'
    )
    p = parse_input(raw)
    assert p["raw_input"].startswith("# host=db01")
    assert "ORA-01555" in p["raw_input"]
    assert p["primary_ora"] == "ORA-01555"
    assert p["mode"] == "log_paste"


def test_unwrap_single_object():
    raw = '{"hostname": "h1", "content": "ORA-00060: deadlock\\n"}'
    text, ok = _unwrap_structured_log_json(raw)
    assert ok is True
    assert "ORA-00060" in text


def test_invalid_json_unchanged():
    raw = "[{not json"
    text, ok = _unwrap_structured_log_json(raw)
    assert ok is False
    assert text == raw


def test_get_commands_for_ora01555_falls_back_to_oracle_action_plan():
    from src.knowledge_graph.graph import get_commands_for_ora

    out = get_commands_for_ora("ORA-01555")
    assert out["commands"]
    assert "snapshot too old" in out["commands"][0].lower()
    assert out["source"] == "oracle_action_plan"


def test_platform_hint_linux_from_oracle_banner_not_only_os_error_line():
    """Catalog / alert lines say 'Linux x86_64' without 'Linux-x86_64 Error:'."""
    p = parse_input(
        "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production\n"
        "Version 19.29.0.0.0 | LINUX X86_64\n"
        "ORA-00600: internal error code\n"
    )
    assert p["platform"] == "LINUX"


def test_platform_hint_linux_tns_for_linux():
    p = parse_input(
        "2026-04-15T07:05:43+05:30\n"
        "TNS:for Linux: Version 19.0.0.0.0 - Production\n"
        "ORA-01110: data file 1\n"
    )
    assert p["platform"] == "LINUX"


def test_platform_hint_rds_does_not_match_inside_records():
    """Regression: loose 'rds' matched 'records' / 'ORDS' and mislabeled platform AWS."""
    p = parse_input(
        "2026-04-15T07:05:43+05:30\n"
        "ORA-00600: internal error code, arguments: [kcbgtcr_17], [0], [7], [], [], [], [], [], [], [], [], []\n"
        "Recovery applied 12 redo records.\n"
    )
    assert p["platform"] != "AWS"


def test_platform_hint_still_detects_explicit_aws_ec2_rds():
    p = parse_input(
        "2026-04-15T07:05:43+05:30\n"
        "Errors in file /u01/app/oracle/diag/rdbms/x/x/trace/alert_x.log:\n"
        "ORA-01110: data file 1: '+DATA/dg/datafile/system01.dbf'\n"
        "Host is on AWS EC2; database is Amazon RDS.\n"
    )
    assert p["platform"] == "AWS"
