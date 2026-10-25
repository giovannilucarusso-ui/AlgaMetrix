"""Tests for the expanded economics: capital structure, profitability, materials, sensitivity."""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.models import Material, Scenario
from algametrix.scenario import run_scenario
from algametrix.sensitivity import PARAMETERS, run_sweep
from algametrix.tea import depreciation_schedule, irr, npv


@pytest.fixture(scope="module")
def lib():
    return load_library()


def base_scenario(lib, price=0.0):
    return Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000,
        product_price=price,
    )


def test_capex_structure(lib):
    r = run_scenario(base_scenario(lib))
    t = r.tea
    assert t.total_investment == pytest.approx(t.dfc + t.working_capital + t.startup_cost)
    assert sum(t.capex_breakdown.values()) == pytest.approx(t.total_investment, rel=1e-9)
    assert t.total_capex == t.total_investment  # backward-compatible alias


def test_opex_breakdown_sums_to_aoc(lib):
    t = run_scenario(base_scenario(lib)).tea
    assert sum(t.opex_breakdown.values()) == pytest.approx(t.annual_opex, rel=1e-9)
    assert sum(t.opex_categories.values()) == pytest.approx(t.annual_opex, rel=1e-9)


def test_explicit_material_raises_cost(lib):
    base = base_scenario(lib)
    with_mat = copy.deepcopy(base)
    with_mat.materials = [Material("Yeast extract", amount_per_kg=0.5, price=7.5, gwp=1.5, ced=20.0)]
    c0 = run_scenario(base).tea.production_cost_eur_per_kg
    c1 = run_scenario(with_mat).tea.production_cost_eur_per_kg
    # 0.5 kg/kg * 7.5 EUR/kg = 3.75 EUR/kg direct, plus overhead on it.
    direct = 0.5 * 7.5
    assert c1 - c0 == pytest.approx(direct * (1 + lib.economics.overhead_frac), abs=1e-6)
    # And its GWP shows up in the LCA.
    g0 = run_scenario(base).lca.gwp_kg_co2eq_per_kg
    g1 = run_scenario(with_mat).lca.gwp_kg_co2eq_per_kg
    assert g1 - g0 == pytest.approx(0.5 * 1.5, abs=1e-6)


def test_profitability_sign(lib):
    cheap = run_scenario(base_scenario(lib, price=0.0)).tea
    rich = run_scenario(base_scenario(lib, price=50.0)).tea
    assert cheap.revenues == 0.0
    assert cheap.gross_profit < 0          # no sales -> loss
    assert rich.gross_profit > 0
    assert rich.npv > cheap.npv
    # Taxes only on positive profit.
    assert cheap.taxes == 0.0
    assert rich.taxes > 0.0


def test_npv_irr_consistency():
    cash_flows = [-1000.0, 300.0, 300.0, 300.0, 300.0, 300.0]
    rate = irr(cash_flows)
    assert rate is not None
    assert npv(rate, cash_flows) == pytest.approx(0.0, abs=1.0)


def test_depreciation_stops_when_the_asset_is_written_off():
    assert depreciation_schedule(100.0, 2.5, 5) == pytest.approx([40.0, 40.0, 20.0, 0.0, 0.0])
    assert sum(depreciation_schedule(100.0, 10, 20)) == pytest.approx(100.0)
    # A period longer than the plant life leaves part of the asset undepreciated.
    assert sum(depreciation_schedule(100.0, 25, 20)) == pytest.approx(80.0)
    assert depreciation_schedule(100.0, 0, 3) == [0.0, 0.0, 0.0]


def test_npv_and_irr_are_computed_on_the_reported_series(lib):
    t = run_scenario(base_scenario(lib, price=50.0)).tea
    eco = lib.economics
    assert len(t.cash_flows) == int(round(eco.plant_lifetime)) + 1
    assert t.cash_flows[0] == pytest.approx(-t.total_investment)
    assert t.npv == pytest.approx(npv(eco.discount_rate, t.cash_flows), rel=1e-9)
    assert t.irr is not None
    assert npv(t.irr, t.cash_flows) == pytest.approx(0.0, abs=1e-6 * t.total_investment)


def test_the_tax_shield_ends_with_the_depreciation_period(lib):
    scn = base_scenario(lib, price=50.0)
    scn.economics = replace(lib.economics, plant_lifetime=20, depreciation_years=10)
    eco = scn.economics
    t = run_scenario(scn).tea
    shield = eco.tax_rate * t.dfc / eco.depreciation_years
    assert t.gross_profit > 0                  # so the deduction is used in full
    assert t.cash_flows[10] - t.cash_flows[11] == pytest.approx(shield, rel=1e-9)
    # Up to 1.5 the shield ran for all 20 years, which overstated the NPV by its
    # present value in years 11 to 20.
    flat = [-t.total_investment] + [t.annual_cash_flow] * 20
    flat[-1] += t.working_capital
    lost = sum(shield / (1 + eco.discount_rate) ** year for year in range(11, 21))
    assert npv(eco.discount_rate, flat) - t.npv == pytest.approx(lost, rel=1e-9)


def test_depreciation_over_the_whole_plant_life_gives_a_flat_series(lib):
    """The one case the constant series of 1.5 and earlier got right."""
    scn = base_scenario(lib, price=50.0)
    scn.economics = replace(lib.economics, plant_lifetime=20, depreciation_years=20)
    t = run_scenario(scn).tea
    assert t.cash_flows[1:-1] == pytest.approx([t.annual_cash_flow] * 19, rel=1e-9)
    assert t.cash_flows[-1] == pytest.approx(t.annual_cash_flow + t.working_capital, rel=1e-9)


def test_without_tax_the_depreciation_period_does_not_move_npv(lib):
    """Depreciation is not a cash flow; it only matters through the tax it saves."""
    values = []
    for years in (5, 10, 20):
        scn = base_scenario(lib, price=50.0)
        scn.economics = replace(lib.economics, tax_rate=0.0, depreciation_years=years)
        values.append(run_scenario(scn).tea.npv)
    assert values == pytest.approx([values[0]] * len(values), rel=1e-9)


def test_sensitivity_sweep_scale(lib):
    base = base_scenario(lib, price=8.0)
    scale_param = next(p for p in PARAMETERS if p.name == "Plant scale")
    values = [50_000, 100_000, 200_000, 400_000]
    points = run_sweep(base, scale_param, values)
    assert len(points) == len(values)
    costs = [p.results.tea.production_cost_eur_per_kg for p in points]
    # Larger plants spread fixed costs -> lower unit production cost.
    assert costs == sorted(costs, reverse=True)
