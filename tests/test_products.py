"""Tests for the downstream extraction and multi-product allocation module."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.inventory import build_inventory
from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Extraction, Product, Scenario
from microalgae_tea_lca.products import product_masses, product_yield
from microalgae_tea_lca.scenario import run_scenario
from microalgae_tea_lca.validation import model_metrics


@pytest.fixture(scope="module")
def lib():
    return load_library()


def oil_scenario(lib, allocation="economic"):
    return Scenario(
        organism=lib.organisms["Nannochloropsis sp."],   # lipid 0.35, protein 0.35
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["No drying (wet paste)"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=1_000_000,
        extraction=Extraction(
            enabled=True, solvent_kg_per_kg=5.0, solvent_recovery=0.99,
            solvent_price=1.5, solvent_gwp=0.9, solvent_ced=55.0,
            elec_kwh_per_kg=0.3, heat_mj_per_kg=2.0, capex_per_kgyr=1.0,
            allocation=allocation,
        ),
        products=[
            Product("Algal oil", "lipid", recovery=0.90, price=2.5, is_main=True),
            Product("Protein meal", "protein", recovery=0.80, price=0.60),
            Product("Residual", "residual", recovery=1.0, price=0.10),
        ],
    )


def test_product_yield_from_composition(lib):
    scn = oil_scenario(lib)
    oil = scn.products[0]
    # lipid fraction 0.35 * recovery 0.90 = 0.315 kg oil / kg biomass
    assert product_yield(scn, oil) == pytest.approx(0.35 * 0.90)


def test_residual_is_leftover(lib):
    scn = oil_scenario(lib)
    residual = scn.products[2]
    # 1 - lipid*0.9 - protein*0.8
    expected = 1.0 - 0.35 * 0.90 - 0.35 * 0.80
    assert product_yield(scn, residual) == pytest.approx(expected)


def test_allocation_shares_sum_to_one(lib):
    r = run_scenario(oil_scenario(lib, "economic"))
    assert sum(p.allocation_share for p in r.products) == pytest.approx(1.0)
    r_mass = run_scenario(oil_scenario(lib, "mass"))
    assert sum(p.allocation_share for p in r_mass.products) == pytest.approx(1.0)


def test_none_allocation_loads_main_product(lib):
    r = run_scenario(oil_scenario(lib, "none"))
    main = r.main_product
    assert main.name == "Algal oil"
    assert main.allocation_share == pytest.approx(1.0)
    # Co-products carry no cost under "none" allocation.
    others = [p for p in r.products if not p.is_main]
    assert all(p.production_cost_eur_per_kg == 0.0 for p in others)


def test_extraction_adds_solvent_and_capex(lib):
    base = oil_scenario(lib)
    no_ext = copy.deepcopy(base)
    no_ext.extraction = Extraction(enabled=False)

    inv = build_inventory(base)
    assert inv.solvent_net_per_kg == pytest.approx(5.0 * (1 - 0.99))
    assert inv.elec_breakdown["extraction"] == pytest.approx(0.3)

    with_ext = run_scenario(base).tea
    without = run_scenario(no_ext).tea
    assert with_ext.total_investment > without.total_investment   # extraction CAPEX
    assert with_ext.annual_opex > without.annual_opex             # solvent + energy


def test_economic_allocation_tracks_revenue(lib):
    r = run_scenario(oil_scenario(lib, "economic"))
    total_rev = sum(p.revenue for p in r.products)
    for p in r.products:
        assert p.allocation_share == pytest.approx(p.revenue / total_rev)


def test_custom_yield_override_pigment(lib):
    # A high-value minor product (e.g. a pigment) defined by an explicit yield.
    scn = Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Membrane filtration"],
        drying=lib.drying["No drying (wet paste)"],
        economics=lib.economics, lcia=lib.lcia, scale=8_000,
        products=[
            Product("Pigment", "custom", yield_override=0.05, price=250.0, is_main=True),
            Product("Spent biomass", "custom", yield_override=0.90, price=1.0),
        ],
    )
    r = run_scenario(scn)
    assert r.main_product.name == "Pigment"
    assert r.main_product.annual_kg == pytest.approx(r.inventory.annual_biomass_kg * 0.05)
    # Economic allocation loads almost all cost onto the high-value pigment.
    assert r.main_product.allocation_share > 0.8
    assert r.main_product.production_cost_eur_per_kg > 10 * lib.economics.electricity_price


def test_model_metrics_use_main_product(lib):
    r = run_scenario(oil_scenario(lib))
    m = model_metrics(r)
    # For a biorefinery, validation metrics refer to the main product, not biomass.
    assert m["production_cost_eur_per_kg"] == pytest.approx(r.main_product.production_cost_eur_per_kg)
    assert m["annual_production_kg"] == pytest.approx(r.main_product.annual_kg)
    assert r.main_product.annual_kg < r.inventory.annual_biomass_kg
