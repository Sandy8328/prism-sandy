"""
Persist diagnosis runs into the evidence-first DuckDB schema (sql/evidence_first/).

Flow: incident_case → source_bundle → source_file → parser_run → normalized_event
      → correlation_run → rca_candidate → report_snapshot

Enable in config/settings.yaml: evidence_store.enabled: true
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "sql" / "evidence_first" / "evidence_first_schema.duckdb.sql"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    out = json.dumps(v, ensure_ascii=True, default=str, allow_nan=False)
    return out.replace("\x00", "")


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return v


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def _sql_text(s: Any, max_len: int) -> str:
    t = str(s).replace("\x00", "")
    return t[:max_len]


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _cfg() -> dict[str, Any]:
    import yaml

    p = PROJECT_ROOT / "config" / "settings.yaml"
    try:
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _retrieval_duckdb_path() -> Path | None:
    raw = ((_cfg().get("duckdb") or {}) or {}).get("db_path")
    if not raw:
        return None
    p = Path(str(raw))
    return p if p.is_absolute() else PROJECT_ROOT / p


def _db_path(override: str | None) -> Path:
    if override:
        p = Path(override)
        out = p if p.is_absolute() else PROJECT_ROOT / p
    else:
        raw = ((_cfg().get("evidence_store") or {}) or {}).get("db_path") or "./data/duckdb/evidence_store.duckdb"
        p = Path(str(raw))
        out = p if p.is_absolute() else PROJECT_ROOT / p

    retrieval = _retrieval_duckdb_path()
    if retrieval is not None:
        try:
            same = out.resolve() == retrieval.resolve()
        except OSError:
            same = False
        if same:
            raise ValueError(
                "evidence_store.db_path must not be the same file as duckdb.db_path (retrieval metadata). "
                "The metadata database is opened read-only for search and cannot hold evidence-first DDL. "
                "Use a separate path such as ./data/duckdb/evidence_store.duckdb and apply "
                "sql/evidence_first/evidence_first_schema.duckdb.sql (not evidence_first_schema.postgresql.sql)."
            )
    return out


def ensure_evidence_schema(conn: Any) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.execute(sql)


def _infer_bundle_type(source_summary: dict[str, Any] | None) -> str:
    s = source_summary or {}
    st = str(s.get("source_type") or "").lower()
    if "paste" in st or st == "pasted_text":
        return "PASTE"
    if st == "multi_log":
        return "MULTI_FILE"
    if "zip" in st or st == "ahf_zip":
        return "AHF_ZIP"
    return "FILE"


def _details_merge(ev: dict[str, Any]) -> dict[str, Any]:
    d = ev.get("details")
    out: dict[str, Any] = dict(d) if isinstance(d, dict) else {}
    for k in ("parser_name", "mapped_code_hint", "source_type"):
        if ev.get(k) is not None:
            out[k] = ev[k]
    return out


def _normalized_row(
    ev: dict[str, Any],
    *,
    incident_id: str,
    bundle_id: str,
    source_id: str,
    parser_run_id: str,
) -> tuple[Any, ...]:
    raw = ev.get("raw") or ""
    rh = ev.get("raw_hash") or (hashlib.sha256(str(raw).encode()).hexdigest()[:32] if raw else None)
    details = _json(_details_merge(ev))
    tags = _json(ev.get("tags"))
    return (
        ev.get("event_id") or f"ev_{uuid.uuid4().hex[:16]}",
        incident_id,
        bundle_id,
        source_id,
        parser_run_id,
        _parse_ts(ev.get("timestamp")),
        ev.get("timestamp_raw"),
        ev.get("timestamp_confidence"),
        ev.get("source_file"),
        ev.get("source_path"),
        ev.get("line_number"),
        ev.get("line_start"),
        ev.get("line_end"),
        ev.get("host"),
        ev.get("platform"),
        ev.get("database"),
        ev.get("instance"),
        ev.get("layer"),
        ev.get("component"),
        ev.get("process"),
        ev.get("pid"),
        ev.get("thread"),
        ev.get("code"),
        ev.get("code_type"),
        ev.get("message"),
        ev.get("severity"),
        ev.get("role_hint"),
        ev.get("failure_family"),
        ev.get("object_type"),
        ev.get("object_name"),
        ev.get("file_path"),
        ev.get("trace_file"),
        ev.get("device"),
        ev.get("multipath_device"),
        ev.get("diskgroup"),
        ev.get("asm_group"),
        ev.get("asm_disk"),
        ev.get("asm_file"),
        ev.get("au"),
        ev.get("offset"),
        ev.get("block"),
        ev.get("size"),
        ev.get("redo_group"),
        ev.get("redo_thread"),
        ev.get("redo_sequence"),
        ev.get("os_errno"),
        ev.get("linux_error"),
        ev.get("cell"),
        ev.get("flash_disk"),
        ev.get("cell_disk"),
        ev.get("grid_disk"),
        ev.get("crs_resource"),
        rh,
        raw if isinstance(raw, str) else str(raw),
        ev.get("preview"),
        ev.get("parse_confidence"),
        ev.get("evidence_state"),
        ev.get("row_kind"),
        details,
        tags,
        _utcnow(),
    )


_NORM_SQL = """
INSERT INTO normalized_event (
  event_id, incident_id, bundle_id, source_id, parser_run_id,
  ts, timestamp_raw, timestamp_confidence,
  source_file, source_path, line_number, line_start, line_end,
  host, platform, database_name, instance_name,
  layer, component, process, pid, thread,
  code, code_type, message, severity, role_hint, failure_family,
  object_type, object_name, file_path, trace_file,
  device, multipath_device, diskgroup,
  asm_group, asm_disk, asm_file, au, offset_value, block_value, size_value,
  redo_group, redo_thread, redo_sequence,
  os_errno, linux_error,
  cell, flash_disk, cell_disk, grid_disk, crs_resource,
  raw_hash, raw, preview, parse_confidence, evidence_state, row_kind,
  details, tags, created_at
) VALUES (
  ?, ?, ?, ?, ?,
  ?, ?, ?,
  ?, ?, ?, ?, ?,
  ?, ?, ?, ?,
  ?, ?, ?, ?, ?,
  ?, ?, ?, ?, ?, ?,
  ?, ?, ?, ?,
  ?, ?, ?,
  ?, ?, ?, ?, ?, ?, ?,
  ?, ?, ?,
  ?, ?,
  ?, ?, ?, ?, ?,
  ?, ?, ?, ?, ?, ?,
  CAST(? AS JSON), CAST(? AS JSON), ?
)
"""


def persist_evidence_first_diagnosis(
    *,
    parsed_input: dict[str, Any],
    report: dict[str, Any],
    source_summary: dict[str, Any] | None = None,
    incident_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, str]:
    """
    Write one diagnosis run: evidence rows + one correlation_run + primary rca_candidate + report_snapshot.

    Does not write event_pattern_match / edges / cascade_step / recommended_action (extend later).
    """
    import duckdb

    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    inc = incident_id or f"inc_{uuid.uuid4().hex[:12]}"
    bundle_id = f"bun_{uuid.uuid4().hex[:12]}"
    source_id = f"src_{uuid.uuid4().hex[:12]}"
    parser_run_id = f"pr_{uuid.uuid4().hex[:12]}"
    correlation_run_id = f"cr_{uuid.uuid4().hex[:12]}"
    candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
    report_id = f"rep_{uuid.uuid4().hex[:12]}"

    evs: list[dict[str, Any]] = list(report.get("normalized_events") or [])
    rca = dict(report.get("rca_framework") or {})
    rc = dict(rca.get("root_cause_candidate") or {})
    now = _utcnow()

    title = _sql_text(parsed_input.get("primary_ora") or parsed_input.get("query") or "diagnosis", 500)
    status_top = str(report.get("status") or "UNKNOWN")
    root_pat = _sql_text((report.get("root_cause") or {}).get("pattern") or rc.get("root_cause") or "", 4000)
    score = _safe_float((report.get("confidence") or {}).get("score") or rc.get("correlation_score"), 0.0)
    rca_status = _sql_text(rca.get("root_cause_evidence_status") or rc.get("status") or "UNKNOWN", 128)

    observed_layers = sorted({(e.get("layer") or "UNKNOWN").upper() for e in evs if (e.get("layer") or "").strip()})
    oras = list(dict.fromkeys(parsed_input.get("all_ora_codes") or []))
    non_ora = sorted(
        {
            (e.get("code") or "").strip()
            for e in evs
            if (e.get("code") or "").strip() and str(e.get("code_type") or "").upper() != "ORA"
        }
    )[:200]

    bundle_type = _infer_bundle_type(source_summary)
    ingest = report.get("ingest_diagnostics") or {}
    summ = source_summary or {}

    conn = duckdb.connect(str(path))
    try:
        ensure_evidence_schema(conn)
        conn.execute("BEGIN TRANSACTION")

        conn.execute(
            """
            INSERT OR REPLACE INTO incident_case (
              incident_id, title, status, created_at, updated_at,
              user_id, environment, db_name, instance_name, primary_host, platform,
              current_rca_status, current_root_cause, current_score, tags, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), ?)
            """,
            [
                inc,
                title,
                "OPEN",
                now,
                now,
                None,
                "unknown",
                parsed_input.get("primary_ora") or None,
                None,
                parsed_input.get("hostname") or None,
                parsed_input.get("platform") or None,
                rca_status,
                root_pat,
                score,
                _json({"source_summary": summ}),
                None,
            ],
        )

        conn.execute(
            """
            INSERT INTO source_bundle (
              bundle_id, incident_id, bundle_type, original_name, uploaded_at,
              sha256, size_bytes, storage_uri, accepted, rejection_reason,
              ingest_diagnostics, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), CAST(? AS JSON))
            """,
            [
                bundle_id,
                inc,
                bundle_type,
                (
                    summ.get("zip_path")
                    or summ.get("source_file")
                    or (
                        summ["sources"][0]
                        if isinstance(summ.get("sources"), list) and summ.get("sources")
                        else None
                    )
                    or "upload"
                ),
                now,
                None,
                None,
                None,
                True,
                None,
                _json(ingest),
                _json({"source_summary": summ}),
            ],
        )

        src_label = str(
            summ.get("source_path")
            or summ.get("source_file")
            or summ.get("zip_path")
            or "uploaded_input"
        )[:2000]
        conn.execute(
            """
            INSERT INTO source_file (
              source_id, bundle_id, incident_id, source_file, source_path, internal_zip_path,
              source_type, detected_layer, host, db_name, instance_name,
              sha256, size_bytes, line_count, parse_status, skip_reason,
              storage_uri, raw_stored, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON))
            """,
            [
                source_id,
                bundle_id,
                inc,
                Path(src_label).name[:512],
                src_label[:4000],
                None,
                str(summ.get("source_type") or "unknown")[:64],
                (observed_layers[0] if observed_layers else "UNKNOWN"),
                parsed_input.get("hostname"),
                None,
                None,
                None,
                None,
                len(evs),
                "PARSED",
                None,
                None,
                False,
                now,
                _json({"parsed_input_mode": parsed_input.get("mode")}),
            ],
        )

        conn.execute(
            """
            INSERT INTO parser_run (
              parser_run_id, incident_id, source_id, parser_name, parser_version, schema_version,
              started_at, finished_at, duration_ms, status, event_count, warning_count, error_message, diagnostics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON))
            """,
            [
                parser_run_id,
                inc,
                source_id,
                "evidence_first_unified",
                "1",
                "normalized_event_v1",
                now,
                now,
                _safe_int(report.get("processing_ms"), 0),
                "SUCCESS",
                len(evs),
                0,
                None,
                _json({"normalized_event_count": len(evs)}),
            ],
        )

        rows = [_normalized_row(e, incident_id=inc, bundle_id=bundle_id, source_id=source_id, parser_run_id=parser_run_id) for e in evs]
        if rows:
            conn.executemany(_NORM_SQL, rows)

        run_row = conn.execute(
            "SELECT COALESCE(MAX(run_number), 0) + 1 FROM correlation_run WHERE incident_id = ?",
            [inc],
        ).fetchone()
        run_number = int(run_row[0]) if run_row else 1

        conn.execute(
            """
            INSERT INTO correlation_run (
              correlation_run_id, incident_id, run_number, correlation_version,
              started_at, finished_at, duration_ms, event_count, source_count,
              observed_layers, observed_ora_codes, observed_non_ora_codes,
              correlation_model_score, root_cause_evidence_status,
              retrieval_confidence, retrieval_note, summary, diagnostics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), CAST(? AS JSON), CAST(? AS JSON), ?, ?, ?, ?, ?, CAST(? AS JSON))
            """,
            [
                correlation_run_id,
                inc,
                run_number,
                "event_correlation_v1",
                now,
                now,
                _safe_int(report.get("processing_ms"), 0),
                len(evs),
                1,
                _json(observed_layers),
                _json(oras),
                _json(non_ora),
                _safe_float(rca.get("correlation_model_score"), 0.0),
                rca_status,
                None,
                None,
                _sql_text(rca.get("executive_summary") or "", 8000),
                _json({"report_status": status_top}),
            ],
        )

        conn.execute(
            """
            INSERT INTO rca_candidate (
              candidate_id, correlation_run_id, incident_id, rank,
              root_cause, root_layer, status, score,
              why_this_candidate, what_would_change,
              evidence_event_ids, missing_evidence, is_selected, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), CAST(? AS JSON), ?, CAST(? AS JSON))
            """,
            [
                candidate_id,
                correlation_run_id,
                inc,
                1,
                rc.get("root_cause"),
                rc.get("layer"),
                rc.get("status"),
                _safe_float(rc.get("correlation_score"), 0.0),
                _sql_text(rc.get("why_deepest_supported") or "", 16000),
                _sql_text(rc.get("what_would_change_conclusion") or "", 8000),
                _json([e.get("event_id") for e in evs if e.get("event_id")][:500]),
                _json(rca.get("additional_evidence_needed") or []),
                True,
                _json({"source": "root_cause_candidate"}),
            ],
        )

        report_blob = {
            "status": report.get("status"),
            "root_cause": report.get("root_cause"),
            "confidence": report.get("confidence"),
            "rca_framework": rca,
            "related_errors": report.get("related_errors"),
            "fixes": report.get("fixes"),
            "normalized_event_count": report.get("normalized_event_count"),
            "source_summary": summ,
        }
        conn.execute(
            """
            INSERT INTO report_snapshot (
              report_id, incident_id, correlation_run_id, report_version, status, title,
              executive_summary, root_cause_summary, confidence_summary,
              report_json, report_markdown, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), ?, ?)
            """,
            [
                report_id,
                inc,
                correlation_run_id,
                "report_builder_v1",
                status_top,
                _sql_text(title, 2000),
                _sql_text(rca.get("executive_summary") or "", 8000),
                _sql_text(root_pat, 4000),
                _sql_text((report.get("confidence") or {}).get("explanation") or "", 8000),
                _json(report_blob),
                None,
                now,
            ],
        )

        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return {
        "incident_id": inc,
        "bundle_id": bundle_id,
        "source_id": source_id,
        "parser_run_id": parser_run_id,
        "correlation_run_id": correlation_run_id,
        "rca_candidate_id": candidate_id,
        "report_id": report_id,
        "db_path": str(path),
    }


__all__ = ["persist_evidence_first_diagnosis", "ensure_evidence_schema", "PROJECT_ROOT", "SCHEMA_PATH"]
