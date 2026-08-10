"""The shared-inventory claim, as tests.

The claim under test is:

    for every applicable scenario, the quantity of each physical flow that the
    techno-economic analysis prices is the same quantity that the life-cycle
    analysis characterizes.

Because ``run_scenario`` hands one ``Inventory`` to both analyses, this is an
architectural invariant rather than an empirical result, and these are
verification tests: they hold the interface between the two analyses in place
and would fail if a future edit made one of them read a different field, apply a
different scaling, or report on a different basis.
"""

from __future__ import annotations

import pytest

from algametrix.consistency import (
    CONSISTENCY_TOL,
    check_propagation,
    check_scenario,
    duplicated_inventory_drift,
)
from algametrix.library import load_library
from algametrix.models import CarbonSource, TrophicMode
from algametrix.paper import suite

LIB = load_library()
CASES, _DUPES = suite.distinct_cases(LIB)
CASE_IDS = [c.key for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_tea_and_lca_recover_the_same_flow_quantities(case):
    """Every flow, recovered independently from the cost and from the impact."""
    report = check_scenario(case.scenario(LIB), case.label)
    assert report.active_flows, f"{case.key} exercised no shared flow"
    bad = [(f.flow, f.tea_quantity, f.lca_quantity, f.discrepancy)
           for f in report.active_flows if not f.consistent]
    assert not bad, f"{case.key}: TEA and LCA disagree on {bad}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_recovered_quantities_match_the_inventory(case):
    """The recovered quantities are the inventory fields, not merely each other."""
    report = check_scenario(case.scenario(LIB), case.label)
    assert report.max_inventory_discrepancy <= CONSISTENCY_TOL


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_structural_checks_hold(case):
    """Functional unit, land area and multi-product allocation are shared too."""
    report = check_scenario(case.scenario(LIB), case.label)
    failed = [name for name, ok, _ in report.structural if not ok]
    assert not failed, f"{case.key}: {failed}"


def test_the_suite_covers_both_trophic_modes_and_both_carbon_sources():
    """A guard on the claim that the scenario set is heterogeneous."""
    cov = suite.coverage(LIB)
    assert cov["phototrophic"] >= 5 and cov["heterotrophic"] >= 3
    assert cov["carbon source: CO2"] >= 5 and cov["carbon source: NaHCO3"] >= 1
    assert cov["batch"] >= 1 and cov["continuous"] >= 5
    assert cov["with extraction"] >= 3 and cov["multi-product allocation"] >= 3
    assert cov["with drying"] >= 5 and cov["without drying"] >= 3


@pytest.mark.parametrize("key", ["rec_heterotrophic_powder", "rec_spirulina_padi",
                                 "rec_algal_oil", "arch_led_pbr"])
def test_one_edit_propagates_to_both_analyses(key):
    """Move a single physical assumption; both analyses must follow it together."""
    case = next(c for c in suite.all_cases() if c.key == key)
    scn = case.scenario(LIB)
    report, deltas = check_propagation(scn, case.label, recovery_delta=-0.10)

    # still consistent after the edit ...
    assert report.all_pass, f"{key}: {report.max_discrepancy:.2e}"
    # ... and the edit was not a no-op: at least one flow actually moved.
    moved = [f for f, (before, after) in deltas.items()
             if abs(after - before) > 1e-12 * max(abs(before), 1.0)]
    assert moved, f"{key}: the perturbation changed nothing, so the test is vacuous"


@pytest.mark.parametrize("key", ["rec_heterotrophic_powder", "rec_spirulina_padi"])
def test_duplicated_inventories_drift_apart_after_the_same_edit(key):
    """The counter-example must actually produce an inconsistency.

    A guard on the demonstration itself: if the emulated duplicate did *not*
    diverge, the contrast drawn in the manuscript would be empty.
    """
    case = next(c for c in suite.all_cases() if c.key == key)
    demo = duplicated_inventory_drift(case.scenario(LIB), case.label)

    assert demo.max_shared_discrepancy <= CONSISTENCY_TOL
    # The un-mirrored edit must open a gap that is large in ordinary terms,
    # i.e. percent-scale rather than round-off scale.
    assert demo.max_duplicated_discrepancy > 0.01
    assert demo.new_value != demo.old_value


def test_phototrophic_and_heterotrophic_use_different_carbon_flows():
    """A sanity check that the probes are not silently inactive everywhere."""
    photo = next(c for c in CASES if c.key == "rec_spirulina_padi")
    hetero = next(c for c in CASES if c.key == "rec_heterotrophic_powder")

    p = check_scenario(photo.scenario(LIB))
    h = check_scenario(hetero.scenario(LIB))
    p_flows = {f.flow for f in p.active_flows}
    h_flows = {f.flow for f in h.active_flows}

    assert photo.scenario(LIB).system.mode is TrophicMode.PHOTOTROPHIC
    assert photo.scenario(LIB).system.carbon_source is CarbonSource.BICARBONATE
    assert "Bicarbonate" in p_flows and "Substrate" not in p_flows
    assert "Substrate" in h_flows and "Bicarbonate" not in h_flows
