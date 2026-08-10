"""Tests for the study-evidence layer: schema, cohorts, endpoints, normalization.

Each test corresponds to an acceptance criterion of the Priority-1 revision.
"""

from __future__ import annotations

import pytest

from algametrix.paper import endpoints, indices, reconstructions, studies
from algametrix.paper.harmonization import (
    common_profile,
    run_analysis_a,
    run_analysis_b,
)
from algametrix.paper.schema import (
    StudyRecord,
    VocabularyError,
    tier_disagreements,
    tier_rule,
)
from algametrix.paper.studies import Cohort, CohortMismatch


@pytest.fixture(scope="module")
def dataset():
    return studies.default_dataset()


# ----------------------------------------------------------------------
# Schema and vocabularies
# ----------------------------------------------------------------------

def test_dataset_loads_and_ids_are_unique(dataset):
    assert len(dataset) > 0
    assert len(set(dataset.ids)) == len(dataset)


def test_closed_vocabulary_rejects_a_typo():
    with pytest.raises(VocabularyError):
        StudyRecord(study_id="x", full_citation="y", economic_endpoint_type="produciton_cost")


def test_unknown_is_none_not_a_default():
    r = StudyRecord(study_id="x", full_citation="y")
    assert r.economic_endpoint_type is None
    assert r.includes_depreciation is None
    assert r.plant_maturity is None


def test_source_value_defaults_to_the_reported_pair():
    r = StudyRecord(study_id="x", full_citation="y", reported_value=3.0, reported_unit="EUR/kg")
    assert r.source_value == 3.0
    assert r.source_unit == "EUR/kg"


def test_completeness_score_is_a_fraction(dataset):
    for r in dataset:
        assert 0.0 <= r.completeness() <= 1.0


def test_tier_rule_requires_inventory_economics_and_a_builder():
    base = dict(study_id="x", full_citation="y", published_inventory_available=True,
                published_capex_available=True, reconstruction_builder="scp_protein")
    assert tier_rule(StudyRecord(**base)) == "B"
    assert tier_rule(StudyRecord(**{**base, "reconstruction_builder": None})) == "A"
    assert tier_rule(StudyRecord(**{**base, "published_inventory_available": None})) == "A"
    assert tier_rule(StudyRecord(**{**base, "published_capex_available": None})) == "A"


def test_declared_tier_disagreements_are_exactly_the_missing_scenarios(dataset):
    disagreeing = {sid for sid, _, _ in tier_disagreements(dataset.records)}
    assert disagreeing == set(reconstructions.MISSING_SCENARIOS)


def test_every_study_in_a_main_result_has_provenance(dataset):
    """A number that cannot be attached to an identified source is not evidence."""
    cohort = endpoints.primary_cost_cohort(dataset.records)
    assert len(cohort) > 0
    for rec in cohort:
        assert not rec.missing_provenance(), (
            f"{rec.study_id} enters the primary cost spread without "
            f"{rec.missing_provenance()}"
        )


def test_traceability_gaps_are_visible_not_silent(dataset):
    """Weaker traceability does not block a record, but must be reported."""
    with_gaps = [r.study_id for r in dataset if r.missing_traceability()]
    assert with_gaps, "expected the curated dataset to have traceability gaps"
    for sid in with_gaps:
        assert dataset.by_id(sid).missing_traceability()


def test_every_registered_builder_runs(dataset):
    for name in reconstructions.available():
        scn = reconstructions.build(name)
        assert scn.scale > 0


def test_records_claiming_reproduced_have_a_registered_builder(dataset):
    for r in dataset:
        if r.reconstruction_status == "reproduced":
            assert reconstructions.has_builder(r.reconstruction_builder), r.study_id


# ----------------------------------------------------------------------
# TASK 2 - economic endpoints
# ----------------------------------------------------------------------

def test_msp_is_never_classified_as_production_cost(dataset):
    for r in dataset:
        if r.economic_endpoint_type in ("minimum_selling_price",
                                        "minimum_biomass_selling_price",
                                        "minimum_product_selling_price"):
            audit = endpoints.classify(r)
            assert not audit.eligible
            assert "endpoint is" in (audit.exclusion_reason or "")


def test_mbsp_study_is_excluded_from_the_primary_spread(dataset):
    """nrel_davis2016 reports an MBSP and defined the legacy spread minimum."""
    cohort = endpoints.primary_cost_cohort(dataset.records)
    assert "nrel_davis2016" not in cohort.ids


def test_mixed_endpoints_cannot_enter_one_spread(dataset):
    good = list(endpoints.primary_cost_cohort(dataset.records))
    endpoints.assert_single_endpoint(good)          # must not raise
    with pytest.raises(endpoints.MixedEndpointError):
        endpoints.assert_single_endpoint(good + [dataset.by_id("nrel_davis2016")])


