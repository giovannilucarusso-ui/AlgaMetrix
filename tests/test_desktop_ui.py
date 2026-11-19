"""The redesigned screens: every number with its unit and basis, every state shown.

Off-screen, against the real :class:`MainWindow`, like ``test_desktop_window``.
These pin down what the design guidelines (docs/UI_GUIDELINES.md) promise.
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

pytest.importorskip("PySide6", reason="the desktop client needs PySide6")
pytest.importorskip("matplotlib", reason="the results panel embeds matplotlib")

from PySide6.QtWidgets import QApplication  # noqa: E402

from algametrix.models import TrophicMode  # noqa: E402
from desktop import evidence, fields, fmt, theme  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from desktop.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


# --------------------------------------------------------------------------- #
# Formatting and tokens
# --------------------------------------------------------------------------- #
def test_significant_figures_never_overstate_precision():
    assert fmt.sig(0.000457) == "0.000457"
    assert fmt.sig(1234.5) == "1,234"
    assert fmt.sig(17.55, 3) == "17.6"
    assert fmt.sig(0.5) == "0.5"
    assert fmt.sig(float("nan")) == fmt.DASH
    assert fmt.sig(None) == fmt.DASH
    assert fmt.money(2.34e6) == "€ 2.34 M"
    assert fmt.compact(23456) == "23.5k"


def test_the_stylesheet_builds_and_the_theme_applies_once(qapp):
    assert "QDoubleSpinBox[issue=\"error\"]" in theme.STYLESHEET
    assert "inherit" not in theme.STYLESHEET      # not a Qt stylesheet value
    theme.apply_to(qapp)
    theme.apply_to(qapp)
    assert qapp.property("algametrix_theme_applied") is True


# --------------------------------------------------------------------------- #
# Inputs: unit, range and provenance on every field
# --------------------------------------------------------------------------- #
def test_every_numeric_field_is_catalogued_with_a_unit_and_a_range(window):
    assert window._spins, "no fields were built"
    for key, sb in window._spins.items():
        spec = fields.spec(*key)
        # A greyed-out row carries its reason instead; the catalogue text is kept.
        tip = window._base_tooltips[id(sb)]
        assert spec.label in tip
        assert "Accepts" in tip
        assert sb.minimum() == pytest.approx(spec.lo)
        assert sb.maximum() == pytest.approx(spec.hi)
        assert sb.decimals() == spec.decimals


def test_a_background_factor_cites_the_source_the_data_declares(window):
    tip = window._spins[("lcia", "elec_gwp")].toolTip()
    assert "Source:" in tip
    assert "EU-27" in tip
    assert "indicative" in tip


def test_an_economic_default_is_not_given_an_invented_source(window):
    tip = window._spins[("economics", "electricity_price")].toolTip()
    assert "Source:" not in tip
    assert "placeholder" in tip


def test_units_follow_the_sizing_basis(window):
    het = next(n for n, s in window.lib.systems.items() if s.mode == TrophicMode.HETEROTROPHIC)
    window.cmb_sys.setCurrentText(het)
    unit = window.sec_cultivation._units[id(window.spn_productivity)].text()
    assert unit == "g/L/d"
    assert "g/L/d" in window.spn_productivity.toolTip()
    assert window.sec_cultivation._units[id(window.spn_scale)].text() == "m³"


def test_preset_notes_follow_the_combo(window):
    window.cmb_harv.setCurrentText("Membrane filtration")
    assert "membrane" in window.lbl_harv_notes.text().lower()


def test_an_inadmissible_input_is_marked_on_its_own_field(window):
    sb = window._spins[("system", "productivity")]
    sb.setValue(0.0)
    assert sb.property("issue") == "error"
    assert "Check:" in sb.toolTip()
    sb.setValue(20.0)
    assert sb.property("issue") == ""
    assert "Check:" not in sb.toolTip()


def test_a_warning_marks_the_field_amber_without_blocking(window):
    sb = window._spins[("organism", "carbon")]
    sb.setValue(0.60)      # far from what the composition implies, still possible
    assert sb.property("issue") == "warning"
    assert "Check:" in sb.toolTip()
    assert window.results is not None


def test_the_filter_hides_sections_without_a_match(window):
    window.input_search.setText("discount")
    shown = [s.title for s in window.sections if not s.isHidden()]
    assert shown == ["Economics"]
    window.input_search.setText("")
    assert all(not s.isHidden() for s in window.sections)


# --------------------------------------------------------------------------- #
# Results: unit and basis on every number, states before an analysis
# --------------------------------------------------------------------------- #
def test_kpi_tiles_state_their_unit_and_basis(window):
    for card in window.kpi.values():
        assert card._unit.text()
        assert card._basis.text()
    assert "plant gate" in window.kpi["cost"]._basis.text()
    assert "cradle-to-gate" in window.kpi["gwp"]._basis.text()


def test_the_overview_states_boundary_allocation_and_price_basis(window):
    html = window.lbl_basis.text()
    for phrase in ("Functional unit", "cradle-to-gate", "Allocation", "EUR as entered"):
        assert phrase in html
    assert window.chip_fu.text() == "1 kg dry biomass"


def test_tab_labels_are_words_not_pictographs(window):
    for i in range(window.tabs.count()):
        text = window.tabs.tabText(i)
        assert text and all(ord(ch) < 0x2000 for ch in text), text


def test_analyses_start_from_an_empty_state(window):
    assert window.tbl_sens.isHidden()
    assert window.tbl_compare.isHidden()
    assert not window.empty_cmp.isHidden()
    window.run_sensitivity()
    assert not window.tbl_sens.isHidden()
    assert window.tbl_sens.rowCount() > 0
    window.snapshot_scenario()
    assert not window.tbl_compare.isHidden()
    assert window.tbl_compare.columnCount() == 1
    assert window.empty_cmp.isHidden()


@pytest.mark.parametrize("size", [(1180, 760), (1440, 900)])
def test_an_empty_state_hint_gets_the_height_its_text_needs(window, qapp, size):
    """The hint used to be drawn narrower than the height it was given, and lost lines."""
    from desktop.results_panel import TAB_COMPARE, TAB_PRODUCTS

    window.resize(*size)
    window.show()
    # The default case is a single product, and no snapshot has been taken yet.
    for tab, state in ((TAB_PRODUCTS, window.empty_products), (TAB_COMPARE, window.empty_cmp)):
        window.tabs.setCurrentIndex(tab)
        for _ in range(3):
            qapp.processEvents()
        assert state.isVisible()
        hint = state._hint
        assert hint.isVisible() and hint.text()
        assert hint.heightForWidth(hint.width()) <= hint.height()


def test_product_tonnage_keeps_three_significant_figures(window):
    """A small plant listed its products in whole tonnes, and under half a tonne read 0."""
    from algametrix.templates import get_template, set_scale_from_target

    scn = get_template("Algal-oil biorefinery (phototrophic)").build(window.lib)
    set_scale_from_target(scn, 3.0)
    window.apply_scenario(scn)
    table = window.tbl_products
    shown = [table.item(r, 1).text() for r in range(table.rowCount())]
    assert shown == [fmt.sig(p.annual_kg / 1000, 3) for p in window.results.products]
    assert any("." in text for text in shown)


def test_the_report_page_says_what_each_analysis_adds(window):
    text = window.lbl_report_pages.text()
    assert "Sensitivity sweep" in text and "needs" in text
    window.run_sensitivity()
    assert "Sensitivity sweep <span" in window.lbl_report_pages.text()


def test_exports_are_disabled_while_the_case_is_inadmissible(window):
    window._spins[("system", "productivity")].setValue(0.0)
    assert not window.btn_export_pdf.isEnabled()
    window._spins[("system", "productivity")].setValue(20.0)
    assert window.btn_export_pdf.isEnabled()


# --------------------------------------------------------------------------- #
# Validation page: evidence classes and caveats stay visible
# --------------------------------------------------------------------------- #
def test_evidence_classes_join_by_doi_and_by_author_year():
    records = evidence.load_records()
    assert records
    padi = evidence.match("Padi et al. 2023, Algal Research 74:103190",
                          "https://doi.org/10.1016/j.algal.2023.103190", records)
    assert padi is not None and padi.evidence_class == "range"
    ahmed = evidence.match("Frontiers Sust. Food Syst. 2026 (organic spirulina, Italy)",
                           "https://www.frontiersin.org/journals/sustainable-food-systems/"
                           "articles/10.3389/fsufs.2026.1763476/full", records)
    assert ahmed is not None and ahmed.evidence_class == "calibrated"
    assert evidence.match("Nobody et al. 1999", "", records) is None


def test_the_validation_library_prints_the_class_in_the_row(window):
    table = window.tbl_library
    assert table.rowCount() > 0
    assert table.horizontalHeaderItem(2).text() == "Evidence class"
    rows = {table.item(r, 0).text(): table.item(r, 2).text() for r in range(table.rowCount())}
    assert "range" in next(v for k, v in rows.items() if k.startswith("Padi"))
    assert "calibrated" in next(v for k, v in rows.items() if k.startswith("Frontiers"))
    assert any(v == "not in evidence set" for v in rows.values())


def test_the_caveat_stays_on_the_validation_page(window):
    assert "prospective validation" in window.banner_caveat.text()
    assert not window.banner_caveat.isHidden()


def test_a_reference_comparison_gives_its_verdict_in_words(window):
    from desktop.results_panel import TAB_VALIDATION

    window.load_bundled_reference("reference_superpro_heterotrophic.csv")
    assert window.tabs.currentIndex() == TAB_VALIDATION
    table = window.tbl_reference
    assert not table.isHidden() and table.rowCount() > 0
    verdicts = {table.item(r, 5).text() for r in range(table.rowCount())}
    assert verdicts <= {"within 10%", "within 25%", "beyond 25%", "no reference"}
    assert table.horizontalHeaderItem(1).text() == "Unit"
