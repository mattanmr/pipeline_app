"""
gui/views.py

One class per screen (a ttk.Frame), plus AppContext -- the small
piece of shared state (workspace root, schema, current
project/sequence/shot selection) every screen reads and writes so
that picking a shot in one tab is still the selected shot when you
switch to another tab.

Each view calls straight into core/manager.py and core/versioning.py,
the same functions main.py's CLI uses -- the GUI holds no pipeline
logic of its own, same as the CLI.
"""

from __future__ import annotations

import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from core import manager, versioning
from utils.metadata import read_json, make_source_ref
from utils.naming import sanitize_filename

from gui.components import (
    LabeledEntry, PathPicker, StatusBar, AIMetadataFrame, RefreshableCombobox,
)


class AppContext:
    """Shared state + disk-scanning helpers used by every view."""

    def __init__(self, schema: dict, workspace_root: Path):
        self.schema = schema
        self.workspace_root = Path(workspace_root)
        self.current_project: str | None = None
        self.current_sequence: str | None = None
        self.current_shot: str | None = None
        # Fired whenever project/sequence/shot selection changes, so
        # other tabs can refresh their dropdowns without polling.
        self.on_selection_changed: list = []

    def notify_selection_changed(self):
        for cb in self.on_selection_changed:
            cb()

    # -- scanning -----------------------------------------------------

    def list_projects(self) -> list[str]:
        if not self.workspace_root.exists():
            return []
        info_file = self.schema["project_info_file"]
        return sorted(
            p.name for p in self.workspace_root.iterdir()
            if p.is_dir() and (p / info_file).exists()
        )

    def project_root(self, project_name: str | None = None) -> Path:
        name = project_name or self.current_project
        return self.workspace_root / name

    def list_sequences(self, project_name: str | None = None) -> list[str]:
        root = self.project_root(project_name) / self.schema["sequences"]["dir_name"]
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir())

    def sequence_root(self, sequence_name: str | None = None, project_name: str | None = None) -> Path:
        seq = sequence_name or self.current_sequence
        return self.project_root(project_name) / self.schema["sequences"]["dir_name"] / seq

    def list_shots(self, sequence_name: str | None = None, project_name: str | None = None) -> list[str]:
        shots_dir = self.sequence_root(sequence_name, project_name) / self.schema["sequences"]["shots"]["dir_name"]
        if not shots_dir.exists():
            return []
        return sorted(p.name for p in shots_dir.iterdir() if p.is_dir())

    def shot_root(self, shot_name: str | None = None, sequence_name: str | None = None,
                  project_name: str | None = None) -> Path:
        shot = shot_name or self.current_shot
        shot_def = self.schema["sequences"]["shots"]
        return self.sequence_root(sequence_name, project_name) / shot_def["dir_name"] / shot

    def shot_category_names(self) -> list[str]:
        shot_def = self.schema["sequences"]["shots"]
        names = list(shot_def["categories"].keys())
        ai_def = shot_def["ai_generated"]
        for subtype in ai_def["subtypes"]:
            names.append(f"{ai_def['dir_name']}/{subtype}")
        return names

    def category_path_and_tracking(self, category: str) -> tuple[Path, str]:
        """
        Resolve a category name (e.g. "Animation" or "AI_Generated/Video")
        against the current shot into (folder_path, tracking_filename).
        """
        shot_def = self.schema["sequences"]["shots"]
        shot_root = self.shot_root()
        if category in shot_def["categories"]:
            return shot_root / category, shot_def["categories"][category]["tracking_file"]
        ai_def = shot_def["ai_generated"]
        _, subtype = category.split("/", 1)
        return (shot_root / ai_def["dir_name"] / subtype,
                ai_def["subtypes"][subtype]["tracking_file"])

    def list_versions(self, category: str) -> list[str]:
        cat_path, tracking_file = self.category_path_and_tracking(category)
        tracking_path = cat_path / tracking_file
        if not tracking_path.exists():
            return []
        data = read_json(tracking_path)
        return [v["version"] for v in data.get("versions", [])]

    def project_level_category_path_and_tracking(self, category: str) -> tuple[Path, str]:
        cat_def = self.schema["project_level_categories"][category]
        return self.project_root() / category, cat_def["tracking_file"]


