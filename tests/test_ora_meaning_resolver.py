"""Tests for ORA meaning resolution (PDF JSON + catalog + optional LLM)."""

import json

import pytest

from src.agent import ora_meaning_resolver as omr


@pytest.fixture(autouse=True)
def _reset_ora_cache():
    omr.reset_cache_for_tests()
    yield
    omr.reset_cache_for_tests()


def test_pdf_entry_used(monkeypatch, tmp_path):
    p = tmp_path / "ora.json"
    p.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {"ORA-99998": {"m": "From bundled extract.", "llm": False}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(omr, "_json_path", lambda: p)
    assert omr.resolve_observed_ora_meaning("ORA-99998", None) == "From bundled extract."


def test_catalog_used_when_no_pdf_row(monkeypatch, tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
    monkeypatch.setattr(omr, "_json_path", lambda: p)
    mean = omr.resolve_observed_ora_meaning(
        "ORA-99997",
        "Curated catalog meaning for rare code.",
    )
    assert mean == "Curated catalog meaning for rare code."


def test_placeholder_catalog_skipped(monkeypatch, tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
    monkeypatch.setattr(omr, "_json_path", lambda: p)
    monkeypatch.setattr(omr, "_llm_enabled", lambda: False)
    mean = omr.resolve_observed_ora_meaning("ORA-99996", omr._PLACEHOLDER)
    assert "ORA-99996" in mean
    assert "My Oracle Support" in mean or "reference" in mean.lower()


def test_llm_flag_prefers_stub_when_llm_disabled(monkeypatch, tmp_path):
    p = tmp_path / "x.json"
    p.write_text(
        json.dumps(
            {"version": 1, "entries": {"ORA-77777": {"m": "", "llm": True}}},
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(omr, "_json_path", lambda: p)
    monkeypatch.setattr(omr, "_llm_enabled", lambda: False)
    mean = omr.resolve_observed_ora_meaning("ORA-77777", None)
    assert "ORA-77777" in mean
