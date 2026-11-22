"""
main.py

CLI entry point. This is the thin layer Phase 1-2 are tested through
before the GUI (Phase 3) exists. Every subcommand maps directly onto
a function in core/manager.py or core/versioning.py – the CLI itself
holds no pipeline logic.

Examples:
    python main.py init-project "My Show" --root ./workspace
    python main.py create-sequence "My Show" 01 --root ./workspace
    python main.py create-shot "My Show" 01 001 --root ./workspace
    python main.py publish "My Show" 01 01_001 comp ./scratch/comp_v1 --root ./workspace
    python main.py record-shot-cut "My Show" 01 01_001 --root ./workspace \
        --source comp:v001 --source FX:v002 --source generated:v001
    python main.py tree "My Show" --root ./workspace
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core import manager, versioning
from utils.metadata import make_source_ref
from utils.naming import format_shot_name


def _load_settings(settings_path: str = "config/settings.json") -> dict:
    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_schema_from_settings(settings: dict) -> dict:
    return manager.load_schema(settings["schema_path"])


def _resolve_shot_root(seq_root: Path, sequence_name: str, shot_name: str, shot_def: dict) -> Path:
    shots_dir = seq_root / shot_def["dir_name"]
    direct = shots_dir / shot_name
    if direct.exists():
        return direct
    prefixed = shots_dir / format_shot_name(sequence_name, shot_name)
    return prefixed


def cmd_init_project(args):
    schema = manager.load_schema(args.schema)
    root = manager.create_project(
        args.root, args.project_name, schema,
        production_folder_target=args.production_folder,
    )
    print(f"Created project: {root}")


def cmd_create_sequence(args):
    schema = manager.load_schema(args.schema)
    project_root = Path(args.root) / args.project_name
    seq_root = manager.create_sequence(project_root, args.sequence_name, schema)
    print(f"Created sequence: {seq_root}")


def cmd_create_shot(args):
    schema = manager.load_schema(args.schema)
    project_root = Path(args.root) / args.project_name
    shot_root = manager.create_shot(project_root, args.sequence_name, args.shot_name, schema)
    print(f"Created shot: {shot_root}")


def cmd_publish(args):
    schema = manager.load_schema(args.schema)
    project_root = Path(args.root) / args.project_name
    seq_def = schema["sequences"]
    shot_def = seq_def["shots"]
    seq_root = project_root / seq_def["dir_name"] / args.sequence_name

    extra_fields = {}
    if args.category in seq_def.get("categories", {}):
        tracking_file = seq_def["categories"][args.category]["tracking_file"]
        category_path = seq_root / args.category
    else:
        shot_root = _resolve_shot_root(seq_root, args.sequence_name, args.shot_name, shot_def)
        if args.category in shot_def["categories"]:
            tracking_file = shot_def["categories"][args.category]["tracking_file"]
            category_path = shot_root / args.category
            if args.category == "generated":
                if args.model:
                    extra_fields["model"] = args.model
                if args.prompt:
                    extra_fields["prompt"] = args.prompt
                if args.ai_source:
                    extra_fields["source"] = [
                        make_source_ref(*pair.split(":", 1)) for pair in args.ai_source
                    ]
        else:
            ai_def = shot_def["ai_generated"]
            _, subtype = args.category.split("/", 1)
            tracking_file = ai_def["subtypes"][subtype]["tracking_file"]
            category_path = shot_root / ai_def["dir_name"] / subtype
            if args.model:
                extra_fields["model"] = args.model
            if args.prompt:
                extra_fields["prompt"] = args.prompt
            if args.ai_source:
                extra_fields["source"] = [
                    make_source_ref(*pair.split(":", 1)) for pair in args.ai_source
                ]

    version = versioning.publish(
        category_path, args.source_path, tracking_file,
        version_format=schema["version_format"],
        extra_fields=extra_fields or None,
    )
    print(f"Published {args.category} -> {version}")


def cmd_record_shot_cut(args):
    schema = manager.load_schema(args.schema)
    project_root = Path(args.root) / args.project_name
    seq_def = schema["sequences"]
    shot_def = seq_def["shots"]
    seq_root = project_root / seq_def["dir_name"] / args.sequence_name
    shot_root = _resolve_shot_root(seq_root, args.sequence_name, args.shot_name, shot_def)

    sources = [make_source_ref(*pair.split(":", 1)) for pair in args.source]
    version = versioning.record_cut(
        shot_root, shot_def["tracking_file"], sources,
        versions_key="cuts", master_key="current_cut_master",
        cut_versions_dir=shot_def["cut_versions_dir"],
        cut_master_dir=shot_def["cut_master_dir"],
        version_format=schema["version_format"],
    )
    print(f"Shot cut recorded -> {version}")


def cmd_tree(args):
    project_root = Path(args.root) / args.project_name
    if not project_root.exists():
        print(f"No such project: {project_root}", file=sys.stderr)
        sys.exit(1)
    _print_tree(project_root)


def cmd_gui(args):
    from gui.app import PipelineApp
    app = PipelineApp()
    app.mainloop()


def _print_tree(path: Path, prefix: str = ""):
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        print(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            _print_tree(entry, prefix + extension)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pipeline management CLI")
    p.add_argument("--schema", default="config/pipeline_schema.json")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init-project")
    sp.add_argument("project_name")
    sp.add_argument("--root", required=True)
    sp.add_argument("--production-folder", default=None)
    sp.set_defaults(func=cmd_init_project)

    sp = sub.add_parser("create-sequence")
    sp.add_argument("project_name")
    sp.add_argument("sequence_name")
    sp.add_argument("--root", required=True)
    sp.set_defaults(func=cmd_create_sequence)

    sp = sub.add_parser("create-shot")
    sp.add_argument("project_name")
    sp.add_argument("sequence_name")
    sp.add_argument("shot_name")
    sp.add_argument("--root", required=True)
    sp.set_defaults(func=cmd_create_shot)

    sp = sub.add_parser("publish")
    sp.add_argument("project_name")
    sp.add_argument("sequence_name")
    sp.add_argument("shot_name")
    sp.add_argument("category", help="e.g. comp, FX, generated, edit, sound, or AI_Generated/Video")
    sp.add_argument("source_path")
    sp.add_argument("--root", required=True)
    sp.add_argument("--model", default=None, help="AI model name (generated / AI_Generated only)")
    sp.add_argument("--prompt", default=None, help="AI prompt text (generated / AI_Generated only)")
    sp.add_argument("--ai-source", action="append", default=[],
                    help="Category:version this AI asset was generated from, "
                         "repeatable, e.g. --ai-source AI_Generated/Images:v003")
    sp.set_defaults(func=cmd_publish)

    sp = sub.add_parser("record-shot-cut")
    sp.add_argument("project_name")
    sp.add_argument("sequence_name")
    sp.add_argument("shot_name")
    sp.add_argument("--root", required=True)
    sp.add_argument("--source", action="append", required=True,
                    help="Category:version composing this cut, repeatable, "
                         "e.g. --source comp:v001 --source FX:v002")
    sp.set_defaults(func=cmd_record_shot_cut)

    sp = sub.add_parser("tree")
    sp.add_argument("project_name")
    sp.add_argument("--root", required=True)
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("gui")
    sp.set_defaults(func=cmd_gui)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
