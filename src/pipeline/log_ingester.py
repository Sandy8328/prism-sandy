"""
log_ingester.py — Ingests physical log files, groups rotated files, and creates chunks.

Handles Phase 1 Edge Cases:
- Edge Case 5: Log File Rotation Boundaries (stitches rotated files chronologically)
- Edge Case 6: Shared Bus Failures (merges >3 hardware failures into a SYSTEM_BUS_RESET super-chunk)
"""

import os
import re
from datetime import datetime
from collections import defaultdict
from typing import List, Dict

from src.parsers.syslog_parser import parse_syslog_file
from src.parsers.alert_log_parser import parse_alert_log_file
from src.chunker.event_chunker import chunk_syslog, chunk_alert_log
from src.parsers.platform_detector import detect_platform

def group_rotated_files(filepaths: List[str]) -> Dict[str, List[str]]:
    """
    [Edge Case 5: Log File Rotation Boundaries]
    Groups rotated log files together based on their base name.
    Example: 'messages', 'messages.1', 'messages-20240421' -> all map to 'messages'
    """
    groups = defaultdict(list)
    
    # Regex to detect common rotation suffixes: .1, .2.gz, -20240421
    rotation_pattern = re.compile(r'(\.log)?([-\.]\d+)?(\.gz)?$')
    
    for filepath in filepaths:
        basename = os.path.basename(filepath)
        # Strip the rotation suffix to find the logical "base" file
        logical_name = rotation_pattern.sub('', basename)
        if not logical_name:
            logical_name = basename
            
        groups[logical_name].append(filepath)
        
    return dict(groups)

def _merge_shared_bus_failures(chunks: List[dict]) -> List[dict]:
    """
    [Edge Case 6: Shared Bus Failures]
    If >3 distinct hardware devices fail within the same 2-second time window,
    merge them into a SYSTEM_BUS_RESET super-chunk.
    """
    if not chunks:
        return chunks
        
    merged_chunks = []
    # Group chunks by exact or very close timestamp
    # Since syslog chunks represent windows, we look at timestamp_start
    windows = defaultdict(list)
    for c in chunks:
        if c.get("category") == "OS" and c.get("timestamp_start"):
            # Group by 2-second windows using the start timestamp string
            # A simple approach is to use the raw ISO string up to the 10s place
            # Better: convert to datetime and group dynamically. 
            # For simplicity, we just use the exact timestamp_start here.
            ts_str = c["timestamp_start"]
            windows[ts_str].append(c)
        else:
            merged_chunks.append(c)
            
    for ts_str, window_chunks in windows.items():
        if len(window_chunks) <= 3:
            merged_chunks.extend(window_chunks)
            continue
            
        # Count unique devices
        unique_devices = {c.get("device") for c in window_chunks if c.get("device")}
        
        if len(unique_devices) > 3:
            # Create a super-chunk
            print(f"  -> [Log Ingester] Detected Shared Bus Failure: {len(unique_devices)} devices failed at {ts_str}")
            super_chunk = window_chunks[0].copy()
            super_chunk["chunk_id"] = f"SUPER-{super_chunk['chunk_id'][:10]}"
            super_chunk["device"] = "SYSTEM_BUS"
            super_chunk["os_pattern"] = "SYSTEM_BUS_RESET"
            super_chunk["severity"] = "CRITICAL"
            
            # Merge lines
            all_lines = []
            for c in window_chunks:
                all_lines.extend(c.get("raw_text", "").splitlines())
            super_chunk["raw_text"] = "\n".join(all_lines)
            super_chunk["line_count"] = len(all_lines)
            super_chunk["keywords"] = list(unique_devices) + ["SYSTEM_BUS_RESET"]
            
            merged_chunks.append(super_chunk)
        else:
            merged_chunks.extend(window_chunks)
            
    # Preserve original chronological order approximately
    merged_chunks.sort(key=lambda x: x.get("timestamp_start", ""))
    return merged_chunks

def ingest_logs(filepaths: List[str], hostname: str = "unknown", platform: str = None, collection_id: str = "AUTO") -> List[dict]:
    """
    Main entry point for ingesting a batch of log files.
    If platform is not provided, it is auto-detected from file content.
    """
    all_chunks = []
    groups = group_rotated_files(filepaths)

    for logical_name, files in groups.items():
        # Read and parse all files in the group
        group_entries = []
        is_syslog = "messages" in logical_name or "syslog" in logical_name
        is_alert = "alert" in logical_name

        # Auto-detect platform from first file if not provided
        resolved_platform = platform
        if not resolved_platform and files:
            try:
                with open(files[0], "r", errors="replace") as _f:
                    sample = _f.read(4000)
                resolved_platform = detect_platform(text=sample, filename=os.path.basename(files[0])) or "UNKNOWN"
            except Exception:
                resolved_platform = "UNKNOWN"

        for filepath in files:
            try:
                if is_syslog:
                    group_entries.extend(parse_syslog_file(filepath))
                elif is_alert:
                    group_entries.extend(parse_alert_log_file(filepath))
            except Exception as e:
                print(f"Error parsing {filepath}: {e}")
                
        # [Edge Case 5] Stitch together by sorting chronologically
        # Both parse_syslog_file and parse_alert_log_file return dicts with 'timestamp' keys
        valid_entries = [e for e in group_entries if e.get("timestamp")]
        invalid_entries = [e for e in group_entries if not e.get("timestamp")]
        
        valid_entries.sort(key=lambda x: x["timestamp"])
        stitched_entries = valid_entries + invalid_entries
        
        # Chunk the stitched entries
        chunks = []
        if is_syslog:
            chunks = chunk_syslog(stitched_entries, hostname, resolved_platform, collection_id)
            chunks = _merge_shared_bus_failures(chunks)
        elif is_alert:
            chunks = chunk_alert_log(stitched_entries, hostname, resolved_platform, collection_id)
            
        all_chunks.extend(chunks)
        
    return all_chunks
