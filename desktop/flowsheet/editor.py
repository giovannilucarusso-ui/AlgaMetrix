"""The Process Designer widget.

A process flow diagram of the case study that doubles as its control panel.
Every block generated from the scenario carries the engine's figures and the
scenario fields behind it, so moving a variable in the inspector re-runs the
TEA/LCA, and the drawing, the KPI strip and the charts follow at once. Edits
stay in a working copy (:class:`~desktop.flowsheet.process.DesignSession`)
until they are applied to the case study.

Blocks can still be drawn by hand from the palette; those take part in the
canvas mass balance only.
"""

from __future__ import annotations

import csv
import json
import math
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPdfWriter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import builder as B
from . import icons, model as M
from . import process as P
from .builder import flowsheet_from_scenario, seed_flows
from .charts import KpiTile, StackedBars, TornadoChart
from .inspector import Context, Inspector
from .scene import FlowsheetScene, NodeItem
from .theme import LAYER_LABELS, STREAM_LABELS, THIN_SCROLLBAR
from .view import FlowsheetView

# Palette order (category -> heading label).
_CATEGORY_LABELS = {
    "io": "Feeds & products",
    "cultivation": "Cultivation",
    "separation": "Separation",
    "thermal": "Thermal",
    "downstream": "Downstream",
    "logic": "Logic",
}

_COMPONENT_LABELS = {"biomass": "Biomass (dry)", "water": "Water", "solvent": "Solvent",
                     "product": "Product", "substrate": "Substrate", "co2": "CO₂",
                     "other": "Salts & other"}

_COST_CATS = (("energy", "Energy", "#d4a106"), ("materials", "Feeds & materials", "#8a5a44"),
              ("capital", "Capital-related", "#475569"), ("utilities", "Utilities", "#0284c7"),
              ("plant", "Labour, overhead & other", "#7c3aed"))
_GWP_CATS = (("elec", "Electricity", "#d4a106"), ("heat", "Heat", "#dc2626"),
             ("inputs", "Feeds & materials", "#8a5a44"), ("uptake", "Biogenic uptake", "#16a34a"),
             ("credit", "Avoided treatment", "#0d9488"), ("other", "Other", "#64748b"))
_ENERGY_CATS = (("power", "Electricity", "#d4a106"), ("heat", "Heat", "#dc2626"))

_LINKED_ROLES = (B.CULTIVATION, B.HARVEST, B.DRYING, B.DISRUPTION, B.EXTRACTION, B.FEED_WATER,
                 B.FEED_NUTRIENTS, B.FEED_CARBON, B.FEED_SUBSTRATE, B.FEED_SOLVENT, B.FEED_CHEMICALS,
                 B.FEED_WASTE, B.PRODUCT)

_TOOL_CSS = (
    "QToolButton{background:#ffffff; color:#334155; border:1px solid #cbd5e1; border-radius:5px; "
    "padding:4px 9px; font-weight:600;} "
    "QToolButton:hover{background:#f1f5f9; border-color:#94a3b8;} "
    "QToolButton:checked{background:#e7f0e9; border-color:#15803d; color:#14532d;} "
    "QToolButton:disabled{color:#b8c2cc; border-color:#e2e8f0;} "
    "QToolButton::menu-indicator{image:none;}")
_PRIMARY_CSS = (
    "QToolButton{background:#15803d; color:white; border:none; border-radius:5px; padding:5px 11px; "
    "font-weight:700;} QToolButton:hover{background:#116330;} "
    "QToolButton:disabled{background:#c3ccd6; color:#eef2f6;}")
_BLUE_CSS = (
    "QToolButton{background:#1565c0; color:white; border:none; border-radius:5px; padding:5px 11px; "
    "font-weight:700;} QToolButton:hover{background:#0f4c99;} "
    "QToolButton:disabled{background:#c3ccd6; color:#eef2f6;}")


def _stream_width(total: float, fmax: float) -> float:
    if total <= 0 or fmax <= 0:
        return 1.3
    return 1.4 + 6.4 * math.log1p(total) / math.log1p(fmax)


def _cost_cat(line: str, role: str) -> str:
    if line in ("Electricity", "Heat"):
        return "energy"
    if line == "Facility-dependent":
        return "capital"
    if role == P.PLANT:
        return "plant"
    if role == B.CULTIVATION:
        return "utilities"
    return "materials"


def _gwp_cat(line: str, role: str) -> str:
    if line == "Electricity":
        return "elec"
    if line == "Heat":
        return "heat"
    if line == "Biogenic CO2 uptake":
        return "uptake"
    if line == "Avoided treatment (system expansion)":
        return "credit"
    return "other" if role == P.PLANT else "inputs"


