"""
iostat_parser.py — Parses iostat, vmstat, sar, and df output.

These are metric files collected by AHF or provided by DBA.
Parser extracts numeric values and compares against thresholds from settings.yaml.
"""

import re
from typing import Optional

_SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3, "UNKNOWN": -1}


def _severity_max(*labels: str) -> str:
    return max(labels, key=lambda x: _SEVERITY_RANK.get(x, 0))


# ── iostat parser ───────────────────────────────────────────────
# iostat -x output:
# Device:  rrqm/s wrqm/s   r/s   w/s  rkB/s  wkB/s  avgrq-sz avgqu-sz  await r_await w_await  svctm  %util
# sdb        0.00   0.10  82.00 120.00 3280.00 4800.00    79.51     1.21  6.00   5.50   6.40   5.80  93.70

_IOSTAT_HEADER = re.compile(
    r"Device[:\s]+rrqm.*avgrq.*await.*%util", re.I
)
_IOSTAT_HEADER_MODERN = re.compile(
    r"Device\s+r/s\s+w/s\s+rkB/s\s+wkB/s.*r_await",
    re.I,
)
_IOSTAT_ROW_MODERN = re.compile(
    r"^(?P<device>\S+)\s+"
    r"(?P<r_s>[\d.]+)\s+(?P<w_s>[\d.]+)\s+"
    r"(?P<rk>[\d.]+)\s+(?P<wk>[\d.]+)\s+"
    r"(?P<rrqm>[\d.]+)\s+(?P<wrqm>[\d.]+)\s+"
    r"(?P<prr>[\d.]+)\s+(?P<pwr>[\d.]+)\s+"
    r"(?P<r_await>[\d.]+)\s+(?P<w_await>[\d.]+)\s+"
    r"(?P<aqu>[\d.]+)\s+(?:[\d.]+\s+)?(?P<util>[\d.]+)\s*$",
)
# e.g. ... aqu-sz rareq-sz wareq-sz svctm %util
_IOSTAT_ROW_MODERN_EXT = re.compile(
    r"^(?P<device>\S+)\s+"
    r"(?P<r_s>[\d.]+)\s+(?P<w_s>[\d.]+)\s+"
    r"(?P<rk>[\d.]+)\s+(?P<wk>[\d.]+)\s+"
    r"(?P<rrqm>[\d.]+)\s+(?P<wrqm>[\d.]+)\s+"
    r"(?P<prr>[\d.]+)\s+(?P<pwr>[\d.]+)\s+"
    r"(?P<r_await>[\d.]+)\s+(?P<w_await>[\d.]+)\s+"
    r"(?P<aqu>[\d.]+)\s+(?:[\d.]+\s+){1,4}(?P<util>[\d.]+)\s*$",
)
_IOSTAT_ROW = re.compile(
    r"^(?P<device>\S+)\s+"
    r"(?P<rrqm>[\d.]+)\s+(?P<wrqm>[\d.]+)\s+"
    r"(?P<r_s>[\d.]+)\s+(?P<w_s>[\d.]+)\s+"
    r"(?P<rkb>[\d.]+)\s+(?P<wkb>[\d.]+)\s+"
    r"(?P<avgrq>[\d.]+)\s+(?P<avgqu>[\d.]+)\s+"
    r"(?P<await>[\d.]+)\s+(?P<r_await>[\d.]+)\s+(?P<w_await>[\d.]+)\s+"
    r"(?P<svctm>[\d.]+)\s+(?P<util>[\d.]+)"
)

# Simple iostat (older format without r_await/w_await)
_IOSTAT_ROW_SIMPLE = re.compile(
    r"^(?P<device>\S+)\s+"
    r"(?P<tps>[\d.]+)\s+"
    r"(?P<read_s>[\d.]+)\s+(?P<write_s>[\d.]+)\s+"
    r"(?P<read_kb>[\d.]+)\s+(?P<write_kb>[\d.]+)"
)


