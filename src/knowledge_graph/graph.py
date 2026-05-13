"""
graph.py — Loads graph.json into NetworkX and provides traversal functions.

Graph structure (from graph.json):
  Nodes: ORA_CODE, OS_ERROR_PATTERN, FIX_COMMAND
  Edges: caused_by (ORA→OS), triggered_by (OS→OS), fixed_by (OS→FIX)

Key operations:
  get_root_causes(ora_code)  → list of (OS_PATTERN, probability) sorted by prob
  get_fixes(os_pattern)      → list of (FIX_COMMAND, priority) sorted by priority
  get_cascade(pattern)       → cascade dict if pattern is a cascade root
  get_related_ora(pattern)   → other ORA codes caused by same OS pattern
"""

from __future__ import annotations
import json
import os
from functools import lru_cache
from typing import Optional
import networkx as nx

_GRAPH_PATH = os.path.join(
    os.path.dirname(__file__), "data", "graph.json"
)


@lru_cache(maxsize=1)
def _load_graph() -> tuple[nx.DiGraph, dict, list]:
    """Load graph.json and build NetworkX DiGraph. Cached after first load."""
    with open(_GRAPH_PATH) as f:
        data = json.load(f)

    G = nx.DiGraph()

    # Add nodes
    node_attrs = {}
    for node in data["nodes"]:
        nid = node["id"]
        G.add_node(nid, **node)
        node_attrs[nid] = node

    # Add edges — support both 'type' and 'relation' field names
    for edge in data["edges"]:
        edge_type = edge.get("type") or edge.get("relation", "unknown")
        G.add_edge(
            edge["source"],
            edge["target"],
            type=edge_type,
            **{k: v for k, v in edge.items() if k not in ("source", "target", "type", "relation")}
        )

    cascades = data.get("cascades", [])
    return G, node_attrs, cascades


def get_node_info(node_id: str) -> dict:
    """Generic lookup for any node (ORA_CODE, OS_PATTERN, etc.) in the graph."""
    _, node_attrs, _ = _load_graph()
    return node_attrs.get(node_id, {})


def get_root_causes(ora_code: str) -> list[dict]:
    """
    Given an ORA code, return probable OS error patterns.

    Returns:
        [{pattern_id, probability, category, severity, description}, ...]
        sorted by probability descending
    """
    G, node_attrs, _ = _load_graph()
    if ora_code not in G:
        return []

    results = []
    for _, target, edge_data in G.out_edges(ora_code, data=True):
        if edge_data.get("type") == "caused_by":
            node = node_attrs.get(target, {})
            results.append({
                "pattern_id":  target,
                "probability": edge_data.get("probability", 0.0),
                "category":    node.get("category", ""),
                "sub_category":node.get("sub_category", ""),
                "severity":    node.get("severity", "ERROR"),
                "platforms":   node.get("platforms", []),
            })

    results.sort(key=lambda x: x["probability"], reverse=True)
    return results


def get_fixes(os_pattern: str) -> list[dict]:
    """
    Given an OS error pattern, return fix commands in priority order.

    Returns:
        [{fix_id, commands, risk, requires, downtime_required, priority}, ...]
    """
    G, node_attrs, _ = _load_graph()
    if os_pattern not in G:
        return []

    results = []
    for _, target, edge_data in G.out_edges(os_pattern, data=True):
        if edge_data.get("type") == "fixed_by":
            node = node_attrs.get(target, {})
            results.append({
                "fix_id":           target,
                "commands":         node.get("commands", []),
                "risk":             node.get("risk", "MEDIUM"),
                "requires":         node.get("requires", "root"),
                "downtime_required":node.get("downtime_required", False),
                "priority":         edge_data.get("priority", 99),
            })

    results.sort(key=lambda x: x["priority"])
    return results


def get_triggered_by(os_pattern: str) -> list[dict]:
    """
    Return deeper OS patterns that trigger the given pattern.
    Used for root-cause drilling.

    Returns:
        [{pattern_id, probability, time_gap_sec}, ...]
    """
    G, node_attrs, _ = _load_graph()
    if os_pattern not in G:
        return []

    results = []
    for _, target, edge_data in G.out_edges(os_pattern, data=True):
        if edge_data.get("type") == "triggered_by":
            results.append({
                "pattern_id":  target,
                "probability": edge_data.get("probability", 0.0),
                "time_gap_sec":edge_data.get("time_gap_sec", 0),
            })
    return sorted(results, key=lambda x: x["probability"], reverse=True)


