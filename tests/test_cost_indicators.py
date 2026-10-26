"""Production cost, allocated cost and break-even price (Tables C and D).

The break-even price comes out of a bisection on the NPV, so these tests check
it against the closed form it must reduce to when tax, working capital and
start-up cost are set to zero. The allocated values are checked against the
allocation shares they are built from, and the values the manuscript quotes are
pinned, so a change that moves one of them has to be explained.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix.library import load_library  # noqa: E402
from algametrix.paper import (  # noqa: E402
    archetypes,
    costindicators,
    reconstructions,
    report,
    suite,
    supplementary,
)
from algametrix.scenario import minimum_selling_price, run_scenario  # noqa: E402

#: Absolute price tolerance of the bisection in minimum_selling_price.
PRICE_TOL = 1e-3


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def break_even(lib):
    return {r.key: r for r in costindicators.break_even_rows(lib)}


@pytest.fixture(scope="module")
def multi(lib):
    return {r.key: r for r in costindicators.multi_product_rows(lib)}


def _untaxed(scn):
    eco = replace(scn.economics, tax_rate=0.0, working_capital_frac=0.0, startup_frac=0.0)
    return replace(scn, economics=eco)


def test_capital_recovery_factor():
    assert costindicators.crf(0.08, 20) == pytest.approx(0.10185, abs=1e-5)
    assert costindicators.crf(0.0, 20) == pytest.approx(0.05)


@pytest.mark.parametrize("key", [a.key for a in archetypes.ARCHETYPES])
def test_without_tax_the_gap_is_the_capital_recovery_term(lib, key):
    """p* - c_prod = C_DFC [CRF(i, n) - 1/n_dep] / m, also with n_dep < n."""
    scn = _untaxed(archetypes.build(key, lib))
    res = run_scenario(scn)
    p_star = minimum_selling_price(scn)
    expected = res.tea.production_cost_eur_per_kg * (1 + costindicators.simplified_gap(scn))
    assert p_star == pytest.approx(expected, abs=PRICE_TOL)


def test_without_tax_a_multi_product_break_even_nets_the_co_products(lib):
    """p* = (AOC - D + C_DFC CRF - R_co) / m_main, R_co including other credits."""
    scn = _untaxed(reconstructions.build("algal_oil", lib))
    res = run_scenario(scn)
    eco, tea = scn.economics, res.tea
    main = res.main_product
    co_revenue = sum(p.revenue for p in res.products if not p.is_main)
    numerator = (tea.annual_opex - tea.depreciation
                 + tea.dfc * costindicators.crf(eco.discount_rate, eco.plant_lifetime)
                 - co_revenue - scn.credits_per_year - scn.coproduct_revenue_per_year)
    assert scn.credits_per_year > 0          # the case exercises the credit term
    assert minimum_selling_price(scn) == pytest.approx(numerator / main.annual_kg,
                                                       abs=PRICE_TOL)


def test_tax_and_working_capital_widen_the_gap(lib, break_even):
    for row in break_even.values():
        assert row.gap > row.simplified_gap


def test_archetypes_come_first_and_their_reconstructions_are_not_repeated(break_even):
    keys = list(break_even)
    assert keys[:3] == [f"arch_{a.key}" for a in archetypes.ARCHETYPES]
    twins = {r.same_as for r in break_even.values() if r.same_as}
    assert twins == {"scp_protein", "heterotrophic_powder"}
    assert not {f"rec_{t}" for t in twins} & set(keys)


def test_gwp_only_and_multi_product_reconstructions_are_left_out(lib, break_even):
    for name in reconstructions.GWP_ONLY:
        assert f"rec_{name}" not in break_even
    for name in reconstructions.available():
        if reconstructions.build(name, lib).products:
            assert f"rec_{name}" not in break_even


def test_table_c_holds_every_multi_product_scenario_of_the_suite(lib, multi):
    cases, _ = suite.distinct_cases(lib)
    assert len(multi) == suite.coverage(lib, cases)["multi-product allocation"] == 5


def test_allocated_values_follow_from_the_shares(multi):
    for r in multi.values():
        a = r.allocated
        assert a["none"].share == 1.0
        assert a["none"].cost == pytest.approx(r.production_cost / r.main_yield)
        for method in costindicators.ALLOCATIONS:
            share = a[method].share
            assert a[method].cost == pytest.approx(r.production_cost * share / r.main_yield)
            assert a[method].gwp_gross == pytest.approx(r.gwp_gross * share / r.main_yield)
        assert r.gwp_ratio == pytest.approx(a["economic"].share / a["mass"].share)


def test_the_values_the_manuscript_quotes(break_even, multi):
    """Section 2.3 and Tables C and D quote these. Explain a change, then update."""
    gaps = [round(break_even[f"arch_{a.key}"].gap * 100) for a in archetypes.ARCHETYPES]
    assert gaps == [13, 5, 4]
    assert round(break_even["rec_tredici2016"].gap * 100) == 17
    assert round(break_even["rec_vazquez2022b_nas_10ha"].gap * 100) == 58
    assert round(break_even["rec_vazquez2022b_nas_10ha"].depreciation_share * 100) == 54
    assert round(multi["rec_astaxanthin"].gwp_ratio) == 39
    assert round(multi["rec_phycocyanin"].gwp_ratio) == 15
    assert round(multi["rec_omega3"].gwp_ratio, 1) == 2.6
    assert sum(r.gwp_net < 0 for r in multi.values()) == 2


def test_the_report_names_what_it_leaves_out_and_fits_the_page(break_even, multi):
    text = report.cost_indicators(list(break_even.values()), list(multi.values()),
                                  costindicators.left_out_of_break_even())
    for name in reconstructions.GWP_ONLY:
        assert name in text
    assert "Identical to the reconstruction 'scp_protein'" in text
    assert supplementary._widest_table_row(text) <= supplementary.PRINT_WIDTH
