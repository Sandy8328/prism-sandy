"""
Post-LLM policy guardrails.

The advisory output can never introduce entities outside deterministic evidence.
"""

from __future__ import annotations

import re
from typing import Any

from src.agent.llm_schema import LlmAdvisoryOutput


_CODE_TOKEN = re.compile(r"\b[A-Z]{2,12}-\d{4,5}\b")

_NO_MATCH_CODE_TOKEN = re.compile(
    r"\b(?:ORA|CRS|IPC|TNS|DRG|OCR|ONS|CLSR|EVM|CSS|CRSD|GIPC)-\d+(?::\d+)?\b",
    re.I,
)


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


def validate_no_match_grounded(
    raw: dict[str, Any] | Any,
    *,
    allowed_ids: set[str],
    observed_codes: set[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    """
    Strip unknown command IDs; flag summary tokens not present in deterministic observed_codes.
    """
    violations: list[str] = []
    if not isinstance(raw, dict):
        return False, ["response_not_object"], {"summary": "", "recommended_command_ids": []}

    summary = str(raw.get("summary") or "")[:800]
    ids_raw = raw.get("recommended_command_ids")
    if not isinstance(ids_raw, list):
        violations.append("recommended_command_ids_not_list")
        ids_raw = []

    clean_ids: list[str] = []
    seen: set[str] = set()
    for x in ids_raw:
        sx = str(x).strip()
        if not sx:
            continue
        if sx in allowed_ids:
            if sx not in seen:
                seen.add(sx)
                clean_ids.append(sx)
        else:
            violations.append(f"unknown_command_id:{sx}")

    invented: set[str] = set()
    for tok in _NO_MATCH_CODE_TOKEN.findall(summary.upper()):
        if tok not in observed_codes:
            invented.add(tok)
    if invented:
        violations.append(f"summary_codes_not_in_evidence:{sorted(invented)}")

    ok = len(violations) == 0
    return ok, violations, {"summary": summary, "recommended_command_ids": clean_ids}