def test_mixed_functional_units_cannot_enter_one_spread(dataset):
    good = list(endpoints.primary_cost_cohort(dataset.records))
    with pytest.raises(endpoints.MixedEndpointError):
        endpoints.assert_single_functional_unit(good + [dataset.by_id("phycocyanin")])


def test_every_eligible_study_has_a_known_endpoint_and_functional_unit(dataset):
    for a in endpoints.audit_all(dataset.records):
        if a.eligible:
            assert a.classification == endpoints.PRIMARY_ENDPOINT
            assert a.functional_unit == endpoints.PRIMARY_FUNCTIONAL_UNIT


def test_every_exclusion_carries_a_machine_readable_reason(dataset):
    for a in endpoints.audit_all(dataset.records):
        if not a.eligible:
            assert a.exclusion_reason


# ----------------------------------------------------------------------
# TASK 3 - normalization audit trail
# ----------------------------------------------------------------------

def test_normalization_is_auditable(dataset):
    reg = indices.default_registry()
    rec = dataset.by_id("norsker2011_pond")
    n = indices.normalize(rec, 2022, reg)
    assert n.ok
    assert n.currency_step is not None
    assert n.index_steps, "no index transformation recorded"
    step = n.index_steps[0]
    assert step.base_year == 2011 and step.target_year == 2022
    assert step.value_base > 0 and step.value_target > 0
    assert abs(n.value - rec.source_value * step.factor) < 1e-9


def test_missing_price_year_yields_not_normalizable(dataset):
    n = indices.normalize(dataset.by_id("phycocyanin"), 2022)
    assert not n.ok
    assert n.quality == "not_normalizable"
    assert n.todos


def test_engine_share_weighted_is_flagged_and_bounded(dataset):
    """No published breakdown: per-class indices, engine shares, reported as an interval."""
    shares = indices.component_share_bounds(reconstructions.available())
    n = indices.normalize(dataset.by_id("norsker2011_pond"), 2022, shares=shares)
    assert n.quality == "engine_share_weighted"
    assert n.lower is not None and n.upper is not None
    assert n.lower <= n.value <= n.upper
    assert n.legacy_whole_cost_value is not None      # the old method, for comparison
    assert n.todos                                     # still wants the source's own split


def test_without_a_share_set_it_falls_back_to_first_order(dataset):
    n = indices.normalize(dataset.by_id("norsker2011_pond"), 2022)
    assert n.quality == "whole_cost_first_order"
    assert n.value == pytest.approx(n.legacy_whole_cost_value)


def test_each_class_uses_its_own_index(dataset):
    """The failure this guards: one plant-cost index applied to labour and energy."""
    shares = indices.component_share_bounds(reconstructions.available())
    n = indices.normalize(dataset.by_id("tredici2016"), 2022, shares=shares)
    used = {step.normalization_class: step.index_name for step in n.index_steps}
    assert used["capital"] == "CEPCI"
    assert used["labour"] == "labour_cost_index"
    assert used["energy"] == "energy_price_series"
    assert used["general_opex"] == "general_opex_index"
    # The four factors must genuinely differ, otherwise the split changes nothing.
    factors = {s.normalization_class: s.factor for s in n.index_steps}
    assert len({round(f, 3) for f in factors.values()}) == len(factors)


def test_energy_escalated_far_more_than_plant_cost_2016_to_2022():
    """The quantitative reason the old method was wrong."""
    reg = indices.default_registry()
    cepci = reg.by_class("capital").factor(2016, 2022).factor
    energy = reg.by_class("energy").factor(2016, 2022).factor
    assert energy > 1.4 * cepci


def test_exceeding_an_index_documented_span_is_flagged():
    reg = indices.default_registry()
    cepci = reg.by_class("capital")
    assert cepci.max_recommended_span_years == 5
    assert cepci.factor(2011, 2022).exceeds_recommended_span
    assert not cepci.factor(2020, 2022).exceeds_recommended_span


def test_exchange_rate_is_year_specific():
    reg = indices.default_registry()
    c2011 = reg.conversion("USD", "EUR", year=2011)
    c2022 = reg.conversion("USD", "EUR", year=2022)
    assert c2011.year_specific and c2022.year_specific
    assert c2011.rate != c2022.rate
    assert c2011.retrieval_date and c2022.source


def test_component_resolved_path_uses_one_index_per_component(dataset):
    """A record with a breakdown must not have CEPCI applied to every component."""
    rec = dataset.by_id("norsker2011_pond")
    rec = StudyRecord(**{**rec.to_dict(),
                         "cost_breakdown": {"capital_annualised": 0.5, "labour": 0.5}})
    n = indices.normalize(rec, 2022)
    # No labour index is available in this repository, so the honest outcome is a
    # downgrade to partial_component, never a silent CEPCI on labour.
    assert n.quality in ("component_resolved", "partial_component")
    assert n.component_shares == {"capital_annualised": 0.5, "labour": 0.5}
    assert n.todos if n.quality == "partial_component" else True


