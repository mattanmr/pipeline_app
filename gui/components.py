"""
gui/components.py

Small reusable Tkinter widgets and modal dialogs shared across views.py.
Nothing here talks to core/ directly -- these are pure UI building
blocks that report user input back through callbacks/getters.
"""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from utils.naming import sanitize_filename, sanitize_name


class LabeledEntry(ttk.Frame):
    """A label + single-line entry, laid out in a grid row."""

    def __init__(self, parent, label: str, width: int = 32, **kwargs):
        super().__init__(parent, **kwargs)
        ttk.Label(self, text=label).pack(side="left", padx=(0, 8))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)

    def clear(self) -> None:
        self.var.set("")


class PathPicker(ttk.Frame):
    """A label + entry + Browse button, for picking a file or a folder."""

    def __init__(self, parent, label: str, mode: str = "file",
                 width: int = 40, **kwargs):
        super().__init__(parent, **kwargs)
        self.mode = mode
        ttk.Label(self, text=label).pack(side="left", padx=(0, 8))
        self.var = tk.StringVar()
        ttk.Entry(self, textvariable=self.var, width=width).pack(
            side="left", fill="x", expand=True, padx=(0, 6))

        if mode in ("file", "any"):
            ttk.Button(self, text="Browse File...", command=self._browse_file).pack(side="left", padx=2)
        if mode in ("folder", "any"):
            ttk.Button(self, text="Browse Folder...", command=self._browse_folder).pack(side="left", padx=2)

    def _browse_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.var.set(path)

    def _browse_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.var.set(path)

    def get(self) -> str:
        return self.var.get().strip()

    def clear(self) -> None:
        self.var.set("")


class MultiSourcePicker(ttk.Frame):
    """
    A multi-item source selector supporting multiple files, multiple
    folders, or a mix of both (Issue #7). Displays the queued items
    along with their sanitized destination names.
    """

    def __init__(self, parent, label: str = "Client materials (files and/or folders):", **kwargs):
        super().__init__(parent, **kwargs)
        self._sources: list[str] = []

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text=label).pack(side="left")

        btn_row = ttk.Frame(header)
        btn_row.pack(side="right")
        ttk.Button(btn_row, text="➕ Add Files...", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(btn_row, text="📁 Add Folder...", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(btn_row, text="➖ Remove Selected", command=self._remove_selected).pack(side="left", padx=2)
        ttk.Button(btn_row, text="✖ Clear All", command=self.clear).pack(side="left", padx=2)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_frame, height=6, selectmode="extended", exportselection=False)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vsb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

    def add_paths(self, paths: list[str | Path]) -> None:
        for raw in paths:
            p_str = str(Path(raw))
            if p_str and p_str not in self._sources:
                self._sources.append(p_str)
        self._refresh_listbox()

    def _add_files(self):
        paths = filedialog.askopenfilenames(title="Select one or more client files")
        if paths:
            self.add_paths(list(paths))

    def _add_folder(self):
        path = filedialog.askdirectory(title="Select a client folder to add")
        if path:
            self.add_paths([path])

    def _remove_selected(self):
        sel = sorted(self.listbox.curselection(), reverse=True)
        for idx in sel:
            if 0 <= idx < len(self._sources):
                self._sources.pop(idx)
        self._refresh_listbox()

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for src_str in self._sources:
            p = Path(src_str)
            kind = "Folder" if p.is_dir() else "File"
            try:
                stored = sanitize_name(p.name) if p.is_dir() else sanitize_filename(p.name)
            except ValueError:
                stored = p.name
            self.listbox.insert(tk.END, f"[{kind}] {src_str}  ->  {stored}")

    def get_sources(self) -> list[str]:
        return list(self._sources)

    def clear(self) -> None:
        self._sources.clear()
        self.listbox.delete(0, tk.END)


class StatusBar(ttk.Frame):
    """A single line at the bottom of a view for success/error feedback."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.var = tk.StringVar(value="")
        self.label = ttk.Label(self, textvariable=self.var, anchor="w")
        self.label.pack(fill="x")

    def ok(self, message: str) -> None:
        self.label.configure(foreground="#1a7a1a")
        self.var.set(message)

    def error(self, message: str) -> None:
        self.label.configure(foreground="#b0201a")
        self.var.set(message)

    def clear(self) -> None:
        self.var.set("")


class AIMetadataFrame(ttk.LabelFrame):
    """
    Model / Prompt fields, shown when the selected publish category is
    'generated', 'AI_Generated/Images', or 'AI_Generated/Video'.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, text="AI Generation Metadata", **kwargs)
        self.model = LabeledEntry(self, "Model:", width=30)
        self.model.pack(fill="x", padx=8, pady=4)
        self.prompt = LabeledEntry(self, "Prompt:", width=30)
        self.prompt.pack(fill="x", padx=8, pady=4)
        self.source = LabeledEntry(
            self, "Source(s) (Category:version, comma-separated):", width=30)
        self.source.pack(fill="x", padx=8, pady=4)
        self._source_row = self.source

    def show_source_field(self, visible: bool) -> None:
        if visible:
            self._source_row.pack(fill="x", padx=8, pady=4)
        else:
            self._source_row.pack_forget()

    def get_model(self) -> str:
        return self.model.get()

    def get_prompt(self) -> str:
        return self.prompt.get()

    def get_source_pairs(self) -> list[str]:
        raw = self.source.get()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    def clear(self) -> None:
        self.model.clear()
        self.prompt.clear()
        self.source.clear()