class ProjectPanel(ttk.Frame):
    """Workspace root, existing-project list, and project creation."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx

        ttk.Label(self, text="Workspace root:", font=("", 10, "bold")).pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(2, 10))
        self.root_picker = PathPicker(row, "", mode="folder", width=50)
        self.root_picker.var.set(str(ctx.workspace_root))
        self.root_picker.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Use this root", command=self._use_root).pack(side="left", padx=(6, 0))

        ttk.Label(self, text="Existing projects:", font=("", 10, "bold")).pack(anchor="w", pady=(6, 2))
        list_row = ttk.Frame(self)
        list_row.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_row, height=8, exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        ttk.Button(list_row, text="⟳ Refresh", command=self.refresh).pack(side="left", padx=6, anchor="n")

        ttk.Separator(self).pack(fill="x", pady=10)

        ttk.Label(self, text="Create new project:", font=("", 10, "bold")).pack(anchor="w")
        self.name_entry = LabeledEntry(self, "Project name:")
        self.name_entry.pack(fill="x", pady=3)
        self.prod_folder_entry = LabeledEntry(self, "Production folder (optional link):")
        self.prod_folder_entry.pack(fill="x", pady=3)
        ttk.Button(self, text="Create Project", command=self._create_project).pack(anchor="w", pady=(6, 0))

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

        self.refresh()

    def _use_root(self):
        path = self.root_picker.get()
        if not path:
            return
        self.ctx.workspace_root = Path(path)
        self.refresh()
        self.status.ok(f"Workspace root set to {path}")

    def refresh(self):
        self.listbox.delete(0, tk.END)
        for name in self.ctx.list_projects():
            self.listbox.insert(tk.END, name)

    def _on_select(self, _event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.ctx.current_project = self.listbox.get(sel[0])
        self.ctx.current_sequence = None
        self.ctx.current_shot = None
        self.ctx.notify_selection_changed()
        self.status.ok(f"Selected project: {self.ctx.current_project}")

    def _create_project(self):
        name = self.name_entry.get()
        if not name:
            self.status.error("Project name is required.")
            return
        try:
            manager.create_project(
                self.ctx.workspace_root, name, self.ctx.schema,
                production_folder_target=self.prod_folder_entry.get() or None,
            )
        except FileExistsError:
            self.status.error(f"A project named '{name}' already exists.")
            return
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            self.status.error(str(exc))
            return
        self.name_entry.clear()
        self.prod_folder_entry.clear()
        self.refresh()
        self.status.ok(f"Created project '{name}'.")


class SequenceShotPanel(ttk.Frame):
    """Sequence + shot listing/creation for the currently selected project."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_project_changed)

        self.project_label = ttk.Label(self, text="No project selected", font=("", 10, "bold"))
        self.project_label.pack(anchor="w", pady=(0, 8))

        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True)

        seq_col = ttk.Frame(columns)
        seq_col.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(seq_col, text="Sequences:").pack(anchor="w")
        self.seq_listbox = tk.Listbox(seq_col, height=8, exportselection=False)
        self.seq_listbox.pack(fill="both", expand=True)
        self.seq_listbox.bind("<<ListboxSelect>>", self._on_select_sequence)
        seq_new_row = ttk.Frame(seq_col)
        seq_new_row.pack(fill="x", pady=4)
        self.seq_name_entry = LabeledEntry(seq_new_row, "New:")
        self.seq_name_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(seq_new_row, text="Create", command=self._create_sequence).pack(side="left", padx=4)

        shot_col = ttk.Frame(columns)
        shot_col.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(shot_col, text="Shots:").pack(anchor="w")
        self.shot_listbox = tk.Listbox(shot_col, height=8, exportselection=False)
        self.shot_listbox.pack(fill="both", expand=True)
        self.shot_listbox.bind("<<ListboxSelect>>", self._on_select_shot)
        shot_new_row = ttk.Frame(shot_col)
        shot_new_row.pack(fill="x", pady=4)
        self.shot_name_entry = LabeledEntry(shot_new_row, "New:")
        self.shot_name_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(shot_new_row, text="Create", command=self._create_shot).pack(side="left", padx=4)

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_project_changed(self):
        self.project_label.configure(
            text=f"Project: {self.ctx.current_project}" if self.ctx.current_project else "No project selected"
        )
        self._refresh_sequences()
        self.shot_listbox.delete(0, tk.END)

    def _refresh_sequences(self):
        self.seq_listbox.delete(0, tk.END)
        if not self.ctx.current_project:
            return
        for name in self.ctx.list_sequences():
            self.seq_listbox.insert(tk.END, name)

    def _refresh_shots(self):
        self.shot_listbox.delete(0, tk.END)
        if not self.ctx.current_project or not self.ctx.current_sequence:
            return
        for name in self.ctx.list_shots():
            self.shot_listbox.insert(tk.END, name)

    def _on_select_sequence(self, _event=None):
        sel = self.seq_listbox.curselection()
        if not sel:
            return
        self.ctx.current_sequence = self.seq_listbox.get(sel[0])
        self.ctx.current_shot = None
        self._refresh_shots()
        self.ctx.notify_selection_changed()
        self.status.ok(f"Selected sequence: {self.ctx.current_sequence}")

    def _on_select_shot(self, _event=None):
        sel = self.shot_listbox.curselection()
        if not sel:
            return
        self.ctx.current_shot = self.shot_listbox.get(sel[0])
        self.ctx.notify_selection_changed()
        self.status.ok(f"Selected shot: {self.ctx.current_shot}")

    def _create_sequence(self):
        if not self.ctx.current_project:
            self.status.error("Select a project first.")
            return
        name = self.seq_name_entry.get()
        if not name:
            self.status.error("Sequence name is required.")
            return
        try:
            manager.create_sequence(self.ctx.project_root(), name, self.ctx.schema)
        except FileExistsError:
            self.status.error(f"Sequence '{name}' already exists.")
            return
        except Exception as exc:  # noqa: BLE001
            self.status.error(str(exc))
            return
        self.seq_name_entry.clear()
        self._refresh_sequences()
        self.status.ok(f"Created sequence '{name}'.")

    def _create_shot(self):
        if not self.ctx.current_sequence:
            self.status.error("Select a sequence first.")
            return
        name = self.shot_name_entry.get()
        if not name:
            self.status.error("Shot name is required.")
            return
        try:
            manager.create_shot(self.ctx.project_root(), self.ctx.current_sequence, name, self.ctx.schema)
        except FileExistsError:
            self.status.error(f"Shot '{name}' already exists.")
            return
        except Exception as exc:  # noqa: BLE001
            self.status.error(str(exc))
            return
        self.shot_name_entry.clear()
        self._refresh_shots()
        self.status.ok(f"Created shot '{name}'.")


