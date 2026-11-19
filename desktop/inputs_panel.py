"""The input column: every scenario parameter, grouped by process step.

Builds the widgets onto the main window (``win.cmb_org``, ``win.spn_scale`` and
so on, the names the handlers and the tests use) and returns the column. The
numeric fields come from the catalogue in :mod:`desktop.fields`, so each one
carries its unit, its admissible range and its provenance.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .fields import plain_tooltip, spec
from .i18n import tr
from .widgets import Section, button, label


def number(lo: float, hi: float, value: float, step: float, decimals: int,
           slot=None, tooltip: str = "", grouped: bool = False) -> QDoubleSpinBox:
    """A numeric field with the app's conventions.

    Keyboard tracking is off: the value is committed when the user presses
    Enter, leaves the field or uses the arrows, so a half-typed number does not
    run the engine on every digit.
    """
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(value)
    sb.setKeyboardTracking(False)
    sb.setAccelerated(True)
    sb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if grouped:
        sb.setGroupSeparatorShown(True)
    if tooltip:
        sb.setToolTip(tooltip)
    if slot is not None:
        sb.valueChanged.connect(slot)
    return sb


def combo(items, tooltip: str = "", min_chars: int = 14) -> QComboBox:
    """A combo box that does not force the column as wide as its longest item."""
    cb = QComboBox()
    cb.addItems(list(items))
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(min_chars)
    if tooltip:
        cb.setToolTip(tooltip)
    return cb


def notes_label() -> QLabel:
    """The caption under a preset picker that shows the preset's own notes."""
    lbl = QLabel("")
    lbl.setObjectName("caption")
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


