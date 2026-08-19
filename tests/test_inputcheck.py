"""Inputs that describe nothing must be refused, not computed.

The engine returns a number for almost anything: zero productivity gives a cost
of ``inf``, and a substrate yield of zero is floored internally to 1e-6 and
returns a million kilograms of glucose per kilogram of biomass. Both are
arithmetic on a mistake, and neither looks like one on screen.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix.inputcheck import (  # noqa: E402
    ERROR,
    WARNING,
    check_inputs,
    errors,
    format_issues,
    is_admissible,
)
from algametrix.library import load_library  # noqa: E402
from algametrix.models import Product, TrophicMode  # noqa: E402
from algametrix.templates import TEMPLATES, build_template  # noqa: E402


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture
def biomass(lib):
    return build_template("Whole biomass — food (Chlorella, raceway)", lib)


@pytest.fixture
def fermenter(lib):
    return build_template("Heterotrophic microalgae powder", lib)


def fields(issues) -> set[str]:
    return {i.field for i in issues}


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
def test_every_shipped_template_is_admissible(template, lib):
    """The rules must not block a case the tool itself offers."""
    assert check_inputs(template.build(lib)) == []


def test_zero_productivity_is_rejected(biomass):
    biomass.system.productivity = 0.0
    assert not is_admissible(biomass)
    assert "system.productivity" in fields(errors(biomass))


def test_zero_substrate_yield_is_rejected(fermenter):
    """1e-6 is a floor that hides the mistake, not a value the user meant."""
    fermenter.system.substrate_yield = 0.0
    assert "system.substrate_yield" in fields(errors(fermenter))


def test_substrate_yield_above_one_is_rejected(fermenter):
    fermenter.system.substrate_yield = 1.4
    assert "system.substrate_yield" in fields(errors(fermenter))


def test_impossible_composition_is_rejected(biomass):
    biomass.organism.protein = 1.0
    biomass.organism.lipid = 1.0
    biomass.organism.carbohydrate = 1.0
    biomass.organism.ash = 1.0        # the 400% the wizard used to accept
    issues = errors(biomass)
    assert "organism.composition" in fields(issues)
    assert "400%" in format_issues(issues)


def test_composition_slightly_off_is_a_warning_not_a_block(biomass):
    biomass.organism.protein += 0.08
    issues = check_inputs(biomass)
    assert is_admissible(biomass)
    assert any(i.field == "organism.composition" and i.severity == WARNING for i in issues)


def test_elemental_fractions_cannot_exceed_the_biomass(biomass):
    biomass.organism.carbon = 0.95
    biomass.organism.nitrogen = 0.2
    assert "organism.carbon" in fields(errors(biomass))


def test_carbon_utilization_floor_is_reported_not_hidden(biomass):
    biomass.system.co2_utilization = 0.01
    issues = check_inputs(biomass)
    assert is_admissible(biomass)          # the floor is applied, so it still runs
    warning = next(i for i in issues if i.field == "system.co2_utilization")
    assert warning.severity == WARNING
    assert "floor" in warning.message


def test_zero_carbon_utilization_is_rejected(biomass):
    biomass.system.co2_utilization = 0.0
    assert "system.co2_utilization" in fields(errors(biomass))


def test_recovery_outside_a_fraction_is_rejected(biomass):
    biomass.harvesting.recovery = 1.4
    assert "harvesting.recovery" in fields(errors(biomass))


def test_batch_mode_without_a_schedule_is_rejected(fermenter):
    fermenter.batch_mode = True
    fermenter.batch_cycle_time_h = 0.0
    fermenter.batch_size_kg = 0.0
    assert fields(errors(fermenter)) >= {"batch_cycle_time_h", "batch_size_kg"}


def test_a_batch_scenario_needs_no_productivity(fermenter):
    """Output is batch × batches; productivity is not read, so it is not required."""
    fermenter.batch_mode = True
    fermenter.batch_cycle_time_h = 48.0
    fermenter.batch_size_kg = 5000.0
    fermenter.system.productivity = 0.0
    assert is_admissible(fermenter)


def test_more_product_than_biomass_is_rejected(lib):
    scn = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    scn.products = [Product("Everything", "custom", yield_override=0.8, price=5.0, is_main=True),
                    Product("And more", "custom", yield_override=0.5, price=1.0)]
    assert "products" in fields(errors(scn))


def test_two_main_products_are_rejected(lib):
    scn = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    for p in scn.products[:2]:
        p.is_main = True
    assert "products" in fields(errors(scn))


def test_no_main_product_is_only_a_warning(lib):
    scn = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    for p in scn.products:
        p.is_main = False
    assert is_admissible(scn)
    assert any(i.severity == WARNING and i.field == "products" for i in check_inputs(scn))


def test_a_dosed_stream_that_carries_nothing_is_flagged(lib):
    scn = build_template("Biomass on municipal wastewater (raceway)", lib)
    scn.waste_feed.dosed_on = "substrate"       # a pond has no substrate demand
    issue = next(i for i in check_inputs(scn) if i.field == "waste_feed.dosed_on")
    assert issue.severity == WARNING


def test_errors_sort_before_warnings(biomass):
    biomass.system.productivity = 0.0
    biomass.organism.protein += 0.08
    issues = check_inputs(biomass)
    assert issues[0].severity == ERROR


def test_the_message_names_the_field_and_the_fix(fermenter):
    fermenter.system.substrate_yield = 0.0
    text = format_issues(errors(fermenter))
    assert "system.substrate_yield" in text
    assert "kg biomass per kg substrate" in text


def test_a_deep_copy_is_not_needed_to_check(biomass):
    """Checking must not touch the scenario it is handed."""
    before = copy.deepcopy(biomass)
    check_inputs(biomass)
    assert biomass.system.productivity == before.system.productivity
    assert biomass.organism.protein == before.organism.protein
