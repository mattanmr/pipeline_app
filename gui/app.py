"""
gui/app.py

Phase 3 GUI entry point. Loads config/settings.json and
config/pipeline_schema.json, builds a shared AppContext, and lays
out every screen from views.py as a tab in a ttk.Notebook.
Persists settings (such as workspace_root) back to config/settings.json
when changed and on window close.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import manager  # noqa: E402
from gui.views import (  # noqa: E402
    AppContext, ProjectPanel, SequenceShotPanel, PublishPanel,
    CutPanel, IngestPanel, TreePanel,
)
from utils.metadata import write_json  # noqa: E402

DEFAULT_SETTINGS_PATH = _PROJECT_ROOT / "config" / "settings.json"


def _load_settings(settings_path: Path = DEFAULT_SETTINGS_PATH) -> dict:
    if not settings_path.exists():
        return {
            "local_workspace": str(_PROJECT_ROOT / "workspace"),
            "workspace_root": str(_PROJECT_ROOT / "workspace"),
            "schema_path": "config/pipeline_schema.json",
            "max_publish_size_gb": 0,
        }
    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_settings(settings: dict, settings_path: Path = DEFAULT_SETTINGS_PATH) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(settings_path, settings)


def _resolve_workspace_root(settings: dict) -> Path:
    raw = (
        settings.get("workspace_root")
        or settings.get("default_workspace_root")
        or settings.get("local_workspace")
        or "workspace"
    )
    path = Path(raw)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path


class PipelineApp(tk.Tk):
    def __init__(self, settings_path: Path = DEFAULT_SETTINGS_PATH):
        super().__init__()
        self.title("Pipeline Manager")
        self.geometry("900x660")
        self.minsize(740, 540)

        self.settings_path = Path(settings_path)
        self.settings = _load_settings(self.settings_path)
        schema_rel = self.settings.get("schema_path", "config/pipeline_schema.json")
        schema_path = Path(schema_rel) if Path(schema_rel).is_absolute() else (_PROJECT_ROOT / schema_rel)
        schema = manager.load_schema(schema_path)

        workspace_root = _resolve_workspace_root(self.settings)

        self.ctx = AppContext(
            schema=schema,
            workspace_root=workspace_root,
            on_workspace_root_changed=self.save_settings,
        )

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tabs = {
            "Projects": ProjectPanel(notebook, self.ctx),
            "Sequences & Shots": SequenceShotPanel(notebook, self.ctx),
            "Publish": PublishPanel(notebook, self.ctx),
            "Record Cut": CutPanel(notebook, self.ctx),
            "Ingest Client Material": IngestPanel(notebook, self.ctx),
            "Tree View": TreePanel(notebook, self.ctx),
        }
        for label, frame in self.tabs.items():
            notebook.add(frame, text=label)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def save_settings(self) -> None:
        root_str = str(self.ctx.workspace_root)
        self.settings["workspace_root"] = root_str
        self.settings["local_workspace"] = root_str
        _save_settings(self.settings, self.settings_path)

    def _on_close(self) -> None:
        project_panel = self.tabs.get("Projects")
        if project_panel is not None:
            typed_root = project_panel.root_picker.get()
            if typed_root:
                self.ctx.workspace_root = Path(typed_root)
        self.save_settings()
        self.destroy()


def main():
    app = PipelineApp()
    app.mainloop()


if __name__ == "__main__":
    main()
