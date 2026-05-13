"""
classifier.py
=============
Maps active diagnostic signals to:
  - Issue Category  (e.g. "DB / Performance / Memory")
  - Root Cause Analysis (RCA) narrative
  - Risk Score      (LOW / MEDIUM / HIGH / CRITICAL)
  - Component Heatmap (per-component risk level)
  - Actionable Recommendations

Classification logic is rule-based and deterministic — no ML, no randomness.
All rules are grounded in Oracle DBA best practices.
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# Heatmap components and their default risk
# ─────────────────────────────────────────────────────────────────────────────

_COMPONENTS = [
    "Shared_Pool",
    "PGA",
    "CPU",
    "IO",
    "Redo_Log",
    "Network",
    "Cluster_RAC",
    "DataGuard",
    "Backup",
    "Security",
]

_RISK_LEVELS = ["GREEN", "YELLOW", "ORANGE", "RED"]   # ascending severity

def _max_risk(current: str, new: str) -> str:
    """Return the higher of two risk levels."""
    return new if _RISK_LEVELS.index(new) > _RISK_LEVELS.index(current) else current


# ─────────────────────────────────────────────────────────────────────────────
# Signal → Component Risk rules
# ─────────────────────────────────────────────────────────────────────────────

_SIGNAL_COMPONENT_RISK = {
    # ── Layer-based signals (from graph.json) ─────────────────────────────
    "LAYER_MEMORY":       {"Shared_Pool": "RED",    "PGA": "ORANGE"},
    "LAYER_OS_TRIGGERED": {"IO":          "ORANGE",  "Shared_Pool": "YELLOW"},
    "LAYER_ASM":          {"IO":          "RED"},
    "LAYER_DB":           {"Shared_Pool": "ORANGE"},
    "LAYER_NETWORK":      {"Network":     "RED"},
    "LAYER_CLUSTER":      {"Cluster_RAC": "RED"},
    "LAYER_Storage":      {"IO":          "RED"},
    "LAYER_Network":      {"Network":     "RED"},
    "LAYER_Memory":       {"Shared_Pool": "ORANGE", "PGA": "ORANGE"},
    "LAYER_Filesystem":   {"IO":          "ORANGE"},
    "LAYER_SECURITY":     {"Security":    "RED"},
    "LAYER_DATAGUARD":    {"DataGuard":   "RED"},
    "LAYER_RMAN":         {"Backup":      "ORANGE"},

    # ── ORA code specific signals ──────────────────────────────────────────
    "ORA_04031_DETECTED":         {"Shared_Pool": "RED"},
    "ORA_04030_DETECTED":         {"PGA":         "RED"},

    # ── AWR wait event signals ─────────────────────────────────────────────
    "SHARED_POOL_CONTENTION":     {"Shared_Pool": "RED"},
    "SHARED_POOL_EXHAUSTION":     {"Shared_Pool": "RED"},
    "PARSE_PRESSURE":             {"Shared_Pool": "ORANGE"},
    "LATCH_CONTENTION":           {"Shared_Pool": "ORANGE"},
    "HIGH_HARD_PARSE":            {"Shared_Pool": "ORANGE"},
    "IO_SINGLE_BLOCK":            {"IO":          "ORANGE"},
    "IO_MULTI_BLOCK":             {"IO":          "YELLOW"},
    "IO_DIRECT_PATH":             {"IO":          "YELLOW"},
    "REDO_LOG_PRESSURE":          {"Redo_Log":    "RED"},
    "RAC_GC_CONTENTION":          {"Cluster_RAC": "RED"},

    # ── AWR time signals ───────────────────────────────────────────────────
    "DB_TIME_SPIKE":              {"Shared_Pool": "YELLOW", "CPU": "YELLOW"},
    "DB_TIME_CRITICAL":           {"Shared_Pool": "ORANGE", "CPU": "ORANGE"},
    "ROW_LOCK_CONTENTION":        {"Shared_Pool": "YELLOW"},

    # ── OSW signals ────────────────────────────────────────────────────────
    "CPU_SATURATION":             {"CPU":         "RED"},
    "CPU_USER_HIGH":              {"CPU":         "ORANGE"},
    "MEMORY_PRESSURE":            {"Shared_Pool": "ORANGE", "PGA": "ORANGE"},
    "LOW_PHYSICAL_MEMORY":        {"Shared_Pool": "RED",    "PGA": "RED"},
    "IO_WAIT_HIGH":               {"IO":          "RED"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Classification rules: signal combinations → category + RCA
# Rules are evaluated in priority order (most specific first)
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFICATION_RULES = [
    # ── Memory layer (ORA-04031 / ORA-04030 class) ─────────────────────────
    # Rule 1: Full — memory layer + AWR pool signal + OSW memory
    {
        "id":           "RULE_MEMORY_FULL",
        "requires_any":  ["LAYER_MEMORY", "LAYER_Memory"],
        "requires_any2": ["SHARED_POOL_CONTENTION", "PARSE_PRESSURE",
                          "SHARED_POOL_EXHAUSTION"],
        "requires_any3": ["MEMORY_PRESSURE", "LOW_PHYSICAL_MEMORY", "CPU_SATURATION"],
        "category":     "DB / Performance / Memory",
        "rca":          ("Shared pool or process memory exhaustion during peak load. "
                         "Memory layer ORA code correlated with AWR latch/parse contention "
                         "and OS-level memory pressure confirms a memory configuration "
                         "or SQL literal overuse issue."),
        "risk":         "HIGH",
    },
    # Rule 2: Memory layer + AWR pool signal only
    {
        "id":           "RULE_MEMORY_AWR",
        "requires_any":  ["LAYER_MEMORY", "LAYER_Memory"],
        "requires_any2": ["SHARED_POOL_CONTENTION", "PARSE_PRESSURE",
                          "SHARED_POOL_EXHAUSTION", "HIGH_HARD_PARSE"],
        "requires_any3": None,
        "category":     "DB / Performance / Memory",
        "rca":          ("Shared memory allocation failure confirmed by alert log. "
                         "Corroborated by AWR latch or parse wait events. "
                         "Review shared pool sizing and cursor_sharing configuration."),
        "risk":         "HIGH",
    },
    # Rule 3: Memory layer alone
    {
        "id":           "RULE_MEMORY_SUSPECTED",
        "requires_any":  ["LAYER_MEMORY", "LAYER_Memory"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Memory",
        "rca":          ("Memory layer error detected in alert log. "
                         "Without AWR or OSWatcher evidence this may be transient. "
                         "Upload AWR and OSWatcher for full multi-source diagnosis."),
        "risk":         "MEDIUM",
    },

    # ── OS-Triggered layer (ENOSPC, EIO class ORA codes) ───────────────────
    {
        "id":           "RULE_OS_TRIGGERED",
        "requires_any":  ["LAYER_OS_TRIGGERED"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "OS / Infrastructure",
        "rca":          ("ORA code triggered by an OS-level condition (disk full, I/O error, "
                         "or filesystem issue). The root cause is in the OS or infrastructure "
                         "layer — not inside the Oracle engine. Check disk space, I/O errors "
                         "in dmesg, and storage path health."),
        "risk":         "HIGH",
    },

    # ── ASM layer ──────────────────────────────────────────────────────────
    {
        "id":           "RULE_ASM",
        "requires_any":  ["LAYER_ASM"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Infrastructure / ASM",
        "rca":          ("ASM layer error detected. Diskgroup may be dismounted or "
                         "one or more ASM disks are inaccessible. Check V$ASM_DISKGROUP "
                         "state and storage multipath connectivity."),
        "risk":         "HIGH",
    },

    # ── Network / Listener layer ───────────────────────────────────────────
    {
        "id":           "RULE_NETWORK",
        "requires_any":  ["LAYER_NETWORK", "LAYER_Network"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "Network / Connectivity",
        "rca":          ("Network or listener layer error detected. Database connection "
                         "or listener availability is impacted. Check lsnrctl status, "
                         "firewall rules on port 1521, and TNS configuration."),
        "risk":         "HIGH",
    },

    # ── Cluster / RAC layer ────────────────────────────────────────────────
    {
        "id":           "RULE_CLUSTER",
        "requires_any":  ["LAYER_CLUSTER"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Infrastructure / RAC / Cluster",
        "rca":          ("RAC cluster layer error detected. Node eviction or interconnect "
                         "failure may have occurred. Check crsctl stat res -t, "
                         "cluster interconnect health, and NTP synchronization."),
        "risk":         "HIGH",
    },

    # ── Storage / Filesystem OS pattern layer ──────────────────────────────
    {
        "id":           "RULE_OS_STORAGE",
        "requires_any":  ["LAYER_Storage", "LAYER_Filesystem"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "OS / Infrastructure / Storage",
        "rca":          ("OS-level storage or filesystem event detected in logs. "
                         "SCSI errors, HBA failures, or multipath failover may have "
                         "caused this incident. Escalate to storage/infrastructure team."),
        "risk":         "HIGH",
    },

    # ── Security / Access Control layer ───────────────────────────────────
    {
        "id":           "RULE_SECURITY",
        "requires_any":  ["LAYER_SECURITY"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Security / Access",
        "rca":          ("Security or access control error detected. Account may be locked, "
                         "password expired, or a profile limit exceeded. "
                         "Check DBA_PROFILES, DBA_USERS status, and audit trail."),
        "risk":         "HIGH",
    },

    # ── DataGuard / Standby layer ──────────────────────────────────────────
    {
        "id":           "RULE_DATAGUARD",
        "requires_any":  ["LAYER_DATAGUARD"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / DataGuard / Standby",
        "rca":          ("DataGuard standby synchronization issue detected. Redo transport "
                         "failure, apply lag, or managed recovery process (MRP) stopped. "
                         "Check V$DATAGUARD_STATUS, V$MANAGED_STANDBY, and archive log gaps."),
        "risk":         "HIGH",
    },

    # ── RMAN / Backup-Recovery layer ───────────────────────────────────────
    {
        "id":           "RULE_RMAN",
        "requires_any":  ["LAYER_RMAN"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Backup / Recovery",
        "rca":          ("RMAN backup or recovery operation failed. Archived log may be "
                         "missing or backup destination is full. "
                         "Check RMAN job history: LIST FAILURE; and verify archive log availability."),
        "risk":         "MEDIUM",
    },

    # ── Pure DB internal layer ─────────────────────────────────────────────
    {
        "id":           "RULE_DB_INTERNAL",
        "requires_any":  ["LAYER_DB"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Internal",
        "rca":          ("Oracle internal database error detected. The issue originated "
                         "inside the Oracle engine (not triggered by OS or infrastructure). "
                         "Check alert log trace files, ADRCI incident list, and recent DDL."),
        "risk":         "MEDIUM",
    },

    # ── AWR performance: CPU spike + OSW saturation (no ORA code) ──────────
    {
        "id":           "RULE_PERF_CPU",
        "requires_any":  ["DB_TIME_SPIKE", "DB_TIME_CRITICAL"],
        "requires_any2": ["CPU_SATURATION", "CPU_USER_HIGH"],
        "requires_any3": None,
        "category":     "DB / Performance / CPU",
        "rca":          ("High DB time correlated with OS CPU saturation. "
                         "No ORA code in alert log. Likely a runaway query, "
                         "full table scan storm, or sudden workload spike."),
        "risk":         "MEDIUM",
    },

    # ── I/O signals ────────────────────────────────────────────────────────
    {
        "id":           "RULE_PERF_IO",
        "requires_any":  ["IO_WAIT_HIGH"],
        "requires_any2": ["IO_SINGLE_BLOCK", "IO_MULTI_BLOCK"],
        "requires_any3": None,
        "category":     "DB / Performance / I/O",
        "rca":          ("High I/O wait at OS level with corroborating I/O wait events in AWR. "
                         "Potential storage bottleneck or missing indexes causing excessive scans."),
        "risk":         "MEDIUM",
    },

    # ── RAC GC contention ──────────────────────────────────────────────────
    {
        "id":           "RULE_RAC_GC",
        "requires_any":  ["RAC_GC_CONTENTION"],
        "requires_any2": None,
        "requires_any3": None,
        "category":     "DB / Performance / RAC",
        "rca":          ("Global Cache contention in AWR. Excessive inter-node block shipping "
                         "in RAC. Review connection load balancing and object partitioning."),
        "risk":         "HIGH",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation library — keyed by signal
# ─────────────────────────────────────────────────────────────────────────────

_RECOMMENDATIONS = {
    "ORA_04031_DETECTED": [
        "Immediately: ALTER SYSTEM FLUSH SHARED_POOL; (temporary relief only)",
        "Review SHARED_POOL_SIZE and SGA_TARGET — increase if < 30% of RAM",
        "Set CURSOR_SHARING = FORCE to reduce hard parse pressure from SQL literals",
        "Identify top hard-parsing SQL from AWR 'SQL ordered by Parse Calls' section",
        "Review V$SGASTAT for 'free memory' in shared pool — if < 5%, resize required",
    ],
    "ORA_04030_DETECTED": [
        "Review PGA_AGGREGATE_TARGET — increase to accommodate workload sort/hash operations",
        "Identify sessions with high PGA usage: SELECT SID, PGA_USED_MEM FROM V$PROCESS",
        "Check for large unbounded sorts or hash joins in AWR Top SQL",
        "Consider enabling WORKAREA_SIZE_POLICY = AUTO with adequate PGA target",
    ],
    "SHARED_POOL_CONTENTION": [
        "Identify latch holders: SELECT * FROM V$LATCH WHERE NAME LIKE '%shared pool%'",
        'Tune shared pool sub-pools: ALTER SYSTEM SET "_kghdsidx_count"=4 SCOPE=SPFILE',
        "Implement bind variables in application code to reduce hard parsing",
    ],
    "PARSE_PRESSURE": [
        "Enable SESSION_CACHED_CURSORS to reduce repeated parses per session",
        "Investigate library cache hit ratio: SELECT * FROM V$LIBRARYCACHE",
        "Review OPEN_CURSORS parameter — increase if applications hold many cursors",
    ],
    "HIGH_HARD_PARSE": [
        "Run AWR 'SQL ordered by Parse Calls' to identify literal SQL",
        "Use V$SQL to find SQL with high PARSE_CALLS vs EXECUTIONS ratio",
        "Enforce application-level bind variable usage policy",
    ],
    "DB_TIME_SPIKE": [
        "Review AWR 'Top 10 Foreground Events' for the peak window",
        "Compare current AWR snapshot with baseline using DBMS_WORKLOAD_REPOSITORY",
        "Identify sessions with high CPU during peak: SELECT * FROM V$SESSION_LONGOPS",
    ],
    "MEMORY_PRESSURE": [
        "Check OS free memory trend from OSWatcher archives",
        "Verify SGA + PGA total does not exceed 70-75% of physical RAM",
        "Review MEMORY_TARGET or SGA_TARGET vs current usage in V$SGA",
    ],
    "LOW_PHYSICAL_MEMORY": [
        "CRITICAL: OS is actively paging — reduce MEMORY_TARGET immediately",
        "Check for memory leak in Oracle processes: ps aux | grep oracle | sort -k6 -rn",
        "Review HugePages configuration — ensure SGA is mapped to HugePages",
    ],
    "CPU_SATURATION": [
        "Identify top CPU consumers: SELECT * FROM V$SESSION ORDER BY VALUE DESC (CPU used)",
        "Review OSWatcher CPU data for run queue sustained above 2× CPU count",
        "Check for recursive SQL or excessive parse calls driving CPU",
    ],
    "IO_WAIT_HIGH": [
        "Review iostat output for device utilization > 80%",
        "Check for missing indexes via AWR 'SQL ordered by Physical Reads'",
        "Verify storage multipath is active and all paths healthy",
    ],
    "RAC_GC_CONTENTION": [
        "Review interconnect bandwidth and latency between RAC nodes",
        "Check AWR 'Global Cache and Enqueue Statistics' section",
        "Consider partition pruning or sequence caching to reduce cross-node traffic",
    ],
}


def _build_heatmap(active_signals: set) -> dict:
    """Build component heatmap from active signals."""
    heatmap = {c: "GREEN" for c in _COMPONENTS}

    for signal in active_signals:
        component_risks = _SIGNAL_COMPONENT_RISK.get(signal, {})
        for component, risk in component_risks.items():
            if component in heatmap:
                heatmap[component] = _max_risk(heatmap[component], risk)

    return heatmap


def _match_rule(rule: dict, active_signals: set) -> bool:
    """Return True if all requires_any conditions of a rule are satisfied."""
    def any_match(signal_list, signals):
        if signal_list is None:
            return True
        return any(s in signals for s in signal_list)

    return (
        any_match(rule.get("requires_any"),  active_signals)
        and any_match(rule.get("requires_any2"), active_signals)
        and any_match(rule.get("requires_any3"), active_signals)
    )


def _build_recommendations(active_signals: set) -> list[str]:
    """Collect unique recommendations for all active signals."""
    recs = []
    seen = set()
    for signal in sorted(active_signals):
        for rec in _RECOMMENDATIONS.get(signal, []):
            if rec not in seen:
                recs.append(rec)
                seen.add(rec)
    return recs


def classify_incident(
    active_signals: list[str] | set[str],
    confidence_score: int = 0,
) -> dict:
    """
    Classify an incident based on active diagnostic signals.

    Args:
        active_signals   : List/set of signal strings from evidence_aggregator.
        confidence_score : Score from evidence_aggregator (used for risk override).

    Returns:
        {
            "issue_category":   str,
            "rca":              str,
            "risk_score":       str,       # LOW / MEDIUM / HIGH / CRITICAL
            "heatmap":          dict,      # {component: risk_level}
            "recommendations":  list[str],
            "rule_matched":     str,
        }
    """
    signals = set(active_signals)

    # Default (no rule matched)
    result = {
        "issue_category":  "DB / Unknown",
        "rca":             "Insufficient evidence for classification. Upload alert.log, AWR, and OSWatcher for full diagnosis.",
        "risk_score":      "LOW",
        "heatmap":         _build_heatmap(signals),
        "recommendations": _build_recommendations(signals),
        "rule_matched":    "NONE",
    }

    # Evaluate rules in priority order
    for rule in _CLASSIFICATION_RULES:
        if _match_rule(rule, signals):
            result["issue_category"] = rule["category"]
            result["rca"]            = rule["rca"]
            result["risk_score"]     = rule["risk"]
            result["rule_matched"]   = rule["id"]
            break

    # Override risk to CRITICAL if confidence is very high and risk is HIGH
    if confidence_score >= 90 and result["risk_score"] == "HIGH":
        result["risk_score"] = "CRITICAL"

    return result
