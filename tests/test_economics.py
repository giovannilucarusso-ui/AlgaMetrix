"""Tests for the expanded economics: capital structure, profitability, materials, sensitivity."""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Material, Scenario
from microalgae_tea_lca.scenario import run_scenario
from microalgae_tea_lca.sensitivity import PARAMETERS, run_sweep
from microalgae_tea_lca.tea import irr, npv


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


def test_sensitivity_sweep_scale(lib):
    base = base_scenario(lib, price=8.0)
    scale_param = next(p for p in PARAMETERS if p.name == "Plant scale")
    values = [50_000, 100_000, 200_000, 400_000]
    points = run_sweep(base, scale_param, values)
    assert len(points) == len(values)
    costs = [p.results.tea.production_cost_eur_per_kg for p in points]
    # Larger plants spread fixed costs -> lower unit production cost.
    assert costs == sorted(costs, reverse=True)
