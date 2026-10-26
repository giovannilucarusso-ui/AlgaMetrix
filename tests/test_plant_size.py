"""The plant-size sweep behind the SI figure on capital-cost scaling.

The sweep runs the heterotrophic archetype from a tenth to ten times its
reference plant, with the default cost model and with literature exponents.
These tests hold what the figure relies on: every case meets the archetype's own
result at the reference size, the default case is the archetype with only its
volume changed, the power laws do what their exponents say, and no size in the
sweep needs an input-check warning.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix.inputcheck import check_inputs  # noqa: E402
from algametrix.library import load_library  # noqa: E402
from algametrix.paper import archetypes, plantsize, report  # noqa: E402
from algametrix.scenario import run_scenario  # noqa: E402


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def ref(lib):
    return plantsize.reference(lib)


@pytest.fixture(scope="module")
def table(ref):
    return plantsize.sweep(ref)


def test_the_reference_is_the_calibrated_heterotrophic_plant(ref):
    """The exponents are anchored here because this plant's capital cost was set
    at this size. If the template changes, the anchor has to be checked again."""
    arch = archetypes.get(plantsize.ARCHETYPE)
    assert arch.kind == "study_reconstruction" and arch.study_id == "russo2022_aury"
    assert ref.volume_m3 == 150.0
    assert ref.cultivation_cost_per_m3 == 10_000.0


def test_every_case_gives_the_reference_result_at_the_reference_size(ref, table):
    i = plantsize.TABLE_MULTIPLES.index(1.0)
    for key, points in table.items():
        assert points[i].investment == (ref.investment, ref.investment), key
        assert points[i].cost == (ref.cost, ref.cost), key


def test_the_default_case_is_the_archetype_with_only_its_volume_changed(lib, ref, table):
    base = archetypes.build(plantsize.ARCHETYPE, lib)
    for k, point in zip(plantsize.TABLE_MULTIPLES, table["default"]):
        tea = run_scenario(replace(base, scale=ref.volume_m3 * k)).tea
        assert point.investment == (tea.total_investment,) * 2
        assert point.cost == (tea.production_cost_eur_per_kg,) * 2


def test_output_and_default_investment_are_proportional_to_volume(ref, table):
    for k, point in zip(plantsize.TABLE_MULTIPLES, table["default"]):
        assert point.output_kg == pytest.approx(ref.output_kg * k, rel=1e-12)
        assert point.investment[0] == pytest.approx(ref.investment * k, rel=1e-12)


def test_the_investment_follows_the_equipment_exponents(ref, table):
    """Every equipment group sits at k times its reference capacity, so the
    equipment part of the investment scales as k^n. Land stays proportional."""
    eco = ref.scenario.economics
    land = (run_scenario(ref.scenario).tea.capex_breakdown["Land"]
            * (1.0 + eco.working_capital_frac + eco.startup_frac))
    for k, point in zip(plantsize.TABLE_MULTIPLES, table["equipment"]):
        ends = [(ref.investment - land) * k ** n + land * k
                for n in plantsize.EQUIPMENT_EXPONENTS]
        assert point.investment == pytest.approx((min(ends), max(ends)), rel=1e-12)


@pytest.mark.parametrize("k", [0.1, 0.5, 2.0, 10.0])
def test_labour_that_grows_with_the_plant_moves_cost_but_not_capital(ref, k):
    """Below the reference a labour exponent costs less than a fixed figure, above
    it more, and the investment does not see it at all."""
    fixed = run_scenario(plantsize.resized(ref, ref.volume_m3 * k, 0.6, 0.0)).tea
    scaled = run_scenario(plantsize.resized(ref, ref.volume_m3 * k, 0.6, 0.25)).tea
    assert (scaled.production_cost_eur_per_kg < fixed.production_cost_eur_per_kg) == (k < 1)
    assert scaled.total_investment == fixed.total_investment


def test_no_size_in_the_sweep_needs_a_warning(ref):
    """The sweep stays within a factor of ten of the reference, where the input
    check accepts a power law without a declared range."""
    assert plantsize.FIGURE_MULTIPLES[0] == 0.1 and plantsize.FIGURE_MULTIPLES[-1] == 10.0
    for k in plantsize.FIGURE_MULTIPLES[::10]:
        for n, n_labour in product(plantsize.EQUIPMENT_EXPONENTS, plantsize.LABOUR_EXPONENTS):
            issues = check_inputs(plantsize.resized(ref, ref.volume_m3 * k, n, n_labour))
            assert not issues, (k, n, n_labour, [i.message for i in issues])


def test_the_report_prints_the_reference_and_every_size(ref, table):
    text = report.plant_size(ref, table)
    assert f"production cost     : {ref.cost:.2f} EUR/kg" in text
    for point in table["default"]:
        assert f"  {point.volume_m3:7.1f}  {point.output_kg / 1000:7.1f}   " in text
    # The change against the default is zero at the reference for both cases.
    assert "    150.0   +0.0%" in text
