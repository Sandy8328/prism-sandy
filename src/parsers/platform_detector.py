"""
platform_detector.py — Detects the OS platform from log content or AHF metadata.

Supported platforms:
  LINUX     - Oracle Linux, RHEL, CentOS
  AIX       - IBM AIX (errpt format)
  SOLARIS   - Oracle Solaris (fmadm/var/adm/messages)
  HPUX      - HP-UX (/var/adm/syslog)
  WINDOWS   - Windows Event Log (Event ID format)
  EXADATA   - Exadata (cellcli alerthistory)
  OCI       - OCI Cloud Linux (cloud-agent present)
  UNKNOWN   - Cannot determine

Detection priority:
  1. uname.txt from AHF ZIP
  2. ORA error line in alert.log  (e.g. "Linux-x86_64 Error: 5")
  3. Log format fingerprint        (errpt header = AIX, fmadm = Solaris)
  4. Filename patterns             (errpt.txt, fmdump.txt, eventvwr.txt)
"""

import re
from typing import Optional


# ── Platform signatures ─────────────────────────────────────────

# Matched against uname.txt content or first line of any log
UNAME_SIGNATURES = [
    (re.compile(r"Linux.*x86_64|Oracle Linux|Red Hat|CentOS", re.I), "LINUX"),
    (re.compile(r"AIX|IBM AIX", re.I), "AIX"),
    (re.compile(r"SunOS|Solaris", re.I), "SOLARIS"),
    (re.compile(r"HP-UX", re.I), "HPUX"),
    (re.compile(r"CYGWIN|Windows", re.I), "WINDOWS"),
]

# ORA error lines — "Linux-x86_64 Error: 5: Input/output error"
ORA_ERRNO_PLATFORM = [
    (re.compile(r"Linux-x86_64 Error:"), "LINUX"),
    (re.compile(r"IBM AIX RISC System"), "AIX"),
    (re.compile(r"SunOS-\d+\.\d+ Error:|Solaris"), "SOLARIS"),
    (re.compile(r"HP-UX Error:"), "HPUX"),
    (re.compile(r"O/S-Error: \(OS \d+\)"), "WINDOWS"),
]

# Log content fingerprints — unique markers per platform
CONTENT_FINGERPRINTS = [
    (re.compile(r"^LABEL:\s+\w+\s*\nIDENTIFIER:", re.M), "AIX"),           # errpt -a output
    (re.compile(r"fmadm.*faultid|fmadm.*repaired", re.I), "SOLARIS"),      # fmadm output
    (re.compile(r"fmdump.*UUID:|fault\.io\.scsi", re.I), "SOLARIS"),       # fmdump output
    (re.compile(r"/var/adm/syslog|HP-UX B\.\d+\.\d+", re.I), "HPUX"),    # HP-UX syslog
    (re.compile(r"Event ID:\s+\d+|Level:\s+Error\s*\nDate:", re.I), "WINDOWS"),  # Event Viewer
    (re.compile(r"cellcli.*alerthistory|alertType:.*Stateful|cellDiskType:|Read Failed. group:\d+", re.I), "EXADATA"),
    (re.compile(r"cloud-agent|oracle-cloud-agent|oci-metadata", re.I), "OCI"),
]

# File name fingerprints
FILENAME_FINGERPRINTS = [
    (re.compile(r"errpt", re.I), "AIX"),
    (re.compile(r"lspath|lparstat|fcstat", re.I), "AIX"),
    (re.compile(r"fmdump|fmadm|var_adm_messages", re.I), "SOLARIS"),
    (re.compile(r"eventvwr|event_viewer|evtx", re.I), "WINDOWS"),
    (re.compile(r"cellcli|exadata", re.I), "EXADATA"),
    (re.compile(r"var_log_messages|messages$|dmesg|syslog", re.I), "LINUX"),
    (re.compile(r"alert.*oci|oci.*alert|cloud.agent", re.I), "OCI"),
]


def detect_from_uname(uname_content: str) -> Optional[str]:
    """Detect platform from uname.txt content."""
    for pattern, platform in UNAME_SIGNATURES:
        if pattern.search(uname_content):
            return platform
    return None


