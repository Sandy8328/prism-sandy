"""
event_correlation.py — Evidence-first event extraction and ORA correlation.

LLM is not used for correlation logic; optional Gemini may supply ORA meaning glosses
via ora_meaning_resolver when the bundled PDF extract leaves gaps.

Implements a dynamic pipeline:
  extract line/block signals → classify layer → aggregate correlation keys
  → assign ORA roles from catalog + context → build marked cascade → RCA sections

This module does not invent ORA codes; roles apply only to codes observed in text.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

from src.agent.ora_meaning_resolver import resolve_observed_ora_meaning

# Layer ordering index: lower = deeper physical root
_LAYER_DEPTH = {
    "STORAGE": 0,
    "INFRA": 0,
    "OS": 1,
    "NETWORK": 1,
    "ASM": 2,
    "CRS": 2,
    "BACKUP": 2,
    "SECURITY": 2,
    "AUDIT": 3,
    "RDBMS": 3,
    "DB": 3,
    "CLIENT": 5,
    "UNKNOWN": 9,
}

# Layers that count toward multi-layer corroboration / cross-layer score
_CORRELATION_LAYERS = frozenset(
    {
        "STORAGE",
        "INFRA",
        "OS",
        "ASM",
        "DB",
        "RDBMS",
        "NETWORK",
        "BACKUP",
        "CRS",
        "SECURITY",
        "AUDIT",
    }
)

# ORA codes that must never be promoted to incident root (locators / pointers only)
_NON_ROOT_ORA_CODES = frozenset({"ORA-00312"})

_ORA_LINE = re.compile(r"\b(ORA-\d{5})\b", re.I)
_TRACE_PATH = re.compile(r"(/[\w./]+\.(?:trc|TRC))\b")
_REDO_GROUP = re.compile(r"(?:group|GROUP)\s*[#:]?\s*(\d+)|online log\s+(\d+)\s+thread", re.I)
_ASM_DG = re.compile(r"(?:diskgroup|Diskgroup|DISKGROUP)\s+['\"]?(\w+)['\"]?|\+(\w+)\b", re.I)
_READ_FAIL_AU = re.compile(
    r"Read Failed.*?group[:\s]*(\d+).*?AU[:\s]*(\d+).*?offset[:\s]*(\d+)",
    re.I | re.S,
)
_DEVICE = re.compile(r"\b(sd[a-z]+)\b|(?:dev|mpath)(/[\w/]+)|\b(mpath[a-z0-9_]+)\b", re.I)
_CELL_SIG = re.compile(
    r"FLASH_IO_TIMEOUT|flashdisk|FlashDisk|celldisk|CellDisk|griddisk|GridDisk|CELLSRV|cellsrv|cellcli",
    re.I,
)
_LGWR_TERM = re.compile(r"LGWR.*terminating.*instance", re.I)
_LINUX_ERR = re.compile(r"Linux[-\w]*\s+Error:\s*\(?(\d+)\)?|O/S-Error:\s*\(OS\s*(\d+)\)|errno=(\d+)", re.I)

_TS_PATTERNS = [
    re.compile(
        r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?)\b"
    ),
    re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\w+\s+\d{1,2}\s+[\d:]+", re.M),
    re.compile(
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}",
        re.M,
    ),
]

# Catalog: ORA meaning is static; role is default — context may refine in assign_ora_roles
_ORA_ROLE_CATALOG: dict[str, dict[str, str]] = {
    "ORA-27072": {
        "default_role": "DB_IO_SYMPTOM",
        "meaning": "Oracle file I/O error — bridge from OS/storage to RDBMS",
    },
    "ORA-00312": {
        "default_role": "OBJECT_LOCATOR",
        "meaning": "Identifies affected online redo log member",
    },
    "ORA-00353": {
        "default_role": "FATAL_DB_SYMPTOM",
        "meaning": "Redo log corruption or unreadable redo",
    },
    "ORA-15080": {
        "default_role": "ASM_CONSEQUENCE",
        "meaning": "ASM synchronous disk I/O failure",
    },
    "ORA-15081": {
        "default_role": "ASM_CONSEQUENCE",
        "meaning": "ASM failed to submit I/O to disk",
    },
    "ORA-15130": {
        "default_role": "ASM_CONSEQUENCE",
        "meaning": "ASM diskgroup dismount / escalation",
    },
}

_PATTERN_LAYER = {
    # STORAGE / INFRA
    "EXA_FLASH_FAIL": "STORAGE",
    "EXA_CELL_IO_ERROR": "STORAGE",
    "EXA_SMART_SCAN_DISABLED": "STORAGE",
    "STORAGE_FLASH_IO_OR_MEDIA_FAILURE": "STORAGE",
    "EXA_CELL_STOP": "INFRA",
    "EXA_IB_LINK_DOWN": "INFRA",
    # OS / path / filesystem / kernel / resource
    "SCSI_DISK_TIMEOUT": "OS",
    "FC_HBA_RESET": "OS",
    "MULTIPATH_ALL_PATHS_DOWN": "OS",
    "IO_QUEUE_TIMEOUT": "OS",
    "OS_STORAGE_PATH_FAILURE": "OS",
    "EXT4_JOURNAL_ABORT": "OS",
    "XFS_FILESYSTEM_SHUTDOWN": "OS",
    "FILESYSTEM_ARCH_FULL": "OS",
    "FILESYSTEM_ANY_FULL": "OS",
    "SMARTCTL_PENDING_SECTOR": "OS",
    "ISCSI_SESSION_FAIL": "OS",
    "LVM_DEVICE_FAIL": "OS",
    "OOM_KILLER_ACTIVE": "OS",
    "CGROUP_OOM_KILL": "OS",
    "MEMORY_SWAP_STORM": "OS",
    "SHMGET_EINVAL": "OS",
    "HUGEPAGES_FREE_ZERO": "OS",
    "SEMAPHORE_LIMIT_EXHAUSTED": "OS",
    "FD_LIMIT_EXHAUSTED": "OS",
    "MEMLOCK_ULIMIT_TOO_LOW": "OS",
    "DEVSHM_TOO_SMALL": "OS",
    "THP_LATENCY_STALL": "OS",
    "CPU_RUNQUEUE_SATURATION": "OS",
    "CPU_STEAL_TIME": "OS",
    "SOFT_LOCKUP": "OS",
    "HARD_LOCKUP": "OS",
    "KERNEL_PANIC": "OS",
    "MCE_CORRECTED_MEMORY": "OS",
    "MCE_UNCORRECTED_MEMORY": "OS",
    "KERNEL_NULL_PTR_DEREF": "OS",
    "SELINUX_BLOCKING": "OS",
    "NTP_TIME_JUMP": "OS",
    # NETWORK
    "BONDING_FAILOVER_EVENT": "NETWORK",
    "BOTH_NICS_DOWN": "NETWORK",
    "NF_CONNTRACK_FULL": "NETWORK",
    "IB_LINK_DEGRADED": "NETWORK",
    "IPTABLES_BLOCKING_1521": "NETWORK",
    "NFS_MOUNT_TIMEOUT": "NETWORK",
    "UDP_BUFFER_OVERFLOW": "NETWORK",
    "SOCKET_EXHAUSTION": "NETWORK",
    # ASM
    "ASM_DISMOUNT_CRITICAL": "ASM",
    # Generic ORA extractors (not physical roots)
    "ORA_ANY_GENERIC": "DB",
    "GENERIC_ORA_EXTRACT": "DB",
}

_OS_PATH_PATTERN_IDS = frozenset(
    {"SCSI_DISK_TIMEOUT", "FC_HBA_RESET", "MULTIPATH_ALL_PATHS_DOWN", "IO_QUEUE_TIMEOUT"}
)
# Semantic group for collapsing multiple path signals → OS_STORAGE_PATH_FAILURE.
# Long-term: move "semantic_group": "OS_STORAGE_PATH" into patterns.json metadata.


def _normalize_layer(layer: str) -> str:
    value = (layer or "").strip().upper()
    if not value:
        return "UNKNOWN"
    aliases = {
        "DATABASE": "DB",
        "RDBMS": "DB",
        "CELL": "STORAGE",
        "EXADATA": "STORAGE",
        "INFRASTRUCTURE": "INFRA",
        "KERNEL": "OS",
        "LINUX": "OS",
        "AIX": "OS",
        "FILESYSTEM": "OS",
        "SOLARIS": "OS",
        "CLUSTER": "CRS",
        "CLUSTERWARE": "CRS",
    }
    value = aliases.get(value, value)
    return value if value in _LAYER_DEPTH else "UNKNOWN"


def _layer_from_category(category: str) -> str:
    c = (category or "").upper()
    if not c:
        return "UNKNOWN"
    if any(x in c for x in ("EXADATA", "CELL", "CELLDISK", "GRIDDISK", "FLASH", "STORAGE")):
        return "STORAGE"
    if any(x in c for x in ("ASM", "DISKGROUP")):
        return "ASM"
    if any(x in c for x in ("CRS", "CSS", "CLUSTER", "OCR", "VOTING")):
        return "CRS"
    if any(x in c for x in ("NETWORK", "TNS", "LISTENER", "SCAN", "VIP", "NFS", "TCP", "UDP")):
        return "NETWORK"
    if any(x in c for x in ("RMAN", "BACKUP", "ARCHIVE", "ARCHIVER")):
        return "BACKUP"
    if any(
        x in c
        for x in (
            "KERNEL",
            "SCSI",
            "MULTIPATH",
            "HBA",
            "FILESYSTEM",
            "CPU",
            "MEMORY",
            "OOM",
            "SWAP",
        )
    ):
        return "OS"
    if any(
        x in c
        for x in (
            "ORA",
            "REDO",
            "CONTROLFILE",
            "DATAFILE",
            "UNDO",
            "RECOVERY",
            "DATABASE",
        )
    ):
        return "DB"
    return "UNKNOWN"


def _layer_for_pattern(pattern_id: str) -> str:
    """
    Resolve pattern_id → logical layer. Unknown / unmapped patterns return UNKNOWN — never OS by default.
    """
    pid = (pattern_id or "").strip().upper()
    if not pid:
        return "UNKNOWN"
    if pid in _PATTERN_LAYER:
        return _PATTERN_LAYER[pid]
    try:
        from src.knowledge_graph.graph import get_node_info

        node = get_node_info(pid) or {}
        raw_layer = (
            node.get("layer")
            or node.get("source_layer")
            or node.get("component_layer")
            or ""
        )
        if str(raw_layer).strip():
            return _normalize_layer(str(raw_layer))
        category = (
            node.get("category")
            or node.get("sub_category")
            or node.get("family")
            or ""
        )
        inferred = _layer_from_category(str(category))
        if inferred != "UNKNOWN":
            return inferred
    except Exception:
        pass
    return "UNKNOWN"


def _event_layer(e: dict[str, Any]) -> str:
    """
    Derive a single logical layer from a correlation event dict (line-scan or normalized).
    Uses explicit fields first; never defaults to OS without evidence.
    """
    raw = e.get("layer") or e.get("source_layer") or e.get("component_layer") or ""
    if str(raw).strip():
        ly0 = _normalize_layer(str(raw).strip())
        if ly0 != "UNKNOWN":
            return ly0
    ctype = (e.get("code_type") or "").strip().upper()
    code = (e.get("code") or "").strip()
    code_u = code.upper()
    if ctype == "ORA" and re.match(r"^ORA-\d{5}$", code, re.I):
        return "DB"
    if ctype == "TNS" or code_u.startswith("TNS-") or (code and re.match(r"^TNS-\d+", code, re.I)):
        return "NETWORK"
    if code and ctype and ctype != "ORA":
        type_map = {
            "STORAGE_PATTERN": "STORAGE",
            "STORAGE": "STORAGE",
            "OS_PATTERN": "OS",
            "ASM_PATTERN": "ASM",
            "CRS": "CRS",
            "CRS_PATTERN": "CRS",
            "SECURITY_PATTERN": "SECURITY",
            "AUDIT_PATTERN": "AUDIT",
            "TNS": "NETWORK",
        }
        if ctype in type_map:
            return type_map[ctype]
        if ctype.endswith("_PATTERN") and code:
            return _layer_for_pattern(code)
    if e.get("oracle_codes"):
        return "DB"
    prev = (e.get("preview") or "")[:800]
    if _CELL_SIG.search(prev) or "FLASH_IO_TIMEOUT" in prev.upper():
        return "STORAGE"
    return "UNKNOWN"


def _collect_merged_layer_set(
    parsed_layers: list[str],
    events: list[dict[str, Any]],
    direct: list[str],
) -> set[str]:
    """Union of parser-reported layers, per-event layers, and direct pattern layers."""
    s: set[str] = set()
    for x in parsed_layers or []:
        if x and str(x).strip():
            ly = _normalize_layer(str(x).strip())
            if ly != "UNKNOWN":
                s.add(ly)
    for e in events or []:
        ly = _event_layer(e)
        if ly != "UNKNOWN":
            s.add(ly)
    for pid in direct or []:
        ly = _layer_for_pattern(pid)
        if ly != "UNKNOWN":
            s.add(ly)
    return s


def _parse_ts(line: str) -> datetime | None:
    for pat in _TS_PATTERNS:
        m = pat.search(line)
        if not m:
            continue
        try:
            return date_parser.parse(m.group(0), fuzzy=True)
        except (ValueError, TypeError):
            continue
    return None


def _classify_layer(line: str) -> str:
    u = line.upper()
    if _CELL_SIG.search(line) or "FLASH_IO_TIMEOUT" in u or "MEDIA READ RETRIES" in u:
        return "STORAGE"
    if "ASM" in u or "DISKGROUP" in u or "+DATA" in line or "ORA-150" in u or "ORA-151" in u:
        return "ASM"
    if _LGWR_TERM.search(line) or "ORA-" in u or "ERRORS IN FILE" in u:
        return "DB"
    if (
        "KERNEL:" in u
        or "DMESG" in u
        or "MULTIPATHD" in u
        or "QLA2XXX" in u
        or "LPFC" in u
        or "BLK_UPDATE_REQUEST" in u
        or "I/O ERROR" in u
        or "SCSI" in u
    ):
        return "OS"
    if "TNS-" in u or "LISTENER" in u:
        return "NETWORK"
    if "RMAN" in u or "BACKUP" in u:
        return "BACKUP"
    return "UNKNOWN"


def _extract_process(line: str) -> str:
    for p in ("LGWR", "DBWR", "CKPT", "ARC", "PMON", "SMON", "MMON", "ASMB", "LMD", "LMON", "LMS"):
        m = re.search(rf"\b({p}\d*)\b", line, re.I)
        if m:
            return m.group(1)
    return ""


def _ts_from_normalized_value(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return date_parser.parse(val, fuzzy=True)
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def correlation_events_from_normalized(
    normalized: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Map normalized evidence schema rows into the lightweight correlation event dicts
    used by extract_events / timeline / key aggregation.
    """
    out: list[dict[str, Any]] = []
    for i, ev in enumerate(normalized or []):
        layer_raw = (ev.get("layer") or "UNKNOWN").strip().upper()
        if layer_raw == "INFRA" and (ev.get("cell") or ev.get("flash_disk")):
            layer_raw = "STORAGE"
        if layer_raw == "RDBMS":
            layer_raw = "DB"
        code = (ev.get("code") or "").strip()
        ctype = (ev.get("code_type") or "").strip().upper()
        oracle_codes: list[str] = []
        if ctype == "ORA" and re.match(r"^ORA-\d{5}$", code, re.I):
            oracle_codes = [code.upper()]
        layer_norm = _normalize_layer(layer_raw)
        if oracle_codes:
            layer_norm = "DB"
        elif layer_norm == "UNKNOWN" and ctype == "STORAGE_PATTERN":
            layer_norm = "STORAGE"
        elif layer_norm == "UNKNOWN" and ctype == "OS_PATTERN":
            layer_norm = "OS"
        elif layer_norm == "UNKNOWN" and ctype == "ASM_PATTERN":
            layer_norm = "ASM"
        elif layer_norm == "UNKNOWN" and (ctype == "TNS" or re.match(r"^TNS-\d+", code, re.I)):
            layer_norm = "NETWORK"
        ff = (ev.get("failure_family") or "").strip()
        if layer_norm == "UNKNOWN" and ff:
            lyff = _layer_from_category(ff)
            if lyff != "UNKNOWN":
                layer_norm = lyff
        raw = ev.get("raw") or ""
        preview = (ev.get("preview") or raw)[:220]
        if len(raw) > 220 and not str(preview).endswith("…"):
            preview = preview + "…"
        line_ix = max(0, int(ev.get("line_number") or (i + 1)) - 1)
        ts_sort = _ts_from_normalized_value(ev.get("timestamp"))
        ts_raw = str(ev.get("timestamp_raw") or ev.get("timestamp") or "")
        out.append(
            {
                "event_id": ev.get("event_id") or f"ne_{i}",
                "line_index": line_ix,
                "timestamp_raw": ts_raw,
                "timestamp_sort": ts_sort,
                "source_layer": layer_norm,
                "code_type": ctype,
                "code": code,
                "process": (ev.get("process") or "")[:64],
                "oracle_codes": oracle_codes,
                "linux_errno": str(ev.get("os_errno") or ""),
                "trace_file": (ev.get("trace_file") or "")[:512],
                "diskgroup": (ev.get("diskgroup") or "")[:64],
                "asm_au": str(ev.get("au") or ""),
                "asm_offset": str(ev.get("offset") or ""),
                "device": (ev.get("device") or ev.get("multipath_device") or "")[:64],
                "severity": (ev.get("severity") or "ERROR").upper(),
                "preview": preview,
            }
        )
    return out