def get_related_ora_codes(os_pattern: str) -> list[str]:
    """
    Return all ORA codes that can be caused by the given OS pattern.
    (Reverse traversal of caused_by edges)
    """
    G, _, _ = _load_graph()
    results = []
    for source, target, edge_data in G.in_edges(os_pattern, data=True):
        if edge_data.get("type") == "caused_by":
            results.append(source)
    return results


def get_cascade_for_pattern(os_pattern: str) -> Optional[dict]:
    """Return cascade definition if this pattern is a known cascade root."""
    _, _, cascades = _load_graph()
    for cascade in cascades:
        if cascade.get("root_pattern") == os_pattern:
            return cascade
    return None


def get_all_cascades() -> list[dict]:
    _, _, cascades = _load_graph()
    return cascades


def get_commands_for_ora(ora_code: str) -> dict:
    """
    PRIMARY LOOKUP: Given an ORA error code, return its exact runbook commands.

    Lookup strategy (in order of priority):
      1. Check `error_code` node by label match → remediation_commands field
      2. Check `ORA_CODE` node by id match → remediation_commands field
      3. Follow HAS_FIX_COMMAND edge → FIX_COMMAND node → commands field

    Returns:
        {
            "ora_code":    str,
            "title":       str,
            "commands":    [str, ...],   # exact copy-paste commands
            "source":      str,          # where the commands came from
            "fix_node_id": str | None
        }
    """
    G, node_attrs, _ = _load_graph()

    # ── Strategy 1: error_code node (oracle_ora_XXXXX) ────────────────────
    alt_id = "oracle_" + ora_code.lower().replace("-", "_")
    if alt_id in node_attrs:
        node = node_attrs[alt_id]
        cmds = node.get("remediation_commands") or []
        if cmds:
            return {
                "ora_code":    ora_code,
                "title":       node.get("runbook_title", node.get("description", "")),
                "commands":    cmds,
                "source":      "error_code_node",
                "fix_node_id": node.get("fix_command_ref"),
            }
        oap = (node.get("oracle_action_plan") or "").strip()
        if oap:
            title = node.get("label") or node.get("description") or ora_code
            return {
                "ora_code":    ora_code,
                "title":       title,
                "commands":    [oap],
                "source":      "oracle_action_plan",
                "fix_node_id": None,
            }

    # ── Strategy 2: ORA_CODE node (id = ora_code directly) ───────────────
    if ora_code in node_attrs:
        node = node_attrs[ora_code]
        cmds = node.get("remediation_commands") or []
        if cmds:
            return {
                "ora_code":    ora_code,
                "title":       node.get("runbook_title", node.get("description", "")),
                "commands":    cmds,
                "source":      "ora_code_node",
                "fix_node_id": node.get("fix_command_ref"),
            }
        oap = (node.get("oracle_action_plan") or "").strip()
        if oap:
            title = node.get("label") or node.get("description") or ora_code
            return {
                "ora_code":    ora_code,
                "title":       title,
                "commands":    [oap],
                "source":      "oracle_action_plan",
                "fix_node_id": None,
            }

    # ── Strategy 3: HAS_FIX_COMMAND edge → FIX_COMMAND node ─────────────
    lookup_ids = [ora_code, alt_id]
    for lid in lookup_ids:
        if lid not in G:
            continue
        for _, target, edge_data in G.out_edges(lid, data=True):
            if edge_data.get("type") == "HAS_FIX_COMMAND":
                fix_node = node_attrs.get(target, {})
                cmds = fix_node.get("commands", [])
                if cmds:
                    return {
                        "ora_code":    ora_code,
                        "title":       fix_node.get("id", target),
                        "commands":    cmds,
                        "source":      f"fix_command_edge → {target}",
                        "fix_node_id": target,
                    }

    # ── No commands found ─────────────────────────────────────────────────
    return {
        "ora_code":    ora_code,
        "title":       "No runbook available",
        "commands":    [],
        "source":      "not_found",
        "fix_node_id": None,
    }


# ── fix_tier field → layer mapping ───────────────────────────────────────────
# Sourced directly from fix_tier values seen in graph.json nodes.
# Covers all compound tiers (e.g. "OS + Database" = OS is the root cause).
_FIX_TIER_LAYER_MAP: dict[str, str] = {
    "OS + Infrastructure": "OS_TRIGGERED",
    "OS + ASM":            "ASM",
    "OS + Database":       "OS_TRIGGERED",
    "ASM":                 "ASM",
    "Network":             "NETWORK",
    "Memory":              "MEMORY",
    "Cluster":             "CLUSTER",
    "Database":            "DB",
}

