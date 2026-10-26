"""The scenario list behind SI Table S-B.

The verification and consistency checks run over 27 scenarios, and the
manuscript describes them through this table. These tests hold that the table
lists exactly those scenarios, in the order the checks use, and that its rows
and its counts agree with each other.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix.library import load_library  # noqa: E402
from algametrix.paper import report_verification, suite, supplementary  # noqa: E402


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def distinct(lib):
    return suite.distinct_cases(lib)


@pytest.fixture(scope="module")
def rows(lib):
    return suite.describe(lib)


@pytest.fixture(scope="module")
def counts(lib, distinct):
    return suite.coverage(lib, distinct[0])


def test_one_row_per_distinct_scenario_in_suite_order(rows, distinct):
    cases, duplicates = distinct
    assert [r.key for r in rows] == [c.key for c in cases]
    assert [r.number for r in rows] == list(range(1, len(cases) + 1))
    assert {r.key: list(r.also) for r in rows if r.also} == duplicates


def test_every_row_says_where_it_comes_from(rows):
    assert all(r.source for r in rows)
    assert all(r.source != "no study record" for r in rows if r.key != "rec_scp_protein")


def test_the_counts_add_up(counts):
    assert counts["drying fuel: natural gas"] + counts["drying fuel: electricity"] \
        == counts["with drying"]
    assert counts["carbon source: CO2"] + counts["carbon source: NaHCO3"] \
        == counts["phototrophic"]
    conventions = sum(v for k, v in counts.items() if k.startswith("biogenic carbon:"))
    assert conventions == counts["total"]


def test_the_rows_agree_with_the_counts(rows, counts):
    assert len(rows) == counts["total"]
    assert sum(r.operation == "batch" for r in rows) == counts["batch"]
    assert sum(r.basis == "volume" for r in rows) == counts["volume basis"]
    assert sum(r.drying == "none" for r in rows) == counts["without drying"]
    assert sum(r.drying.endswith(", electric") for r in rows) \
        == counts["drying fuel: electricity"]
    assert sum(r.downstream != "none" for r in rows) == counts["with extraction"]
    assert sum(r.products > 1 for r in rows) == counts["multi-product allocation"]
    assert sum(r.carbon == "NaHCO3" for r in rows) == counts["carbon source: NaHCO3"]
    assert sum("cultivation heat" in r.options for r in rows) == counts["heated cultivation"]


def test_the_table_names_every_scenario_and_fits_the_page(rows, counts):
    text = report_verification.scenario_suite(rows, counts)
    for r in rows:
        assert r.key in text
    assert supplementary._widest_table_row(text) <= supplementary.PRINT_WIDTH
