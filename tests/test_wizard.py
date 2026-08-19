"""The setup wizard must not build a plant nobody could commission.

Driven page by page on Qt's off-screen platform: each page's ``validatePage``
is the step the wizard takes when the user presses Next, so calling it is
pressing Next.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

pytest.importorskip("PySide6", reason="the wizard needs PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from algametrix.inputcheck import is_admissible  # noqa: E402
from algametrix.library import load_library  # noqa: E402
from algametrix.models import Basis, TrophicMode  # noqa: E402
from algametrix.scenario import run_scenario  # noqa: E402

START, GOAL, ORGANISM, CULTIVATION, DOWNSTREAM, CONTEXT, REVIEW = range(7)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def lib():
    return load_library()


@pytest.fixture
def wizard(qapp, lib):
    from desktop.wizard import SetupWizard

    wiz = SetupWizard(lib)
    yield wiz
    wiz.deleteLater()


def page(wiz, index):
    return wiz.page(wiz.pageIds()[index])


def from_scratch(wiz):
    """Press 'Build from scratch' and walk to the cultivation page."""
    start = page(wiz, START)
    start.rb_scratch.setChecked(True)
    assert start.validatePage()
    for i in (GOAL, ORGANISM):
        p = page(wiz, i)
        p.initializePage()
        assert p.validatePage()
    cult = page(wiz, CULTIVATION)
    cult.initializePage()
    return cult


def fermenter_name(lib):
    return next(n for n, s in lib.systems.items() if s.basis == Basis.VOLUME
                and s.mode == TrophicMode.HETEROTROPHIC)


# --------------------------------------------------------------------------- #
# QA-007 — a batch has to fit in the vessel that holds it
# --------------------------------------------------------------------------- #
def test_batch_target_sizes_the_vessel_from_volume_and_titer(wizard, lib):
    cult = from_scratch(wizard)
    cult.cmb_sys.setCurrentText(fermenter_name(lib))
    cult.cmb_batch.setCurrentIndex(1)              # batch
    cult.cmb_mode.setCurrentIndex(0)               # by target production
    cult.spn_target.setValue(100.0)                # 100 t/yr
    assert cult.validatePage()

    scn = wizard.scenario
    assert scn.system.basis == Basis.VOLUME
    assert scn.batch_mode is True
    # The vessel now holds exactly one batch: volume x working volume x titer.
    held = scn.scale * scn.system.working_volume * scn.system.biomass_conc
    assert held == pytest.approx(scn.batch_size_kg, rel=1e-6)
    assert scn.scale < 100.0                       # was 100,000 m3 of fermenter

    r = run_scenario(scn)
    assert r.inventory.annual_biomass_kg / 1000 == pytest.approx(100.0, rel=1e-6)
    assert r.tea.total_investment < 20e6            # was EUR 287.5 M for 100 t/yr


def test_area_to_volume_switch_does_not_reuse_scale(wizard, lib):
    """100,000 m² of pond is not 100,000 m³ of fermenter."""
    cult = from_scratch(wizard)
    assert cult.spn_size.value() == pytest.approx(100_000.0)   # the raceway default
    cult.cmb_sys.setCurrentText(fermenter_name(lib))
    assert cult.spn_size.value() < 10_000.0
    assert "m³" in cult.lbl_size.text()


def test_sizing_by_volume_sets_the_batch_from_the_vessel(wizard, lib):
    cult = from_scratch(wizard)
    cult.cmb_sys.setCurrentText(fermenter_name(lib))
    cult.cmb_batch.setCurrentIndex(1)
    cult.cmb_mode.setCurrentIndex(1)               # by cultivation size
    cult.spn_size.setValue(200.0)                  # 200 m3 of fermenter
    cult.spn_titer.setValue(80.0)
    cult.spn_working.setValue(0.75)
    assert cult.validatePage()

    scn = wizard.scenario
    assert scn.scale == pytest.approx(200.0)
    assert scn.batch_size_kg == pytest.approx(200.0 * 0.75 * 80.0)   # 12,000 kg
    assert scn.system.biomass_conc == pytest.approx(80.0)


def test_the_page_states_the_batch_it_derives(wizard, lib):
    cult = from_scratch(wizard)
    cult.cmb_sys.setCurrentText(fermenter_name(lib))
    cult.cmb_batch.setCurrentIndex(1)
    cult.cmb_mode.setCurrentIndex(1)
    cult.spn_size.setValue(100.0)
    cult._update_derived()
    assert "per batch" in cult.lbl_derived.text()


def test_continuous_operation_keeps_the_productivity_route(wizard, lib):
    cult = from_scratch(wizard)
    cult.cmb_batch.setCurrentIndex(0)              # continuous raceway
    cult.cmb_mode.setCurrentIndex(0)
    cult.spn_target.setValue(500.0)
    assert cult.validatePage()
    scn = wizard.scenario
    assert scn.batch_mode is False
    assert run_scenario(scn).inventory.annual_biomass_kg / 1000 == pytest.approx(500.0, rel=1e-6)


# --------------------------------------------------------------------------- #
# QA-010 — the wizard must refuse an impossible case
# --------------------------------------------------------------------------- #
def test_invalid_composition_cannot_leave_the_organism_page(wizard, monkeypatch):
    # The page also warns in a modal box, which has nobody to close it here.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    from_scratch(wizard)
    org = page(wizard, ORGANISM)
    org.initializePage()
    for spin in (org.protein, org.lipid, org.carb, org.ash):
        spin.setValue(1.0)                          # the 400% composition
    assert org.validatePage() is False              # Next does nothing
    assert org.wiz.scenario.organism.protein != 1.0  # and nothing was written
    assert "cannot contain more than a kilogram" in org.lbl_sum.text()


def test_a_plausible_composition_still_passes(wizard):
    from_scratch(wizard)
    org = page(wizard, ORGANISM)
    org.initializePage()
    org.protein.setValue(0.45)
    org.lipid.setValue(0.25)
    org.carb.setValue(0.22)
    org.ash.setValue(0.08)
    assert org.validatePage() is True
    assert org.wiz.scenario.organism.protein == pytest.approx(0.45)


def test_finish_is_blocked_while_the_case_is_inadmissible(wizard, lib):
    from_scratch(wizard)
    review = page(wizard, REVIEW)
    wizard.scenario.system.productivity = 0.0      # nothing can come out of this
    review.initializePage()
    assert review.isComplete() is False
    assert "cannot be computed" in review.lbl.text()


def test_finish_is_allowed_for_an_admissible_case(wizard, lib):
    cult = from_scratch(wizard)
    cult.validatePage()
    for i in (DOWNSTREAM, CONTEXT):
        p = page(wizard, i)
        p.initializePage()
        assert p.validatePage()
    review = page(wizard, REVIEW)
    review.initializePage()
    assert review.isComplete() is True
    assert is_admissible(wizard.scenario)
    assert "Production cost" in review.lbl.text()


def test_a_template_walks_through_unchanged(wizard, lib):
    """Every page pressed Next: the validated case must survive the trip."""
    start = page(wizard, START)
    start.rb_example.setChecked(True)
    start.cmb.setCurrentText("Omega-3 oil (heterotrophic fermentation)")
    assert start.validatePage()
    for i in (GOAL, ORGANISM, CULTIVATION, DOWNSTREAM, CONTEXT):
        p = page(wizard, i)
        p.initializePage()
        assert p.validatePage()
    scn = wizard.scenario
    assert is_admissible(scn)
    assert [p.name for p in scn.products][0] == "Omega-3 oil"
    assert scn.batch_mode is True
