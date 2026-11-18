"""Compatibility shim: the stylesheet now lives in :mod:`desktop.theme`.

Kept so that ``from desktop.style import STYLESHEET`` keeps working for any
script written against the previous layout.
"""

from .theme import ACCENT, ACCENT_DARK, STYLESHEET

__all__ = ["ACCENT", "ACCENT_DARK", "STYLESHEET"]
