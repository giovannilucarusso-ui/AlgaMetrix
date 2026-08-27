"""Inputs the engine cannot use, and the substrate it was assuming.

Two guarantees are tested here, and they are the same guarantee twice: a number
that comes out of the engine describes the numbers that went in.

* **The substrate is declared, not assumed.** The carbon fraction of the organic
  feed is a scenario field. It was a module constant — glucose's — applied to
  glycerol, ethanol and food side-streams alike, and it drives the respired
  carbon and the "biomass C <= substrate C" admissibility check.
* **The balance refuses what it cannot compute.** Recovery, carbon utilization,
  nutrient uptake and substrate yield are all divided by, so all four are
  bounded before use. ``run_scenario`` now rejects a scenario that would need
  one of those bounds, and where a caller asks for the computation anyway the
  bound that bit is recorded on the inventory.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.inputcheck import (
    ERROR,
    WARNING,
    InadmissibleScenarioError,
    check_inputs,
    errors,
)
from algametrix.inventory import SUBSTRATE_CARBON_FRACTION, build_inventory
from algametrix.library import load_library
from algametrix.scenario import run_scenario
from algametrix.templates import build_template, template_names
from algametrix.verification import verify

GLYCEROL = 3 * 12.011 / 92.094      # 0.391 kg C/kg
HETEROTROPHIC = "Omega-3 oil (heterotrophic fermentation)"
PHOTOTROPHIC = "Whole biomass — food (Chlorella, raceway)"


@pytest.fixture(scope="module")
def lib():
    return load_library()


def _with_substrate(scenario, name: str, fraction: float):
    scenario.system = dataclasses.replace(
        scenario.system, substrate_name=name, substrate_carbon_fraction=fraction)
    return scenario


# --------------------------------------------------------------------------- #
# The substrate is declared
# --------------------------------------------------------------------------- #
def test_the_default_substrate_is_glucose(lib):
    """Unchanged behaviour for every case that really does feed glucose."""
    fermenter = lib.systems["Stirred-tank fermenter (heterotrophic)"]
    assert fermenter.substrate_name == "glucose"
    assert fermenter.substrate_carbon_fraction == pytest.approx(
        SUBSTRATE_CARBON_FRACTION, rel=1e-4)


def test_the_declared_fraction_drives_the_carbon_bookkeeping(lib):
    base = build_template(HETEROTROPHIC, lib)
    glucose = build_inventory(base)
    glycerol = build_inventory(
        _with_substrate(build_template(HETEROTROPHIC, lib), "glycerol", GLYCEROL))

    ratio = GLYCEROL / base.system.substrate_carbon_fraction
    assert glycerol.substrate_co2_supplied_per_kg == pytest.approx(
        glucose.substrate_co2_supplied_per_kg * ratio, rel=1e-9)
    # The respired term is the difference, so it moves by the whole gap.
    assert glycerol.biogenic_co2_respired_per_kg < glucose.biogenic_co2_respired_per_kg
    # The substrate mass, its price and its production burden are per kilogram
    # and do not move: this is a carbon-accounting field, and only that.
    assert glycerol.substrate_per_kg == pytest.approx(glucose.substrate_per_kg)


def test_a_low_carbon_substrate_can_fail_the_check_glucose_would_pass(lib):
    """The reason the constant mattered: it decides a falsifiable check.

    A stream carrying a quarter of glucose's carbon cannot supply the carbon in
    the biomass it is credited with making. Under the old constant the check
    read that scenario as admissible.
    """
    scenario = _with_substrate(build_template(HETEROTROPHIC, lib), "dilute permeate", 0.10)
    carbon = [i for i in verify(scenario).admissibility if "substrate C" in i.name]
    assert carbon and not carbon[0].passed

    glucose = build_template(HETEROTROPHIC, lib)
    carbon = [i for i in verify(glucose).admissibility if "substrate C" in i.name]
    assert carbon and carbon[0].passed


def test_naming_a_substrate_without_its_carbon_is_flagged(lib):
    scenario = build_template(HETEROTROPHIC, lib)
    scenario.system = dataclasses.replace(scenario.system, substrate_name="glycerol")
    issue = next(i for i in check_inputs(scenario)
                 if i.field == "system.substrate_carbon_fraction")
    assert issue.severity == WARNING
    assert "glucose" in issue.message
    # It is a warning, not a refusal: the scenario still computes.
    assert run_scenario(scenario).inventory.substrate_per_kg > 0


def test_a_carbon_fraction_outside_zero_to_one_is_refused(lib):
    scenario = _with_substrate(build_template(HETEROTROPHIC, lib), "impossible", 1.4)
    assert any(i.field == "system.substrate_carbon_fraction" and i.severity == ERROR
               for i in check_inputs(scenario))
    with pytest.raises(InadmissibleScenarioError):
        run_scenario(scenario)


def test_a_phototroph_ignores_the_substrate_fields(lib):
    """No carbon fraction can change a scenario that feeds no substrate."""
    base = run_scenario(build_template(PHOTOTROPHIC, lib))
    other = run_scenario(_with_substrate(build_template(PHOTOTROPHIC, lib), "glycerol", GLYCEROL))
    assert other.lca.gwp_kg_co2eq_per_kg == pytest.approx(base.lca.gwp_kg_co2eq_per_kg)
    assert other.inventory.substrate_co2_supplied_per_kg == 0.0


# --------------------------------------------------------------------------- #
# The balance refuses what it cannot compute
# --------------------------------------------------------------------------- #
#: Field, the value that forces a bound, and how to set it.
_BAD_INPUTS = (
    ("harvesting.recovery",
     lambda s: dataclasses.replace(s.harvesting, recovery=1.4), "harvesting"),
    ("harvesting.recovery",
     lambda s: dataclasses.replace(s.harvesting, recovery=0.0), "harvesting"),
    ("harvesting.final_solids",
     lambda s: dataclasses.replace(s.harvesting, final_solids=0.0), "harvesting"),
    ("system.nutrient_uptake",
     lambda s: dataclasses.replace(s.system, nutrient_uptake=1.5), "system"),
    ("system.co2_utilization",
     lambda s: dataclasses.replace(s.system, co2_utilization=1.5), "system"),
)


@pytest.mark.parametrize("field,mutate,attr", _BAD_INPUTS,
                         ids=[f"{f}={i}" for i, (f, _, _) in enumerate(_BAD_INPUTS)])
def test_run_scenario_refuses_an_input_it_would_have_bounded(lib, field, mutate, attr):
    scenario = build_template(PHOTOTROPHIC, lib)
    setattr(scenario, attr, mutate(scenario))
    with pytest.raises(InadmissibleScenarioError) as raised:
        run_scenario(scenario)
    assert any(i.field == field for i in raised.value.issues)
    # The same scenario computed without the guard records what it did instead.
    inv = run_scenario(scenario, validate=False).inventory
    assert any(c.field == field for c in inv.clamps)


def test_every_shipped_template_needs_no_bound(lib):
    for name in template_names():
        inv = run_scenario(build_template(name, lib)).inventory
        assert inv.clamps == (), f"{name}: {[str(c) for c in inv.clamps]}"


def test_the_clamp_says_what_was_given_and_what_was_used(lib):
    scenario = build_template(PHOTOTROPHIC, lib)
    scenario.harvesting = dataclasses.replace(scenario.harvesting, recovery=1.4)
    clamp = run_scenario(scenario, validate=False).inventory.clamps[0]
    assert (clamp.field, clamp.given, clamp.used) == ("harvesting.recovery", 1.4, 1.0)
    assert "divides by recovery" in clamp.why


def test_the_carbon_floor_warns_rather_than_refuses(lib):
    """The one bound that bites on an admissible scenario, declared as such."""
    scenario = build_template(PHOTOTROPHIC, lib)
    scenario.system = dataclasses.replace(scenario.system, co2_utilization=0.02)
    assert not errors(scenario)
    issue = next(i for i in check_inputs(scenario) if i.field == "system.co2_utilization")
    assert issue.severity == WARNING
    inv = run_scenario(scenario).inventory     # runs: it is admissible
    assert [c.field for c in inv.clamps] == ["system.co2_utilization"]


def test_a_solvent_recovery_outside_zero_to_one_is_refused(lib):
    scenario = build_template("Algal-oil biorefinery (phototrophic)", lib)
    scenario.extraction = dataclasses.replace(scenario.extraction, solvent_recovery=1.2)
    with pytest.raises(InadmissibleScenarioError):
        run_scenario(scenario)


def test_the_exported_result_carries_the_bounds_that_bit(lib):
    from algametrix.serialization import results_to_dict

    scenario = build_template(PHOTOTROPHIC, lib)
    scenario.harvesting = dataclasses.replace(scenario.harvesting, recovery=1.4)
    exported = results_to_dict(run_scenario(scenario, validate=False))
    clamps = exported["inventory_per_kg_biomass"]["clamps"]
    assert clamps and clamps[0]["given"] == 1.4 and clamps[0]["used"] == 1.0
    # And the substrate the carbon bookkeeping used travels with it.
    assert exported["scenario"]["system"]["substrate_carbon_fraction"] > 0
