"""
fix_domain_layers.py
--------------------
Corrects domain-specific OS_ERROR_PATTERN nodes that were incorrectly
set to OS_TRIGGERED by patch_graph_layers.py (because their categories
had no explicit mapping). Targets only the 6 known misclassifications.
"""

import json
import shutil
from datetime import datetime

GRAPH_PATH = "/Users/kommanasaisandilya/Downloads/dba_agent/src/knowledge_graph/data/graph.json"

# node_id → correct layer
CORRECTIONS = {
    "DG_APPLY_LAG":         "DATAGUARD",
    "RMAN_BACKUP_FAILED":   "RMAN",
    "CRS_RESOURCE_FAILED":  "CLUSTER",
    "ASM_DISK_DROP":        "ASM",
    "DB_CRASH_ORA_00603":   "DB",
    "DB_EVICTION_ORA_29740":"CLUSTER",
}


def fix(graph_path: str) -> None:
    print(f"[fix] Loading {graph_path} …")
    with open(graph_path, encoding="utf-8") as f:
        data = json.load(f)

    fixed = 0
    for node in data["nodes"]:
        nid = node.get("id")
        if nid in CORRECTIONS:
            old = node.get("layer", "<none>")
            new = CORRECTIONS[nid]
            node["layer"] = new
            print(f"  [~] {nid:35s}  {old} → {new}")
            fixed += 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = graph_path + f".bak_{ts}"
    shutil.copy2(graph_path, backup)
    print(f"\n[fix] Backup saved → {backup}")

    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"[fix] Done.  corrected={fixed}")


if __name__ == "__main__":
    fix(GRAPH_PATH)