class _ElidedLabel(QLabel):
    """One-line label that shortens itself with an ellipsis instead of widening the window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def set_full_text(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        room = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(room, 0)))


class FlowsheetEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = FlowsheetScene(M.starter_flowsheet())
        self.scene.set_sections([(s.code, s.label, s.roles, s.color) for s in P.SECTIONS])
        self.scene.logo = self._logo_pixmap()
        self.scene.stream_info = self._stream_card
        self.view = FlowsheetView(self.scene)

        self.session: P.DesignSession | None = None
        self._base_att: P.Attribution | None = None
        self._att: P.Attribution | None = None
        self._solve: M.SolveResult | None = None
        self._status: dict = {}
        self._stream_no: dict[str, int] = {}
        self._layer = "cost"
        self._focus: P.Variable | None = None
        self._curve_key: tuple | None = None
        self._curve_points: list = []
        self._case_changed = False
        self._add_offset = 0
        self._log_sig: tuple | None = None
        self._table_dirty = True
        # Set by the host window: returns (Scenario, Results | None) for the live
        # case study, takes a Scenario back, and provides the preset library.
        self._scenario_source = None
        self._scenario_sink = None
        self._library = None
        self._autogen_done = False

        self._analysis_timer = QTimer(self)
        self._analysis_timer.setSingleShot(True)
        self._analysis_timer.setInterval(300)
        self._analysis_timer.timeout.connect(self._run_analysis)

        self._build_ui()

        self.scene.graphChanged.connect(self.solve_and_annotate)
        self.scene.nodeSelected.connect(self._on_node_selected)
        self.scene.edgeSelected.connect(self._on_edge_selected)
        self.scene.message.connect(self._flash)

        self.btn_palette.setChecked(True)
        self.solve_and_annotate()
        self.view.fit_content()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.addLayout(self._build_toolbar())

        self.kpi_bar = QWidget()
        kl = QHBoxLayout(self.kpi_bar)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(6)
        self.tiles: dict[str, KpiTile] = {}
        for k in P.KPIS:
            tile = KpiTile(k)
            tile.setMinimumWidth(96)
            kl.addWidget(tile)
            self.tiles[k.key] = tile
        root.addWidget(self.kpi_bar)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(10, 5, 6, 5)
        bl.setSpacing(8)
        self.banner_text = QLabel("")
        self.banner_text.setTextFormat(Qt.RichText)
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        self.banner_btns: list[QPushButton] = []
        self._banner_actions: list = [None, None]
        for i in range(2):
            b = QPushButton("")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self._banner_click(i))
            bl.addWidget(b)
            self.banner_btns.append(b)
        root.addWidget(self.banner)

        self.palette_box = self._build_palette()
        self.inspector = Inspector()
        self.inspector.variableEdited.connect(self._on_variable_edited)
        self.inspector.variableFocused.connect(self._on_variable_focused)
        self.inspector.variableReset.connect(self._on_variable_reset)
        self.inspector.technologyChosen.connect(self._on_technology)
        self.inspector.nodeParamEdited.connect(self._set_param)
        self.inspector.nodeRenamed.connect(self._rename)
        self.inspector.deleteRequested.connect(self._delete_node)

        canvas = QFrame()
        canvas.setObjectName("canvasFrame")
        canvas.setStyleSheet("#canvasFrame{border:1px solid #d5dde3; border-radius:6px;}")
        cl = QVBoxLayout(canvas)
        cl.setContentsMargins(1, 1, 1, 1)
        cl.addWidget(self.view)
        self._build_canvas_bar()

        middle = QSplitter(Qt.Horizontal)
        middle.addWidget(self.palette_box)
        middle.addWidget(canvas)
        middle.addWidget(self.inspector)
        middle.setStretchFactor(0, 0)
        middle.setStretchFactor(1, 1)
        middle.setStretchFactor(2, 0)
        middle.setChildrenCollapsible(False)
        middle.setSizes([215, 1000, 370])

        self.dock = self._build_dock()
        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(middle)
        vsplit.addWidget(self.dock)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 0)
        vsplit.setSizes([640, 250])
        root.addWidget(vsplit, 1)

        for seq, slot in ((QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo),
                          (QKeySequence("Ctrl+Shift+Z"), self.redo),
                          (QKeySequence("F"), self.view.fit_content)):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def _tool(self, text: str, tip: str, slot=None, checkable=False, checked=False, css=_TOOL_CSS):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if checkable:
            b.setChecked(checked)
            if slot is not None:
                b.toggled.connect(slot)
        elif slot is not None:
            b.clicked.connect(slot)
        b.setStyleSheet(css)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(5)
        title = QLabel("Process Designer")
        title.setStyleSheet("font-weight:800; color:#0f172a; font-size:14px; letter-spacing:0.3px;")
        bar.addWidget(title)
        self.pfd_subtitle = _ElidedLabel()
        self.pfd_subtitle.setStyleSheet("color:#5b6b78; font-size:11px; padding-left:8px;")
        bar.addWidget(self.pfd_subtitle, 1)

        self.btn_generate = self._tool(
            "⟳ From case study", "Build the drawing from the current TEA/LCA case study "
            "(organism, system, harvesting, drying, extraction) and link it to the engine.",
            self.generate_from_scenario, css=_BLUE_CSS)
        self.btn_undo = self._tool("↶ Undo", "Undo the last change (Ctrl+Z)", self.undo)
        self.btn_redo = self._tool("↷ Redo", "Redo (Ctrl+Y)", self.redo)
        self.btn_apply = self._tool(
            "✓ Apply to case study", "Copy the designer's working copy into the case study: the "
            "Scenario tab, the KPI cards and every export will use it.", self.apply_to_case,
            css=_PRIMARY_CSS)
        self.btn_reset = self._tool("Reset", "Back to the case study as loaded (undoable)",
                                    self.reset_to_case)
        self.btn_palette = self._tool("Blocks", "Show the palette of unit operations for drawing "
                                      "by hand", self._set_palette_visible, checkable=True)
        for b in (self.btn_generate, self.btn_undo, self.btn_redo, self.btn_apply, self.btn_reset):
            bar.addWidget(b)
        bar.addSpacing(8)
        bar.addWidget(self.btn_palette)

        file_btn = self._tool("File ▾", "Save or load a drawing")
        menu = QMenu(file_btn)
        menu.addAction("Save drawing…", self.save_flowsheet)
        menu.addAction("Load drawing…", self.load_flowsheet)
        menu.addSeparator()
        menu.addAction("Sketch example", self.load_example)
        menu.addAction("Clear canvas", self.clear_flowsheet)
        file_btn.setMenu(menu)
        file_btn.setPopupMode(QToolButton.InstantPopup)
        bar.addWidget(file_btn)

        exp_btn = self._tool("Export ▾", "Export the drawing or the stream table")
        emenu = QMenu(exp_btn)
        emenu.addAction("Image (PNG)…", lambda: self.export_image("png"))
        emenu.addAction("Vector PDF…", lambda: self.export_image("pdf"))
        emenu.addAction("Vector SVG…", lambda: self.export_image("svg"))
        emenu.addSeparator()
        emenu.addAction("Stream table (CSV)…", self.export_streams_csv)
        exp_btn.setMenu(emenu)
        exp_btn.setPopupMode(QToolButton.InstantPopup)
        bar.addWidget(exp_btn)
        return bar

    def _build_canvas_bar(self):
        """Floating controls over the canvas: overlay layer, what to show, theme, zoom."""
        self.canvas_bar = QFrame(self.view)
        self.canvas_bar.setObjectName("canvasBar")
        lay = QHBoxLayout(self.canvas_bar)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)

        cap = QLabel("HALO")
        cap.setObjectName("cap")
        lay.addWidget(cap)
        self.layer_group = QButtonGroup(self.canvas_bar)
        self.layer_group.setExclusive(True)
        self.layer_btns: dict[str, QToolButton] = {}
        for key, label in (("none", "Off"),) + tuple(LAYER_LABELS.items()):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setChecked(key == self._layer)
            b.setToolTip({"none": "No halo behind the blocks",
                          "mass": "Halo sized by the mass each block handles",
                          "energy": "Halo sized by electric load plus heat duty",
                          "cost": "Halo sized by each block's share of the operating cost",
                          "gwp": "Halo sized by each block's GWP contribution "
                                 "(green: a credit)"}[key])
            b.clicked.connect(lambda _=False, k=key: self.set_layer(k))
            self.layer_group.addButton(b)
            lay.addWidget(b)
            self.layer_btns[key] = b
        lay.addSpacing(8)

        self.toggle_btns: dict[str, QToolButton] = {}
        for key, label, tip, on in (
                ("areas", "Areas", "Dashed frames around the plant areas (100–500)", True),
                ("utilities", "Utilities", "Electricity and heat headers with a drop to each user", False),
                ("labels", "Labels", "Flow chips and stream numbers on the lines", True),
                ("flow", "Flow", "Moving dashes along the streams", True),
                ("sheet", "Sheet", "Drawing border, legend and title block", True),
                ("map", "Map", "Overview map in the corner while part of the drawing is "
                                "off screen", True)):
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(on)
            b.toggled.connect(lambda checked, k=key: self._toggle(k, checked))
            lay.addWidget(b)
            self.toggle_btns[key] = b
        lay.addSpacing(8)

        self.btn_boxes = QToolButton()
        self.btn_boxes.setText("Boxes")
        self.btn_boxes.setCheckable(True)
        self.btn_boxes.setChecked(not getattr(NodeItem, "BOXLESS", True))
        self.btn_boxes.setToolTip("Boxed blocks with port labels (handier for wiring by hand)")
        self.btn_boxes.toggled.connect(self._toggle_boxes)
        lay.addWidget(self.btn_boxes)
        lay.addSpacing(8)
        for text, tip, slot in (("−", "Zoom out", lambda: self.view.zoom_by(1 / 1.2)),
                                ("100 %", "Click for 100 %. Wheel to zoom, middle-drag to pan.",
                                 self.view.reset_zoom),
                                ("+", "Zoom in", lambda: self.view.zoom_by(1.2)),
                                ("Fit", "Fit the drawing (F)", self.view.fit_content)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            lay.addWidget(b)
            if text == "100 %":
                b.setMinimumWidth(52)
                self.btn_zoom = b
        self.view.zoomChanged.connect(lambda k: self.btn_zoom.setText(f"{k * 100:.0f} %"))
        self._style_canvas_bar()
        self.canvas_bar.move(12, 10)
        self.canvas_bar.raise_()
        self.view.top_reserve = 48.0

    def _fit_canvas_bar(self):
        # sizes are only right once the style sheet has been applied
        self.canvas_bar.ensurePolished()
        self.canvas_bar.adjustSize()

    def _style_canvas_bar(self):
        self.canvas_bar.setStyleSheet(
            "#canvasBar{background:rgba(255,255,255,240); border:1px solid #cbd5e1; border-radius:8px;}"
            "#canvasBar QLabel#cap{color:#94a3b8; font-size:9px; font-weight:700; padding:0 3px;}"
            "#canvasBar QToolButton{background:transparent; color:#334155; border:1px solid transparent;"
            " border-radius:4px; padding:2px 7px; font-size:11px; font-weight:600;}"
            "#canvasBar QToolButton:hover{background:#f1f5f9;}"
            "#canvasBar QToolButton:checked{background:#e7f0e9; color:#14532d; border-color:#14532d;}")
        self._fit_canvas_bar()

    def _build_palette(self) -> QWidget:
        box = QFrame()
        box.setObjectName("kpiCard")
        box.setMinimumWidth(200)
        box.setMaximumWidth(260)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        head = QLabel("Unit operations")
        head.setStyleSheet("font-weight:700; color:#334155;")
        lay.addWidget(head)
        self.palette = QListWidget()
        self.palette.setFrameShape(QFrame.NoFrame)
        self.palette.setIconSize(QSize(22, 22))
        self.palette.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.palette.setTextElideMode(Qt.ElideRight)
        self.palette.setStyleSheet("QListWidget{background:transparent;} "
                                   "QListWidget::item{padding:4px 4px; border-radius:6px;} "
                                   "QListWidget::item:hover{background:#eef5ee;}")
        self.palette.verticalScrollBar().setStyleSheet(THIN_SCROLLBAR)
        self.palette.itemDoubleClicked.connect(self._palette_add)
        for cat, label in _CATEGORY_LABELS.items():
            header = QListWidgetItem(label.upper())
            header.setFlags(Qt.NoItemFlags)
            header.setFont(QFont("Segoe UI", 7, QFont.Bold))
            header.setForeground(QColor("#90a0ab"))
            self.palette.addItem(header)
            color = QColor(M.CATEGORY_COLORS.get(cat, "#455a64"))
            for key, sp in M.UNIT_TYPES.items():
                if sp.category != cat:
                    continue
                item = QListWidgetItem(f" {sp.label}")
                item.setIcon(QIcon(icons.icon_pixmap(sp.icon, 22, color)))
                item.setData(Qt.UserRole, key)
                item.setToolTip(sp.hint)
                self.palette.addItem(item)
        lay.addWidget(self.palette, 1)
        tip = QLabel("Double-click to drop on the canvas · drag outlet → inlet to connect · "
                     "Del removes a hand-drawn block")
        tip.setObjectName("subtle")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return box

    def _build_dock(self) -> QTabWidget:
        dock = QTabWidget()
        dock.setDocumentMode(True)

        def scrolled(widget) -> QScrollArea:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setWidget(widget)
            return sa

        self.cost_chart = StackedBars("Annual operating cost by block")
        self.gwp_chart = StackedBars("GWP contribution by block")
        self.energy_chart = StackedBars("Electric load and heat duty by block")
        dock.addTab(scrolled(self.cost_chart), "Cost")
        dock.addTab(scrolled(self.gwp_chart), "Emissions")
        dock.addTab(scrolled(self.energy_chart), "Energy")

        self.stream_table = QTableWidget(0, 6 + len(M.COMPONENTS))
        self.stream_table.setHorizontalHeaderLabels(
            ["S#", "From", "To", "Kind", "Total kg/h"]
            + [_COMPONENT_LABELS[c].split(" (")[0] for c in M.COMPONENTS] + ["DS %"])
        self.stream_table.verticalHeader().setVisible(False)
        self.stream_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stream_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stream_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.stream_table.setAlternatingRowColors(True)
        self.stream_table.setStyleSheet("QTableWidget{border:none; font-size:11px;} "
                                        "QHeaderView::section{font-size:10px; font-weight:600;}")
        hh = self.stream_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        self.stream_table.itemSelectionChanged.connect(self._on_table_selection)
        dock.addTab(self.stream_table, "Streams")

        self.tornado = TornadoChart()
        self._drivers_page = scrolled(self.tornado)
        dock.addTab(self._drivers_page, "Key drivers")

        self.log_list = QListWidget()
        self.log_list.setStyleSheet("QListWidget{border:none; font-size:11px;} "
                                    "QListWidget::item{padding:3px 6px;}")
        self.log_list.itemClicked.connect(self._on_log_clicked)
        dock.addTab(self.log_list, "Change log")
        dock.currentChanged.connect(self._on_dock_tab)
        return dock

    # ------------------------------------------------------------------ #
    # Host wiring
    # ------------------------------------------------------------------ #
    def set_scenario_source(self, provider) -> None:
        """Register a callable returning ``(Scenario, Results | None)``.

        The host window wires this to its live case study so the canvas can be
        regenerated from the same inputs that drive the TEA and LCA."""
        self._scenario_source = provider
        self.btn_generate.setEnabled(provider is not None)
        self._update_banner()

    def set_scenario_sink(self, sink) -> None:
        """Register a callable that takes a Scenario and makes it the case study."""
        self._scenario_sink = sink
        self._update_buttons()

    def set_library(self, library) -> None:
        """The preset library, for the technology choices in the inspector."""
        self._library = library
        if self.session is not None:
            self.session.library = library

    def _current_scenario(self):
        if self._scenario_source is None:
            return None, None
        try:
            scn, results = self._scenario_source()
            return scn, results
        except Exception:  # never let a scenario error break the canvas
            return None, None

    # ------------------------------------------------------------------ #
    # Linking to the case study
    # ------------------------------------------------------------------ #
    def generate_from_scenario(self, *, confirm: bool = True) -> bool:
        """Replace the canvas with a flowsheet built from the live scenario."""
        scn, _results = self._current_scenario()
        if scn is None:
            QMessageBox.information(
                self, "From case study",
                "No case study is available yet. Set up a scenario on the "
                "Scenario tab (or via the wizard) first.")
            return False
        has_free = any(not n.role for n in self.scene.flowsheet.nodes.values())
        dirty = self.session is not None and self.session.is_dirty
        if confirm and self.scene.flowsheet.nodes and (dirty or (has_free and not self._is_pristine())):
            text = ("Rebuild the drawing from the case study? "
                    + ("The designer's changes that were not applied will be lost. " if dirty else "")
                    + ("Blocks drawn by hand will be removed." if has_free else ""))
            if QMessageBox.question(self, "From case study", text.strip()) \
                    != QMessageBox.StandardButton.Yes:
                return False
        self._start_session(scn)
        self.view.fit_content()
        self._autogen_done = True
        return True

    def _start_session(self, scn) -> None:
        self.session = P.DesignSession(scn, self._library)
        res = self.session.results
        self._base_att = P.attribute(res) if res is not None else None
        self._case_changed = False
        self._curve_key = None
        self._log_sig = None
        fs = flowsheet_from_scenario(self.session.scenario, res)
        self.scene.set_flowsheet(fs)          # re-annotates through graphChanged
        self.btn_palette.setChecked(False)
        self._set_case_subtitle()
        self._show_selection(None)

    def maybe_autogenerate(self) -> None:
        """Called whenever the tab is shown: build the drawing the first time, and
        follow the case study when it changed on the Scenario tab."""
        if self._scenario_source is None:
            return
        if self.session is None:
            if not self._autogen_done and self._is_pristine():
                self.generate_from_scenario(confirm=False)
            return
        scn, _ = self._current_scenario()
        if scn is None:
            return
        try:
            same = scn == self.session.baseline
        except Exception:
            same = False
        if same:
            if self._case_changed:
                self._case_changed = False
                self._update_banner()
            return
        if not self.session.is_dirty:
            self._reload_case(scn)
        else:
            self._case_changed = True
            self._update_banner()

    def _reload_case(self, scn=None):
        if scn is None:
            scn, _ = self._current_scenario()
            if scn is None:
                return
        selected = self._selected_role()
        self.session.rebase(scn)
        res = self.session.results
        self._base_att = P.attribute(res) if res is not None else None
        self._case_changed = False
        self._curve_key = None
        self._log_sig = None
        if not self._sync_topology():
            self.solve_and_annotate()
        self._set_case_subtitle()
        self._reselect(selected)

    def apply_to_case(self):
        if self.session is None or self._scenario_sink is None:
            return
        if self.session.results is None:
            QMessageBox.warning(self, "Apply to case study",
                                "The designer's current point is not admissible, so it cannot "
                                "become the case study. Undo the last change or fix the input "
                                "marked in red first.")
            return
        import copy

        selected = self._selected_role()
        self._scenario_sink(copy.deepcopy(self.session.scenario))
        scn, _ = self._current_scenario()
        if scn is not None:
            self.session.rebase(scn)
            res = self.session.results
            self._base_att = P.attribute(res) if res is not None else None
        self._case_changed = False
        self._log_sig = None
        self._curve_key = None
        self.solve_and_annotate()
        self._set_case_subtitle()
        self._reselect(selected)
        self._flash("Applied: the case study now uses the designer's values.")

    def reset_to_case(self):
        if self.session is None or not self.session.is_dirty:
            return
        self.session.reset()
        self._session_changed("reset")

    def undo(self):
        if self.session is not None and self.session.undo():
            self._session_changed("undo")

    def redo(self):
        if self.session is not None and self.session.redo():
            self._session_changed("redo")

    # ------------------------------------------------------------------ #
    # Session edits
    # ------------------------------------------------------------------ #
    def _role_label(self, var: P.Variable) -> str:
        kind, nid = self.inspector.mode
        node = self.scene.flowsheet.nodes.get(nid) if nid else None
        if node is not None and node.role:
            return node.tag
        return "Plant" if kind == "plant" else ""

    def _on_variable_edited(self, var: P.Variable, value: float, fresh: bool):
        if self.session is None:
            return
        if self.session.set_value(var, value, label=self._role_label(var), coalesce=not fresh):
            self._session_changed(var.path)

    def _on_variable_reset(self, var: P.Variable):
        if self.session is None:
            return
        base = self.session.baseline_value(var.path)
        if base is not None and self.session.set_value(var, base, label=self._role_label(var),
                                                       coalesce=False):
            self._session_changed(var.path)

    def _on_technology(self, role: str, name: str):
        if self.session is None:
            return
        opts = P.technology_options(role, self.session.scenario, self._library)
        if opts is None or opts[0] == name:
            return
        self.session.set_technology(role, name)
        self._session_changed("tech:" + P.role_base(role), rebuild_inspector=True)

    def _session_changed(self, key: str, rebuild_inspector: bool = False):
        if self._focus is None or key != self._focus.path:
            self._curve_key = None
        kind, nid = self.inspector.mode
        selected = self._selected_role()
        if not self._sync_topology():
            self.solve_and_annotate()
        fs = self.scene.flowsheet
        if kind == "free":
            if nid not in fs.nodes:
                self._show_selection(None)
        elif selected in ("", P.PLANT):
            if rebuild_inspector or self._inspector_needs_rebuild(None):
                self._show_selection(None)
            else:
                self._refresh_inspector()
        else:
            node = self._node_for_role(selected)
            if node is None:
                self._show_selection(None)
            elif self.inspector.mode[1] != node.id:
                self._reselect(selected)
            elif rebuild_inspector or self._inspector_needs_rebuild(node):
                self._show_selection(node.id)
            else:
                self._refresh_inspector()
        self._schedule_analysis()

    def _inspector_needs_rebuild(self, node) -> bool:
        if self.session is None or self.inspector.is_editing():
            return False
        return self.inspector.needs_rebuild(self._context(), node)

    # ------------------------------------------------------------------ #
    # Drawing <-> scenario
    # ------------------------------------------------------------------ #
    def _drawn(self):
        """Results the drawing shows: the current point, or the last admissible one."""
        if self.session is None:
            return None
        return self.session.results or self.session.last_good()

    def _sync_topology(self) -> bool:
        """Rebuild the drawing when the equipment list changed (technology swap,
        undo over one, batch mode). Returns True if it rebuilt."""
        if self.session is None:
            return False
        drawn = self._drawn()
        scn = drawn.scenario if drawn is not None else self.session.scenario
        new_fs = flowsheet_from_scenario(scn, drawn)
        cur = self.scene.flowsheet

        def sig(fs):
            return sorted((n.role, n.kind) for n in fs.nodes.values() if n.role)

        if sig(new_fs) == sig(cur):
            return False
        if {r for r, _k in sig(new_fs)} == {r for r, _k in sig(cur)}:
            # same blocks, other equipment: keep wherever the user put them
            pos = {n.role: (n.x, n.y) for n in cur.nodes.values() if n.role}
            for n in new_fs.nodes.values():
                if n.role in pos:
                    n.x, n.y = pos[n.role]
        self._carry_free_blocks(cur, new_fs)
        self.scene.set_flowsheet(new_fs)
        return True

    @staticmethod
    def _carry_free_blocks(old: M.Flowsheet, new: M.Flowsheet) -> None:
        free = [n for n in old.nodes.values() if not n.role]
        if not free:
            return
        ids = {}
        for n in free:
            nn = new.add_node(n.kind, n.x, n.y, n.name)
            nn.params = dict(n.params)
            ids[n.id] = nn.id
        old_role = {n.id: n.role for n in old.nodes.values() if n.role}
        new_id = {n.role: n.id for n in new.nodes.values() if n.role}
        for lk in old.links.values():
            if lk.src_node not in ids and lk.dst_node not in ids:
                continue
            s = ids.get(lk.src_node) or new_id.get(old_role.get(lk.src_node, ""))
            d = ids.get(lk.dst_node) or new_id.get(old_role.get(lk.dst_node, ""))
            if s and d:
                new.add_link(s, lk.src_port, d, lk.dst_port)

    def _status_map(self, scn, issues) -> dict:
        roles = sorted({P.role_base(n.role) for n in self.scene.flowsheet.nodes.values() if n.role})
        out: dict = {}
        for iss in issues:
            level = "error" if iss.is_error else "warning"
            for owner in P.owner_roles(iss.field, scn, roles + [P.PLANT]):
                cur = out.get(owner)
                if cur is None:
                    out[owner] = (level, [iss.message])
                else:
                    worst = "error" if "error" in (cur[0], level) else "warning"
                    out[owner] = (worst, cur[1] + [iss.message])
        return out

    # ------------------------------------------------------------------ #
    # Solve + annotate
    # ------------------------------------------------------------------ #
    def solve_and_annotate(self):
        fs = self.scene.flowsheet
        drawn = self._drawn()
        if drawn is not None:
            seed_flows(fs, drawn.scenario, drawn)
        result = M.solve(fs)
        self._solve = result
        self._att = P.attribute(drawn) if drawn is not None else None
        self._status = (self._status_map(self.session.scenario, self.session.issues)
                        if self.session is not None else {})

        self._stream_no = {lid: i + 1 for i, lid in enumerate(fs.links)}
        totals = {lid: M.flow_total(result.stream_flows.get(lid, M.empty_flow())) for lid in fs.links}
        fmax = max(totals.values(), default=0.0)
        for lid, edge in self.scene.edge_items.items():
            flow = result.stream_flows.get(lid, M.empty_flow())
            src = fs.nodes.get(edge.link.src_node)
            kind = P.stream_class(flow, edge.link.src_port, src.role if src is not None else "")
            total = totals.get(lid, 0.0)
            edge.set_stream(self._stream_no.get(lid, 0), P.fmt_rate(total) if total > 0 else "",
                            flow, kind, _stream_width(total, fmax))
            edge.update_path()

        for nid, item in self.scene.node_items.items():
            node = item.node
            if node.role and drawn is not None:
                item.set_readout(P.faceplate(node.role, drawn, self._att))
                u = self._att.units.get(P.role_base(node.role))
                first = node.role == P.role_base(node.role)
                item.set_parallel(u.units_parallel if u is not None and first else 0)
            else:
                item.set_readout(self._free_readout(nid, result))
                item.set_parallel(0)
            if node.role and self.session is not None:
                level, msgs = self._status.get(P.role_base(node.role), ("ok", []))
                item.set_status(level, "; ".join(msgs[:2]))
            else:
                item.set_status("idle")
        self._apply_layer()
        self._update_utilities()
        self._update_sheet()
        self._refresh_panels()
        self.scene.refresh_decor()

    def _free_readout(self, node_id: str, result: M.SolveResult):
        node = self.scene.flowsheet.nodes[node_id]
        if not node.spec.outputs:
            agg = M.empty_flow()
            for lk in self.scene.flowsheet.links.values():
                if lk.dst_node == node_id:
                    agg = M.flow_add(agg, result.stream_flows.get(lk.id, M.empty_flow()))
            return [[("", "← " + P.fmt_rate(M.flow_total(agg)))]]
        outs = result.node_outputs.get(node_id, {})
        return [[("", "Σ " + P.fmt_rate(sum(M.flow_total(f) for f in outs.values())))]]

    def _throughput(self, node_id: str) -> float:
        if self._solve is None:
            return 0.0
        outs = self._solve.node_outputs.get(node_id, {})
        total = sum(M.flow_total(f) for f in outs.values())
        if total <= 0:
            for lk in self.scene.flowsheet.links.values():
                if lk.dst_node == node_id:
                    total += M.flow_total(self._solve.stream_flows.get(lk.id, M.empty_flow()))
        return total

    # -- overlay layer -------------------------------------------------- #
    def set_layer(self, layer: str):
        self._layer = layer
        btn = self.layer_btns.get(layer)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        self._apply_layer()
        self._update_sheet()

    def _layer_values(self) -> dict[str, float]:
        att, layer = self._att, self._layer
        out: dict[str, float] = {}
        if layer == "none":
            return out
        for nid, item in self.scene.node_items.items():
            role = item.node.role
            if layer == "mass":
                out[nid] = self._throughput(nid)
                continue
            if att is None or not role or role != P.role_base(role):
                continue
            u = att.units.get(role)
            if u is None:
                continue
            out[nid] = {"energy": u.power_kw + u.heat_kw, "cost": u.annual_cost, "gwp": u.gwp}[layer]
        return out

    def _apply_layer(self):
        t = self.scene.theme
        layer = self._layer
        values = self._layer_values()
        vmax = max((abs(v) for v in values.values()), default=0.0)
        for nid, item in self.scene.node_items.items():
            v = values.get(nid, 0.0)
            if layer == "none" or not v or vmax <= 0:
                item.set_overlay(0.0, None, "")
                continue
            if layer == "mass":
                k = math.log1p(v) / math.log1p(vmax)
                badge = P.fmt_rate(v)
            else:
                k = abs(v) / vmax
                if layer == "energy":
                    badge = P.fmt_power(v)
                elif layer == "cost":
                    badge = f"{self._att.share(item.node.role, 'annual_cost') * 100:,.0f} %"
                else:
                    badge = f"{v:+,.2f}"
            color = t.credit if (layer == "gwp" and v < 0) else t.layer[layer]
            item.set_overlay(k, color, badge)
        # area totals on the frames
        metrics = {}
        att = self._att
        if att is not None and layer in ("cost", "gwp", "energy"):
            for sec in P.SECTIONS:
                if layer == "cost":
                    tot = att.section_total(sec, "annual_cost")
                    share = tot / att.annual_opex if att.annual_opex else 0.0
                    text = f"{P.fmt_money(tot)}/yr · {share * 100:,.0f} %" if tot else ""
                elif layer == "gwp":
                    tot = att.section_total(sec, "gwp")
                    share = abs(tot) / (abs(att.gwp) or 1.0)
                    text = f"{tot:+,.2f} kg CO₂-eq/kg" if tot else ""
                else:
                    tot = att.section_total(sec, "power_kw") + att.section_total(sec, "heat_kw")
                    allp = sum(u.power_kw + u.heat_kw for u in att.units.values()) or 1.0
                    share = tot / allp
                    text = P.fmt_power(tot) if tot else ""
                metrics[sec.code] = (text, min(1.0, share))
        self.scene.set_section_metrics(metrics)

    def _layer_scale(self):
        layer = self._layer
        if layer == "none":
            return None
        values = list(self._layer_values().values())
        if not values:
            return None
        color = self.scene.theme.layer[layer]
        hi = max(values)
        lo = min(values)
        if layer == "mass":
            return ("mass handled", "small", P.fmt_rate(hi), color)
        if layer == "energy":
            return ("electric + heat", "0", P.fmt_power(hi), color)
        if layer == "cost":
            return ("operating cost", "0", P.fmt_money(hi) + "/yr", color)
        return ("GWP per kg DW", f"{min(lo, 0.0):+,.2f}", f"{hi:+,.2f}", color)

    def _update_utilities(self):
        att = self._att
        loads, tp, th = {}, 0.0, 0.0
        if att is not None:
            for nid, item in self.scene.node_items.items():
                role = item.node.role
                if not role or role != P.role_base(role):
                    continue
                u = att.units.get(role)
                if u is None:
                    continue
                d = {}
                if u.power_kw > 0:
                    d["power"] = P.fmt_power(u.power_kw)
                    tp += u.power_kw
                if u.heat_kw > 0:
                    d["heat"] = P.fmt_power(u.heat_kw)
                    th += u.heat_kw
                if d:
                    loads[nid] = d
        self.scene.set_utility_loads(loads, {"power": P.fmt_power(tp), "heat": P.fmt_power(th) + " th"})

    def _update_sheet(self):
        drawn = self._drawn()
        if drawn is not None:
            scn = drawn.scenario
            from algametrix.models import Basis

            unit = "m²" if scn.system.basis == Basis.AREA else "m³"
            mp = drawn.main_product
            if mp is not None:
                product = f"{mp.name}: {mp.annual_kg / 1000:,.1f} t/yr"
            else:
                product = f"dry biomass: {drawn.inventory.annual_biomass_kg / 1000:,.1f} t/yr"
            hours = max(scn.system.operating_days, 1.0) * 24.0
            info = {"title": f"{scn.organism.name} — {scn.system.name}",
                    "subtitle": f"{product}  ·  {scn.scale:,.0f} {unit}  ·  "
                                f"{'batch' if scn.batch_mode else 'continuous'}",
                    "drawing": "PFD-001",
                    "rev": "A · draft" if self.session.is_dirty else "A",
                    "date": date.today().isoformat(),
                    "basis": f"kg/h · {hours:,.0f} h/yr"}
        else:
            info = {"title": "Sketch", "subtitle": "drawn by hand · sketch mass balance",
                    "drawing": "SK-001", "rev": "—", "date": date.today().isoformat(),
                    "basis": "kg/h"}
        kinds = sorted({e.kind for e in self.scene.edge_items.values() if e.kind != "empty"})
        self.scene.set_sheet_info(info, kinds, self._layer_scale())

    # ------------------------------------------------------------------ #
    # Panels
    # ------------------------------------------------------------------ #
    def _refresh_panels(self):
        linked = self.session is not None
        self.kpi_bar.setVisible(linked)
        if linked:
            self._update_kpis()
        self._update_charts()
        self._table_dirty = True
        if self.dock.currentWidget() is self.stream_table:
            self._update_stream_table()
        self._update_log()
        self._update_banner()
        self._update_buttons()

    def _update_kpis(self):
        st = self.session.state
        hist = self.session.history
        for key, tile in self.tiles.items():
            if st.kpis is None:
                tile.set_unavailable("not admissible")
                continue
            base = self.session.baseline_kpis.get(key) if self.session.baseline_kpis else None
            tile.set_data(st.kpis[key], base, [s.kpis[key] for s in hist if s.kpis])

    def _chart_rows(self):
        """``[(role, label, colour)]`` in plant-area order, for roles the engine costs."""
        att = self._att
        if att is None:
            return []
        tags = {}
        for n in self.scene.flowsheet.nodes.values():
            if n.role and n.role == P.role_base(n.role):
                tags.setdefault(n.role, n.tag)
        rows = []
        for sec in P.SECTIONS:
            for role in sec.roles:
                if role in att.units:
                    label = P.ROLE_LABELS.get(role, role)
                    if role in tags:
                        label = f"{tags[role]}  {label}"
                    rows.append((role, label, sec.color))
        if P.PLANT in att.units:
            rows.append((P.PLANT, "Plant-wide (labour, overhead, other)", "#7c3aed"))
        return rows

    def _update_charts(self):
        att, base = self._att, self._base_att
        if att is None:
            msg = "Build the drawing from the case study to see each block's share."
            for chart in (self.cost_chart, self.gwp_chart, self.energy_chart):
                chart.set_data([], [], note=msg)
            return
        rows_c, rows_g, rows_e = [], [], []
        for role, label, color in self._chart_rows():
            u = att.units[role]
            b = base.units.get(role) if base is not None else None
            parts: dict[str, float] = {}
            for line, v in u.cost_items.items():
                cat = _cost_cat(line, role)
                parts[cat] = parts.get(cat, 0.0) + v
            if any(parts.values()):
                rows_c.append((label, color, parts, b.annual_cost if b is not None else None))
            gparts: dict[str, float] = {}
            for line, v in u.gwp_items.items():
                cat = _gwp_cat(line, role)
                gparts[cat] = gparts.get(cat, 0.0) + v
            if any(gparts.values()):
                rows_g.append((label, color, gparts, b.gwp if b is not None else None))
            if u.power_kw or u.heat_kw:
                rows_e.append((label, color, {"power": u.power_kw, "heat": u.heat_kw},
                               (b.power_kw + b.heat_kw) if b is not None else None))
        self.cost_chart.set_data(rows_c, _COST_CATS, "€ per year",
                                 lambda v: P.fmt_money(v) + "/yr",
                                 note=f"total {P.fmt_money(att.annual_opex)}/yr")
        self.gwp_chart.set_data(rows_g, _GWP_CATS, "kg CO₂-eq per kg dry biomass, before allocation",
                                lambda v: f"{v:+,.3f}", note=f"net {att.gwp:+,.3f} kg CO₂-eq/kg")
        tot_p = sum(u.power_kw for u in att.units.values())
        tot_h = sum(u.heat_kw for u in att.units.values())
        self.energy_chart.set_data(rows_e, _ENERGY_CATS, "kW (heat as kW thermal)", P.fmt_power,
                                   note=f"{P.fmt_power(tot_p)} electric · {P.fmt_power(tot_h)} heat")

    def _update_stream_table(self):
        fs, res = self.scene.flowsheet, self._solve
        self._table_dirty = False
        if res is None:
            return
        table = self.stream_table
        table.blockSignals(True)
        table.setRowCount(len(fs.links))
        theme = self.scene.theme
        for r, (lid, lk) in enumerate(fs.links.items()):
            flow = res.stream_flows.get(lid, M.empty_flow())
            total = M.flow_total(flow)
            src, dst = fs.nodes.get(lk.src_node), fs.nodes.get(lk.dst_node)
            edge = self.scene.edge_items.get(lid)
            kind = edge.kind if edge is not None else "empty"
            bio, water = flow.get("biomass", 0.0), flow.get("water", 0.0)
            ds = f"{bio / (bio + water) * 100:,.2f}" if bio > 0 and bio + water > 0 else ""
            cells = [str(self._stream_no.get(lid, r + 1)),
                     f"{src.tag if src else '?'} · {lk.src_port}",
                     f"{dst.tag if dst else '?'} · {lk.dst_port}",
                     STREAM_LABELS.get(kind, "—"), f"{total:,.1f}"]
            cells += [f"{flow.get(c, 0.0):,.1f}" if flow.get(c, 0.0) else "" for c in M.COMPONENTS]
            cells.append(ds)
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setData(Qt.UserRole, lid)
                    it.setTextAlignment(Qt.AlignCenter)
                elif c >= 4:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3:
                    it.setForeground(QColor(theme.stream.get(kind, theme.stream["empty"])))
                table.setItem(r, c, it)
        table.blockSignals(False)

    def _update_log(self):
        if self.session is None:
            if self.log_list.count():
                self.log_list.clear()
            self._log_sig = None
            return
        states = self.session.all_states
        sig = (len(states), self.session.position, id(states[-1]), states[-1].label)
        if sig == self._log_sig:
            return
        self._log_sig = sig
        self.log_list.clear()
        prev = None
        for i, st in enumerate(states):
            text = f"{i:>3}   {st.label}"
            if st.kpis is not None and prev is not None and prev.kpis is not None and prev.kpis["cost"]:
                d = (st.kpis["cost"] - prev.kpis["cost"]) / abs(prev.kpis["cost"]) * 100
                text += f"      cost {d:+.1f} %"
            elif st.kpis is None:
                text += "      not admissible"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, i)
            if i == self.session.position:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setForeground(QColor("#14532d"))
                it.setText("▶" + text[1:])
            elif i > self.session.position:
                it.setForeground(QColor("#a8b4c0"))
            self.log_list.addItem(it)
            prev = st
        self.log_list.scrollToItem(self.log_list.item(self.session.position))

    def _change_count(self) -> int:
        if self.session is None:
            return 0
        n = len(self.session.changed_paths())
        a, b = self.session.scenario, self.session.baseline
        for x, y in ((a.system.name, b.system.name), (a.harvesting.name, b.harvesting.name),
                     (a.drying.name, b.drying.name), (a.extraction.name, b.extraction.name)):
            if x != y:
                n += 1
        return n

    def _set_banner(self, kind: str, html: str, buttons=()):
        colors = {"info": ("#eff6ff", "#bfdbfe", "#1e3a5f"), "warn": ("#fffbeb", "#fcd34d", "#78350f"),
                  "error": ("#fef2f2", "#fca5a5", "#7f1d1d"), "ok": ("#f0fdf4", "#86efac", "#14532d")}
        bg, border, ink = colors[kind]
        self.banner.setStyleSheet(
            f"#banner{{background:{bg}; border:1px solid {border}; border-radius:6px;}}"
            f"#banner QLabel{{color:{ink}; font-size:11px;}}"
            f"#banner QPushButton{{background:#ffffff; color:{ink}; border:1px solid {border};"
            f" border-radius:4px; padding:3px 10px; font-weight:600;}}"
            f"#banner QPushButton:hover{{background:{border};}}")
        self.banner_text.setText(html)
        for i, b in enumerate(self.banner_btns):
            if i < len(buttons):
                text, slot = buttons[i]
                b.setText(text)
                self._banner_actions[i] = slot
                b.setVisible(True)
            else:
                self._banner_actions[i] = None
                b.setVisible(False)
        self.banner.setVisible(True)

    def _banner_click(self, i: int):
        action = self._banner_actions[i]
        if action is not None:
            action()

    def _update_banner(self):
        s = self.session
        if s is None:
            if self._scenario_source is not None:
                self._set_banner("info", "<b>Sketch mode.</b> This drawing is not linked to the case "
                                 "study: its balance is the sketch solver's. Build it from the case "
                                 "study to tune the process against the TEA/LCA engine.",
                                 [("Build from case study", lambda: self.generate_from_scenario())])
            else:
                self.banner.setVisible(False)
            return
        if s.results is None:
            errors = [i.message for i in s.issues if i.is_error]
            msg = errors[0] if errors else "the engine refused the inputs"
            self._set_banner("error", f"<b>Not computed:</b> {msg} The drawing shows the last "
                             "admissible point; the block concerned is marked red.",
                             [("Undo", self.undo)])
            return
        if self._case_changed:
            self._set_banner("info", "<b>The case study changed</b> on the Scenario tab since the "
                             "designer loaded it.",
                             [("Reload from case", self._reload_case)])
            return
        n = self._change_count()
        if s.is_dirty and n:
            self._set_banner("warn", f"<b>{n} change{'s' if n != 1 else ''}</b> in the designer, "
                             "not yet in the case study. The Scenario tab and the exports still "
                             "use the case as it was.",
                             [("Apply to case study", self.apply_to_case),
                              ("Discard", self.reset_to_case)])
            return
        self.banner.setVisible(False)

    def _update_buttons(self):
        s = self.session
        self.btn_undo.setEnabled(s is not None and s.can_undo())
        self.btn_redo.setEnabled(s is not None and s.can_redo())
        dirty = s is not None and s.is_dirty and self._change_count() > 0
        self.btn_apply.setEnabled(dirty and self._scenario_sink is not None and s.results is not None)
        self.btn_reset.setEnabled(dirty)

    def _flash(self, text: str):
        win = self.window()
        bar = getattr(win, "statusBar", None)
        if callable(bar):
            bar().showMessage(text, 7000)
        else:
            self.pfd_subtitle.set_full_text(text)

    def _set_case_subtitle(self):
        if self.session is None:
            self.pfd_subtitle.set_full_text("")
            return
        scn = self.session.baseline
        op = "batch" if scn.batch_mode else "continuous"
        self.pfd_subtitle.set_full_text(f"Linked to the case study:  {scn.organism.name}  ·  "
                                  f"{scn.system.name}  ·  {op}")

    # ------------------------------------------------------------------ #
    # Analysis around the operating point (debounced)
    # ------------------------------------------------------------------ #
    def _schedule_analysis(self):
        if self.session is not None:
            self._analysis_timer.start()

    def _run_analysis(self):
        s = self.session
        if s is None:
            return
        if s.results is None:
            self.inspector.set_elasticities({v.path: (None, None) for v in self.inspector.variables()})
            self.inspector.response.clear("Not computed at this point.")
            return
        scn = s.scenario
        self.inspector.set_elasticities({v.path: P.elasticity(scn, v) for v in self.inspector.variables()})
        self._update_response(force=False)
        if self.dock.currentWidget() is self._drivers_page:
            self._update_tornado()

    def _on_variable_focused(self, var: P.Variable):
        if self._focus is None or self._focus.path != var.path:
            self._focus = var
            self._curve_key = None
            self._update_response(force=True)

    def _update_response(self, force: bool):
        s, var = self.session, self._focus
        if s is None or var is None:
            return
        if s.results is None:
            self.inspector.response.clear("Not computed at this point.")
            return
        try:
            x_now = P.get_value(s.scenario, var.path)
        except (AttributeError, IndexError):
            return
        key = (var.path,)
        if force or self._curve_key != key:
            self._curve_points = P.response_curve(s.scenario, var)
            self._curve_key = key
        self.inspector.response.set_curve(var, self._curve_points, x_now, s.baseline_value(var.path))

    def _update_tornado(self):
        s = self.session
        if s is None or s.results is None:
            self.tornado.set_message("Build the drawing from the case study to rank the inputs.")
            return
        scn = s.scenario
        roles = sorted({P.role_base(n.role) for n in self.scene.flowsheet.nodes.values() if n.role})
        variables = P.all_variables(scn, roles)
        rows = []
        for var, lo, hi in P.tornado(scn, variables, 0.2)[:18]:
            owners = P.owner_roles(var.path, scn, roles + [P.PLANT])
            owner = P.ROLE_LABELS.get(owners[0], "") if owners else ""
            if owner.startswith("Plant-wide"):
                owner = "Plant"
            rows.append((f"{owner} · {var.label}" if owner else var.label, lo, hi))
        self.tornado.set_data(rows, P.headline(s.results)[0], 0.2)

    def _on_dock_tab(self, _index: int):
        w = self.dock.currentWidget()
        if w is self.stream_table and self._table_dirty:
            self._update_stream_table()
        elif w is self._drivers_page:
            self._update_tornado()

    # ------------------------------------------------------------------ #
    # Selection -> inspector
    # ------------------------------------------------------------------ #
    def _context(self) -> Context:
        s = self.session
        return Context(session=s, results=s.results if s else None, drawn=self._drawn(),
                       att=self._att, status=self._status, library=self._library,
                       streams_for=self._node_streams)

    def _selected_role(self) -> str:
        kind, nid = self.inspector.mode
        node = self.scene.flowsheet.nodes.get(nid) if nid else None
        if kind == "plant":
            return P.PLANT
        return node.role if node is not None else ""

    def _node_for_role(self, role: str):
        if not role or role == P.PLANT:
            return None
        return next((n for n in self.scene.flowsheet.nodes.values() if n.role == role), None)

    def _reselect(self, role: str):
        node = self._node_for_role(role)
        if node is not None:
            self.scene.select_node(node.id)
            self._show_selection(node.id)
        else:
            self._show_selection(None)

    def _on_node_selected(self, node_id):
        self._show_selection(node_id)

    def _show_selection(self, node_id):
        fs = self.scene.flowsheet
        node = fs.nodes.get(node_id) if node_id else None
        if node is None:
            if self.session is not None:
                self.inspector.show_plant(self._context())
                self._default_focus(P.variables_for(P.PLANT, self.session.scenario))
            else:
                self.inspector.show_empty("Select a block on the canvas to inspect it, or build "
                                          "the drawing from the case study to link it to the engine.")
            return
        if node.role and self.session is not None:
            self.inspector.show_linked(node, self._context())
            self._default_focus(P.variables_for(node.role, self.session.scenario))
        else:
            self.inspector.show_free(node, self._node_streams(node.id))
        self._schedule_analysis()

    def _default_focus(self, variables):
        if not variables:
            self.inspector.response.clear("This block has no variables of its own.")
            self._focus = None
            return
        keep = self._focus is not None and any(v.path == self._focus.path for v in variables)
        if not keep:
            self._focus = variables[0]
            self._curve_key = None
        self._update_response(force=False)

    def _refresh_inspector(self):
        if self.session is None:
            return
        kind, nid = self.inspector.mode
        node = self.scene.flowsheet.nodes.get(nid) if nid else None
        if kind in ("linked", "plant"):
            self.inspector.refresh(self._context(), node)

    def _node_streams(self, node_id: str):
        fs, res = self.scene.flowsheet, self._solve
        node = fs.nodes.get(node_id)
        if node is None or res is None:
            return []
        rows = []
        for port in node.spec.inputs:
            lk = next((lk for lk in fs.links.values() if lk.dst_node == node_id and lk.dst_port == port), None)
            if lk is None:
                rows.append((0, "in", port, "—", "open"))
                continue
            flow = res.stream_flows.get(lk.id, M.empty_flow())
            other = fs.nodes[lk.src_node].tag if lk.src_node in fs.nodes else "?"
            rows.append((self._stream_no.get(lk.id, 0), "in", port, other, P.fmt_rate(M.flow_total(flow))))
        outs = res.node_outputs.get(node_id, {})
        for port in node.spec.outputs:
            lk = next((lk for lk in fs.links.values() if lk.src_node == node_id and lk.src_port == port), None)
            flow = outs.get(port, M.empty_flow())
            other = fs.nodes[lk.dst_node].tag if lk is not None and lk.dst_node in fs.nodes else "—"
            rows.append((self._stream_no.get(lk.id, 0) if lk is not None else 0, "out", port, other,
                         P.fmt_rate(M.flow_total(flow))))
        return rows

    def _on_edge_selected(self, link_id):
        if link_id is None or self.dock.currentWidget() is not self.stream_table:
            return
        for r in range(self.stream_table.rowCount()):
            it = self.stream_table.item(r, 0)
            if it is not None and it.data(Qt.UserRole) == link_id:
                self.stream_table.blockSignals(True)
                self.stream_table.selectRow(r)
                self.stream_table.blockSignals(False)
                break

    def _on_table_selection(self):
        rows = self.stream_table.selectionModel().selectedRows()
        if not rows:
            return
        it = self.stream_table.item(rows[0].row(), 0)
        lid = it.data(Qt.UserRole) if it is not None else None
        edge = self.scene.edge_items.get(lid)
        if edge is not None:
            self.scene.blockSignals(True)
            self.scene.select_edge(lid)
            self.scene.blockSignals(False)
            self.view.centerOn(edge.path().pointAtPercent(0.5))

    def _on_log_clicked(self, item: QListWidgetItem):
        if self.session is None:
            return
        idx = item.data(Qt.UserRole)
        if idx is not None and idx != self.session.position:
            self.session.jump(int(idx))
            self._session_changed("jump")

    # ------------------------------------------------------------------ #
    # Canvas options
    # ------------------------------------------------------------------ #
    def _toggle(self, key: str, on: bool):
        if key == "areas":
            self.scene.set_show_sections(on)
        elif key == "utilities":
            self.scene.set_show_utilities(on)
        elif key == "labels":
            self.scene.set_show_labels(on)
        elif key == "flow":
            self.scene.set_animation(on)
        elif key == "sheet":
            self.scene.set_show_sheet(on)
        elif key == "map":
            self.view.set_minimap_visible(on)

    def _toggle_boxes(self, checked: bool):
        """Flip between the boxed-card and the boxless PFD rendering."""
        NodeItem.BOXLESS = not checked
        for item in self.scene.node_items.values():
            item.update()
        self.view.viewport().update()

    def _set_palette_visible(self, on: bool):
        self.palette_box.setVisible(on)
        if self.btn_palette.isChecked() != on:
            self.btn_palette.setChecked(on)

    def showEvent(self, event):
        super().showEvent(event)
        self.scene.pause_animation(False)
        self.palette_box.setVisible(self.btn_palette.isChecked())
        self._fit_canvas_bar()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.scene.pause_animation(True)

    # ------------------------------------------------------------------ #
    # Hand-drawn blocks
    # ------------------------------------------------------------------ #
    def _palette_add(self, item: QListWidgetItem):
        kind = item.data(Qt.UserRole)
        if not kind:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self._add_offset = (self._add_offset + 1) % 6
        pos = QPointF(center.x() - 84 + self._add_offset * 18, center.y() - 40 + self._add_offset * 18)
        self.scene.add_node(kind, pos)

    def _rename(self, node_id: str, text: str):
        node = self.scene.flowsheet.nodes.get(node_id)
        if node is None:
            return
        node.name = text
        item = self.scene.node_item(node_id)
        if item is not None:
            item._refresh_tooltip()
            item.update()

    def _set_param(self, node_id: str, key: str, value: float):
        node = self.scene.flowsheet.nodes.get(node_id)
        if node is None:
            return
        node.params[key] = float(value)
        self.solve_and_annotate()

    def _delete_node(self, node_id: str):
        item = self.scene.node_item(node_id)
        if item is not None:
            self.scene.clearSelection()
            item.setSelected(True)
            self.scene.delete_selected()
        self._show_selection(None)

    def _stream_card(self, edge):
        fs = self.scene.flowsheet
        lk = edge.link
        src, dst = fs.nodes.get(lk.src_node), fs.nodes.get(lk.dst_node)
        num = self._stream_no.get(lk.id, 0)
        title = f"Stream {num}   {src.tag if src else '?'} → {dst.tag if dst else '?'}"
        flow = edge.flow or {}
        total = M.flow_total(flow)
        rows = [("Mass flow", P.fmt_rate(total))]
        for comp in M.COMPONENTS:
            v = flow.get(comp, 0.0)
            if v > 0 and total > 0:
                rows.append((_COMPONENT_LABELS[comp], f"{P.fmt_rate(v)}   {v / total * 100:,.1f} %"))
        bio, water = flow.get("biomass", 0.0), flow.get("water", 0.0)
        if bio > 0 and bio + water > 0:
            rows.append(("Dry solids", f"{bio / (bio + water) * 100:,.2f} %"))
        if water > 0:
            rows.append(("Liquid volume", f"≈ {water / 1000:,.2f} m³/h"))
        if src is not None and dst is not None:
            rows.append(("Ports", f"{src.tag}.{lk.src_port} → {dst.tag}.{lk.dst_port}"))
        return title, rows

    # ------------------------------------------------------------------ #
    # File / lifecycle
    # ------------------------------------------------------------------ #
    def save_flowsheet(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save drawing", "flowsheet.flow.json", "Flowsheet (*.flow.json *.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.scene.flowsheet.to_dict(), indent=2), encoding="utf-8")

    def load_flowsheet(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load drawing", "", "Flowsheet (*.flow.json *.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            fs = M.Flowsheet.from_dict(data)
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", f"Could not read the drawing:\n{exc}")
            return
        if self.session is None or not any(n.role for n in fs.nodes.values()):
            self.session = None
        self.scene.set_flowsheet(fs)
        self._show_selection(None)
        self.view.fit_content()

    def load_example(self):
        self.session = None
        self._set_case_subtitle()
        self.scene.set_flowsheet(M.starter_flowsheet())
        self.btn_palette.setChecked(True)
        self._show_selection(None)
        self.view.fit_content()

    def clear_flowsheet(self):
        if QMessageBox.question(self, "Clear canvas", "Remove all blocks and streams?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.session = None
        self._set_case_subtitle()
        self.scene.set_flowsheet(M.Flowsheet())
        self.btn_palette.setChecked(True)
        self._show_selection(None)

    def _is_pristine(self) -> bool:
        """True when the canvas still holds the built-in starter, unedited."""
        starter = M.starter_flowsheet()
        cur = self.scene.flowsheet
        return (sorted(n.kind for n in cur.nodes.values())
                == sorted(n.kind for n in starter.nodes.values()))

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #
    def _logo_pixmap(self):
        """Cached AlgaMetrix logo pixmap (empty if the asset is missing)."""
        if not hasattr(self, "_logo_pm"):
            from PySide6.QtGui import QPixmap

            from .. import resources

            p = resources.logo_path()
            self._logo_pm = QPixmap(p) if p else QPixmap()
        return self._logo_pm

    @contextmanager
    def _clean_render(self):
        """Selection and hover card set aside while rendering."""
        selected = self.scene.selectedItems()
        self.scene.blockSignals(True)
        self.scene.clearSelection()
        card = self.scene.card.isVisible()
        self.scene.card.setVisible(False)
        try:
            yield
        finally:
            self.scene.card.setVisible(card)
            for it in selected:
                it.setSelected(True)
            self.scene.blockSignals(False)

    def export_image(self, fmt: str = "png"):
        """Export the drawing as a high-resolution PNG or a vector PDF/SVG."""
        filters = {"png": "PNG image (*.png)", "pdf": "PDF document (*.pdf)", "svg": "SVG drawing (*.svg)"}
        path, _ = QFileDialog.getSaveFileName(self, "Export drawing", f"process_flow_diagram.{fmt}",
                                              filters.get(fmt, filters["png"]))
        if not path:
            return
        if not self.scene.node_items:
            QMessageBox.information(self, "Export", "The canvas is empty.")
            return
        try:
            with self._clean_render():
                rect = self.scene.export_rect()
                low = path.lower()
                if low.endswith(".pdf"):
                    self._render_pdf(path, rect)
                elif low.endswith(".svg"):
                    self._render_svg(path, rect)
                else:
                    self._render_png(path, rect, 3.0)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", f"Could not export the drawing:\n{exc}")

    def render_diagram_png(self, path: str, scale: float = 2.5) -> bool:
        """Render the current drawing to ``path`` (used by the PDF report). Returns
        False if the canvas is empty."""
        if not self.scene.node_items:
            return False
        with self._clean_render():
            self._render_png(path, self.scene.export_rect(), scale)
        return True

    def _render_png(self, path: str, rect: QRectF, scale: float = 2.0):
        w = max(1, int(rect.width() * scale))
        h = max(1, int(rect.height() * scale))
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(QColor(self.scene.theme.canvas))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.scene.render(painter, QRectF(0, 0, w, h), rect, Qt.KeepAspectRatio)
        painter.end()
        img.save(path)

    def _render_pdf(self, path: str, rect: QRectF):
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QPageSize

        writer = QPdfWriter(path)
        writer.setResolution(300)
        writer.setPageSize(QPageSize(QSizeF(rect.width() / 96.0, rect.height() / 96.0),
                                     QPageSize.Unit.Inch))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        painter = QPainter(writer)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillRect(QRectF(0, 0, writer.width(), writer.height()), QColor(self.scene.theme.canvas))
        self.scene.render(painter, QRectF(0, 0, writer.width(), writer.height()), rect, Qt.KeepAspectRatio)
        painter.end()

    def _render_svg(self, path: str, rect: QRectF):
        from PySide6.QtSvg import QSvgGenerator

        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(QSize(int(rect.width()), int(rect.height())))
        gen.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
        gen.setTitle("Process flow diagram")
        gen.setDescription("AlgaMetrix Process Designer")
        painter = QPainter(gen)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(QRectF(0, 0, rect.width(), rect.height()), QColor(self.scene.theme.canvas))
        self.scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), rect, Qt.KeepAspectRatio)
        painter.end()

    def export_streams_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export stream table", "streams.csv", "CSV (*.csv)")
        if not path:
            return
        if self._table_dirty:
            self._update_stream_table()
        t = self.stream_table
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([t.horizontalHeaderItem(c).text() for c in range(t.columnCount())])
            for r in range(t.rowCount()):
                w.writerow([(t.item(r, c).text() if t.item(r, c) else "").replace(",", "")
                            for c in range(t.columnCount())])
