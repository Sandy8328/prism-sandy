"""
zip_evidence.py — Safe AHF/TFA-style ZIP extraction for text log analysis.

Does not execute archive members; skips path traversal and oversized files.
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from typing import Any


def safe_extract_zip(
    zip_path: str,
    dest_dir: str,
    *,
    max_uncompressed_bytes: int = 200 * 1024 * 1024,
    max_members: int = 8000,
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
        for idx, info in enumerate(zf.infolist()):
            if idx >= max_members:
                skipped.append({"path": "*", "reason": "max_zip_members_exceeded"})
                break
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


def _tar_open_mode(archive_path: str) -> str | None:
    pl = (archive_path or "").lower()
    if pl.endswith(".tar.xz"):
        return "r:xz"
    if pl.endswith(".tar.gz") or pl.endswith(".tgz"):
        return "r:gz"
    if pl.endswith(".tar.bz2"):
        return "r:bz2"
    if pl.endswith(".tar"):
        return "r:"
    return None


def safe_extract_tar(
    tar_path: str,
    dest_dir: str,
    *,
    max_member_bytes: int = 200 * 1024 * 1024,
    max_members: int = 250_000,
) -> dict[str, Any]:
    """
    Extract regular files from a tar / tar.gz / tar.xz / tar.bz2 bundle.

    Skips symlinks/hardlinks/special nodes and path-unsafe member names.
    """
    mode = _tar_open_mode(tar_path)
    if not mode:
        return {"extracted": [], "skipped": [{"path": tar_path, "reason": "unsupported_tar_suffix"}]}

    dest_abs = os.path.abspath(dest_dir)
    os.makedirs(dest_abs, exist_ok=True)
    written: list[str] = []
    skipped: list[dict[str, str]] = []
    try:
        with tarfile.open(tar_path, mode) as tf:
            for idx, member in enumerate(tf):
                if idx >= max_members:
                    skipped.append({"path": "*", "reason": "max_tar_members_exceeded"})
                    break
                if not member.isfile():
                    continue
                if member.size and member.size > max_member_bytes:
                    skipped.append({"path": member.name, "reason": "file_too_large"})
                    continue
                name = (member.name or "").replace("\\", "/").lstrip("/")
                rel = name
                if not name or ".." in name.split("/"):
                    skipped.append({"path": rel, "reason": "path_traversal_or_empty"})
                    continue
                target = os.path.normpath(os.path.join(dest_abs, name))
                if not target.startswith(dest_abs + os.sep):
                    skipped.append({"path": rel, "reason": "unsafe_target_path"})
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                try:
                    fobj = tf.extractfile(member)
                except (OSError, tarfile.TarError, KeyError) as e:
                    skipped.append({"path": rel, "reason": f"extractfile_error:{e}"})
                    continue
                if fobj is None:
                    skipped.append({"path": rel, "reason": "non_extractable_member"})
                    continue
                try:
                    data = fobj.read()
                finally:
                    fobj.close()
                if len(data) > max_member_bytes:
                    skipped.append({"path": rel, "reason": "file_too_large_after_read"})
                    continue
                with open(target, "wb") as out:
                    out.write(data)
                written.append(target)
    except (OSError, tarfile.TarError, EOFError) as e:
        return {"extracted": written, "skipped": skipped + [{"path": tar_path, "reason": f"tar_open_failed:{e}"}]}
    return {"extracted": written, "skipped": skipped}
