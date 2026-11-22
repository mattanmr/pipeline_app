"""
core/versioning.py

The Version Cascade.

Two distinct operations live here, matching how the pipeline was
designed:

1. publish() / publish_multiple() – a category (comp, FX, generated,
   edit, sound, Client_Materials, AI_Generated/Video, ...) gets a new
   version from one or multiple source files/folders. The sources are
   copied into versions/vXXX, then master/ is overwritten with the
   same content, and the category's tracking JSON records which
   version is now master.

2. record_cut() – an explicit, artist-driven composition step: "this
   shot's new cut (vYYY) is made from these specific category
   versions".
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Sequence

from core.io_handler import safe_copy, clear_folder, source_size_bytes
from utils.metadata import (
    read_json, write_json, next_version_number,
    make_version_record, make_source_ref,
)
from utils.naming import sanitize_filename, sanitize_name


def _target_name_for_source(src: Path, sanitize_names: bool) -> str:
    if not sanitize_names:
        return src.name
    return sanitize_filename(src.name) if src.is_file() else sanitize_name(src.name)


def publish_multiple(category_path: str | Path, sources: Sequence[str | Path],
                     tracking_file: str, version_format: str = "v{:03d}",
                     extra_fields: dict | None = None, max_size_gb: float = 0,
                     sanitize_names: bool = False, progress_callback=None) -> str:
    """
    Publish one or more `sources` (files, folders, or a mix of both) into
    a single new version of the category at `category_path`.

    Returns the new version string (e.g. "v001").
    """
    source_paths = [Path(s) for s in sources]
    if not source_paths:
        raise ValueError("At least one source file or folder is required.")
    for src in source_paths:
        if not src.exists():
            raise FileNotFoundError(f"Source does not exist: {src}")

    total_bytes = sum(source_size_bytes(src) for src in source_paths)
    if max_size_gb and total_bytes > max_size_gb * (1024 ** 3):
        raise RuntimeError(
            f"Combined sources are {total_bytes / (1024**3):.2f} GB, "
            f"which exceeds the configured limit of {max_size_gb} GB."
        )

    category_path = Path(category_path)
    tracking_path = category_path / tracking_file
    data = read_json(tracking_path)

    version = next_version_number(data["versions"], version_format)
    version_dir = category_path / "versions" / version
    version_dir.mkdir(parents=True, exist_ok=True)

    master_dir = category_path / "master"
    master_dir.mkdir(parents=True, exist_ok=True)
    clear_folder(master_dir)

    used_names: set[str] = set()
    for src in source_paths:
        target_name = _target_name_for_source(src, sanitize_names)
        # Disambiguate if two sources map to the same target filename
        base_name = target_name
        counter = 2
        while target_name in used_names:
            if "." in base_name and src.is_file():
                stem, _, ext = base_name.rpartition(".")
                target_name = f"{stem}_{counter}.{ext}"
            else:
                target_name = f"{base_name}_{counter}"
            counter += 1
        used_names.add(target_name)

        safe_copy(src, version_dir / target_name, max_size_gb=0, progress_callback=progress_callback)
        safe_copy(src, master_dir / target_name, max_size_gb=0)

    merged_extra = dict(extra_fields) if extra_fields else {}
    if len(source_paths) > 1:
        merged_extra["sources"] = [str(s) for s in source_paths]

    source_desc = str(source_paths[0]) if len(source_paths) == 1 else ", ".join(str(s) for s in source_paths)
    record = make_version_record(version, source_desc=source_desc, extra_fields=merged_extra or None)
    data["versions"].append(record)
    data["current_master"] = version
    write_json(tracking_path, data)

    return version


def publish(category_path: str | Path, source: str | Path | Sequence[str | Path],
            tracking_file: str, version_format: str = "v{:03d}",
            extra_fields: dict | None = None, max_size_gb: float = 0,
            sanitize_names: bool = False, progress_callback=None) -> str:
    """
    Publish `source` (a single file/folder or a list of files/folders)
    as the next version of the category at `category_path`.
    """
    if isinstance(source, (list, tuple)):
        sources = list(source)
    else:
        sources = [source]
    return publish_multiple(
        category_path,
        sources,
        tracking_file,
        version_format=version_format,
        extra_fields=extra_fields,
        max_size_gb=max_size_gb,
        sanitize_names=sanitize_names,
        progress_callback=progress_callback,
    )


def record_cut(unit_path: str | Path, tracking_file: str, sources: list[dict[str, Any]],
               versions_key: str = "cuts", master_key: str = "current_cut_master",
               cut_versions_dir: str = "cut_versions", cut_master_dir: str = "cut_master",
               version_format: str = "v{:03d}") -> str:
    """
    Record a composition step: a new cut/master at `unit_path` is
    built from `sources` (a list of dicts from make_source_ref(),
    e.g. [{"category": "comp", "version": "v005"}, ...]).
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
