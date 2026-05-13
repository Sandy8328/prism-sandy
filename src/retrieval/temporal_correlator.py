"""
temporal_correlator.py — Links chunks from different log sources within a time window.

Purpose:
  If alert.log shows ORA-27072 at 02:44:19 on dbhost01,
  and /var/log/messages shows SCSI_DISK_TIMEOUT at 02:44:16 on same host,
  → these are the SAME incident. Temporal correlator finds and links them.

Time window: ±60 seconds (from chunking_rules.md)
Same host: hostname must match
Different log sources: links alert.log ↔ syslog ↔ CRS ↔ dmesg

Outputs a temporal_bonus score (+10 points) added to confidence when
multiple log sources agree on the same time window and host.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from dateutil import parser as dp
import duckdb
import yaml

from src.pipeline.topology import TopologyMap

# ── Config ──────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    _cfg = yaml.safe_load(f)

DUCKDB_PATH          = _cfg["duckdb"]["db_path"]
TIME_WINDOW_S        = _cfg["chunking"]["time_window_sec"]      # 60 seconds
TEMPORAL_BONUS       = _cfg["scoring"]["temporal_bonus"]         # 10
DOMINO_LOOKBACK_HRS  = _cfg["retrieval"]["domino_lookback_hours"]  # 24 hours
CASCADE_WINDOW_SEC   = _cfg["retrieval"]["cascade_window_sec"]     # 300 seconds


def _parse_ts(ts_val) -> datetime | None:
    """Parse timestamp from string or datetime."""
    if ts_val is None:
        return None
    if isinstance(ts_val, datetime):
        return ts_val
    try:
        return dp.parse(str(ts_val))
    except Exception:
        return None


def find_correlated_chunks(
    reference_chunks: list[dict],
    time_window_sec: int = TIME_WINDOW_S,
    drift_offset_sec: int = 0,
) -> dict[str, list[dict]]:
    """
    For each reference chunk, find other chunks from DIFFERENT log sources
    on the SAME host within the time window.

    Args:
        reference_chunks: List of payload dicts from Qdrant results

    Returns:
        Dict mapping chunk_id → list of correlated chunk payloads
    """
    if not reference_chunks:
        return {}

    correlations: dict[str, list[dict]] = {}

    # Group reference chunks by (hostname, time_range)
    conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    topology = TopologyMap()

    for chunk in reference_chunks:
        chunk_id  = chunk.get("chunk_id")
        hostname  = chunk.get("hostname")
        ts_start  = _parse_ts(chunk.get("timestamp_start"))
        log_src   = chunk.get("log_source")

        if not chunk_id or not hostname or not ts_start:
            correlations[chunk_id] = []
            continue

        # [Edge Case 3: Time Drift Offset]
        # Adjust the reference timestamp by the calculated drift between OS and DB time.
        # This aligns the correlation window accurately even if clocks are out of sync.
        adjusted_ts_start = ts_start + timedelta(seconds=drift_offset_sec)

        ts_low  = (adjusted_ts_start - timedelta(seconds=time_window_sec)).isoformat()
        ts_high = (adjusted_ts_start + timedelta(seconds=time_window_sec)).isoformat()

        # [Edge Cases 1 & 2: Cross-Node RAC & Exadata Architecture]
        # Allow correlation across sibling nodes (e.g. cell01 <-> dbnode01)
        connected_hosts = topology.get_all_connected_hosts(hostname)
        placeholders = ','.join(['?'] * len(connected_hosts))
        
        # [Edge Case 10: Domino Delay / Stateful Cascade Memory]
        # Infrastructure failures (Disk/Network) persist until recovered. We look backwards
        # 24 hours for these stateful drops, overriding the strict 60s window.
        ts_domino_low = (adjusted_ts_start - timedelta(hours=DOMINO_LOOKBACK_HRS)).isoformat()
        
        # [Edge Case 30: Coincidental Outage / Independent Layer Rule]
        # Do not link physical infrastructure failures to purely logical application errors.
        logical_ora_codes = {"ORA-00942", "ORA-01031", "ORA-01403", "ORA-00001"}
        is_logical_error = chunk.get("ora_code") in logical_ora_codes
        
        try:
            params = connected_hosts + [log_src, ts_low, ts_high, ts_domino_low, adjusted_ts_start.isoformat()]
            
            # Query combines the strict 60s window (for general events)
            # WITH a 24-hour lookback ONLY for stateful infrastructure errors (OS/DISK/NETWORK/CRS)
            query = f"""
                SELECT chunk_id, log_source, timestamp_start,
                       category, severity, ora_code, os_pattern, raw_text
                FROM chunks
                WHERE hostname IN ({placeholders})
                  AND log_source != ?
                  AND severity IN ('CRITICAL', 'ERROR')
                  AND (
                      (timestamp_start BETWEEN ? AND ?)
                      OR
                      (category IN ('OS', 'DISK', 'NETWORK', 'CRS') AND timestamp_start BETWEEN ? AND ?)
                  )
                ORDER BY timestamp_start
            """
            
            rows = conn.execute(query, params).fetchall()

            correlated = []
            for row in rows:
                row_cat = row[3]
                # Enforce Independent Layer Rule
                if is_logical_error and row_cat in ('OS', 'DISK', 'NETWORK', 'CRS'):
                    continue
                    
                correlated.append({
                    "chunk_id":        row[0],
                    "log_source":      row[1],
                    "timestamp_start": row[2],
                    "category":        row[3],
                    "severity":        row[4],
                    "ora_code":        row[5],
                    "os_pattern":      row[6],
                    "raw_text":        row[7],
                })
            correlations[chunk_id] = correlated
        except Exception:
            correlations[chunk_id] = []

    conn.close()
    return correlations


def compute_temporal_bonus(correlations: dict[str, list[dict]], chunk_id: str) -> int:
    """
    Return temporal bonus score for a chunk.
    +10 if 1+ correlated chunks found from a different log source.
    +20 if 2+ different log sources corroborate (multi-source confirmation).
    """
    correlated = correlations.get(chunk_id, [])
    if not correlated:
        return 0

    unique_sources = {c["log_source"] for c in correlated}
    if len(unique_sources) >= 2:
        return TEMPORAL_BONUS * 2   # multi-source confirmation
    return TEMPORAL_BONUS


def detect_cascade(
    all_chunks: list[dict],
    cascade_library: list[dict],
    time_window_sec: int = CASCADE_WINDOW_SEC,
) -> list[dict]:
    """
    Check if retrieved chunks match a known cascade sequence.

    Args:
        all_chunks:       All payloads from retrieval + correlation
        cascade_library:  cascade list from graph.json

    Returns:
        List of matched cascade dicts with root_pattern identified
    """
    # Collect all patterns and ORA codes found
    found_patterns = {c.get("os_pattern") for c in all_chunks if c.get("os_pattern")}
    found_ora      = {c.get("ora_code") for c in all_chunks if c.get("ora_code")}
    found_all      = found_patterns | found_ora

    matched_cascades = []
    for cascade in cascade_library:
        sequence = set(cascade.get("sequence", []))
        # Cascade matches if at least 60% of sequence elements are found
        overlap = len(sequence & found_all)
        if overlap >= max(2, len(sequence) * 0.6):
            matched_cascades.append({
                "cascade_id":    cascade["cascade_id"],
                "root_pattern":  cascade["root_pattern"],
                "sequence":      cascade["sequence"],
                "matched_items": list(sequence & found_all),
                "match_pct":     round(overlap / len(sequence) * 100, 1),
            })

    # Sort by match percentage
    matched_cascades.sort(key=lambda x: x["match_pct"], reverse=True)
    return matched_cascades
