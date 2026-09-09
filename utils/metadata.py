"""
utils/metadata.py

Helpers for reading/writing the tracking JSON files, and for building
the small structured records (version entries, source references,
AI generation metadata) that get appended to them.
"""

from __future__ import annotations

import json
import datetime as _dt
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    """
    Write JSON atomically: write to a temp file in the same directory,
    then replace — so a crash mid-write never corrupts the tracking
    file (these are small, but they're load-bearing for the pipeline).
    """
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def next_version_number(existing_versions: list[dict], version_format: str = "v{:03d}") -> str:
    """
    Given the 'versions' list already in a tracking file, compute the
    next version string (v001, v002, ...).
    """
    n = 0
    for entry in existing_versions:
        v = entry.get("version", "")
        digits = "".join(ch for ch in v if ch.isdigit())
        if digits.isdigit():
            n = max(n, int(digits))
    return version_format.format(n + 1)


def make_version_record(version: str, source_desc: str, extra_fields: dict | None = None) -> dict:
    """Build one entry for a category's 'versions' list."""
    record = {
        "version": version,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": source_desc,
    }
    if extra_fields:
        record.update(extra_fields)
    return record


def make_source_ref(category: str, version: str) -> dict:
    """
    A pointer used in composition records (shot_info.json,
    sequence_info.json, export_info.json, ai_video_info.json 'source').
    e.g. {"category": "Footage", "version": "v002"}
    """
    return {"category": category, "version": version}