def parse_iostat_text(text: str) -> list:
    """
    Parse iostat -x output (legacy columns with await/svctm, modern r_await/w_await/aqu-sz,
    or simple tps layout). Returns list of device metric dicts.
    """
    results: list[dict] = []
    mode: str | None = None

    def _append_row(device: str, await_ms: float, r_await: float, w_await: float, util_pct: float, r_s: float, w_s: float, raw: str):
        severity = "INFO"
        if util_pct >= 95:
            severity = "CRITICAL"
        elif util_pct >= 80 or await_ms >= 200:
            severity = "ERROR"
        elif await_ms >= 100:
            severity = "WARNING"
        results.append(
            {
                "device": device,
                "await_ms": await_ms,
                "r_await": r_await,
                "w_await": w_await,
                "util_pct": util_pct,
                "iops": r_s + w_s,
                "severity": severity,
                "log_source": "IOSTAT_OUTPUT",
                "raw": raw,
            }
        )

    for line in text.splitlines():
        ls = line.strip()
        if not ls:
            continue
        if _IOSTAT_HEADER.search(ls):
            mode = "legacy"
            continue
        if _IOSTAT_HEADER_MODERN.search(ls):
            mode = "modern"
            continue
        if ls.startswith("Device") and "r/s" in ls and "rkB/s" in ls and "r_await" in ls:
            mode = "modern"
            continue

        if mode == "legacy":
            m = _IOSTAT_ROW.match(ls)
            if m:
                _append_row(
                    m.group("device"),
                    float(m.group("await")),
                    float(m.group("r_await")),
                    float(m.group("w_await")),
                    float(m.group("util")),
                    float(m.group("r_s")),
                    float(m.group("w_s")),
                    ls,
                )
                continue
            ms = _IOSTAT_ROW_SIMPLE.match(ls)
            if ms:
                results.append(
                    {
                        "device": ms.group("device"),
                        "await_ms": 0.0,
                        "r_await": 0.0,
                        "w_await": 0.0,
                        "util_pct": 0.0,
                        "iops": float(ms.group("tps")),
                        "severity": "INFO",
                        "log_source": "IOSTAT_OUTPUT",
                        "raw": ls,
                    }
                )
        elif mode == "modern":
            m = _IOSTAT_ROW_MODERN.match(ls) or _IOSTAT_ROW_MODERN_EXT.match(ls)
            if m:
                r_a = float(m.group("r_await"))
                w_a = float(m.group("w_await"))
                await_ms = max(r_a, w_a)
                _append_row(
                    m.group("device"),
                    await_ms,
                    r_a,
                    w_a,
                    float(m.group("util")),
                    float(m.group("r_s")),
                    float(m.group("w_s")),
                    ls,
                )

    return results


# ── vmstat parser ───────────────────────────────────────────────
# vmstat 1 5 output:
# procs  -----------memory----------  ---swap-- -----io---- -system-- ------cpu-----
#  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
#  2  0      0 1234567  12345 789012    0    0     1     2  123  456  5  2 93  0  0

_VMSTAT_HEADER = re.compile(r"\s+si\s+so\s+bi\s+bo", re.I)
_VMSTAT_ROW = re.compile(
    r"^\s*(?P<r>\d+)\s+(?P<b>\d+)\s+(?P<swpd>\d+)\s+(?P<free>\d+)\s+"
    r"(?P<buff>\d+)\s+(?P<cache>\d+)\s+(?P<si>\d+)\s+(?P<so>\d+)\s+"
    r"(?P<bi>\d+)\s+(?P<bo>\d+)\s+(?P<in>\d+)\s+(?P<cs>\d+)\s+"
    r"(?P<us>\d+)\s+(?P<sy>\d+)\s+(?P<id>\d+)\s+(?P<wa>\d+)"
)


