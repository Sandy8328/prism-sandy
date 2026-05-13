"""
Structured schema for LLM advisory integration.

Deterministic engines remain authoritative; this schema is for constrained
advisory reasoning only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CandidateHypothesis:
    pattern_id: str
    score: float
    supporting_codes: list[str] = field(default_factory=list)
    contradicting_codes: list[str] = field(default_factory=list)


@dataclass
class LlmAdvisoryInput:
    incident_id: str
    candidates: list[CandidateHypothesis]
    observed_codes: list[str]
    observed_layers: list[str]
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class LlmAdvisoryOutput:
    selected_hypothesis: str
    confidence_band: str
    rationale: str
    rejected_hypotheses: list[str] = field(default_factory=list)
    next_commands: list[str] = field(default_factory=list)
    needs_more_evidence: list[str] = field(default_factory=list)


def parse_llm_advisory_output(payload: dict[str, Any]) -> LlmAdvisoryOutput:
    """
    Parse LLM JSON object into a typed advisory output.
    Raises ValueError on malformed payload.
    """
    if not isinstance(payload, dict):
        raise ValueError("LLM payload must be a JSON object")

    selected = str(payload.get("selected_hypothesis") or "").strip()
    confidence = str(payload.get("confidence_band") or "").strip().lower()
    rationale = str(payload.get("rationale") or "").strip()
    if not selected:
        raise ValueError("Missing selected_hypothesis")
    if confidence not in {"low", "medium", "high"}:
        raise ValueError("confidence_band must be low|medium|high")
    if not rationale:
        raise ValueError("Missing rationale")

    def _str_list(v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("Expected list")
        return [str(x).strip() for x in v if str(x).strip()]

    return LlmAdvisoryOutput(
        selected_hypothesis=selected,
        confidence_band=confidence,
        rationale=rationale,
        rejected_hypotheses=_str_list(payload.get("rejected_hypotheses")),
        next_commands=_str_list(payload.get("next_commands")),
        needs_more_evidence=_str_list(payload.get("needs_more_evidence")),
    )