# ── Keyword → layer mapping ───────────────────────────────────────────────────
# Keywords are substrings of Oracle documentation language.
# First match in priority order wins. "DB" is NOT in this list — it is the
# final inference fallback inside _infer_layer_from_node(), not a default.
_LAYER_KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("MEMORY",       ["shared memory", "unable to allocate", "pga aggregate",
                      "large pool", "java pool", "streams pool", "out of memory",
                      "program global area"]),
    ("ASM",          ["diskgroup", "disk group", "automatic storage management",
                      "asm disk", "oracle asm"]),
    ("CLUSTER",      ["cluster", "node eviction", "voting disk",
                      "clusterware", "css timeout", "rac instance", "global cache"]),
    ("NETWORK",      ["tns:", "listener", "network adapter", "dead connection",
                      "socket error", "network error", "tcp"]),
    # Security / Access Control
    ("SECURITY",     ["account is locked", "password has expired",
                      "too many authentication failures",
                      "insufficient privileges", "profile limit",
                      "audit trail", "user has not logged"]),
    # DataGuard / Standby
    ("DATAGUARD",    ["standby database", "managed recovery process",
                      "archive log gap", "redo transport",
                      "apply lag", "far sync instance", "log apply stopped"]),
    # RMAN / Backup-Recovery
    ("RMAN",         ["recovery manager", "backup set",
                      "archived log not found", "catalog database",
                      "backup piece", "restore point"]),
    # OS-triggered ORA codes (disk, semaphore, hugepage, archiver)
    ("OS_TRIGGERED", ["operating system error", "semaphore", "hugepage",
                      "huge page", "shmget", "errno", "i/o error", "disk error",
                      "no space left", "file system", "archivelog destination",
                      "archiver", "synchronous i/o"]),
]


def _infer_layer_from_node(node: dict, G, node_id: str) -> str:
    """
    Infer diagnostic layer from an oracle_ora_* (error_code) node using:
      1. fix_tier field — already domain-labelled in graph.json
      2. Keyword scan of description + oracle_action_plan text
      3. Graph edge walk to neighbors with known layers
      4. domain field as structural hint

    This is called only for Tier 2 (oracle_ora_* nodes found in graph.json
    but lacking an explicit 'layer' field). Returns a layer string.
    """
    # 1. fix_tier — most reliable, already classified in graph.json
    fix_tier = node.get("fix_tier", "")
    if fix_tier in _FIX_TIER_LAYER_MAP:
        return _FIX_TIER_LAYER_MAP[fix_tier]

    # 2. Keyword scan on description + oracle_action_plan
    text = (
        node.get("description", "") + " " +
        node.get("oracle_action_plan", "")
    ).lower()
    for layer, keywords in _LAYER_KEYWORD_MAP:
        if any(kw in text for kw in keywords):
            return layer

    # 3. Graph edge walk — check if graph neighbors have a known layer
    _, node_attrs_local, _ = _load_graph()
    try:
        for neighbor_id in G.neighbors(node_id):
            neighbor = node_attrs_local.get(neighbor_id, {})
            neighbor_layer = neighbor.get("layer") or neighbor.get("category")
            if neighbor_layer and neighbor_layer not in ("UNKNOWN", "NEEDS_MORE_INFO"):
                return neighbor_layer
    except Exception:
        pass

    # 4. domain field structural hint
    domain = node.get("domain", "").lower()
    if "network" in domain:
        return "NETWORK"
    if "cluster" in domain or "rac" in domain:
        return "CLUSTER"
    if "os" in domain or "infrastructure" in domain:
        return "OS_TRIGGERED"

    # All 4 inference methods exhausted (fix_tier, keyword scan, edge walk, domain).
    # The code exists in the PDF but its layer cannot be determined from available data.
    # Returning NEEDS_MORE_INFO triggers the orchestrator to ask the user for more evidence
    # (AWR, OSW, related ORA codes) rather than producing an inaccurate classification.
    return "NEEDS_MORE_INFO"


