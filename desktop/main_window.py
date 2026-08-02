"""The main application window: inputs on the left, live results on the right."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from algametrix import library as _lib
from algametrix.benchmarks import (
    check_benchmarks,
    infer_category,
    load_market_prices,
    load_validation_references,
)
from algametrix.comparison import KPI_ORDER, scenario_kpis
from algametrix.library import DEFAULT_DATA_DIR, load_library
from algametrix.models import (
    Basis,
    CarbonSource,
    Extraction,
    Material,
    Product,
    Scenario,
)
from algametrix.scenario import minimum_selling_price, run_scenario
from algametrix.sensitivity import OUTPUTS, PARAMETERS, run_sweep
from algametrix.uncertainty import run_montecarlo
from algametrix.validation import (
    METRICS,
    compare,
    parse_reference_csv,
    parse_superpro_excel,
)

from .i18n import tr
from .style import STYLESHEET
from .widgets import KpiCard, MplCanvas, NEG, POS

# Chart accent is kept independent of the Blueprint UI accent: the plots keep their
# original green so the figures read as before, while the interface stays blue.
ACCENT = "#2e7d32"


def _money(v: float) -> str:
    if abs(v) >= 1e6:
        return f"€ {v / 1e6:,.2f} M"
    if abs(v) >= 1e3:
        return f"€ {v / 1e3:,.1f} k"
    return f"€ {v:,.0f}"


class TableEditorDialog(QDialog):
    """Generic editable table for building a list of rows (add/remove/edit)."""

    def __init__(self, title, headers, rows, parent=None, hint: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 340)
        lay = QVBoxLayout(self)
        if hint:
            lbl = QLabel(hint)
            lbl.setObjectName("subtle")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        self.table = QTableWidget(len(rows), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))
        lay.addWidget(self.table)
        btns = QHBoxLayout()
        add = QPushButton(tr("Add row"))
        add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        rem = QPushButton(tr("Remove selected"))
        rem.clicked.connect(self._remove_selected)
        ok = QPushButton(tr("OK"))
        ok.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _remove_selected(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def result_rows(self) -> list[list[str]]:
        out = []
        for r in range(self.table.rowCount()):
            row = [(self.table.item(r, c).text() if self.table.item(r, c) else "")
                   for c in range(self.table.columnCount())]
            if any(x.strip() for x in row):
                out.append(row)
        return out


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("AlgaMetrix  ·  Techno-economic & LCA for microalgae"))
        self.resize(1280, 820)
        self.setStyleSheet(STYLESHEET)

        self.lib = load_library()
        self._loading = True          # suppress recompute while (re)building controls
        self.reference: dict[str, float] = {}

        # Live, editable copies of the current building blocks.
        self.organism = copy.deepcopy(next(iter(self.lib.organisms.values())))
        self.system = copy.deepcopy(next(iter(self.lib.systems.values())))
        self.harvesting = copy.deepcopy(next(iter(self.lib.harvesting.values())))
        self.drying = copy.deepcopy(next(iter(self.lib.drying.values())))
        self.economics = copy.deepcopy(self.lib.economics)
        self.lcia = copy.deepcopy(self.lib.lcia)
        self.scale = 100_000.0
        self.product_price = self.system.product_price
        self.coproduct_revenue = 0.0
        self.batch_mode = False
        self.batch_size_kg = 1000.0
        self.batch_cycle_time_h = 48.0
        self.custom_materials: list[Material] = []
        self.extraction = Extraction(enabled=False)
        self.products: list[Product] = []

        self._spins: dict[tuple[str, str], QDoubleSpinBox] = {}
        self._checks: dict[tuple[str, str], QCheckBox] = {}
        self._snapshots: list[tuple[str, dict]] = []

        self._build_menu()
        self._build_ui()
        self._update_carbon_labels()
        self._loading = False
        self.recompute()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu(tr("&File"))
        file_menu.addAction(tr("New case study (wizard)…"), self.open_wizard)
        file_menu.addAction(tr("New / reset"), self.reset_defaults)
        file_menu.addAction(tr("Open scenario…"), self.load_scenario)
        file_menu.addAction(tr("Save scenario…"), self.save_scenario)
        file_menu.addSeparator()
        file_menu.addAction(tr("Export results (JSON)…"), self.export_results)
        file_menu.addAction(tr("Export process report (PDF)…"), self.export_process_report)
        file_menu.addSeparator()
        file_menu.addAction(tr("Exit"), self.close)

        val_menu = bar.addMenu(tr("&Validation"))
        val_menu.addAction(
            "SuperPro: heterotrophic powder (bundled)",
            lambda: self.load_bundled_reference("reference_superpro_heterotrophic.csv"),
        )
        val_menu.addAction(
            "SuperPro: phototrophic algal oil (bundled)",
            lambda: self.load_bundled_reference("reference_superpro_phototrophic.csv"),
        )
        val_menu.addAction(
            "SuperPro: omega-3 oil fermentation (bundled)",
            lambda: self.load_bundled_reference("reference_superpro_omega3.csv"),
        )
        val_menu.addSeparator()
        val_menu.addAction(tr("Load reference CSV…"), self.load_reference_csv)
        val_menu.addAction(tr("Import SuperPro Excel report…"), self.load_superpro_excel)
        val_menu.addSeparator()
        val_menu.addAction(tr("Show comparison"), self.show_comparison)
        val_menu.addSeparator()
        val_menu.addAction(tr("Check open-literature benchmarks"), self.show_benchmarks)
        val_menu.addAction(tr("Market price reference"), self.show_market_prices)
        val_menu.addAction(tr("Validation library (papers)…"), self.show_validation_references)

        help_menu = bar.addMenu(tr("&Help"))
        help_menu.addAction(tr("Language…"), self.change_language)
        help_menu.addAction(tr("About"), self.show_about)

    def _spin(self, obj: str, attr: str, lo: float, hi: float, step: float, decimals: int = 3):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        sb.setValue(float(getattr(getattr(self, obj), attr)))
        sb.valueChanged.connect(lambda v, o=obj, a=attr: self._on_field(o, a, v))
        self._spins[(obj, attr)] = sb
        return sb

    def _check(self, obj: str, attr: str, text: str):
        cb = QCheckBox(tr(text))
        cb.setChecked(bool(getattr(getattr(self, obj), attr)))
        cb.toggled.connect(lambda v, o=obj, a=attr: self._on_field(o, a, v))
        self._checks[(obj, attr)] = cb
        return cb

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Classic parametric view: inputs on the left, live results on the right.
        scenario_tab = QWidget()
        scenario_layout = QVBoxLayout(scenario_tab)
        scenario_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_results_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)  # neither panel can be dragged to zero
        splitter.setSizes([480, 1120])
        self.splitter = splitter
        scenario_layout.addWidget(splitter)

        # Top-level mode switch: parametric scenario vs. the visual flowsheet.
        self.top_tabs = QTabWidget()
        self.top_tabs.addTab(scenario_tab, tr("⚗  Scenario"))
        self._flowsheet_tab_index = self.top_tabs.addTab(
            self._build_flowsheet_tab(), tr("🧩  Process Designer"))
        self.top_tabs.currentChanged.connect(self._on_top_tab_changed)
        root.addWidget(self.top_tabs)

    def _build_flowsheet_tab(self) -> QWidget:
        """The SuperPro-style visual process editor (lazy import to keep startup
        cheap and to isolate any Qt-canvas issues from the classic view)."""
        from .flowsheet import FlowsheetEditor

        self.flowsheet_editor = FlowsheetEditor()
        # Let the designer (re)generate its diagram from the live case study.
        self.flowsheet_editor.set_scenario_source(
            lambda: (self.build_scenario(), getattr(self, "results", None)))
        return self.flowsheet_editor

    def _on_top_tab_changed(self, index: int):
        """First time the Process Designer is opened, auto-build from the case."""
        if index == getattr(self, "_flowsheet_tab_index", -1):
            self.flowsheet_editor.maybe_autogenerate()

    def _build_input_panel(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 4, 4, 4)

        # --- Organism -------------------------------------------------
        g_org = QGroupBox(tr("Organism"))
        f = QFormLayout(g_org)
        self.cmb_org = QComboBox()
        self.cmb_org.addItems(list(self.lib.organisms))
        self.cmb_org.currentTextChanged.connect(self._on_organism)
        f.addRow(tr("Strain"), self.cmb_org)
        f.addRow(tr("Carbon (frac. DW)"), self._spin("organism", "carbon", 0.0, 1.0, 0.01))
        f.addRow(tr("Nitrogen (frac. DW)"), self._spin("organism", "nitrogen", 0.0, 0.3, 0.005))
        f.addRow(tr("Phosphorus (frac. DW)"), self._spin("organism", "phosphorus", 0.0, 0.1, 0.001))
        f.addRow(tr("Phycocyanin (frac. DW)"), self._spin("organism", "phycocyanin", 0.0, 0.3, 0.01, 3))
        v.addWidget(g_org)

        # --- Cultivation ---------------------------------------------
        g_sys = QGroupBox(tr("Cultivation system"))
        f = QFormLayout(g_sys)
        self.cmb_sys = QComboBox()
        self.cmb_sys.addItems(list(self.lib.systems))
        self.cmb_sys.currentTextChanged.connect(self._on_system)
        f.addRow(tr("System"), self.cmb_sys)
        self.lbl_prod = QLabel(tr("Productivity (g/m²/d)"))
        f.addRow(self.lbl_prod, self._spin("system", "productivity", 0.0, 300.0, 1.0, 1))
        f.addRow(tr("Operating days / yr"), self._spin("system", "operating_days", 1.0, 365.0, 5.0, 0))
        f.addRow(tr("Cultivation elec. (kWh/kg)"), self._spin("system", "elec_kwh_per_kg", 0.0, 50.0, 0.1, 2))
        self.cmb_carbon = QComboBox()
        self.cmb_carbon.addItems([tr("CO₂ (gas)"), tr("Sodium bicarbonate (NaHCO₃)")])
        self.cmb_carbon.currentIndexChanged.connect(self._on_carbon_source)
        f.addRow(tr("Carbon source"), self.cmb_carbon)
        self.lbl_util = QLabel(tr("CO₂ utilization"))
        f.addRow(self.lbl_util, self._spin("system", "co2_utilization", 0.05, 1.0, 0.05, 2))
        f.addRow(tr("Nutrient uptake eff."), self._spin("system", "nutrient_uptake", 0.1, 1.0, 0.05, 2))
        f.addRow(tr("Water use (m³/kg)"), self._spin("system", "water_m3_per_kg", 0.0, 5.0, 0.05, 2))
        f.addRow(tr("Cultivation heat (MJ/kg)"), self._spin("system", "cultivation_heat_mj_per_kg", 0.0, 200.0, 2.0, 1))
        self.cmb_heatfuel = QComboBox()
        self.cmb_heatfuel.addItems([tr("Natural gas"), tr("Electricity")])
        self.cmb_heatfuel.currentIndexChanged.connect(self._on_heat_fuel)
        f.addRow(tr("Heat fuel"), self.cmb_heatfuel)
        f.addRow(tr("Substrate yield (kg/kg)"), self._spin("system", "substrate_yield", 0.0, 1.0, 0.05, 2))
        self.lbl_capex = QLabel(tr("Cultivation CAPEX (€/m²)"))
        f.addRow(self.lbl_capex, self._spin("system", "capex_per_unit", 0.0, 5000.0, 5.0, 1))
        self.lbl_scale = QLabel(tr("Plant scale (m²)"))
        self.spn_scale = QDoubleSpinBox()
        self.spn_scale.setRange(1.0, 1e9)
        self.spn_scale.setDecimals(0)
        self.spn_scale.setGroupSeparatorShown(True)
        self.spn_scale.setValue(self.scale)
        self.spn_scale.valueChanged.connect(self._on_scale)
        f.addRow(self.lbl_scale, self.spn_scale)
        v.addWidget(g_sys)

        # --- Downstream ----------------------------------------------
        g_dn = QGroupBox(tr("Downstream (harvesting & drying)"))
        f = QFormLayout(g_dn)
        self.cmb_harv = QComboBox()
        self.cmb_harv.addItems(list(self.lib.harvesting))
        self.cmb_harv.currentTextChanged.connect(self._on_harvesting)
        f.addRow(tr("Harvesting"), self.cmb_harv)
        f.addRow(tr("Biomass recovery"), self._spin("harvesting", "recovery", 0.1, 1.0, 0.02, 2))
        f.addRow(tr("Harvesting elec. (kWh/kg)"), self._spin("harvesting", "elec_kwh_per_kg", 0.0, 20.0, 0.1, 2))
        f.addRow(tr("Concentrate solids"), self._spin("harvesting", "final_solids", 0.02, 0.5, 0.01, 2))
        self.cmb_dry = QComboBox()
        self.cmb_dry.addItems(list(self.lib.drying))
        self.cmb_dry.currentTextChanged.connect(self._on_drying)
        f.addRow(tr("Drying"), self.cmb_dry)
        f.addRow(tr(""), self._check("drying", "enabled", "Drying enabled"))
        f.addRow(tr("Drying heat (MJ/kg water)"), self._spin("drying", "thermal_mj_per_kg_water", 0.0, 6.0, 0.1, 2))
        f.addRow(tr("Dried product solids"), self._spin("drying", "final_solids", 0.5, 1.0, 0.01, 2))
        v.addWidget(g_dn)

        # --- Economics -----------------------------------------------
        g_eco = QGroupBox(tr("Economic assumptions"))
        f = QFormLayout(g_eco)
        f.addRow(tr("Electricity price (€/kWh)"), self._spin("economics", "electricity_price", 0.0, 1.0, 0.01, 3))
        f.addRow(tr("Heat price (€/MJ)"), self._spin("economics", "heat_price", 0.0, 0.2, 0.005, 3))
        f.addRow(tr("CO₂ price (€/kg)"), self._spin("economics", "co2_price", -0.2, 1.0, 0.01, 3))
        f.addRow(tr("Bicarbonate price (€/kg)"), self._spin("economics", "bicarbonate_price", 0.0, 2.0, 0.01, 3))
        f.addRow(tr("Nitrogen price (€/kg N)"), self._spin("economics", "nitrogen_price", 0.0, 10.0, 0.1, 2))
        f.addRow(tr("Phosphorus price (€/kg P)"), self._spin("economics", "phosphorus_price", 0.0, 15.0, 0.1, 2))
        f.addRow(tr("Substrate price (€/kg)"), self._spin("economics", "substrate_price", 0.0, 3.0, 0.05, 2))
        f.addRow(tr("Water price (€/m³)"), self._spin("economics", "water_price", 0.0, 5.0, 0.05, 2))
        f.addRow(tr("Land price (€/m²)"), self._spin("economics", "land_price", 0.0, 200.0, 1.0, 1))
        f.addRow(tr("Harvest CAPEX (€/kg·yr)"), self._spin("economics", "harvest_capex_per_kgyr", 0.0, 50.0, 0.5, 2))
        f.addRow(tr("Drying CAPEX (€/kg·yr)"), self._spin("economics", "drying_capex_per_kgyr", 0.0, 50.0, 0.5, 2))
        f.addRow(tr("Installation factor"), self._spin("economics", "installation_factor", 1.0, 6.0, 0.1, 2))
        f.addRow(tr("Labour (€/yr)"), self._spin("economics", "labor_cost_per_year", 0.0, 1e7, 10000.0, 0))
        f.addRow(tr("Maintenance (frac. CAPEX/yr)"), self._spin("economics", "maintenance_frac", 0.0, 0.2, 0.005, 3))
        f.addRow(tr("Discount rate"), self._spin("economics", "discount_rate", 0.0, 0.25, 0.005, 3))
        f.addRow(tr("Plant lifetime (yr)"), self._spin("economics", "plant_lifetime", 1.0, 40.0, 1.0, 0))
        f.addRow(tr("Depreciation period (yr)"), self._spin("economics", "depreciation_years", 1.0, 30.0, 1.0, 0))
        f.addRow(tr("Tax rate"), self._spin("economics", "tax_rate", 0.0, 0.6, 0.05, 2))
        v.addWidget(g_eco)

        # --- Profitability -------------------------------------------
        g_prof = QGroupBox(tr("Profitability"))
        f = QFormLayout(g_prof)
        self.spn_price = QDoubleSpinBox()
        self.spn_price.setRange(0.0, 1000.0)
        self.spn_price.setDecimals(2)
        self.spn_price.setSingleStep(0.5)
        self.spn_price.setValue(self.product_price)
        self.spn_price.valueChanged.connect(self._on_price)
        f.addRow(tr("Product price (€/kg)"), self.spn_price)
        self.spn_coproduct = QDoubleSpinBox()
        self.spn_coproduct.setRange(0.0, 1e9)
        self.spn_coproduct.setDecimals(0)
        self.spn_coproduct.setSingleStep(50_000)
        self.spn_coproduct.setGroupSeparatorShown(True)
        self.spn_coproduct.setValue(self.coproduct_revenue)
        self.spn_coproduct.valueChanged.connect(self._on_coproduct)
        f.addRow(tr("Co-product revenue (€/yr)"), self.spn_coproduct)
        v.addWidget(g_prof)

        # --- Extraction & products (biorefinery) ---------------------
        g_ext = QGroupBox(tr("Downstream extraction & products"))
        f = QFormLayout(g_ext)
        self.chk_extraction = QCheckBox("Enable extraction & co-products")
        self.chk_extraction.toggled.connect(self._on_extraction_change)
        f.addRow(tr(""), self.chk_extraction)
        self.cmb_ext_tech = QComboBox()
        self.cmb_ext_tech.addItems(list(self.lib.extraction))
        self.cmb_ext_tech.setToolTip(tr(
            "Downstream extraction technology (hexane, ethanol, supercritical CO2, "
            "bead-milling, ultrafiltration, chromatography). Sets the energy, solvent "
            "and CAPEX of the extraction step from the literature-anchored catalogue."
        ))
        self.cmb_ext_tech.currentTextChanged.connect(self._on_extraction_tech)
        f.addRow(tr("Extraction technology"), self.cmb_ext_tech)
        self.cmb_downstream = QComboBox()
        self.cmb_downstream.addItems([
            tr("Oil / lipid → main product"),
            tr("Protein → main product"),
        ])
        self.cmb_downstream.currentTextChanged.connect(self._on_extraction_change)
        f.addRow(tr("Target product"), self.cmb_downstream)

        def _ext_spin(lo, hi, val, step, dec):
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setDecimals(dec)
            sb.setSingleStep(step)
            sb.setValue(val)
            sb.valueChanged.connect(self._on_extraction_change)
            return sb

        self.spn_oil_rec = _ext_spin(0.1, 1.0, 0.90, 0.05, 2)
        self.spn_oil_price = _ext_spin(0.0, 50.0, 2.50, 0.1, 2)
        self.spn_prot_rec = _ext_spin(0.0, 1.0, 0.80, 0.05, 2)
        self.spn_prot_price = _ext_spin(0.0, 10.0, 0.60, 0.05, 2)
        self.spn_solvent_price = _ext_spin(0.0, 10.0, 1.50, 0.1, 2)
        f.addRow(tr("Oil (lipid) recovery"), self.spn_oil_rec)
        f.addRow(tr("Oil price (€/kg)"), self.spn_oil_price)
        f.addRow(tr("Protein recovery"), self.spn_prot_rec)
        f.addRow(tr("Protein price (€/kg)"), self.spn_prot_price)
        f.addRow(tr("Solvent make-up price (€/kg)"), self.spn_solvent_price)
        self.cmb_alloc = QComboBox()
        self.cmb_alloc.addItems(["economic", "mass", "none"])
        self.cmb_alloc.currentTextChanged.connect(self._on_extraction_change)
        f.addRow(tr("Allocation method"), self.cmb_alloc)
        v.addWidget(g_ext)

        # --- Batch scheduling ----------------------------------------
        g_batch = QGroupBox(tr("Batch scheduling"))
        f = QFormLayout(g_batch)
        self.chk_batch = QCheckBox("Batch mode (else continuous)")
        self.chk_batch.toggled.connect(self._on_batch_change)
        f.addRow(tr(""), self.chk_batch)
        self.spn_batch_size = QDoubleSpinBox()
        self.spn_batch_size.setRange(1.0, 1e7)
        self.spn_batch_size.setDecimals(0)
        self.spn_batch_size.setGroupSeparatorShown(True)
        self.spn_batch_size.setValue(self.batch_size_kg)
        self.spn_batch_size.valueChanged.connect(self._on_batch_change)
        self.spn_batch_cycle = QDoubleSpinBox()
        self.spn_batch_cycle.setRange(1.0, 2000.0)
        self.spn_batch_cycle.setDecimals(1)
        self.spn_batch_cycle.setValue(self.batch_cycle_time_h)
        self.spn_batch_cycle.valueChanged.connect(self._on_batch_change)
        f.addRow(tr("Batch size (kg gross/batch)"), self.spn_batch_size)
        f.addRow(tr("Cycle time (h)"), self.spn_batch_cycle)
        v.addWidget(g_batch)

        # --- Custom media & products (editors) -----------------------
        g_custom = QGroupBox(tr("Custom media & products"))
        cf = QVBoxLayout(g_custom)
        btn_mat = QPushButton(tr("Edit media / materials…"))
        btn_mat.clicked.connect(self.edit_materials)
        btn_prod = QPushButton(tr("Edit products…"))
        btn_prod.clicked.connect(self.edit_products)
        self.lbl_custom = QLabel(tr(tr("No custom media or products defined.")))
        self.lbl_custom.setObjectName("subtle")
        self.lbl_custom.setWordWrap(True)
        cf.addWidget(btn_mat)
        cf.addWidget(btn_prod)
        cf.addWidget(self.lbl_custom)
        v.addWidget(g_custom)

        # --- LCA ------------------------------------------------------
        g_lca = QGroupBox(tr("LCA characterization factors"))
        f = QFormLayout(g_lca)
        f.addRow(tr("Electricity GWP (kg CO₂-eq/kWh)"), self._spin("lcia", "elec_gwp", 0.0, 1.5, 0.01, 3))
        f.addRow(tr("Electricity CED (MJ/kWh)"), self._spin("lcia", "elec_ced", 0.0, 15.0, 0.5, 2))
        f.addRow(tr("Heat GWP (kg CO₂-eq/MJ)"), self._spin("lcia", "heat_gwp", 0.0, 0.3, 0.005, 3))
        f.addRow(tr("N fertilizer GWP (kg CO₂-eq/kg)"), self._spin("lcia", "nitrogen_gwp", 0.0, 20.0, 0.5, 2))
        f.addRow(tr("P fertilizer GWP (kg CO₂-eq/kg)"), self._spin("lcia", "phosphorus_gwp", 0.0, 10.0, 0.5, 2))
        f.addRow(tr("CO₂ supply GWP (kg CO₂-eq/kg)"), self._spin("lcia", "co2_supply_gwp", 0.0, 1.0, 0.01, 3))
        f.addRow(tr("Bicarbonate GWP (kg CO₂-eq/kg)"), self._spin("lcia", "bicarbonate_gwp", 0.0, 3.0, 0.05, 2))
        f.addRow(tr("Substrate GWP (kg CO₂-eq/kg)"), self._spin("lcia", "substrate_gwp", 0.0, 5.0, 0.05, 2))
        f.addRow(tr(""), self._check("lcia", "count_biogenic_uptake", "Credit biogenic CO₂ uptake at gate"))
        v.addWidget(g_lca)

        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setMinimumWidth(400)
        return scroll

    def _build_results_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        title = QLabel(tr("Techno-economic & Life-cycle results"))
        title.setObjectName("h1")
        v.addWidget(title)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("subtle")
        # Wrap instead of forcing the whole panel as wide as this one-line summary,
        # which would stop the input column from being dragged wider.
        self.subtitle.setWordWrap(True)
        v.addWidget(self.subtitle)

        # KPI cards
        kpi_row = QHBoxLayout()
        self.kpi = {
            "cost": KpiCard(tr("Production cost"), "€ / kg"),
            "npv": KpiCard("NPV", "€ M"),
            "payback": KpiCard(tr("Payback"), "years"),
            "roi": KpiCard("ROI", "% / yr"),
            "gwp": KpiCard("GWP", "kg CO₂-eq / kg"),
            "output": KpiCard(tr("Annual output"), "t / yr"),
        }
        for card in self.kpi.values():
            kpi_row.addWidget(card)
        v.addLayout(kpi_row)

        # Tabs with charts
        tabs = QTabWidget()

        tea_tab = QWidget()
        tea_l = QGridLayout(tea_tab)
        self.cv_opex = MplCanvas()
        self.cv_capex = MplCanvas()
        tea_l.addWidget(self.cv_opex, 0, 0)
        tea_l.addWidget(self.cv_capex, 0, 1)
        # Itemised production-cost table: every operating-cost line (raw materials,
        # utilities, labour, facility, overhead) with its unit cost, annual cost and
        # share of the total — the detail behind the € / kg production cost.
        self.tbl_tea = QTableWidget(0, 4)
        self.tbl_tea.setHorizontalHeaderLabels(
            [tr("Cost item"), tr("€ / kg"), tr("€ / yr"), tr("% of total")]
        )
        self.tbl_tea.horizontalHeader().setStretchLastSection(True)
        self.tbl_tea.verticalHeader().setVisible(False)
        self.tbl_tea.setEditTriggers(QTableWidget.NoEditTriggers)
        tea_l.addWidget(self.tbl_tea, 1, 0, 1, 2)
        self.lbl_tea_totals = QLabel("")
        self.lbl_tea_totals.setObjectName("subtle")
        self.lbl_tea_totals.setWordWrap(True)
        tea_l.addWidget(self.lbl_tea_totals, 2, 0, 1, 2)
        tea_l.setRowStretch(0, 3)
        tea_l.setRowStretch(1, 2)
        tabs.addTab(tea_tab, tr("💶  Techno-economic"))

        lca_tab = QWidget()
        lca_l = QVBoxLayout(lca_tab)
        lca_top = QHBoxLayout()
        self.cv_gwp = MplCanvas(width=6)
        lca_top.addWidget(self.cv_gwp, 2)
        self.tbl_impacts = QTableWidget(0, 2)
        self.tbl_impacts.setHorizontalHeaderLabels([tr("Impact category"), tr("per kg biomass")])
        self.tbl_impacts.horizontalHeader().setStretchLastSection(True)
        self.tbl_impacts.verticalHeader().setVisible(False)
        lca_top.addWidget(self.tbl_impacts, 1)
        lca_l.addLayout(lca_top)
        self.lbl_lca_totals = QLabel("")
        self.lbl_lca_totals.setObjectName("subtle")
        self.lbl_lca_totals.setWordWrap(True)
        lca_l.addWidget(self.lbl_lca_totals)
        tabs.addTab(lca_tab, tr("🌍  Life-cycle"))

        inv_tab = QWidget()
        inv_l = QHBoxLayout(inv_tab)
        self.tbl_inv = QTableWidget(0, 3)
        self.tbl_inv.setHorizontalHeaderLabels([tr("Flow"), tr("Value"), tr("Unit")])
        self.tbl_inv.horizontalHeader().setStretchLastSection(True)
        self.tbl_inv.verticalHeader().setVisible(False)
        inv_l.addWidget(self.tbl_inv, 1)
        self.cv_elec = MplCanvas()
        inv_l.addWidget(self.cv_elec, 1)
        tabs.addTab(inv_tab, tr("📦  Inventory"))

        prod_tab = QWidget()
        pl = QVBoxLayout(prod_tab)
        self.lbl_products_hint = QLabel(
            "Enable “extraction & co-products” in the sidebar to split the biomass into a "
            "main product (e.g. algal oil) and co-products, with cost & impact allocation."
        )
        self.lbl_products_hint.setObjectName("subtle")
        self.lbl_products_hint.setWordWrap(True)
        pl.addWidget(self.lbl_products_hint)
        self.tbl_products = QTableWidget(0, 6)
        self.tbl_products.setHorizontalHeaderLabels(
            [tr("Product"), "t/yr", tr("Cost €/kg"), tr("Price €/kg"), tr("Alloc %"), "GWP kgCO₂/kg"]
        )
        self.tbl_products.horizontalHeader().setStretchLastSection(True)
        self.tbl_products.verticalHeader().setVisible(False)
        pl.addWidget(self.tbl_products)
        tabs.addTab(prod_tab, tr("🛢  Products"))

        sens_tab = QWidget()
        sl = QVBoxLayout(sens_tab)
        ctrl = QHBoxLayout()
        self.cmb_sens_param = QComboBox()
        self.cmb_sens_param.addItems([p.name for p in PARAMETERS])
        self.cmb_sens_output = QComboBox()
        self.cmb_sens_output.addItems(list(OUTPUTS.keys()))
        self.cmb_sens_output.setCurrentText("NPV (€)")
        # Cap how wide these long-labelled combos ask to be, so the Sensitivity /
        # Uncertainty tabs don't force the whole results panel (and the input
        # column's max width) to the width of their longest option.
        for _cb in (self.cmb_sens_param, self.cmb_sens_output):
            _cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            _cb.setMinimumContentsLength(14)
        btn_run = QPushButton(tr("Run sweep"))
        btn_run.clicked.connect(self.run_sensitivity)
        ctrl.addWidget(QLabel(tr("Vary:")))
        ctrl.addWidget(self.cmb_sens_param)
        ctrl.addWidget(QLabel(tr("Output:")))
        ctrl.addWidget(self.cmb_sens_output)
        ctrl.addWidget(btn_run)
        ctrl.addStretch(1)
        sl.addLayout(ctrl)
        self.cv_sens = MplCanvas(width=6)
        sl.addWidget(self.cv_sens)
        tabs.addTab(sens_tab, tr("📈  Sensitivity"))

        # --- Uncertainty (Monte Carlo) tab ---------------------------
        unc_tab = QWidget()
        ul = QVBoxLayout(unc_tab)
        ul.addWidget(QLabel(tr("Vary:")))
        # A wrapping grid of parameter checkboxes rather than one long horizontal row,
        # so this tab does not force the whole results panel (and the splitter) wide.
        unc_grid = QGridLayout()
        unc_grid.setContentsMargins(0, 0, 0, 0)
        self.unc_checks: dict[str, QCheckBox] = {}
        default_on = {"Plant scale", "Product price", "Productivity", "Electricity price"}
        cols = 2
        for idx, p in enumerate(PARAMETERS):
            cb = QCheckBox(p.name)
            cb.setChecked(p.name in default_on)
            self.unc_checks[p.name] = cb
            unc_grid.addWidget(cb, idx // cols, idx % cols)
        ul.addLayout(unc_grid)
        row2 = QHBoxLayout()
        self.spn_unc_pct = QSpinBox()
        self.spn_unc_pct.setRange(1, 80)
        self.spn_unc_pct.setValue(20)
        self.spn_unc_pct.setSuffix(" %")
        self.spn_unc_n = QSpinBox()
        self.spn_unc_n.setRange(100, 20000)
        self.spn_unc_n.setSingleStep(100)
        self.spn_unc_n.setValue(1000)
        self.cmb_unc_output = QComboBox()
        self.cmb_unc_output.addItems(list(OUTPUTS.keys()))
        self.cmb_unc_output.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_unc_output.setMinimumContentsLength(14)
        btn_unc = QPushButton(tr("Run Monte Carlo"))
        btn_unc.clicked.connect(self.run_uncertainty)
        row2.addWidget(QLabel(tr("Relative width (±):")))
        row2.addWidget(self.spn_unc_pct)
        row2.addWidget(QLabel(tr("Samples:")))
        row2.addWidget(self.spn_unc_n)
        row2.addStretch(1)
        ul.addLayout(row2)
        # Output selector + run on their own row so the controls don't force a very
        # wide minimum for the whole results panel.
        row3 = QHBoxLayout()
        row3.addWidget(QLabel(tr("Output:")))
        row3.addWidget(self.cmb_unc_output)
        row3.addWidget(btn_unc)
        row3.addStretch(1)
        ul.addLayout(row3)
        self.cv_unc = MplCanvas(width=6)
        ul.addWidget(self.cv_unc)
        self.lbl_unc_stats = QLabel("")
        self.lbl_unc_stats.setObjectName("subtle")
        ul.addWidget(self.lbl_unc_stats)
        tabs.addTab(unc_tab, tr("🎲  Uncertainty"))

        # --- Compare tab ---------------------------------------------
        cmp_tab = QWidget()
        cl = QVBoxLayout(cmp_tab)
        cbtns = QHBoxLayout()
        btn_snap = QPushButton(tr("Snapshot current scenario"))
        btn_snap.clicked.connect(self.snapshot_scenario)
        btn_clear = QPushButton(tr("Clear"))
        btn_clear.clicked.connect(self.clear_snapshots)
        cbtns.addWidget(btn_snap)
        cbtns.addWidget(btn_clear)
        cbtns.addStretch(1)
        cl.addLayout(cbtns)
        self.tbl_compare = QTableWidget(len(KPI_ORDER), 0)
        self.tbl_compare.setVerticalHeaderLabels(KPI_ORDER)
        cl.addWidget(self.tbl_compare)
        tabs.addTab(cmp_tab, tr("⚖  Compare"))

        v.addWidget(tabs, 1)
        return panel

    def run_uncertainty(self):
        selected = [
            (p, self.spn_unc_pct.value() / 100.0)
            for p in PARAMETERS if self.unc_checks[p.name].isChecked()
        ]
        if not selected:
            return
        out_name = self.cmb_unc_output.currentText()
        mc = run_montecarlo(
            self.build_scenario(), selected,
            outputs={out_name: OUTPUTS[out_name]}, n=self.spn_unc_n.value(),
        )
        vals = mc.series[out_name]
        s = mc.stats(out_name)
        self._last_uncertainty = {
            "output": out_name, "n": mc.n, "vals": list(vals), "stats": dict(s),
        }
        ax = self.cv_unc.reset()
        ax.hist(vals, bins=30, color=ACCENT, alpha=0.85)
        for q, col in ((s["p10"], "#888888"), (s["p50"], "#c0392b"), (s["p90"], "#888888")):
            ax.axvline(q, color=col, linestyle="--", linewidth=1)
        ax.set_title(f"{out_name}   (n = {mc.n})", fontsize=10)
        ax.set_xlabel(out_name, fontsize=9)
        ax.tick_params(labelsize=8)
        self.cv_unc.refresh()
        self.lbl_unc_stats.setText(
            f"P10: {s['p10']:,.2f}   ·   P50 (median): {s['p50']:,.2f}   ·   "
            f"P90: {s['p90']:,.2f}   ·   mean: {s['mean']:,.2f}   ·   std: {s['std']:,.2f}"
        )

    def snapshot_scenario(self):
        kpis = scenario_kpis(self.results)
        n = len(self._snapshots) + 1
        label = f"{n}: {self.organism.name.split()[0]}/{self.system.name.split()[0]}"
        self._snapshots.append((label, kpis))
        self._refresh_compare()

    def clear_snapshots(self):
        self._snapshots = []
        self._refresh_compare()

    def _refresh_compare(self):
        self.tbl_compare.setColumnCount(len(self._snapshots))
        self.tbl_compare.setHorizontalHeaderLabels([lbl for lbl, _ in self._snapshots])
        self.tbl_compare.setRowCount(len(KPI_ORDER))
        self.tbl_compare.setVerticalHeaderLabels(KPI_ORDER)
        for c, (_, kpis) in enumerate(self._snapshots):
            for r_i, metric in enumerate(KPI_ORDER):
                item = QTableWidgetItem(f"{kpis.get(metric, float('nan')):,.2f}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_compare.setItem(r_i, c, item)
        self.tbl_compare.resizeColumnsToContents()

    def run_sensitivity(self):
        base = self.build_scenario()
        param = next(p for p in PARAMETERS if p.name == self.cmb_sens_param.currentText())
        values = param.default_range(base)
        points = run_sweep(base, param, values)
        getter = OUTPUTS[self.cmb_sens_output.currentText()]
        xs = [pt.value for pt in points]
        ys = [getter(pt.results) for pt in points]
        self._last_sensitivity = {
            "param": param.name, "unit": param.unit,
            "output": self.cmb_sens_output.currentText(), "xs": xs, "ys": ys,
        }
        ax = self.cv_sens.reset()
        ax.plot(xs, ys, marker="o", color=ACCENT)
        ax.axhline(0, color="#bbbbbb", linewidth=0.8)
        ax.set_xlabel(f"{param.name} ({param.unit})", fontsize=9)
        ax.set_ylabel(self.cmb_sens_output.currentText(), fontsize=9)
        ax.set_title(
            f"{self.cmb_sens_output.currentText()} vs {param.name}", fontsize=10
        )
        ax.tick_params(labelsize=8)
        ax.grid(True, alpha=0.3)
        self.cv_sens.refresh()

    # ------------------------------------------------------------------ #
    # Signal handlers
    # ------------------------------------------------------------------ #
    def _on_field(self, obj: str, attr: str, value):
        setattr(getattr(self, obj), attr, value)
        if not self._loading:
            self.recompute()

    def _on_scale(self, value: float):
        self.scale = value
        if not self._loading:
            self.recompute()

    def _on_price(self, value: float):
        self.product_price = value
        if not self._loading:
            self.recompute()

    def _on_coproduct(self, value: float):
        self.coproduct_revenue = value
        if not self._loading:
            self.recompute()

    def _on_extraction_tech(self, name: str):
        """Selecting a technology preset seeds the editable solvent-price field."""
        preset = self.lib.extraction.get(name)
        if preset is not None:
            self.spn_solvent_price.blockSignals(True)
            self.spn_solvent_price.setValue(preset.solvent_price)
            self.spn_solvent_price.blockSignals(False)
        self._on_extraction_change()

    def _on_extraction_change(self, *_):
        if self._loading:
            return
        self.extraction, self.products = self._build_extraction()
        self.recompute()

    def apply_scenario(self, scn: Scenario):
        """Load a Scenario object (e.g. from the setup wizard) into the UI state."""
        self._loading = True
        self._last_sensitivity = self._last_uncertainty = None  # stale on a new case
        self.organism = copy.deepcopy(scn.organism)
        self.system = copy.deepcopy(scn.system)
        self.harvesting = copy.deepcopy(scn.harvesting)
        self.drying = copy.deepcopy(scn.drying)
        self.economics = copy.deepcopy(scn.economics)
        self.lcia = copy.deepcopy(scn.lcia)
        self.scale = scn.scale
        self.extraction = copy.deepcopy(scn.extraction)
        self.products = [copy.deepcopy(p) for p in scn.products]
        self.batch_mode = scn.batch_mode
        self.batch_size_kg = scn.batch_size_kg or 1000.0
        self.batch_cycle_time_h = scn.batch_cycle_time_h or 48.0
        self.coproduct_revenue = scn.coproduct_revenue_per_year
        main = next((p for p in self.products if p.is_main), None)
        self.product_price = main.price if main else scn.product_price
        sys_names = {m.name for m in self.system.materials}
        self.custom_materials = [copy.deepcopy(m) for m in scn.materials if m.name not in sys_names]

        self._sync_combo(self.cmb_org, self.organism.name)
        self._sync_combo(self.cmb_sys, self.system.name)
        self._sync_combo(self.cmb_harv, self.harvesting.name)
        self._sync_combo(self.cmb_dry, self.drying.name)
        for obj in ("organism", "system", "harvesting", "drying", "economics", "lcia"):
            self._refresh(obj)
        self.chk_extraction.setChecked(self.extraction.enabled)
        self.chk_batch.setChecked(self.batch_mode)
        if any(p.is_main and "protein" in p.name.lower() for p in self.products):
            self.cmb_downstream.setCurrentIndex(1)
        if self.extraction.name in self.lib.extraction:
            self._sync_combo(self.cmb_ext_tech, self.extraction.name)
        self.spn_solvent_price.blockSignals(True)
        self.spn_solvent_price.setValue(self.extraction.solvent_price)
        self.spn_solvent_price.blockSignals(False)
        self.cmb_alloc.setCurrentText(self.extraction.allocation)
        for spn, val in ((self.spn_scale, self.scale), (self.spn_price, self.product_price),
                         (self.spn_coproduct, self.coproduct_revenue),
                         (self.spn_batch_size, self.batch_size_kg),
                         (self.spn_batch_cycle, self.batch_cycle_time_h)):
            spn.blockSignals(True)
            spn.setValue(val)
            spn.blockSignals(False)
        self._update_basis_labels()
        self._update_custom_label()
        self._loading = False
        self.recompute()

    def _on_batch_change(self, *_):
        if self._loading:
            return
        self.batch_mode = self.chk_batch.isChecked()
        self.batch_size_kg = self.spn_batch_size.value()
        self.batch_cycle_time_h = self.spn_batch_cycle.value()
        self.recompute()

    def edit_materials(self):
        headers = ["Name", "kg per kg product", "€/kg", "GWP kgCO₂/kg", "CED MJ/kg"]
        rows = [[m.name, m.amount_per_kg, m.price, m.gwp, m.ced] for m in self.custom_materials]
        dlg = TableEditorDialog(tr("Media / materials editor"), headers, rows, self)
        if dlg.exec():
            mats = []
            for row in dlg.result_rows():
                try:
                    mats.append(Material(
                        name=row[0].strip(), amount_per_kg=float(row[1] or 0),
                        price=float(row[2] or 0), gwp=float(row[3] or 0), ced=float(row[4] or 0),
                    ))
                except (ValueError, IndexError):
                    continue
            self.custom_materials = mats
            self._update_custom_label()
            self.recompute()

    def edit_products(self):
        headers = ["Name", "Fraction", "Recovery", "Price €/kg", "Main (1/0)", "Yield override"]
        rows = [[p.name, p.fraction, p.recovery, p.price, int(p.is_main), p.yield_override]
                for p in self.products]
        dlg = TableEditorDialog(tr("Products editor"), headers, rows, self,
                                hint="Fraction: lipid | protein | carbohydrate | ash | biomass | "
                                     "residual | custom.  Yield override (kg/kg) used if > 0.")
        if dlg.exec():
            prods = []
            for row in dlg.result_rows():
                try:
                    prods.append(Product(
                        name=row[0].strip(), fraction=(row[1].strip() or "custom"),
                        recovery=float(row[2] or 1.0), price=float(row[3] or 0.0),
                        is_main=bool(int(float(row[4] or 0))),
                        yield_override=float(row[5] or 0.0),
                    ))
                except (ValueError, IndexError):
                    continue
            self.products = prods
            self._update_custom_label()
            self.recompute()

    def _update_custom_label(self):
        parts = []
        if self.custom_materials:
            parts.append(f"{len(self.custom_materials)} custom material(s)")
        if self.products:
            parts.append(f"{len(self.products)} product(s)")
        self.lbl_custom.setText("  ·  ".join(parts) if parts else tr("No custom media or products defined."))

    def _build_extraction(self) -> tuple[Extraction, list[Product]]:
        """Construct the Extraction config and product list from the UI."""
        if not self.chk_extraction.isChecked():
            return Extraction(enabled=False), []
        # Take the process parameters (energy, solvent, CAPEX) from the selected
        # catalogue preset; keep the solvent price and allocation editable in the UI.
        preset = self.lib.extraction.get(self.cmb_ext_tech.currentText())
        ext = copy.deepcopy(preset) if preset is not None else Extraction(
            name="Solvent extraction", disruption_elec_kwh_per_kg=0.5, elec_kwh_per_kg=0.3,
            heat_mj_per_kg=2.0, solvent_name="Hexane", solvent_kg_per_kg=5.0,
            solvent_recovery=0.99, solvent_gwp=0.9, solvent_ced=55.0, capex_per_kgyr=1.0,
        )
        ext.enabled = True
        ext.solvent_price = self.spn_solvent_price.value()
        ext.allocation = self.cmb_alloc.currentText()
        protein_is_main = self.cmb_downstream.currentIndex() == 1
        oil = Product("Algal oil (lipid/PUFA)", "lipid", recovery=self.spn_oil_rec.value(),
                      price=self.spn_oil_price.value(), is_main=not protein_is_main)
        protein = Product("Protein meal/isolate", "protein", recovery=self.spn_prot_rec.value(),
                          price=self.spn_prot_price.value(), is_main=protein_is_main)
        residual = Product("Residual biomass", "residual", recovery=1.0, price=0.10)
        products = [protein, oil, residual] if protein_is_main else [oil, protein, residual]
        return ext, products

    def _refresh(self, obj: str):
        target = getattr(self, obj)
        for (o, a), sb in self._spins.items():
            if o == obj:
                sb.blockSignals(True)
                sb.setValue(float(getattr(target, a)))
                sb.blockSignals(False)
        for (o, a), cb in self._checks.items():
            if o == obj:
                cb.blockSignals(True)
                cb.setChecked(bool(getattr(target, a)))
                cb.blockSignals(False)
        if obj == "system":
            self._update_carbon_labels()

    def _on_organism(self, name: str):
        if name in self.lib.organisms:
            self.organism = copy.deepcopy(self.lib.organisms[name])
            self._refresh("organism")
            if not self._loading:
                self.recompute()

    def _on_system(self, name: str):
        if name not in self.lib.systems:
            return
        prev_basis = self.system.basis
        self.system = copy.deepcopy(self.lib.systems[name])
        self._refresh("system")
        self._update_basis_labels()
        if self.system.basis != prev_basis:
            self.scale = 100_000.0 if self.system.basis == Basis.AREA else 500.0
            self.spn_scale.blockSignals(True)
            self.spn_scale.setValue(self.scale)
            self.spn_scale.blockSignals(False)
        # Carry the system's seed selling price into the profitability input.
        if self.system.product_price:
            self.product_price = self.system.product_price
            self.spn_price.blockSignals(True)
            self.spn_price.setValue(self.product_price)
            self.spn_price.blockSignals(False)
        if not self._loading:
            self.recompute()

    def _on_harvesting(self, name: str):
        if name in self.lib.harvesting:
            self.harvesting = copy.deepcopy(self.lib.harvesting[name])
            self._refresh("harvesting")
            if not self._loading:
                self.recompute()

    def _on_drying(self, name: str):
        if name in self.lib.drying:
            self.drying = copy.deepcopy(self.lib.drying[name])
            self._refresh("drying")
            if not self._loading:
                self.recompute()

    def _update_basis_labels(self):
        if self.system.basis == Basis.AREA:
            self.lbl_prod.setText("Productivity (g/m²/d)")
            self.lbl_capex.setText("Cultivation CAPEX (€/m²)")
            self.lbl_scale.setText("Plant scale (m²)")
        else:
            self.lbl_prod.setText("Productivity (g/L/d)")
            self.lbl_capex.setText("Cultivation CAPEX (€/m³)")
            self.lbl_scale.setText("Plant scale (m³)")

    def _on_carbon_source(self, index: int):
        self.system.carbon_source = (
            CarbonSource.BICARBONATE if index == 1 else CarbonSource.CO2
        )
        self._update_carbon_labels()
        if not self._loading:
            self.recompute()

    def _on_heat_fuel(self, index: int):
        self.system.cultivation_heat_fuel = "electricity" if index == 1 else "natural_gas"
        if not self._loading:
            self.recompute()

    def _update_carbon_labels(self):
        """Sync the carbon-source & heat-fuel combos and relabel the utilization spin.

        ``co2_utilization`` is an *efficiency* (fraction of supplied inorganic
        carbon that is fixed), not an amount — the label makes that explicit for
        each carbon source so lowering it reads as 'less efficient', not 'less fed'.
        """
        is_bicarb = self.system.carbon_source == CarbonSource.BICARBONATE
        self.lbl_util.setText(
            tr("NaHCO₃ utilization") if is_bicarb else tr("CO₂ utilization")
        )
        self.cmb_carbon.blockSignals(True)
        self.cmb_carbon.setCurrentIndex(1 if is_bicarb else 0)
        self.cmb_carbon.blockSignals(False)
        self.cmb_heatfuel.blockSignals(True)
        self.cmb_heatfuel.setCurrentIndex(1 if self.system.cultivation_heat_fuel == "electricity" else 0)
        self.cmb_heatfuel.blockSignals(False)

    # ------------------------------------------------------------------ #
    # Compute + render
    # ------------------------------------------------------------------ #
    def build_scenario(self) -> Scenario:
        products = self.products
        materials = list(self.system.materials) + list(self.custom_materials)
        return Scenario(
            organism=self.organism,
            system=self.system,
            harvesting=self.harvesting,
            drying=self.drying,
            economics=self.economics,
            lcia=self.lcia,
            scale=self.scale,
            materials=materials,
            utilities=list(self.system.utilities),
            product_price=self.product_price,
            coproduct_revenue_per_year=self.coproduct_revenue,
            extraction=self.extraction,
            products=products,
            batch_mode=self.batch_mode,
            batch_size_kg=self.batch_size_kg,
            batch_cycle_time_h=self.batch_cycle_time_h,
        )

    def recompute(self):
        self.results = run_scenario(self.build_scenario())
        r = self.results
        unit = "m²" if self.system.basis == Basis.AREA else "m³"
        self.subtitle.setText(
            f"{self.organism.name}  ·  {self.system.name}  ·  {self.scale:,.0f} {unit}"
            f"  ·  functional unit: 1 kg dry biomass"
        )
        if r.inventory.batches_per_year:
            self.subtitle.setText(
                self.subtitle.text()
                + f"  ·  {r.inventory.batches_per_year:,.0f} batches/yr "
                  f"× {r.inventory.batch_product_kg:,.0f} kg"
            )
        pb = r.tea.payback_years
        if r.main_product:  # biorefinery mode: report per the main product
            self.kpi["cost"].set_value(f"{r.main_product.production_cost_eur_per_kg:,.2f}")
            self.kpi["gwp"].set_value(f"{r.main_product.gwp_kg_co2eq_per_kg:,.2f}")
            self.subtitle.setText(self.subtitle.text().replace(
                "1 kg dry biomass", f"1 kg {r.main_product.name}"))
        else:
            self.kpi["cost"].set_value(f"{r.tea.production_cost_eur_per_kg:,.2f}")
            self.kpi["gwp"].set_value(f"{r.lca.gwp_kg_co2eq_per_kg:,.2f}")
        self.kpi["npv"].set_value(f"{r.tea.npv / 1e6:,.1f}")
        self.kpi["payback"].set_value("∞" if pb == float("inf") else f"{pb:,.1f}")
        self.kpi["roi"].set_value(f"{r.tea.roi * 100:,.0f}")
        self.kpi["output"].set_value(f"{r.inventory.annual_biomass_kg / 1000:,.0f}")

        self._draw_tea(r)
        self._draw_lca(r)
        self._draw_inventory(r)
        self._draw_products(r)

    def _draw_tea(self, r):
        items = sorted(r.tea.opex_breakdown.items(), key=lambda kv: kv[1])
        labels = [k for k, _ in items]
        vals = [v / 1e6 for _, v in items]
        ax = self.cv_opex.reset()
        ax.barh(labels, vals, color=ACCENT)
        ax.set_title(tr("Annual cost breakdown (€ M/yr)"), fontsize=10)
        ax.tick_params(labelsize=8)
        self.cv_opex.refresh()

        cap = r.tea.capex_breakdown
        ax = self.cv_capex.reset()
        ax.pie(list(cap.values()), labels=list(cap.keys()),
               autopct="%1.0f%%", textprops={"fontsize": 7})
        ax.set_title(tr("CAPEX breakdown"), fontsize=10)
        self.cv_capex.refresh()

        # Itemised production-cost table. Unit cost is per kg of the reported product
        # (main product in a biorefinery, else dry biomass), matching the cost KPI.
        aoc = r.tea.annual_opex
        denom = r.main_product.annual_kg if r.main_product else r.inventory.annual_biomass_kg
        items = sorted(r.tea.opex_breakdown.items(), key=lambda kv: kv[1], reverse=True)
        summary = [
            (tr("Raw materials (subtotal)"), r.tea.raw_materials_cost),
            (tr("Annual operating cost"), aoc),
        ]
        self.tbl_tea.setRowCount(len(items) + len(summary))

        def _cost_row(row, name, val, bold=False):
            per_kg = val / denom if denom else 0.0
            pct = val / aoc * 100.0 if aoc else 0.0
            cells = [name, f"{per_kg:,.3f}", _money(val), f"{pct:,.1f}%"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if bold:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.tbl_tea.setItem(row, c, item)

        for i, (name, val) in enumerate(items):
            _cost_row(i, name, val)
        for j, (name, val) in enumerate(summary):
            _cost_row(len(items) + j, name, val, bold=True)
        self.tbl_tea.resizeColumnsToContents()
        self.tbl_tea.horizontalHeader().setStretchLastSection(True)

        irr_txt = "n/a" if r.tea.irr is None else f"{r.tea.irr * 100:,.1f}%"
        pb = "∞" if r.tea.payback_years == float("inf") else f"{r.tea.payback_years:,.1f} yr"
        mepp = minimum_selling_price(r.scenario)
        mepp_txt = "n/a" if mepp is None else f"€ {mepp:,.2f}/kg"
        self.lbl_tea_totals.setText(
            f"Total investment: {_money(r.tea.total_investment)}   ·   "
            f"AOC: {_money(r.tea.annual_opex)}/yr   ·   "
            f"Revenues: {_money(r.tea.revenues)}/yr   ·   "
            f"Net profit: {_money(r.tea.net_profit)}/yr\n"
            f"NPV: {_money(r.tea.npv)}   ·   IRR: {irr_txt}   ·   "
            f"ROI: {r.tea.roi * 100:,.1f}%   ·   Payback: {pb}   ·   "
            f"Net production cost: € {r.tea.net_production_cost_eur_per_kg:,.2f}/kg   ·   "
            f"Break-even price (MEPP): {mepp_txt}"
        )

    def _draw_lca(self, r):
        items = sorted(r.lca.gwp_breakdown.items(), key=lambda kv: kv[1])
        labels = [k for k, _ in items]
        vals = [v for _, v in items]
        colors = [NEG if v < 0 else POS for v in vals]
        ax = self.cv_gwp.reset()
        ax.barh(labels, vals, color=colors)
        ax.axvline(r.lca.gwp_kg_co2eq_per_kg, color="#333", linestyle="--", linewidth=1)
        ax.set_title(tr("GWP contribution (kg CO₂-eq / kg biomass)"), fontsize=10)
        ax.tick_params(labelsize=8)
        self.cv_gwp.refresh()

        self.lbl_lca_totals.setText(
            f"Net GWP: {r.lca.gwp_kg_co2eq_per_kg:,.2f} kg CO₂-eq/kg     ·     "
            f"CED: {r.lca.ced_mj_per_kg:,.1f} MJ/kg     ·     "
            f"Water: {r.lca.water_m3_per_kg:,.2f} m³/kg     ·     "
            f"Land: {r.lca.land_m2a_per_kg:,.2f} m²·a/kg"
        )

        impacts = r.lca.impacts
        self.tbl_impacts.setRowCount(len(impacts))
        for i, (cat, val) in enumerate(impacts.items()):
            self.tbl_impacts.setItem(i, 0, QTableWidgetItem(cat))
            item = QTableWidgetItem(f"{val:,.4g}")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_impacts.setItem(i, 1, item)
        self.tbl_impacts.resizeColumnsToContents()

    def _draw_inventory(self, r):
        inv = r.inventory
        rows = [
            ("Electricity", inv.elec_kwh_per_kg, "kWh"),
            ("Heat (drying)", inv.heat_mj_per_kg, "MJ"),
            ("CO₂ supplied", inv.co2_supply_per_kg, "kg"),
            ("Bicarbonate (NaHCO₃) supplied", inv.bicarbonate_supply_per_kg, "kg"),
            ("CO₂ fixed (biogenic)", inv.co2_fixed_per_kg, "kg"),
            ("Nitrogen", inv.nitrogen_per_kg, "kg"),
            ("Phosphorus", inv.phosphorus_per_kg, "kg"),
            ("Water", inv.water_m3_per_kg, "m³"),
            ("Substrate (glucose)", inv.substrate_per_kg, "kg"),
        ]
        for m in r.scenario.materials:
            rows.append((f"  {m.name}", m.amount_per_kg, "kg"))
        for u in r.scenario.utilities:
            rows.append((f"  {u.name}", u.amount_per_kg, u.unit))
        rows.append(("Land occupation", inv.land_m2a_per_kg, "m²·a"))
        self.tbl_inv.setRowCount(len(rows))
        for i, (name, val, unit) in enumerate(rows):
            self.tbl_inv.setItem(i, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(f"{val:,.3f}")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_inv.setItem(i, 1, item)
            self.tbl_inv.setItem(i, 2, QTableWidgetItem(unit))
        self.tbl_inv.resizeColumnsToContents()

        ax = self.cv_elec.reset()
        stages = inv.elec_breakdown
        ax.bar(list(stages.keys()), list(stages.values()), color=ACCENT)
        ax.set_title(tr("Electricity by stage (kWh/kg)"), fontsize=10)
        ax.tick_params(labelsize=8)
        self.cv_elec.refresh()

    def _draw_products(self, r):
        self.lbl_products_hint.setVisible(not r.products)
        self.tbl_products.setRowCount(len(r.products))
        for i, p in enumerate(r.products):
            cells = [
                p.name,
                f"{p.annual_kg / 1000:,.0f}",
                f"{p.production_cost_eur_per_kg:,.2f}",
                f"{p.price:,.2f}",
                f"{p.allocation_share * 100:,.1f}",
                f"{p.gwp_kg_co2eq_per_kg:,.2f}",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if p.is_main:
                    from PySide6.QtGui import QFont
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.tbl_products.setItem(i, c, item)
        self.tbl_products.resizeColumnsToContents()

    # ------------------------------------------------------------------ #
    # File actions
    # ------------------------------------------------------------------ #
    def open_wizard(self):
        from desktop.wizard import SetupWizard

        wiz = SetupWizard(self.lib, self)
        if wiz.exec():
            self.apply_scenario(wiz.scenario)

    def change_language(self):
        from .i18n import LANGUAGES, current_language, save_language

        codes = list(LANGUAGES)
        names = [LANGUAGES[c] for c in codes]
        cur = current_language()
        idx = codes.index(cur) if cur in codes else 0
        name, ok = QInputDialog.getItem(self, tr("Language…"), tr("Select language"), names, idx, False)
        if ok:
            save_language(codes[names.index(name)])
            QMessageBox.information(self, tr("Language…"),
                                    tr("Language changed — restart the app to apply it fully."))

    def reset_defaults(self):
        self._loading = True
        self._last_sensitivity = self._last_uncertainty = None
        self.cmb_org.setCurrentIndex(0)
        self.cmb_sys.setCurrentIndex(0)
        self.cmb_harv.setCurrentIndex(0)
        self.cmb_dry.setCurrentIndex(0)
        self.organism = copy.deepcopy(self.lib.organisms[self.cmb_org.currentText()])
        self.system = copy.deepcopy(self.lib.systems[self.cmb_sys.currentText()])
        self.harvesting = copy.deepcopy(self.lib.harvesting[self.cmb_harv.currentText()])
        self.drying = copy.deepcopy(self.lib.drying[self.cmb_dry.currentText()])
        self.economics = copy.deepcopy(self.lib.economics)
        self.lcia = copy.deepcopy(self.lib.lcia)
        self.scale = 100_000.0 if self.system.basis == Basis.AREA else 500.0
        self.product_price = self.system.product_price
        self.coproduct_revenue = 0.0
        for obj in ("organism", "system", "harvesting", "drying", "economics", "lcia"):
            self._refresh(obj)
        for spn, val in ((self.spn_scale, self.scale),
                         (self.spn_price, self.product_price),
                         (self.spn_coproduct, self.coproduct_revenue)):
            spn.blockSignals(True)
            spn.setValue(val)
            spn.blockSignals(False)
        self._update_basis_labels()
        self._loading = False
        self.recompute()

    def save_scenario(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Save scenario"), "scenario.json", "JSON (*.json)")
        if not path:
            return
        data = {
            "organism": asdict(self.organism),
            "system": asdict(self.system),
            "harvesting": asdict(self.harvesting),
            "drying": asdict(self.drying),
            "economics": asdict(self.economics),
            "lcia": asdict(self.lcia),
            "scale": self.scale,
            "product_price": self.product_price,
            "coproduct_revenue": self.coproduct_revenue,
        }
        Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        self.statusBar().showMessage(f"Scenario saved to {path}", 5000)

    def load_scenario(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Open scenario"), "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.organism = _lib._organism(data["organism"])
            self.system = _lib._system(data["system"])
            self.harvesting = _lib._harvesting(data["harvesting"])
            self.drying = _lib._drying(data["drying"])
            self.economics = _lib._economics(data["economics"])
            self.lcia = _lib._lcia(data["lcia"])
            self.scale = float(data["scale"])
            self.product_price = float(data.get("product_price", self.system.product_price))
            self.coproduct_revenue = float(data.get("coproduct_revenue", 0.0))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load failed", f"Could not load scenario:\n{exc}")
            return

        self._loading = True
        self._sync_combo(self.cmb_org, self.organism.name)
        self._sync_combo(self.cmb_sys, self.system.name)
        self._sync_combo(self.cmb_harv, self.harvesting.name)
        self._sync_combo(self.cmb_dry, self.drying.name)
        for obj in ("organism", "system", "harvesting", "drying", "economics", "lcia"):
            self._refresh(obj)
        for spn, val in ((self.spn_scale, self.scale),
                         (self.spn_price, self.product_price),
                         (self.spn_coproduct, self.coproduct_revenue)):
            spn.blockSignals(True)
            spn.setValue(val)
            spn.blockSignals(False)
        self._update_basis_labels()
        self._loading = False
        self.recompute()
        self.statusBar().showMessage(f"Scenario loaded from {path}", 5000)

    @staticmethod
    def _sync_combo(combo: QComboBox, text: str):
        combo.blockSignals(True)
        idx = combo.findText(text)
        if idx < 0:
            combo.addItem(text)
            idx = combo.findText(text)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def export_process_report(self):
        """Export a shareable PDF: KPI summary + the Process Flow Diagram + streams."""
        import os
        import tempfile

        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export process report"), "process_report.pdf", "PDF (*.pdf)")
        if not path:
            return
        ed = self.flowsheet_editor
        # Make the diagram reflect the current case: (re)generate if it is still the
        # untouched starter, otherwise keep the user's diagram and just re-balance it.
        if ed._is_pristine():
            ed.generate_from_scenario(confirm=False)
        else:
            ed.solve_and_annotate()

        fd, png = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            from .report import build_process_report
            has_diagram = ed.render_diagram_png(png)
            mp = self.results.main_product
            title = (mp.name if mp else self.organism.name)
            # Gather every analysis the user has run so it lands in the report.
            extras: dict = {}
            if getattr(self, "_last_sensitivity", None):
                extras["sensitivity"] = self._last_sensitivity
            if getattr(self, "_last_uncertainty", None):
                extras["uncertainty"] = self._last_uncertainty
            if getattr(self, "_snapshots", None):
                extras["compare"] = {"order": KPI_ORDER, "snapshots": self._snapshots}
            build_process_report(
                path, self.results, self.build_scenario(),
                flowsheet=ed.scene.flowsheet,
                pfd_png=png if has_diagram else None,
                title=f"{title} — process report", extras=extras,
            )
            self.statusBar().showMessage(f"Report saved to {path}", 6000)
        except Exception as exc:
            QMessageBox.warning(self, tr("Export failed"),
                                f"Could not build the report:\n{exc}")
        finally:
            try:
                os.remove(png)
            except OSError:
                pass

    def export_results(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export results"), "results.json", "JSON (*.json)")
        if not path:
            return
        r = self.results
        out = {
            "scenario": {
                "organism": self.organism.name,
                "system": self.system.name,
                "scale": self.scale,
            },
            "annual_biomass_t": r.inventory.annual_biomass_kg / 1000,
            "tea": {
                "production_cost_eur_per_kg": r.tea.production_cost_eur_per_kg,
                "total_capex_eur": r.tea.total_capex,
                "annual_opex_eur": r.tea.annual_opex,
                "opex_breakdown_eur": r.tea.opex_breakdown,
                "capex_breakdown_eur": r.tea.capex_breakdown,
            },
            "lca_per_kg": {
                "gwp_kg_co2eq": r.lca.gwp_kg_co2eq_per_kg,
                "ced_mj": r.lca.ced_mj_per_kg,
                "water_m3": r.lca.water_m3_per_kg,
                "land_m2a": r.lca.land_m2a_per_kg,
                "gwp_breakdown": r.lca.gwp_breakdown,
            },
        }
        Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
        self.statusBar().showMessage(f"Results exported to {path}", 5000)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def load_bundled_reference(self, filename: str):
        path = DEFAULT_DATA_DIR / filename
        try:
            self.reference = parse_reference_csv(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Load failed"), str(exc))
            return
        self.show_comparison()

    def load_reference_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Load reference CSV"), "", "CSV (*.csv)")
        if not path:
            return
        try:
            self.reference = parse_reference_csv(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Load failed"), str(exc))
            return
        self.show_comparison()

    def load_superpro_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Import SuperPro Excel report"), "", "Excel (*.xlsx *.xls)"
        )
        if not path:
            return
        try:
            self.reference = parse_superpro_excel(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Import failed"), str(exc))
            return
        if not self.reference:
            QMessageBox.information(
                self, tr("Nothing found"),
                "Could not locate known metrics in that file. Try the reference "
                "CSV template instead (Validation menu).",
            )
            return
        self.show_comparison()

    def show_comparison(self):
        if not self.reference:
            QMessageBox.information(
                self, tr("No reference loaded"),
                "Load a SuperPro Excel report or a reference CSV first "
                "(Validation menu). A CSV template is in data/.",
            )
            return
        rows = compare(self.reference, self.results)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Validation vs reference (e.g. SuperPro)"))
        dlg.resize(680, 300)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels([tr("Metric"), tr("Reference"), tr("This tool"), "Δ %", tr("Fit")])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        colors = {"good": "#2e7d32", "fair": "#e08e0b", "poor": "#c0392b", "n/a": "#9aa7b0"}
        for i, row in enumerate(rows):
            ref = "—" if row.reference is None else f"{row.reference:,.2f}"
            pct = "—" if row.pct_diff is None else f"{row.pct_diff:+.1f}%"
            cells = [f"{row.label} ({row.unit})", ref, f"{row.model:,.2f}", pct, row.status]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 4:
                    item.setForeground(Qt.white if False else item.foreground())
                if c == 3 and row.pct_diff is not None:
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor(colors[row.status]))
                table.setItem(i, c, item)
        table.resizeColumnsToContents()
        lay.addWidget(QLabel(
            "Green ≤10%, amber ≤25%, red >25% deviation from the reference."
        ))
        lay.addWidget(table)
        dlg.exec()

    def show_benchmarks(self):
        from PySide6.QtGui import QColor

        rows = check_benchmarks(self.results)
        cat = infer_category(self.system).replace("_", " ")
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Open-literature benchmarks (per kg dry biomass)"))
        dlg.resize(760, 320)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            f"Category: <b>{cat}</b>. The model value should fall within the published "
            "range (green). Ranges are wide — read the source. Values ~USD≈EUR."
        ))
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels([tr("Metric"), tr("Model"), tr("Literature range"), tr("Fit"), tr("Source")])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        colors = {"within": "#2e7d32", "above": "#c0392b", "below": "#e08e0b"}
        labels = {"production_cost": "Production cost", "gwp": "GWP",
                  "ced": "Energy demand", "electricity": "Electricity"}
        for i, r in enumerate(rows):
            cells = [
                f"{labels.get(r.metric, r.metric)} ({r.unit})",
                f"{r.model:,.2f}",
                f"{r.low:g} – {r.high:g}",
                r.status,
                r.source,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in (1, 2):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3:
                    item.setForeground(QColor(colors.get(r.status, "#333333")))
                table.setItem(i, c, item)
        table.resizeColumnsToContents()
        lay.addWidget(table)
        n_ok = sum(1 for r in rows if r.in_range)
        lay.addWidget(QLabel(
            f"{n_ok}/{len(rows)} metrics within the published range."
        ))
        dlg.exec()

    def show_market_prices(self):
        prices = load_market_prices()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Indicative microalgal product prices"))
        dlg.resize(760, 320)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "Order-of-magnitude ranges to sanity-check selling prices (USD≈EUR). "
            "Broad and time-varying — read the source."
        ))
        table = QTableWidget(len(prices), 4)
        table.setHorizontalHeaderLabels([tr("Product"), tr("Range"), tr("Unit"), tr("Source")])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        for i, p in enumerate(prices):
            cells = [p.product, f"{p.low:g} – {p.high:g}", p.unit, p.source]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, c, item)
        table.resizeColumnsToContents()
        lay.addWidget(table)
        dlg.exec()

    def show_validation_references(self):
        refs = load_validation_references()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Validation library — published TEA/LCA studies"))
        dlg.resize(900, 360)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "Published Spirulina/microalgae studies this model has been checked against — "
            "the paper's reported value next to our model's output. Hover a paper for its system & link."
        ))
        headers = [tr("Paper"), tr("Type"), tr("Metric"),
                   tr("Paper value"), tr("Our model"), tr("Match")]
        table = QTableWidget(len(refs), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        for i, r in enumerate(refs):
            cells = [r.paper, r.type, r.metric, r.paper_value, r.model_value, r.match]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0 and (r.system or r.url):
                    item.setToolTip(f"{r.system}\n{r.url}".strip())
                if c >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, c, item)
        table.resizeColumnsToContents()
        lay.addWidget(table)
        if not refs:
            lay.addWidget(QLabel(tr("No validation references defined yet.")))
        dlg.exec()

    def show_about(self):
        QMessageBox.about(
            self, "About AlgaMetrix",
            "<b>AlgaMetrix</b><br>Open-source techno-economic &amp; life-cycle "
            "analysis for microalgae, cyanobacteria and thraustochytrid biomass.<br><br>"
            "One mass/energy balance feeds both the TEA and the LCA.<br>"
            "MIT licensed. Default values are literature-typical placeholders.",
        )
