"""
syslog_translator.py — Converts raw syslog/dmesg/alert.log text into
                        internal OS_ERROR_PATTERN codes used by the graph.

PURPOSE
-------
The knowledge graph stores patterns like OS_OOM_KILLER, OS_SCSI_TIMEOUT,
NTP_TIME_JUMP etc. But a DBA pastes raw messages like:
  "kernel: Out of memory: Kill process 14823 (ora_dbw0_PROD) score 962"
This translator bridges that gap BEFORE the orchestrator runs.

Without it:
  raw text → graph lookup → NOT FOUND → Tier 3 NEEDS_MORE_INFO (false escalation)

With it:
  raw text → translate() → ["OS_OOM_KILLER"] → Tier 1 hit → precise diagnosis

INTEGRATION
-----------
Called in orchestrator.handle_enriched_query() BEFORE evidence aggregation.
The returned code list is injected into the active session as OS signals.

DESIGN RULES
------------
1. Patterns are ordered priority-first (most specific → most general)
2. All matches are case-insensitive
3. Multiple codes can match one message (e.g. disk I/O + multipath)
4. No false positives: patterns are anchored to known Oracle-impacting keywords
5. Pure stdlib — no external dependencies
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Pattern definition ─────────────────────────────────────────────────────────

@dataclass
class SyslogPattern:
    """Maps one regex pattern to one internal OS_ERROR_PATTERN code."""
    code:        str           # Internal graph node id, e.g. "OS_OOM_KILLER"
    regex:       re.Pattern    # Compiled pattern (case-insensitive)
    layer:       str           # Diagnostic layer this code belongs to
    severity:    str           # CRITICAL / ERROR / WARNING
    description: str           # Human-readable label for logging


# ── Master pattern registry ────────────────────────────────────────────────────
# ORDER MATTERS: More specific patterns must come before general ones.
# Each pattern is compiled once at module load.

_RAW_PATTERNS: list[tuple[str, str, str, str, str]] = [
    # (code, regex_str, layer, severity, description)

    # ── Memory / OOM ──────────────────────────────────────────────────────────
    (
        "OS_OOM_KILLER",
        r"(invoked oom.killer|kill process \d+ .ora_|oom.kill.process|"
        r"out of memory.+kill process|memory cgroup out of memory)",
        "OS_TRIGGERED", "CRITICAL",
        "Linux OOM Killer terminated Oracle process"
    ),
    (
        "CGROUP_OOM_KILL",
        r"memory cgroup out of memory|cgroup.*oom",
        "OS_TRIGGERED", "CRITICAL",
        "cgroup OOM kill — container/cgroup memory limit hit"
    ),
    (
        "OS_HUGEPAGE_FAIL",
        r"(hugepages.*(failed|exhausted|insufficient|could not|unable)|"
        r"nr_hugepages.*0|hugetlb.*failed)",
        "OS_TRIGGERED", "CRITICAL",
        "HugePages allocation failure for Oracle SGA"
    ),
    (
        "HUGEPAGES_FREE_ZERO",
        r"hugepages_free:\s*0",
        "OS_TRIGGERED", "ERROR",
        "HugePages_Free is zero — SGA cannot allocate huge pages"
    ),
    (
        "SHMGET_EINVAL",
        r"shmget.*einval|shmget.*failed|cannot attach to shared memory",
        "OS_TRIGGERED", "CRITICAL",
        "shmget() EINVAL — SGA shared memory segment error"
    ),
    (
        "OS_SWAP_STORM",
        r"(swap.*full|swap usage.*[89]\d%|oracle.*paged out|"
        r"si:\s*[1-9]\d{3}|so:\s*[1-9]\d{3})",
        "OS_TRIGGERED", "CRITICAL",
        "Swap storm — Oracle SGA being paged to disk"
    ),
    (
        "MEMORY_SWAP_STORM",
        r"(high swap activity|swap space.*critically|vmstat.*swap.*[89]\d)",
        "OS_TRIGGERED", "CRITICAL",
        "High swap activity detected"
    ),
    (
        "MEMLOCK_ULIMIT_TOO_LOW",
        r"(memlock.*unlimited|ulimit.*memlock|unable to lock pages)",
        "OS_TRIGGERED", "ERROR",
        "memlock ulimit too low for Oracle to lock SGA"
    ),
    (
        "SEMAPHORE_LIMIT_EXHAUSTED",
        r"(semaphore.*exhausted|semmni|semmsl|ipcs.*limit|"
        r"no space left.*semaphore|semop.*failed)",
        "OS_TRIGGERED", "CRITICAL",
        "Semaphore limit exhausted — Oracle cannot create IPC semaphores"
    ),
    (
        "FD_LIMIT_EXHAUSTED",
        r"(too many open files|file descriptor.*limit|"
        r"ulimit.*nofile|open files.*max)",
        "OS_TRIGGERED", "CRITICAL",
        "File descriptor limit exhausted"
    ),

    # ── Disk / Storage / I/O ──────────────────────────────────────────────────
    (
        "FC_HBA_ABORT",
        r"(qla2xxx.*Abort command issued|Abort command issued.*qla2xxx)",
        "OS_TRIGGERED", "WARNING",
        "Fibre Channel HBA abort command issued"
    ),
    (
        "OS_SCSI_TIMEOUT",
        r"(scsi error|scsi.*(timeout|failed|reset|abort)|"
        r"end_request.*i/o error.*dev sd|"
        r"blk_update_request.*i/o error|"
        r"hostbyte=DID_TIME_OUT|driverbyte=DRIVER_TIMEOUT)",
        "OS_TRIGGERED", "CRITICAL",
        "SCSI disk timeout or I/O error"
    ),
    (
        "OS_MULTIPATH_DOWN",
        r"(all paths.*down|multipath.*failed|dm-[0-9]+.*failed|"
        r"multipathd.*checker failed|path.*failover.*failed)",
        "OS_TRIGGERED", "CRITICAL",
        "All multipath paths down — storage connectivity lost"
    ),
    (
        "MULTIPATH_ALL_PATHS_DOWN",
        r"(no paths.*available|multipath.*no working paths|"
        r"sd[a-z]+.*removed|lun.*offline|"
        r"multipathd:\s*\S+:\s*remaining active paths:\s*0|"
        r"multipathd:.*\bno active paths\b)",
        "OS_TRIGGERED", "CRITICAL",
        "All multipath paths to LUN offline"
    ),
    (
        "FC_HBA_RESET",
        r"(qla2xxx.*reset|lpfc.*link down|fc.*link.*fail|"
        r"hba.*reset|fibre channel.*error|fcp.*i/o error)",
        "OS_TRIGGERED", "CRITICAL",
        "Fibre Channel HBA reset or link failure"
    ),
    (
        "OS_ISCSI_FAIL",
        r"(iscsi.*session.*failed|iscsid.*connection.*timeout|"
        r"iscsi.*io error|iscsi.*login.*failed)",
        "OS_TRIGGERED", "CRITICAL",
        "iSCSI session failure"
    ),
    (
        "IO_QUEUE_TIMEOUT",
        r"(i/o timeout.*deadline|io timeout|device.*timed out|"
        r"hung_task_timeout|task.*blocked.*more than \d+ seconds)",
        "OS_TRIGGERED", "CRITICAL",
        "I/O queue timeout — device not responding"
    ),
    (
        "EXT4_JOURNAL_ABORT",
        r"(ext4.*journal.*abort|ext4.fs error.*journal|"
        r"jbd2.*aborted|ext4.*remounted.*read.only)",
        "OS_TRIGGERED", "CRITICAL",
        "EXT4 journal aborted — filesystem remounted read-only"
    ),
    (
        "XFS_FILESYSTEM_SHUTDOWN",
        r"(xfs.*filesystem shutdown|xfs.*ioerror|xfs.*corruption|"
        r"xfs.*forced shutdown)",
        "OS_TRIGGERED", "CRITICAL",
        "XFS filesystem shutdown due to I/O error"
    ),
    (
        "OS_DISK_FULL",
        r"(no space left on device|disk.*100%|filesystem.*full|"
        r"enospc|wrote 0 of \d+ bytes)",
        "OS_TRIGGERED", "CRITICAL",
        "Filesystem 100% full"
    ),
    (
        "FILESYSTEM_ARCH_FULL",
        r"(arch.*100%|archivelog.*destination.*full|"
        r"/arch.*no space|fra.*full|db_recovery_file_dest.*full)",
        "OS_TRIGGERED", "CRITICAL",
        "Archivelog destination or FRA filesystem full"
    ),

    # ── Kernel / Stability ────────────────────────────────────────────────────
    (
        "OS_KERNEL_PANIC",
        r"(kernel panic|kernel.*not syncing|oops.*general protection|"
        r"bug.*kernel null pointer|rip.*kernel)",
        "OS_TRIGGERED", "CRITICAL",
        "Linux kernel panic"
    ),
    (
        "KERNEL_PANIC",
        r"(kernel panic - not syncing|panic occurred)",
        "OS_TRIGGERED", "CRITICAL",
        "Kernel panic — system crash"
    ),
    (
        "SOFT_LOCKUP",
        r"soft lockup.*cpu.*stuck|watchdog.*soft lockup",
        "OS_TRIGGERED", "CRITICAL",
        "CPU soft lockup detected"
    ),
    (
        "HARD_LOCKUP",
        r"hard lockup.*cpu|watchdog.*hard lockup|nmi.*watchdog",
        "OS_TRIGGERED", "CRITICAL",
        "CPU hard lockup detected"
    ),
    (
        "OS_MCE_UNCORRECTED",
        r"(machine check.*uncorrected|mce.*fatal|hardware error.*uncorrectable|"
        r"edac.*ue.*error)",
        "OS_TRIGGERED", "CRITICAL",
        "Uncorrected Machine Check Exception — hardware memory error"
    ),
    (
        "MCE_CORRECTED_MEMORY",
        r"(mce.*corrected|edac.*ce.*error|corrected memory error)",
        "OS_TRIGGERED", "WARNING",
        "Corrected Machine Check Exception — hardware memory warning"
    ),
    (
        "OS_SELINUX_BLOCK",
        r"(selinux.*denied|avc.*denied|type=avc.*oracle|"
        r"selinux.*prevented.*oracle)",
        "OS_TRIGGERED", "ERROR",
        "SELinux blocking Oracle file or network access"
    ),
    (
        "AUDITD_KILL_9",
        r"(type=obj_pid.*op=kill.*sig=9|audit.*kill -9.*oracle)",
        "OS_TRIGGERED", "CRITICAL",
        "auditd detected kill -9 signal sent to Oracle process"
    ),

    # ── ASM / Storage ─────────────────────────────────────────────────────────
    (
        "ASM_HIGH_POWER_REBALANCE",
        r"(rebal.*power.*([5-9]|[1-9]\d+)|power=\s*([5-9]|[1-9]\d+).*rebal|rebal\s+run\s+([5-9]|[1-9]\d+))",
        "LAYER_ASM", "WARNING",
        "ASM High Power Rebalance detected — may cause storage DoS"
    ),

    # ── CPU ───────────────────────────────────────────────────────────────────
    (
        "OS_CPU_SATURATION",
        r"(cpu.*runqueue.*\b[1-9]\d\b|load average.*\b[1-9]\d\b|"
        r"cpu steal.*[3-9]\d%|%steal.*[3-9]\d|"
        r"scheduler.*overload|run queue.*saturation)",
        "OS_TRIGGERED", "ERROR",
        "CPU runqueue saturation"
    ),
    (
        "CPU_STEAL_TIME",
        r"(steal time.*[3-9]\d|%st\s+[3-9]\d|cpu steal.*high|"
        r"hypervisor.*stealing)",
        "OS_TRIGGERED", "ERROR",
        "High CPU steal time — hypervisor resource contention"
    ),

    # ── Network ───────────────────────────────────────────────────────────────
    (
        "OS_NET_DROP",
        r"(link.*down|nic.*down|eth[0-9]+.*no carrier|"
        r"bond[0-9]+.*link failure|interface.*down)",
        "NETWORK", "CRITICAL",
        "Network link or NIC down"
    ),
    (
        "BONDING_FAILOVER_EVENT",
        r"(bonding.*active.*slave changed|bond.*failover|"
        r"backup.*slave.*active|bonding.*link.*failure)",
        "NETWORK", "ERROR",
        "Network bonding failover event"
    ),
    (
        "BOTH_NICS_DOWN",
        r"(both.*slaves.*down|no active.*bond|bonding.*no backup)",
        "NETWORK", "CRITICAL",
        "Both bonding NICs down — no active network path"
    ),
    (
        "OS_CONNTRACK_FULL",
        r"(nf_conntrack.*table full|conntrack.*full|"
        r"nf_conntrack.*dropping|ip_conntrack.*full)",
        "NETWORK", "CRITICAL",
        "nf_conntrack table full — packets being dropped"
    ),
    (
        "NF_CONNTRACK_FULL",
        r"nf_conntrack: table full, dropping packet",
        "NETWORK", "CRITICAL",
        "nf_conntrack table full (exact kernel message)"
    ),
    (
        "IPTABLES_BLOCKING_1521",
        r"(iptables.*drop.*1521|firewall.*reject.*1521|"
        r"1521.*connection refused|1521.*blocked)",
        "NETWORK", "ERROR",
        "iptables blocking Oracle listener port 1521"
    ),
    (
        "OS_NFS_STALE",
        r"(stale nfs file handle|nfs.*stale|stale file handle.*nfs|"
        r"nfs.*server.*not responding)",
        "OS_TRIGGERED", "CRITICAL",
        "Stale NFS file handle — NFS mount unavailable"
    ),
    (
        "NFS_MOUNT_TIMEOUT",
        r"(nfs.*timed out|nfs.*mount.*failed|nfs.*connection timed out|"
        r"nfs.*server.*not responding.*timed out)",
        "OS_TRIGGERED", "CRITICAL",
        "NFS mount timeout"
    ),

    # ── Cluster / NTP ─────────────────────────────────────────────────────────
    (
        "OS_NTP_JUMP",
        r"(time.*jump|ntpd.*offset.*[5-9]\d{2,}|"
        r"clock.*drift|time.*adjusted.*[5-9]\d{2,}ms|"
        r"chronyd.*large.*offset|adjtime.*large)",
        "CLUSTER", "CRITICAL",
        "NTP time jump — may cause RAC CSS eviction"
    ),
    (
        "NTP_TIME_JUMP",
        r"(ntp.*step|stepped.*clock|time.*stepped.*offset|"
        r"chronyd.*stepped|offset.*too large)",
        "CLUSTER", "CRITICAL",
        "NTP clock step (large time correction)"
    ),

    # ── Platform-specific ─────────────────────────────────────────────────────
    (
        "OS_LPAR_CPU_CAP",
        r"(lpar.*cpu.*cap|processor.*entitlement|"
        r"cpu.*pool.*exhausted|entitled capacity)",
        "OS_TRIGGERED", "ERROR",
        "AIX LPAR CPU cap hit — Oracle CPU throttled"
    ),
    (
        "OS_VMWARE_SNAPSHOT",
        r"(vmware.*snapshot|vsphere.*quiesce|"
        r"vmtools.*freeze|guestfs.*quiesce)",
        "OS_TRIGGERED", "ERROR",
        "VMware snapshot causing I/O freeze"
    ),
]


# ── Compile all patterns once at module load ───────────────────────────────────
_COMPILED_PATTERNS: list[SyslogPattern] = [
    SyslogPattern(
        code=code,
        regex=re.compile(regex_str, re.IGNORECASE),
        layer=layer,
        severity=severity,
        description=desc,
    )
    for code, regex_str, layer, severity, desc in _RAW_PATTERNS
]


# ── Public API ─────────────────────────────────────────────────────────────────

@dataclass
class TranslationMatch:
    """Single match result from translate()."""
    code:        str
    layer:       str
    severity:    str
    description: str
    matched_text: str   # The specific substring that triggered the match


def translate(raw_text: str) -> list[TranslationMatch]:
    """
    Scan raw_text (syslog line, dmesg block, or alert.log excerpt) for
    known OS error patterns and return all matches.

    Args:
        raw_text: One or more lines of raw log text (any format).

    Returns:
        List of TranslationMatch in detection order.
        Empty list if no known pattern matched.

    Example:
        >>> results = translate(
        ...     "kernel: Out of memory: Kill process 14823 (ora_dbw0_PROD) score 962"
        ... )
        >>> results[0].code
        'OS_OOM_KILLER'
    """
    matches: list[TranslationMatch] = []
    seen_codes: set[str] = set()   # deduplicate — same code from multiple lines

    for pat in _COMPILED_PATTERNS:
        m = pat.regex.search(raw_text)
        if m and pat.code not in seen_codes:
            seen_codes.add(pat.code)
            matches.append(TranslationMatch(
                code=pat.code,
                layer=pat.layer,
                severity=pat.severity,
                description=pat.description,
                matched_text=m.group(0)[:120],   # cap for display
            ))

    return matches


def translate_entries(entries: list[dict]) -> list[TranslationMatch]:
    """
    Run pattern matching per syslog/alert entry so timestamps and source lines
    are not collapsed into one blob.
    """
    matches: list[TranslationMatch] = []
    seen_codes: set[str] = set()
    for entry in entries or []:
        blob = (entry.get("message") or "") + "\n" + (entry.get("raw") or "")
        if not blob.strip():
            continue
        for pat in _COMPILED_PATTERNS:
            m = pat.regex.search(blob)
            if m and pat.code not in seen_codes:
                seen_codes.add(pat.code)
                matches.append(
                    TranslationMatch(
                        code=pat.code,
                        layer=pat.layer,
                        severity=pat.severity,
                        description=pat.description,
                        matched_text=m.group(0)[:200],
                    )
                )
    return matches


def extract_codes(raw_text: str) -> list[str]:
    """
    Convenience function — returns just the code strings.

    Example:
        >>> extract_codes("nf_conntrack: table full, dropping packet")
        ['OS_CONNTRACK_FULL', 'NF_CONNTRACK_FULL']
    """
    return [m.code for m in translate(raw_text)]


def highest_severity(matches: list[TranslationMatch]) -> Optional[str]:
    """Return the highest severity across all matches (CRITICAL > ERROR > WARNING)."""
    order = {"CRITICAL": 3, "ERROR": 2, "WARNING": 1}
    if not matches:
        return None
    return max(matches, key=lambda m: order.get(m.severity, 0)).severity


def summarise(matches: list[TranslationMatch]) -> str:
    """
    Return a short human-readable summary of all matched patterns.
    Used in chatbot response generation.
    """
    if not matches:
        return "No known OS error patterns detected in the provided log text."
    lines = [f"Detected {len(matches)} OS-layer signal(s):"]
    for m in matches:
        lines.append(f"  [{m.severity}] {m.code} — {m.description}")
        lines.append(f"           matched: \"{m.matched_text}\"")
    return "\n".join(lines)
