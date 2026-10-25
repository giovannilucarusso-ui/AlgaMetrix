"""Tests for the nitrogen and phosphorus that recipe materials carry.

A material such as yeast extract or urea can declare how much N and P it
contains. The share the culture can use meets the demand before any fertiliser
is bought, and whatever it carries beyond that is discharged. The demand itself
never moves, the same rule as for a waste feed.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.consistency import check_scenario
from algametrix.inputcheck import errors
from algametrix.inventory import build_inventory
from algametrix.lca import run_lca
from algametrix.library import load_library
from algametrix.models import Material, WasteFeed
from algametrix.serialization import scenario_from_dict, scenario_to_dict
from algametrix.tea import run_tea
from algametrix.templates import build_template
from algametrix.verification import verify

TOL = 1e-12
MEP = "Marine eutrophication (kg N-eq)"


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def photo(lib):
    """A raceway with no nutrient-bearing material: it buys all its N and P."""
    return build_template("Single-cell protein (Chlorella, raceway)", lib)


@pytest.fixture(scope="module")
def hetero(lib):
    """The fermenter, whose yeast extract declares its nitrogen."""
    return build_template("Heterotrophic microalgae powder", lib)


def _urea(amount: float, share: float = 1.0) -> Material:
    return Material(name="Urea", amount_per_kg=amount, price=0.45, gwp=1.2, ced=20.0,
                    nitrogen_fraction=0.466, assimilable_fraction=share)


def _phosphate(amount: float) -> Material:
    return Material(name="Monopotassium phosphate", amount_per_kg=amount, price=1.2,
                    gwp=1.6, ced=18.0, phosphorus_fraction=0.2276)


def _with(scn, *materials):
    return replace(scn, materials=list(scn.materials) + list(materials))


def _without_recipe_nutrients(scn):
    return replace(scn, materials=[replace(m, nitrogen_fraction=0.0,
                                           phosphorus_fraction=0.0)
                                   for m in scn.materials])


# =====================================================================
# The default changes nothing
# =====================================================================

def test_a_material_declares_no_nutrients_unless_told_to():
    m = Material(name="Sea salts", amount_per_kg=1.0, price=0.24)
    assert m.nitrogen_fraction == 0.0
    assert m.phosphorus_fraction == 0.0
    assert m.assimilable_fraction == 1.0


def test_without_declared_nutrients_everything_is_bought(photo):
    inv = build_inventory(photo)
    assert inv.nitrogen_purchased_per_kg == inv.nitrogen_per_kg
    assert inv.phosphorus_purchased_per_kg == inv.phosphorus_per_kg
    assert inv.nitrogen_from_materials_per_kg == 0.0
    assert inv.nitrogen_materials_surplus_per_kg == 0.0


# =====================================================================
# What the recipe covers, and what it discharges
# =====================================================================

def test_the_demand_does_not_move(hetero):
    """The biomass needs the same nitrogen however it arrives."""
    with_recipe = build_inventory(hetero)
    without = build_inventory(_without_recipe_nutrients(hetero))
    assert with_recipe.nitrogen_per_kg == pytest.approx(without.nitrogen_per_kg)
    assert with_recipe.phosphorus_per_kg == pytest.approx(without.phosphorus_per_kg)


def test_the_yeast_extract_covers_the_fermenter_nitrogen(hetero):
    """0.61 kg/kg at 11 % N, 69 % of it usable, is more than the demand.

    So nothing is bought, and the extract's nitrogen beyond the demand leaves
    with the effluent along with the share the culture never takes up.
    """
    ye = next(m for m in hetero.materials if m.name == "Yeast extract")
    carried = ye.amount_per_kg * ye.nitrogen_fraction
    inv = build_inventory(hetero)
    assert carried * ye.assimilable_fraction > inv.nitrogen_per_kg
    assert inv.nitrogen_purchased_per_kg == pytest.approx(0.0, abs=TOL)
    assert inv.nitrogen_from_materials_per_kg == pytest.approx(inv.nitrogen_per_kg)
    assert inv.nitrogen_materials_surplus_per_kg == pytest.approx(
        carried - inv.nitrogen_per_kg)
    # No phosphorus is declared for the extract, so all of it is still bought.
    assert inv.phosphorus_purchased_per_kg == pytest.approx(inv.phosphorus_per_kg)


def test_a_recipe_poorer_than_the_demand_leaves_the_rest_to_buy(photo):
    demand = build_inventory(photo).nitrogen_per_kg
    amount = 0.25 * demand / 0.466
    inv = build_inventory(_with(photo, _urea(amount)))
    assert inv.nitrogen_from_materials_per_kg == pytest.approx(0.25 * demand)
    assert inv.nitrogen_purchased_per_kg == pytest.approx(0.75 * demand)
    assert inv.nitrogen_materials_surplus_per_kg == pytest.approx(0.0, abs=TOL)


def test_only_the_assimilable_share_displaces_the_purchase(photo):
    """The unassimilable half is discharged even though the demand is not met."""
    demand = build_inventory(photo).nitrogen_per_kg
    amount = 0.5 * demand / 0.466
    base = build_inventory(photo)
    inv = build_inventory(_with(photo, _urea(amount, share=0.5)))
    assert inv.nitrogen_from_materials_per_kg == pytest.approx(0.25 * demand)
    assert inv.nitrogen_purchased_per_kg == pytest.approx(0.75 * demand)
    assert inv.nitrogen_materials_surplus_per_kg == pytest.approx(0.25 * demand)
    assert inv.nitrogen_emitted_per_kg == pytest.approx(
        base.nitrogen_emitted_per_kg + 0.25 * demand)


def test_phosphorus_follows_the_same_rule(photo):
    demand = build_inventory(photo).phosphorus_per_kg
    inv = build_inventory(_with(photo, _phosphate(2.0 * demand / 0.2276)))
    assert inv.phosphorus_purchased_per_kg == pytest.approx(0.0, abs=TOL)
    assert inv.phosphorus_materials_surplus_per_kg == pytest.approx(demand)
    # Nitrogen is untouched by a phosphate salt.
    assert inv.nitrogen_purchased_per_kg == pytest.approx(inv.nitrogen_per_kg)


def test_a_waste_feed_is_counted_before_the_recipe(photo):
    """The recipe meets what the stream left open, never the same kilogram twice."""
    feed = WasteFeed(enabled=True, name="Test effluent", unit="m3",
                     nitrogen_per_unit=0.04, phosphorus_per_unit=0.0005,
                     dosed_on="nitrogen", coverage=0.4)
    demand = build_inventory(photo).nitrogen_per_kg
    scn = replace(_with(photo, _urea(demand / 0.466)), waste_feed=feed)
    inv = build_inventory(scn)
    assert inv.nitrogen_from_waste_per_kg == pytest.approx(0.4 * demand)
    assert inv.nitrogen_from_materials_per_kg == pytest.approx(0.6 * demand)
    assert inv.nitrogen_purchased_per_kg == pytest.approx(0.0, abs=TOL)
    assert inv.nitrogen_materials_surplus_per_kg == pytest.approx(0.4 * demand)


# =====================================================================
# Money and burden
# =====================================================================

def test_the_nitrogen_line_goes_and_the_material_line_stays(hetero):
    base = _without_recipe_nutrients(hetero)
    tea = run_tea(hetero, build_inventory(hetero))
    tea0 = run_tea(base, build_inventory(base))
    assert tea0.opex_breakdown["Nitrogen"] > 0
    assert tea.opex_breakdown.get("Nitrogen", 0.0) == pytest.approx(0.0, abs=TOL)
    assert tea.opex_breakdown["Yeast extract"] == pytest.approx(
        tea0.opex_breakdown["Yeast extract"])


def test_the_discharge_lands_on_marine_eutrophication(hetero):
    """Fertiliser production goes; the unused nitrogen goes to water instead."""
    base = _without_recipe_nutrients(hetero)
    inv, inv0 = build_inventory(hetero), build_inventory(base)
    lca, lca0 = run_lca(hetero, inv), run_lca(base, inv0)
    f = hetero.lcia
    assert lca.gwp_breakdown.get("Nitrogen", 0.0) == pytest.approx(0.0, abs=TOL)
    expected = ((inv.nitrogen_emitted_per_kg - inv0.nitrogen_emitted_per_kg)
                * f.n_to_water_frac
                - inv0.nitrogen_purchased_per_kg * f.nitrogen_eutroph_n)
    assert lca.impacts[MEP] - lca0.impacts[MEP] == pytest.approx(expected)
    assert lca.impacts[MEP] > lca0.impacts[MEP]


# =====================================================================
# The checks that hold the rest together
# =====================================================================

def _configurations(photo, hetero):
    demand = build_inventory(photo).nitrogen_per_kg
    feed = WasteFeed(enabled=True, name="Test effluent", unit="m3",
                     nitrogen_per_unit=0.04, phosphorus_per_unit=0.007,
                     dosed_on="nitrogen", coverage=0.4)
    return {
        "fermenter as shipped": hetero,
        "urea short of the demand": _with(photo, _urea(0.3 * demand / 0.466)),
        "urea past the demand": _with(photo, _urea(3.0 * demand / 0.466, share=0.7)),
        "phosphate salt": _with(photo, _phosphate(0.01)),
        "waste feed and urea": replace(_with(photo, _urea(demand / 0.466)),
                                       waste_feed=feed),
    }


CONFIGURATIONS = ["fermenter as shipped", "urea short of the demand",
                  "urea past the demand", "phosphate salt", "waste feed and urea"]


@pytest.mark.parametrize("name", CONFIGURATIONS)
def test_every_identity_still_closes(photo, hetero, name):
    scn = _configurations(photo, hetero)[name]
    report = verify(scn)
    assert report.all_pass, [c.name for c in report.balances if not c.closes]
    assert report.max_residual < 1e-9


@pytest.mark.parametrize("name", CONFIGURATIONS)
def test_the_independent_matrix_implementation_agrees(photo, hetero, name):
    from algametrix.paper import matrixlca

    scn = _configurations(photo, hetero)[name]
    report = matrixlca.benchmark(scn, name)
    bad = [(r.label, r.engine, r.matrix, r.rel_diff)
           for r in report.rows if r.rel_diff > matrixlca.BENCHMARK_TOL]
    assert not bad, bad


def test_identities_are_added_only_for_a_nutrient_the_recipe_declares(hetero):
    """No 0 == 0 checks: the extract declares nitrogen, so phosphorus gets none."""
    names = [c.name for c in verify(hetero).balances]
    assert "Identity: N demand == purchased + from recipe" in names
    assert "Identity: recipe N content == used + surplus" in names
    assert not any("recipe P" in n or n.startswith("Identity: P demand") for n in names)


def test_nitrogen_stops_being_a_shared_flow_when_nothing_is_bought(hetero):
    report = check_scenario(hetero, "fermenter")
    assert report.all_pass
    names = {f.flow for f in report.active_flows}
    assert "Nitrogen" not in names
    assert "Material: Yeast extract" in names


# =====================================================================
# Inputs
# =====================================================================

@pytest.mark.parametrize("field,value", [
    ("nitrogen_fraction", 1.2),
    ("phosphorus_fraction", -0.1),
    ("assimilable_fraction", 1.5),
])
def test_a_fraction_outside_zero_to_one_is_refused(photo, field, value):
    scn = _with(photo, replace(_urea(0.01), **{field: value}))
    i = len(scn.materials) - 1
    assert f"materials[{i}].{field}" in {e.field for e in errors(scn)}


def test_a_negative_amount_cannot_bring_nutrients(photo):
    scn = _with(photo, _urea(-0.01))
    i = len(scn.materials) - 1
    assert f"materials[{i}].amount_per_kg" in {e.field for e in errors(scn)}


def test_the_fractions_survive_a_save_and_load(hetero):
    restored = scenario_from_dict(scenario_to_dict(hetero))
    ye = next(m for m in restored.materials if m.name == "Yeast extract")
    assert ye.nitrogen_fraction == pytest.approx(0.11)
    assert ye.assimilable_fraction == pytest.approx(0.69)


def test_every_library_material_that_declares_nutrients_is_admissible(lib):
    declared = [(sys_name, m) for sys_name, s in lib.systems.items()
                for m in s.materials if m.nitrogen_fraction or m.phosphorus_fraction]
    assert declared, "the fermenter's yeast extract should declare its nitrogen"
    for sys_name, m in declared:
        for value in (m.nitrogen_fraction, m.phosphorus_fraction,
                      m.assimilable_fraction):
            assert 0.0 <= value <= 1.0, (sys_name, m.name)
        assert m.assimilable_fraction > 0, (sys_name, m.name)
