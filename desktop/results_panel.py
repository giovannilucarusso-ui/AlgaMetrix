"""The results panel: one tab per question a reader asks of a case.

Builds the widgets onto the main window and returns the panel. The window's
render methods fill them in; this module only lays them out and gives each
page its empty state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from algametrix.comparison import KPI_ORDER
from algametrix.sensitivity import OUTPUTS, PARAMETERS

from . import report_panel, validation_panel
from .i18n import tr
from .widgets import EmptyState, KeyValueGrid, KpiCard, MplCanvas, button, label, make_table

(TAB_OVERVIEW, TAB_COSTS, TAB_LCA, TAB_INVENTORY, TAB_PRODUCTS, TAB_SENSITIVITY,
 TAB_UNCERTAINTY, TAB_COMPARE, TAB_VALIDATION, TAB_REPORT) = range(10)

TAB_TITLES = ("Overview", "Costs", "Life cycle", "Inventory", "Products", "Sensitivity",
              "Uncertainty", "Compare", "Validation", "Report")


def page(margins: int = 12, spacing: int = 10) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return w, lay


def scrollable(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(inner)
    return scroll


def basis_box() -> tuple[QFrame, QLabel]:
    """A quiet box that states what the numbers on the page are per."""
    box = QFrame()
    box.setObjectName("basisBox")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 8, 12, 8)
    lbl = QLabel("")
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(lbl)
    return box, lbl


def build(win) -> QWidget:
    panel = QWidget()
    panel.setObjectName("page")
    v = QVBoxLayout(panel)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    win.tabs = QTabWidget()
    win.tabs.setUsesScrollButtons(True)
    win.tabs.setElideMode(Qt.ElideNone)
    win.tabs.setFocusPolicy(Qt.TabFocus)
    builders = (_overview, _costs, _lca, _inventory, _products, _sensitivity, _uncertainty,
                _compare, validation_panel.build, report_panel.build)
    for title, make in zip(TAB_TITLES, builders):
        win.tabs.addTab(make(win), tr(title))
    win.tabs.setTabToolTip(TAB_OVERVIEW, "Headline numbers, their basis and the two breakdowns")
    win.tabs.setTabToolTip(TAB_COSTS, "Capital and operating cost, itemised")
    win.tabs.setTabToolTip(TAB_LCA, "Impact categories and where the GWP comes from")
    win.tabs.setTabToolTip(TAB_INVENTORY, "Foreground flows per kg of dry biomass")
    win.tabs.setTabToolTip(TAB_PRODUCTS, "Multi-product split and allocation")
    win.tabs.setTabToolTip(TAB_SENSITIVITY, "One input swept, one output followed")
    win.tabs.setTabToolTip(TAB_UNCERTAINTY, "Monte Carlo on the inputs you choose")
    win.tabs.setTabToolTip(TAB_COMPARE, "Snapshots of cases side by side")
    win.tabs.setTabToolTip(TAB_VALIDATION, "Reference cases, literature ranges, evidence classes")
    win.tabs.setTabToolTip(TAB_REPORT, "What the PDF report contains, and the exports")
    v.addWidget(win.tabs, 1)
    return panel


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def _overview(win) -> QWidget:
    inner, lay = page()

    # Inadmissible input is reported here and nowhere else: one banner, above
    # the numbers it is withholding.
    win.lbl_issues = QLabel("")
    win.lbl_issues.setObjectName("issueBanner")
    win.lbl_issues.setWordWrap(True)
    win.lbl_issues.setTextInteractionFlags(Qt.TextSelectableByMouse)
    win.lbl_issues.setVisible(False)
    lay.addWidget(win.lbl_issues)

    grid = QGridLayout()
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(10)
    win.kpi = {
        "cost": KpiCard(tr("Production cost"), "€ / kg",
                        "annual operating cost per kg at the plant gate"),
        "gwp": KpiCard("GWP", "kg CO₂-eq / kg", "cradle-to-gate, attributional"),
        "output": KpiCard(tr("Annual output"), "t / yr", "dry basis, after harvest losses"),
        "npv": KpiCard("NPV", "€ M", "after tax, over the plant lifetime"),
        "payback": KpiCard(tr("Payback"), "years", "total investment ÷ annual after-tax cash flow"),
        "roi": KpiCard("ROI", "% / yr", "net profit after tax ÷ total investment"),
    }
    for i, key in enumerate(("cost", "gwp", "output", "npv", "payback", "roi")):
        grid.addWidget(win.kpi[key], i // 3, i % 3)
    for c in range(3):
        grid.setColumnStretch(c, 1)
    lay.addLayout(grid)

    charts = QHBoxLayout()
    charts.setSpacing(10)
    win.cv_overview_cost = MplCanvas(width=5.0, height=3.2)
    win.cv_overview_gwp = MplCanvas(width=5.0, height=3.2)
    charts.addWidget(win.cv_overview_cost, 1)
    charts.addWidget(win.cv_overview_gwp, 1)
    lay.addLayout(charts, 1)

    win.basis_frame, win.lbl_basis = basis_box()
    lay.addWidget(win.basis_frame)
    return scrollable(inner)


# --------------------------------------------------------------------------- #
# Costs
# --------------------------------------------------------------------------- #
def _costs(win) -> QWidget:
    inner, lay = page()
    row = QHBoxLayout()
    row.setSpacing(10)
    win.cv_opex = MplCanvas(width=5.0, height=3.0)
    win.cv_capex = MplCanvas(width=5.0, height=3.0)
    row.addWidget(win.cv_opex, 1)
    row.addWidget(win.cv_capex, 1)
    lay.addLayout(row, 3)

    lay.addWidget(label(tr("Itemised production cost"), "h2"))
    win.tbl_tea = make_table([tr("Cost item"), "€ / kg", tr("€ / yr (plant total)"),
                              tr("% of total")])
    win.tbl_tea.setMinimumHeight(180)
    lay.addWidget(win.tbl_tea, 3)
    win.lbl_tea_totals = label("", "caption", wrap=True)
    lay.addWidget(win.lbl_tea_totals)

    lay.addWidget(label(tr("Financial summary"), "h2"))
    win.kv_tea = KeyValueGrid(columns=3)
    lay.addWidget(win.kv_tea)
    return scrollable(inner)


# --------------------------------------------------------------------------- #
# Life cycle
# --------------------------------------------------------------------------- #
def _lca(win) -> QWidget:
    inner, lay = page()
    split = QSplitter(Qt.Horizontal)
    split.setChildrenCollapsible(False)
    win.cv_gwp = MplCanvas(width=6.0, height=3.4)
    split.addWidget(win.cv_gwp)
    right = QWidget()
    rl = QVBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(6)
    rl.addWidget(label(tr("Impact categories"), "h2"))
    win.tbl_impacts = make_table([tr("Impact category"), tr("Value"), tr("Unit"), tr("Method")])
    rl.addWidget(win.tbl_impacts)
    rl.addWidget(label(tr("Per kg of dry biomass processed. Hover a row for the method note."),
                       "caption", wrap=True))
    rl.addStretch(1)
    split.addWidget(right)
    split.setStretchFactor(0, 3)
    split.setStretchFactor(1, 2)
    split.setSizes([700, 520])
    lay.addWidget(split, 1)

    win.lbl_lca_totals = label("", "subtle", wrap=True)
    win.lbl_lca_totals.setTextFormat(Qt.RichText)
    lay.addWidget(win.lbl_lca_totals)
    # An impact number is not interpretable without its method, so the tab
    # that shows the numbers also says which method produced them and which
    # flows this scenario leaves uncharacterized.
    box, win.lbl_lca_method = basis_box()
    lay.addWidget(box)
    return scrollable(inner)


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
def _inventory(win) -> QWidget:
    inner, lay = page()
    win.lbl_inv_basis = label(
        tr("Foreground inventory per 1 kg of dry biomass processed — the flows "
           "the allocation is applied to, not per kg of main product."),
        "subtle", wrap=True)
    lay.addWidget(win.lbl_inv_basis)
    split = QSplitter(Qt.Horizontal)
    split.setChildrenCollapsible(False)
    win.tbl_inv = make_table([tr("Flow"), tr("Value"), tr("Unit")])
    split.addWidget(win.tbl_inv)
    win.cv_elec = MplCanvas(width=4.5, height=3.0)
    split.addWidget(win.cv_elec)
    split.setStretchFactor(0, 1)
    split.setStretchFactor(1, 1)
    split.setSizes([620, 600])
    lay.addWidget(split, 1)
    return inner


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
def _products(win) -> QWidget:
    inner, lay = page()
    win.empty_products = EmptyState(
        tr("Single product: the whole biomass"),
        tr("Enable “extraction and co-products” in the inputs (step 4) to split the "
           "biomass into a main product and co-products, with cost and impact allocation."))
    # The name the render code has always used for this hint.
    win.lbl_products_hint = win.empty_products
    lay.addWidget(win.empty_products)
    win.lbl_products_basis = label("", "subtle", wrap=True)
    lay.addWidget(win.lbl_products_basis)
    win.tbl_products = make_table([tr("Product"), "t / yr", tr("Cost € / kg"), tr("Price € / kg"),
                                   tr("Allocation %"), "GWP kg CO₂-eq / kg", tr("Revenue € / yr")])
    lay.addWidget(win.tbl_products, 1)
    lay.addStretch(0)
    return inner


# --------------------------------------------------------------------------- #
# Sensitivity
# --------------------------------------------------------------------------- #
def _sensitivity(win) -> QWidget:
    inner, lay = page()
    ctrl = QHBoxLayout()
    ctrl.setSpacing(8)
    win.cmb_sens_param = QComboBox()
    win.cmb_sens_param.addItems([p.name for p in PARAMETERS])
    win.cmb_sens_param.setToolTip("The input to sweep across its default range, "
                                  "everything else held at the current case.")
    win.cmb_sens_output = QComboBox()
    win.cmb_sens_output.addItems(list(OUTPUTS.keys()))
    win.cmb_sens_output.setCurrentText("NPV (€)")
    win.cmb_sens_output.setToolTip("The result to follow.")
    # Cap how wide these long-labelled combos ask to be, so the tab does not
    # force the whole results panel wide.
    for cb in (win.cmb_sens_param, win.cmb_sens_output):
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(16)
    win.btn_sens = button(tr("Run sweep"), "primary", win.run_sensitivity,
                          "Recompute the case at eleven values of the chosen input", "F5")
    ctrl.addWidget(QLabel(tr("Vary:")))
    ctrl.addWidget(win.cmb_sens_param)
    ctrl.addWidget(QLabel(tr("Output:")))
    ctrl.addWidget(win.cmb_sens_output)
    ctrl.addWidget(win.btn_sens)
    ctrl.addStretch(1)
    lay.addLayout(ctrl)
    split = QSplitter(Qt.Horizontal)
    split.setChildrenCollapsible(False)
    win.cv_sens = MplCanvas(width=6, height=3.4)
    split.addWidget(win.cv_sens)
    win.tbl_sens = make_table([tr("Input value"), tr("Output"), tr("Change vs current")])
    win.tbl_sens.setVisible(False)
    split.addWidget(win.tbl_sens)
    split.setStretchFactor(0, 3)
    split.setStretchFactor(1, 2)
    split.setSizes([800, 420])
    lay.addWidget(split, 1)
    win.lbl_sens_note = label("", "caption", wrap=True)
    lay.addWidget(win.lbl_sens_note)
    win.cv_sens.show_message(tr("No sweep run yet"),
                             tr("Pick an input and an output above, then run the sweep. "
                                "Points that make the case inadmissible are left out."))
    return inner


# --------------------------------------------------------------------------- #
# Uncertainty
# --------------------------------------------------------------------------- #
def _uncertainty(win) -> QWidget:
    inner, lay = page()
    lay.addWidget(label(tr("Vary these inputs"), "h3"))
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(2)
    win.unc_checks: dict[str, QCheckBox] = {}
    default_on = {"Plant scale", "Product price", "Productivity", "Electricity price"}
    cols = 3
    for idx, p in enumerate(PARAMETERS):
        cb = QCheckBox(p.name)
        cb.setChecked(p.name in default_on)
        cb.setToolTip(f"Unit: {p.unit}")
        win.unc_checks[p.name] = cb
        grid.addWidget(cb, idx // cols, idx % cols)
    lay.addLayout(grid)
    row = QHBoxLayout()
    row.setSpacing(8)
    win.spn_unc_pct = QSpinBox()
    win.spn_unc_pct.setRange(1, 80)
    win.spn_unc_pct.setValue(20)
    win.spn_unc_pct.setSuffix(" %")
    win.spn_unc_pct.setToolTip("Each chosen input is drawn uniformly within ± this share "
                               "of its current value.")
    win.spn_unc_n = QSpinBox()
    win.spn_unc_n.setRange(100, 20000)
    win.spn_unc_n.setSingleStep(100)
    win.spn_unc_n.setValue(1000)
    win.spn_unc_n.setGroupSeparatorShown(True)
    win.spn_unc_n.setToolTip("Number of Monte Carlo draws.")
    win.cmb_unc_output = QComboBox()
    win.cmb_unc_output.addItems(list(OUTPUTS.keys()))
    win.cmb_unc_output.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    win.cmb_unc_output.setMinimumContentsLength(16)
    win.btn_unc = button(tr("Run Monte Carlo"), "primary", win.run_uncertainty,
                         "Sample the chosen inputs and recompute the case for every draw", "F6")
    row.addWidget(QLabel(tr("Relative width (±):")))
    row.addWidget(win.spn_unc_pct)
    row.addWidget(QLabel(tr("Samples:")))
    row.addWidget(win.spn_unc_n)
    row.addWidget(QLabel(tr("Output:")))
    row.addWidget(win.cmb_unc_output)
    row.addWidget(win.btn_unc)
    row.addStretch(1)
    lay.addLayout(row)
    win.cv_unc = MplCanvas(width=6, height=3.2)
    lay.addWidget(win.cv_unc, 1)
    win.kv_unc = KeyValueGrid(columns=5)
    lay.addWidget(win.kv_unc)
    win.lbl_unc_stats = label("", "caption", wrap=True)
    lay.addWidget(win.lbl_unc_stats)
    win.cv_unc.show_message(tr("No Monte Carlo run yet"),
                            tr("Tick the inputs to vary, set the width and the number of "
                               "draws, then run."))
    return inner


# --------------------------------------------------------------------------- #
# Compare
# --------------------------------------------------------------------------- #
def _compare(win) -> QWidget:
    inner, lay = page()
    row = QHBoxLayout()
    row.setSpacing(8)
    win.btn_snap = button(tr("Snapshot current scenario"), "primary", win.snapshot_scenario,
                          "Keep the current case's KPIs as a column", "F7")
    win.btn_clear_snap = button(tr("Clear snapshots"), "secondary", win.clear_snapshots)
    row.addWidget(win.btn_snap)
    row.addWidget(win.btn_clear_snap)
    row.addStretch(1)
    lay.addLayout(row)
    win.empty_cmp = EmptyState(
        tr("No snapshots yet"),
        tr("Take a snapshot of the current case, change something, and take another: the "
           "KPIs line up side by side. Every column states its own functional unit."))
    lay.addWidget(win.empty_cmp)
    win.tbl_compare = make_table([])
    win.tbl_compare.setRowCount(len(KPI_ORDER))
    win.tbl_compare.verticalHeader().setVisible(True)
    win.tbl_compare.setVerticalHeaderLabels(KPI_ORDER)
    win.tbl_compare.setVisible(False)
    lay.addWidget(win.tbl_compare, 1)
    lay.addStretch(0)
    return inner
