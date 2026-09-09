"""
gui/components.py

Small reusable Tkinter widgets shared across views.py. Nothing here
talks to core/ directly -- these are pure UI building blocks that
report user input back through callbacks/getters, kept dumb on
purpose so views.py stays the only place that decides what a button
press means for the pipeline.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog


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
        """
        mode: "file", "folder", or "any" (lets the user browse either,
        via two buttons -- used for publish sources which can be a
        single file or a whole folder, e.g. an EXR sequence).
        """
        super().__init__(parent, **kwargs)
        self.mode = mode
        ttk.Label(self, text=label).pack(side="left", padx=(0, 8))
        self.var = tk.StringVar()
        ttk.Entry(self, textvariable=self.var, width=width).pack(
            side="left", fill="x", expand=True, padx=(0, 6))

        if mode in ("file", "any"):
            ttk.Button(self, text="Browse File…", command=self._browse_file).pack(side="left", padx=2)
        if mode in ("folder", "any"):
            ttk.Button(self, text="Browse Folder…", command=self._browse_folder).pack(side="left", padx=2)

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
    Model / Prompt fields, shown only when the selected publish
    category is AI_Generated/Images or AI_Generated/Video. For Video,
    also exposes a free-text "source" field -- entered as
    Category:version pairs, comma-separated (e.g.
    "AI_Generated/Images:v001, Footage:v002") -- since a generated
    video's source can point at any category, not just AI images.
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
