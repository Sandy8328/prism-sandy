"""Unit tests for NO_MATCH KB-grounded LLM policy and helpers."""

from __future__ import annotations

from src.agent.llm_policy import validate_no_match_grounded
from src.agent.no_match_grounded import _materialize, build_grounding_bundle


def test_validate_no_match_strips_unknown_ids() -> None:
    raw = {
        "summary": "Focus on storage path for ORA-27072.",
        "recommended_command_ids": ["kb_ORA-27072", "kb_ORA-99999", "not_an_id"],
    }
    ok, violations, cleaned = validate_no_match_grounded(
        raw,
        allowed_ids={"kb_ORA-27072"},
        observed_codes={"ORA-27072"},
    )
    assert not ok
    assert any("unknown_command_id" in v for v in violations)
    assert cleaned["recommended_command_ids"] == ["kb_ORA-27072"]


def test_validate_summary_invented_ora() -> None:
    raw = {
        "summary": "Likely ORA-99999 from CRS.",
        "recommended_command_ids": [],
    }
    ok, violations, cleaned = validate_no_match_grounded(
        raw,
        allowed_ids=set(),
        observed_codes={"CRS-8500"},
    )
    assert not ok
    assert any("summary_codes_not_in_evidence" in v for v in violations)
    assert cleaned["summary"]


def test_materialize_dedupes_ids() -> None:
    by_id = {
        "kb_ORA-27072": {
            "id": "kb_ORA-27072",
            "ora_code": "ORA-27072",
            "source": "graph",
            "title": "t",
            "commands": ["ls -la"],
        }
    }
    out = _materialize(["kb_ORA-27072", "kb_ORA-27072", "missing"], by_id)
    assert len(out) == 1
    assert out[0]["commands"] == ["ls -la"]


def test_build_grounding_bundle_digest_cap() -> None:
    events = [
        {
            "source_file": "a.log",
            "code": "ORA-27072",
            "code_type": "ORA",
            "layer": "DB",
            "preview": "line",
        }
        for _ in range(5)
    ]
    report = {
        "status": "NO_MATCH",
        "no_match_reason": "test",
        "related_errors": ["ORA-27072"],
        "ora_code": {"code": "ORA-27072"},
    }
    b = build_grounding_bundle(report, events, max_digest_events=2)
    assert len(b["event_digest"]) == 2
    assert b["total_events"] == 5
    assert b["cache_key"] and len(b["cache_key"]) == 64
