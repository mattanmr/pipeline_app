"""
core/versioning.py

The Version Cascade.

Two distinct operations live here, matching how the pipeline was
designed:

1. publish() — a single category (Footage, Animation, AI_Generated/
   Video, ...) gets a new version. The file/folder is copied into
   versions/vXXX, then master/ is overwritten with the same content,
   and the category's tracking JSON records which version is now
   master. This is the "leaf" level operation.

2. record_cut() — an explicit, artist-driven composition step: "this
   shot's new cut (vYYY) is made from these specific category
   versions". This is deliberately NOT automatic — publishing a new
   Animation version does not by itself create a new shot cut, the
   same way generating new AI images doesn't automatically become
   part of an edit. The same record_cut()-shaped function is reused
   at the sequence level (composed from shot cuts) and the project
   Export level (composed from sequence cuts), since the schema
   gives all three the same versions/master + composition-record
   shape.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from core.io_handler import safe_copy, clear_folder
from utils.metadata import (
    read_json, write_json, next_version_number,
    make_version_record, make_source_ref,
)


def publish(category_path: str | Path, source: str | Path,
            tracking_file: str, version_format: str = "v{:03d}",
            extra_fields: dict | None = None, max_size_gb: float = 0,
            progress_callback=None) -> str:
    """
    Publish `source` (a file or a folder, e.g. an EXR sequence) as the
    next version of the category at `category_path`.

    `extra_fields` is where AI generation metadata goes, e.g.
        {"model": "Veo 3", "prompt": "wide shot of..."}
    or, for an AI video, also a "source" list built with make_source_ref().

    Returns the new version string (e.g. "v006").
    """
    category_path = Path(category_path)
    tracking_path = category_path / tracking_file
    data = read_json(tracking_path)

    version = next_version_number(data["versions"], version_format)
    version_dir = category_path / "versions" / version
    versioned_target = version_dir / Path(source).name

    safe_copy(source, versioned_target, max_size_gb=max_size_gb, progress_callback=progress_callback)

    # master/ is always overwritten by the latest publish.
    master_dir = category_path / "master"
    master_dir.mkdir(parents=True, exist_ok=True)
    clear_folder(master_dir)
    safe_copy(source, master_dir / Path(source).name, max_size_gb=max_size_gb)

    record = make_version_record(version, source_desc=str(source), extra_fields=extra_fields)
    data["versions"].append(record)
    data["current_master"] = version
    write_json(tracking_path, data)

    return version


def record_cut(unit_path: str | Path, tracking_file: str, sources: list[dict[str, Any]],
               versions_key: str = "cuts", master_key: str = "current_cut_master",
               cut_versions_dir: str = "cut_versions", cut_master_dir: str = "cut_master",
               version_format: str = "v{:03d}") -> str:
    """
    Record a composition step: a new cut/master at `unit_path` is
    built from `sources` (a list of dicts from make_source_ref(),
    e.g. [{"category": "Animation", "version": "v005"}, ...]).

    Used for:
      - shot_info.json      (sources = category versions)
      - sequence_info.json  (sources = shot cut versions)
      - export_info.json    (sources = sequence cut versions)

    Returns the new cut/master version string.
    """
    unit_path = Path(unit_path)
    tracking_path = unit_path / tracking_file
    data = read_json(tracking_path)

    existing = data.get(versions_key, [])
    version = next_version_number(
        [{"version": e["version"]} for e in existing], version_format
    )

    record = {
        "version": version,
        "sources": sources,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    existing.append(record)
    data[versions_key] = existing
    data[master_key] = version
    write_json(tracking_path, data)

    # Mirror the version into a cut_versions/vXXX marker folder and
    # refresh cut_master/ so the filesystem reflects the tracking file.
    (unit_path / cut_versions_dir / version).mkdir(parents=True, exist_ok=True)
    master_dir = unit_path / cut_master_dir
    master_dir.mkdir(parents=True, exist_ok=True)

    return version


def record_client_material_usage(shot_path: str | Path, usage_file: str,
                                  client_material_version: str) -> None:
    """Note that a shot drew on a specific Client_Materials version."""
    shot_path = Path(shot_path)
    tracking_path = shot_path / usage_file
    data = read_json(tracking_path)
    data.setdefault("usages", []).append({
        "client_materials_version": client_material_version,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
    })
    write_json(tracking_path, data)
