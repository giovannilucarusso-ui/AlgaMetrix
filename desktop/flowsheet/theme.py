"""Drawing colours for the Process Designer.

Everything the canvas paints takes its colours from :data:`PAPER`, a white
drafting sheet on the grey desk of the rest of the app. The values are the
app's design tokens (``desktop/theme.py``): text in the ink tones, hairlines in
``LINE``, the selection in ``ACCENT``, block states in the state colours, and
stream classes, utilities and plant areas in the chart palette. The palette has
eight hues for eleven stream classes, so the three that matter least for
reading the process (gas, effluent, vapour) are drawn in greys.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import theme as ui

# Stream classes, in legend order. ``process.stream_class`` assigns them.
STREAM_LABELS: dict[str, str] = {
    "broth": "Culture broth",
    "slurry": "Concentrate / paste",
    "solids": "Dry solids",
    "water": "Water / medium",
    "effluent": "Effluent",
    "vapour": "Vapour",
    "gas": "CO₂ / gas",
    "nutrients": "Nutrients / reagents",
    "substrate": "Organic substrate",
    "solvent": "Solvent",
    "extract": "Extract / product",
}

# Overlay layers: what a block's halo is coloured by.
LAYERS = ("mass", "energy", "cost", "gwp")
LAYER_LABELS = {"mass": "Mass", "energy": "Energy", "cost": "Cost", "gwp": "GWP"}

# Stream classes and the components inside a stream share their hues, so water
# is the same blue on a line and in a stream's composition bar.
_BLUE, _ORANGE, _AQUA, _YELLOW, _MAGENTA, _GREEN, _VIOLET, _RED = ui.SERIES

STREAM_COLORS: dict[str, str] = {
    "broth": _AQUA, "slurry": _GREEN, "solids": _YELLOW, "water": _BLUE,
    "effluent": ui.INK_DISABLED, "vapour": ui.CHART_AXIS, "gas": ui.INK_2,
    "nutrients": _ORANGE, "substrate": _MAGENTA, "solvent": _VIOLET, "extract": _RED,
    "empty": ui.LINE,
}

COMPONENT_COLORS: dict[str, str] = {
    "biomass": _GREEN, "water": _BLUE, "solvent": _VIOLET, "product": _RED,
    "substrate": _MAGENTA, "co2": ui.INK_2, "other": _ORANGE,
}


@dataclass(frozen=True)
class Theme:
    canvas: str          # the drawing sheet
    desk: str            # around the sheet
    grid_minor: str
    grid_major: str
    ink: str             # tags, headings
    ink_dim: str         # block names
    ink_faint: str       # secondary labels
    face_bg: str         # read-out plate under a block
    face_border: str
    face_ink: str
    chip_bg: str         # flow-rate chips on streams
    chip_border: str
    selection: str
    hover: str
    frame: str           # sheet border and title block
    flow_tint: str       # moving dashes drawn over a stream
    elec: str
    heat: str
    ok: str
    warn: str
    error: str
    idle: str
    layer: dict = field(default_factory=dict)    # layer -> halo colour
    credit: str = ui.CREDIT                      # negative contributions (GWP credits)
    stream: dict = field(default_factory=dict)   # stream class -> colour


PAPER = Theme(
    canvas=ui.SURFACE, desk=ui.CANVAS,
    grid_minor=ui.SURFACE_3, grid_major=ui.LINE_SOFT,
    ink=ui.INK, ink_dim=ui.INK_2, ink_faint=ui.INK_3,
    face_bg=ui.SURFACE, face_border=ui.LINE, face_ink=ui.INK,
    chip_bg=ui.SURFACE, chip_border=ui.LINE,
    selection=ui.ACCENT, hover=ui.ACCENT_SOFT, frame=ui.INK_3,
    flow_tint=ui.SURFACE,
    elec=_YELLOW, heat=_RED,
    ok=ui.SUCCESS, warn=ui.WARNING_LINE, error=ui.DANGER_LINE, idle=ui.INK_DISABLED,
    # A halo shows how much of something a block carries: one hue for every
    # layer, except GWP, which has a sign (burden red, credit blue).
    layer={"mass": ui.CHART_PRIMARY, "energy": ui.CHART_PRIMARY,
           "cost": ui.CHART_PRIMARY, "gwp": ui.BURDEN},
    credit=ui.CREDIT,
    stream=dict(STREAM_COLORS),
)


def category_color(category: str) -> str:
    """Symbol colour of a unit category (the colours the palette uses)."""
    from .model import CATEGORY_COLORS

    return CATEGORY_COLORS.get(category, ui.INK_2)


def _families(stack: str) -> list[str]:
    generic = {"monospace", "sans-serif", "serif"}
    names = (name.strip().strip('"') for name in stack.split(","))
    return [name for name in names if name and name not in generic]


def ui_font_families() -> list[str]:
    """The app's text font stack (``theme.FONT_FAMILY``) as a list for ``QFont``."""
    return _families(ui.FONT_FAMILY)


def mono_font_families() -> list[str]:
    """The monospace stack of the app (``theme.FONT_MONO``) as a list for ``QFont``."""
    return _families(ui.FONT_MONO)


def mono_family() -> str:
    """The first family of that stack installed here, for rich text, which takes one."""
    from PySide6.QtGui import QFontDatabase

    installed = set(QFontDatabase.families())
    return next((name for name in mono_font_families() if name in installed), "monospace")


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def on_fill(hex_color: str) -> str:
    """Text colour for a label set inside a coloured fill: white or the ink,
    whichever stands out more against that fill."""
    fill = _luminance(hex_color)
    against_white = 1.05 / (fill + 0.05)
    against_ink = (fill + 0.05) / (_luminance(ui.INK) + 0.05)
    return ui.SURFACE if against_white >= against_ink else ui.INK


# Slim scroll bar for the side panels (palette, inspector).
THIN_SCROLLBAR = (
    "QScrollBar:vertical{background:transparent; width:8px; margin:2px 0;}"
    f"QScrollBar::handle:vertical{{background:{ui.LINE}; border-radius:4px; min-height:28px;}}"
    f"QScrollBar::handle:vertical:hover{{background:{ui.INK_DISABLED};}}"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}"
)