class RefreshableCombobox(ttk.Frame):
    """A labeled combobox with a small refresh button next to it."""

    def __init__(self, parent, label: str, on_refresh, width: int = 28, **kwargs):
        super().__init__(parent, **kwargs)
        ttk.Label(self, text=label).pack(side="left", padx=(0, 8))
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, width=width, state="readonly")
        self.combo.pack(side="left", padx=(0, 6))
        ttk.Button(self, text="⟳", width=3, command=on_refresh).pack(side="left")

    def set_values(self, values: list[str]) -> None:
        self.combo["values"] = values
        if values and self.var.get() not in values:
            self.var.set(values[0])
        elif not values:
            self.var.set("")

    def get(self) -> str:
        return self.var.get()

    def bind_select(self, callback) -> None:
        self.combo.bind("<<ComboboxSelected>>", callback)


class MoveShotsDialog(tk.Toplevel):
    """
    Modal dialog to move one or more shots from `source_sequence` to an
    existing or newly created sequence (Issue #5).
    """

    def __init__(self, parent, source_sequence: str, all_shots: list[str],
                 preselected_shots: list[str], other_sequences: list[str]):
        super().__init__(parent)
        self.title(f"Move Shot(s) from '{source_sequence}'")
        self.geometry("420x360")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.result: tuple[list[str], str] | None = None

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=f"Select shot(s) in '{source_sequence}' to move:",
                  font=("", 9, "bold")).pack(anchor="w")

        list_row = ttk.Frame(body)
        list_row.pack(fill="both", expand=True, pady=4)
        self.shot_listbox = tk.Listbox(list_row, height=7, selectmode="extended", exportselection=False)
        self.shot_listbox.pack(side="left", fill="both", expand=True)
        for idx, s in enumerate(all_shots):
            self.shot_listbox.insert(tk.END, s)
            if s in preselected_shots:
                self.shot_listbox.selection_set(idx)

        sel_btns = ttk.Frame(list_row)
        sel_btns.pack(side="left", padx=(6, 0), anchor="n")
        ttk.Button(sel_btns, text="Select All",
                   command=lambda: self.shot_listbox.selection_set(0, tk.END)).pack(fill="x", pady=2)
        ttk.Button(sel_btns, text="Clear",
                   command=lambda: self.shot_listbox.selection_clear(0, tk.END)).pack(fill="x", pady=2)

        ttk.Label(body, text="Target sequence (choose existing or type a new name):",
                  font=("", 9, "bold")).pack(anchor="w", pady=(8, 2))
        self.target_var = tk.StringVar(value=other_sequences[0] if other_sequences else "")
        self.target_combo = ttk.Combobox(body, textvariable=self.target_var, values=other_sequences)
        self.target_combo.pack(fill="x", pady=2)

        btn_bar = ttk.Frame(body)
        btn_bar.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(btn_bar, text="Move Shot(s)", command=self._confirm).pack(side="right")

    def _confirm(self):
        sel = self.shot_listbox.curselection()
        if not sel:
            messagebox.showerror("Move Shots", "Select at least one shot to move.", parent=self)
            return
        target = self.target_var.get().strip()
        if not target:
            messagebox.showerror("Move Shots", "Enter or select a target sequence name.", parent=self)
            return
        shots = [self.shot_listbox.get(i) for i in sel]
        self.result = (shots, target)
        self.destroy()


