"""
core/manager.py

Reads config/pipeline_schema.json and creates the physical directory
tree + the initial (empty) tracking JSON files for a project, a
sequence, or a shot. This is the only module that knows how the
schema maps onto folders on disk — everything else (versioning,
GUI, CLI) calls into this module rather than hardcoding paths.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from utils.metadata import write_json
from utils.naming import sanitize_name


def load_schema(schema_path: str | Path) -> dict[str, Any]:
    """Load and return the pipeline schema as a dict."""
    schema_path = Path(schema_path)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _make_versionable(unit_path: Path, tracking_file: str, extra_keys: dict | None = None) -> None:
    """
    Create the standard versions/ + master/ + <tracking>.json trio
    inside `unit_path`. This is the repeating pattern used by every
    simple category (References, Footage, Animation, ...).
    """
    (unit_path / "versions").mkdir(parents=True, exist_ok=True)
    (unit_path / "master").mkdir(parents=True, exist_ok=True)

    tracking_path = unit_path / tracking_file
    if not tracking_path.exists():
        payload = {
            "created": _now_iso(),
            "current_master": None,   # e.g. "v003"
            "versions": [],            # list of version records, newest last
        }
        if extra_keys:
            payload["extra_fields"] = extra_keys
        write_json(tracking_path, payload)


def _make_cut_unit(unit_path: Path, tracking_file: str, cut_versions_dir: str,
                    cut_master_dir: str, extra_top_keys: dict | None = None) -> None:
    """
    Create the cut_versions/ + cut_master/ + <tracking>.json trio used
    at the shot and sequence level to record *composition* (which
    child versions were combined to produce this cut).
    """
    (unit_path / cut_versions_dir).mkdir(parents=True, exist_ok=True)
    (unit_path / cut_master_dir).mkdir(parents=True, exist_ok=True)

    tracking_path = unit_path / tracking_file
    if not tracking_path.exists():
        payload = {
            "created": _now_iso(),
            "current_cut_master": None,
            "cuts": [],   # list of {"version": "v00X", "sources": [...], "created": ...}
        }
        if extra_top_keys:
            payload.update(extra_top_keys)
        write_json(tracking_path, payload)


def create_project(root_path: str | Path, project_name: str, schema: dict[str, Any],
                    production_folder_target: str | None = None) -> Path:
    """
    Create a new project tree under `root_path`, following `schema`.
    Returns the path to the created project root.
    """
    project_name = sanitize_name(project_name)
    project_root = Path(root_path) / project_name
    project_root.mkdir(parents=True, exist_ok=False)

    # project_info.json — metadata, production-folder link, schema version
    info_path = project_root / schema["project_info_file"]
    write_json(info_path, {
        "project_name": project_name,
        "created": _now_iso(),
        "structure_schema": "pipeline_schema.json",
        "structure_version": schema.get("structure_version", 1),
        "production_folder_link": production_folder_target,
    })

    # Shortcut placeholder to the (externally managed) production folder.
    # Real OS shortcuts differ per platform; we drop a small pointer file
    # so the link is at least discoverable everywhere.
    shortcut_name = schema["production_folder_shortcut"]
    shortcut_path = project_root / f"{shortcut_name}.link.json"
    write_json(shortcut_path, {
        "target": production_folder_target,
        "note": "Points at the external production folder. "
                "Not managed by this tool.",
    })

    # Project-level general categories: References, Client_Materials, Docs
    for cat_name, cat_def in schema["project_level_categories"].items():
        cat_path = project_root / cat_name
        _make_versionable(cat_path, cat_def["tracking_file"])

    # Sequences/ container (empty until sequences are created)
    (project_root / schema["sequences"]["dir_name"]).mkdir(parents=True, exist_ok=True)

    # Export/
    export_def = schema["export"]
    export_path = project_root / export_def["dir_name"]
    (export_path / export_def["versions_dir"]).mkdir(parents=True, exist_ok=True)
    (export_path / export_def["master_dir"]).mkdir(parents=True, exist_ok=True)
    export_tracking = export_path / export_def["tracking_file"]
    if not export_tracking.exists():
        write_json(export_tracking, {
            "created": _now_iso(),
            "current_master": None,
            "masters": [],   # list of {"version": "v00X", "sources": [...], "created": ...}
        })

    return project_root


def create_sequence(project_root: str | Path, sequence_name: str,
                     schema: dict[str, Any]) -> Path:
    """Create a sequence folder (with its cut tracking) inside a project."""
    sequence_name = sanitize_name(sequence_name)
    seq_def = schema["sequences"]
    seq_root = Path(project_root) / seq_def["dir_name"] / sequence_name
    seq_root.mkdir(parents=True, exist_ok=False)

    _make_cut_unit(
        seq_root,
        tracking_file=seq_def["tracking_file"],
        cut_versions_dir=seq_def["cut_versions_dir"],
        cut_master_dir=seq_def["cut_master_dir"],
        extra_top_keys={"shots": []},   # membership: which shots belong here
    )

    (seq_root / seq_def["shots"]["dir_name"]).mkdir(parents=True, exist_ok=True)
    return seq_root


def create_shot(project_root: str | Path, sequence_name: str, shot_name: str,
                 schema: dict[str, Any]) -> Path:
    """Create a shot folder (with all its categories) inside a sequence."""
    sequence_name = sanitize_name(sequence_name)
    shot_name = sanitize_name(shot_name)

    seq_def = schema["sequences"]
    shot_def = seq_def["shots"]

    seq_root = Path(project_root) / seq_def["dir_name"] / sequence_name
    if not seq_root.exists():
        raise FileNotFoundError(f"Sequence does not exist yet: {seq_root}")

    shot_root = seq_root / shot_def["dir_name"] / shot_name
    shot_root.mkdir(parents=True, exist_ok=False)

    _make_cut_unit(
        shot_root,
        tracking_file=shot_def["tracking_file"],
        cut_versions_dir=shot_def["cut_versions_dir"],
        cut_master_dir=shot_def["cut_master_dir"],
        extra_top_keys={"parent_sequence": sequence_name},
    )

    # Simple categories: Footage, Animation, Renders, Effects, Sound
    for cat_name, cat_def in shot_def["categories"].items():
        _make_versionable(shot_root / cat_name, cat_def["tracking_file"])

    # AI_Generated/Images and AI_Generated/Video
    ai_def = shot_def["ai_generated"]
    ai_root = shot_root / ai_def["dir_name"]
    for subtype_name, subtype_def in ai_def["subtypes"].items():
        _make_versionable(
            ai_root / subtype_name,
            subtype_def["tracking_file"],
            extra_keys={"fields": subtype_def["extra_fields"]},
        )

    # client_material_usage.json — which Client_Materials version(s) used here
    usage_path = shot_root / shot_def["client_material_usage_file"]
    if not usage_path.exists():
        write_json(usage_path, {"created": _now_iso(), "usages": []})

    # Register this shot with its parent sequence's membership list.
    _register_shot_with_sequence(seq_root, seq_def["tracking_file"], shot_name)

    return shot_root


def _register_shot_with_sequence(seq_root: Path, seq_tracking_file: str, shot_name: str) -> None:
    from utils.metadata import read_json  # local import avoids a cycle at module load

    tracking_path = seq_root / seq_tracking_file
    data = read_json(tracking_path)
    shots = data.setdefault("shots", [])
    if shot_name not in shots:
        shots.append(shot_name)
    write_json(tracking_path, data)
