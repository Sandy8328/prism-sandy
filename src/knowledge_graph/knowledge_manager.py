"""
knowledge_manager.py — Implements the Dynamic Learning Loop.
Injects new DBA feedback into Qdrant (Vector DB) and graph.json (Knowledge Graph).
"""

import json
import os
import uuid
import fcntl
from datetime import datetime

from src.embeddings.embedder import embed_chunks
from src.vectordb.qdrant_client import upsert_chunks
from src.knowledge_graph.graph import _load_graph, _GRAPH_PATH

# Valid layers across the full Infra → OS → DB → Application stack
_VALID_LAYERS = {
    "INFRA", "OS_TRIGGERED", "ASM", "MEMORY", "NETWORK",
    "CLUSTER", "DB", "DATAGUARD", "RMAN", "SECURITY", "APPLICATION"
}

# Valid fix_tier values matching graph.json conventions
_VALID_FIX_TIERS = {
    "OS + Infrastructure", "OS + ASM", "OS + Database",
    "ASM", "Network", "Memory", "Cluster", "Database", "Application"
}

# Valid platforms across all parsers in the codebase
_VALID_PLATFORMS = {
    "LINUX", "AIX", "SOLARIS", "HPUX", "WINDOWS", "EXADATA", "UNKNOWN"
}

# Valid categories across the full Infra → OS → DB → Application stack
_VALID_CATEGORIES = {
    "DB", "OS", "NETWORK", "STORAGE", "MEMORY", "CLUSTER", "SECURITY", "APPLICATION"
}

def learn_new_incident(
    error_code: str,
    log_snippet: str,
    runbook_commands: list[str],
    platform: str,          # LINUX | AIX | SOLARIS | HPUX | WINDOWS | EXADATA | UNKNOWN
    category: str,          # DB | OS | NETWORK | STORAGE | MEMORY | CLUSTER | SECURITY | APPLICATION
    layer: str,             # INFRA | OS_TRIGGERED | ASM | MEMORY | NETWORK | CLUSTER | DB | DATAGUARD | RMAN | SECURITY | APPLICATION
    fix_tier: str,          # Database | OS + Infrastructure | OS + ASM | OS + Database | ASM | Network | Memory | Cluster | Application
    hostname: str = "unknown"
) -> dict:
    """
    platform : LINUX | AIX | SOLARIS | HPUX | WINDOWS | EXADATA | UNKNOWN
    category : DB | OS | NETWORK | STORAGE | MEMORY | CLUSTER | SECURITY | APPLICATION
    layer    : architectural layer (INFRA, OS_TRIGGERED, ASM, MEMORY, NETWORK,
               CLUSTER, DB, DATAGUARD, RMAN, SECURITY, APPLICATION)
    fix_tier : fix tier matching graph.json conventions
               ('OS + Infrastructure', 'OS + ASM', 'OS + Database',
                'ASM', 'Network', 'Memory', 'Cluster', 'Database', 'Application')
    """
    platform = platform.upper()
    category = category.upper()

    if platform not in _VALID_PLATFORMS:
        print(f"  [KnowledgeManager] WARNING: unknown platform '{platform}', defaulting to 'UNKNOWN'")
        platform = "UNKNOWN"
    if category not in _VALID_CATEGORIES:
        print(f"  [KnowledgeManager] WARNING: unknown category '{category}', defaulting to 'DB'")
        category = "DB"
    if layer not in _VALID_LAYERS:
        print(f"  [KnowledgeManager] WARNING: unknown layer '{layer}', defaulting to 'DB'")
        layer = "DB"
    if fix_tier not in _VALID_FIX_TIERS:
        print(f"  [KnowledgeManager] WARNING: unknown fix_tier '{fix_tier}', defaulting to 'Database'")
        fix_tier = "Database"


    # ── Step 1: Update Qdrant (Vector DB) ───────────────────────────────────

    chunk_id = f"learned_{uuid.uuid4().hex[:8]}"
    chunk = {
        "chunk_id": chunk_id,
        "platform": platform,
        "hostname": hostname,
        "log_source": "DBA_FEEDBACK",
        "timestamp_start": datetime.now().isoformat(),
        "timestamp_end": datetime.now().isoformat(),
        "category": category,
        "sub_category": "LEARNED",
        "severity": "CRITICAL",
        "ora_code": error_code,
        "os_pattern": error_code,
        "errno": "",
        "device": "",
        "keywords": [error_code],
        "raw_text": log_snippet,
        "linked_chunks": []
    }
    
    vectors = embed_chunks([chunk], show_progress=False)
    upsert_chunks([chunk], vectors)
    
    # ── Step 2: Update graph.json (Knowledge Graph) ─────────────────────────
    alt_id = "oracle_" + error_code.lower().replace("-", "_")
    new_node = {
        "id": alt_id,
        "label": "ORA_CODE",
        "layer": layer,
        "description": "Learned from DBA feedback",
        "runbook_title": f"DBA Fix for {error_code}",
        "remediation_commands": runbook_commands,
        "fix_tier": fix_tier
    }
    
    try:
        # Use file locking to prevent race conditions when updating JSON
        with open(_GRAPH_PATH, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                data = json.load(f)
                
                # Check if node already exists
                existing = False
                for node in data.get("nodes", []):
                    if node.get("id") == alt_id:
                        node["remediation_commands"] = runbook_commands
                        existing = True
                        break
                        
                if not existing:
                    data.setdefault("nodes", []).append(new_node)
                
                # Write back
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=4)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        print(f"Failed to update graph.json: {e}")
        return {"status": "error", "message": str(e)}

    # ── Step 3: Clear LRU Cache ─────────────────────────────────────────────
    _load_graph.cache_clear()
    
    # Force reload
    _load_graph()
    
    print(f"  -> [KnowledgeManager] Successfully learned {error_code} and updated Qdrant & Graph.")
    
    return {"status": "success", "chunk_id": chunk_id, "node_id": alt_id}
