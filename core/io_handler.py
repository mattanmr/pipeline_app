"""
core/io_handler.py

Handles moving heavy media (EXR sequences, DaVinci/Fusion renders,
multi-GB video files) from the artist's fast local scratch disk to
the shared/master location, without ever leaving a half-copied,
corrupt result in the destination if something goes wrong mid-copy.

Strategy: copy into a sibling '<name>.partial' path first, then do
an atomic rename/replace into the real destination. Works for both
single files and whole directories (image sequences).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

ProgressCallback = Optional[Callable[[int, int], None]]  # (done, total) in bytes


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _copy_file_with_progress(src: Path, dst: Path, total: int, done: int,
                              callback: ProgressCallback, chunk_size: int = 8 * 1024 * 1024) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            chunk = fsrc.read(chunk_size)
            if not chunk:
                break
            fdst.write(chunk)
            done += len(chunk)
            if callback:
                callback(done, total)
    shutil.copystat(src, dst)
    return done


def safe_copy(source: str | Path, destination: str | Path,
              max_size_gb: float = 0, progress_callback: ProgressCallback = None) -> Path:
    """
    Safely copy a file OR a directory (e.g. an EXR sequence folder)
    from `source` to `destination`. Copies into a '.partial' staging
    path first, then atomically renames into place.

    Returns the final destination path.
    Raises RuntimeError if max_size_gb > 0 and the source exceeds it.
    """
    source = Path(source)
    destination = Path(destination)
    if not source.exists():
        raise FileNotFoundError(f"Source does not exist: {source}")

    total_bytes = source.stat().st_size if source.is_file() else _dir_size(source)
    if max_size_gb and total_bytes > max_size_gb * (1024 ** 3):
        raise RuntimeError(
            f"Source is {total_bytes / (1024**3):.2f} GB, "
            f"which exceeds the configured limit of {max_size_gb} GB."
        )

    staging = destination.with_name(destination.name + ".partial")
    if staging.exists():
        if staging.is_dir():
            shutil.rmtree(staging)
        else:
            staging.unlink()

    done = 0
    if source.is_file():
        done = _copy_file_with_progress(source, staging, total_bytes, done, progress_callback)
    else:
        staging.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.rglob("*")):
            if item.is_dir():
                continue
            rel = item.relative_to(source)
            done = _copy_file_with_progress(item, staging / rel, total_bytes, done, progress_callback)

    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    staging.replace(destination)
    return destination


def clear_folder(path: str | Path) -> None:
    """Empty a folder's contents without deleting the folder itself (used to reset 'master/')."""
    path = Path(path)
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
