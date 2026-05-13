from src.agent.llm_policy import validate_llm_advisory
from src.agent.llm_schema import parse_llm_advisory_output


def test_llm_policy_accepts_valid_output():
    advisory = parse_llm_advisory_output(
        {
            "selected_hypothesis": "EXA_FLASH_FAIL",
            "confidence_band": "medium",
            "rationale": "Observed ORA-27072 and storage-cell error signals.",
            "rejected_hypotheses": ["FC_HBA_RESET had weaker support"],
            "next_commands": ["iostat -xz 1 5"],
            "needs_more_evidence": ["cell metric history"],
        }
    )
    ok, violations = validate_llm_advisory(
        advisory,
        allowed_candidates={"EXA_FLASH_FAIL", "FC_HBA_RESET"},
        allowed_codes={"ORA-27072", "ORA-00353", "FC_HBA_RESET"},
        can_confirm=False,
    )
    assert ok
    assert violations == []


def test_llm_policy_rejects_invented_code_and_candidate():
    advisory = parse_llm_advisory_output(
        {
            "selected_hypothesis": "MADE_UP_PATTERN",
            "confidence_band": "high",
            "rationale": "Root cause is ORA-99999 and hidden issue.",
            "rejected_hypotheses": [],
            "next_commands": [],
            "needs_more_evidence": [],
        }
    )
    ok, violations = validate_llm_advisory(
        advisory,
        allowed_candidates={"EXA_FLASH_FAIL"},
        allowed_codes={"ORA-27072"},
        can_confirm=False,
    )
    assert not ok
    assert any("selected_hypothesis" in v for v in violations)
    assert any("invented codes" in v for v in violations)
    assert any("high confidence" in v for v in violations)