def merge_extract_events_with_normalized(
    raw_text: str,
    normalized: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    Prefer unified normalized evidence when present; merge in legacy line scan for gaps.
    """
    ne = correlation_events_from_normalized(normalized or [])
    legacy = extract_events(raw_text)
    if not ne:
        return legacy
    seen: set[tuple] = set()
    merged: list[dict[str, Any]] = []
    for e in ne + legacy:
        key = (
            e.get("line_index"),
            tuple(e.get("oracle_codes") or []),
            (e.get("preview") or "")[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
    return merged


def extract_events(raw_text: str) -> list[dict[str, Any]]:
    """Convert non-empty lines into lightweight event records."""
    events: list[dict[str, Any]] = []
    for i, line in enumerate((raw_text or "").splitlines()):
        s = line.strip()
        if len(s) < 8:
            continue
        layer = _classify_layer(s)
        oras = list(dict.fromkeys(_ORA_LINE.findall(s)))
        if not oras and layer == "UNKNOWN" and not _CELL_SIG.search(s):
            continue
        m_trace = _TRACE_PATH.search(s)
        m_dev = _DEVICE.search(s)
        m_dg = _ASM_DG.search(s)
        m_rf = _READ_FAIL_AU.search(s)
        le = _LINUX_ERR.search(s)
        ts = _parse_ts(s)
        ts_raw = ""
        for pat in _TS_PATTERNS:
            mm = pat.search(s)
            if mm:
                ts_raw = mm.group(0)
                break
        events.append(
            {
                "event_id": f"e{i}",
                "line_index": i,
                "timestamp_raw": ts_raw,
                "timestamp_sort": ts,
                "source_layer": layer,
                "process": _extract_process(s),
                "oracle_codes": oras,
                "linux_errno": (le.group(1) or le.group(2) or le.group(3) if le else ""),
                "trace_file": m_trace.group(1) if m_trace else "",
                "diskgroup": (m_dg.group(1) or m_dg.group(2) or "") if m_dg else "",
                "asm_au": m_rf.group(2) if m_rf else "",
                "asm_offset": m_rf.group(3) if m_rf else "",
                "device": (m_dev.group(1) or m_dev.group(2) or m_dev.group(3) or "") if m_dev else "",
                "severity": "CRITICAL" if any(x in s.upper() for x in ("FATAL", "TERMINATING", "FAILED")) else "ERROR",
                "preview": s[:220] + ("…" if len(s) > 220 else ""),
            }
        )
    return events


def _aggregate_keys(events: list[dict[str, Any]]) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {
        "devices": set(),
        "diskgroups": set(),
        "trace_files": set(),
        "processes": set(),
        "oras": set(),
        "layers": set(),
    }
    for e in events:
        keys["layers"].add(_event_layer(e))
        if e.get("device"):
            keys["devices"].add(e["device"])
        if e.get("diskgroup"):
            keys["diskgroups"].add(e["diskgroup"])
        if e.get("trace_file"):
            keys["trace_files"].add(e["trace_file"])
        if e.get("process"):
            keys["processes"].add(e["process"])
        for o in e.get("oracle_codes") or []:
            keys["oras"].add(o)
    return keys


def _correlation_key_for_ora(ora: str, keys: dict[str, set[str]], events: list[dict[str, Any]]) -> str:
    parts = []
    if keys["devices"]:
        parts.append(f"device={','.join(sorted(keys['devices']))}")
    if keys["diskgroups"] and ora.upper().startswith("ORA-15"):
        parts.append(f"diskgroup={','.join(sorted(keys['diskgroups']))}")
    if keys["trace_files"]:
        parts.append(f"trace={','.join(sorted(keys['trace_files']))}")
    if keys["processes"] and ora in {"ORA-00353", "ORA-00312", "ORA-27072"}:
        parts.append(f"process={','.join(sorted(keys['processes']))}")
    if keys["layers"]:
        parts.append(f"layers={','.join(sorted(keys['layers']))}")
    # Same-line hints
    for e in events:
        if ora in (e.get("oracle_codes") or []):
            if e.get("asm_au"):
                parts.append(f"AU={e['asm_au']}")
            break
    return "; ".join(parts) if parts else "time_window + log co-location"


def _refine_ora_role(
    ora: str,
    default_role: str,
    observed_layers: set[str],
    has_storage_signal: bool,
    has_os_signal: bool,
) -> str:
    if ora == "ORA-27072":
        if has_storage_signal or has_os_signal:
            return "DB_IO_SYMPTOM"
        if observed_layers <= {"DB", "RDBMS"} or observed_layers == {"DB"}:
            return "DB_IO_SYMPTOM"
    return default_role


def _build_observed_ora_correlation_table(
    observed_oras: list[str],
    events: list[dict[str, Any]],
    keys: dict[str, set[str]],
    observed_layers: list[str],
    has_storage: bool,
    has_os: bool,
) -> list[dict[str, Any]]:
    """Observed ORA codes only — never LGWR or pattern names (those go to non_ora_correlated_events)."""
    ol = set(observed_layers or [])
    rows = []
    for ora in observed_oras:
        cat = _ORA_ROLE_CATALOG.get(ora, {})
        role = _refine_ora_role(
            ora,
            cat.get("default_role", "POSSIBLY_RELATED"),
            ol,
            has_storage,
            has_os,
        )
        meaning = resolve_observed_ora_meaning(ora, cat.get("meaning"))
        ev_preview = ""
        for e in events:
            if ora in (e.get("oracle_codes") or []):
                ev_preview = e.get("preview", "")
                break
        rows.append(
            {
                "row_kind": "ORA_CODE",
                "error": ora,
                "layer": "ASM"
                if ora.startswith("ORA-150") or ora.startswith("ORA-151")
                else ("RDBMS" if ora.startswith("ORA-003") or ora == "ORA-27072" else "DB"),
                "role": role,
                "meaning": meaning,
                "evidence_preview": ev_preview or "(ORA referenced in evidence text)",
                "correlation_key": _correlation_key_for_ora(ora, keys, events),
                "confidence_note": "Stronger if same device/diskgroup/trace appears across layers.",
            }
        )
    return rows


def _build_non_ora_correlated_events(
    events: list[dict[str, Any]],
    direct_patterns: list[str],
    keys: dict[str, set[str]],
    has_storage_ev: bool,
) -> list[dict[str, Any]]:
    """Process termination, storage signals, and matched OS/infra patterns — not ORA codes."""
    rows: list[dict[str, Any]] = []
    if _LGWR_TERM.search("\n".join(e["preview"] for e in events)):
        rows.append(
            {
                "row_kind": "NON_ORA_EVENT",
                "event": "LGWR_INSTANCE_TERMINATION",
                "layer": "DB",
                "role": "FINAL_IMPACT",
                "meaning": "Instance termination due to fatal error — not an ORA code.",
                "evidence_preview": next(
                    (e["preview"] for e in events if _LGWR_TERM.search(e["preview"])),
                    "",
                ),
                "correlation_key": "process=LGWR; co-locate with ORA-00353/redo context in evidence",
                "confidence_note": "Do not label this row as an ORA code.",
            }
        )
    seen_flash = False
    for e in events:
        if _event_layer(e) == "STORAGE" and "FLASH_IO_TIMEOUT" in e.get("preview", "").upper():
            if not seen_flash:
                seen_flash = True
                rows.append(
                    {
                        "row_kind": "STORAGE_SIGNAL",
                        "event": "FLASH_IO_TIMEOUT",
                        "layer": "STORAGE",
                        "role": "ROOT_CAUSE"
                        if has_storage_ev
                        else "POSSIBLY_RELATED",
                        "meaning": "Storage/flash I/O timeout signal from evidence text.",
                        "evidence_preview": e.get("preview", ""),
                        "correlation_key": "storage layer text; align with cell/array logs",
                        "confidence_note": "Treat as root-class signal only when corroborated across layers.",
                    }
                )
    for pid in dict.fromkeys(direct_patterns or []):
        if pid in ("ORA_ANY_GENERIC", "GENERIC_ORA_EXTRACT"):
            continue
        layer = _layer_for_pattern(pid)
        role = (
            "INTERMEDIATE_CAUSE"
            if layer in ("OS", "STORAGE")
            else "INTERMEDIATE_CAUSE"
        )
        if pid in {"EXA_FLASH_FAIL", "EXA_CELL_IO_ERROR"}:
            role = "ROOT_CAUSE"
        rows.append(
            {
                "row_kind": "PATTERN_MATCH",
                "event": pid,
                "layer": layer,
                "role": role,
                "meaning": f"Regex/pattern match in uploaded evidence: {pid}",
                "evidence_preview": "(matched in direct input / chunk text)",
                "correlation_key": "; ".join(
                    x
                    for x in (
                        f"devices={','.join(sorted(keys['devices']))}" if keys["devices"] else "",
                        f"layers={','.join(sorted(keys['layers']))}" if keys["layers"] else "",
                    )
                    if x
                )
                or "pattern + log co-location",
                "confidence_note": "Pattern is not an ORA code; use with ORA/device context.",
            }
        )
    return rows


def _deepest_pattern_root(direct_pattern_ids: list[str]) -> tuple[str, str, int]:
    best = ""
    best_layer = "UNKNOWN"
    best_depth = 99
    for pid in direct_pattern_ids or []:
        layer = _layer_for_pattern(pid)
        d = _LAYER_DEPTH.get(layer, 9)
        if d < best_depth:
            best_depth = d
            best = pid
            best_layer = layer
    return best, best_layer, best_depth


def _ora_cascade_sort_key(ora: str) -> tuple[int, str]:
    u = ora.upper()
    if u.startswith("ORA-150") or u.startswith("ORA-151"):
        return (0, u)
    if u == "ORA-27072":
        return (1, u)
    if u.startswith("ORA-003"):
        return (2, u)
    return (3, u)


def _build_marked_cascade(
    direct_patterns: list[str],
    causal_chain_existing: list[str],
    observed_layers: list[str],
    has_storage_events: bool,
    observed_oras: list[str] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Build cascade with [INFERRED]/[NEEDS_EVIDENCE] markers; prefer observed ordering."""
    out: list[str] = []
    ol = set(observed_layers or [])
    oras = list(observed_oras or [])
    evs = list(events or [])

    # ASM/DB symptoms without storage/cell confirmation
    if (
        not has_storage_events
        and not any(p in (direct_patterns or []) for p in ("EXA_FLASH_FAIL", "EXA_CELL_IO_ERROR"))
        and any(o.upper().startswith(("ORA-150", "ORA-151")) for o in oras)
    ):
        out.append("[NEEDS_EVIDENCE: storage/cell/SAN logs to confirm deepest backend root]")

    # Deepest storage label from patterns or events
    root_pat, root_layer, _ = _deepest_pattern_root(direct_patterns)
    if has_storage_events or root_pat in {"EXA_FLASH_FAIL", "EXA_CELL_IO_ERROR"}:
        label = (
            "STORAGE_FLASH_IO_OR_MEDIA_FAILURE"
            if has_storage_events
            else root_pat
        )
        out.append(f"{label} [CONFIRMED]")
    elif root_pat and root_layer == "STORAGE":
        out.append(f"{root_pat} [CONFIRMED]")
    elif "INFRA" in ol or has_storage_events:
        out.append("STORAGE/INFRA [CONFIRMED]")
    else:
        if {"ORA-27072", "ORA-15080", "ORA-15130"} & set(
            x for step in causal_chain_existing for x in step.split() if x.startswith("ORA-")
        ):
            out.append("[NEEDS_EVIDENCE: storage/cell/SAN logs to confirm deepest root]")

    for pid in ["SCSI_DISK_TIMEOUT", "FC_HBA_RESET", "MULTIPATH_ALL_PATHS_DOWN", "IO_QUEUE_TIMEOUT"]:
        if pid in direct_patterns:
            tag = "[CONFIRMED]" if "OS" in ol else "[INFERRED]"
            out.append(f"{pid} {tag}")

    for step in causal_chain_existing:
        if step.startswith(("DB:", "ROOT:", "OS:", "ASM:")):
            if "[NEEDS_EVIDENCE" in step:
                out.append(step)
            else:
                out.append(f"{step} [CONFIRMED]")

    # Evidence-first path: legacy causal_chain is often empty — synthesize from ORAs + LGWR
    if not causal_chain_existing and oras:
        for ora in sorted(set(oras), key=_ora_cascade_sort_key):
            tag = "ASM" if ora.upper().startswith(("ORA-150", "ORA-151")) else "DB"
            out.append(f"{tag}: {ora} [CONFIRMED]")
    if evs and any(_LGWR_TERM.search((e.get("preview") or "")) for e in evs):
        if not any("LGWR_INSTANCE_TERMINATION" in s for s in out):
            out.append("DB: LGWR_INSTANCE_TERMINATION [CONFIRMED]")

    if "OS" not in ol and any(
        p in (direct_patterns or []) for p in ("SCSI_DISK_TIMEOUT", "FC_HBA_RESET", "MULTIPATH_ALL_PATHS_DOWN")
    ):
        out.append("[INFERRED: OS path symptoms from pattern match — confirm with host logs]")

    return out


def _has_object_process_correlation(keys: dict[str, set[str]]) -> bool:
    if keys.get("devices") or keys.get("diskgroups"):
        return True
    return bool(keys.get("trace_files") and keys.get("processes"))


def _root_status(
    observed_layers: list[str],
    correlated_score: float,
    multi_layer: bool,
    keys: dict[str, set[str]],
    has_storage_ev: bool,
    has_os_ev: bool,
    observed_oras: list[str],
    direct_patterns: list[str],
) -> str:
    """
    Evidence-gated status — never CONFIRMED from time proximity alone.
    """
    ol = set(observed_layers or [])
    obj = _has_object_process_correlation(keys)
    downstream_oracle = "DB" in ol or "RDBMS" in ol or bool(observed_oras)
    downstream_asm = any(
        o.upper().startswith("ORA-150") or o.upper().startswith("ORA-151") for o in observed_oras
    )
    deepest_storage = has_storage_ev or "STORAGE" in ol
    deepest_os_infra = "OS" in ol or "INFRA" in ol or "NETWORK" in ol

    if multi_layer and correlated_score >= 65 and obj and downstream_oracle:
        if deepest_storage and ("DB" in ol or downstream_asm or "RDBMS" in ol):
            return "CONFIRMED"
        if deepest_os_infra and ("DB" in ol or downstream_asm or "RDBMS" in ol):
            return "CONFIRMED"
        if "ASM" in ol and ("DB" in ol or "RDBMS" in ol or downstream_asm):
            return "CONFIRMED"
    if multi_layer and correlated_score >= 50:
        return "LIKELY"
    if downstream_oracle and (deepest_os_infra or deepest_storage):
        return "LIKELY" if correlated_score >= 38 else "SUSPECTED"
    if observed_oras or direct_patterns:
        return "SUSPECTED"
    if ol:
        return "SUSPECTED"
    return "UNKNOWN"


def _correlation_strength_score(
    events: list[dict[str, Any]],
    keys: dict[str, set[str]],
    observed_layers: list[str],
) -> float:
    """
    Weighted corroboration score (0-100), separate from retrieval confidence.
    time:15, process:15, object:20, device/asm:20, cross-layer:20, ordering:10
    """
    ol = set(observed_layers or [])
    score = 0.0
    if len(events) >= 2:
        score += 8.0
    ts_ok = sum(1 for e in events if e.get("timestamp_sort"))
    if ts_ok >= 2:
        score += 15.0
    elif ts_ok == 1:
        score += 7.0
    if keys["processes"]:
        score += min(15.0, 5.0 + 5.0 * min(len(keys["processes"]), 2))
    obj_n = len(keys["diskgroups"]) + len(keys["trace_files"])
    if obj_n:
        score += min(20.0, 10.0 * min(obj_n, 2))
    if keys["devices"] or keys["diskgroups"]:
        score += min(20.0, 10.0 + 5.0 * min(len(keys["devices"]) + len(keys["diskgroups"]), 3))
    if len(ol.intersection(_CORRELATION_LAYERS)) >= 2:
        score += 20.0
    elif len(ol) >= 2:
        score += 12.0
    # Layer ordering: reward STORAGE before OS before DB signals
    if "STORAGE" in keys["layers"] or "STORAGE" in ol or "INFRA" in ol:
        score += 10.0
    elif "ASM" in ol and "DB" in ol:
        score += 7.0
    elif "OS" in ol and "DB" in ol:
        score += 7.0
    elif "DB" in ol:
        score += 3.0
    return min(100.0, score)


def build_event_correlation_analysis(
    parsed_input: dict[str, Any],
    fused_results: list[dict[str, Any]],
    root_cause_chain: dict[str, Any] | None,
    best_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Build rca_framework-style structures from raw evidence only.
    """
    text = parsed_input.get("raw_input") or ""
    norm = parsed_input.get("normalized_events")
    events = merge_extract_events_with_normalized(text, norm if isinstance(norm, list) else None)
    keys = _aggregate_keys(events)
    parsed_layers_in = list(parsed_input.get("observed_layers") or [])
    direct = list(parsed_input.get("direct_pattern_ids") or [])
    observed_oras = list(dict.fromkeys(parsed_input.get("all_ora_codes") or []))

    layer_set = _collect_merged_layer_set(parsed_layers_in, events, direct)
    observed_layers = sorted(layer_set)
    ol = layer_set

    has_storage_ev = "STORAGE" in layer_set
    has_os_ev = "OS" in layer_set

    corr_score = _correlation_strength_score(events, keys, observed_layers)
    multi_layer = len(ol.intersection(_CORRELATION_LAYERS)) >= 2
    status = _root_status(
        observed_layers,
        corr_score,
        multi_layer,
        keys,
        has_storage_ev,
        has_os_ev,
        observed_oras,
        direct,
    )

    deepest_pat, deepest_layer, _ = _deepest_pattern_root(direct)
    legacy_root = (root_cause_chain or {}).get("root_pattern", "") or (best_candidate or {}).get(
        "pattern_id", ""
    )
    os_path_ids = [
        p for p in direct if p in _OS_PATH_PATTERN_IDS and _layer_for_pattern(p) == "OS"
    ]

    if has_storage_ev or legacy_root in {"EXA_FLASH_FAIL", "EXA_CELL_IO_ERROR"} or deepest_pat in {
        "EXA_FLASH_FAIL",
        "EXA_CELL_IO_ERROR",
    }:
        root_label = "STORAGE_FLASH_IO_OR_MEDIA_FAILURE"
        root_layer_eff = "STORAGE"
    elif deepest_layer == "STORAGE" and deepest_pat:
        root_label = deepest_pat
        root_layer_eff = "STORAGE"
    elif deepest_layer == "OS" and deepest_pat and has_os_ev:
        if len(os_path_ids) >= 2:
            root_label = "OS_STORAGE_PATH_FAILURE"
        else:
            root_label = deepest_pat
        root_layer_eff = "OS"
    elif deepest_pat and deepest_layer != "UNKNOWN":
        root_label = deepest_pat
        root_layer_eff = deepest_layer
    elif legacy_root:
        root_label = legacy_root
        lyr = _layer_for_pattern(legacy_root)
        if lyr == "UNKNOWN" and legacy_root.upper().startswith(("ORA-150", "ORA-151")):
            lyr = "ASM"
        root_layer_eff = lyr
    elif observed_oras:
        up = {o.upper() for o in observed_oras}
        cand = [o for o in observed_oras if o.upper() not in _NON_ROOT_ORA_CODES]
        if not cand:
            root_label = "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT"
            root_layer_eff = "DB"
        elif (
            {"ORA-27072", "ORA-00353", "ORA-00312"} <= up
            and not has_storage_ev
            and not has_os_ev
            and not os_path_ids
            and not any(o.upper().startswith(("ORA-150", "ORA-151")) for o in observed_oras)
        ):
            root_label = "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE"
            root_layer_eff = "DB"
        else:
            skip_27072_as_root = bool(
                os_path_ids
                or has_os_ev
                or any(o.upper().startswith(("ORA-150", "ORA-151")) for o in observed_oras)
            )
            cand2 = [o for o in cand if not (skip_27072_as_root and o.upper() == "ORA-27072")]
            pick = cand2[0] if cand2 else (cand[0] if cand else observed_oras[0])
            root_label = pick
            root_layer_eff = (
                "ASM" if pick.upper().startswith(("ORA-150", "ORA-151")) else "DB"
            )
    else:
        root_label = "NEEDS_MORE_INFO"
        root_layer_eff = "UNKNOWN"

    if root_label == "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT":
        status = "NEEDS_MORE_INFO"

    if root_layer_eff == "UNKNOWN":
        corr_score = min(float(corr_score), 45.0)
        if status == "CONFIRMED":
            status = "NEEDS_MORE_INFO"
    chain_existing = list((root_cause_chain or {}).get("causal_chain") or [])
    cascade_marked = _build_marked_cascade(
        direct, chain_existing, observed_layers, has_storage_ev, observed_oras, events
    )

    ora_table = _build_observed_ora_correlation_table(
        observed_oras, events, keys, observed_layers, has_storage_ev, has_os_ev
    )
    non_ora_table = _build_non_ora_correlated_events(events, direct, keys, has_storage_ev)

    affected = {
        "hostname": parsed_input.get("hostname") or "",
        "platform": parsed_input.get("platform") or "",
        "devices": sorted(keys["devices"]),
        "diskgroups": sorted(keys["diskgroups"]),
        "trace_files": sorted(keys["trace_files"])[:12],
        "processes": sorted(keys["processes"]),
        "observed_ora_codes": observed_oras,
    }

    timeline = sorted(
        [
            {
                "timestamp": e.get("timestamp_raw") or "(no parseable ts)",
                "source": "uploaded_evidence",
                "layer": _event_layer(e),
                "event": ", ".join(e.get("oracle_codes") or []) or e["preview"][:80],
                "preview": e["preview"],
                "linked_to": _correlation_key_for_ora(
                    (e.get("oracle_codes") or ["*"])[0], keys, events
                ),
            }
            for e in events
        ],
        key=lambda r: r["timestamp"],
    )

    conf_expl = (
        f"Correlation model score ≈ {corr_score:.0f}/100 based on shared keys across layers "
        f"(time/process/object/device/diskgroup). "
        f"Observed layers: {', '.join(observed_layers) or 'none'}. "
    )
    if not multi_layer:
        conf_expl += "Multi-layer corroboration is limited — treat lower-layer root as SUSPECTED until OS/ASM/infra logs align."
    if root_layer_eff == "UNKNOWN":
        conf_expl += " Root layer UNKNOWN — correlation score capped; add lower-layer logs and pattern metadata."
    if has_storage_ev:
        conf_expl += " Storage/cell-class signals present — prefer STORAGE as deepest confirmed class when patterns match."
    elif has_os_ev and "DB" in ol:
        conf_expl += " OS + DB signals present — root may be OS path or deeper storage; add cell/array logs if I/O-wide."
    if root_layer_eff == "OS" and os_path_ids:
        conf_expl += (
            " Deepest confirmed RCA is anchored at the OS/host path (multipath/HBA/disk); "
            "ORA-27072 is treated as a downstream symptom when OS path patterns are present."
        )

    exec_summary = (
        f"Incident analysis from uploaded evidence only. "
        f"Primary technical signal: {root_label} ({root_layer_eff}). "
        f"Root status: {status}. "
        f"Do not treat ORA codes alone as root cause when OS/ASM/storage context exists."
    )

    if root_layer_eff == "OS" and (root_label in _OS_PATH_PATTERN_IDS or root_label == "OS_STORAGE_PATH_FAILURE"):
        why_deepest = (
            f"Deepest confirmed layer is OS (host multipath/HBA/disk path). "
            f"Matched patterns: {', '.join(direct) or 'none'}. "
            "ORA-27072 is a downstream database I/O symptom when OS path failure is established, not the root label."
        )
        what_change = (
            "Add storage/cell or SAN-side logs for the same incident window if a deeper backend fault is suspected; "
            "stabilize OS multipath and path state before redo/ASM recovery actions."
        )
    elif root_layer_eff == "STORAGE":
        why_deepest = (
            f"Deepest layer with storage-class evidence: {root_layer_eff}. "
            f"Patterns in evidence: {', '.join(direct) or 'none'}."
        )
        what_change = (
            "Add cell/SAN logs, multipath -ll output, ASM alert, or trace bundle tied to the same AU/device/redo member."
        )
    elif root_label == "DB_REDO_IO_FAILURE_NEEDS_LOWER_LAYER_EVIDENCE":
        why_deepest = (
            "ORA-27072, ORA-00353, and ORA-00312 together describe redo/file I/O distress at the database layer; "
            "ORA-00312 is a member locator, not a physical root. No OS, ASM, or storage-class evidence is in this bundle."
        )
        what_change = (
            "Collect host syslog/dmesg, multipath output, ASM alert, and cell/SAN logs for the same incident window "
            "before assigning a confirmed lower-layer root."
        )
    elif root_label == "DB_OBJECT_LOCATOR_ONLY_NEEDS_CONTEXT":
        why_deepest = (
            "Only locator-class ORA evidence is present (for example ORA-00312 naming an online log member). "
            "Locators are not promoted to root cause without primary fault ORAs or lower-layer signals."
        )
        what_change = (
            "Provide alert.log and trace snippets that include the first fatal ORA, plus OS or storage logs for the same time."
        )
    elif root_layer_eff == "NETWORK":
        why_deepest = (
            f"Network-layer signal selected as root context: {root_label}. "
            f"Patterns in evidence: {', '.join(direct) or 'none'}."
        )
        what_change = (
            "Correlate with listener.log, sqlnet traces, firewall or security group changes, and client-to-DB path checks."
        )
    elif root_layer_eff == "ASM" and root_label not in (
        "OS_STORAGE_PATH_FAILURE",
        "STORAGE_FLASH_IO_OR_MEDIA_FAILURE",
    ):
        why_deepest = (
            f"ASM-layer pattern or symptom in evidence: {root_label}. "
            f"Patterns in evidence: {', '.join(direct) or 'none'}."
        )
        what_change = (
            "Validate diskgroup health, asm alert, asmcmd offline disks, and underlying OS/storage paths for the same AU/device."
        )
    else:
        why_deepest = (
            f"Deepest layer with matching evidence: {root_layer_eff}. "
            f"Patterns in evidence: {', '.join(direct) or 'none'}."
        )
        what_change = (
            "Add cell/SAN logs, multipath -ll output, ASM alert, or trace bundle tied to the same AU/device/redo member."
        )

    root_block = {
        "root_cause": root_label,
        "layer": root_layer_eff,
        "status": status,
        "correlation_score": round(corr_score, 1),
        "why_deepest_supported": why_deepest,
        "what_would_change_conclusion": what_change,
    }

    remediation_direction = {
        "INFRA_STORAGE": "Validate cell/flash/grid disk health and backend read paths before host-only fixes.",
        "OS_MULTIPATH_HBA": "Confirm path state, HBA resets, and multipath maps only after storage health is understood.",
        "ASM": "Check diskgroup redundancy and disk offline events after path stability.",
        "DATABASE_RECOVERY": "Redo/archive/backup posture must be known before any destructive recovery command.",
    }

    extra_evidence = []
    if not has_storage_ev and any(o.startswith("ORA-150") for o in observed_oras):
        extra_evidence.append("Cell or storage array logs for the same time window as ASM ORA-150xx")
    if "OS" not in ol and observed_oras:
        extra_evidence.append("Host syslog/dmesg or OSWatcher for the same host and incident window")
    if not keys["trace_files"] and any(o in {"ORA-00353", "ORA-00312", "ORA-27072"} for o in observed_oras):
        extra_evidence.append("LGWR / DBWR trace referenced in alert for the same ORA timestamps")

    return {
        "executive_summary": exec_summary,
        "root_cause_candidate": root_block,
        "cascade_chain_marked": cascade_marked,
        "observed_ora_correlation_table": ora_table,
        "non_ora_correlated_events": non_ora_table,
        # Backward compat: ORA-only rows (no LGWR / pattern rows mislabeled as ORAs).
        "correlated_error_table": ora_table,
        "affected_objects": affected,
        "evidence_timeline": timeline[:40],
        "confidence_explanation": conf_expl,
        "remediation_direction": remediation_direction,
        "additional_evidence_needed": extra_evidence
        or ["None beyond standard corroboration if layers already align."],
        "correlation_model_score": round(corr_score, 1),
        "root_cause_evidence_status": status,
        "events_extracted_count": len(events),
        "anti_hallucination_notes": [
            "Only ORA codes appearing in uploaded text are classified in the ORA table.",
            "LGWR termination and OS/infra patterns appear only under non-ORA correlated events.",
            "Exadata-specific claims require cell/celldisk/griddisk/cellcli-class evidence.",
        ],
    }


_CMD_ORDER = [
    "DESTRUCTIVE_DBA_APPROVAL_REQUIRED",
    "HIGH_RISK_REMEDIATION",
    "REMEDIATION",
    "LOW_RISK_REMEDIATION",
    "DIAGNOSTIC",
]
_CMD_RANK = {name: i for i, name in enumerate(_CMD_ORDER)}


def _classify_one_command(cmd: str) -> str:
    """Classify a single command line for bundle-level safety tagging."""
    c = (cmd or "").strip()
    if not c:
        return "DIAGNOSTIC"
    low = c.lower()
    if re.search(
        r"clear\s+unarchived|resetlogs|until\s+cancel|drop\s+logfile|drop\s+disk|"
        r"offline.*disk|force\s+dismount|alter\s+database\s+recover",
        low,
    ):
        return "DESTRUCTIVE_DBA_APPROVAL_REQUIRED"
    if re.search(
        r"\b(shutdown\s+(immediate|abort|transactional)|startup\s+force|"
        r"alter\s+database\s+(open|recover|mount)|alter\s+diskgroup\s+[^;]*drop)",
        low,
    ):
        return "HIGH_RISK_REMEDIATION"
    if re.search(r"\balter\s+(database|system)\b", low) and "check datafiles" not in low:
        return "HIGH_RISK_REMEDIATION"
    if re.match(
        r"^\s*(select\b|grep\b|dmesg\b|multipath\b|cat\b|tail\b|head\b|ipcs\b|sysctl\b|"
        r"df\b|free\b|chronyc\b|asmcmd\s+ls|cellcli\s+-e\s+list|adrci\b|systool\b|"
        r"iscsiadm\b|kfod\b|lsblk\b|lsscsi\b|systemctl\s+status\b)",
        low,
    ):
        return "DIAGNOSTIC"
    if "show incident" in low or "lsdg" in low or re.match(r"^\s*select\s", low):
        return "DIAGNOSTIC"
    if "alter system check datafiles" in low:
        return "LOW_RISK_REMEDIATION"
    return "REMEDIATION"


def _bundle_command_category(cmds: list[str]) -> str:
    """Worst (most dangerous) command in the bundle wins; all-diagnostic → DIAGNOSTIC."""
    if not cmds:
        return "DIAGNOSTIC"
    worst_rank = _CMD_RANK["DIAGNOSTIC"]
    for cmd in cmds:
        cat = _classify_one_command(cmd)
        worst_rank = min(worst_rank, _CMD_RANK[cat])
    return _CMD_ORDER[worst_rank]


def annotate_fix_command_categories(fixes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tag each fix bundle with command_category (DIAGNOSTIC … DESTRUCTIVE…)."""
    out = []
    for f in fixes:
        nf = dict(f)
        cmds = nf.get("commands") or []
        nf["command_category"] = _bundle_command_category(cmds)
        nf["command_categories_detail"] = [_classify_one_command(x) for x in cmds]
        out.append(nf)
    return out


def downgrade_rca_for_no_match(rca: dict[str, Any], no_match_reason: str) -> dict[str, Any]:
    """
    When the report is NO_MATCH, avoid implying a confirmed RCA from partial correlation.
    """
    out = {**rca}
    out["executive_summary"] = (
        "No finalized incident diagnosis from current evidence. "
        f"{no_match_reason} "
        "Extracted signals are shown for triage only — root cause remains UNKNOWN until gates pass."
    )
    rc = dict(out.get("root_cause_candidate") or {})
    rc["root_cause"] = "UNKNOWN"
    rc["layer"] = "UNKNOWN"
    rc["status"] = "NEEDS_MORE_INFO"
    prev = float(rc.get("correlation_score") or 0.0)
    rc["correlation_score"] = round(min(prev, 40.0), 1)
    rc["why_deepest_supported"] = (
        "Policy or evidence gate blocked finalization — do not treat correlation hints as confirmed root."
    )
    out["root_cause_candidate"] = rc
    prev_cascade = list(out.get("cascade_chain_marked") or [])
    out["cascade_chain_marked"] = [
        "[NEEDS_EVIDENCE] Provide logs from the missing_evidence checklist",
    ] + prev_cascade[:12]
    out["confidence_explanation"] = (
        (out.get("confidence_explanation") or "").strip()
        + " NO_MATCH: correlation model score is capped for display; do not promote to CONFIRMED."
    )
    out["root_cause_evidence_status"] = "NEEDS_MORE_INFO"
    out["anti_hallucination_notes"] = list(out.get("anti_hallucination_notes") or []) + [
        "NO_MATCH: do not invent a root cause from weak similarity or retrieval alone.",
    ]
    return out
