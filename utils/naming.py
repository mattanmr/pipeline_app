"""
utils/naming.py

Small, dependency-free helpers for turning arbitrary strings (project
names, sequence/shot names, or filenames coming from a client) into
safe, consistent names for use on disk – Windows, macOS, and Linux.
"""

from __future__ import annotations

import re

# Characters that are illegal (or awkward) in filenames on at least
# one of Windows / macOS / Linux.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*()\x00-\x1f]')
_MULTI_WHITESPACE = re.compile(r"\s+")
_MULTI_UNDERSCORE = re.compile(r"_+")


def sanitize_name(name: str) -> str:
    """
    Sanitize a project/sequence/shot name:
    spaces -> underscores, illegal characters stripped, trimmed.
    Does NOT touch the file extension logic – use sanitize_filename
    for actual client files.
    """
    name = name.strip()
    if name in {".", ".."}:
        raise ValueError("Name cannot be '.' or '..'.")
    name = _ILLEGAL_CHARS.sub("", name)
    name = _MULTI_WHITESPACE.sub("_", name)
    name = _MULTI_UNDERSCORE.sub("_", name)
    name = name.strip("_")
    if not name:
        raise ValueError("Name is empty after sanitization.")
    return name


def format_shot_name(sequence_name: str, shot_name: str) -> str:
    """
    Prefix a shot name with its parent sequence name/number using an
    underscore (e.g. sequence '01' + shot '001' -> '01_001',
    sequence 'hallway' + shot '001' -> 'hallway_001').
    Avoids double-prefixing if shot_name already starts with '<sequence>_'.
    """
    seq = sanitize_name(sequence_name)
    shot = sanitize_name(shot_name)
    prefix = f"{seq}_"
    if shot.startswith(prefix):
        return shot
    return f"{prefix}{shot}"


def rename_shot_for_sequence(shot_name: str, old_sequence: str, new_sequence: str) -> str:
    """
    Compute the new shot name when moving `shot_name` from `old_sequence`
    to `new_sequence` (e.g. '01_001' from '01' to '02' -> '02_001',
    'hallway_001' from 'hallway' to 'lobby' -> 'lobby_001').
    """
    old_seq = sanitize_name(old_sequence)
    new_seq = sanitize_name(new_sequence)
    shot = sanitize_name(shot_name)
    old_prefix = f"{old_seq}_"
    if shot.startswith(old_prefix) and len(shot) > len(old_prefix):
        base_shot = shot[len(old_prefix):]
    else:
        base_shot = shot
    return format_shot_name(new_seq, base_shot)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize an incoming client filename while preserving its
    extension, e.g. 'Final Comp (v2).mov' -> 'Final_Comp_v2.mov'.
    """
    if "." in filename:
        stem, _, ext = filename.rpartition(".")
        return f"{sanitize_name(stem)}.{ext.lower()}"
    return sanitize_name(filename)
