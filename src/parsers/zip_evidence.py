"""
zip_evidence.py — Safe AHF/TFA-style ZIP extraction for text log analysis.

Does not execute archive members; skips path traversal and oversized files.
"""

from __future__ import annotations

import os
import zipfile
from typing import Any


def safe_extract_zip(
    zip_path: str,
    dest_dir: str,
    *,
    max_uncompressed_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """
    Extract members under dest_dir only.

    Returns:
        {
          "extracted": list of absolute paths written,
          "skipped": list of {"path": str, "reason": str},
        }
    """
    dest_abs = os.path.abspath(dest_dir)
    os.makedirs(dest_abs, exist_ok=True)
    written: list[str] = []
    skipped: list[dict[str, str]] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = (info.filename or "").replace("\\", "/").lstrip("/")
            rel = name
            if not name or ".." in name.split("/"):
                skipped.append({"path": rel, "reason": "path_traversal_or_empty"})
                continue
            if info.file_size > max_uncompressed_bytes:
                skipped.append({"path": rel, "reason": "file_too_large"})
                continue
            target = os.path.normpath(os.path.join(dest_abs, name))
            if not target.startswith(dest_abs + os.sep):
                skipped.append({"path": rel, "reason": "unsafe_target_path"})
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as out:
                out.write(src.read())
            written.append(target)
    return {"extracted": written, "skipped": skipped}
