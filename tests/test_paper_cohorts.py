"""Tests for what the cohorts are allowed to claim about themselves.

Two reviewer findings are guarded here:

* a cohort screened on endpoint *label* is not a homogeneous production-cost
  cohort, and nothing in the code may describe it as one;
* the matched reconstructable cohort's size is not the same thing as the amount
  of independent evidence behind it.
"""

from __future__ import annotations

import pytest

from algametrix.paper import endpoints, reconstructions, studies
from algametrix.paper.harmonization import independence_audit, run_analysis_b


@pytest.fixture(scope="module")
def dataset():
    return studies.default_dataset()


# ----------------------------------------------------------------------
# Nominal, not homogeneous
# ----------------------------------------------------------------------

def test_cohort_label_does_not_claim_homogeneity():
    assert "homogeneous" not in endpoints.PRIMARY_COHORT_LABEL.lower()
    assert "nominally" in endpoints.PRIMARY_COHORT_LABEL


def test_definition_audit_reports_every_cohort_member(dataset):
    defn = endpoints.definition_audit(dataset.records)
    cohort = endpoints.primary_cost_cohort(dataset.records)
    assert defn.n == len(cohort)
    assert set(defn.unknown_by_study) == set(cohort.ids)


def test_homogeneity_is_only_claimed_when_every_attribute_is_known(dataset):
    defn = endpoints.definition_audit(dataset.records)
    text = " ".join(defn.statement())
    if defn.verified:
        assert "homogeneous in the endpoint definition" in text
    else:
        assert "DECLARED endpoint and functional unit only" in text
        assert endpoints.PRIMARY_COHORT_LABEL in text


def test_a_study_with_a_full_endpoint_definition_scores_as_such(dataset):
    """The studies added with their financial conventions must show up as known."""
    defn = endpoints.definition_audit(dataset.records)
    assert defn.unknown_by_study["vazquez2022b_nas"] == []


# ----------------------------------------------------------------------
# Eligibility is honoured
# ----------------------------------------------------------------------

def test_an_excluded_record_never_enters_the_primary_cohort(dataset):
    excluded = [r.study_id for r in dataset if r.eligibility_status == "excluded"]
    assert excluded, "the dataset should still carry at least one excluded record"
    cohort_ids = set(endpoints.primary_cost_cohort(dataset.records).ids)
    assert not cohort_ids & set(excluded)


def test_the_uncited_benchmark_is_out_of_every_study_population(dataset):
    rec = dataset.by_id("scp_protein")
    assert rec.eligibility_status == "excluded"
    assert not rec.is_executable, "an uncited envelope must not be a validation row"
    assert rec.exclusion_reason and "no primary source" in rec.exclusion_reason
    # The builder survives: it is still the open-raceway archetype.
    assert reconstructions.has_builder("scp_protein")


# ----------------------------------------------------------------------
# Independence
# ----------------------------------------------------------------------

def test_matched_cohort_is_larger_than_the_four_it_started_from(dataset):
    b = run_analysis_b(dataset)
    assert b.n >= 5


def test_independence_audit_counts_publications_not_records(dataset):
    b = run_analysis_b(dataset)
    ind = independence_audit(b.cohort)
    assert ind.n == b.n
    assert ind.n_publications <= ind.n
    assert ind.n_external + len(ind.self_cited) == ind.n


def test_self_citations_are_named_not_merely_disclosed_in_prose(dataset):
    b = run_analysis_b(dataset)
    ind = independence_audit(b.cohort)
    for sid in ind.self_cited:
        assert dataset.by_id(sid).author_overlap_with_algametrix is True
    text = " ".join(ind.statement())
    for sid in ind.self_cited:
        assert sid in text


def test_records_sharing_a_publication_are_flagged_as_not_independent(dataset):
    b = run_analysis_b(dataset)
    ind = independence_audit(b.cohort)
    shared = [ids for ids in ind.publications.values() if len(ids) > 1]
    if shared:
        assert "not independent evidence" in " ".join(ind.statement())


def test_stoten_reconstructions_are_untuned_and_carry_a_cost_breakdown(dataset):
    for sid in ("vazquez2022b_nas", "vazquez2022b_tiso_pht", "vazquez2022b_nas_10ha"):
        rec = dataset.by_id(sid)
        assert rec.evidence_class == "retrospective_untuned"
        assert rec.is_executable
        assert rec.has_cost_breakdown
        assert abs(sum(rec.cost_breakdown.values()) - 1.0) < 5e-3, sid
        assert rec.author_overlap_with_algametrix is False


def test_the_three_stoten_scenarios_are_one_independent_source(dataset):
    """Three scenarios of one publication are three comparisons and one source."""
    groups = {dataset.by_id(sid).independence_group
              for sid in ("vazquez2022b_nas", "vazquez2022b_tiso_pht",
                          "vazquez2022b_nas_10ha")}
    assert groups == {"vazquez_stoten_2022"}
