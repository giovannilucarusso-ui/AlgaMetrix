"""Guided setup wizard for a researcher's TEA/LCA case study.

Seven steps that build a scenario either from the closest validated example or
from scratch, then hand it to the main window. Every step is pre-filled, every
numeric field carries its unit, and a step list on the left says where the
user is.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from algametrix.inputcheck import check_inputs, format_issues
from algametrix.library import Library
from algametrix.models import Basis, Scenario
from algametrix.products import main_product
from algametrix.regions import describe as describe_region
from algametrix.regions import load_regions
from algametrix.templates import (
    TEMPLATES,
    apply_goal,
    batch_size_from_volume,
    get_template,
    set_scale_from_target,
)

from desktop import resources, theme
from desktop.fields import plain_tooltip
from desktop.fields import spec as field_spec
from desktop.fmt import sig
from desktop.i18n import tr
from desktop.inputs_panel import number

STEP_TITLES = ("Start", "Product goal", "Organism", "Cultivation & scale", "Downstream",
               "Economic context", "Review")


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


def _form(page: QWizardPage) -> QFormLayout:
    f = QFormLayout(page)
    f.setHorizontalSpacing(14)
    f.setVerticalSpacing(10)
    f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return f


def _caption(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("caption")
    lbl.setWordWrap(True)
    return lbl


def _with_unit(field: QWidget, unit: str) -> QWidget:
    """A field followed by its unit tag; the holder is what the form registers."""
    if not unit:
        return field
    holder = QWidget()
    hl = QHBoxLayout(holder)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(6)
    hl.addWidget(field, 1)
    tag = QLabel(unit)
    tag.setObjectName("unit")
    hl.addWidget(tag)
    return holder


class StepList(QFrame):
    """The column on the left: which step this is, which are done."""

    def __init__(self, titles):
        super().__init__()
        self.setObjectName("wizardSide")
        self.setFixedWidth(200)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(4)
        path = resources.logo_path()
        pm = QPixmap(path) if path else QPixmap()
        if not pm.isNull():
            logo = QLabel()
            logo.setPixmap(pm.scaledToWidth(150, Qt.SmoothTransformation))
            lay.addWidget(logo)
            lay.addSpacing(10)
        title = QLabel(tr("Set up a case"))
        title.setObjectName("h2")
        lay.addWidget(title)
        lay.addWidget(_caption(tr("Seven steps, every field pre-filled. You can change "
                                  "anything later in the full tool.")))
        lay.addSpacing(10)
        self._labels = []
        for i, t in enumerate(titles):
            lbl = QLabel(f"{i + 1}.  {tr(t)}")
            lbl.setObjectName("wizardStep")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
            self._labels.append(lbl)
        lay.addStretch(1)

    def set_current(self, index: int):
        for i, lbl in enumerate(self._labels):
            name = ("wizardStepCurrent" if i == index
                    else "wizardStepDone" if i < index else "wizardStep")
            if lbl.objectName() != name:
                lbl.setObjectName(name)
                theme.repolish(lbl)


class StartPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Start your case study"))
        self.setSubTitle(tr("Begin from the closest validated example, or from scratch."))
        v = QVBoxLayout(self)
        v.setSpacing(10)
        self.grp = QButtonGroup(self)
        self.rb_example = QRadioButton(tr("Start from a validated example (recommended)"))
        self.rb_scratch = QRadioButton(tr("Build from scratch"))
        self.rb_example.setChecked(True)
        self.grp.addButton(self.rb_example)
        self.grp.addButton(self.rb_scratch)
        v.addWidget(self.rb_example)
        self.cmb = QComboBox()
        self.cmb.addItems([t.name for t in TEMPLATES])
        self.cmb.setToolTip(plain_tooltip(
            "Validated examples", "Each template rebuilds a published or reference case; the "
            "description below says what it was checked against."))
        v.addWidget(self.cmb)
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setObjectName("subtle")
        v.addWidget(self.lbl)
        v.addSpacing(8)
        v.addWidget(self.rb_scratch)
        v.addWidget(_caption(tr("From scratch: Chlorella vulgaris in an open raceway pond, "
                                "10 ha, spray-dried. Every default is a literature-typical "
                                "placeholder you will replace.")))
        v.addStretch(1)
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
    HINTS = {
        "biomass": "No extraction: the dried biomass is the product.",
        "oil": "Solvent extraction of the lipid fraction; protein meal and residue as co-products.",
        "protein": "Cell disruption and aqueous extraction; the protein fraction is the product.",
        "pigment": "Extraction and purification of a pigment; low yield, high value.",
        "biofuel": "Lipid extraction and transesterification to biodiesel.",
    }

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Product goal"))
        self.setSubTitle(tr("What is the main product? This sets up the downstream and products."))
        v = QVBoxLayout(self)
        v.setSpacing(8)
        self.grp = QButtonGroup(self)
        self.rbs = {}
        for text, key in self.LABELS:
            rb = QRadioButton(tr(text))
            rb.setToolTip(self.HINTS[key])
            self.grp.addButton(rb)
            v.addWidget(rb)
            self.rbs[key] = rb
        v.addSpacing(6)
        v.addWidget(_caption(tr("The cost and the GWP are reported per kg of the main product; "
                                "co-products take their share by the allocation method of the "
                                "template (economic by default).")))
        v.addStretch(1)

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
        f = _form(self)
        self.cmb = QComboBox()
        self.cmb.addItems(list(wiz.lib.organisms))
        f.addRow(tr("Strain"), self.cmb)
        self.lbl_notes = _caption()
        f.addRow("", self.lbl_notes)

        def _spin(hi, step, dec, tip):
            sb = number(0, hi, 0.0, step, dec, self._update_sum, plain_tooltip(tip[0], tip[1]))
            return sb

        self.protein = _spin(1, 0.01, 3, ("Protein", "Mass fraction of the dry weight."))
        self.lipid = _spin(1, 0.01, 3, ("Lipid", "Mass fraction of the dry weight."))
        self.carb = _spin(1, 0.01, 3, ("Carbohydrate", "Mass fraction of the dry weight."))
        self.ash = _spin(1, 0.01, 3, ("Ash", "Mass fraction of the dry weight."))
        self.c = _spin(1, 0.01, 3, ("Carbon", "Elemental carbon; drives the CO₂ or substrate demand."))
        self.n = _spin(0.3, 0.005, 3, ("Nitrogen", "Elemental nitrogen; drives the N demand."))
        self.p = _spin(0.1, 0.001, 3, ("Phosphorus", "Elemental phosphorus; drives the P demand."))
        unit = "kg/kg DW"
        f.addRow(tr("Protein (fraction DW)"), _with_unit(self.protein, unit))
        f.addRow(tr("Lipid (fraction DW)"), _with_unit(self.lipid, unit))
        f.addRow(tr("Carbohydrate (fraction DW)"), _with_unit(self.carb, unit))
        f.addRow(tr("Ash (fraction DW)"), _with_unit(self.ash, unit))
        f.addRow(tr("Carbon (fraction DW)"), _with_unit(self.c, unit))
        f.addRow(tr("Nitrogen (fraction DW)"), _with_unit(self.n, unit))
        f.addRow(tr("Phosphorus (fraction DW)"), _with_unit(self.p, unit))
        self.lbl_sum = QLabel()
        self.lbl_sum.setObjectName("subtle")
        self.lbl_sum.setWordWrap(True)
        f.addRow("", self.lbl_sum)
        self.cmb.currentTextChanged.connect(self._load_strain)

    def _fields(self):
        return {"protein": self.protein, "lipid": self.lipid, "carbohydrate": self.carb,
                "ash": self.ash, "carbon": self.c, "nitrogen": self.n, "phosphorus": self.p}

    def _load_strain(self, name):
        o = self.wiz.lib.organisms.get(name)
        if o:
            for attr, sb in self._fields().items():
                sb.blockSignals(True)
                sb.setValue(getattr(o, attr))
                sb.blockSignals(False)
            self.lbl_notes.setText(" ".join((o.notes or "").split()))
            self._update_sum()

    def _update_sum(self):
        s = self.protein.value() + self.lipid.value() + self.carb.value() + self.ash.value()
        self.lbl_sum.setText(tr("Composition sums to {s:.0%} (should be ~100%).").format(s=s))
        self.lbl_sum.setStyleSheet("" if 0.95 <= s <= 1.05 else f"color: {theme.WARNING};")

    def initializePage(self):
        o = self.wiz.scenario.organism
        i = self.cmb.findText(o.name)
        if i >= 0:
            self.cmb.blockSignals(True)
            self.cmb.setCurrentIndex(i)
            self.cmb.blockSignals(False)
        for attr, sb in self._fields().items():
            sb.blockSignals(True)
            sb.setValue(getattr(o, attr))
            sb.blockSignals(False)
        self.lbl_notes.setText(" ".join((o.notes or "").split()))
        self._update_sum()

    def validatePage(self):
        """A composition that cannot exist does not get to become a case.

        The page used to accept 400% with a note that it "should be ~100%",
        which is a remark, not a check: the wizard went on and produced yields
        taken from a kilogram containing four kilograms of components.
        """
        org = copy.deepcopy(self.wiz.lib.organisms[self.cmb.currentText()])
        for attr, sb in self._fields().items():
            setattr(org, attr, sb.value())
        candidate = copy.copy(self.wiz.scenario)
        candidate.organism = org
        blocking = [i for i in check_inputs(candidate)
                    if i.is_error and i.field.startswith("organism")]
        if blocking:
            # On the page as well as in the box: a Next button that silently does
            # nothing is its own kind of bug.
            self.lbl_sum.setText(" ".join(i.message for i in blocking))
            self.lbl_sum.setStyleSheet(f"color: {theme.DANGER};")
            QMessageBox.warning(self, tr("Composition is not possible"),
                                format_issues(blocking))
            return False
        self.lbl_sum.setStyleSheet("")
        self.wiz.scenario.organism = org
        return True


class CultivationPage(QWizardPage):
    """System, scale and schedule — with the batch tied to the vessel that holds it."""

    #: Where the size box starts when the basis changes and the old number means
    #: something else entirely.
    DEFAULT_SIZE = {Basis.AREA: 100_000.0, Basis.VOLUME: 500.0}

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Cultivation & scale"))
        self.setSubTitle(tr("Choose the system, how to size the plant, and batch or continuous operation."))
        f = _form(self)
        self.form = f
        self._holders: dict[int, QWidget] = {}
        self.cmb_sys = QComboBox()
        self.cmb_sys.addItems(list(wiz.lib.systems))
        f.addRow(tr("System"), self.cmb_sys)
        self.lbl_sys_notes = _caption()
        f.addRow("", self.lbl_sys_notes)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([tr("By target production (t/yr)"), tr("By cultivation size")])
        self.cmb_mode.setToolTip(plain_tooltip(
            "How to size the plant", "Give the output you want and let the scale follow, or "
            "give the area or volume and read the output."))
        f.addRow(tr("Specify scale"), self.cmb_mode)
        self.spn_target = number(0.1, 1e7, 100, 10, 0, grouped=True,
                                 tooltip=plain_tooltip("Target production",
                                                       "Main product leaving the gate per year."))
        self._add(f, QLabel(tr("Target product (t/yr)")), self.spn_target, "t/yr")
        self.spn_size = number(1, 1e9, 100_000, 1000, 0, grouped=True)
        self.lbl_size = QLabel(tr("Cultivation size (m²)"))
        self.lbl_size_unit = QLabel("m²")
        self.lbl_size_unit.setObjectName("unit")
        self._add(f, self.lbl_size, self.spn_size, unit_label=self.lbl_size_unit)
        self.cmb_batch = QComboBox()
        self.cmb_batch.addItems([tr("Continuous"), tr("Batch")])
        f.addRow(tr("Operation"), self.cmb_batch)

        # The two numbers that set the area when sizing by target. They used to
        # come from the system preset without being shown, so a target turned
        # into an area with no visible basis. Productivity has no meaning at
        # zero, hence the floor.
        fp = field_spec("system", "productivity")
        self.spn_productivity = number(
            max(fp.lo, 0.1), fp.hi, 20.0, fp.step, fp.decimals, tooltip=plain_tooltip(
                tr("Productivity"),
                tr("Annual mean over the operating days, for the site's climate.")))
        self.lbl_productivity = QLabel(tr("Productivity (g/m²/d)"))
        self.lbl_productivity_unit = QLabel("g/m²/d")
        self._add(f, self.lbl_productivity, self.spn_productivity,
                  unit_label=self.lbl_productivity_unit)
        fd = field_spec("system", "operating_days")
        self.spn_days = number(
            fd.lo, fd.hi, 330.0, fd.step, fd.decimals, tooltip=plain_tooltip(
                tr("Operating days"),
                tr("Days a year the plant produces. In batch operation it also sets the "
                   "number of batches a year.")))
        self._add(f, QLabel(tr("Operating days (d/yr)")), self.spn_days, "d/yr")

        # The three numbers that make a batch a batch. Without them "batch size"
        # is a free parameter and the reactor volume is decoration.
        self.spn_titer = number(0.1, 500.0, 50.0, 1.0, 1, tooltip=tr(
            "Dry biomass concentration at harvest. In g/L and kg/m³ this is the "
            "same number, so one batch holds volume × working volume × titer."))
        self.lbl_titer = QLabel(tr("Final titer (g/L)"))
        self._add(f, self.lbl_titer, self.spn_titer, "g/L")
        self.spn_working = number(0.05, 1.0, 0.8, 0.05, 2, tooltip=tr(
            "Fraction of the nominal reactor volume the culture occupies; "
            "headspace, foam and impeller clearance take the rest."))
        self.lbl_working = QLabel(tr("Working volume (fraction)"))
        self._add(f, self.lbl_working, self.spn_working, "fraction (0-1)")
        self.spn_cycle = number(1.0, 2000.0, 48.0, 1.0, 1, tooltip=plain_tooltip(
            "Cycle time", "Hours from one batch start to the next, turnaround included."))
        self.lbl_cycle = QLabel(tr("Batch cycle time (h, incl. turnaround)"))
        self._add(f, self.lbl_cycle, self.spn_cycle, "h")

        self.lbl_derived = QLabel("")
        self.lbl_derived.setObjectName("subtle")
        self.lbl_derived.setWordWrap(True)
        f.addRow("", self.lbl_derived)

        self.cmb_mode.currentIndexChanged.connect(self._toggle)
        self.cmb_sys.currentTextChanged.connect(self._sys_changed)
        self.cmb_batch.currentIndexChanged.connect(self._toggle)
        for w in (self.spn_size, self.spn_titer, self.spn_working, self.spn_cycle,
                  self.spn_target, self.spn_productivity, self.spn_days):
            w.valueChanged.connect(self._update_derived)

    def _add(self, form, label, field, unit: str = "", unit_label: QLabel | None = None):
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(field, 1)
        tag = unit_label if unit_label is not None else QLabel(unit)
        tag.setObjectName("unit")
        hl.addWidget(tag)
        form.addRow(label, holder)
        self._holders[id(field)] = holder

    def _row_visible(self, field, on: bool):
        self.form.setRowVisible(self._holders.get(id(field), field), on)

    # -- state ------------------------------------------------------------
    def _system(self):
        return self.wiz.lib.systems.get(self.cmb_sys.currentText())

    def _is_batch(self) -> bool:
        return self.cmb_batch.currentIndex() == 1

    def _toggle(self):
        by_target = self.cmb_mode.currentIndex() == 0
        sysm = self._system()
        volume = sysm is not None and sysm.basis == Basis.VOLUME
        self._row_visible(self.spn_target, by_target)
        self._row_visible(self.spn_size, not by_target)
        # Titer and working volume only mean something for a vessel, and only a
        # batch schedule reads them.
        for widget in (self.spn_titer, self.spn_working):
            self._row_visible(widget, volume and self._is_batch())
        self._row_visible(self.spn_cycle, self._is_batch())
        # A batch's output is batch size × batches a year; productivity only
        # enters continuous operation. Operating days count in both.
        self._row_visible(self.spn_productivity, not self._is_batch())
        self._update_derived()

    def _sys_changed(self, name):
        s = self.wiz.lib.systems.get(name)
        if not s:
            return
        self._set_basis_labels(s.basis)
        self.lbl_sys_notes.setText(" ".join((s.notes or "").split()))
        self.cmb_batch.setCurrentIndex(1 if s.mode.value == "heterotrophic" else 0)
        self.spn_titer.setValue(s.biomass_conc)
        self.spn_working.setValue(s.working_volume)
        for sb, value in ((self.spn_productivity, s.productivity),
                          (self.spn_days, s.operating_days)):
            sb.blockSignals(True)
            sb.setValue(value)
            sb.blockSignals(False)
        # A basis change makes the old number mean something else: 100,000 m² of
        # pond is not 100,000 m³ of fermenter. Never carry it across.
        if s.basis != getattr(self, "_basis", None):
            self._basis = s.basis
            self.spn_size.setValue(self.DEFAULT_SIZE[s.basis])
        self._toggle()

    def _set_basis_labels(self, basis):
        volume = basis == Basis.VOLUME
        self.lbl_size.setText(tr("Reactor volume (m³)") if volume else tr("Cultivation size (m²)"))
        self.lbl_size_unit.setText("m³" if volume else "m²")
        self.spn_size.setSingleStep(10 if volume else 1000)
        self.lbl_productivity.setText(
            tr("Productivity (g/L/d)") if volume else tr("Productivity (g/m²/d)"))
        self.lbl_productivity_unit.setText("g/L/d" if volume else "g/m²/d")
        self.spn_productivity.setSingleStep(0.1 if volume else 1.0)

    def _sized_system(self, sysm):
        """The selected system with the productivity and operating days typed here."""
        sized = copy.deepcopy(sysm)
        sized.productivity = self.spn_productivity.value()
        sized.operating_days = self.spn_days.value()
        return sized

    def _continuous_text(self, sized, by_target: bool) -> str:
        """The area (or volume) a target needs, or the output a size gives, with its basis."""
        volume = sized.basis == Basis.VOLUME
        if volume:
            unit, p_unit, y_unit = "m³", "g/L/d", "kg/m³/yr"
            per_unit = sized.productivity * sized.operating_days           # g/L/d = kg/m³/d
        else:
            unit, p_unit, y_unit = "m²", "g/m²/d", "kg/m²/yr"
            per_unit = sized.productivity * sized.operating_days / 1000.0
        recovery = self.wiz.scenario.harvesting.recovery
        values = dict(u=unit, p=sig(sized.productivity, 3), pu=p_unit,
                      d=f"{sized.operating_days:.0f}", r=f"{recovery:.0%}")
        if by_target:
            # Sized on a copy, the way validatePage will size it, so the yield
            # of the main product for the chosen goal is in the number.
            trial = copy.copy(self.wiz.scenario)
            trial.system = sized
            trial.batch_mode = False
            set_scale_from_target(trial, self.spn_target.value())
            return tr("{t} t/yr → {a} {u} at {p} {pu} × {d} d = {y} {yu}, with {r} harvest "
                      "recovery.").format(t=sig(self.spn_target.value(), 3),
                                          a=sig(trial.scale, 3), y=sig(per_unit, 3),
                                          yu=y_unit, **values)
        gross_t = self.spn_size.value() * per_unit / 1000.0
        return tr("{s} {u} × {p} {pu} × {d} d = {g} t/yr of gross dry biomass, before {r} "
                  "harvest recovery.").format(s=sig(self.spn_size.value(), 3),
                                              g=sig(gross_t, 3), **values)

    def _update_derived(self):
        sysm = self._system()
        if sysm is None:
            return
        by_target = self.cmb_mode.currentIndex() == 0
        batches = self.spn_days.value() * 24.0 / max(self.spn_cycle.value(), 1e-9)
        if self._is_batch() and sysm.basis == Basis.VOLUME:
            if by_target:
                self.lbl_derived.setText(tr(
                    "The reactor volume follows from the batch: at {t:.0f} g/L and "
                    "{w:.0%} working volume, the vessel is sized to hold one batch "
                    "of the {n:.0f} batches a year this schedule allows."
                ).format(t=self.spn_titer.value(), w=self.spn_working.value(), n=batches))
            else:
                sized = copy.deepcopy(sysm)
                sized.biomass_conc = self.spn_titer.value()
                sized.working_volume = self.spn_working.value()
                per_batch = batch_size_from_volume(sized, self.spn_size.value())
                gross = per_batch * batches
                self.lbl_derived.setText(tr(
                    "{v:,.0f} m³ × {w:.0%} × {t:.0f} g/L = {b:,.0f} kg of gross dry "
                    "biomass per batch; {n:.0f} batches a year → {y:,.0f} t/yr gross."
                ).format(v=self.spn_size.value(), w=self.spn_working.value(),
                         t=self.spn_titer.value(), b=per_batch, n=batches, y=gross / 1000.0))
        elif self._is_batch():
            self.lbl_derived.setText(tr(
                "Batch operation on an area-based system: the annual output is the "
                "batch size × {n:.0f} batches a year, and the cultivation area does "
                "not enter it."
            ).format(n=batches))
        else:
            self.lbl_derived.setText(self._continuous_text(self._sized_system(sysm), by_target))

    def initializePage(self):
        scn = self.wiz.scenario
        i = self.cmb_sys.findText(scn.system.name)
        self._basis = scn.system.basis
        if i >= 0:
            self.cmb_sys.blockSignals(True)
            self.cmb_sys.setCurrentIndex(i)
            self.cmb_sys.blockSignals(False)
        self.lbl_sys_notes.setText(" ".join((scn.system.notes or "").split()))
        self.spn_size.setValue(scn.scale)
        self.spn_titer.setValue(scn.system.biomass_conc)
        self.spn_working.setValue(scn.system.working_volume)
        self.spn_productivity.setValue(scn.system.productivity)
        self.spn_days.setValue(scn.system.operating_days)
        self.cmb_batch.setCurrentIndex(1 if scn.batch_mode else 0)
        if scn.batch_cycle_time_h > 0:
            self.spn_cycle.setValue(scn.batch_cycle_time_h)
        self._set_basis_labels(scn.system.basis)
        self._toggle()

    def validatePage(self):
        scn = self.wiz.scenario
        scn.system = copy.deepcopy(self.wiz.lib.systems[self.cmb_sys.currentText()])
        scn.system.productivity = self.spn_productivity.value()
        scn.system.operating_days = self.spn_days.value()
        scn.system.biomass_conc = self.spn_titer.value()
        scn.system.working_volume = self.spn_working.value()
        scn.materials = list(scn.system.materials)
        scn.utilities = list(scn.system.utilities)
        scn.batch_mode = self._is_batch()
        if scn.batch_mode:
            scn.batch_cycle_time_h = self.spn_cycle.value()
        if self.cmb_mode.currentIndex() == 0:
            # Kept on the wizard: the downstream page sizes again once the
            # harvesting, and so the recovery, is known.
            self.wiz.target_t_yr = self.spn_target.value()
            set_scale_from_target(scn, self.wiz.target_t_yr)
        else:
            self.wiz.target_t_yr = None
            scn.scale = self.spn_size.value()
            if scn.batch_mode and scn.system.basis == Basis.VOLUME:
                # One batch is what the vessel holds. Sizing by volume therefore
                # sets the batch, not the other way round.
                scn.batch_size_kg = batch_size_from_volume(scn.system, scn.scale)
        if scn.batch_mode and scn.batch_size_kg <= 0:
            scn.batch_size_kg = 1000.0
        return True


class DownstreamPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Downstream"))
        self.setSubTitle(tr("How the biomass is harvested, dried and (if needed) processed into the product."))
        f = _form(self)
        self.cmb_harv = QComboBox()
        self.cmb_harv.addItems(list(wiz.lib.harvesting))
        self.cmb_dry = QComboBox()
        self.cmb_dry.addItems(list(wiz.lib.drying))
        f.addRow(tr("Harvesting"), self.cmb_harv)
        self.lbl_harv_notes = _caption()
        f.addRow("", self.lbl_harv_notes)
        f.addRow(tr("Drying"), self.cmb_dry)
        self.lbl_dry_notes = _caption()
        f.addRow("", self.lbl_dry_notes)
        self.cmb_ext = QComboBox()
        self.cmb_ext.addItems(list(wiz.lib.extraction))
        f.addRow(tr("Extraction technology"), self.cmb_ext)
        self.lbl = QLabel()
        self.lbl.setObjectName("subtle")
        self.lbl.setWordWrap(True)
        f.addRow("", self.lbl)
        self.lbl_ext_notes = _caption()
        f.addRow("", self.lbl_ext_notes)
        self.cmb_harv.currentTextChanged.connect(self._notes)
        self.cmb_dry.currentTextChanged.connect(self._notes)
        self.cmb_ext.currentTextChanged.connect(self._notes)

    def _notes(self, *_):
        lib = self.wiz.lib
        harv = lib.harvesting.get(self.cmb_harv.currentText())
        dry = lib.drying.get(self.cmb_dry.currentText())
        ext = lib.extraction.get(self.cmb_ext.currentText())
        self.lbl_harv_notes.setText(" ".join((harv.notes if harv else "").split()))
        self.lbl_dry_notes.setText(" ".join((dry.notes if dry else "").split()))
        self.lbl_ext_notes.setText(
            " ".join((ext.notes if ext else "").split()) if self.cmb_ext.isEnabled() else "")

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
        self._notes()

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
        # The cultivation page sized a target with the harvesting the scenario
        # had then. Recoveries differ between methods, so size again with the
        # one chosen here, or the plant misses its target by the difference.
        if self.wiz.target_t_yr is not None:
            set_scale_from_target(self.wiz.scenario, self.wiz.target_t_yr)
        return True


class ContextPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(tr("Economic & environmental context"))
        self.setSubTitle(tr("Regional energy, finance and selling price. Defaults are fine to start."))
        f = _form(self)
        # A region fills the two electricity inputs from data/regions.yaml, where
        # each value has a source. The first entry keeps the scenario's own
        # values, so a template is not overwritten unless the user asks.
        regional = load_regions()
        self.regions = list(regional.regions) if regional else []
        self.cmb_region = QComboBox()
        self.cmb_region.addItem(tr("Keep the scenario's values"))
        self.cmb_region.addItems([r.name for r in self.regions])
        self.cmb_region.setToolTip(plain_tooltip(
            "Region", "Sets the electricity price and the grid emission factor from "
            "data/regions.yaml, each with its source and year. The other background "
            "factors stay as declared in data/lcia.yaml."))
        f.addRow(tr("Region (electricity)"), self.cmb_region)
        self.spn_elec_price = number(0, 5, 0.15, 0.01, 4)
        self.spn_elec_gwp = number(0, 5, 0.35, 0.01, 4)
        f.addRow(tr("Electricity price (€/kWh)"), _with_unit(self.spn_elec_price, "€/kWh"))
        f.addRow(tr("Grid emission factor (kg CO₂-eq/kWh)"),
                 _with_unit(self.spn_elec_gwp, "kg CO₂-eq/kWh"))
        self.lbl_region = QLabel()
        self.lbl_region.setWordWrap(True)
        self.lbl_region.setObjectName("caption")
        f.addRow("", self.lbl_region)
        self._shown: tuple[float, float] = (0.0, 0.0)
        self.cmb_region.currentIndexChanged.connect(self._region_changed)
        self.spn_disc = number(0, 0.25, 0.08, 0.01, 3, tooltip=plain_tooltip(
            "Discount rate", "For the NPV and the capital recovery factor."))
        self.spn_life = number(1, 40, 20, 1, 0, tooltip=plain_tooltip(
            "Plant lifetime", "Project evaluation horizon."))
        self.spn_price = number(0, 100000, 8.0, 0.5, 2, tooltip=plain_tooltip(
            "Selling price", "Of the main product, per kg. Check the Market prices page in "
            "the full tool for published ranges."))
        f.addRow(tr("Discount rate"), _with_unit(self.spn_disc, "fraction (0-1)"))
        f.addRow(tr("Plant lifetime (yr)"), _with_unit(self.spn_life, "yr"))
        f.addRow(tr("Product selling price (€/kg)"), _with_unit(self.spn_price, "€/kg"))
        f.addRow("", _caption(tr("Prices are in EUR as entered: the model applies no inflation "
                                 "and no currency conversion.")))

    def initializePage(self):
        scn = self.wiz.scenario
        self.cmb_region.blockSignals(True)
        self.cmb_region.setCurrentIndex(0)
        self.cmb_region.blockSignals(False)
        self._region_changed(0)
        self.spn_disc.setValue(scn.economics.discount_rate)
        self.spn_life.setValue(scn.economics.plant_lifetime)
        mp = main_product(scn)
        self.spn_price.setValue(mp.price if mp else scn.product_price)

    def _region_changed(self, index: int) -> None:
        scn = self.wiz.scenario
        price, gwp = scn.economics.electricity_price, scn.lcia.elec_gwp
        if index <= 0:
            text = tr("The scenario's own values. Edit them here or pick a region.")
        else:
            region = self.regions[index - 1]
            gwp = region.grid.value
            if region.price is not None:
                price = region.price.value
            text = describe_region(region)
        self.spn_elec_price.setValue(price)
        self.spn_elec_gwp.setValue(gwp)
        self.lbl_region.setText(text)
        self._shown = (self.spn_elec_price.value(), self.spn_elec_gwp.value())

    def validatePage(self):
        scn = self.wiz.scenario
        shown = (self.spn_elec_price.value(), self.spn_elec_gwp.value())
        # The spin boxes round to four decimals; write them back only when a
        # region was picked or the user typed a value, so the scenario's own
        # numbers pass through untouched otherwise.
        if self.cmb_region.currentIndex() > 0 or shown != self._shown:
            scn.economics.electricity_price = shown[0]
            scn.lcia.elec_gwp = shown[1]
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
        v.setSpacing(10)
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setTextFormat(Qt.RichText)
        self.lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl)
        v.addWidget(_caption(tr("Costs per kg of the main product at the plant gate, in EUR "
                                "as entered; GWP cradle-to-gate. Every number can be revisited "
                                "in the full tool.")))
        v.addStretch(1)
        self._blocking: list = []

    def isComplete(self) -> bool:
        """Finish stays disabled while the case is not physically admissible."""
        return not self._blocking

    def initializePage(self):
        from algametrix.scenario import run_scenario
        scn = self.wiz.scenario
        self._blocking = [i for i in check_inputs(scn) if i.is_error]
        if self._blocking:
            self.lbl.setText(
                f"<p style='color:{theme.DANGER}'><b>"
                + tr("This scenario cannot be computed. Go back and fix:") + "</b></p><pre>"
                + format_issues(self._blocking) + "</pre>"
            )
            self.completeChanged.emit()
            return
        self.completeChanged.emit()
        r = run_scenario(scn)
        mp = r.main_product
        cost = mp.production_cost_eur_per_kg if mp else r.tea.production_cost_eur_per_kg
        gwp = mp.gwp_kg_co2eq_per_kg if mp else r.lca.gwp_kg_co2eq_per_kg
        prod = mp.name if mp else tr("Whole biomass (food / feed)")
        unit = "m²" if scn.system.basis == Basis.AREA else "m³"
        op = tr("Batch") if scn.batch_mode else tr("Continuous")
        closest = ""
        if self.wiz.from_example:
            t = get_template(self.wiz.from_example)
            closest = ("<p style='margin-top:8px'>"
                       + tr("Validated against: {v}").format(v=f"{t.name} — {t.validation}")
                       + "</p>")
        per = mp.name if mp else "dry biomass"
        system = f"{scn.system.name}  ·  {scn.scale:,.0f} {unit}  ·  {op}"
        if not scn.batch_mode:
            p_unit = "g/m²/d" if scn.system.basis == Basis.AREA else "g/L/d"
            system += (f"  ·  {sig(scn.system.productivity, 3)} {p_unit} × "
                       f"{scn.system.operating_days:.0f} d")

        def row(k, v):
            return (f"<tr><td style='color:{theme.INK_3}; padding:2px 14px 2px 0'>{k}</td>"
                    f"<td style='padding:2px 0'>{v}</td></tr>")

        self.lbl.setText(
            "<table cellspacing='0'>"
            + row(tr("Organism"), scn.organism.name)
            + row(tr("System"), system)
            + row(tr("Product goal"), prod)
            + "</table><table cellspacing='0' style='margin-top:10px'>"
            + row(tr("Production cost"), f"<b>€ {cost:,.2f}</b> / kg {per}")
            + row("GWP", f"<b>{gwp:,.2f}</b> kg CO₂-eq / kg {per}")
            + row(tr("Annual output"), f"<b>{r.inventory.annual_biomass_kg / 1000:,.0f}</b> t dry biomass / yr")
            + row("NPV", f"<b>€ {r.tea.npv / 1e6:,.1f} M</b> over {scn.economics.plant_lifetime:.0f} yr "
                         f"at {scn.economics.discount_rate:.1%}")
            + "</table>" + closest
        )


class SetupWizard(QWizard):
    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.scenario = _default_scenario(lib)
        self.from_example: str | None = None
        self.goal = "biomass"
        #: Set when the cultivation page sizes by target, so the downstream page
        #: can size again with the harvesting it picks.
        self.target_t_yr: float | None = None
        self.setWindowTitle("AlgaMetrix")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.HaveHelpButton, False)
        self.setButtonText(QWizard.CancelButton, tr("Skip to full tool"))
        self.setButtonText(QWizard.FinishButton, tr("Open in full tool"))
        self.setButtonText(QWizard.BackButton, "‹ " + tr("Back"))
        self.setButtonText(QWizard.NextButton, tr("Next") + " ›")
        self.resize(860, 620)
        self.steps = StepList(STEP_TITLES)
        self.setSideWidget(self.steps)
        for page in (StartPage(self), GoalPage(self), OrganismPage(self), CultivationPage(self),
                     DownstreamPage(self), ContextPage(self), ReviewPage(self)):
            self.addPage(page)
        self.currentIdChanged.connect(self._sync_steps)
        self._sync_steps(self.startId())

    def _sync_steps(self, page_id: int):
        ids = self.pageIds()
        self.steps.set_current(ids.index(page_id) if page_id in ids else 0)

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