class PublishPanel(ttk.Frame):
    """Publish a new version into a shot category, with AI metadata when relevant."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_selection_changed)

        self.context_label = ttk.Label(self, text="No shot selected", font=("", 10, "bold"))
        self.context_label.pack(anchor="w", pady=(0, 8))

        self.category_combo = RefreshableCombobox(self, "Category:", on_refresh=self._refresh_categories)
        self.category_combo.pack(anchor="w", pady=4)
        self.category_combo.bind_select(self._on_category_changed)

        self.source_picker = PathPicker(self, "Source (file or folder):", mode="any", width=45)
        self.source_picker.pack(fill="x", pady=6)

        self.ai_frame = AIMetadataFrame(self)
        # Packed/unpacked dynamically depending on the selected category.

        ttk.Button(self, text="Publish", command=self._publish).pack(anchor="w", pady=(8, 0))

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_selection_changed(self):
        if self.ctx.current_shot:
            self.context_label.configure(
                text=f"Publishing into: {self.ctx.current_project} / "
                     f"{self.ctx.current_sequence} / {self.ctx.current_shot}"
            )
        else:
            self.context_label.configure(text="No shot selected")
        self._refresh_categories()

    def _refresh_categories(self):
        names = self.ctx.shot_category_names() if self.ctx.current_shot else []
        self.category_combo.set_values(names)
        self._on_category_changed()

    def _on_category_changed(self, _event=None):
        category = self.category_combo.get()
        is_ai = category.startswith("AI_Generated/")
        if is_ai:
            self.ai_frame.pack(fill="x", pady=6)
            self.ai_frame.show_source_field(category.endswith("/Video"))
        else:
            self.ai_frame.pack_forget()

    def _publish(self):
        if not self.ctx.current_shot:
            self.status.error("Select a project, sequence, and shot first.")
            return
        category = self.category_combo.get()
        if not category:
            self.status.error("Select a category.")
            return
        source = self.source_picker.get()
        if not source or not Path(source).exists():
            self.status.error("Choose a valid source file or folder.")
            return

        extra_fields = {}
        if category.startswith("AI_Generated/"):
            model = self.ai_frame.get_model()
            prompt = self.ai_frame.get_prompt()
            if model:
                extra_fields["model"] = model
            if prompt:
                extra_fields["prompt"] = prompt
            if category.endswith("/Video"):
                pairs = self.ai_frame.get_source_pairs()
                try:
                    extra_fields["source"] = [make_source_ref(*p.split(":", 1)) for p in pairs]
                except ValueError:
                    self.status.error("Source(s) must look like Category:version, e.g. Footage:v002.")
                    return

        cat_path, tracking_file = self.ctx.category_path_and_tracking(category)
        try:
            version = versioning.publish(
                cat_path, source, tracking_file,
                version_format=self.ctx.schema["version_format"],
                extra_fields=extra_fields or None,
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Publish failed: {exc}")
            return

        self.source_picker.clear()
        self.ai_frame.clear()
        self.status.ok(f"Published {category} -> {version}")


class CutPanel(ttk.Frame):
    """Compose an explicit shot cut from published category versions."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_selection_changed)

        self.context_label = ttk.Label(self, text="No shot selected", font=("", 10, "bold"))
        self.context_label.pack(anchor="w", pady=(0, 8))

        ttk.Label(self, text="Available category versions "
                              "(select one or more to compose the cut):").pack(anchor="w")
        list_row = ttk.Frame(self)
        list_row.pack(fill="both", expand=True, pady=4)
        self.avail_listbox = tk.Listbox(list_row, height=10, selectmode="extended", exportselection=False)
        self.avail_listbox.pack(side="left", fill="both", expand=True)
        ttk.Button(list_row, text="⟳ Refresh", command=self.refresh).pack(side="left", padx=6, anchor="n")

        ttk.Button(self, text="Record Cut From Selected", command=self._record_cut).pack(anchor="w", pady=(6, 10))

        ttk.Label(self, text="Existing cuts for this shot:").pack(anchor="w")
        self.cuts_listbox = tk.Listbox(self, height=5)
        self.cuts_listbox.pack(fill="both", expand=True, pady=4)

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_selection_changed(self):
        if self.ctx.current_shot:
            self.context_label.configure(
                text=f"Shot: {self.ctx.current_project} / {self.ctx.current_sequence} / {self.ctx.current_shot}"
            )
        else:
            self.context_label.configure(text="No shot selected")
        self.refresh()

    def refresh(self):
        self.avail_listbox.delete(0, tk.END)
        self.cuts_listbox.delete(0, tk.END)
        if not self.ctx.current_shot:
            return
        for category in self.ctx.shot_category_names():
            for version in self.ctx.list_versions(category):
                self.avail_listbox.insert(tk.END, f"{category}:{version}")

        shot_def = self.ctx.schema["sequences"]["shots"]
        tracking_path = self.ctx.shot_root() / shot_def["tracking_file"]
        if tracking_path.exists():
            data = read_json(tracking_path)
            current_master = data.get("current_cut_master")
            for cut in data.get("cuts", []):
                marker = "  ← current master" if cut["version"] == current_master else ""
                sources = ", ".join(f"{s['category']}:{s['version']}" for s in cut["sources"])
                self.cuts_listbox.insert(tk.END, f"{cut['version']}  [{sources}]{marker}")

    def _record_cut(self):
        if not self.ctx.current_shot:
            self.status.error("Select a project, sequence, and shot first.")
            return
        sel = self.avail_listbox.curselection()
        if not sel:
            self.status.error("Select at least one category:version to compose the cut from.")
            return
        sources = []
        for i in sel:
            category, version = self.avail_listbox.get(i).split(":", 1)
            sources.append(make_source_ref(category, version))

        shot_def = self.ctx.schema["sequences"]["shots"]
        try:
            version = versioning.record_cut(
                self.ctx.shot_root(), shot_def["tracking_file"], sources,
                versions_key="cuts", master_key="current_cut_master",
                cut_versions_dir=shot_def["cut_versions_dir"],
                cut_master_dir=shot_def["cut_master_dir"],
                version_format=self.ctx.schema["version_format"],
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Record cut failed: {exc}")
            return

        self.refresh()
        self.status.ok(f"Recorded shot cut -> {version}")


class IngestPanel(ttk.Frame):
    """
    Phase 4: bring in a client-supplied file, publish it as a new
    Client_Materials version at the project level (filename auto-
    sanitized), then optionally record which shot used it.
    """

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_selection_changed)

        self.context_label = ttk.Label(self, text="No project selected", font=("", 10, "bold"))
        self.context_label.pack(anchor="w", pady=(0, 8))

        self.source_picker = PathPicker(self, "Client material (file or folder):", mode="any", width=45)
        self.source_picker.pack(fill="x", pady=6)
        self.source_picker.var.trace_add("write", self._update_preview)
        self.preview_label = ttk.Label(self, text="", foreground="#555555")
        self.preview_label.pack(anchor="w")

        ttk.Button(self, text="Publish to Client_Materials", command=self._publish).pack(anchor="w", pady=8)

        ttk.Separator(self).pack(fill="x", pady=8)

        ttk.Label(self, text="Record usage on the currently selected shot "
                              "(optional):", font=("", 9, "bold")).pack(anchor="w")
        self.version_combo = RefreshableCombobox(self, "Client_Materials version:",
                                                   on_refresh=self._refresh_versions)
        self.version_combo.pack(anchor="w", pady=4)
        ttk.Button(self, text="Record Usage on Selected Shot", command=self._record_usage).pack(anchor="w", pady=4)

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_selection_changed(self):
        if self.ctx.current_project:
            self.context_label.configure(text=f"Project: {self.ctx.current_project}")
        else:
            self.context_label.configure(text="No project selected")
        self._refresh_versions()

    def _update_preview(self, *_args):
        source = self.source_picker.get()
        if source and Path(source).is_file():
            self.preview_label.configure(text=f"Will be stored as: {sanitize_filename(Path(source).name)}")
        elif source:
            self.preview_label.configure(text=f"Folder will be copied as-is: {Path(source).name}")
        else:
            self.preview_label.configure(text="")

    def _refresh_versions(self):
        if not self.ctx.current_project:
            self.version_combo.set_values([])
            return
        _, tracking_file = self.ctx.project_level_category_path_and_tracking("Client_Materials")
        tracking_path = self.ctx.project_root() / "Client_Materials" / tracking_file
        versions = []
        if tracking_path.exists():
            data = read_json(tracking_path)
            versions = [v["version"] for v in data.get("versions", [])]
        self.version_combo.set_values(versions)

    def _publish(self):
        if not self.ctx.current_project:
            self.status.error("Select a project first.")
            return
        source = self.source_picker.get()
        if not source or not Path(source).exists():
            self.status.error("Choose a valid client material file or folder.")
            return

        cat_path, tracking_file = self.ctx.project_level_category_path_and_tracking("Client_Materials")
        try:
            version = versioning.publish(
                cat_path, source, tracking_file,
                version_format=self.ctx.schema["version_format"],
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Publish failed: {exc}")
            return

        self.source_picker.clear()
        self._refresh_versions()
        self.status.ok(f"Published Client_Materials -> {version}")

    def _record_usage(self):
        if not self.ctx.current_shot:
            self.status.error("Select a project, sequence, and shot on the Sequences & Shots tab first.")
            return
        version = self.version_combo.get()
        if not version:
            self.status.error("Select (or publish) a Client_Materials version first.")
            return

        shot_def = self.ctx.schema["sequences"]["shots"]
        try:
            versioning.record_client_material_usage(
                self.ctx.shot_root(), shot_def["client_material_usage_file"], version,
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Record usage failed: {exc}")
            return

        self.status.ok(f"Recorded use of Client_Materials {version} on {self.ctx.current_shot}")


class TreePanel(ttk.Frame):
    """Read-only folder-tree view of the currently selected project."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self.refresh)

        top = ttk.Frame(self)
        top.pack(fill="x")
        self.context_label = ttk.Label(top, text="No project selected", font=("", 10, "bold"))
        self.context_label.pack(side="left")
        ttk.Button(top, text="⟳ Refresh", command=self.refresh).pack(side="right")

        text_frame = ttk.Frame(self)
        text_frame.pack(fill="both", expand=True, pady=8)
        self.text = tk.Text(text_frame, wrap="none", font=("Courier New", 10))
        vsb = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        hsb = ttk.Scrollbar(text_frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set, state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

    def refresh(self):
        self.context_label.configure(
            text=f"Project: {self.ctx.current_project}" if self.ctx.current_project else "No project selected"
        )
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        if self.ctx.current_project:
            lines = []
            _walk_tree(self.ctx.project_root(), "", lines)
            self.text.insert("1.0", "\n".join(lines))
        self.text.configure(state="disabled")


def _walk_tree(path: Path, prefix: str, lines: list[str]) -> None:
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            _walk_tree(entry, prefix + extension, lines)
