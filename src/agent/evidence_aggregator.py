"""
DEPRECATED for production RCA — not used by ``src.agent.agent`` (evidence-first path).
Weighted confidence aggregation for legacy orchestrator flows; tests and demos may still import this module.

evidence_aggregator.py
======================
Aggregates evidence from multiple diagnostic sources into a single
weighted confidence score.

Evidence sources supported:
  1. Temporal graph anchor (alert.log / syslog)  → ORA code detected
  2. AWR parser output                           → performance signals
  3. OSWatcher parser output                     → OS-level signals
  4. CRS alert log (clean = no critical events)  → cluster cleared

Confidence scoring formula (maximum 100 points):
  ORA-04031 in alert log          +30 pts   (primary SGA signal)
  ORA-04030 in alert log          +30 pts   (primary PGA signal)
  AWR DB Time spike (ratio >1.5)  +15 pts
  AWR shared pool / parse wait    +15 pts
  AWR top SQL high hard parse     +10 pts
  OSW CPU saturation              +10 pts
  OSW memory pressure / low mem   +15 pts
  CRS alert clean (no critical)   + 5 pts
  MAX                              100 pts

Confidence labels:
  80–100  CONFIRMED
  60–79   HIGH_CONFIDENCE
  40–59   PROBABLE
  <  40   SUSPECTED
"""

from __future__ import annotations
import os
import yaml
from src.knowledge_graph.graph import get_layer_for_code

# ── Load thresholds from settings.yaml (single source of truth) ──────────────────
_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "settings.yaml"
)
try:
    with open(_SETTINGS_PATH) as _f:
        _cfg = yaml.safe_load(_f)
    _CONF_HIGH   = _cfg["thresholds"]["high_confidence"]    # 80
    _CONF_MEDIUM = _cfg["thresholds"]["medium_confidence"]  # 60
    _CONF_LOW    = _cfg["thresholds"]["low_confidence"]     # 40
    # Evidence scoring weights (all 35 signals)
    _WEIGHTS: dict[str, int] = _cfg.get("evidence_weights", {})
    # Evidence rules
    _rules            = _cfg.get("evidence_rules", {})
    _FATAL_OS_EVENTS  = set(_rules.get("fatal_os_events",
                            ["OS_KERNEL_PANIC", "OS_POWER_FAILURE",
                             "OS_OOM_KILLER", "OS_SCSI_TIMEOUT"]))
    _CRY_WOLF_THRESH  = _rules.get("cry_wolf_threshold", 100)
    _AWR_SYMPTOM_BONUS = _rules.get("awr_symptom_bonus", 20)
except Exception:
    _CONF_HIGH, _CONF_MEDIUM, _CONF_LOW = 80, 60, 40   # safe fallback
    _WEIGHTS = {}
    _FATAL_OS_EVENTS  = {"OS_KERNEL_PANIC", "OS_POWER_FAILURE", "OS_OOM_KILLER", "OS_SCSI_TIMEOUT"}
    _CRY_WOLF_THRESH  = 100
    _AWR_SYMPTOM_BONUS = 20

# If settings.yaml weights are empty (first run), fall back to built-in defaults
if not _WEIGHTS:
    _WEIGHTS = {
        "LAYER_MEMORY":           30, "LAYER_OS_TRIGGERED":     25,
        "LAYER_ASM":              25, "LAYER_DB":               20,
        "LAYER_NETWORK":          20, "LAYER_CLUSTER":          25,
        "ASM_HIGH_POWER_REBALANCE": 25, "LAYER_Storage":        25,
        "LAYER_Network":          20, "LAYER_Memory":           25,
        "LAYER_Filesystem":       20, "LAYER_SECURITY":         20,
        "AUDITD_KILL_9":          30, "LAYER_DATAGUARD":        25,
        "LAYER_RMAN":             20, "LAYER_NEEDS_MORE_INFO":   0,
        "DB_TIME_SPIKE":          15, "DB_TIME_CRITICAL":       15,
        "SHARED_POOL_CONTENTION": 15, "PARSE_PRESSURE":         15,
        "SHARED_POOL_EXHAUSTION": 15, "HIGH_HARD_PARSE":        10,
        "LATCH_CONTENTION":       10, "CPU_SATURATION":         10,
        "CPU_USER_HIGH":          10, "MEMORY_PRESSURE":        15,
        "LOW_PHYSICAL_MEMORY":    15, "PROCESS_D_STATE_ZOMBIE": 20,
        "CRS_CLEAN":               5,
    }


