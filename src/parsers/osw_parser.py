"""
osw_parser.py
=============
Parses Oracle OSWatcher (oswbb) output files.

Supported formats:
  - oswvmstat.dat   (vmstat captures — primary target)
  - Plain text summary exports from OSWatcher

OSWatcher vmstat block format (verified Oracle OSWatcher 7.x / 8.x output):

  zzz ***Mon Mar 07 03:14:01 IST 2024
   r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa
   8  2  51200 102400  12800 409600  500 1200  2400  3600 1200 2400 85  8  2  5

Column definitions (from vmstat man page — not invented):
  r   = run queue length (processes waiting for CPU)
  b   = processes in uninterruptible sleep (I/O wait)
  swpd = virtual memory used (KB)
  free = idle memory (KB)
  buff = memory used as buffers (KB)
  cache = memory used as cache (KB)
  si  = memory swapped in from disk per second (KB/s)
  so  = memory swapped out to disk per second (KB/s)
  bi  = blocks received from block device (blocks/s)
  bo  = blocks sent to block device (blocks/s)
  in  = interrupts per second
  cs  = context switches per second
  us  = user CPU time %
  sy  = system CPU time %
  id  = idle CPU time %
  wa  = I/O wait CPU time %
"""

from __future__ import annotations
import os
import re
import yaml
from typing import Optional

# ── Load thresholds from settings.yaml (single source of truth) ───────────────
_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "settings.yaml")
try:
    with open(_SETTINGS_PATH) as _f:
        _cfg = yaml.safe_load(_f)
    _osw = _cfg.get("osw_thresholds", {})
    _RUN_QUEUE_MULTIPLIER   = _osw.get("run_queue_multiplier",   2)
    _SWAP_THRESHOLD_KB_S    = _osw.get("swap_threshold_kb_s",    200)
    _IOWAIT_THRESHOLD_PCT   = _osw.get("iowait_threshold_pct",   20)
    _CPU_USER_THRESHOLD_PCT = _osw.get("cpu_user_threshold_pct", 80)
except Exception:
    _RUN_QUEUE_MULTIPLIER   = 2
    _SWAP_THRESHOLD_KB_S    = 200
    _IOWAIT_THRESHOLD_PCT   = 20
    _CPU_USER_THRESHOLD_PCT = 80

# Run queue > cpu_count × multiplier indicates CPU saturation.
_DEFAULT_CPU_COUNT   = os.cpu_count() or 4
_RUN_QUEUE_THRESHOLD = _DEFAULT_CPU_COUNT * _RUN_QUEUE_MULTIPLIER

# Free memory < 512MB (in KB) indicates low physical memory
_FREE_MEM_THRESHOLD_KB = 524288    # 512 MB in KB


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp pattern for OSWatcher block separator
# Format: zzz ***Mon Mar 07 03:14:01 IST 2024
# ─────────────────────────────────────────────────────────────────────────────
_ZZZ_PATTERN = re.compile(
    r'^zzz\s+\*{3}\s*'
    r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
    r'\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\d{4}',
    re.MULTILINE
)

# vmstat data line: 16 numeric columns (no steal), or 17 with final `st` (steal).
_VMSTAT_LINE = re.compile(
    r'^\s*'
    r'(\d+)\s+'   # r (run queue)
    r'(\d+)\s+'   # b
    r'(\d+)\s+'   # swpd
    r'(\d+)\s+'   # free
    r'(\d+)\s+'   # buff
    r'(\d+)\s+'   # cache
    r'(\d+)\s+'   # si
    r'(\d+)\s+'   # so
    r'(\d+)\s+'   # bi
    r'(\d+)\s+'   # bo
    r'(\d+)\s+'   # in
    r'(\d+)\s+'   # cs
    r'(\d+)\s+'   # us
    r'(\d+)\s+'   # sy
    r'(\d+)\s+'   # id
    r'(\d+)'      # wa
    r'\s*$',
    re.MULTILINE,
)
_VMSTAT_LINE_ST = re.compile(
    r'^\s*'
    r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+'
    r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+'
    r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)'
    r'\s*$',
    re.MULTILINE,
)


def _row_from_vmstat_match(m: re.Match, *, with_st: bool) -> dict:
    base = {
        "r":     int(m.group(1)),
        "b":     int(m.group(2)),
        "swpd":  int(m.group(3)),
        "free":  int(m.group(4)),
        "buff":  int(m.group(5)),
        "cache": int(m.group(6)),
        "si":    int(m.group(7)),
        "so":    int(m.group(8)),
        "bi":    int(m.group(9)),
        "bo":    int(m.group(10)),
        "in_":   int(m.group(11)),
        "cs":    int(m.group(12)),
        "us":    int(m.group(13)),
        "sy":    int(m.group(14)),
        "id":    int(m.group(15)),
        "wa":    int(m.group(16)),
    }
    if with_st:
        base["st"] = int(m.group(17))
    return base


