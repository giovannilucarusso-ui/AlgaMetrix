"""The desktop window must mean what it shows.

These run the real :class:`MainWindow` on Qt's off-screen platform, so they
exercise the widgets, their signals and the scenario the window hands the
engine — the layer where a case can look right and compute something else.
Each test names the failure it pins down.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

pytest.importorskip("PySide6", reason="the desktop client needs PySide6")
pytest.importorskip("matplotlib", reason="the results panel embeds matplotlib")

from PySide6.QtWidgets import QApplication  # noqa: E402

from algametrix.models import Material, TrophicMode, WasteBurdenConvention  # noqa: E402
from algametrix.scenario import run_scenario  # noqa: E402
from algametrix.serialization import (  # noqa: E402
    load_scenario,
    results_to_dict,
    save_scenario,
)
from algametrix.templates import build_template  # noqa: E402

OMEGA3 = "Omega-3 oil (heterotrophic fermentation)"
WASTEWATER = "Biomass on municipal wastewater (raceway)"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from desktop.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


@pytest.fixture
def omega3_window(window):
    window.apply_scenario(build_template(OMEGA3, window.lib))
    return window


# --------------------------------------------------------------------------- #
# QA-006 — the fields must describe the case they claim to describe
# --------------------------------------------------------------------------- #
def test_template_products_reach_the_widgets(omega3_window):
    w = omega3_window
    assert w.spn_oil_rec.value() == pytest.approx(0.70)   # was 0.90, the stale default
    assert w.spn_oil_price.value() == pytest.approx(30.0)  # was 2.50
    assert w.spn_price.value() == pytest.approx(30.0)
    assert [p.name for p in w.products] == ["Omega-3 oil", "Protein meal", "Residual biomass"]


def test_allocation_change_does_not_replace_product_definitions(omega3_window):
    w = omega3_window
    before = [(p.name, p.fraction, p.recovery, p.price, p.is_main) for p in w.products]
    w.cmb_alloc.setCurrentText("mass")
    after = [(p.name, p.fraction, p.recovery, p.price, p.is_main) for p in w.products]
    assert after == before
    assert w.build_scenario().extraction.allocation == "mass"


def test_technology_change_does_not_replace_product_definitions(omega3_window):
    w = omega3_window
    before = [(p.name, p.recovery, p.price) for p in w.products]
    other = next(n for n in w.lib.extraction if n != w.cmb_ext_tech.currentText())
    w.cmb_ext_tech.setCurrentText(other)
    assert [(p.name, p.recovery, p.price) for p in w.products] == before
    assert w.extraction.name == other


def test_product_fields_edit_the_products_in_place(omega3_window):
    w = omega3_window
    w.spn_oil_rec.setValue(0.55)
    oil = next(p for p in w.products if p.fraction == "lipid")
    assert oil.name == "Omega-3 oil"     # edited, not recreated under a new name
    assert oil.recovery == pytest.approx(0.55)


def test_switching_extraction_off_and_on_returns_the_case(omega3_window):
    w = omega3_window
    w.chk_extraction.setChecked(False)
    assert w.products == [] and w.extraction.enabled is False
    w.chk_extraction.setChecked(True)
    assert [p.name for p in w.products] == ["Omega-3 oil", "Protein meal", "Residual biomass"]


# --------------------------------------------------------------------------- #
# QA-005 — the profitability controls must do something
# --------------------------------------------------------------------------- #
def test_main_product_price_changes_revenue_and_npv(omega3_window):
    w = omega3_window
    npv_before, rev_before = w.results.tea.npv, w.results.tea.revenues
    w.spn_price.setValue(35.0)
    assert w._main_product().price == pytest.approx(35.0)
    assert w.results.tea.revenues > rev_before
    assert w.results.tea.npv > npv_before


def test_coproduct_revenue_is_applied_in_a_multiproduct_case(omega3_window):
    w = omega3_window
    npv_before, rev_before = w.results.tea.npv, w.results.tea.revenues
    w.spn_coproduct.setValue(1_000_000.0)
    assert w.results.tea.revenues == pytest.approx(rev_before + 1_000_000.0)
    assert w.results.tea.npv > npv_before


def test_annual_credits_and_other_opex_reach_the_engine(window):
    """The algal-oil case credits EUR 16 M/yr; the window used to drop it."""
    window.apply_scenario(build_template("Algal-oil biorefinery (phototrophic)", window.lib))
    assert window.credits_per_year == pytest.approx(16_000_000.0)
    assert window.build_scenario().credits_per_year == pytest.approx(16_000_000.0)
    npv_before = window.results.tea.npv
    window.spn_other_opex.setValue(2_000_000.0)
    assert window.build_scenario().other_opex_per_year == pytest.approx(2_000_000.0)
    assert window.results.tea.npv < npv_before


# --------------------------------------------------------------------------- #
# QA-003 — a saved case must come back
# --------------------------------------------------------------------------- #
def test_save_load_roundtrip_preserves_all_advanced_state(omega3_window, tmp_path):
    w = omega3_window
    w.custom_materials = [Material("Trace metals", 0.002, 12.0, 3.0, 40.0)]
    w.chk_waste.setChecked(True)
    w.recompute()
    saved = w.build_scenario()

    path = tmp_path / "case.json"
    save_scenario(saved, path)
    w.reset_defaults()
    assert w.products == []          # the reset really cleared it
    w.apply_scenario(load_scenario(path))

    back = w.build_scenario()
    assert back.extraction.enabled is True
    assert [p.name for p in back.products] == [p.name for p in saved.products]
    assert len(w.custom_materials) == 1
    assert back.waste_feed.enabled is True
    assert back.batch_mode is True
    assert back.batch_size_kg == pytest.approx(saved.batch_size_kg)
    assert (run_scenario(back).tea.production_cost_eur_per_kg
            == pytest.approx(run_scenario(saved).tea.production_cost_eur_per_kg))


# --------------------------------------------------------------------------- #
# QA-008 — reset must reset
# --------------------------------------------------------------------------- #
def test_reset_clears_all_advanced_state(omega3_window):
    w = omega3_window
    w.custom_materials = [Material("Yeast extract", 0.04, 2.5, 1.8, 30.0)]
    w.chk_waste.setChecked(True)
    w.reset_defaults()

    assert w.products == []
    assert w.extraction.enabled is False
    assert w.custom_materials == []
    assert w.waste_feed.enabled is False
    assert w.batch_mode is False
    assert w.credits_per_year == 0.0 and w.other_opex_per_year == 0.0
    assert w.chk_extraction.isChecked() is False
    assert w.chk_waste.isChecked() is False
    assert w.chk_batch.isChecked() is False
    assert w.results.main_product is None


# --------------------------------------------------------------------------- #
# QA-004 / QA-009 — the export and the screen must agree
# --------------------------------------------------------------------------- #
def test_export_matches_main_product_kpis(omega3_window, tmp_path):
    w = omega3_window
    data = results_to_dict(w.results)

    assert data["basis"]["reference_product"] == "Omega-3 oil"
    assert data["basis"]["functional_unit"] == "1 kg Omega-3 oil"
    assert data["basis"]["allocation_method"] == "economic"

    kpi_cost = float(w.kpi["cost"]._value.text().replace(",", ""))
    kpi_gwp = float(w.kpi["gwp"]._value.text().replace(",", ""))
    assert data["headline"]["production_cost_eur_per_kg"] == pytest.approx(kpi_cost, abs=5e-3)
    assert data["headline"]["gwp_kg_co2eq_per_kg"] == pytest.approx(kpi_gwp, abs=5e-3)

    # Both bases present, and clearly not the same number under the same name.
    assert data["biomass_basis"]["production_cost_eur_per_kg"] < kpi_cost
    assert data["main_product_basis"]["annual_kg"] == pytest.approx(
        w.results.main_product.annual_kg)
    assert json.dumps(data)          # strict JSON: no Infinity, no NaN


def test_export_carries_the_scenario_that_made_it(omega3_window, tmp_path):
    path = tmp_path / "results.json"
    from algametrix.serialization import save_results, scenario_from_dict

    save_results(omega3_window.results, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    restored = scenario_from_dict(data["scenario"])
    assert restored.organism.name == omega3_window.organism.name
    assert len(restored.products) == 3


def test_the_kpi_cards_name_their_functional_unit(omega3_window):
    w = omega3_window
    assert "Omega-3 oil" in w.kpi["cost"]._unit.text()
    assert "Omega-3 oil" in w.kpi["gwp"]._unit.text()
    assert w.kpi["output"]._title.text() == "Main product output"
    assert "1 kg Omega-3 oil" in w.subtitle.text()


def test_whole_biomass_case_says_dry_biomass(window):
    assert window.results.main_product is None
    assert window.kpi["output"]._title.text() == "Dry biomass output"
    assert "1 kg dry biomass" in window.subtitle.text()


def test_itemised_cost_table_adds_up_to_the_cost_kpi(omega3_window):
    """The allocated €/kg column must total the production-cost KPI."""
    w = omega3_window
    rows = {
        w.tbl_tea.item(r, 0).text(): float(w.tbl_tea.item(r, 1).text().replace(",", ""))
        for r in range(w.tbl_tea.rowCount())
    }
    total = rows["Annual operating cost"]
    assert total == pytest.approx(w.results.main_product.production_cost_eur_per_kg, rel=1e-3)
    assert f"€ / kg Omega-3 oil" == w.tbl_tea.horizontalHeaderItem(1).text()


# --------------------------------------------------------------------------- #
# QA-011 — a control that does nothing must say so
# --------------------------------------------------------------------------- #
def test_irrelevant_controls_are_disabled_by_trophic_mode(window):
    het = next(n for n, s in window.lib.systems.items() if s.mode == TrophicMode.HETEROTROPHIC)
    photo = next(n for n, s in window.lib.systems.items() if s.mode == TrophicMode.PHOTOTROPHIC)

    window.cmb_sys.setCurrentText(het)
    assert window._spins[("system", "co2_utilization")].isEnabled() is False
    assert window.cmb_carbon.isEnabled() is False
    assert window._spins[("system", "substrate_yield")].isEnabled() is True
    assert window._spins[("economics", "substrate_price")].isEnabled() is True

    window.cmb_sys.setCurrentText(photo)
    assert window._spins[("system", "substrate_yield")].isEnabled() is False
    assert window._spins[("lcia", "substrate_gwp")].isEnabled() is False
    assert window._spins[("system", "co2_utilization")].isEnabled() is True


def test_disabled_controls_explain_themselves(window):
    photo = next(n for n, s in window.lib.systems.items() if s.mode == TrophicMode.PHOTOTROPHIC)
    window.cmb_sys.setCurrentText(photo)
    tip = window._spins[("system", "substrate_yield")].toolTip()
    assert "phototrophic" in tip.lower()


def test_waste_feed_detail_is_dead_until_the_stream_is_fed(window):
    assert window.spn_waste_cov.isEnabled() is False
    window.chk_waste.setChecked(True)
    assert window.spn_waste_cov.isEnabled() is True
    # The displaced-treatment field only means something under system expansion.
    window.cmb_waste_conv.setCurrentText("cut_off")
    assert window.spn_waste_avoided.isEnabled() is False
    window.cmb_waste_conv.setCurrentText("avoided_treatment")
    assert window.spn_waste_avoided.isEnabled() is True
    assert (window.build_scenario().waste_feed.convention
            is WasteBurdenConvention.AVOIDED_TREATMENT)


def test_extraction_fields_are_dead_while_extraction_is_off(window):
    assert window.chk_extraction.isChecked() is False
    for widget in (window.cmb_ext_tech, window.spn_oil_rec, window.spn_oil_price,
                   window.cmb_alloc, window.cmb_downstream):
        assert widget.isEnabled() is False
    window.chk_extraction.setChecked(True)
    assert window.cmb_ext_tech.isEnabled() is True
    assert window.spn_oil_rec.isEnabled() is True


def test_batch_fields_are_dead_in_continuous_operation(window):
    assert window.spn_batch_size.isEnabled() is False
    window.chk_batch.setChecked(True)
    assert window.spn_batch_size.isEnabled() is True


def test_pigment_case_disables_the_lipid_fields_it_has_no_product_for(window):
    window.apply_scenario(build_template("C-phycocyanin (Spirulina)", window.lib))
    assert window.chk_extraction.isChecked() is True
    assert window.spn_oil_rec.isEnabled() is False    # products are yield-override based
    assert "no lipid product" in window.spn_oil_rec.toolTip().replace("defines ", "")
    assert window._main_product().name.startswith("C-phycocyanin")


# --------------------------------------------------------------------------- #
# QA-010 — an inadmissible case is not computed, exported or analysed
# --------------------------------------------------------------------------- #
def test_zero_productivity_is_not_computed(window):
    window._spins[("system", "productivity")].setValue(0.0)
    assert window.results is None
    assert window.kpi["cost"]._value.text() == "—"
    assert any(i.field == "system.productivity" for i in window.issues)
    assert window.lbl_issues.isHidden() is False
    assert "not physically admissible" in window.lbl_issues.text()


def test_the_case_recovers_when_the_input_is_fixed(window):
    window._spins[("system", "productivity")].setValue(0.0)
    window._spins[("system", "productivity")].setValue(20.0)
    assert window.results is not None
    assert window.lbl_issues.isHidden() is True
    assert window.kpi["cost"]._value.text() != "—"


def test_zero_substrate_yield_is_rejected_not_floored(window):
    het = next(n for n, s in window.lib.systems.items() if s.mode == TrophicMode.HETEROTROPHIC)
    window.cmb_sys.setCurrentText(het)
    assert window.results is not None
    window._spins[("system", "substrate_yield")].setValue(0.0)
    assert window.results is None          # not 1e-6, and not 866,682 €/kg
    assert any(i.field == "system.substrate_yield" for i in window.issues)


def test_export_is_refused_while_the_case_is_inadmissible(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "nope.json"), ""))
    window._spins[("system", "productivity")].setValue(0.0)
    window.export_results()
    assert warned, "the export went ahead without a result"
    assert not (tmp_path / "nope.json").exists()


def test_a_warning_does_not_block_the_run(window):
    """An unusual input is flagged; only an impossible one stops the engine."""
    window._spins[("organism", "carbon")].setValue(0.60)   # composition still fine
    window._spins[("system", "co2_utilization")].setValue(0.05)
    window.organism.protein += 0.08
    window.recompute()
    assert window.results is not None
    assert window.kpi["cost"]._value.text() != "—"


# --------------------------------------------------------------------------- #
# QA-001 / QA-002 — the shipped application has to start
# --------------------------------------------------------------------------- #
def test_self_test_builds_the_default_scenario(qapp, tmp_path, capsys):
    """What CI runs against the packaged .exe, run here against the source."""
    from desktop.app import self_test

    out = tmp_path / "smoke.txt"
    assert self_test(str(out)) == 0
    report = out.read_text(encoding="utf-8")
    assert "self-test: PASS" in report
    assert "production cost" in report
    assert "PDF report" in report      # the report module survived the bundling
    assert "language" in report        # and the language the build starts in


def test_the_entry_point_says_what_to_install(monkeypatch, capsys):
    """Without PySide6 the command must instruct, not raise ImportError."""
    import desktop.app as app

    monkeypatch.setattr(app, "missing_desktop_requirements", lambda: ["PySide6"])
    assert app.main(["algametrix"]) == 1
    message = capsys.readouterr().err
    assert 'pip install "algametrix[desktop]"' in message
    assert "the Qt user interface" in message


# --------------------------------------------------------------------------- #
# Released builds ship without the Process Designer (desktop/features.py)
# --------------------------------------------------------------------------- #
def test_the_process_designer_is_off_by_default(window):
    from desktop.features import PROCESS_DESIGNER

    assert PROCESS_DESIGNER is False
    assert window.flowsheet_editor is None
    assert window.top_tabs is None          # one view, so no tab bar to switch it
    assert not any(name.startswith("desktop.flowsheet.editor") for name in sys.modules)


def test_the_pdf_report_still_exports_without_a_diagram(window, monkeypatch, tmp_path):
    """Every page but the flow diagram and the stream table is unaffected."""
    from PySide6.QtWidgets import QFileDialog

    out = tmp_path / "report.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    window.export_process_report()
    assert out.exists() and out.stat().st_size > 10_000
