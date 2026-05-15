"""Unit tests for advisory remediation playbook helpers (no Gemini)."""

from src.agent.remediation_playbook_advisory import _clamp_markdown


def test_clamp_markdown_noop_when_short() -> None:
    s = "hello\nworld"
    assert _clamp_markdown(s, 100) == s


def test_clamp_markdown_truncates() -> None:
    s = "x" * 100
    out = _clamp_markdown(s, 40)
    assert len(out) <= 40
    assert "truncated" in out
