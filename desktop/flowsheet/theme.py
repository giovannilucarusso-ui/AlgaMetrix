"""Drawing colours for the Process Designer.

Everything the canvas paints takes its colours from :data:`PAPER`, a light
drafting sheet that prints well.
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


PAPER = Theme(
    canvas="#fbfcfd", grid_minor="#eef2f6", grid_major="#e0e7ec",
    ink="#0f172a", ink_dim="#64748b", ink_faint="#94a3b8",
    face_bg="#ffffff", face_border="#d9e1e8", face_ink="#1f2d3a",
    chip_bg="#ffffff", chip_border="#d5dde3",
    selection="#15803d", hover="#e9f3ee", frame="#5b6b78",
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


def category_color(category: str) -> str:
    """Symbol colour of a unit category (the colours the palette uses)."""
    from .model import CATEGORY_COLORS

    return CATEGORY_COLORS.get(category, "#455a64")


# Slim scroll bar for the side panels (palette, inspector).
THIN_SCROLLBAR = (
    "QScrollBar:vertical{background:transparent; width:8px; margin:2px 0;}"
    "QScrollBar::handle:vertical{background:#cbd5e1; border-radius:4px; min-height:28px;}"
    "QScrollBar::handle:vertical:hover{background:#94a3b8;}"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0;}"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}"
)