def build(win) -> QWidget:
    container = QWidget()
    container.setObjectName("page")
    root = QVBoxLayout(container)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(8)

    head = QHBoxLayout()
    head.setContentsMargins(2, 0, 2, 0)
    head.addWidget(label(tr("Inputs"), "h1"))
    head.addStretch(1)
    win.lbl_input_count = label("", "caption")
    head.addWidget(win.lbl_input_count)
    root.addLayout(head)

    win.input_search = QLineEdit()
    win.input_search.setObjectName("search")
    win.input_search.setPlaceholderText("Find a parameter  (Ctrl+F)")
    win.input_search.setClearButtonEnabled(True)
    win.input_search.setToolTip("Type part of a parameter name to show only matching rows.")
    win.input_search.textChanged.connect(win._filter_inputs)
    root.addWidget(win.input_search)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()
    inner.setObjectName("page")
    col = QVBoxLayout(inner)
    col.setContentsMargins(2, 2, 6, 2)
    col.setSpacing(10)
    win.sections = []

    def section(title, step, description="", expanded=True):
        s = Section(title, step, description, expanded=expanded)
        win.sections.append(s)
        col.addWidget(s)
        return s

    def spin_row(s, obj, attr, text=None):
        """A catalogued numeric field, labelled and tagged with its unit."""
        fs = spec(obj, attr)
        sb = win._spin(obj, attr)
        unit = fs.unit_for(win._basis_key())
        lbl = s.add_row(text if text is not None else tr(fs.label), sb, unit, sb.toolTip())
        return sb, lbl

    # --- 1 Organism ----------------------------------------------------------
    s = section(tr("Organism"), 1,
                "Strain and composition. The elemental fractions drive the carbon and "
                "nutrient demand of the whole plant.")
    win.cmb_org = combo(list(win.lib.organisms),
                        plain_tooltip("Strain", "A strain from data/organisms.yaml. Picking one "
                                      "loads its composition into the fields below, which stay "
                                      "editable."))
    win.cmb_org.currentTextChanged.connect(win._on_organism)
    s.add_row(tr("Strain"), win.cmb_org)
    win.lbl_org_notes = notes_label()
    s.add_widget(win.lbl_org_notes)
    for attr in ("carbon", "nitrogen", "phosphorus", "phycocyanin"):
        spin_row(s, "organism", attr)

    # --- 2 Cultivation -------------------------------------------------------
    s = section(tr("Cultivation"), 2,
                "The system, how well it runs, and how big it is. Fields a system does not "
                "read are greyed out and say why.")
    win.cmb_sys = combo(list(win.lib.systems),
                        plain_tooltip("Cultivation system", "A pond, photobioreactor or "
                                      "fermenter from data/systems.yaml. It sets the sizing basis "
                                      "(area or volume), the trophic mode and the defaults below."))
    win.cmb_sys.currentTextChanged.connect(win._on_system)
    win.sec_cultivation = s
    s.add_row(tr("System"), win.cmb_sys)
    win.lbl_sys_notes = notes_label()
    s.add_widget(win.lbl_sys_notes)
    sb, win.lbl_prod = spin_row(s, "system", "productivity")
    win.spn_productivity = sb
    spin_row(s, "system", "operating_days")
    spin_row(s, "system", "elec_kwh_per_kg")
    win.cmb_carbon = combo([tr("CO₂ (gas)"), tr("Sodium bicarbonate (NaHCO₃)")],
                           plain_tooltip("Carbon source", "Gaseous CO₂ sparged into the culture, "
                                         "or dissolved sodium bicarbonate as used for alkaline "
                                         "cultures such as Arthrospira. Only a phototrophic "
                                         "system reads it."))
    win.cmb_carbon.currentIndexChanged.connect(win._on_carbon_source)
    s.add_row(tr("Carbon source"), win.cmb_carbon)
    sb, win.lbl_util = spin_row(s, "system", "co2_utilization", tr("CO₂ utilization"))
    spin_row(s, "system", "nutrient_uptake")
    spin_row(s, "system", "water_m3_per_kg")
    spin_row(s, "system", "cultivation_heat_mj_per_kg")
    win.cmb_heatfuel = combo([tr("Natural gas"), tr("Electricity")],
                             plain_tooltip("Heat fuel", "What supplies the cultivation heat. It "
                                           "routes the burden and the price of that heat."))
    win.cmb_heatfuel.currentIndexChanged.connect(win._on_heat_fuel)
    s.add_row(tr("Heat fuel"), win.cmb_heatfuel)
    spin_row(s, "system", "substrate_yield")
    sb, win.lbl_capex = spin_row(s, "system", "capex_per_unit")
    win.spn_capex = sb
    scale_spec = spec("scenario", "scale")
    win.spn_scale = number(scale_spec.lo, scale_spec.hi, win.scale, 1000.0, 0,
                           win._on_scale, grouped=True)
    win.spn_scale.setToolTip(win._tooltip_for(scale_spec))
    win.lbl_scale = s.add_row(tr("Plant scale"), win.spn_scale, scale_spec.unit_for(win._basis_key()),
                              win.spn_scale.toolTip())

    # --- 3 Harvest and drying ------------------------------------------------
    s = section(tr("Harvest and drying"), 3,
                "Dewatering and, if the product is dried, the dryer. Together they fix the "
                "water the plant has to remove and the biomass it loses on the way.")
    win.cmb_harv = combo(list(win.lib.harvesting),
                         plain_tooltip("Harvesting", "A dewatering train from data/parameters.yaml."))
    win.cmb_harv.currentTextChanged.connect(win._on_harvesting)
    s.add_row(tr("Harvesting"), win.cmb_harv)
    win.lbl_harv_notes = notes_label()
    s.add_widget(win.lbl_harv_notes)
    spin_row(s, "harvesting", "recovery")
    spin_row(s, "harvesting", "elec_kwh_per_kg")
    spin_row(s, "harvesting", "final_solids")
    win.cmb_dry = combo(list(win.lib.drying),
                        plain_tooltip("Drying", "A dryer from data/parameters.yaml, or no drying: "
                                      "the product then leaves as a wet paste and every result "
                                      "is still per kg of dry matter."))
    win.cmb_dry.currentTextChanged.connect(win._on_drying)
    s.add_row(tr("Drying"), win.cmb_dry)
    win.lbl_dry_notes = notes_label()
    s.add_widget(win.lbl_dry_notes)
    s.add_row("", win._check("drying", "enabled", "Drying enabled"))
    spin_row(s, "drying", "thermal_mj_per_kg_water")
    spin_row(s, "drying", "final_solids")

    # --- 4 Downstream extraction and products ---------------------------------
    s = section(tr("Downstream extraction and products"), 4,
                "Split the biomass into a main product and co-products. The cost and the "
                "GWP are then reported per kg of the main product.")
    win.chk_extraction = QCheckBox("Enable extraction and co-products")
    win.chk_extraction.toggled.connect(win._on_extraction_toggled)
    s.add_row("", win.chk_extraction)
    win.cmb_ext_tech = combo(list(win.lib.extraction), tr(
        "Downstream extraction technology (hexane, ethanol, supercritical CO2, "
        "bead-milling, ultrafiltration, chromatography). Sets the energy, solvent "
        "and CAPEX of the extraction step from the literature-anchored catalogue."))
    win.cmb_ext_tech.currentTextChanged.connect(win._on_extraction_tech)
    s.add_row(tr("Extraction technology"), win.cmb_ext_tech)
    win.lbl_ext_notes = notes_label()
    s.add_widget(win.lbl_ext_notes)
    win.cmb_downstream = combo([tr("Oil / lipid → main product"), tr("Protein → main product")],
                               plain_tooltip("Target product", "Which product carries the "
                                             "reported cost and GWP. It moves the main flag; it "
                                             "renames nothing."))
    win.cmb_downstream.currentTextChanged.connect(win._on_target_product)
    s.add_row(tr("Target product"), win.cmb_downstream)
    win.spn_oil_rec = number(0.0, 1.0, 0.90, 0.05, 2, win._on_product_fields,
                             plain_tooltip("Oil recovery", "Share of the lipid fraction of the "
                                           "biomass that ends up in the oil product."))
    s.add_row(tr("Oil (lipid) recovery"), win.spn_oil_rec, "fraction (0-1)")
    win.spn_oil_price = number(0.0, 1e6, 2.50, 0.1, 2, win._on_product_fields,
                               plain_tooltip("Oil price", "Selling price of the oil product."))
    s.add_row(tr("Oil price"), win.spn_oil_price, "€/kg")
    win.spn_prot_rec = number(0.0, 1.0, 0.80, 0.05, 2, win._on_product_fields,
                              plain_tooltip("Protein recovery", "Share of the protein fraction "
                                            "of the biomass that ends up in the protein product."))
    s.add_row(tr("Protein recovery"), win.spn_prot_rec, "fraction (0-1)")
    win.spn_prot_price = number(0.0, 1e6, 0.60, 0.05, 2, win._on_product_fields,
                                plain_tooltip("Protein price", "Selling price of the protein product."))
    s.add_row(tr("Protein price"), win.spn_prot_price, "€/kg")
    win.spn_solvent_price = number(0.0, 100.0, 1.50, 0.1, 2, win._on_solvent_price,
                                   plain_tooltip("Solvent make-up price", "Price of the solvent "
                                                 "bought to replace what the recovery loses."))
    s.add_row(tr("Solvent make-up price"), win.spn_solvent_price, "€/kg")
    win.cmb_alloc = combo(["economic", "mass", "none"], tr(
        "How the operating cost and the environmental burden are split between "
        "the products. It changes how the results are attributed, never what "
        "the products are."))
    win.cmb_alloc.currentTextChanged.connect(win._on_allocation)
    s.add_row(tr("Allocation method"), win.cmb_alloc)
    win.lbl_products = notes_label()
    s.add_widget(win.lbl_products)

    # --- 5 Waste-derived nutrients and carbon ---------------------------------
    s = section(tr("Waste-derived nutrients and carbon"), 5,
                "Grow on an effluent or a food side-stream instead of buying nutrients. "
                "The biomass needs the same nutrients; what changes is what is bought, "
                "the fertiliser burden avoided and the money the stream brings or costs.")
    win.chk_waste = QCheckBox("Feed the culture on a waste stream")
    win.chk_waste.setToolTip(
        "Cover part of the nitrogen, phosphorus or carbon demand with an "
        "effluent or a food-industry side-stream instead of buying it. The "
        "biomass still needs the same nutrients: what changes is the purchase, "
        "the burden of making fertiliser, and the money the stream brings or costs.")
    win.chk_waste.toggled.connect(win._on_waste_toggled)
    s.add_row("", win.chk_waste)
    win.cmb_waste = combo(list(win.lib.waste_feeds), (
        "Municipal effluent, anaerobic digestate, or a food-industry side-stream "
        "(whey permeate, vinasse, potato fruit juice). Concentrations are "
        "literature central values: replace them with an analysis of your stream."))
    win.cmb_waste.currentTextChanged.connect(win._on_waste_preset)
    s.add_row(tr("Stream"), win.cmb_waste)
    win.lbl_waste_notes = notes_label()
    s.add_widget(win.lbl_waste_notes)
    win.cmb_waste_dosed = combo(["nitrogen", "phosphorus", "substrate"], (
        "Which demand fixes how much of the stream is dosed. One stream has one "
        "composition, so what it delivers of the other two follows from this "
        "choice - and any excess is discharged, not stored."))
    win.cmb_waste_dosed.currentTextChanged.connect(win._on_waste_change)
    s.add_row(tr("Dosed on"), win.cmb_waste_dosed)
    win.spn_waste_cov = number(0.0, 100.0, 100.0, 5.0, 0, win._on_waste_change, (
        "Share of that demand the stream is dosed to cover. Below 100% for a "
        "stream that is not available year-round, or whose colour or ammonia "
        "load caps how much of the culture it may make up."))
    win.spn_waste_cov.setSuffix(" %")
    s.add_row(tr("Coverage"), win.spn_waste_cov, "of the dosed demand")
    win.spn_waste_price = number(-1000.0, 1000.0, 0.0, 0.05, 3, win._on_waste_change, (
        "Price per m³ or per kg of stream. NEGATIVE means a gate fee: you are "
        "paid to accept it, which is how a works treating municipal effluent earns."))
    s.add_row(tr("Price (negative = gate fee)"), win.spn_waste_price, "€/unit")
    win.cmb_waste_conv = combo(["cut_off", "avoided_treatment"], (
        "cut_off: the waste enters burden-free and you carry only what you do "
        "yourself. avoided_treatment: system expansion, crediting the treatment "
        "you displace - both its emissions and its cost, since one boundary has "
        "to serve both analyses. Either way the credit is reported on its own "
        "line and kept out of the gross, so it can be taken back off."))
    win.cmb_waste_conv.currentTextChanged.connect(win._on_waste_change)
    s.add_row(tr("System boundary"), win.cmb_waste_conv)
    win.spn_waste_avoided = number(0.0, 1000.0, 0.0, 0.05, 3, win._on_waste_change, (
        "What treating this stream conventionally would have cost somebody, per "
        "unit. This is NOT money you receive - that is the price above - so it "
        "never enters the operating cost or the production cost. It lowers the "
        "net cost and the profit, and only under avoided_treatment."))
    s.add_row(tr("Treatment displaced"), win.spn_waste_avoided, "€/unit")
    win.lbl_waste = notes_label()
    s.add_widget(win.lbl_waste)

    # --- 6 Operation schedule ------------------------------------------------
    s = section(tr("Operation schedule"), 6,
                "Continuous operation follows scale × productivity × operating days; a "
                "batch schedule follows the batch size and the cycle time instead.")
    win.chk_batch = QCheckBox("Batch mode (else continuous)")
    win.chk_batch.toggled.connect(win._on_batch_change)
    s.add_row("", win.chk_batch)
    win.spn_batch_size = number(1.0, 1e7, win.batch_size_kg, 100.0, 0, win._on_batch_change,
                                plain_tooltip("Batch size", "Gross dry biomass produced per "
                                              "batch, before harvest losses."), grouped=True)
    s.add_row(tr("Batch size"), win.spn_batch_size, "kg gross / batch")
    win.spn_batch_cycle = number(1.0, 2000.0, win.batch_cycle_time_h, 1.0, 1, win._on_batch_change,
                                 plain_tooltip("Cycle time", "Hours from one batch start to the "
                                               "next, turnaround included."))
    s.add_row(tr("Cycle time"), win.spn_batch_cycle, "h")

    # --- 7 Economics -----------------------------------------------------------
    s = section(tr("Economics"), 7,
                "Prices, capital and finance. Amounts are in EUR exactly as entered: the "
                "model applies no inflation, no currency conversion and no price year.")
    s.add_heading("Prices")
    for attr in ("electricity_price", "heat_price", "co2_price", "bicarbonate_price",
                 "nitrogen_price", "phosphorus_price", "substrate_price", "water_price",
                 "land_price"):
        spin_row(s, "economics", attr)
    s.add_heading("Capital")
    for attr in ("harvest_capex_per_kgyr", "drying_capex_per_kgyr", "installation_factor",
                 "labor_cost_per_year", "maintenance_frac"):
        spin_row(s, "economics", attr)
    s.add_heading("Finance")
    for attr in ("discount_rate", "plant_lifetime", "depreciation_years", "tax_rate"):
        spin_row(s, "economics", attr)
    s.add_heading("Revenue")
    win.spn_price = number(0.0, 1e6, win.product_price, 0.5, 2, win._on_price, tr(
        "Selling price of the product the cost and GWP are reported per. In a "
        "multiproduct case this is the main product's price: changing it here "
        "changes that product's price, its revenue and the NPV."))
    win.lbl_price_row = s.add_row(tr("Product price"), win.spn_price, "€/kg",
                                  win.spn_price.toolTip())
    win.spn_coproduct = number(0.0, 1e9, win.coproduct_revenue, 50_000, 0, win._on_coproduct, tr(
        "Revenue from by-products that are NOT in the product list - sold "
        "residue, spent media, heat. Products defined in the biorefinery "
        "section already earn through their own price; this is on top of them."),
        grouped=True)
    s.add_row(tr("Other co-product revenue"), win.spn_coproduct, "€/yr")
    win.spn_credits = number(0.0, 1e9, win.credits_per_year, 50_000, 0, win._on_credits, tr(
        "Operating credits: energy or heat recovery, biogas, waste valorisation. "
        "They lower the NET operating cost and the profit, never the gross "
        "production cost."), grouped=True)
    s.add_row(tr("Operating credits"), win.spn_credits, "€/yr")
    win.spn_other_opex = number(0.0, 1e9, win.other_opex_per_year, 10_000, 0, win._on_other_opex, tr(
        "Annual operating costs that are neither per-kg materials/utilities nor "
        "labour: consumables, probes and filters, effluent treatment, "
        "contingencies. Enters the annual operating cost as its own category."),
        grouped=True)
    s.add_row(tr("Other operating cost"), win.spn_other_opex, "€/yr")

    # --- 8 Life-cycle background ----------------------------------------------
    s = section(tr("Life-cycle background"), 8,
                "Characterization factors from data/lcia.yaml. Each tooltip carries the "
                "factor's quality flag, geography, period and source.", expanded=True)
    for attr in ("elec_gwp", "elec_ced", "heat_gwp", "nitrogen_gwp", "phosphorus_gwp",
                 "co2_supply_gwp", "bicarbonate_gwp", "substrate_gwp"):
        spin_row(s, "lcia", attr)
    chk = win._check("lcia", "count_biogenic_uptake", "Credit biogenic CO₂ uptake at gate")
    chk.setToolTip(plain_tooltip(
        "Biogenic carbon", "Credit the CO₂ fixed into the product under the declared "
        "convention (see docs/CARBON_ACCOUNTING.md). Off, no credit is given and the "
        "GWP is the gross cradle-to-gate burden."))
    s.add_row("", chk)

    # --- Advanced: custom media and products ----------------------------------
    s = section(tr("Custom media and products"), None,
                "Media components, process chemicals and product definitions beyond the "
                "presets.", expanded=True)
    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(8)
    rl.addWidget(button(tr("Edit media / materials…"), "secondary", win.edit_materials,
                        "Add priced and characterised media components or chemicals."))
    rl.addWidget(button(tr("Edit products…"), "secondary", win.edit_products,
                        "Define the products the biomass is split into."))
    rl.addStretch(1)
    s.add_widget(row, "media materials products editor")
    win.lbl_custom = notes_label()
    win.lbl_custom.setText(tr("No custom media or products defined."))
    s.add_widget(win.lbl_custom)

    col.addStretch(1)
    scroll.setWidget(inner)
    scroll.setMinimumWidth(440)
    root.addWidget(scroll, 1)
    return container
