"""
patch_graph_layers.py
---------------------
Adds missing "layer" fields to OS_ERROR_PATTERN nodes in graph.json
that currently only have "category" but no explicit "layer".

Layer assignment rules:
  - DISK    category            → OS_TRIGGERED
  - MEMORY  category            → OS_TRIGGERED
  - CPU     category            → OS_TRIGGERED
  - KERNEL  category            → OS_TRIGGERED
  - NETWORK / BONDING           → NETWORK
  - NETWORK / FIREWALL          → NETWORK
  - NETWORK / NFS               → OS_TRIGGERED
  - NETWORK / NTP               → CLUSTER  (NTP skew causes RAC eviction)
"""

import json
import os
import shutil
from datetime import datetime

GRAPH_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "src", "knowledge_graph", "data", "graph.json"
)

# ── Exact layer for nodes that need special treatment ────────────────────────
EXPLICIT_LAYER: dict[str, str] = {
    # DISK
    "SCSI_DISK_TIMEOUT":        "OS_TRIGGERED",
    "FC_HBA_RESET":             "OS_TRIGGERED",
    "MULTIPATH_ALL_PATHS_DOWN": "OS_TRIGGERED",
    "IO_QUEUE_TIMEOUT":         "OS_TRIGGERED",
    "EXT4_JOURNAL_ABORT":       "OS_TRIGGERED",
    "XFS_FILESYSTEM_SHUTDOWN":  "OS_TRIGGERED",
    "FILESYSTEM_ARCH_FULL":     "OS_TRIGGERED",
    "ISCSI_SESSION_FAIL":       "OS_TRIGGERED",
    # MEMORY
    "OOM_KILLER_ACTIVE":        "OS_TRIGGERED",
    "CGROUP_OOM_KILL":          "OS_TRIGGERED",
    "SHMGET_EINVAL":            "OS_TRIGGERED",
    "HUGEPAGES_FREE_ZERO":      "OS_TRIGGERED",
    "MEMORY_SWAP_STORM":        "OS_TRIGGERED",
    "SEMAPHORE_LIMIT_EXHAUSTED":"OS_TRIGGERED",
    "FD_LIMIT_EXHAUSTED":       "OS_TRIGGERED",
    "MEMLOCK_ULIMIT_TOO_LOW":   "OS_TRIGGERED",
    # CPU
    "CPU_RUNQUEUE_SATURATION":  "OS_TRIGGERED",
    "CPU_STEAL_TIME":           "OS_TRIGGERED",
    # KERNEL
    "SOFT_LOCKUP":              "OS_TRIGGERED",
    "HARD_LOCKUP":              "OS_TRIGGERED",
    "KERNEL_PANIC":             "OS_TRIGGERED",
    "MCE_CORRECTED_MEMORY":     "OS_TRIGGERED",
    "MCE_UNCORRECTED_MEMORY":   "OS_TRIGGERED",
    "SELINUX_BLOCKING":         "OS_TRIGGERED",
    # NETWORK
    "BONDING_FAILOVER_EVENT":   "NETWORK",
    "BOTH_NICS_DOWN":           "NETWORK",
    "NF_CONNTRACK_FULL":        "NETWORK",
    "NTP_TIME_JUMP":            "CLUSTER",      # NTP skew → RAC eviction
    "IPTABLES_BLOCKING_1521":   "NETWORK",
    "NFS_MOUNT_TIMEOUT":        "OS_TRIGGERED",
}

# ── Category → layer fallback for any OTHER OS_ERROR_PATTERN nodes ────────────
CATEGORY_LAYER_MAP: dict[str, str] = {
    "DISK":    "OS_TRIGGERED",
    "MEMORY":  "OS_TRIGGERED",
    "CPU":     "OS_TRIGGERED",
    "KERNEL":  "OS_TRIGGERED",
    "NETWORK": "NETWORK",      # default for network; specific NTP override above
}


def _infer_layer(node: dict) -> str:
    """Determine the correct layer for an OS_ERROR_PATTERN node."""
    node_id = node.get("id", "")
    if node_id in EXPLICIT_LAYER:
        return EXPLICIT_LAYER[node_id]

    category = node.get("category", "")
    sub_category = node.get("sub_category", "")

    # NTP always clusters
    if sub_category == "NTP":
        return "CLUSTER"

    return CATEGORY_LAYER_MAP.get(category, "OS_TRIGGERED")


def patch(graph_path: str) -> None:
    print(f"[patch] Loading {graph_path} …")
    with open(graph_path, encoding="utf-8") as f:
        data = json.load(f)

    patched = 0
    skipped = 0

    for node in data["nodes"]:
        if node.get("type") != "OS_ERROR_PATTERN":
            continue

        if "layer" in node:
            skipped += 1
            continue  # already has layer — leave it untouched

        node["layer"] = _infer_layer(node)
        patched += 1
        print(f"  [+] {node['id']:35s} → layer = {node['layer']}")

    # ── Backup before writing ─────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = graph_path + f".bak_{ts}"
    shutil.copy2(graph_path, backup_path)
    print(f"\n[patch] Backup saved → {backup_path}")

    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"\n[patch] Done.  patched={patched}  already-had-layer={skipped}")


if __name__ == "__main__":
    patch(os.path.abspath(GRAPH_PATH))
