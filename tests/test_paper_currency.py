"""Tests for the price-basis layer.

The defect these guard against: the validation table divided an engine output
denominated in one currency by a source value denominated in another, and
printed the quotient as a percentage deviation. Every test here fails if that
becomes possible again.
"""

from __future__ import annotations

import pytest

from algametrix.paper import indices, reconstructions, reproduction, studies
from algametrix.paper.basis import LIBRARY_PRICE_BASIS, PriceBasis, basis_of_source
from algametrix.paper.harmonization import run_analysis_b


@pytest.fixture(scope="module")
def dataset():
    return studies.default_dataset()


@pytest.fixture(scope="module")
def registry():
    return indices.default_registry()


@pytest.fixture(scope="module")
def rows(dataset):
    return reproduction.build_rows(dataset)


# ----------------------------------------------------------------------
# The basis object itself
# ----------------------------------------------------------------------

def test_price_basis_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        PriceBasis("EUR", 2022, "made_up_kind", "nowhere")


def test_two_bases_with_an_unknown_year_are_not_the_same_basis():
    a = PriceBasis("EUR", None, "source_price_set", "x")
    b = PriceBasis("EUR", None, "source_price_set", "y")
    assert not a.same_as(b)
    assert a.same_as(PriceBasis("EUR", None, "source_price_set", "y")) is False


def test_every_registered_builder_declares_a_basis():
    for name in reconstructions.available():
        basis = reconstructions.price_basis(name)
        assert basis.currency in ("EUR", "USD")
        assert basis.provenance


# ----------------------------------------------------------------------
# Transfers
# ----------------------------------------------------------------------

def test_transfer_between_currencies_uses_the_rate_of_the_denomination_year(registry):
    src = PriceBasis("USD", 2015, "source_price_set", "x")
    dst = PriceBasis("EUR", 2015, "source_price_set", "y")
    t = indices.transfer(100.0, src, dst, registry)
    assert t.ok
    assert t.quality == "currency_only"
    # ECB annual average for 2015, not the 2022 rate and not a flat rate.
    assert t.currency_step.year == 2015
    assert t.amount_out == pytest.approx(100.0 * 0.90130, rel=1e-9)


def test_transfer_refuses_a_currency_change_when_the_price_year_is_unknown(registry):
    src = PriceBasis("EUR", 2022, "library_default_price_set", "x")
    dst = basis_of_source("USD", None)
    t = indices.transfer(100.0, src, dst, registry)
    assert not t.ok
    assert t.quality == "blocked"
    assert "unknown" in (t.blocked_reason or "")


def test_transfer_refuses_an_unknown_currency(registry):
    t = indices.transfer(1.0, LIBRARY_PRICE_BASIS, basis_of_source(None, 2020), registry)
    assert not t.ok


def test_same_currency_unknown_year_is_flagged_not_silently_aligned(registry):
    t = indices.transfer(10.0, LIBRARY_PRICE_BASIS, basis_of_source("EUR", None), registry)
    assert t.ok
    assert t.quality == "currency_aligned_year_unknown"
    assert t.amount_out == 10.0


def test_reverse_rate_is_the_reciprocal_of_the_published_one(registry):
    fwd = registry.conversion("USD", "EUR", year=2021)
    rev = registry.conversion("EUR", "USD", year=2021)
    assert rev.rate == pytest.approx(1.0 / fwd.rate, rel=1e-12)
    assert "inverted" in rev.provenance


# ----------------------------------------------------------------------
# The validation table
# ----------------------------------------------------------------------

def test_no_cost_row_reports_a_deviation_across_two_currencies(rows):
    """The reviewer's finding: a EUR/USD quotient is not a deviation."""
    for r in rows:
        if r.metric != "cost" or r.comparison_kind not in ("point", "range"):
            continue
        assert r.engine_basis is not None and r.source_basis is not None
        assert r.transfer is not None and r.transfer.ok, r.study_id
        # After the transfer both sides are in the source's own currency.
        assert r.transfer.to_basis.currency == r.source_basis.currency, r.study_id


def test_a_row_that_cannot_be_brought_to_one_basis_carries_no_percentage(rows):
    blocked = [r for r in rows if r.comparison_kind == "not_comparable"]
    for r in blocked:
        assert r.ratio is None
        assert "%" not in r.verdict


def test_mixed_price_sets_report_an_interval(rows):
    mixed = [r for r in rows if r.metric == "cost" and r.engine_basis is not None
             and r.engine_basis.is_mixed and r.model_alt is not None]
    assert mixed, "the SuperPro/Russo reconstructions are mixed price sets"
    for r in mixed:
        lo, hi = r.ratio_bounds
        assert lo <= r.ratio <= hi
        assert "to" in r.verdict


def test_source_price_set_reconstructions_need_no_conversion(rows):
    """tredici2016 and vazquez2022 are fed the paper's own EUR prices."""
    by_id = {r.study_id: r for r in rows if r.metric == "cost"}
    for sid in ("tredici2016", "vazquez2022"):
        assert by_id[sid].transfer.is_identity, sid


# ----------------------------------------------------------------------
# Analysis B
# ----------------------------------------------------------------------

def test_analysis_b_pools_only_values_in_the_common_basis(dataset):
    b = run_analysis_b(dataset)
    assert b.n > 0
    for sid in b.cohort.ids:
        tr = b.engine_transfers[sid]
        assert tr.ok
        assert tr.to_basis.currency == "EUR"
        assert tr.to_basis.price_year == b.target_price_year


def test_analysis_b_engine_values_differ_from_their_native_units(dataset):
    """At least one member is denominated in something other than EUR 2022.

    If this ever stops being true the conversion is untested, not unnecessary.
    """
    b = run_analysis_b(dataset)
    converted = [sid for sid, tr in b.engine_transfers.items() if not tr.is_identity]
    assert converted
    for sid in converted:
        per = b.per_study[sid]
        assert per["engine_source_accounting"] != per["engine_source_accounting_native"]