def _parse_vmstat_blocks(text: str) -> list[dict]:
    """
    Extract all vmstat data rows from OSWatcher file.
    Returns list of dicts, one per data line.
    """
    rows: list[dict] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m17 = _VMSTAT_LINE_ST.match(s)
        if m17:
            rows.append(_row_from_vmstat_match(m17, with_st=True))
            continue
        m16 = _VMSTAT_LINE.match(s)
        if m16:
            rows.append(_row_from_vmstat_match(m16, with_st=False))
    return rows


def _compute_peaks(rows: list[dict]) -> dict:
    """Compute peak/min values across all vmstat rows."""
    if not rows:
        return {}

    return {
        "peak_run_queue":    max(r["r"]    for r in rows),
        "peak_blocked":      max(r["b"]    for r in rows),
        "peak_swap_in":      max(r["si"]   for r in rows),
        "peak_swap_out":     max(r["so"]   for r in rows),
        "min_free_mem_kb":   min(r["free"] for r in rows),
        "peak_iowait_pct":   max(r["wa"]   for r in rows),
        "peak_user_cpu_pct": max(r["us"]   for r in rows),
        "peak_swpd_kb":      max(r["swpd"] for r in rows),
        "sample_count":      len(rows),
    }


def _detect_signals(peaks: dict) -> list[str]:
    """
    Apply threshold rules to peak values.
    Returns list of signal strings — based on verified thresholds only.
    """
    signals = []

    if not peaks:
        return signals

    if peaks.get("peak_run_queue", 0) > _RUN_QUEUE_THRESHOLD:
        signals.append("CPU_SATURATION")

    # [Phase 4 - Edge Case 20: Unkillable Zombie]
    # The 'b' column in vmstat represents processes in D state (Uninterruptible sleep).
    # If this is > 0, processes are stuck in kernel space (usually I/O hang) and cannot be kill -9'd.
    if peaks.get("peak_blocked", 0) > 0:
        signals.append("PROCESS_D_STATE_ZOMBIE")

    swap_in  = peaks.get("peak_swap_in", 0)
    swap_out = peaks.get("peak_swap_out", 0)
    if swap_in > _SWAP_THRESHOLD_KB_S or swap_out > _SWAP_THRESHOLD_KB_S:
        signals.append("MEMORY_PRESSURE")

    if peaks.get("min_free_mem_kb", float('inf')) < _FREE_MEM_THRESHOLD_KB:
        signals.append("LOW_PHYSICAL_MEMORY")

    if peaks.get("peak_iowait_pct", 0) > _IOWAIT_THRESHOLD_PCT:
        signals.append("IO_WAIT_HIGH")

    if peaks.get("peak_user_cpu_pct", 0) > _CPU_USER_THRESHOLD_PCT:
        signals.append("CPU_USER_HIGH")

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# Main Parser Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def parse_osw_report(filepath: str) -> dict:
    """
    Parse an OSWatcher vmstat file.

    Args:
        filepath: Path to oswvmstat.dat or plain-text OSW export.

    Returns:
        {
            "source_file":         str,
            "sample_count":        int,
            "peak_run_queue":      int,
            "peak_blocked":        int,
            "peak_swap_in":        int,    # KB/s
            "peak_swap_out":       int,    # KB/s
            "min_free_mem_kb":     int,
            "peak_iowait_pct":     int,
            "peak_user_cpu_pct":   int,
            "peak_swpd_kb":        int,
            "osw_signals":         list[str],
            "parse_error":         str | None,
        }
    """
    result = {
        "source_file":       filepath,
        "sample_count":      0,
        "peak_run_queue":    0,
        "peak_blocked":      0,
        "peak_swap_in":      0,
        "peak_swap_out":     0,
        "min_free_mem_kb":   0,
        "peak_iowait_pct":   0,
        "peak_user_cpu_pct": 0,
        "peak_swpd_kb":      0,
        "osw_signals":       [],
        "parse_error":       None,
    }

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except FileNotFoundError:
        result["parse_error"] = f"File not found: {filepath}"
        return result
    except Exception as e:
        result["parse_error"] = f"Read error: {e}"
        return result

    rows = _parse_vmstat_blocks(text)

    if not rows:
        result["parse_error"] = "No vmstat data rows found in file."
        return result

    peaks = _compute_peaks(rows)
    result.update(peaks)
    result["osw_signals"] = _detect_signals(peaks)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: parse inline OSW text (for unit tests / session upload)
# ─────────────────────────────────────────────────────────────────────────────

def parse_osw_text(text: str) -> dict:
    """
    Parse OSW vmstat content from a string (e.g. from session upload).
    Same output format as parse_osw_report(), without source_file.
    """
    result = {
        "source_file":       "inline",
        "sample_count":      0,
        "peak_run_queue":    0,
        "peak_blocked":      0,
        "peak_swap_in":      0,
        "peak_swap_out":     0,
        "min_free_mem_kb":   0,
        "peak_iowait_pct":   0,
        "peak_user_cpu_pct": 0,
        "peak_swpd_kb":      0,
        "osw_signals":       [],
        "parse_error":       None,
    }

    rows = _parse_vmstat_blocks(text)
    if not rows:
        result["parse_error"] = "No vmstat data found in provided text."
        return result

    peaks = _compute_peaks(rows)
    result.update(peaks)
    result["osw_signals"] = _detect_signals(peaks)
    return result
