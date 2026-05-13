"""
knowledge_store.py
==================
Persists confirmed incident patterns to metadata.duckdb and retrieves
known patterns for future incident matching.

Table: incident_patterns
  incident_id      TEXT PRIMARY KEY
  ora_code         TEXT
  issue_category   TEXT
  rca              TEXT
  confidence_score INTEGER
  risk_score       TEXT
  active_signals   TEXT    (JSON array)
  resolution_cmds  TEXT    (JSON array)
  heatmap          TEXT    (JSON object)
  created_at       TIMESTAMP

Only incidents with confidence_score >= 60 are persisted (HIGH_CONFIDENCE+).
"""

from __future__ import annotations
import json
import os
import yaml
import duckdb
from datetime import datetime, timezone

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "settings.yaml"
)
try:
    with open(_SETTINGS_PATH) as _f:
        _cfg = yaml.safe_load(_f)
    _MIN_CONFIDENCE_TO_STORE = _cfg["thresholds"]["medium_confidence"]   # 60
except Exception:
    _MIN_CONFIDENCE_TO_STORE = 60   # safe fallback

_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "vector_db", "metadata.duckdb"
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS incident_patterns (
    incident_id      VARCHAR PRIMARY KEY,
    ora_code         VARCHAR,
    issue_category   VARCHAR,
    rca              TEXT,
    confidence_score INTEGER,
    risk_score       VARCHAR,
    active_signals   TEXT,
    resolution_cmds  TEXT,
    heatmap          TEXT,
    created_at       TIMESTAMP
);
"""

def _get_conn() -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection and ensure the table exists."""
    db_path = os.path.abspath(_DB_PATH)
    conn = duckdb.connect(db_path)
    conn.execute(_CREATE_TABLE_SQL)
    return conn


def store_incident(
    incident_id:      str,
    ora_code:         str,
    issue_category:   str,
    rca:              str,
    confidence_score: int,
    risk_score:       str,
    active_signals:   list[str],
    resolution_cmds:  list[str],
    heatmap:          dict,
) -> bool:
    """
    Persist an incident pattern to the knowledge store.

    Returns True if stored, False if below confidence threshold.
    """
    if confidence_score < _MIN_CONFIDENCE_TO_STORE:
        return False

    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO incident_patterns
            (incident_id, ora_code, issue_category, rca, confidence_score,
             risk_score, active_signals, resolution_cmds, heatmap, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                ora_code,
                issue_category,
                rca,
                confidence_score,
                risk_score,
                json.dumps(active_signals),
                json.dumps(resolution_cmds),
                json.dumps(heatmap),
                datetime.now(timezone.utc),
            )
        )
        conn.close()
        return True
    except Exception as e:
        print(f"  [KnowledgeStore] Write error: {e}")
        return False


def find_known_pattern(
    ora_code:       str,
    active_signals: list[str],
) -> dict | None:
    """
    Search for a previously stored incident pattern that matches the
    current ORA code and has at least 2 overlapping signals.

    Returns the best matching stored pattern dict, or None.
    """
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT incident_id, ora_code, issue_category, rca,
                   confidence_score, risk_score, active_signals,
                   resolution_cmds, heatmap, created_at
            FROM incident_patterns
            WHERE ora_code = ?
            ORDER BY confidence_score DESC
            LIMIT 10
            """,
            (ora_code,)
        ).fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    current_signals = set(active_signals)
    best_match = None
    best_overlap = 0

    for row in rows:
        stored_signals = set(json.loads(row[6]) if row[6] else [])
        overlap = len(current_signals & stored_signals)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = {
                "incident_id":     row[0],
                "ora_code":        row[1],
                "issue_category":  row[2],
                "rca":             row[3],
                "confidence_score":row[4],
                "risk_score":      row[5],
                "active_signals":  json.loads(row[6]) if row[6] else [],
                "resolution_cmds": json.loads(row[7]) if row[7] else [],
                "heatmap":         json.loads(row[8]) if row[8] else {},
                "created_at":      str(row[9]),
                "signal_overlap":  overlap,
            }

    # Require at least 2 signals overlapping for a match
    if best_match and best_overlap >= 2:
        return best_match
    return None


def list_stored_patterns(limit: int = 20) -> list[dict]:
    """Return most recent stored patterns (for audit/review)."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT incident_id, ora_code, issue_category,
                   confidence_score, risk_score, created_at
            FROM incident_patterns
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        conn.close()
        return [
            {
                "incident_id":     r[0],
                "ora_code":        r[1],
                "issue_category":  r[2],
                "confidence_score":r[3],
                "risk_score":      r[4],
                "created_at":      str(r[5]),
            }
            for r in rows
        ]
    except Exception:
        return []
