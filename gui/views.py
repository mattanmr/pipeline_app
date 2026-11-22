"""
gui/views.py

The main GUI screens, implemented as Tkinter Frames.

Panels:
1. ProjectPanel      - create projects, set workspace root, open project/client folders
2. SequenceShotPanel - create, select, move, and delete sequences and shots
3. PublishPanel      - publish new versions to a shot or sequence category (with AI fields)
4. CutPanel          - record a shot cut from child versions
5. IngestPanel       - ingest multiple client files/folders into Client_Materials
6. TreePanel         - collapsible tree view (ttk.Treeview) of selected project
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Callable

from core import manager, versioning
from utils.metadata import read_json, make_source_ref

from gui.components import (
    LabeledEntry, PathPicker, MultiSourcePicker, StatusBar,
    AIMetadataFrame, RefreshableCombobox, MoveShotsDialog, DeleteSequenceDialog,
)


def open_folder_in_explorer(folder_path: Path) -> None:
    """Open `folder_path` in the native OS file manager."""
    folder_path = Path(folder_path).resolve()
    if not folder_path.exists():
        raise FileNotFoundError(f"Folder does not exist: {folder_path}")
    if sys.platform.startswith("win"):
        os.startfile(str(folder_path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder_path)])
    else:
        subprocess.Popen(["xdg-open", str(folder_path)])


class AppContext:
    """Shared state + disk-scanning helpers used by every view."""

    def __init__(self, schema: dict, workspace_root: Path,
                 on_workspace_root_changed: Callable[[], None] | None = None):
        self.schema = schema
        self.workspace_root = Path(workspace_root)
        self.on_workspace_root_changed = on_workspace_root_changed
        self.current_project: str | None = None
        self.current_sequence: str | None = None
        self.current_shot: str | None = None
        self.on_selection_changed: list = []

    def set_workspace_root(self, new_root: str | Path) -> None:
        self.workspace_root = Path(new_root)
        if self.on_workspace_root_changed is not None:
            self.on_workspace_root_changed()

    def notify_selection_changed(self):
        for cb in self.on_selection_changed:
            cb()

    # -- scanning ---------------------------------------------------

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

    def client_materials_root(self, project_name: str | None = None) -> Path:
        return self.project_root(project_name) / "Client_Materials"

    def list_sequences(self, project_name: str | None = None) -> list[str]:
        if not (project_name or self.current_project):
            return []
        root = self.project_root(project_name) / self.schema["sequences"]["dir_name"]
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir())

    def sequence_root(self, sequence_name: str | None = None, project_name: str | None = None) -> Path:
        seq = sequence_name or self.current_sequence
        return self.project_root(project_name) / self.schema["sequences"]["dir_name"] / seq

    def list_shots(self, sequence_name: str | None = None, project_name: str | None = None) -> list[str]:
        if not (project_name or self.current_project) or not (sequence_name or self.current_sequence):
            return []
        shots_dir = self.sequence_root(sequence_name, project_name) / self.schema["sequences"]["shots"]["dir_name"]
        if not shots_dir.exists():
            return []
        return sorted(p.name for p in shots_dir.iterdir() if p.is_dir())

    def shot_root(self, shot_name: str | None = None, sequence_name: str | None = None,
                  project_name: str | None = None) -> Path:
        shot = shot_name or self.current_shot
        shot_def = self.schema["sequences"]["shots"]
        return self.sequence_root(sequence_name, project_name) / shot_def["dir_name"] / shot

    def sequence_category_names(self) -> list[str]:
        seq_def = self.schema["sequences"]
        return list(seq_def.get("categories", {}).keys())

    def shot_category_names(self) -> list[str]:
        shot_def = self.schema["sequences"]["shots"]
        names = list(shot_def["categories"].keys())
        if "ai_generated" in shot_def:
            ai_def = shot_def["ai_generated"]
            for subtype in ai_def["subtypes"]:
                names.append(f"{ai_def['dir_name']}/{subtype}")
        return names

    def publishable_category_names(self) -> list[str]:
        names: list[str] = []
        if self.current_shot:
            names.extend(self.shot_category_names())
        if self.current_sequence:
            for seq_cat in self.sequence_category_names():
                label = f"Sequence/{seq_cat}" if self.current_shot else seq_cat
                names.append(label)
        return names

    def category_path_and_tracking(self, category: str) -> tuple[Path, str]:
        seq_def = self.schema["sequences"]
        seq_cats = seq_def.get("categories", {})

        if category.startswith("Sequence/"):
            seq_cat = category.split("/", 1)[1]
            return self.sequence_root() / seq_cat, seq_cats[seq_cat]["tracking_file"]
        if category in seq_cats and not self.current_shot:
            return self.sequence_root() / category, seq_cats[category]["tracking_file"]

        shot_def = seq_def["shots"]
        shot_root = self.shot_root()
        if category in shot_def["categories"]:
            return shot_root / category, shot_def["categories"][category]["tracking_file"]
        if category in seq_cats:
            return self.sequence_root() / category, seq_cats[category]["tracking_file"]

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
    """Workspace root, existing-project list, folder shortcuts, and project creation."""

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

        btn_col = ttk.Frame(list_row)
        btn_col.pack(side="left", padx=6, anchor="n")
        ttk.Button(btn_col, text="🔄 Refresh", command=self.refresh).pack(fill="x", pady=(0, 4))
        ttk.Button(btn_col, text="📂 Open Project Folder", command=self._open_project_folder).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="📂 Open Client Folder", command=self._open_client_folder).pack(fill="x", pady=2)

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
        self.ctx.set_workspace_root(path)
        self.ctx.current_project = None
        self.ctx.current_sequence = None
        self.ctx.current_shot = None
        self.refresh()
        self.ctx.notify_selection_changed()
        self.status.ok(f"Workspace root set and saved: {path}")

    def refresh(self):
        self.listbox.delete(0, tk.END)
        projects = self.ctx.list_projects()
        for idx, name in enumerate(projects):
            self.listbox.insert(tk.END, name)
            if name == self.ctx.current_project:
                self.listbox.selection_set(idx)

    def _on_select(self, _event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        selected = self.listbox.get(sel[0])
        if selected != self.ctx.current_project:
            self.ctx.current_project = selected
            self.ctx.current_sequence = None
            self.ctx.current_shot = None
            self.ctx.notify_selection_changed()
        self.status.ok(f"Selected project: {self.ctx.current_project}")

    def _open_project_folder(self):
        if not self.ctx.current_project:
            self.status.error("Select a project first.")
            return
        try:
            open_folder_in_explorer(self.ctx.project_root())
            self.status.ok(f"Opened project folder: {self.ctx.project_root()}")
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Could not open project folder: {exc}")

    def _open_client_folder(self):
        if not self.ctx.current_project:
            self.status.error("Select a project first.")
            return
        try:
            open_folder_in_explorer(self.ctx.client_materials_root())
            self.status.ok(f"Opened client folder: {self.ctx.client_materials_root()}")
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Could not open client folder: {exc}")

    def _create_project(self):
        name = self.name_entry.get()
        if not name:
            self.status.error("Project name is required.")
            return
        try:
            root = manager.create_project(
                self.ctx.workspace_root, name, self.ctx.schema,
                production_folder_target=self.prod_folder_entry.get() or None,
            )
        except FileExistsError:
            self.status.error(f"A project named '{name}' already exists.")
            return
        except Exception as exc:  # noqa: BLE001
            self.status.error(str(exc))
            return
        self.name_entry.clear()
        self.prod_folder_entry.clear()
        self.ctx.current_project = root.name
        self.ctx.current_sequence = None
        self.ctx.current_shot = None
        self.refresh()
        self.ctx.notify_selection_changed()
        self.status.ok(f"Created project '{root.name}'.")


class SequenceShotPanel(ttk.Frame):
    """Sequence + shot listing, creation, moving, and deletion for the selected project."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_selection_changed)

        self.project_label = ttk.Label(self, text="No project selected", font=("", 10, "bold"))
        self.project_label.pack(anchor="w", pady=(0, 8))

        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True)

        # Left column: Sequences
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

        seq_actions = ttk.Frame(seq_col)
        seq_actions.pack(fill="x", pady=(2, 0))
        ttk.Button(seq_actions, text="🗑️ Delete Sequence...", command=self._delete_sequence).pack(side="left")

        # Right column: Shots
        shot_col = ttk.Frame(columns)
        shot_col.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(shot_col, text="Shots (Ctrl/Shift-click for multi-select):").pack(anchor="w")
        self.shot_listbox = tk.Listbox(shot_col, height=8, selectmode="extended", exportselection=False)
        self.shot_listbox.pack(fill="both", expand=True)
        self.shot_listbox.bind("<<ListboxSelect>>", self._on_select_shot)

        shot_new_row = ttk.Frame(shot_col)
        shot_new_row.pack(fill="x", pady=4)
        self.shot_name_entry = LabeledEntry(shot_new_row, "New:")
        self.shot_name_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(shot_new_row, text="Create", command=self._create_shot).pack(side="left", padx=4)

        shot_actions = ttk.Frame(shot_col)
        shot_actions.pack(fill="x", pady=(2, 0))
        ttk.Button(shot_actions, text="⇄ Move Shot(s)...", command=self._move_shots).pack(side="left", padx=(0, 6))
        ttk.Button(shot_actions, text="🗑️ Delete Shot(s)", command=self._delete_shots).pack(side="left")

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_selection_changed(self):
        self.project_label.configure(
            text=f"Project: {self.ctx.current_project}" if self.ctx.current_project else "No project selected"
        )
        self._refresh_sequences()
        self._refresh_shots()

    def _refresh_sequences(self):
        self.seq_listbox.delete(0, tk.END)
        if not self.ctx.current_project:
            return
        sequences = self.ctx.list_sequences()
        for idx, name in enumerate(sequences):
            self.seq_listbox.insert(tk.END, name)
            if name == self.ctx.current_sequence:
                self.seq_listbox.selection_set(idx)

    def _refresh_shots(self):
        prev_selected = {self.shot_listbox.get(i) for i in self.shot_listbox.curselection()}
        self.shot_listbox.delete(0, tk.END)
        if not self.ctx.current_project or not self.ctx.current_sequence:
            return
        shots = self.ctx.list_shots()
        for idx, name in enumerate(shots):
            self.shot_listbox.insert(tk.END, name)
            if name == self.ctx.current_shot or name in prev_selected:
                self.shot_listbox.selection_set(idx)

    def _on_select_sequence(self, _event=None):
        sel = self.seq_listbox.curselection()
        if not sel:
            return
        selected = self.seq_listbox.get(sel[0])
        if selected != self.ctx.current_sequence:
            self.ctx.current_sequence = selected
            self.ctx.current_shot = None
            self.ctx.notify_selection_changed()
        else:
            self._refresh_shots()
        self.status.ok(f"Selected sequence: {self.ctx.current_sequence}")

    def _on_select_shot(self, _event=None):
        sel = self.shot_listbox.curselection()
        if not sel:
            return
        selected_shots = [self.shot_listbox.get(i) for i in sel]
        primary = selected_shots[0]
        if primary != self.ctx.current_shot:
            self.ctx.current_shot = primary
            self.ctx.notify_selection_changed()
        if len(selected_shots) == 1:
            self.status.ok(f"Selected shot: {primary}")
        else:
            self.status.ok(f"Selected {len(selected_shots)} shots (active: {primary})")

    def _create_sequence(self):
        if not self.ctx.current_project:
            self.status.error("Select a project first.")
            return
        name = self.seq_name_entry.get()
        if not name:
            self.status.error("Sequence name is required.")
            return
        try:
            seq_root = manager.create_sequence(self.ctx.project_root(), name, self.ctx.schema)
        except FileExistsError:
            self.status.error(f"Sequence '{name}' already exists.")
            return
        except Exception as exc:  # noqa: BLE001
            self.status.error(str(exc))
            return
        self.seq_name_entry.clear()
        self.ctx.current_sequence = seq_root.name
        self.ctx.current_shot = None
        self.ctx.notify_selection_changed()
        self.status.ok(f"Created sequence '{seq_root.name}'.")

    def _create_shot(self):
        if not self.ctx.current_sequence:
            self.status.error("Select a sequence first.")
            return
        name = self.shot_name_entry.get()
        if not name:
            self.status.error("Shot name is required.")
            return
        try:
            shot_root = manager.create_shot(
                self.ctx.project_root(), self.ctx.current_sequence, name, self.ctx.schema
            )
        except FileExistsError:
            self.status.error(f"Shot already exists in '{self.ctx.current_sequence}'.")
            return
        except Exception as exc:  # noqa: BLE001
            self.status.error(str(exc))
            return
        self.shot_name_entry.clear()
        self.ctx.current_shot = shot_root.name
        self.ctx.notify_selection_changed()
        self.status.ok(f"Created shot '{shot_root.name}'.")

    def _delete_shots(self):
        if not self.ctx.current_project or not self.ctx.current_sequence:
            self.status.error("Select a project and sequence first.")
            return
        sel = self.shot_listbox.curselection()
        if not sel:
            self.status.error("Select one or more shots to delete.")
            return
        shot_names = [self.shot_listbox.get(i) for i in sel]
        confirm = messagebox.askyesno(
            "Delete Shot(s)",
            f"Permanently delete {len(shot_names)} shot(s) from '{self.ctx.current_sequence}'?\n\n"
            + ", ".join(shot_names),
            parent=self,
        )
        if not confirm:
            return
        try:
            for s_name in shot_names:
                manager.delete_shot(
                    self.ctx.project_root(), self.ctx.current_sequence, s_name, self.ctx.schema
                )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Delete shot failed: {exc}")
            return
        self.ctx.current_shot = None
        self.ctx.notify_selection_changed()
        self.status.ok(f"Deleted {len(shot_names)} shot(s) from '{self.ctx.current_sequence}'.")

    def _move_shots(self):
        if not self.ctx.current_project or not self.ctx.current_sequence:
            self.status.error("Select a project and sequence first.")
            return
        all_shots = self.ctx.list_shots()
        if not all_shots:
            self.status.error(f"Sequence '{self.ctx.current_sequence}' has no shots to move.")
            return
        preselected = [self.shot_listbox.get(i) for i in self.shot_listbox.curselection()]
        if not preselected and self.ctx.current_shot:
            preselected = [self.ctx.current_shot]
        other_seqs = [s for s in self.ctx.list_sequences() if s != self.ctx.current_sequence]

        dlg = MoveShotsDialog(self, self.ctx.current_sequence, all_shots, preselected, other_seqs)
        self.wait_window(dlg)
        if not dlg.result:
            return
        shots_to_move, target_seq = dlg.result
        try:
            moved_paths = manager.move_shots(
                self.ctx.project_root(), self.ctx.current_sequence, target_seq,
                shots_to_move, self.ctx.schema,
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Move shot(s) failed: {exc}")
            return

        new_names = [p.name for p in moved_paths]
        self.ctx.current_sequence = moved_paths[0].parent.parent.name
        self.ctx.current_shot = new_names[0]
        self.ctx.notify_selection_changed()
        self.status.ok(
            f"Moved {len(new_names)} shot(s) to '{self.ctx.current_sequence}': {', '.join(new_names)}"
        )

    def _delete_sequence(self):
        if not self.ctx.current_project or not self.ctx.current_sequence:
            self.status.error("Select a sequence to delete first.")
            return
        seq_name = self.ctx.current_sequence
        shots = self.ctx.list_shots(seq_name)
        shots_to_move: list[str] = []
        target_seq: str | None = None

        if shots:
            other_seqs = [s for s in self.ctx.list_sequences() if s != seq_name]
            dlg = DeleteSequenceDialog(self, seq_name, shots, other_seqs)
            self.wait_window(dlg)
            confirmed, shots_to_move, target_seq = dlg.result
            if not confirmed:
                return
        else:
            confirm = messagebox.askyesno(
                "Delete Sequence",
                f"Permanently delete empty sequence '{seq_name}'?",
                parent=self,
            )
            if not confirm:
                return

        try:
            moved_paths = manager.delete_sequence(
                self.ctx.project_root(), seq_name, self.ctx.schema,
                shots_to_move=shots_to_move or None,
                target_sequence=target_seq,
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Delete sequence failed: {exc}")
            return

        if moved_paths:
            self.ctx.current_sequence = moved_paths[0].parent.parent.name
            self.ctx.current_shot = moved_paths[0].name
            msg = (
                f"Deleted sequence '{seq_name}' after moving {len(moved_paths)} shot(s) "
                f"to '{self.ctx.current_sequence}'."
            )
        else:
            self.ctx.current_sequence = None
            self.ctx.current_shot = None
            msg = f"Deleted sequence '{seq_name}'."

        self.ctx.notify_selection_changed()
        self.status.ok(msg)


class PublishPanel(ttk.Frame):
    """Publish a new version into a shot or sequence category, with AI metadata when relevant."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_selection_changed)

        self.context_label = ttk.Label(self, text="No sequence or shot selected", font=("", 10, "bold"))
        self.context_label.pack(anchor="w", pady=(0, 8))

        self.category_combo = RefreshableCombobox(self, "Category:", on_refresh=self._refresh_categories)
        self.category_combo.pack(anchor="w", pady=4)
        self.category_combo.bind_select(self._on_category_changed)

        self.source_picker = PathPicker(self, "Source (file or folder):", mode="any", width=45)
        self.source_picker.pack(fill="x", pady=6)

        self.ai_frame = AIMetadataFrame(self)

        ttk.Button(self, text="Publish", command=self._publish).pack(anchor="w", pady=(8, 0))

        self.status = StatusBar(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_selection_changed(self):
        if self.ctx.current_shot:
            self.context_label.configure(
                text=f"Publishing into: {self.ctx.current_project} / "
                     f"{self.ctx.current_sequence} / {self.ctx.current_shot}"
            )
        elif self.ctx.current_sequence:
            self.context_label.configure(
                text=f"Publishing into sequence: {self.ctx.current_project} / "
                     f"{self.ctx.current_sequence}"
            )
        else:
            self.context_label.configure(text="No sequence or shot selected")
        self._refresh_categories()

    def _refresh_categories(self):
        names = self.ctx.publishable_category_names()
        self.category_combo.set_values(names)
        self._on_category_changed()

    def _on_category_changed(self, _event=None):
        category = self.category_combo.get()
        is_ai = category == "generated" or category.startswith("AI_Generated/")
        if is_ai:
            self.ai_frame.pack(fill="x", pady=6)
            self.ai_frame.show_source_field(category == "generated" or category.endswith("/Video"))
        else:
            self.ai_frame.pack_forget()

    def _publish(self):
        if not self.ctx.current_sequence and not self.ctx.current_shot:
            self.status.error("Select a project and sequence (and shot for shot categories) first.")
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
        if category == "generated" or category.startswith("AI_Generated/"):
            model = self.ai_frame.get_model()
            prompt = self.ai_frame.get_prompt()
            if model:
                extra_fields["model"] = model
            if prompt:
                extra_fields["prompt"] = prompt
            if category == "generated" or category.endswith("/Video"):
                pairs = self.ai_frame.get_source_pairs()
                if pairs:
                    try:
                        extra_fields["source"] = [make_source_ref(*p.split(":", 1)) for p in pairs]
                    except ValueError:
                        self.status.error("Source(s) must look like Category:version, e.g. comp:v002.")
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
        ttk.Button(list_row, text="🔄 Refresh", command=self.refresh).pack(side="left", padx=6, anchor="n")

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
                marker = "  <- current master" if cut["version"] == current_master else ""
                sources = ", ".join(f"{s['category']}:{s['version']}" for s in cut["sources"])
                self.cuts_listbox.insert(tk.END, f"{cut['version']} [{sources}]{marker}")

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
    Phase 4: bring in one or more client-supplied files, folders, or a
    mix of both (Issue #7), publish them as a new Client_Materials
    version at the project level (names auto-sanitized), and optionally
    record which shot used it.
    """

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self._on_selection_changed)

        top_row = ttk.Frame(self)
        top_row.pack(fill="x", pady=(0, 8))
        self.context_label = ttk.Label(top_row, text="No project selected", font=("", 10, "bold"))
        self.context_label.pack(side="left")
        ttk.Button(top_row, text="📂 Open Client Folder", command=self._open_client_folder).pack(side="right")

        self.multi_picker = MultiSourcePicker(
            self, label="Client materials (add multiple files, folders, or a mix):"
        )
        self.multi_picker.pack(fill="both", expand=True, pady=6)

        ttk.Button(self, text="Publish to Client_Materials", command=self._publish).pack(anchor="w", pady=6)

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

    def _open_client_folder(self):
        if not self.ctx.current_project:
            self.status.error("Select a project first.")
            return
        try:
            open_folder_in_explorer(self.ctx.client_materials_root())
            self.status.ok(f"Opened client folder: {self.ctx.client_materials_root()}")
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Could not open client folder: {exc}")

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
        sources = self.multi_picker.get_sources()
        if not sources:
            self.status.error("Add at least one client file or folder to ingest.")
            return
        missing = [s for s in sources if not Path(s).exists()]
        if missing:
            self.status.error(f"Source does not exist: {missing[0]}")
            return

        cat_path, tracking_file = self.ctx.project_level_category_path_and_tracking("Client_Materials")
        try:
            version = versioning.publish_multiple(
                cat_path,
                sources,
                tracking_file,
                version_format=self.ctx.schema["version_format"],
                sanitize_names=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.status.error(f"Publish failed: {exc}")
            return

        count = len(sources)
        self.multi_picker.clear()
        self._refresh_versions()
        self.status.ok(f"Published {count} item(s) to Client_Materials -> {version}")

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
    """Compact collapsible folder-tree view (ttk.Treeview) of the currently selected project."""

    def __init__(self, parent, ctx: AppContext, **kwargs):
        super().__init__(parent, padding=12, **kwargs)
        self.ctx = ctx
        ctx.on_selection_changed.append(self.refresh)

        top = ttk.Frame(self)
        top.pack(fill="x")
        self.context_label = ttk.Label(top, text="No project selected", font=("", 10, "bold"))
        self.context_label.pack(side="left")

        btn_bar = ttk.Frame(top)
        btn_bar.pack(side="right")
        ttk.Button(btn_bar, text="Expand All", command=lambda: self._set_all_open(True)).pack(side="left", padx=2)
        ttk.Button(btn_bar, text="Collapse All", command=lambda: self._set_all_open(False)).pack(side="left", padx=2)
        ttk.Button(btn_bar, text="🔄 Refresh", command=self.refresh).pack(side="left", padx=(4, 0))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, pady=8)

        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

    def refresh(self):
        self.context_label.configure(
            text=f"Project: {self.ctx.current_project}" if self.ctx.current_project else "No project selected"
        )
        for item in self.tree.get_children():
            self.tree.delete(item)
        if self.ctx.current_project:
            proj_root = self.ctx.project_root()
            if proj_root.exists():
                root_id = self.tree.insert("", "end", text=f"📁 {proj_root.name}/", open=True)
                self._populate_tree(proj_root, root_id, depth=1)

    def _populate_tree(self, path: Path, parent_id: str, depth: int) -> None:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        seq_dir_name = self.ctx.schema["sequences"]["dir_name"]
        shots_dir_name = self.ctx.schema["sequences"]["shots"]["dir_name"]
        for entry in entries:
            if entry.is_dir():
                should_open = (
                    (depth == 1 and entry.name == seq_dir_name)
                    or (depth == 2 and path.name == seq_dir_name)
                    or (depth == 3 and entry.name == shots_dir_name)
                )
                node_id = self.tree.insert(
                    parent_id, "end", text=f"📁 {entry.name}/", open=should_open
                )
                self._populate_tree(entry, node_id, depth=depth + 1)
            else:
                self.tree.insert(parent_id, "end", text=f"📄 {entry.name}", open=False)

    def _set_all_open(self, is_open: bool, parent_id: str = "") -> None:
        for item_id in self.tree.get_children(parent_id):
            if parent_id == "" and not is_open:
                self.tree.item(item_id, open=True)
            else:
                self.tree.item(item_id, open=is_open)
            self._set_all_open(is_open, item_id)
