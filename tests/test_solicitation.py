"""Solicitation (Guided Diagnostic) should respect session uploads, not only retrieval chunks."""

from __future__ import annotations

from src.agent.report_builder import _get_solicitation, _solicitation_already_covered


def test_asm_log_upload_covers_asm_alert_checklist_item() -> None:
    evs = [{"source_file": "asm.log", "source_path": "asm.log", "layer": "ASM", "preview": "NOTE:"}]
    out = _get_solicitation("ASM", set(), evs)
    assert "ASM alert log" not in out
    assert "asmcmd lsdg" in out


def test_diag_asm_path_in_preview_covers_asm_alert() -> None:
    evs = [
        {
            "source_file": "paste.txt",
            "preview": "see +ASM /oracle/diag/asm/+asm/+ASM/trace/alert_+ASM.log",
        }
    ]
    assert _solicitation_already_covered("ASM alert log", set(), evs)


def test_messages_upload_covers_os_solicitation() -> None:
    evs = [{"source_file": "messages", "source_path": "/var/log/messages"}]
    out = _get_solicitation("OS_TRIGGERED", set(), evs)
    assert "/var/log/messages" not in out
