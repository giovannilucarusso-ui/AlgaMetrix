"""Tests for extra LCA categories, Monte-Carlo uncertainty and comparison."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.benchmarks import check_benchmarks, infer_category, load_market_prices
from algametrix.comparison import KPI_ORDER, scenario_kpis
from algametrix.inventory import build_inventory
from algametrix.library import load_library
from algametrix.models import Scenario
from algametrix.scenario import run_scenario
from algametrix.sensitivity import PARAMETERS
from algametrix.uncertainty import run_montecarlo


@pytest.fixture(scope="module")
def lib():
    return load_library()


def base(lib):
    return Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000,
        product_price=8.0,
    )


def test_new_organisms_loaded(lib):
    for name in ("Aurantiochytrium sp.", "Tetraselmis suecica", "Phaeodactylum tricornutum"):
        assert name in lib.organisms


def test_impact_categories_present(lib):
    lca = run_scenario(base(lib)).lca
    for cat in ("GWP (kg CO₂-eq)", "Marine eutrophication (kg N-eq)",
                "Freshwater eutrophication (kg P-eq)", "Acidification (kg SO₂-eq)"):
        assert cat in lca.impacts
    # Eutrophication and acidification are non-negative.
    assert lca.impacts["Acidification (kg SO₂-eq)"] > 0
    assert lca.impacts["Marine eutrophication (kg N-eq)"] > 0


def test_nutrient_emissions(lib):
    inv = build_inventory(base(lib))
    uptake = 0.90  # raceway default
    assert inv.nitrogen_emitted_per_kg == pytest.approx(inv.nitrogen_per_kg * (1 - uptake))
    assert inv.phosphorus_emitted_per_kg == pytest.approx(inv.phosphorus_per_kg * (1 - uptake))


def test_montecarlo_distribution(lib):
    scale = next(p for p in PARAMETERS if p.name == "Plant scale")
    price = next(p for p in PARAMETERS if p.name == "Product price")
    mc = run_montecarlo(base(lib), [(scale, 0.3), (price, 0.25)], n=200, seed=1)
    assert mc.n == 200
    s = mc.stats("Production cost (€/kg)")
    assert s["p10"] <= s["p50"] <= s["p90"]
    assert s["min"] <= s["mean"] <= s["max"]
    # Reproducible with a fixed seed.
    mc2 = run_montecarlo(base(lib), [(scale, 0.3), (price, 0.25)], n=200, seed=1)
    assert mc.series["NPV (€)"][:5] == mc2.series["NPV (€)"][:5]


def test_comparison_kpis(lib):
    kpis = scenario_kpis(run_scenario(base(lib)))
    assert list(kpis.keys()) == KPI_ORDER
    assert kpis["Production cost (€/kg)"] > 0


def test_benchmarks_open_literature(lib):
    r = run_scenario(base(lib))          # raceway Chlorella
    assert infer_category(r.scenario.system) == "open_pond"
    rows = check_benchmarks(r)
    assert rows                           # some benchmarks apply
    # The default raceway scenario should sit within the published ranges.
    assert all(row.in_range for row in rows), [
        (row.metric, row.model, row.low, row.high) for row in rows if not row.in_range
    ]
    # Each row carries a citable source.
    assert all(row.source for row in rows)


def test_market_prices_loaded():
    prices = load_market_prices()
    assert prices
    assert all(p.low <= p.high for p in prices)
    assert all(p.source for p in prices)


def test_energy_credit_lowers_net_cost(lib):
    scn = base(lib)
    r0 = run_scenario(scn)
    scn.credits_per_year = 500_000.0
    r1 = run_scenario(scn)
    # A credit lowers the net production cost and raises NPV; gross AOC is unchanged.
    assert r1.tea.net_production_cost_eur_per_kg < r0.tea.net_production_cost_eur_per_kg
    assert r1.tea.npv > r0.tea.npv
    assert r1.tea.annual_opex == pytest.approx(r0.tea.annual_opex)


def test_batch_mode(lib):
    scn = base(lib)                 # raceway: operating_days 330, recovery 0.90
    scn.batch_mode = True
    scn.batch_size_kg = 1000.0
    scn.batch_cycle_time_h = 24.0
    inv = build_inventory(scn)
    assert inv.batches_per_year == pytest.approx(330.0 * 24.0 / 24.0)
    assert inv.annual_biomass_kg == pytest.approx(1000.0 * 330.0 * scn.harvesting.recovery)
    assert inv.batch_product_kg == pytest.approx(1000.0 * scn.harvesting.recovery)
