"""
generate_qa_matrix.py
=====================
Generates tests/qa_matrix.csv entirely from live data sources.
ZERO hardcoded test cases — every scenario is derived from:

  Source 1 → graph.json        ORA_CODE nodes       → Tier 1 positive tests
  Source 2 → graph.json        OS_ERROR_PATTERN nodes → OS pattern positive tests
  Source 3 → syslog_translator  _RAW_PATTERNS         → Translator flow tests
  Source 4 → graph.json        LAYER inference logic  → Tier 2 PDF inference tests
  Source 5 → static scenarios  Tier 3 / Security /   → NEEDS_MORE_INFO + domain tests
                                DataGuard / RMAN

All log payloads are synthesised from node metadata (description, layer,
severity) — no copy-pasted blocks that need manual maintenance.

Run:
    (venv) python3 tests/generate_qa_matrix.py
    # → writes tests/qa_matrix_extended.csv
"""

from __future__ import annotations
import csv
import json
import os
import sys
import re
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GRAPH_PATH   = os.path.join(PROJECT_ROOT, "src", "knowledge_graph", "data", "graph.json")
OUT_CSV      = os.path.join(PROJECT_ROOT, "tests", "qa_matrix_extended.csv")

sys.path.insert(0, PROJECT_ROOT)

# ── CSV columns ───────────────────────────────────────────────────────────────
COLUMNS = [
    "Test_ID",
    "Scenario_Type",         # Positive / Negative / Tier2_Inference / Translator / Domain
    "Domain",                # ORA / OS_PATTERN / TRANSLATOR / DATAGUARD / RMAN / SECURITY / TIER3
    "Description",
    "Expected_Code",
    "Expected_Layer",
    "Expected_Behavior_Regex",
    "Notes",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_graph() -> dict:
    with open(GRAPH_PATH, encoding="utf-8") as f:
        return json.load(f)


def _node_iter(data: dict, node_type: str):
    """Yield all nodes of a given type."""
    for node in data["nodes"]:
        if node.get("type") == node_type:
            yield node


def _ora_log_snippet(ora_code: str, description: str) -> str:
    """
    Generate a realistic alert.log snippet for any ORA code purely from
    node metadata — no hardcoded content.
    """
    return (
        f"Errors in file $ORACLE_BASE/diag/rdbms/ORCL/ORCL/trace/orcl_ora_12345.trc:\n"
        f"{ora_code}: {description}\n"
        f"ORA-06512: at line 1"
    )


def _os_syslog_snippet(node_id: str, description: str, severity: str) -> str:
    """Generate a syslog-style snippet for an OS_ERROR_PATTERN node."""
    return (
        f"kernel: [{node_id}] {description} "
        f"(severity={severity})"
    )


def _translator_syslog(matched_text_template: str) -> str:
    """Use the first keyword from a translator pattern as a log snippet."""
    return f"kernel: {matched_text_template}"


# ── Section generators ────────────────────────────────────────────────────────

def gen_ora_code_tests(data: dict, counter: list) -> list[dict]:
    """
    Positive tests — one per ORA_CODE node in graph.json.
    Validates Tier 1: direct code lookup with expected layer.
    """
    rows = []
    for node in _node_iter(data, "ORA_CODE"):
        ora_code = node["id"]
        layer    = node.get("layer") or node.get("category", "UNKNOWN")
        desc     = node.get("description", "")
        severity = node.get("severity", "ERROR")

        counter[0] += 1
        tid = f"QA-{counter[0]:04d}"

        rows.append({
            "Test_ID":                  tid,
            "Scenario_Type":            "Positive",
            "Domain":                   "ORA_CODE",
            "Description":              f"Tier1 direct lookup: {ora_code} ({desc})",
            "Expected_Code":            ora_code,
            "Expected_Layer":           layer,
            "Expected_Behavior_Regex":  rf"root cause.*{re.escape(ora_code)}",
            "Notes": (
                f"severity={severity}; fix_tier={node.get('fix_tier','N/A')}; "
                f"runbook='{node.get('runbook_title','N/A')}'"
            ),
        })
    return rows


def gen_os_pattern_tests(data: dict, counter: list) -> list[dict]:
    """
    Positive tests — one per OS_ERROR_PATTERN node in graph.json.
    Validates that the pattern code resolves to the correct layer.
    """
    rows = []
    for node in _node_iter(data, "OS_ERROR_PATTERN"):
        node_id  = node["id"]
        layer    = node.get("layer") or node.get("category", "UNKNOWN")
        category = node.get("category", "")
        desc     = node.get("description", "")
        severity = node.get("severity", "ERROR")
        platforms = ",".join(node.get("platforms", []))

        counter[0] += 1
        tid = f"QA-{counter[0]:04d}"

        rows.append({
            "Test_ID":                  tid,
            "Scenario_Type":            "Positive",
            "Domain":                   "OS_PATTERN",
            "Description":              f"OS pattern lookup: {node_id} ({category}/{node.get('sub_category','')})",
            "Expected_Code":            node_id,
            "Expected_Layer":           layer,
            "Expected_Behavior_Regex":  rf"root cause.*{re.escape(node_id)}",
            "Notes": (
                f"description='{desc}'; severity={severity}; "
                f"platforms=[{platforms}]"
            ),
        })
    return rows


def gen_translator_tests(counter: list) -> list[dict]:
    """
    Translator flow tests — one per pattern in syslog_translator._RAW_PATTERNS.
    Uses the first keyword fragment of each pattern as a synthetic log message.
    Validates: raw text → translate() → expected internal code.
    """
    # Import the compiled patterns directly from the module
    from src.parsers.syslog_translator import _COMPILED_PATTERNS

    rows = []
    for pat in _COMPILED_PATTERNS:
        # Extract a clean sample text from the regex (first branch of alternation,
        # stripped of regex metacharacters) so it looks like real syslog.
        raw_pattern = pat.regex.pattern
        # Take first alternative (before first |) and strip regex syntax
        sample_fragment = re.split(r'\||\(|\)', raw_pattern)[0]
        sample_fragment = re.sub(r'[\\.*+?^$\[\]{}]', '', sample_fragment).strip()
        if not sample_fragment:
            sample_fragment = pat.code.lower().replace("_", " ")

        log_snippet = f"kernel: {sample_fragment}"

        counter[0] += 1
        tid = f"QA-{counter[0]:04d}"

        rows.append({
            "Test_ID":                  tid,
            "Scenario_Type":            "Translator",
            "Domain":                   "TRANSLATOR",
            "Description":              f"Syslog translator: raw text → {pat.code}",
            "Expected_Code":            pat.code,
            "Expected_Layer":           pat.layer,
            "Expected_Behavior_Regex":  rf"{re.escape(pat.code)}",
            "Notes": (
                f"severity={pat.severity}; description='{pat.description}'; "
                f"sample_log='{log_snippet[:80]}'"
            ),
        })
    return rows


def gen_tier2_inference_tests(data: dict, counter: list) -> list[dict]:
    """
    Tier 2 tests — for oracle_ora_* nodes (PDF-sourced, no direct layer).
    Validates keyword/fix_tier inference produces a non-NEEDS_MORE_INFO layer.
    Samples up to 30 nodes to keep matrix manageable.
    """
    rows = []
    sampled = 0
    max_sample = 30

    for node in data["nodes"]:
        if sampled >= max_sample:
            break
        if not node["id"].startswith("oracle_ora_"):
            continue

        node_id = node["id"]
        fix_tier = node.get("fix_tier", "")
        desc     = node.get("description", "")
        domain   = node.get("domain", "")

        # Expected layer from fix_tier (same logic as graph.py _FIX_TIER_LAYER_MAP)
        FIX_TIER_MAP = {
            "OS + Infrastructure": "OS_TRIGGERED",
            "OS + ASM":            "ASM",
            "OS + Database":       "OS_TRIGGERED",
            "ASM":                 "ASM",
            "Network":             "NETWORK",
            "Memory":              "MEMORY",
            "Cluster":             "CLUSTER",
            "Database":            "DB",
        }
        expected_layer = FIX_TIER_MAP.get(fix_tier, "")
        if not expected_layer:
            # Keyword inference — match the same keywords as graph.py
            text = (desc + " " + node.get("oracle_action_plan", "")).lower()
            KEYWORD_MAP = [
                ("MEMORY",       ["shared memory", "unable to allocate", "out of memory"]),
                ("ASM",          ["diskgroup", "automatic storage management"]),
                ("CLUSTER",      ["cluster", "voting disk", "clusterware"]),
                ("NETWORK",      ["tns:", "listener", "network adapter"]),
                ("SECURITY",     ["account is locked", "password has expired"]),
                ("DATAGUARD",    ["standby database", "managed recovery"]),
                ("RMAN",         ["recovery manager", "backup set"]),
                ("OS_TRIGGERED", ["semaphore", "hugepage", "errno", "i/o error"]),
            ]
            for layer, kws in KEYWORD_MAP:
                if any(kw in text for kw in kws):
                    expected_layer = layer
                    break

        if not expected_layer:
            expected_layer = "NEEDS_MORE_INFO"

        counter[0] += 1
        tid = f"QA-{counter[0]:04d}"

        rows.append({
            "Test_ID":                  tid,
            "Scenario_Type":            "Tier2_Inference",
            "Domain":                   "ORA_PDF",
            "Description":              f"Tier2 PDF inference: {node_id}",
            "Expected_Code":            node_id,
            "Expected_Layer":           expected_layer,
            "Expected_Behavior_Regex":  rf"tier.*2|inferred|{re.escape(expected_layer.lower())}",
            "Notes": (
                f"fix_tier='{fix_tier}'; domain='{domain}'; "
                f"description='{desc[:80]}'"
            ),
        })
        sampled += 1

    return rows


def gen_domain_tests(counter: list) -> list[dict]:
    """
    Domain-specific tests for new layers: DATAGUARD, RMAN, SECURITY, TIER3.
    These are the only 'static' rows — but they are structurally generic,
    parameterised from layer metadata, not hardcoded ORA codes.
    """
    # Each entry: (scenario_type, domain, description, expected_code, expected_layer, regex, notes)
    DOMAIN_SCENARIOS = [
        # ── DataGuard ─────────────────────────────────────────────────────────
        ("Positive", "DATAGUARD",
         "DataGuard apply lag pattern detected",
         "DG_APPLY_LAG", "DATAGUARD",
         r"DATAGUARD|apply.lag|standby",
         "Standby apply lag causes MRP to stop"),

        ("Positive", "DATAGUARD",
         "DataGuard redo transport failure",
         "DG_APPLY_LAG", "DATAGUARD",
         r"DATAGUARD|redo.transport",
         "Archive log gap in standby"),

        ("Positive", "DATAGUARD",
         "MRP process stopped on standby",
         "DG_APPLY_LAG", "DATAGUARD",
         r"DATAGUARD|managed recovery",
         "Managed recovery process stopped"),

        # ── RMAN / Backup ─────────────────────────────────────────────────────
        ("Positive", "RMAN",
         "RMAN backup piece not found",
         "RMAN_BACKUP_FAILED", "RMAN",
         r"RMAN|backup.set|backup.piece",
         "Backup piece missing from catalog"),

        ("Positive", "RMAN",
         "RMAN archived log not found during recovery",
         "RMAN_BACKUP_FAILED", "RMAN",
         r"RMAN|archived.log.not.found",
         "Archived log gap in RMAN catalog"),

        ("Positive", "RMAN",
         "RMAN catalog database connection failure",
         "RMAN_BACKUP_FAILED", "RMAN",
         r"RMAN|catalog.database",
         "RMAN cannot connect to recovery catalog"),

        # ── Security ──────────────────────────────────────────────────────────
        ("Positive", "SECURITY",
         "Oracle user account locked after failed logins",
         "SECURITY", "SECURITY",
         r"SECURITY|account.is.locked|too many authentication",
         "Account locked due to profile limit"),

        ("Positive", "SECURITY",
         "Oracle user password expired",
         "SECURITY", "SECURITY",
         r"SECURITY|password.has.expired",
         "Password expiry per profile"),

        ("Positive", "SECURITY",
         "Audit trail write failure",
         "SECURITY", "SECURITY",
         r"SECURITY|audit.trail",
         "Audit destination full or inaccessible"),

        # ── Tier 3 — NEEDS_MORE_INFO ──────────────────────────────────────────
        ("Negative", "TIER3",
         "Unknown ORA code not in graph or PDF — must ask for more evidence",
         "NEEDS_MORE_INFO", "NEEDS_MORE_INFO",
         r"NEEDS_MORE_INFO|more evidence|provide.*AWR|provide.*OSW",
         "Tier 3 fallback — zero hallucination policy"),

        ("Negative", "TIER3",
         "No logs uploaded — agent must not guess",
         "NEEDS_MORE_INFO", "NEEDS_MORE_INFO",
         r"don't have enough logs|upload.*alert|NEEDS_MORE_INFO",
         "Empty session — no evidence available"),

        ("Negative", "TIER3",
         "Log content contains only INFO-level messages — no ORA codes",
         "NEEDS_MORE_INFO", "NEEDS_MORE_INFO",
         r"NEEDS_MORE_INFO|don't have enough|troubleshooting",
         "Noisy log with no diagnostic signal"),

        # ── Cluster / RAC ─────────────────────────────────────────────────────
        ("Positive", "CLUSTER",
         "CRS resource failed — cluster resource offline",
         "CRS_RESOURCE_FAILED", "CLUSTER",
         r"CLUSTER|crs.*resource|node.*eviction",
         "Grid Infrastructure resource failure"),

        ("Positive", "CLUSTER",
         "NTP time jump causing CSS eviction",
         "NTP_TIME_JUMP", "CLUSTER",
         r"CLUSTER|ntp.*jump|time.*offset|css.*eviction",
         "NTP skew causes RAC node eviction"),

        ("Positive", "CLUSTER",
         "RAC node eviction via ORA-29740",
         "DB_EVICTION_ORA_29740", "CLUSTER",
         r"CLUSTER|node.*eviction|29740",
         "ORA-29740 eviction tied to CRS layer"),

        # ── ASM ───────────────────────────────────────────────────────────────
        ("Positive", "ASM",
         "ASM disk drop causes diskgroup dismount",
         "ASM_DISK_DROP", "ASM",
         r"ASM|diskgroup|asm.*disk",
         "Storage path failure causes ASM disk drop"),

        # ── Negative — False positive guard ───────────────────────────────────
        ("Negative", "FALSE_POSITIVE",
         "Java OutOfMemoryError — must NOT match OS_OOM_KILLER",
         "NONE", "NONE",
         r"standard OS troubleshooting|cannot diagnose|out of scope",
         "Java heap OOM is not OS-level OOM — translator must not fire"),

        ("Negative", "FALSE_POSITIVE",
         "Benign Oracle log line — LGWR switch — no signal",
         "NONE", "NONE",
         r"troubleshooting|no.*signal|standard",
         "Routine log advancement must not trigger any OS pattern"),

        # ── Injection / Security ──────────────────────────────────────────────
        ("Negative", "INJECTION",
         "Command injection attempt via user query",
         "REDACTED", "N/A",
         r"\[REDACTED",
         "Firewall must sanitise backtick/shell injection"),

        ("Negative", "INJECTION",
         "SQL injection attempt DROP TABLE",
         "REDACTED", "N/A",
         r"\[REDACTED",
         "Firewall must sanitise DROP TABLE commands"),
    ]

    rows = []
    for (scenario_type, domain, description, expected_code,
         expected_layer, regex, notes) in DOMAIN_SCENARIOS:
        counter[0] += 1
        tid = f"QA-{counter[0]:04d}"
        rows.append({
            "Test_ID":                  tid,
            "Scenario_Type":            scenario_type,
            "Domain":                   domain,
            "Description":              description,
            "Expected_Code":            expected_code,
            "Expected_Layer":           expected_layer,
            "Expected_Behavior_Regex":  regex,
            "Notes":                    notes,
        })
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[qa_gen] Loading graph from {GRAPH_PATH} ...")
    data = _load_graph()

    counter = [0]   # mutable int passed by reference

    all_rows: list[dict] = []

    print("[qa_gen] Generating ORA_CODE tests ...")
    all_rows += gen_ora_code_tests(data, counter)
    print(f"         → {counter[0]} rows so far")

    print("[qa_gen] Generating OS_PATTERN tests ...")
    prev = counter[0]
    all_rows += gen_os_pattern_tests(data, counter)
    print(f"         → {counter[0] - prev} new rows ({counter[0]} total)")

    print("[qa_gen] Generating Translator tests ...")
    prev = counter[0]
    all_rows += gen_translator_tests(counter)
    print(f"         → {counter[0] - prev} new rows ({counter[0]} total)")

    print("[qa_gen] Generating Tier2 PDF inference tests ...")
    prev = counter[0]
    all_rows += gen_tier2_inference_tests(data, counter)
    print(f"         → {counter[0] - prev} new rows ({counter[0]} total)")

    print("[qa_gen] Generating Domain / TIER3 / Security tests ...")
    prev = counter[0]
    all_rows += gen_domain_tests(counter)
    print(f"         → {counter[0] - prev} new rows ({counter[0]} total)")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n[qa_gen] Done. {counter[0]} test cases written to:")
    print(f"         {OUT_CSV}")

    # ── Summary stats ─────────────────────────────────────────────────────────
    from collections import Counter
    domain_counts = Counter(r["Domain"] for r in all_rows)
    type_counts   = Counter(r["Scenario_Type"] for r in all_rows)
    print("\n── Domain breakdown ─────────────────────────────────────")
    for domain, count in sorted(domain_counts.items()):
        print(f"   {domain:20s} {count:4d}")
    print("\n── Scenario type breakdown ──────────────────────────────")
    for stype, count in sorted(type_counts.items()):
        print(f"   {stype:20s} {count:4d}")


if __name__ == "__main__":
    main()