def test_component_shares_come_from_the_engine_and_sum_to_one():
    shares = indices.component_share_bounds(reconstructions.available())
    assert shares.available
    for name, vec in shares.per_builder.items():
        assert abs(sum(vec.values()) - 1.0) < 1e-6, name
        assert set(vec) <= {"capital", "energy", "labour", "general_opex"}
    assert abs(sum(shares.median.values()) - 1.0) < 1e-9


def test_every_index_is_available_and_carries_provenance():
    reg = indices.default_registry()
    for name in ("CEPCI", "labour_cost_index", "general_opex_index", "energy_price_series"):
        idx = reg.indices[name]
        assert idx.available, f"{name} has no values"
        assert idx.source, f"{name} has no source"
    # The three fetched series must carry a retrieval date; CEPCI must not pretend to.
    for name in ("labour_cost_index", "general_opex_index", "energy_price_series"):
        idx = reg.indices[name]
        assert idx.provenance == "fetched_from_provider_api"
        assert idx.retrieval_date
    cepci = reg.indices["CEPCI"]
    assert cepci.provenance == "back_calculated_from_legacy_results"
    assert cepci.retrieval_date is None
    assert cepci.todos


# ----------------------------------------------------------------------
# TASK 1 - constant cohorts
# ----------------------------------------------------------------------

def test_cohort_mismatch_is_detected(dataset):
    a = Cohort([dataset.by_id("norsker2011_pond"), dataset.by_id("ruiz2016")])
    b = Cohort([dataset.by_id("norsker2011_pond")])
    a.require_same_as(Cohort(list(a)), "s1", "s2")
    with pytest.raises(CohortMismatch):
        a.require_same_as(b, "s1", "s2")


def test_analysis_a_uses_one_cohort_at_both_stages(dataset):
    a = run_analysis_a(dataset)
    assert set(a.stage_common_currency.ids) == set(a.cohort.ids)
    assert set(a.stage_price_normalized.ids) == set(a.cohort.ids)
    assert a.stage_common_currency.n == a.stage_price_normalized.n == len(a.cohort)


def test_analysis_b_uses_one_cohort_at_all_three_stages(dataset):
    b = run_analysis_b(dataset)
    ids = set(b.cohort.ids)
    for sp in (b.stage_source_value, b.stage_source_accounting, b.stage_common_accounting):
        assert set(sp.ids) == ids
        assert sp.n == len(b.cohort)


def test_analysis_b_names_every_blocked_tier_b_study(dataset):
    b = run_analysis_b(dataset)
    eligible = set(endpoints.primary_cost_cohort(dataset.records).ids)
    for sid in eligible:
        rec = dataset.by_id(sid)
        if rec.reconstructability_tier == "B" and not rec.is_executable:
            assert sid in b.blocked


def test_common_accounting_profile_is_actually_applied(dataset):
    """Applying the profile must overwrite a scenario's own conventions."""
    from dataclasses import replace

    prof = common_profile()
    scn = reconstructions.build("spirulina_padi")
    assert scn.economics.depreciation_years != prof.depreciation_years
    harmonized = prof.apply(scn)
    assert harmonized.economics.depreciation_years == prof.depreciation_years
    assert harmonized.economics.maintenance_frac == prof.maintenance_frac
    # and it must not touch prices
    assert harmonized.economics.nitrogen_price == scn.economics.nitrogen_price
    del replace


# --------------------------------------------------------------------------
# Group-wise Sobol' decomposition (replaces the pinned conditional-variance
# ratios as the decomposition the paper reports)
# --------------------------------------------------------------------------

def test_group_sobol_recovers_a_known_partition():
    """Two groups, one with an interaction INSIDE it, and no interaction between.

    Y = x1*x2 + 3*x3, groups {x1,x2} and {x3}. Var(x1x2) = 7/144, Var(3x3) = 3/4,
    the groups are independent, so S[G1] and S[G2] are the exact variance shares
    and the between-group interaction is zero. A per-parameter analysis would
    NOT give this: it would split the x1*x2 term across two parameters and leave
    an interaction residual behind.
    """
    from algametrix.paper.sobol import Parameter, analyze_groups

    def model(X):
        return X[:, 0] * X[:, 1] + 3.0 * X[:, 2]

    ps = [Parameter("x1", 0, 1, group="G1"),
          Parameter("x2", 0, 1, group="G1"),
          Parameter("x3", 0, 1, group="G2")]
    r = analyze_groups(ps, model, 4096, 20260801, "Y", bootstrap=100)

    v1, v2 = 7 / 144, 0.75
    total = v1 + v2
    got = r.by_group()
    assert got["G1"][0].value == pytest.approx(v1 / total, abs=0.02)
    assert got["G2"][0].value == pytest.approx(v2 / total, abs=0.02)
    assert r.interactions == pytest.approx(0.0, abs=0.02)
    assert not r.violations()
    # A group's total index is at least its first-order index. For a model that
    # is additive in the groups the two are EQUAL, and S and ST come from two
    # different estimators (Saltelli and Jansen), so they agree only up to
    # Monte-Carlo error - the tolerance is sampling noise, not slack.
    for g, (s, st) in got.items():
        assert st.value >= s.value - 0.01, g


