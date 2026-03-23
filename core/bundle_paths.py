"""Resolve bundled files when running under PyInstaller (sys.frozen) vs dev tree."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def _meipass() -> Path:
    return Path(getattr(sys, "_MEIPASS"))


def game_data_json() -> Path:
    """Path to data.json (combat definitions)."""
    if is_frozen():
        return _meipass() / "core" / "data.json"
    return _CORE_DIR / "data.json"


def assets_sound_dir() -> Path:
    """Directory with MP3 SFX (may be partial; missing files are skipped at runtime)."""
    if is_frozen():
        return _meipass() / "assets" / "sound"
    return _CORE_DIR.parent / "assets" / "sound"
