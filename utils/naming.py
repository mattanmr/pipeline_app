"""
utils/naming.py

Small, dependency-free helpers for turning arbitrary strings (project
names, sequence/shot names, or filenames coming from a client) into
safe, consistent names for use on disk — Windows, macOS, and Linux.
"""

from __future__ import annotations

import re

# Characters that are illegal (or awkward) in filenames on at least
# one of Windows / macOS / Linux.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_WHITESPACE = re.compile(r"\s+")
_MULTI_UNDERSCORE = re.compile(r"_+")


def sanitize_name(name: str) -> str:
    """
    Sanitize a project/sequence/shot name:
    spaces -> underscores, illegal characters stripped, trimmed.
    Does NOT touch the file extension logic — use sanitize_filename
    for actual client files.
    """
    name = name.strip()
    name = _ILLEGAL_CHARS.sub("", name)
    name = _MULTI_WHITESPACE.sub("_", name)
    name = _MULTI_UNDERSCORE.sub("_", name)
    name = name.strip("_.")
    if not name:
        raise ValueError("Name is empty after sanitization.")
    return name


def sanitize_filename(filename: str) -> str:
    """
    Sanitize an incoming client filename while preserving its
    extension, e.g. 'Final Comp (v2).mov' -> 'Final_Comp_v2.mov'.
    """
    if "." in filename:
        stem, _, ext = filename.rpartition(".")
        return f"{sanitize_name(stem)}.{ext.lower()}"
    return sanitize_name(filename)
