"""Unified extractor must route multipathd[pid] syslog lines through syslog parsing (not generic-only)."""

from src.parsers.unified_evidence import extract_normalized_events_unified


def test_multipathd_with_pid_triggers_syslog_route_not_generic_only():
    text = "Mar 16 07:30:14 dbhost07 multipathd[921]: mpatha: remaining active paths: 0"
    ev = extract_normalized_events_unified(text, source_file="messages", source_path="messages")
    codes = [e.get("code") for e in ev if e.get("code")]
    parsers = {e.get("parser_name") for e in ev}
    assert "MULTIPATH_ALL_PATHS_DOWN" in codes, f"expected multipath code, got {codes}"
    assert "syslog_parser" in parsers or any(
        "syslog" in (p or "").lower() for p in parsers
    ), f"expected syslog-derived rows, parsers={parsers}"
