"""
Post-LLM policy guardrails.

The advisory output can never introduce entities outside deterministic evidence.
"""

from __future__ import annotations

import re
from typing import Any

from src.agent.llm_schema import LlmAdvisoryOutput


_CODE_TOKEN = re.compile(r"\b[A-Z]{2,12}-\d{4,5}\b")


def validate_llm_advisory(
    advisory: LlmAdvisoryOutput,
    *,
    allowed_candidates: set[str],
    allowed_codes: set[str],
    can_confirm: bool = False,
) -> tuple[bool, list[str]]:
    violations: list[str] = []

    if advisory.selected_hypothesis not in allowed_candidates:
        violations.append("selected_hypothesis not in deterministic candidates")

    invented: set[str] = set()
    scan_fields = [advisory.rationale] + advisory.rejected_hypotheses
    for line in scan_fields:
        for token in _CODE_TOKEN.findall((line or "").upper()):
            if token not in allowed_codes:
                invented.add(token)
    if invented:
        violations.append(f"invented codes: {sorted(invented)}")

    if advisory.confidence_band == "high" and not can_confirm:
        violations.append("high confidence not allowed under current deterministic gates")

    return (len(violations) == 0), violations


def advisory_to_dict(advisory: LlmAdvisoryOutput, *, policy_ok: bool, violations: list[str]) -> dict[str, Any]:
    return {
        "selected_hypothesis": advisory.selected_hypothesis,
        "confidence_band": advisory.confidence_band,
        "rationale": advisory.rationale,
        "rejected_hypotheses": advisory.rejected_hypotheses,
        "next_commands": advisory.next_commands,
        "needs_more_evidence": advisory.needs_more_evidence,
        "policy_passed": policy_ok,
        "violations": violations,
    }

