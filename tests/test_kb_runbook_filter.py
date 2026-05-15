"""Runbook attachment filtering (executable vs documentation blobs)."""

from __future__ import annotations

from src.agent.agent import _kb_runbook_attachments_for_oras, _looks_like_executable_dba_command


def test_executable_detector_sql() -> None:
    assert _looks_like_executable_dba_command("SELECT 1 FROM dual")
    assert _looks_like_executable_dba_command("alter diskgroup DATA check all")


def test_executable_detector_rejects_mos_prose() -> None:
    blob = "Cause: disk group missing.\n\nAction: Check alert log."
    assert not _looks_like_executable_dba_command(blob)


def test_kb_attachments_returns_both_keys() -> None:
    out = _kb_runbook_attachments_for_oras([])
    assert "runbook_remediation" in out and "runbook_doc_hints" in out
    assert out["runbook_remediation"] == [] and out["runbook_doc_hints"] == []