# Mutually exclusive buckets — only highest signal in each bucket scores.
# LAYER_NEEDS_MORE_INFO is included so it appears in active_signals but scores 0.
_BUCKETS = {
    "layer_primary":  [
        "LAYER_MEMORY", "LAYER_CLUSTER", "LAYER_ASM",
        "LAYER_OS_TRIGGERED", "LAYER_Storage", "LAYER_Memory",
        "LAYER_Filesystem", "LAYER_DB", "LAYER_NETWORK",
        "LAYER_Network", "LAYER_SECURITY", "LAYER_DATAGUARD",
        "LAYER_RMAN", "LAYER_NEEDS_MORE_INFO",
        "ASM_HIGH_POWER_REBALANCE", "AUDITD_KILL_9"
    ],
    "awr_time":   ["DB_TIME_CRITICAL", "DB_TIME_SPIKE"],
    "awr_pool":   ["SHARED_POOL_EXHAUSTION", "SHARED_POOL_CONTENTION", "PARSE_PRESSURE"],
    "awr_sql":    ["HIGH_HARD_PARSE", "LATCH_CONTENTION"],
    "osw_cpu":    ["CPU_SATURATION", "CPU_USER_HIGH"],
    "osw_memory": ["MEMORY_PRESSURE", "LOW_PHYSICAL_MEMORY"],
    "osw_process": ["PROCESS_D_STATE_ZOMBIE"],
    "crs":        ["CRS_CLEAN"],
}


def _score_bucket(bucket_signals: list[str], active_signals: set) -> int:
    """Return score for the first signal in bucket that is active."""
    for signal in bucket_signals:
        if signal in active_signals:
            return _WEIGHTS.get(signal, 0)
    return 0


