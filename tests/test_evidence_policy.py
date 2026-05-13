from src.agent.report_builder import build_report


def _base_best(pattern="FC_HBA_RESET", score=92.7, label="HIGH"):
    return {
        "pattern_id": pattern,
        "device": "0000:04:00.0",
        "score": score,
        "label": label,
        "breakdown": {"keyword": 40, "bm25": 30, "dense": 12.7, "temporal": 10},
    }


def _base_root(pattern="FC_HBA_RESET", ora="ORA-27072"):
    return {
        "root_pattern": pattern,
        "category": "DISK",
        "severity": "CRITICAL",
        "fixes": [],
        "causal_chain": [f"OS: {pattern}", f"DB: {ora}"],
        "related_ora_codes": [],
    }


def _base_parsed():
    return {
        "mode": "log_paste",
        "query": "sample",
        "primary_ora": "ORA-27072",
        "all_ora_codes": ["ORA-27072", "ORA-00353", "ORA-15080"],
        "hostname": "dbhost07",
        "timestamp_str": "2024-03-16T07:08:10+00:00",
        "platform": "LINUX",
        "observed_layers": ["DB", "OS"],
        "direct_pattern_ids": ["FC_HBA_RESET"],
        "nl_ora_hints": [],
        "raw_input": "ORA-27072 ...",
    }


def test_storage_path_requires_infra_before_finalize():
    parsed = _base_parsed()
    report = build_report(
        parsed_input=parsed,
        best_candidate=_base_best(),
        root_cause_chain=_base_root(),
        fused_results=[],
        cascades=[],
        processing_ms=10.0,
    )
    assert report["status"] == "NO_MATCH"
    assert "needs infra evidence" in report["no_match_reason"].lower()


def test_storage_path_can_finalize_with_infra_corroboration():
    parsed = _base_parsed()
    parsed["observed_layers"] = ["DB", "OS", "INFRA"]
    report = build_report(
        parsed_input=parsed,
        best_candidate=_base_best(),
        root_cause_chain=_base_root(),
        fused_results=[{"payload": {"chunk_id": "c1", "log_source": "VAR_LOG_MESSAGES"}}],
        cascades=[],
        processing_ms=10.0,
    )
    assert report["status"] == "SUCCESS"
    assert report["root_cause"]["pattern"] == "FC_HBA_RESET"
    # Related errors come only from evidence ORAs, not graph expansion.
    assert set(report["related_errors"]) == {"ORA-00353", "ORA-15080"}


def test_pattern_not_in_uploaded_evidence_blocks_finalize():
    parsed = _base_parsed()
    parsed["observed_layers"] = ["DB", "OS", "INFRA"]
    parsed["direct_pattern_ids"] = ["EXA_FLASH_FAIL"]
    report = build_report(
        parsed_input=parsed,
        best_candidate=_base_best(pattern="FC_HBA_RESET"),
        root_cause_chain=_base_root(pattern="FC_HBA_RESET"),
        fused_results=[],
        cascades=[],
        processing_ms=10.0,
    )
    assert report["status"] == "NO_MATCH"
    assert "not found in the uploaded" in report["no_match_reason"].lower()


def test_no_match_related_errors_are_evidence_only():
    parsed = _base_parsed()
    report = build_report(
        parsed_input=parsed,
        best_candidate=None,
        root_cause_chain=None,
        fused_results=[],
        cascades=[],
        processing_ms=5.0,
    )
    assert report["status"] == "NO_MATCH"
    assert set(report["related_errors"]) == {"ORA-00353", "ORA-15080"}


def test_report_prefers_root_chain_pattern_over_best_candidate_pattern():
    parsed = _base_parsed()
    parsed["observed_layers"] = ["DB", "OS", "INFRA"]
    report = build_report(
        parsed_input=parsed,
        best_candidate=_base_best(pattern="FC_HBA_RESET"),
        root_cause_chain=_base_root(pattern="EXA_FLASH_FAIL"),
        fused_results=[{"payload": {"chunk_id": "c1", "log_source": "VAR_LOG_MESSAGES"}}],
        cascades=[{"cascade_id": "c", "root_pattern": "FC_HBA_RESET", "sequence": [], "match_pct": 80.0}],
        processing_ms=5.0,
    )
    assert report["status"] == "SUCCESS"
    assert report["root_cause"]["pattern"] == "STORAGE_FLASH_IO_OR_MEDIA_FAILURE"
    # For log_paste, cascade info should not contradict selected evidence root.
    assert report["cascade"] is None


def test_success_includes_db_and_infra_layer_fixes_when_applicable():
    parsed = _base_parsed()
    parsed["observed_layers"] = ["DB", "OS", "INFRA"]
    parsed["direct_pattern_ids"] = ["EXA_FLASH_FAIL"]
    parsed["all_ora_codes"] = ["ORA-27072", "ORA-00353", "ORA-00312", "ORA-15080", "ORA-15130"]
    report = build_report(
        parsed_input=parsed,
        best_candidate=_base_best(pattern="EXA_FLASH_FAIL"),
        root_cause_chain={
            "root_pattern": "EXA_FLASH_FAIL",
            "category": "DISK",
            "severity": "CRITICAL",
            "fixes": [],
            "causal_chain": ["ROOT: EXA_FLASH_FAIL", "DB: ORA-27072", "DB: ORA-00353"],
            "related_ora_codes": [],
        },
        fused_results=[{"payload": {"chunk_id": "c1", "log_source": "CELL_ALERT_LOG"}}],
        cascades=[],
        processing_ms=5.0,
    )
    assert report["status"] == "SUCCESS"
    fix_ids = [f["fix_id"] for f in report["fixes"]]
    assert "INFRA_LAYER_STORAGE_VALIDATION" in fix_ids
    assert "DB_LAYER_RECOVERY_VALIDATION" in fix_ids


def test_db_redo_triangle_preserved_as_needs_more_info_not_unknown():
    """DB-only redo chain: correlation hypothesis must survive legacy NO_MATCH gates."""
    from src.agent.event_correlation import build_event_correlation_analysis

    text = """
ORA-27072: file I/O error
ORA-00353: log corruption near block 1
ORA-00312: online log 1 thread 1: '/redo01.log'
""".strip()
    parsed = {
        "mode": "log_paste",
        "query": "x",
        "primary_ora": "ORA-27072",
        "all_ora_codes": ["ORA-27072", "ORA-00353", "ORA-00312"],
        "hostname": "db01",
        "timestamp_str": "",
        "platform": "LINUX",
        "observed_layers": ["DB"],
        "direct_pattern_ids": [],
        "raw_input": text,
    }
    rca = build_event_correlation_analysis(parsed, [], None, None)
    assert rca["root_cause_candidate"]["root_cause"] == "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE"
    report = build_report(
        parsed_input=parsed,
        best_candidate=None,
        root_cause_chain=None,
        fused_results=[],
        cascades=[],
        processing_ms=1.0,
        event_analysis=rca,
    )
    assert report["status"] == "NEEDS_MORE_INFO"
    assert report["root_cause"]["pattern"] == "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE"
    rc = (report.get("rca_framework") or {}).get("root_cause_candidate") or {}
    assert rc.get("root_cause") == "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE"