def get_layer_for_code(code: str) -> dict:
    """
    3-tier diagnostic layer lookup for any error code.

    Tier 1 — graph.json rich ORA_CODE node:
        Direct id match with explicit 'layer' or 'category' field.
        Covers 20 production-critical codes with full runbook data.

    Tier 2 — oracle_ora_* PDF-sourced node:
        Converts "ORA-00600" → "oracle_ora_00600", looks up in graph.json,
        then infers layer via fix_tier field, keyword scan, graph edge walk,
        and domain field. Covers all 50,000+ ORA codes from the PDF.

    Tier 3 — Not found in graph.json at all:
        Returns layer = "NEEDS_MORE_INFO". The orchestrator detects this
        and asks the user to provide more evidence (AWR, OSW, related errors).

    No hardcoded defaults. No hallucination.

    Returns:
        {
            "code":     str,
            "layer":    str,   # e.g. DB / MEMORY / OS_TRIGGERED / NEEDS_MORE_INFO
            "category": str,
            "severity": str,
            "found":    bool,
            "tier":     int,   # 1, 2, or 3
        }
    """
    G, node_attrs, _ = _load_graph()

    # ── Tier 1: Direct id match (ORA_CODE node with explicit layer field) ─────
    node = node_attrs.get(code)
    if node and (node.get("layer") or node.get("category")):
        return {
            "code":     code,
            "layer":    node.get("layer") or node.get("category"),
            "category": node.get("category", node.get("layer", "")),
            "severity": node.get("severity", "UNKNOWN"),
            "found":    True,
            "tier":     1,
        }

    # ── Tier 2: oracle_ora_XXXXX node → infer layer from PDF content ──────────
    alt_id = "oracle_" + code.lower().replace("-", "_")
    node = node_attrs.get(alt_id)
    if node:
        inferred = _infer_layer_from_node(node, G, alt_id)
        return {
            "code":     code,
            "layer":    inferred,
            "category": inferred,
            "severity": node.get("severity", "UNKNOWN"),
            "found":    True,
            "tier":     2,
        }

    # ── Tier 3: Not found anywhere → chatbot must ask for more evidence ────────
    return {
        "code":     code,
        "layer":    "NEEDS_MORE_INFO",
        "category": "NEEDS_MORE_INFO",
        "severity": "UNKNOWN",
        "found":    False,
        "tier":     3,
    }



def get_ora_codes_by_description_keywords(*keywords: str) -> list[str]:
    """
    Dynamically return ORA_CODE ids whose description OR runbook_title
    contains ANY of the given keywords (case-insensitive).

    Called at import time by input_parser.py to build natural-language hint
    lists from graph.json — so adding a new ORA code to graph.json
    automatically makes it appear in NL hints without any code change.

    Args:
        *keywords: one or more lowercase keyword strings

    Returns:
        Sorted list of matching ORA code ids, e.g. ["ORA-00257", "ORA-19809"]
    """
    _, node_attrs, _ = _load_graph()
    results = []
    for node_id, node in node_attrs.items():
        if node.get("type") != "ORA_CODE":
            continue
        searchable = (
            node.get("description", "") + " " +
            node.get("runbook_title", "")
        ).lower()
        if any(kw.lower() in searchable for kw in keywords):
            results.append(node_id)
    return sorted(results)


def resolve_root_cause_chain(
    ora_code: str,
    matched_patterns: list[str],
) -> Optional[dict]:
    """
    Given an ORA code and matched OS patterns, find the best root cause.

    Strategy:
      1. Get all probable causes from graph for the ORA code
      2. Intersect with matched_patterns
      3. Pick highest probability match
      4. Drill down: check if that pattern is triggered_by another matched pattern

    Returns:
        {
          root_pattern, probability, fixes, cascade,
          causal_chain: [step1, step2, ...],
          related_ora_codes
        }
    """
    probable_causes = get_root_causes(ora_code)
    if not probable_causes:
        return None

    # Find intersection with matched patterns
    matched_set = set(matched_patterns)
    matched_causes = [c for c in probable_causes if c["pattern_id"] in matched_set]

    if not matched_causes:
        # Do not hallucinate a root cause from graph priors alone.
        # Require at least one pattern observed in current evidence.
        return None
    best = matched_causes[0]

    pattern_id = best["pattern_id"]
    fixes      = get_fixes(pattern_id)
    cascade    = get_cascade_for_pattern(pattern_id)
    related    = get_related_ora_codes(pattern_id)

    # Build causal chain
    chain = [f"OS: {pattern_id}"]
    triggered = get_triggered_by(pattern_id)
    for t in triggered[:2]:   # Max 2 levels deep
        if t["pattern_id"] in matched_set:
            chain.insert(0, f"ROOT: {t['pattern_id']}")
            break

    chain.append(f"DB: {ora_code}")

    return {
        "root_pattern":     pattern_id,
        "probability":      best["probability"],
        "category":         best.get("category", ""),
        "severity":         best.get("severity", "CRITICAL"),
        "fixes":            fixes,
        "cascade":          cascade,
        "causal_chain":     chain,
        "related_ora_codes":related,
    }