def compute_confidence(
    anchor_result:  dict | None,
    awr_result:     dict | None,
    osw_result:     dict | None,
    crs_is_clean:   bool = False,
) -> dict:
    """
    Compute weighted confidence score from all evidence sources.

    Args:
        anchor_result : dict returned by orchestrator temporal graph
                        (must have 'root_cause' key with ORA code)
        awr_result    : dict from awr_parser.parse_awr_report()
        osw_result    : dict from osw_parser.parse_osw_report()
        crs_is_clean  : True if CRS/ASM alert log had no critical events

    Returns:
        {
            "confidence_score":   int,        # 0–100
            "confidence_label":   str,        # CONFIRMED / HIGH_CONFIDENCE / ...
            "evidence_sources":   list[str],  # which sources contributed
            "active_signals":     list[str],  # all signals that fired
            "score_breakdown":    dict,       # per-bucket points
        }
    """
    active_signals: set[str] = set()
    evidence_sources: list[str] = []
    score_breakdown: dict[str, int] = {}

    # ── Source 1: Alert log / temporal graph ─────────────────────────────────
    if anchor_result and anchor_result.get("root_cause"):
        root_cause = anchor_result["root_cause"]
        if root_cause not in ("N/A", "UNKNOWN"):
            # Look up the layer from graph.json — works for any ORA code or OS pattern
            layer_info = get_layer_for_code(root_cause)
            layer      = layer_info["layer"]      # e.g. MEMORY / OS_TRIGGERED / DB / ASM
            signal     = f"LAYER_{layer}"          # e.g. LAYER_MEMORY / LAYER_OS_TRIGGERED
            active_signals.add(signal)
            active_signals.add(root_cause)         # Include root_cause so specific weights and Edge Cases can match it
            evidence_sources.append("alert_log")

    # ── Source 2: AWR signals ─────────────────────────────────────────────────
    if awr_result and not awr_result.get("parse_error"):
        awr_signals = set(awr_result.get("awr_signals", []))
        active_signals.update(awr_signals)
        if awr_signals:
            evidence_sources.append("awr")

    # ── Source 3: OSW signals ─────────────────────────────────────────────────
    if osw_result and not osw_result.get("parse_error"):
        osw_signals = set(osw_result.get("osw_signals", []))
        active_signals.update(osw_signals)
        if osw_signals:
            evidence_sources.append("osw")

    # ── Source 4: CRS clean ───────────────────────────────────────────────────
    if crs_is_clean:
        active_signals.add("CRS_CLEAN")
        evidence_sources.append("crs_clean")

    # ── Compute score by buckets ──────────────────────────────────────────────
    total_score = 0
    for bucket_name, bucket_signals in _BUCKETS.items():
        pts = _score_bucket(bucket_signals, active_signals)
        score_breakdown[bucket_name] = pts
        total_score += pts

    # [Phase 3 - Edge Case 4: Sudden Death Paradox]
    # If the temporal anchor is a fatal OS event, it guarantees 100% confidence 
    # because the database was killed instantly and couldn't log an error.
    if anchor_result and anchor_result.get("root_cause") in _FATAL_OS_EVENTS:
        total_score = 100
        active_signals.add("SUDDEN_DEATH_OVERRIDE")

    # [Phase 3 - Edge Case 11: Cry Wolf Threshold]
    # Ignore high-volume network false alarms (like ORA-3136 connection timeout)
    # UNLESS frequency spikes (e.g., > 100).
    if anchor_result and anchor_result.get("root_cause") == "ORA-3136":
        freq = anchor_result.get("frequency", 1)
        if freq < _CRY_WOLF_THRESH:
            total_score = min(total_score, _CONF_LOW - 1)  # force SUSPECTED
            active_signals.add("CRY_WOLF_SUPPRESSED")
        else:
            total_score = 100  # Confirmed connection flood
            active_signals.add("CRY_WOLF_ESCALATED")

    # [Phase 3 - Edge Case 13: AWR Symptom vs Disease]
    # If AWR shows 'log file sync' (storage symptom), but OSW shows 100% CPU, 
    # the disk isn't slow—the I/O thread is just starving for CPU!
    if "LOG_FILE_SYNC" in active_signals and "CPU_SATURATION" in active_signals:
        active_signals.remove("LOG_FILE_SYNC")
        active_signals.add("STARVED_IO_THREAD")
        total_score += _AWR_SYMPTOM_BONUS  # Reward for identifying the true disease

    # [Phase 3 - Edge Case 25: OOM Collateral Damage]
    # If OOM Killer targets a critical daemon (multipathd, iscsid), the DB is a ticking time bomb.
    if anchor_result and anchor_result.get("root_cause") == "OS_OOM_KILLER":
        raw_text = anchor_result.get("raw_content", "").lower()
        if "multipathd" in raw_text or "iscsid" in raw_text:
            total_score = 100
            active_signals.add("CRITICAL_DAEMON_KILLED")

    total_score = min(total_score, 100)   # hard cap

    # ── Confidence label ──────────────────────────────────────────────────────
    if total_score >= _CONF_HIGH:
        label = "CONFIRMED"
    elif total_score >= _CONF_MEDIUM:
        label = "HIGH_CONFIDENCE"
    elif total_score >= _CONF_LOW:
        label = "PROBABLE"
    else:
        label = "SUSPECTED"

    # Detect Tier 3: code was not found in graph.json or PDF data
    needs_more_info = "LAYER_NEEDS_MORE_INFO" in active_signals

    return {
        "confidence_score":  total_score,
        "confidence_label":  label,
        "evidence_sources":  list(dict.fromkeys(evidence_sources)),   # dedup
        "active_signals":    sorted(active_signals),
        "score_breakdown":   score_breakdown,
        "needs_more_info":   needs_more_info,
    }
