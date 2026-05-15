"""Tests for Gemini JSON fence stripping and strict object parsing."""

from __future__ import annotations

import pytest

from src.agent.llm_client import LlmClientError, _parse_gemini_json_object, _strip_markdown_json_fence


def test_strip_fence_json_prefix() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert _strip_markdown_json_fence(raw) == '{"a": 1}'


def test_strip_fence_preserves_inner_backticks() -> None:
    raw = '```\n{"cmd": "echo `date`"}\n```'
    assert "`date`" in _strip_markdown_json_fence(raw)


def test_parse_valid_object() -> None:
    assert _parse_gemini_json_object('{"x": 2}', context="t") == {"x": 2}


def test_parse_rejects_non_object() -> None:
    with pytest.raises(LlmClientError, match="JSON object"):
        _parse_gemini_json_object("[1,2]", context="t")


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(LlmClientError, match="not valid JSON"):
        _parse_gemini_json_object('{"broken": "unterminated}', context="t")
