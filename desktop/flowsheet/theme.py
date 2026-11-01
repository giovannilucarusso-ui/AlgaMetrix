"""Canvas colour themes for the Process Designer.

Two sheets: *Paper*, a light drafting sheet that prints well, and *Blueprint*,
a dark sheet for working on screen. Everything the canvas paints takes its
colours from the active :class:`Theme`, so switching is a repaint.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class Theme:
    name: str
    canvas: str
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
    paper: str           # colour of cut-outs inside symbols
    flow_tint: str       # moving dashes drawn over a stream
    elec: str
    heat: str
    ok: str
    warn: str
    error: str
    idle: str
    layer: dict = field(default_factory=dict)    # layer -> halo colour
    credit: str = "#16a34a"                      # negative contributions (GWP credits)
    stream: dict = field(default_factory=dict)   # stream class -> colour
    dark: bool = False


PAPER = Theme(
    name="Paper",
    canvas="#fbfcfd", grid_minor="#eef2f6", grid_major="#e0e7ec",
    ink="#0f172a", ink_dim="#64748b", ink_faint="#94a3b8",
    face_bg="#ffffff", face_border="#d9e1e8", face_ink="#1f2d3a",
    chip_bg="#ffffff", chip_border="#d5dde3",
    selection="#15803d", hover="#e9f3ee", frame="#5b6b78", paper="#ffffff",
    flow_tint="#ffffff",
    elec="#d4a106", heat="#dc2626",
    ok="#22c55e", warn="#f59e0b", error="#ef4444", idle="#a8b4c0",
    layer={"mass": "#2563eb", "energy": "#d97706", "cost": "#dc2626", "gwp": "#7c3aed"},
    stream={
        "broth": "#23966a", "slurry": "#2e7d32", "solids": "#b7791f", "water": "#2b7bd6",
        "effluent": "#7d9fc0", "vapour": "#9aaabb", "gas": "#4f86a6", "nutrients": "#e8590c",
        "substrate": "#a0522d", "solvent": "#7c3aed", "extract": "#d97706", "empty": "#b9c4cf",
    },
)

BLUEPRINT = Theme(
    name="Blueprint",
    canvas="#0b1a2b", grid_minor="#11253b", grid_major="#18324e",
    ink="#e6f0fa", ink_dim="#8fb0cc", ink_faint="#5d7d99",
    face_bg="#0f2236", face_border="#24486b", face_ink="#d6e6f5",
    chip_bg="#0f2236", chip_border="#24486b",
    selection="#4ade80", hover="#13314f", frame="#5f87ad", paper="#0b1a2b",
    flow_tint="#ffffff",
    elec="#facc15", heat="#f87171",
    ok="#4ade80", warn="#fbbf24", error="#f87171", idle="#5d7d99",
    layer={"mass": "#60a5fa", "energy": "#fbbf24", "cost": "#f87171", "gwp": "#c084fc"},
    credit="#4ade80",
    stream={
        "broth": "#34d399", "slurry": "#4ade80", "solids": "#fbbf24", "water": "#60a5fa",
        "effluent": "#7fa6c9", "vapour": "#94a9bd", "gas": "#67c3e0", "nutrients": "#fb923c",
        "substrate": "#d6a06a", "solvent": "#a78bfa", "extract": "#fcd34d", "empty": "#3d5a76",
    },
    dark=True,
)

THEMES = {t.name: t for t in (PAPER, BLUEPRINT)}

# Symbol colour per unit category on each sheet (the paper colours are the ones
# the palette and the boxed blocks have always used).
CATEGORY_DARK = {
    "io": "#9fb6c8",
    "cultivation": "#4ade80",
    "separation": "#60a5fa",
    "thermal": "#fb923c",
    "downstream": "#c084fc",
    "logic": "#a3b8cc",
}


def category_color(category: str, theme: Theme) -> str:
    from .model import CATEGORY_COLORS

    if theme.dark:
        return CATEGORY_DARK.get(category, "#a3b8cc")
    return CATEGORY_COLORS.get(category, "#455a64")


# Slim scroll bar for the side panels (palette, inspector).
THIN_SCROLLBAR = (
    "QScrollBar:vertical{background:transparent; width:8px; margin:2px 0;}"
    "QScrollBar::handle:vertical{background:#cbd5e1; border-radius:4px; min-height:28px;}"
    "QScrollBar::handle:vertical:hover{background:#94a3b8;}"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}"
)
