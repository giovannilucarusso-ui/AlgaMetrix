"""Guided setup wizard for a researcher's TEA/LCA case study.

Seven steps that build a scenario either from the closest validated example or
from scratch, then hand it to the main window. Every step is pre-filled.
"""

from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from microalgae_tea_lca.library import Library
from microalgae_tea_lca.models import Basis, Scenario
from microalgae_tea_lca.products import main_product
from microalgae_tea_lca.templates import (
    TEMPLATES,
    apply_goal,
    get_template,
    set_scale_from_target,
)

from desktop.i18n import tr

# region -> (electricity price EUR/kWh, grid GWP kg CO2-eq/kWh). Indicative values.
REGION_ELEC = {
    "Europe (EU average)": (0.15, 0.35),
    "Italy": (0.18, 0.32),
    "Spain": (0.14, 0.19),
    "France": (0.13, 0.06),
    "Germany": (0.20, 0.38),
    "United Kingdom": (0.17, 0.21),
    "United States": (0.10, 0.40),
    "China": (0.09, 0.55),
    "India": (0.10, 0.63),
    "Low-carbon grid (Nordics)": (0.12, 0.03),
    "Global average": (0.12, 0.45),
    "Custom / keep current": (None, None),
}


def _default_scenario(lib: Library) -> Scenario:
    sysm = lib.systems["Open raceway pond"]
    return Scenario(
        organism=copy.deepcopy(lib.organisms["Chlorella vulgaris"]),
        system=copy.deepcopy(sysm),
        harvesting=copy.deepcopy(lib.harvesting["Settling + centrifugation"]),
        drying=copy.deepcopy(lib.drying["Spray drying"]),
        economics=copy.deepcopy(lib.economics),
        lcia=copy.deepcopy(lib.lcia),
        scale=100_000.0, materials=list(sysm.materials), product_price=8.0,
    )


class StartPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Start your case study"))
        self.setSubTitle(tr("Begin from the closest validated example, or from scratch."))
        v = QVBoxLayout(self)
        self.grp = QButtonGroup(self)
        self.rb_example = QRadioButton(tr("Start from a validated example (recommended)"))
        self.rb_scratch = QRadioButton(tr("Build from scratch"))
        self.rb_example.setChecked(True)
        self.grp.addButton(self.rb_example)
        self.grp.addButton(self.rb_scratch)
        v.addWidget(self.rb_example)
        self.cmb = QComboBox()
        self.cmb.addItems([t.name for t in TEMPLATES])
        v.addWidget(self.cmb)
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setObjectName("subtle")
        v.addWidget(self.lbl)
        v.addSpacing(8)
        v.addWidget(self.rb_scratch)
        self.cmb.currentTextChanged.connect(self._describe)
        self.rb_example.toggled.connect(self.cmb.setEnabled)
        self._describe()

    def _describe(self):
        t = get_template(self.cmb.currentText())
        if t:
            self.lbl.setText(t.description + "\n" + tr("Validated against: {v}").format(v=t.validation))

    def validatePage(self):
        if self.rb_example.isChecked():
            self.wiz.scenario = get_template(self.cmb.currentText()).build(self.wiz.lib)
            self.wiz.from_example = self.cmb.currentText()
        else:
            self.wiz.scenario = _default_scenario(self.wiz.lib)
            self.wiz.from_example = None
        return True


class GoalPage(QWizardPage):
    LABELS = [("Whole biomass (food / feed)", "biomass"), ("Oil / omega-3", "oil"),
              ("Protein (single-cell protein)", "protein"),
              ("Pigment (phycocyanin, astaxanthin)", "pigment"), ("Biofuel (biodiesel)", "biofuel")]

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Product goal"))
        self.setSubTitle(tr("What is the main product? This sets up the downstream and products."))
        v = QVBoxLayout(self)
        self.grp = QButtonGroup(self)
        self.rbs = {}
        for text, key in self.LABELS:
            rb = QRadioButton(tr(text))
            self.grp.addButton(rb)
            v.addWidget(rb)
            self.rbs[key] = rb

    def initializePage(self):
        self.rbs.get(self.wiz.guess_goal(), self.rbs["biomass"]).setChecked(True)

    def validatePage(self):
        for key, rb in self.rbs.items():
            if rb.isChecked():
                if key != self.wiz.guess_goal():
                    apply_goal(self.wiz.scenario, key)
                self.wiz.goal = key
                return True
        return True


class OrganismPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Organism"))
        self.setSubTitle(tr("Pick a strain, then adjust its composition if you have your own data."))
        f = QFormLayout(self)
        self.cmb = QComboBox()
        self.cmb.addItems(list(wiz.lib.organisms))
        f.addRow(tr("Strain"), self.cmb)

        def _spin(hi, step, dec):
            sb = QDoubleSpinBox(); sb.setRange(0, hi); sb.setSingleStep(step); sb.setDecimals(dec)
            sb.valueChanged.connect(self._update_sum)
            return sb

        self.protein = _spin(1, 0.01, 3); self.lipid = _spin(1, 0.01, 3)
        self.carb = _spin(1, 0.01, 3); self.ash = _spin(1, 0.01, 3)
        self.c = _spin(1, 0.01, 3); self.n = _spin(0.3, 0.005, 3); self.p = _spin(0.1, 0.001, 3)
        f.addRow(tr("Protein (fraction DW)"), self.protein)
        f.addRow(tr("Lipid (fraction DW)"), self.lipid)
        f.addRow(tr("Carbohydrate (fraction DW)"), self.carb)
        f.addRow(tr("Ash (fraction DW)"), self.ash)
        f.addRow(tr("Carbon (fraction DW)"), self.c)
        f.addRow(tr("Nitrogen (fraction DW)"), self.n)
        f.addRow(tr("Phosphorus (fraction DW)"), self.p)
        self.lbl_sum = QLabel(); self.lbl_sum.setObjectName("subtle")
        f.addRow("", self.lbl_sum)
        self.cmb.currentTextChanged.connect(self._load_strain)

    def _fields(self):
        return {"protein": self.protein, "lipid": self.lipid, "carbohydrate": self.carb,
                "ash": self.ash, "carbon": self.c, "nitrogen": self.n, "phosphorus": self.p}

    def _load_strain(self, name):
        o = self.wiz.lib.organisms.get(name)
        if o:
            for attr, sb in self._fields().items():
                sb.blockSignals(True); sb.setValue(getattr(o, attr)); sb.blockSignals(False)
            self._update_sum()

    def _update_sum(self):
        s = self.protein.value() + self.lipid.value() + self.carb.value() + self.ash.value()
        self.lbl_sum.setText(tr("Composition sums to {s:.0%} (should be ~100%).").format(s=s))

    def initializePage(self):
        o = self.wiz.scenario.organism
        i = self.cmb.findText(o.name)
        if i >= 0:
            self.cmb.blockSignals(True); self.cmb.setCurrentIndex(i); self.cmb.blockSignals(False)
        for attr, sb in self._fields().items():
            sb.blockSignals(True); sb.setValue(getattr(o, attr)); sb.blockSignals(False)
        self._update_sum()

    def validatePage(self):
        org = copy.deepcopy(self.wiz.lib.organisms[self.cmb.currentText()])
        for attr, sb in self._fields().items():
            setattr(org, attr, sb.value())
        self.wiz.scenario.organism = org
        return True


class CultivationPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Cultivation & scale"))
        self.setSubTitle(tr("Choose the system, how to size the plant, and batch or continuous operation."))
        f = QFormLayout(self)
        self.form = f
        self.cmb_sys = QComboBox(); self.cmb_sys.addItems(list(wiz.lib.systems))
        f.addRow(tr("System"), self.cmb_sys)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([tr("By target production (t/yr)"), tr("By cultivation size")])
        f.addRow(tr("Specify scale"), self.cmb_mode)
        self.spn_target = QDoubleSpinBox(); self.spn_target.setRange(0.1, 1e7); self.spn_target.setDecimals(0)
        self.spn_target.setGroupSeparatorShown(True); self.spn_target.setValue(100)
        f.addRow(tr("Target product (t/yr)"), self.spn_target)
        self.spn_size = QDoubleSpinBox(); self.spn_size.setRange(1, 1e9); self.spn_size.setDecimals(0)
        self.spn_size.setGroupSeparatorShown(True)
        self.lbl_size = QLabel(tr("Cultivation size (m²)"))
        f.addRow(self.lbl_size, self.spn_size)
        self.cmb_batch = QComboBox(); self.cmb_batch.addItems([tr("Continuous"), tr("Batch")])
        f.addRow(tr("Operation"), self.cmb_batch)
        self.cmb_mode.currentIndexChanged.connect(self._toggle)
        self.cmb_sys.currentTextChanged.connect(self._sys_changed)

    def _toggle(self):
        target = self.cmb_mode.currentIndex() == 0
        self.form.setRowVisible(self.spn_target, target)
        self.form.setRowVisible(self.spn_size, not target)

    def _sys_changed(self, name):
        s = self.wiz.lib.systems.get(name)
        if s:
            self.lbl_size.setText(tr("Reactor volume (m³)") if s.basis == Basis.VOLUME else tr("Cultivation size (m²)"))
            self.cmb_batch.setCurrentIndex(1 if s.mode.value == "heterotrophic" else 0)

    def initializePage(self):
        s = self.wiz.scenario.system
        i = self.cmb_sys.findText(s.name)
        if i >= 0:
            self.cmb_sys.setCurrentIndex(i)
        self.spn_size.setValue(self.wiz.scenario.scale)
        self.cmb_batch.setCurrentIndex(1 if self.wiz.scenario.batch_mode else 0)
        self._sys_changed(s.name); self._toggle()

    def validatePage(self):
        scn = self.wiz.scenario
        scn.system = copy.deepcopy(self.wiz.lib.systems[self.cmb_sys.currentText()])
        scn.materials = list(scn.system.materials)
        scn.utilities = list(scn.system.utilities)
        scn.batch_mode = self.cmb_batch.currentIndex() == 1
        if scn.batch_mode and scn.batch_cycle_time_h <= 0:
            scn.batch_cycle_time_h, scn.batch_size_kg = 48.0, 1000.0
        if self.cmb_mode.currentIndex() == 0:
            set_scale_from_target(scn, self.spn_target.value())
        else:
            scn.scale = self.spn_size.value()
        return True


class DownstreamPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Downstream"))
        self.setSubTitle(tr("How the biomass is harvested, dried and (if needed) processed into the product."))
        f = QFormLayout(self)
        self.cmb_harv = QComboBox(); self.cmb_harv.addItems(list(wiz.lib.harvesting))
        self.cmb_dry = QComboBox(); self.cmb_dry.addItems(list(wiz.lib.drying))
        f.addRow(tr("Harvesting"), self.cmb_harv)
        f.addRow(tr("Drying"), self.cmb_dry)
        self.cmb_ext = QComboBox(); self.cmb_ext.addItems(list(wiz.lib.extraction))
        f.addRow(tr("Extraction technology"), self.cmb_ext)
        self.lbl = QLabel(); self.lbl.setObjectName("subtle"); self.lbl.setWordWrap(True)
        f.addRow("", self.lbl)

    def _guess_preset(self, ext) -> str | None:
        """Best-matching catalogue preset for the goal-set extraction, by solvent."""
        if ext.name in self.wiz.lib.extraction:
            return ext.name
        s = (ext.solvent_name or "").lower()
        for name, preset in self.wiz.lib.extraction.items():
            if preset.solvent_name.lower() == s:
                return name
        return next(iter(self.wiz.lib.extraction), None)

    def initializePage(self):
        self.cmb_harv.setCurrentText(self.wiz.scenario.harvesting.name)
        self.cmb_dry.setCurrentText(self.wiz.scenario.drying.name)
        ext = self.wiz.scenario.extraction
        match = self._guess_preset(ext) if ext.enabled else None
        if match:
            self.cmb_ext.setCurrentText(match)
        self.cmb_ext.setEnabled(ext.enabled)
        self.lbl.setText(
            tr("Extraction step active — pick the technology above.") if ext.enabled
            else tr("No extraction for this product goal (whole biomass / protein).")
        )

    def validatePage(self):
        self.wiz.scenario.harvesting = copy.deepcopy(self.wiz.lib.harvesting[self.cmb_harv.currentText()])
        self.wiz.scenario.drying = copy.deepcopy(self.wiz.lib.drying[self.cmb_dry.currentText()])
        ext = self.wiz.scenario.extraction
        preset = self.wiz.lib.extraction.get(self.cmb_ext.currentText())
        if ext.enabled and preset is not None:
            # Apply the chosen technology's process parameters; keep the goal's
            # allocation method (products were already set by the product goal).
            new_ext = copy.deepcopy(preset)
            new_ext.enabled = True
            new_ext.allocation = ext.allocation
            self.wiz.scenario.extraction = new_ext
        return True


class ContextPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Economic & environmental context"))
        self.setSubTitle(tr("Regional energy, finance and selling price. Defaults are fine to start."))
        f = QFormLayout(self)
        self.cmb_region = QComboBox(); self.cmb_region.addItems(list(REGION_ELEC))
        f.addRow(tr("Region (electricity)"), self.cmb_region)
        self.spn_disc = QDoubleSpinBox(); self.spn_disc.setRange(0, 0.25); self.spn_disc.setSingleStep(0.01); self.spn_disc.setDecimals(3)
        self.spn_life = QDoubleSpinBox(); self.spn_life.setRange(1, 40); self.spn_life.setDecimals(0)
        self.spn_price = QDoubleSpinBox(); self.spn_price.setRange(0, 100000); self.spn_price.setDecimals(2)
        f.addRow(tr("Discount rate"), self.spn_disc)
        f.addRow(tr("Plant lifetime (yr)"), self.spn_life)
        f.addRow(tr("Product selling price (€/kg)"), self.spn_price)

    def initializePage(self):
        scn = self.wiz.scenario
        self.spn_disc.setValue(scn.economics.discount_rate)
        self.spn_life.setValue(scn.economics.plant_lifetime)
        mp = main_product(scn)
        self.spn_price.setValue(mp.price if mp else scn.product_price)

    def validatePage(self):
        scn = self.wiz.scenario
        price, gwp = REGION_ELEC[self.cmb_region.currentText()]
        if price is not None:
            scn.economics.electricity_price = price
            scn.lcia.elec_gwp = gwp
        scn.economics.discount_rate = self.spn_disc.value()
        scn.economics.plant_lifetime = self.spn_life.value()
        mp = main_product(scn)
        if mp:
            mp.price = self.spn_price.value()
        else:
            scn.product_price = self.spn_price.value()
        return True


class ReviewPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Review"))
        self.setSubTitle(tr("Finish to open this scenario in the full tool for analysis."))
        v = QVBoxLayout(self)
        self.lbl = QLabel(); self.lbl.setWordWrap(True)
        v.addWidget(self.lbl)

    def initializePage(self):
        from microalgae_tea_lca.scenario import run_scenario
        scn = self.wiz.scenario
        r = run_scenario(scn)
        mp = r.main_product
        cost = mp.production_cost_eur_per_kg if mp else r.tea.production_cost_eur_per_kg
        prod = mp.name if mp else tr("Whole biomass (food / feed)")
        unit = "m²" if scn.system.basis == Basis.AREA else "m³"
        op = tr("Batch") if scn.batch_mode else tr("Continuous")
        closest = ""
        if self.wiz.from_example:
            t = get_template(self.wiz.from_example)
            closest = "\n\n" + tr("Validated against: {v}").format(v=f"{t.name} — {t.validation}")
        self.lbl.setText(
            f"{tr('Organism')}: {scn.organism.name}\n"
            f"{tr('System')}: {scn.system.name}  ·  {scn.scale:,.0f} {unit}  ·  {op}\n"
            f"{tr('Product goal')}: {prod}\n\n"
            f"{tr('Production cost')}: € {cost:,.2f}/kg  ·  "
            f"{tr('Annual output')}: {r.inventory.annual_biomass_kg/1000:,.0f} t/yr  ·  "
            f"NPV: € {r.tea.npv/1e6:,.1f} M{closest}"
        )


class SetupWizard(QWizard):
    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.scenario = _default_scenario(lib)
        self.from_example: str | None = None
        self.goal = "biomass"
        self.setWindowTitle("AlgaeTEA-LCA")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.CancelButton, tr("Skip to full tool"))
        self.setButtonText(QWizard.FinishButton, tr("Open in full tool"))
        self.setButtonText(QWizard.BackButton, "‹ " + tr("Back"))
        self.setButtonText(QWizard.NextButton, tr("Next") + " ›")
        self.resize(660, 520)
        for page in (StartPage(self), GoalPage(self), OrganismPage(self), CultivationPage(self),
                     DownstreamPage(self), ContextPage(self), ReviewPage(self)):
            self.addPage(page)

    def guess_goal(self) -> str:
        mp = main_product(self.scenario)
        if mp is None:
            return "biomass"
        name = mp.name.lower()
        if "biodiesel" in name or "fame" in name:
            return "biofuel"
        if "phycocyanin" in name or "astaxanthin" in name or "pigment" in name:
            return "pigment"
        if "oil" in name:
            return "oil"
        if "protein" in name:
            return "protein"
        return "oil"