def parse_vmstat_text(text: str) -> list:
    """Parse vmstat output. Returns list of row dicts flagging swap storms."""
    results = []
    for line in text.splitlines():
        m = _VMSTAT_ROW.match(line)
        if m:
            si = int(m.group("si"))
            so = int(m.group("so"))
            wa = int(m.group("wa"))
            r  = int(m.group("r"))
            severity = "INFO"
            patterns = []
            if si > 500 or so > 500:
                severity = "CRITICAL"
                patterns.append("MEMORY_SWAP_STORM")
            if wa > 30:
                severity = _severity_max(severity, "ERROR")
                patterns.append("IO_QUEUE_TIMEOUT")
            if r > 8:
                patterns.append("CPU_RUNQUEUE_SATURATION")

            results.append({
                "si": si, "so": so, "wa": wa, "r": r,
                "free_kb": int(m.group("free")),
                "swpd_kb": int(m.group("swpd")),
                "severity": severity,
                "patterns": patterns,
                "log_source": "VMSTAT_OUTPUT",
                "raw": line.strip(),
            })
    return results


# ── df parser ──────────────────────────────────────────────────
# df -h output:
# Filesystem              Size  Used Avail Use% Mounted on
# /dev/mapper/vg01-arch   200G  200G     0 100% /arch

_DF_ROW = re.compile(
    r"^(?P<filesystem>\S+)\s+(?P<size>\S+)\s+(?P<used>\S+)\s+(?P<avail>\S+)\s+"
    r"(?P<use_pct>\d+)%\s+(?P<mount>\S+)$"
)
_IGNORE_FS = re.compile(r"tmpfs|devtmpfs|udev|none|overlay|squashfs", re.I)


def parse_df_text(text: str) -> list:
    """Parse df output. Returns list of filesystem rows flagging full/near-full."""
    results = []
    for line in text.splitlines():
        m = _DF_ROW.match(line.strip())
        if not m:
            continue
        fs = m.group("filesystem")
        if _IGNORE_FS.search(fs):
            continue
        use_pct = int(m.group("use_pct"))
        mount   = m.group("mount")

        severity = "INFO"
        pattern  = None
        if use_pct >= 100:
            severity = "CRITICAL"
            pattern  = "FILESYSTEM_ARCH_FULL" if "arch" in mount.lower() else "FILESYSTEM_ANY_FULL"
        elif use_pct >= 95:
            severity = "ERROR"
            pattern  = "FILESYSTEM_ANY_FULL"
        elif use_pct >= 85:
            severity = "WARNING"

        results.append({
            "filesystem": fs,
            "size":       m.group("size"),
            "used":       m.group("used"),
            "avail":      m.group("avail"),
            "use_pct":    use_pct,
            "mount":      mount,
            "severity":   severity,
            "os_pattern": pattern,
            "log_source": "DF_OUTPUT",
            "raw":        line.strip(),
        })
    return results


# ── sar parser (CPU) ──────────────────────────────────────────
# sar -u output:
# 03:00:01 AM     CPU     %user   %nice  %system  %iowait  %steal   %idle
# 03:10:01 AM     all      5.21    0.00     1.82     0.12    25.40   67.45

_SAR_CPU_ROW = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2})\s+(?:AM|PM)?\s+"
    r"(?P<cpu>\S+)\s+"
    r"(?P<user>[\d.]+)\s+(?P<nice>[\d.]+)\s+(?P<system>[\d.]+)\s+"
    r"(?P<iowait>[\d.]+)\s+(?P<steal>[\d.]+)\s+(?P<idle>[\d.]+)"
)


def parse_sar_cpu_text(text: str) -> list:
    """Parse sar -u output. Flags high steal or zero idle."""
    results = []
    for line in text.splitlines():
        m = _SAR_CPU_ROW.match(line.strip())
        if m and m.group("cpu") == "all":
            steal = float(m.group("steal"))
            idle  = float(m.group("idle"))
            severity = "INFO"
            patterns = []
            if steal > 20:
                severity = _severity_max(severity, "ERROR")
                patterns.append("CPU_STEAL_TIME")
            if idle < 5:
                severity = _severity_max(severity, "CRITICAL")
                patterns.append("CPU_RUNQUEUE_SATURATION")
            results.append({
                "time":    m.group("time"),
                "steal":   steal,
                "idle":    idle,
                "iowait":  float(m.group("iowait")),
                "user":    float(m.group("user")),
                "severity": severity,
                "patterns": patterns,
                "log_source": "SAR_CPU_OUTPUT",
                "raw": line.strip(),
            })
    return results
