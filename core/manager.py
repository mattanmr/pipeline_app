"""
core/manager.py

Reads config/pipeline_schema.json and creates/manages the physical
directory tree + tracking JSON files for a project, a sequence, or a
shot (including sequence/shot deletion and moving shots across sequences
with automatic folder/file renaming).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
from pathlib import Path
from typing import Any

from utils.metadata import read_json, write_json
from utils.naming import sanitize_name, format_shot_name, rename_shot_for_sequence


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
    inside `unit_path`.
    """
    (unit_path / "versions").mkdir(parents=True, exist_ok=True)
    (unit_path / "master").mkdir(parents=True, exist_ok=True)

    tracking_path = unit_path / tracking_file
    if not tracking_path.exists():
        payload = {
            "created": _now_iso(),
            "current_master": None,
            "versions": [],
        }
        if extra_keys:
            payload["extra_fields"] = extra_keys
        write_json(tracking_path, payload)


def _make_cut_unit(unit_path: Path, tracking_file: str, cut_versions_dir: str,
                   cut_master_dir: str, extra_top_keys: dict | None = None) -> None:
    """
    Create the cut_versions/ + cut_master/ + <tracking>.json trio used
    at the shot and sequence level to record composition.
    """
    (unit_path / cut_versions_dir).mkdir(parents=True, exist_ok=True)
    (unit_path / cut_master_dir).mkdir(parents=True, exist_ok=True)

    tracking_path = unit_path / tracking_file
    if not tracking_path.exists():
        payload = {
            "created": _now_iso(),
            "current_cut_master": None,
            "cuts": [],
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

    info_path = project_root / schema["project_info_file"]
    write_json(info_path, {
        "project_name": project_name,
        "created": _now_iso(),
        "structure_schema": "pipeline_schema.json",
        "structure_version": schema.get("structure_version", 1),
        "production_folder_link": production_folder_target,
    })

    shortcut_name = schema["production_folder_shortcut"]
    shortcut_path = project_root / f"{shortcut_name}.link.json"
    write_json(shortcut_path, {
        "target": production_folder_target,
        "note": "Points at the external production folder. "
                "Not managed by this tool.",
    })

    for cat_name, cat_def in schema["project_level_categories"].items():
        cat_path = project_root / cat_name
        _make_versionable(cat_path, cat_def["tracking_file"])

    (project_root / schema["sequences"]["dir_name"]).mkdir(parents=True, exist_ok=True)

    export_def = schema["export"]
    export_path = project_root / export_def["dir_name"]
    (export_path / export_def["versions_dir"]).mkdir(parents=True, exist_ok=True)
    (export_path / export_def["master_dir"]).mkdir(parents=True, exist_ok=True)
    export_tracking = export_path / export_def["tracking_file"]
    if not export_tracking.exists():
        write_json(export_tracking, {
            "created": _now_iso(),
            "current_master": None,
            "masters": [],
        })

    return project_root


def create_sequence(project_root: str | Path, sequence_name: str,
                    schema: dict[str, Any]) -> Path:
    """Create a sequence folder (with its cut tracking and sequence categories) inside a project."""
    sequence_name = sanitize_name(sequence_name)
    seq_def = schema["sequences"]
    seq_root = Path(project_root) / seq_def["dir_name"] / sequence_name
    seq_root.mkdir(parents=True, exist_ok=False)

    _make_cut_unit(
        seq_root,
        tracking_file=seq_def["tracking_file"],
        cut_versions_dir=seq_def["cut_versions_dir"],
        cut_master_dir=seq_def["cut_master_dir"],
        extra_top_keys={"shots": []},
    )

    # Sequence-level categories: edit, sound
    for cat_name, cat_def in seq_def.get("categories", {}).items():
        _make_versionable(seq_root / cat_name, cat_def["tracking_file"])

    (seq_root / seq_def["shots"]["dir_name"]).mkdir(parents=True, exist_ok=True)
    return seq_root


def create_shot(project_root: str | Path, sequence_name: str, shot_name: str,
                schema: dict[str, Any]) -> Path:
    """
    Create a shot folder (with all its categories) inside a sequence.
    Automatically prefixes the shot name with '<sequence_name>_'.
    """
    sequence_name = sanitize_name(sequence_name)
    shot_name = format_shot_name(sequence_name, shot_name)

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

    for cat_name, cat_def in shot_def["categories"].items():
        _make_versionable(shot_root / cat_name, cat_def["tracking_file"])

    if "ai_generated" in shot_def:
        ai_def = shot_def["ai_generated"]
        ai_root = shot_root / ai_def["dir_name"]
        for subtype_name, subtype_def in ai_def["subtypes"].items():
            _make_versionable(
                ai_root / subtype_name,
                subtype_def["tracking_file"],
                extra_keys={"fields": subtype_def["extra_fields"]},
            )

    usage_path = shot_root / shot_def["client_material_usage_file"]
    if not usage_path.exists():
        write_json(usage_path, {"created": _now_iso(), "usages": []})

    _register_shot_with_sequence(seq_root, seq_def["tracking_file"], shot_name)

    return shot_root


def _resolve_existing_shot_root(seq_root: Path, sequence_name: str,
                                shot_name: str, shots_dir_name: str) -> Path:
    shots_dir = seq_root / shots_dir_name
    cand1 = shots_dir / sanitize_name(shot_name)
    if cand1.exists():
        return cand1
    cand2 = shots_dir / format_shot_name(sequence_name, shot_name)
    if cand2.exists():
        return cand2
    raise FileNotFoundError(f"Shot '{shot_name}' not found in sequence '{sequence_name}'.")


def delete_shot(project_root: str | Path, sequence_name: str, shot_name: str,
                schema: dict[str, Any]) -> None:
    """
    Delete a shot folder and unregister it from its parent sequence's
    tracking JSON.
    """
    sequence_name = sanitize_name(sequence_name)
    seq_def = schema["sequences"]
    shot_def = seq_def["shots"]

    seq_root = Path(project_root) / seq_def["dir_name"] / sequence_name
    if not seq_root.exists():
        raise FileNotFoundError(f"Sequence does not exist: {seq_root}")

    shot_root = _resolve_existing_shot_root(seq_root, sequence_name, shot_name, shot_def["dir_name"])
    actual_shot_name = shot_root.name
    shutil.rmtree(shot_root)
    _unregister_shot_from_sequence(seq_root, seq_def["tracking_file"], actual_shot_name)


def _replace_in_json_value(val: Any, old_shot: str, new_shot: str,
                           old_seq: str, new_seq: str) -> Any:
    if isinstance(val, str):
        updated = val.replace(old_shot, new_shot)
        updated = updated.replace(f"/{old_seq}/", f"/{new_seq}/")
        updated = updated.replace(f"\\{old_seq}\\", f"\\{new_seq}\\")
        return updated
    if isinstance(val, list):
        return [_replace_in_json_value(item, old_shot, new_shot, old_seq, new_seq) for item in val]
    if isinstance(val, dict):
        return {
            k: _replace_in_json_value(v, old_shot, new_shot, old_seq, new_seq)
            for k, v in val.items()
        }
    return val


def _rename_shot_contents(shot_root: Path, old_shot_name: str, new_shot_name: str,
                          old_sequence: str, new_sequence: str, shot_tracking_file: str) -> None:
    """
    Recursively rename any files and subfolders inside `shot_root` whose
    names contain `old_shot_name` (or `<old_sequence>_` prefix) so they
    match `new_shot_name`, and update JSON tracking metadata inside the shot.
    """
    if old_shot_name != new_shot_name:
        for root, dirnames, filenames in os.walk(shot_root, topdown=False):
            root_path = Path(root)
            for fname in filenames:
                if old_shot_name in fname:
                    new_fname = fname.replace(old_shot_name, new_shot_name)
                    src_f = root_path / fname
                    dst_f = root_path / new_fname
                    if not dst_f.exists():
                        src_f.rename(dst_f)
            for dname in dirnames:
                if old_shot_name in dname:
                    new_dname = dname.replace(old_shot_name, new_shot_name)
                    src_d = root_path / dname
                    dst_d = root_path / new_dname
                    if not dst_d.exists():
                        src_d.rename(dst_d)

    # Update JSON metadata inside the moved shot folder
    for json_path in shot_root.rglob("*.json"):
        try:
            data = read_json(json_path)
        except Exception:
            continue
        updated = _replace_in_json_value(data, old_shot_name, new_shot_name, old_sequence, new_sequence)
        if json_path.name == shot_tracking_file and isinstance(updated, dict):
            updated["parent_sequence"] = new_sequence
        write_json(json_path, updated)


def move_shot(project_root: str | Path, source_sequence: str, target_sequence: str,
              shot_name: str, schema: dict[str, Any]) -> Path:
    """
    Move a shot from `source_sequence` to `target_sequence` (creating
    `target_sequence` if it does not exist yet), renaming the shot folder
    and all nested files/folders from `<source_sequence>_<shot>` to
    `<target_sequence>_<shot>`.

    Returns the Path to the moved and renamed shot folder.
    """
    project_root = Path(project_root)
    src_seq = sanitize_name(source_sequence)
    dst_seq = sanitize_name(target_sequence)
    if src_seq == dst_seq:
        raise ValueError("Source and target sequences must be different.")

    seq_def = schema["sequences"]
    shot_def = seq_def["shots"]

    src_seq_root = project_root / seq_def["dir_name"] / src_seq
    if not src_seq_root.exists():
        raise FileNotFoundError(f"Source sequence does not exist: {src_seq_root}")

    src_shot_root = _resolve_existing_shot_root(src_seq_root, src_seq, shot_name, shot_def["dir_name"])
    old_shot_name = src_shot_root.name
    new_shot_name = rename_shot_for_sequence(old_shot_name, src_seq, dst_seq)

    dst_seq_root = project_root / seq_def["dir_name"] / dst_seq
    if not dst_seq_root.exists():
        create_sequence(project_root, dst_seq, schema)

    dst_shot_root = dst_seq_root / shot_def["dir_name"] / new_shot_name
    if dst_shot_root.exists():
        raise FileExistsError(f"Target shot already exists: {dst_shot_root}")

    shutil.move(str(src_shot_root), str(dst_shot_root))
    _rename_shot_contents(
        dst_shot_root, old_shot_name, new_shot_name,
        src_seq, dst_seq, shot_def["tracking_file"],
    )

    _unregister_shot_from_sequence(src_seq_root, seq_def["tracking_file"], old_shot_name)
    _register_shot_with_sequence(dst_seq_root, seq_def["tracking_file"], new_shot_name)

    return dst_shot_root


def move_shots(project_root: str | Path, source_sequence: str, target_sequence: str,
               shot_names: list[str], schema: dict[str, Any]) -> list[Path]:
    """Move multiple shots from `source_sequence` to `target_sequence`."""
    moved: list[Path] = []
    for shot_name in shot_names:
        moved.append(move_shot(project_root, source_sequence, target_sequence, shot_name, schema))
    return moved


def delete_sequence(project_root: str | Path, sequence_name: str,
                    schema: dict[str, Any],
                    shots_to_move: list[str] | None = None,
                    target_sequence: str | None = None) -> list[Path]:
    """
    Delete a sequence folder (and any remaining shots inside it).
    If `shots_to_move` and `target_sequence` are provided, moves those
    shots to `target_sequence` (creating it if needed) before deleting
    `sequence_name`.

    Returns the list of moved shot Paths.
    """
    project_root = Path(project_root)
    seq_name = sanitize_name(sequence_name)
    seq_def = schema["sequences"]
    seq_root = project_root / seq_def["dir_name"] / seq_name
    if not seq_root.exists():
        raise FileNotFoundError(f"Sequence does not exist: {seq_root}")

    moved_paths: list[Path] = []
    if shots_to_move:
        if not target_sequence:
            raise ValueError("target_sequence is required when shots_to_move is non-empty.")
        moved_paths = move_shots(project_root, seq_name, target_sequence, shots_to_move, schema)

    shutil.rmtree(seq_root)
    return moved_paths


def _register_shot_with_sequence(seq_root: Path, seq_tracking_file: str, shot_name: str) -> None:
    tracking_path = seq_root / seq_tracking_file
    if not tracking_path.exists():
        return
    data = read_json(tracking_path)
    shots = data.setdefault("shots", [])
    if shot_name not in shots:
        shots.append(shot_name)
        write_json(tracking_path, data)


def _unregister_shot_from_sequence(seq_root: Path, seq_tracking_file: str, shot_name: str) -> None:
    tracking_path = seq_root / seq_tracking_file
    if not tracking_path.exists():
        return
    data = read_json(tracking_path)
    shots = data.get("shots", [])
    if shot_name in shots:
        shots.remove(shot_name)
        data["shots"] = shots
        write_json(tracking_path, data)