def test_group_estimator_benchmarks_recover_the_exact_remainder():
    """The published group-estimator validation, asserted at its own tolerance.

    ``test_group_sobol_recovers_a_known_partition`` above covers the estimator.
    This one covers the *reportable* benchmarks: they are what
    ``results/sobol_validation.txt`` prints, so a change that broke their exact
    values would ship a wrong validation table rather than fail a test.
    """
    from algametrix.paper import sobol

    for factory in sobol.GROUP_BENCHMARKS:
        o = sobol.run_group_benchmark(factory(), 2048, 20260801, bootstrap=100)
        assert o.max_abs_error <= 0.02, o.benchmark
        assert not o.result.violations(), o.benchmark
        # The remainder has no per-parameter analogue and is the quantity the
        # figure reports, so it is asserted separately rather than folded into
        # max_abs_error alone.
        assert o.interactions_abs_error <= 0.02, o.benchmark

    inside, between = (f() for f in sobol.GROUP_BENCHMARKS)
    assert inside.interactions_exact == pytest.approx(0.0, abs=1e-12)
    assert between.interactions_exact == pytest.approx(1 / 19, abs=1e-12)


def test_group_sobol_first_order_indices_do_not_exceed_one():
    """The property that makes it a decomposition, asserted on the real engine."""
    from algametrix.library import load_library
    from algametrix.paper import archetypes, parameters
    from algametrix.paper.evaluate import make_model, sobol_parameters
    from algametrix.paper.sobol import analyze_groups

    lib = load_library()
    scn = archetypes.build("open_raceway_pond", lib)
    params = parameters.mode_parameters(parameters.MODE_B_FULL_DECISION, scn)
    r = analyze_groups(sobol_parameters(scn, params),
                       make_model(scn, params, "GWP net (kg CO2-eq/kg)"),
                       512, 20260801, "GWP net (kg CO2-eq/kg)", bootstrap=50,
                       group_order=list(parameters.GROUPS))
    assert r.first_order_sum <= 1.05
    assert sum(e.value for e in r.st) >= 0.95
    # Prices cannot move a GWP: the economic group must contribute nothing.
    assert r.by_group()["economic"][1].value == pytest.approx(0.0, abs=1e-9)


def test_excluded_records_leave_every_population_but_stay_countable():
    """An exclusion must be visible, not silent, and must not block a builder."""
    from algametrix.paper import reproduction, studies

    ds = studies.default_dataset()
    excluded = reproduction.excluded_rows(ds)
    assert {"astaxanthin", "phycocyanin"} <= set(excluded)
    for sid, reason in excluded.items():
        assert reason and reason != "no reason recorded", sid
        rec = ds.by_id(sid)
        assert not rec.is_included
        assert not rec.is_executable          # no comparison may be produced
    # ... but they are not reported as missing scenario definitions, because the
    # builders are present and still run.
    assert not (set(excluded) & set(reproduction.blocked_rows(ds)))


def test_a_gwp_comparison_is_refused_when_the_convention_is_unknown_and_material():
    """The convention gate, exercised on a synthetic record.

    Mirrors the currency rule: a percentage between two different carbon
    conventions is not a deviation, so the row is refused rather than printed.
    """
    from copy import deepcopy
    from algametrix.library import load_library
    from algametrix.paper import reproduction, studies

    ds = studies.default_dataset()
    rec = deepcopy(ds.by_id("gwp_iceland_spirulina"))
    rec.biogenic_carbon_convention = None
    rec.reported_gwp_gross = None            # nothing convention-free to fall back on
    row = reproduction.gwp_row(rec, load_library())
    assert row.comparison_kind == "not_comparable"
    assert row.model is None
    assert any("NOT COMPARABLE" in n for n in row.notes)


def test_an_immaterial_adjustment_does_not_block_the_comparison():
    """A heterotrophic case with no biogenic adjustment stays comparable."""
    from algametrix.library import load_library
    from algametrix.paper import reproduction, studies

    row = reproduction.gwp_row(
        studies.default_dataset().by_id("mckuin_schizo"), load_library())
    assert row.comparison_kind == "point"
    assert any("immaterial" in n for n in row.notes)
