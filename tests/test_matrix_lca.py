"""The independent matrix LCA implementation, as a benchmark on the engine.

Two codings of one model specification, on identical foreground data, functional
unit, boundaries and characterization factors. Agreement verifies the
arithmetic; it says nothing about whether the model is right.
"""

from __future__ import annotations

import numpy as np
import pytest

from algametrix.inventory import build_inventory
from algametrix.lca import run_lca
from algametrix.library import load_library
from algametrix.paper import matrixlca, suite

LIB = load_library()
CASES, _ = suite.distinct_cases(LIB)
CASE_IDS = [c.key for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_matrix_implementation_reproduces_the_engine(case):
    report = matrixlca.benchmark(case.scenario(LIB), case.label)
    bad = [(r.label, r.engine, r.matrix, r.rel_diff)
           for r in report.rows if r.rel_diff > matrixlca.BENCHMARK_TOL]
    assert not bad, f"{case.key}: {bad}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_technosphere_is_well_conditioned(case):
    """A benchmark is only evidence if its own linear solve is trustworthy."""
    system = matrixlca.build_system(case.scenario(LIB))
    assert np.isfinite(system.condition_number)
    assert system.condition_number < 1e10


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_annual_production_is_recomputed_consistently(case):
    """The matrix side derives the reference flow itself, not from the inventory."""
    scn = case.scenario(LIB)
    independent = matrixlca.annual_production_kg(scn)
    engine = build_inventory(scn).annual_biomass_kg
    assert independent == pytest.approx(engine, rel=1e-12)


def test_the_harvesting_recovery_is_an_off_diagonal_transfer_coefficient():
    """The matrix system must encode the loss structurally, not as a pre-multiplier."""
    case = next(c for c in CASES if c.key == "rec_scp_protein")
    scn = case.scenario(LIB)
    system = matrixlca.build_system(scn)
    recovery = scn.harvesting.recovery
    # harvesting -> gate is the only place the recovery may appear
    assert system.A[1, 2] == pytest.approx(-1.0 / recovery, rel=1e-12)


def test_changing_a_factor_moves_both_implementations_identically():
    """A perturbation test, so the agreement cannot be an accident of one point."""
    case = next(c for c in CASES if c.key == "rec_scp_protein")
    scn = case.scenario(LIB)
    for factor in (0.1, 0.5, 2.0, 10.0):
        scn.lcia.elec_gwp = 0.35 * factor
        engine = run_lca(scn, build_inventory(scn))
        matrix = matrixlca.run_matrix_lca(scn)
        assert matrix.gwp_net == pytest.approx(engine.gwp_kg_co2eq_per_kg, rel=1e-12)
        assert matrix.gwp_gross == pytest.approx(
            engine.gwp_gross_kg_co2eq_per_kg, rel=1e-12)


@pytest.mark.skipif(not matrixlca.brightway_available(),
                    reason="bw2calc is not installed; the matrix benchmark is the "
                           "primary independent implementation")
@pytest.mark.parametrize("key", ["rec_scp_protein", "rec_heterotrophic_powder",
                                 "rec_algal_oil"])
def test_brightway_solves_the_same_system(key):
    """Optional third-party cross-check on the linear solve itself."""
    case = next(c for c in CASES if c.key == key)
    scn = case.scenario(LIB)
    bw = matrixlca.compare_with_brightway(scn)
    assert bw is not None
    ours = matrixlca.run_matrix_lca(scn).impacts
    for cat, value in bw.items():
        assert value == pytest.approx(ours[cat], rel=1e-9, abs=1e-12), cat
