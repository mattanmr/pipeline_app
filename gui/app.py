"""
gui/app.py

Phase 3 GUI entry point. Loads config/settings.json and
config/pipeline_schema.json, builds a shared AppContext, and lays
out every screen from views.py as a tab in a ttk.Notebook.

Run with:
    python -m gui.app
or via main.py's `gui` subcommand.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# Allow running this file directly (python gui/app.py) as well as as
# a module (python -m gui.app) by making sure the project root is on
# sys.path either way.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import manager  # noqa: E402
from gui.views import (  # noqa: E402
    AppContext, ProjectPanel, SequenceShotPanel, PublishPanel,
    CutPanel, IngestPanel, TreePanel,
)

DEFAULT_SETTINGS_PATH = _PROJECT_ROOT / "config" / "settings.json"


def _load_settings(settings_path: Path = DEFAULT_SETTINGS_PATH) -> dict:
    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)


class PipelineApp(tk.Tk):
    def __init__(self, settings_path: Path = DEFAULT_SETTINGS_PATH):
        super().__init__()
        self.title("Pipeline Manager")
        self.geometry("880x640")
        self.minsize(720, 520)

        settings = _load_settings(settings_path)
        schema_path = settings["schema_path"]
        if not Path(schema_path).is_absolute():
            schema_path = _PROJECT_ROOT / schema_path
        schema = manager.load_schema(schema_path)

        workspace_root = Path(settings.get("local_workspace") or ".")
        self.ctx = AppContext(schema=schema, workspace_root=workspace_root)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tabs = {
            "Projects": ProjectPanel(notebook, self.ctx),
            "Sequences && Shots": SequenceShotPanel(notebook, self.ctx),
            "Publish": PublishPanel(notebook, self.ctx),
            "Record Cut": CutPanel(notebook, self.ctx),
            "Ingest Client Material": IngestPanel(notebook, self.ctx),
            "Tree View": TreePanel(notebook, self.ctx),
        }
        for label, frame in self.tabs.items():
            notebook.add(frame, text=label)


def main():
    app = PipelineApp()
    app.mainloop()


if __name__ == "__main__":
    main()
