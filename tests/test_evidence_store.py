"""Persistence into evidence-first DuckDB schema."""

import pytest

from src.persistence import evidence_store as evidence_store_mod
from src.persistence.evidence_store import persist_evidence_first_diagnosis


def test_db_path_rejects_same_file_as_retrieval_metadata(tmp_path, monkeypatch):
    meta = tmp_path / "metadata.duckdb"
    meta.write_bytes(b"")

    def fake_cfg():
        return {
            "duckdb": {"db_path": str(meta)},
            "evidence_store": {"db_path": str(meta), "enabled": True},
        }

    monkeypatch.setattr(evidence_store_mod, "_cfg", fake_cfg)
    with pytest.raises(ValueError, match="evidence_store.db_path"):
        evidence_store_mod._db_path(None)
    with pytest.raises(ValueError, match="evidence_store.db_path"):
        evidence_store_mod._db_path(str(meta))


def test_persist_evidence_first_diagnosis_tmp_file(tmp_path):
    dbf = tmp_path / "evidence.duckdb"
    parsed = {
        "mode": "log_paste",
        "query": "test",
        "primary_ora": "ORA-27072",
        "all_ora_codes": ["ORA-27072"],
        "hostname": "db01",
        "timestamp_str": "",
        "platform": "LINUX",
        "raw_input": "ORA-27072: I/O error",
    }
    ev = {
        "event_id": "ev_test_1",
        "timestamp": "2024-03-16T07:08:10+00:00",
        "timestamp_raw": "2024-03-16T07:08:10+00:00",
        "source_file": "alert.log",
        "source_path": "alert.log",
        "line_number": 10,
        "layer": "DB",
        "code": "ORA-27072",
        "code_type": "ORA",
        "preview": "ORA-27072",
        "parser_name": "test_parser",
        "details": {},
        "tags": [],
    }
    report = {
        "status": "NEEDS_MORE_INFO",
        "root_cause": {"pattern": "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE"},
        "confidence": {"score": 55.0, "explanation": "test"},
        "rca_framework": {
            "executive_summary": "summary",
            "correlation_model_score": 55.0,
            "root_cause_evidence_status": "SUSPECTED",
            "root_cause_candidate": {
                "root_cause": "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE",
                "layer": "DB",
                "status": "SUSPECTED",
                "correlation_score": 55.0,
                "why_deepest_supported": "why",
                "what_would_change_conclusion": "what",
            },
            "additional_evidence_needed": ["syslog"],
        },
        "related_errors": [],
        "fixes": [],
        "normalized_event_count": 1,
        "normalized_events": [ev],
        "processing_ms": 12.0,
    }
    ids = persist_evidence_first_diagnosis(
        parsed_input=parsed,
        report=report,
        source_summary={"source_type": "pasted_text"},
        incident_id="inc_unit_test",
        db_path=str(dbf),
    )
    assert ids["incident_id"] == "inc_unit_test"
    assert ids["correlation_run_id"]

    import duckdb

    con = duckdb.connect(ids["db_path"])
    n = con.execute("SELECT COUNT(*) FROM normalized_event WHERE incident_id = ?", ["inc_unit_test"]).fetchone()[0]
    assert n == 1
    r = con.execute("SELECT status FROM report_snapshot WHERE incident_id = ?", ["inc_unit_test"]).fetchone()[0]
    assert r == "NEEDS_MORE_INFO"
    con.close()
