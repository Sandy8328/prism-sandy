"""Unit tests for RAG remediation index validation (no Gemini)."""

from src.agent.rag_remediation_outline import _validate_indices


def test_validate_indices_dedupes_and_bounds():
    raw = {"summary": "Pick A then B", "indices": [0, 0, 1, 99, -1, "2", "x", 3]}
    ix, summary = _validate_indices(raw, pool_len=4)
    assert summary == "Pick A then B"
    assert ix == [0, 1, 2, 3]


def test_validate_indices_caps_at_fourteen():
    raw = {"summary": "s", "indices": list(range(30))}
    ix, _ = _validate_indices(raw, pool_len=30)
    assert len(ix) == 14
    assert ix == list(range(14))


def test_validate_indices_missing_indices():
    raw = {"summary": "Nothing fits", "indices": None}
    ix, summary = _validate_indices(raw, pool_len=5)
    assert ix == []
    assert summary == "Nothing fits"
