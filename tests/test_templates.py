"""Tests for the wizard's scenario templates and sizing helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.models import Scenario
from algametrix.products import main_product
from algametrix.scenario import run_scenario
from algametrix.templates import (
    TEMPLATES,
    apply_goal,
    build_template,
    set_scale_from_target,
    template_names,
)


@pytest.fixture(scope="module")
def lib():
    return load_library()


def test_all_templates_build_and_run(lib):
    for t in TEMPLATES:
        r = run_scenario(t.build(lib))
        cost = (r.main_product.production_cost_eur_per_kg if r.main_product
                else r.tea.production_cost_eur_per_kg)
        assert cost > 0
        assert r.inventory.annual_biomass_kg > 0


def test_build_template_by_name(lib):
    assert "Biodiesel (Nannochloropsis)" in template_names()
    r = run_scenario(build_template("Biodiesel (Nannochloropsis)", lib))
    assert r.main_product.name.startswith("Biodiesel")


@pytest.mark.parametrize("goal,expect_products", [
    ("biomass", 0), ("protein", 0), ("oil", 3), ("pigment", 2), ("biofuel", 3),
])
def test_apply_goal(lib, goal, expect_products):
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000,
    )
    apply_goal(scn, goal)
    assert len(scn.products) == expect_products
    assert scn.extraction.enabled == (expect_products > 0)


def test_set_scale_from_target_hits_target(lib):
    scn = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    set_scale_from_target(scn, 500.0)     # want 500 t/yr of the main product
    r = run_scenario(scn)
    assert r.main_product.annual_kg / 1000 == pytest.approx(500.0, rel=1e-3)


def test_set_scale_from_target_biomass(lib):
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=1.0,
    )
    set_scale_from_target(scn, 250.0)     # 250 t biomass/yr, no products
    r = run_scenario(scn)
    assert r.inventory.annual_biomass_kg / 1000 == pytest.approx(250.0, rel=1e-3)
