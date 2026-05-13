"""
syslog_parser.py — Parses /var/log/messages style syslog files (Linux, Solaris var/adm).

Syslog format:
  Mon DD HH:MM:SS hostname process[pid]: message
  Apr 21 03:14:18 dbhost01 kernel: oracle invoked oom-killer ...

Produces a list of SyslogEntry dicts for the chunker.
"""

import re
from datetime import datetime
from typing import Iterator, Optional
from dateutil import parser as dateutil_parser
import pytz

# ── Syslog line regex ───────────────────────────────────────────
# Matches: "Apr 21 03:14:18 dbhost01 kernel: message"
# Also:    "2024-04-21T03:14:18+05:30 dbhost01 kernel: message" (RFC5424)
_SYSLOG_RFC3164 = re.compile(
    r"^(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<process>[^\[:\s]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.+)$"
)

_SYSLOG_RFC5424 = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*)\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<process>[^\[:\s]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.+)$"
)

_DMESG_LINE = re.compile(
    r"^\[\s*(?P<uptime>[\d.]+)\]\s+(?P<message>.+)$"
)


def _parse_rfc3164_ts(month: str, day: str, time_str: str, year: int | None) -> Optional[datetime]:
    """Parse syslog RFC3164 timestamp; returns None if year is not supplied (no silent current-year)."""
    if year is None:
        return None
    try:
        return datetime.strptime(f"{month} {day} {time_str} {year}", "%b %d %H:%M:%S %Y")
    except ValueError:
        return None


def parse_syslog_line(line: str, default_year: int = None) -> Optional[dict]:
    """
    Parse a single syslog line. Returns dict or None if not a valid syslog line.
    """
    line = line.rstrip("\n")

    # Try RFC3164 (classic syslog)
    m = _SYSLOG_RFC3164.match(line)
    if m:
        ts = _parse_rfc3164_ts(
            m.group("month"), m.group("day"), m.group("time"),
            year=default_year,
        )
        tc = "MEDIUM" if default_year is not None else "LOW"
        return {
            "timestamp": ts,
            "timestamp_str": f"{m.group('month')} {m.group('day')} {m.group('time')}",
            "timestamp_confidence": tc,
            "hostname": m.group("hostname"),
            "process": m.group("process"),
            "pid": m.group("pid"),
            "message": m.group("message"),
            "raw": line,
            "format": "RFC3164",
        }

    # Try RFC5424 (ISO timestamp)
    m = _SYSLOG_RFC5424.match(line)
    if m:
        try:
            ts = dateutil_parser.parse(m.group("timestamp"))
        except Exception:
            ts = None
        return {
            "timestamp": ts,
            "timestamp_str": m.group("timestamp"),
            "timestamp_confidence": "HIGH" if ts else "LOW",
            "hostname": m.group("hostname"),
            "process": m.group("process"),
            "pid": m.group("pid"),
            "message": m.group("message"),
            "raw": line,
            "format": "RFC5424",
        }

    # Try dmesg
    m = _DMESG_LINE.match(line)
    if m:
        return {
            "timestamp": None,
            "timestamp_str": f"[{m.group('uptime')}]",
            "timestamp_confidence": "LOW",
            "hostname": None,
            "process": "kernel",
            "pid": None,
            "message": m.group("message"),
            "raw": line,
            "format": "DMESG",
        }

    return None


def parse_syslog_file(filepath: str, default_year: int | None = None) -> list:
    """
    Parse an entire /var/log/messages or dmesg file.
    Returns list of parsed line dicts (skips unparseable lines but keeps raw text).
    """
    entries = []
    unparsed_buffer = []

    with open(filepath, "r", errors="replace") as f:
        for line in f:
            entry = parse_syslog_line(line, default_year=default_year)
            if entry:
                # Flush any buffered unparsed lines as a continuation of previous entry
                if unparsed_buffer and entries:
                    entries[-1]["raw"] += "\n" + "\n".join(unparsed_buffer)
                    entries[-1]["message"] += " " + " ".join(unparsed_buffer)
                    unparsed_buffer = []
                entries.append(entry)
            else:
                stripped = line.strip()
                if stripped:
                    unparsed_buffer.append(stripped)

    return entries


def parse_syslog_text(text: str, hostname: str = None, default_year: int | None = None) -> list:
    """
    Parse syslog content from a string (for pasted log input).
    Returns list of parsed line dicts.
    When default_year is None, RFC3164 lines keep timestamp=None and timestamp_confidence LOW
    unless you pass an inferred incident year.
    """
    entries = []
    for line in text.splitlines():
        entry = parse_syslog_line(line, default_year=default_year)
        if entry:
            if hostname and not entry["hostname"]:
                entry["hostname"] = hostname
            entries.append(entry)
        elif line.strip() and entries:
            # Continuation line — append to previous entry
            entries[-1]["raw"] += "\n" + line
            entries[-1]["message"] += " " + line.strip()

    return entries


def extract_hostname_from_syslog(entries: list) -> Optional[str]:
    """Best-guess hostname from parsed syslog entries."""
    for e in entries:
        if e.get("hostname"):
            return e["hostname"]
    return None
