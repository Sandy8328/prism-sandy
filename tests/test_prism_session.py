"""PRISM session merge (Option C) helpers."""

from ui.prism_session import (
    _extract_pinned_signal_lines,
    merge_turns_to_raw,
    turn_append_file,
    turn_append_paste,
)


def test_merge_turns_preserves_order_and_headers():
    turns: list = []
    turns = turn_append_paste(turns, "ORA-00600: test", 50_000)
    turns = turn_append_file(turns, "alert.log", "Second line\n", 50_000)
    merged = merge_turns_to_raw(turns, 200_000)
    assert "PRISM turn 1" in merged and "ORA-00600" in merged
    assert "PRISM turn 2" in merged and "alert.log" in merged
    assert "Second line" in merged


def test_merge_respects_max_merged():
    turns = [{"kind": "paste", "label": "x", "content": "A" * 200}]
    merged = merge_turns_to_raw(turns, max_merged=80)
    assert "size cap reached" in merged.lower()
    assert len(merged) <= 500


def test_merge_max_merged_zero_is_unlimited():
    turns = [{"kind": "paste", "label": "x", "content": "A" * 800}]
    merged = merge_turns_to_raw(turns, max_merged=0)
    assert "size cap reached" not in merged.lower()
    assert merged.count("A") == 800


def test_pinned_signals_preserved_when_capped():
    turns = [
        {
            "kind": "paste",
            "label": "alert",
            "content": "A" * 120 + "\nORA-00353: log corruption near block\n" + "B" * 120,
        },
        {
            "kind": "paste",
            "label": "syslog",
            "content": "kernel: SCSI_DISK_TIMEOUT on /dev/sdb",
        },
    ]
    merged = merge_turns_to_raw(turns, max_merged=180)
    assert "pinned signals" in merged
    assert "ORA-00353" in merged
    assert "SCSI_DISK_TIMEOUT" in merged


def test_extract_pinned_signal_lines_dedupes_ora():
    turns = [
        {"kind": "paste", "label": "t1", "content": "ORA-00600: internal error"},
        {"kind": "paste", "label": "t2", "content": "ORA-00600: internal error"},
    ]
    lines = _extract_pinned_signal_lines(turns)
    assert len(lines) == 1