def detect_from_ora_errno_line(text: str) -> Optional[str]:
    """Detect platform from ORA error errno line in alert.log."""
    for pattern, platform in ORA_ERRNO_PLATFORM:
        if pattern.search(text):
            return platform
    return None


def detect_from_content(text: str) -> Optional[str]:
    """Detect platform from log content fingerprints."""
    for pattern, platform in CONTENT_FINGERPRINTS:
        if pattern.search(text):
            return platform
    return None


def detect_from_filename(filename: str) -> Optional[str]:
    """Detect platform from log filename."""
    for pattern, platform in FILENAME_FINGERPRINTS:
        if pattern.search(filename):
            return platform
    return None


def detect_platform(
    text: str = "",
    filename: str = "",
    uname_content: str = "",
    default: str = "UNKNOWN",
) -> str:
    """
    Main entry point. Returns platform string.

    Priority:
      1. uname.txt  (most authoritative)
      2. ORA errno line in text
      3. Content fingerprints
      4. Filename
      5. default (UNKNOWN)
    """
    if uname_content:
        result = detect_from_uname(uname_content)
        if result:
            return result

    if text:
        result = detect_from_ora_errno_line(text)
        if result:
            return result

        result = detect_from_content(text)
        if result:
            return result

    if filename:
        result = detect_from_filename(filename)
        if result:
            return result

    return default


# ── Platform-specific log source names ─────────────────────────

LOG_SOURCES_BY_PLATFORM = {
    "LINUX":   ["VAR_LOG_MESSAGES", "DMESG", "ALERT_LOG", "CRS_LOG", "AUDIT_LOG",
                 "DF_OUTPUT", "IOSTAT_OUTPUT", "VMSTAT_OUTPUT", "SAR_CPU_OUTPUT",
                 "SAR_Q_OUTPUT", "PROC_MEMINFO", "SMARTCTL_OUTPUT"],
    "AIX":     ["AIX_ERRPT", "AIX_LPARSTAT", "AIX_LSPATH", "AIX_FCSTAT",
                 "ALERT_LOG", "CRS_LOG", "AIX_VMSTAT", "AIX_SVMON"],
    "SOLARIS": ["SOLARIS_VAR_ADM", "SOLARIS_FMA", "SOLARIS_FMDUMP",
                 "ALERT_LOG", "CRS_LOG", "SOLARIS_PRSTAT"],
    "HPUX":    ["HPUX_SYSLOG", "ALERT_LOG"],
    "WINDOWS": ["WINDOWS_EVENT_LOG", "WINDOWS_PERFMON", "ALERT_LOG"],
    "EXADATA": ["EXADATA_CELLCLI", "VAR_LOG_MESSAGES", "ALERT_LOG", "CRS_LOG"],
    "OCI":     ["VAR_LOG_MESSAGES", "DMESG", "ALERT_LOG", "OCI_CLOUD_AGENT"],
    "UNKNOWN": [],
}


def get_log_sources(platform: str) -> list:
    """Return expected log source IDs for a given platform."""
    return LOG_SOURCES_BY_PLATFORM.get(platform, [])


# ── ORA errno translation per platform ─────────────────────────

ERRNO_LINE_PATTERNS = {
    "LINUX":   re.compile(r"Linux-x86_64 Error: (\d+): (.+)"),
    "AIX":     re.compile(r"IBM AIX RISC System/6000 Error: (\d+): (.+)"),
    "SOLARIS": re.compile(r"Solaris-\w+ Error: (\d+): (.+)"),
    "HPUX":    re.compile(r"HP-UX Error: (\d+): (.+)"),
    "WINDOWS": re.compile(r"O/S-Error: \(OS (\d+)\) (.+)"),
}


def extract_errno(text: str, platform: str) -> Optional[tuple]:
    """
    Extract (errno_number, errno_message) from an ORA errno line.
    Returns None if not found.
    """
    pattern = ERRNO_LINE_PATTERNS.get(platform)
    if not pattern:
        # Try all patterns
        for p in ERRNO_LINE_PATTERNS.values():
            m = p.search(text)
            if m:
                return (m.group(1), m.group(2))
        return None
    m = pattern.search(text)
    if m:
        return (m.group(1), m.group(2))
    return None
