"""The headline totals of the manuscript, asserted rather than transcribed.

Every number in this file also appears in the abstract, in a results table or in
a figure caption. They are asserted here so that a change to the scenario suite,
to the evidence dataset or to the verification routines fails a test instead of
silently leaving the manuscript describing a different repository.

The numbers are not the point; the *agreement* between the paper and the code
is. When one of these fails, the fix is to update the manuscript to what the
code now produces - never to relax the assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from algametrix import consistency as consistency_mod
from algametrix.library import load_library
from algametrix.paper import matrixlca, reproduction, suite
from algametrix.paper.studies import default_dataset
from algametrix.verification import verify

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def cases(lib):
    kept, _duplicates = suite.distinct_cases(lib)
    return kept


# ----------------------------------------------------------------------
# The scenario suite: "27 structurally distinct scenarios"
# ----------------------------------------------------------------------

def test_the_suite_is_27_scenarios_23_phototrophic_and_4_heterotrophic(lib, cases):
    counts = suite.coverage(lib, cases)
    assert counts["total"] == 27
    assert counts["phototrophic"] == 23
    assert counts["heterotrophic"] == 4
    assert counts["phototrophic"] + counts["heterotrophic"] == counts["total"]


# ----------------------------------------------------------------------
# Internal verification: "163 construction identities, 147 admissibility"
# ----------------------------------------------------------------------

def test_verification_is_163_identities_and_147_admissibility_constraints(lib, cases):
    reports = [verify(c.scenario(lib)) for c in cases]
    assert sum(len(r.balances) for r in reports) == 163
    assert sum(len(r.invariants) for r in reports) == 147
    assert all(r.all_pass for r in reports)


# ----------------------------------------------------------------------
# Shared foreground: "167 flow comparisons, within 1.2e-13"
# ----------------------------------------------------------------------

def test_shared_flow_recovery_is_167_comparisons_within_1_2e_13(lib, cases):
    reports = [consistency_mod.check_scenario(c.scenario(lib), c.label) for c in cases]
    assert sum(len(r.active_flows) for r in reports) == 167
    assert all(r.all_pass for r in reports)
    worst = max(r.max_discrepancy for r in reports)
    # The manuscript reports 1.2e-13. The bound is the value that still rounds
    # to it, so a residual that grew by an order of magnitude fails here rather
    # than quietly contradicting the abstract.
    assert worst <= 1.25e-13, f"maximum TEA-LCA gap {worst:.3e} no longer rounds to 1.2e-13"


# ----------------------------------------------------------------------
# Independent implementation: "243 = 27 x 9, within 2.5e-15"
# ----------------------------------------------------------------------

def test_matrix_lca_benchmark_is_243_comparisons_within_2_5e_15(lib, cases):
    reports = [matrixlca.benchmark(c.scenario(lib), c.label) for c in cases]
    n = sum(len(r.rows) for r in reports)
    assert n == 243
    assert n == 27 * (len(matrixlca.IMPACT_CATEGORIES) + 2)   # + gross GWP, + biogenic
    assert all(r.passed(matrixlca.BENCHMARK_TOL) for r in reports)
    worst = max(r.max_rel_diff for r in reports)
    assert worst <= 2.55e-15, f"maximum matrix-LCA difference {worst:.3e}"


# ----------------------------------------------------------------------
# Third-party solver: "189 comparisons, 180 non-zero, within 4.9e-15"
# ----------------------------------------------------------------------

def test_the_recorded_brightway_crosscheck_is_189_comparisons_180_non_zero():
    """Checks the committed artifact, which is what the manuscript cites.

    bw2calc is deliberately not a dependency of the engine, so this cross-check
    runs from ``scripts/brightway_crosscheck.py`` in its own environment. What
    can be verified everywhere is that the result the paper quotes is the result
    in the repository.
    """
    path = ROOT / "results" / "brightway_crosscheck.json"
    if not path.exists():                                    # pragma: no cover
        pytest.skip("no recorded Brightway cross-check in this checkout")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "non_zero_comparisons" not in data:                   # pragma: no cover
        pytest.skip("recorded cross-check predates the comparison counts")
    assert data["scenarios"] == 27
    assert data["indicator_comparisons"] == 189 == 27 * 7
    assert len(data["all_relative_differences"]) == 189
    # An indicator both solvers return as zero agrees trivially; the manuscript
    # quotes the non-zero count beside the total for that reason.
    assert data["non_zero_comparisons"] == 180
    assert data["passed"] is True
    assert data["max_relative_difference"] <= 4.95e-15


# ----------------------------------------------------------------------
# Literature evidence: "12 point comparisons, 7 + 1 + 4"
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def rows(lib):
    return reproduction.build_rows(default_dataset(), lib)


def test_twelve_point_comparisons_split_seven_one_four(rows):
    s = reproduction.evidence_summary(rows)
    assert s.n_point == 12
    assert s.by_class == {
        "retrospective_untuned": 7,
        "component_informed": 1,
        "calibrated": 4,
    }
    assert sum(s.by_class.values()) == s.n_point


def test_untuned_production_cost_is_four_scenarios_from_two_publications(rows):
    c = reproduction.cohort(rows, "retrospective_untuned", "cost")
    assert c.n == 4
    assert c.n_publications == 2
    assert c.range_label == "-14% to +1.5%"


def test_tredici_is_compared_against_the_harmonized_endpoint(rows):
    """The published 12.40 carries financing interest; the engine's endpoint does not.

    (446367 - 10236) / 36000 = 12.114750 EUR2016/kg is what the engine is compared
    against, and the raw published figure travels with the row.
    """
    row = next(r for r in rows if r.study_id == "tredici2016" and r.metric == "cost")
    assert row.raw_reference == pytest.approx(12.40)
    assert row.reference == pytest.approx((446367 - 10236) / 36000, rel=1e-12)
    assert row.deviation_pct == pytest.approx(1.4849, abs=5e-4)
    assert row.verdict == "+1.5%"


def test_untuned_gwp_is_three_scenarios_from_minus_11_to_plus_4(rows):
    c = reproduction.cohort(rows, "retrospective_untuned", "gwp")
    assert c.n == 3
    assert c.range_label == "-11% to +4%"


def test_the_component_informed_case_is_reported_on_its_own(rows):
    c = reproduction.cohort(rows, "component_informed")
    assert c.n == 1
    assert c.rows[0].study_id == "vazquez2022"
    assert c.range_label == "-4% to -4%"


def test_the_four_calibrated_benchmarks_are_not_counted_as_untuned(rows):
    c = reproduction.cohort(rows, "calibrated")
    assert c.n == 4
    assert set(r.study_id for r in c.rows) == {
        "russo2022_aury", "superpro_algaloil", "superpro_omega3",
        "frontiers2026_spirulina",
    }
    untuned = reproduction.cohort(rows, "retrospective_untuned")
    assert not set(r.study_id for r in untuned.rows) & set(r.study_id for r in c.rows)


def test_no_record_is_classified_blind_any_more():
    """The word named a protocol this work does not have; the class is gone."""
    for rec in default_dataset():
        assert rec.evidence_class != "blind"
        assert not hasattr(rec, "validation_mode")
