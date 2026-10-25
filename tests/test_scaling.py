"""Equipment and labour cost against plant capacity.

The power law is optional, and its defaults must give back the proportional
model of 1.5 exactly, because every published number rests on that model. The
rest of the file holds the law itself, the units in parallel above the largest
unit, the labour exponent, the input check, the scenario file and the printed
equations.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix import library  # noqa: E402
from algametrix.inputcheck import (  # noqa: E402
    ERROR,
    WARNING,
    InadmissibleScenarioError,
    check_inputs,
)
from algametrix.library import DEFAULT_DATA_DIR, load_library  # noqa: E402
from algametrix.models import CostScaling, LabourScaling  # noqa: E402
from algametrix.paper import reconstructions, suite  # noqa: E402
from algametrix.paper.specification import check_against_engine  # noqa: E402
from algametrix.scaling import (  # noqa: E402
    equipment_cost,
    equipment_groups,
    labour_cost,
    parallel_units,
)
from algametrix.scenario import run_scenario  # noqa: E402
from algametrix.serialization import scenario_from_dict, scenario_to_dict  # noqa: E402
from algametrix.templates import TEMPLATES, build_template  # noqa: E402

FERMENTER = "Heterotrophic microalgae powder"


@pytest.fixture(scope="module")
def lib():
    return load_library()


def _every_scenario(lib) -> dict:
    scenarios = {f"suite: {c.label}": c.scenario(lib) for c in suite.all_cases()}
    scenarios.update({f"template: {t.name}": t.build(lib) for t in TEMPLATES})
    scenarios.update({f"reconstruction: {name}": reconstructions.build(name, lib)
                      for name in sorted(reconstructions.BUILDER_PROVENANCE)})
    return scenarios


def _with_scaling(scn, annual_kg: float, exponent: float, labour_exponent: float,
                  units: int | None = None):
    """``scn`` with every group and labour declared, reference capacities off-centre."""
    out = copy.copy(scn)

    def declared(capacity: float) -> CostScaling:
        capacity = capacity if capacity > 0 else 1.0
        return CostScaling(exponent, reference_capacity=0.37 * capacity,
                           max_capacity=capacity / units if units else None)

    out.system = replace(scn.system, capex_scaling=declared(scn.scale))
    out.extraction = replace(scn.extraction, capex_scaling=declared(annual_kg))
    out.economics = replace(
        scn.economics,
        harvest_capex_scaling=declared(annual_kg),
        drying_capex_scaling=declared(annual_kg),
        labor_scaling=LabourScaling(labour_exponent,
                                    reference_capacity=2.0 * annual_kg if annual_kg > 0 else 1.0),
    )
    return out


def _fermenter_scaled(lib):
    """The SuperPro-calibrated fermenter template with every scaling option in use."""
    scn = build_template(FERMENTER, lib)
    scn.system = replace(scn.system, capex_scaling=CostScaling(
        0.6, reference_capacity=150.0, min_capacity=20.0, max_capacity=100.0))
    scn.economics = replace(
        scn.economics,
        harvest_capex_scaling=CostScaling(0.6, reference_capacity=283_500.0),
        drying_capex_scaling=CostScaling(0.6, reference_capacity=283_500.0),
        labor_scaling=LabourScaling(0.25, reference_capacity=283_500.0),
    )
    return scn


# --------------------------------------------------------------------------- #
# The defaults are the model of 1.5
# --------------------------------------------------------------------------- #
def test_the_defaults_give_the_proportional_model_of_1_5_exactly(lib):
    """Capital and labour exactly as 1.5 computed them, on every scenario the tool ships."""
    for name, scn in _every_scenario(lib).items():
        r = run_scenario(scn, validate=False)
        m = r.inventory.annual_biomass_kg
        eco = scn.economics
        equipment = (scn.scale * scn.system.capex_per_unit
                     + eco.harvest_capex_per_kgyr * m
                     + (eco.drying_capex_per_kgyr * m if scn.drying.enabled else 0.0)
                     + (scn.extraction.capex_per_kgyr * m if scn.extraction.enabled else 0.0))
        assert r.tea.equipment_cost == equipment, name
        assert r.tea.opex_breakdown.get("Labour", 0.0) == eco.labor_cost_per_year, name


def test_reference_capacities_and_units_change_nothing_at_the_default_exponents(lib):
    """Declaring where a cost came from must not move a number until n does."""
    for name, scn in _every_scenario(lib).items():
        before = run_scenario(scn, validate=False)
        declared = _with_scaling(scn, before.inventory.annual_biomass_kg,
                                 exponent=1.0, labour_exponent=0.0, units=3)
        after = run_scenario(declared, validate=False)
        for f in ("equipment_cost", "dfc", "total_investment", "annual_opex",
                  "production_cost_eur_per_kg", "npv"):
            assert getattr(after.tea, f) == getattr(before.tea, f), (name, f)
        assert after.tea.cash_flows == before.tea.cash_flows, name


def test_every_paper_scenario_uses_the_default_exponents(lib):
    """The specification says every reported result is proportional; hold it to that."""
    for case in suite.all_cases():
        scn = case.scenario(lib)
        assert all(g.scaling.exponent == 1.0 for g in equipment_groups(scn, 1.0)), case.label
        assert scn.economics.labor_scaling.exponent == 0.0, case.label


# --------------------------------------------------------------------------- #
# The law
# --------------------------------------------------------------------------- #
def test_one_unit_follows_the_power_law():
    sc = CostScaling(exponent=0.6, reference_capacity=100.0)
    assert equipment_cost(800.0, 100.0, sc) == (pytest.approx(80_000.0, rel=1e-12), 1)
    cost, units = equipment_cost(800.0, 400.0, sc)
    assert units == 1
    assert cost == pytest.approx(80_000.0 * 4.0 ** 0.6, rel=1e-12)


def test_above_the_largest_unit_the_group_is_built_as_identical_units():
    sc = CostScaling(exponent=0.6, reference_capacity=100.0, max_capacity=200.0)
    assert [parallel_units(s, sc) for s in (50.0, 200.0, 201.0, 1000.0)] == [1, 1, 2, 5]
    # Exactly k units, even where the division lands a hair above k.
    assert parallel_units(1.1, CostScaling(max_capacity=0.1)) == 11
    cost, units = equipment_cost(800.0, 500.0, sc)
    assert units == 3
    assert cost == pytest.approx(3 * 800.0 * 100.0 * (500.0 / 3 / 100.0) ** 0.6, rel=1e-12)


def test_past_the_largest_unit_cost_grows_with_the_number_of_units():
    sc = CostScaling(exponent=0.6, reference_capacity=100.0, max_capacity=200.0)
    one = equipment_cost(800.0, 200.0, sc)[0]
    for k in (2, 3, 7):
        assert equipment_cost(800.0, k * 200.0, sc)[0] == pytest.approx(k * one, rel=1e-12)
    # The step from N to N + 1 units costs ((N + 1)/N)^(1 - n).
    just_above = equipment_cost(800.0, 400.0 * (1 + 1e-9), sc)[0]
    assert just_above / (2 * one) == pytest.approx(1.5 ** 0.4, rel=1e-6)


def test_labour_scales_from_its_reference_capacity():
    sc = LabourScaling(exponent=0.25, reference_capacity=300_000.0)
    assert labour_cost(743_000.0, 300_000.0, sc) == pytest.approx(743_000.0, rel=1e-12)
    assert labour_cost(743_000.0, 4_800_000.0, sc) == pytest.approx(1_486_000.0, rel=1e-12)
    assert labour_cost(743_000.0, 9e9, LabourScaling()) == 743_000.0


def test_the_tea_reports_each_group_and_costs_it_with_the_law(lib):
    scn = _fermenter_scaled(lib)
    r = run_scenario(scn)
    assert set(r.tea.cost_scaling) == {"Cultivation equipment", "Harvesting equipment",
                                       "Drying equipment", "Labour"}
    cult = r.tea.cost_scaling["Cultivation equipment"]
    assert (cult.units, cult.capacity_unit) == (2, "m3")
    assert cult.unit_capacity == pytest.approx(75.0)
    assert cult.cost == pytest.approx(2 * 10_000.0 * 150.0 * 0.5 ** 0.6, rel=1e-12)
    assert r.tea.capex_breakdown["Cultivation equipment"] == pytest.approx(
        cult.cost * scn.economics.installation_factor, rel=1e-12)
    assert r.tea.opex_breakdown["Labour"] == r.tea.cost_scaling["Labour"].cost


def test_below_one_the_unit_cost_falls_faster_with_size_than_proportional(lib):
    proportional = build_template(FERMENTER, lib)
    scaled = _fermenter_scaled(lib)
    scaled.system = replace(scaled.system, capex_scaling=replace(
        scaled.system.capex_scaling, max_capacity=None, min_capacity=None))
    for scn in (proportional, scaled):
        scn.scale *= 5
    assert (run_scenario(scaled).tea.production_cost_eur_per_kg
            < run_scenario(proportional).tea.production_cost_eur_per_kg)


# --------------------------------------------------------------------------- #
# The input check
# --------------------------------------------------------------------------- #
def _issues(scn, prefix: str):
    return [i for i in check_inputs(scn) if i.field.startswith(prefix)]


def test_an_exponent_without_a_reference_capacity_is_refused(lib):
    scn = build_template(FERMENTER, lib)
    scn.system = replace(scn.system, capex_scaling=CostScaling(exponent=0.6))
    assert [i.severity for i in _issues(scn, "system.capex_scaling")] == [ERROR]
    with pytest.raises(InadmissibleScenarioError):
        run_scenario(scn)
    with pytest.raises(ValueError, match="reference capacity"):
        run_scenario(scn, validate=False)


def test_a_labour_exponent_without_a_reference_capacity_is_refused(lib):
    scn = build_template(FERMENTER, lib)
    scn.economics = replace(scn.economics, labor_scaling=LabourScaling(exponent=0.25))
    found = _issues(scn, "economics.labor_scaling")
    assert [(i.field, i.severity) for i in found] == [
        ("economics.labor_scaling.reference_capacity", ERROR)]


@pytest.mark.parametrize("bad", [
    CostScaling(exponent=0.0, reference_capacity=100.0),
    CostScaling(exponent=-0.5, reference_capacity=100.0),
    CostScaling(reference_capacity=-1.0),
    CostScaling(max_capacity=0.0),
    CostScaling(min_capacity=300.0, max_capacity=200.0),
], ids=["zero exponent", "negative exponent", "negative S_ref", "zero unit", "empty range"])
def test_a_declaration_that_describes_no_equipment_is_refused(lib, bad):
    scn = build_template(FERMENTER, lib)
    scn.system = replace(scn.system, capex_scaling=bad)
    assert any(i.is_error for i in _issues(scn, "system.capex_scaling"))


def test_a_unit_below_the_declared_range_is_flagged_but_computed(lib):
    scn = build_template(FERMENTER, lib)   # 150 m3
    scn.system = replace(scn.system, capex_scaling=CostScaling(
        0.6, reference_capacity=300.0, min_capacity=200.0, max_capacity=1000.0))
    found = _issues(scn, "system.capex_scaling")
    assert [(i.field, i.severity) for i in found] == [
        ("system.capex_scaling.min_capacity", WARNING)]
    assert "extrapolated" in found[0].message
    run_scenario(scn)


def test_the_range_applies_to_each_unit_in_parallel(lib):
    scn = build_template(FERMENTER, lib)   # 150 m3 -> 2 units of 75 m3
    scn.system = replace(scn.system, capex_scaling=CostScaling(
        0.6, reference_capacity=100.0, min_capacity=80.0, max_capacity=100.0))
    found = _issues(scn, "system.capex_scaling")
    assert [i.severity for i in found] == [WARNING]
    assert "75 m3 per unit" in found[0].message


def test_labour_above_its_range_is_flagged(lib):
    scn = build_template(FERMENTER, lib)   # 283.5 t/yr
    scn.economics = replace(scn.economics, labor_scaling=LabourScaling(
        0.25, reference_capacity=100_000.0, min_capacity=50_000.0, max_capacity=200_000.0))
    found = _issues(scn, "economics.labor_scaling")
    assert [(i.field, i.severity) for i in found] == [
        ("economics.labor_scaling.max_capacity", WARNING)]


def test_far_from_the_reference_with_no_range_is_flagged(lib):
    scn = build_template(FERMENTER, lib)   # 150 m3
    scn.system = replace(scn.system, capex_scaling=CostScaling(0.6, reference_capacity=10.0))
    found = _issues(scn, "system.capex_scaling")
    assert [i.severity for i in found] == [WARNING]
    assert "factor of ten" in found[0].message


def test_an_exponent_above_one_is_flagged(lib):
    scn = build_template(FERMENTER, lib)
    scn.system = replace(scn.system, capex_scaling=CostScaling(1.2, reference_capacity=150.0))
    assert [i.severity for i in _issues(scn, "system.capex_scaling")] == [WARNING]


# --------------------------------------------------------------------------- #
# Scenario files and the YAML library
# --------------------------------------------------------------------------- #
def test_a_declared_scaling_survives_a_scenario_file(lib):
    scn = _fermenter_scaled(lib)
    back = scenario_from_dict(scenario_to_dict(scn))
    assert back.system.capex_scaling == scn.system.capex_scaling
    assert type(back.economics.labor_scaling) is LabourScaling
    assert back.economics.labor_scaling == scn.economics.labor_scaling
    assert run_scenario(back).tea.annual_opex == run_scenario(scn).tea.annual_opex


def test_a_file_from_before_1_6_keeps_the_proportional_model(lib):
    data = scenario_to_dict(build_template(FERMENTER, lib))
    for key in ("harvest_capex_scaling", "drying_capex_scaling", "labor_scaling"):
        del data["economics"][key]
    del data["system"]["capex_scaling"]
    back = scenario_from_dict(data)
    assert back.system.capex_scaling == CostScaling()
    assert back.economics.labor_scaling == LabourScaling()


def test_a_partial_labour_block_keeps_labour_fixed(lib):
    data = scenario_to_dict(build_template(FERMENTER, lib))
    data["economics"]["labor_scaling"] = {"reference_capacity": 100_000.0}
    assert scenario_from_dict(data).economics.labor_scaling.exponent == 0.0


def test_the_library_reads_a_scaling_block_and_refuses_a_typo():
    assert library._scaling(None) == CostScaling()
    assert library._scaling({"exponent": 0.6, "reference_capacity": 100, "max_capacity": 400,
                             "source": "vendor quote"}) == CostScaling(
        0.6, reference_capacity=100.0, max_capacity=400.0, source="vendor quote")
    assert library._scaling({"reference_capacity": 5}, LabourScaling).exponent == 0.0
    with pytest.raises(ValueError, match="refrence_capacity"):
        library._scaling({"exponent": 0.6, "refrence_capacity": 100})

    block = library._load_yaml(DEFAULT_DATA_DIR / "parameters.yaml")["economics"]
    eco = library._economics({**block, "labor_scaling": {"exponent": 0.25,
                                                         "reference_capacity": 1e6}})
    assert eco.labor_scaling == LabourScaling(0.25, reference_capacity=1e6)
    assert eco.harvest_capex_scaling == CostScaling()


# --------------------------------------------------------------------------- #
# The printed equations
# --------------------------------------------------------------------------- #
def test_the_printed_equations_hold_with_scaling_declared(lib):
    """The suite runs at the defaults, so the scaled branch is checked here."""
    omega3 = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    omega3.extraction = replace(omega3.extraction, capex_scaling=CostScaling(
        0.7, reference_capacity=1e6, max_capacity=2e6))
    omega3.economics = replace(omega3.economics, labor_scaling=LabourScaling(
        0.2, reference_capacity=5e6))
    for label, scn in (("fermenter", _fermenter_scaled(lib)), ("omega-3", omega3)):
        checks = check_against_engine(scn, label)
        assert {c.equation for c in checks} >= {"tea.equipment", "tea.dfc", "tea.aoc"}
        assert all(c.agrees for c in checks), [
            (c.equation, c.stated, c.engine) for c in checks if not c.agrees]
