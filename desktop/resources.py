"""Bundled asset resolution (logo, icons), aware of the PyInstaller layout.

In a source checkout the assets live under ``desktop/assets``. In a frozen
(PyInstaller) build they are shipped under ``sys._MEIPASS`` — the exact subpath
depends on how the spec maps them, so we probe the likely locations. Kept
Qt-free so both the matplotlib report and the Qt widgets resolve the same paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _asset_dirs() -> list[Path]:
    dirs = [_HERE / "assets"]  # source checkout
    if getattr(sys, "frozen", False):
        mei = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs += [mei / "desktop" / "assets", mei / "assets"]
    return dirs


def asset_path(name: str) -> str | None:
    """Absolute path to a bundled asset by file name, or ``None`` if missing."""
    for d in _asset_dirs():
        p = d / name
        if p.exists():
            return str(p)
    return None


def logo_path() -> str | None:
    """Absolute path to the Algametrix logo (transparent lockup), or ``None``."""
    return asset_path("algametrix_logo.png")