class DeleteSequenceDialog(tk.Toplevel):
    """
    Modal dialog presented when deleting a sequence that contains shots
    (Issue #5). Lets the user either delete all shots with the sequence
    or move all/selected shots to an existing or new sequence first.
    """

    def __init__(self, parent, sequence_name: str, shots: list[str], other_sequences: list[str]):
        super().__init__(parent)
        self.title(f"Delete Sequence '{sequence_name}'")
        self.geometry("460x400")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        # result is (confirmed: bool, shots_to_move: list[str], target_sequence: str | None)
        self.result: tuple[bool, list[str], str | None] = (False, [], None)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=f"Sequence '{sequence_name}' contains {len(shots)} shot(s).",
            font=("", 10, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        self.mode_var = tk.StringVar(value="delete_all")
        ttk.Radiobutton(
            body,
            text="Delete sequence and all of its shots",
            variable=self.mode_var,
            value="delete_all",
            command=self._toggle_move_controls,
        ).pack(anchor="w", pady=2)
        ttk.Radiobutton(
            body,
            text="Move all or selected shots to another sequence before deleting",
            variable=self.mode_var,
            value="move_shots",
            command=self._toggle_move_controls,
        ).pack(anchor="w", pady=2)

        self.move_frame = ttk.LabelFrame(body, text="Shots to Move & Target Sequence", padding=8)
        self.move_frame.pack(fill="both", expand=True, pady=8)

        list_row = ttk.Frame(self.move_frame)
        list_row.pack(fill="both", expand=True)
        self.shot_listbox = tk.Listbox(list_row, height=6, selectmode="extended", exportselection=False)
        self.shot_listbox.pack(side="left", fill="both", expand=True)
        for idx, s in enumerate(shots):
            self.shot_listbox.insert(tk.END, s)
            self.shot_listbox.selection_set(idx)

        sel_btns = ttk.Frame(list_row)
        sel_btns.pack(side="left", padx=(6, 0), anchor="n")
        self.select_all_btn = ttk.Button(
            sel_btns, text="Select All",
            command=lambda: self.shot_listbox.selection_set(0, tk.END),
        )
        self.select_all_btn.pack(fill="x", pady=2)
        self.clear_btn = ttk.Button(
            sel_btns, text="Clear",
            command=lambda: self.shot_listbox.selection_clear(0, tk.END),
        )
        self.clear_btn.pack(fill="x", pady=2)

        ttk.Label(self.move_frame, text="Target sequence (existing or new name):").pack(anchor="w", pady=(6, 2))
        self.target_var = tk.StringVar(value=other_sequences[0] if other_sequences else "")
        self.target_combo = ttk.Combobox(self.move_frame, textvariable=self.target_var, values=other_sequences)
        self.target_combo.pack(fill="x")

        btn_bar = ttk.Frame(body)
        btn_bar.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(btn_bar, text="Delete Sequence", command=self._confirm).pack(side="right")

        self._toggle_move_controls()

    def _toggle_move_controls(self):
        moving = self.mode_var.get() == "move_shots"
        state = "normal" if moving else "disabled"
        self.shot_listbox.configure(state=state)
        self.select_all_btn.configure(state=state)
        self.clear_btn.configure(state=state)
        self.target_combo.configure(state=state)

    def _confirm(self):
        if self.mode_var.get() == "move_shots":
            sel = self.shot_listbox.curselection()
            if not sel:
                messagebox.showerror(
                    "Delete Sequence",
                    "Select at least one shot to move, or choose 'Delete sequence and all of its shots'.",
                    parent=self,
                )
                return
            target = self.target_var.get().strip()
            if not target:
                messagebox.showerror("Delete Sequence", "Enter or select a target sequence name.", parent=self)
                return
            shots_to_move = [self.shot_listbox.get(i) for i in sel]
            self.result = (True, shots_to_move, target)
        else:
            self.result = (True, [], None)
        self.destroy()
