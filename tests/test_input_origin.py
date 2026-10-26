"""Where the inputs of the study reconstructions come from (SI S4.6).

S4.6 classes every input a compared result depends on as taken from the source,
a library default, fitted or assumed, and lists the cost coefficients of each
reconstruction with the plant they refer to. These tests hold that it covers
exactly the comparisons of the validation table, that every location recorded
for a builder points at an input its scenario has, and that the counts and the
plant sizes the report quotes agree with the scenarios.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix.library import load_library  # noqa: E402
from algametrix.paper import (  # noqa: E402
    inputorigin,
    reconstructions,
    report,
    reproduction,
    studies,
    supplementary,
)
from algametrix.paper.reproduction import _cost_of  # noqa: E402
from algametrix.scenario import run_scenario  # noqa: E402

COST_RESULTS = ("production cost", "break-even price")


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def dataset():
    return studies.default_dataset()


@pytest.fixture(scope="module")
def compared(lib, dataset):
    return inputorigin.comparisons(lib, dataset)


@pytest.fixture(scope="module")
def coefficients(lib, dataset):
    return inputorigin.cost_coefficients(lib, dataset)


def test_the_comparisons_are_those_of_the_validation_table(lib, dataset, compared):
    rows = reproduction.build_rows(dataset, lib)
    table = {(r.study_id, r.metric, r.evidence_class) for r in rows
             if r.comparison_kind in ("point", "range")}
    ours = {(c.study_id, "cost" if c.result in COST_RESULTS else "gwp", c.evidence_class)
            for c in compared}
    assert ours == table
    assert len(compared) == len(table)


def test_every_compared_builder_and_no_other_has_its_origins_recorded(dataset):
    builders = {r.reconstruction_builder for r in dataset if r.is_executable}
    assert set(inputorigin.ORIGINS) == builders


def test_every_recorded_location_points_at_an_input(lib):
    for builder, origin in inputorigin.ORIGINS.items():
        scn = reconstructions.build(builder, lib)
        paths = [p for p, _ in inputorigin.inputs(scn)]
        for key in origin.entries:
            if "*" in key:
                assert any(inputorigin._pattern(key).match(p) for p in paths), (builder, key)
            else:
                assert key in paths, (builder, key)
        for component, entry in origin.base.items():
            inputorigin._library_object(lib, component, entry)
        assert origin.calibrated <= set(origin.base), builder


def test_every_input_is_classed_and_the_counts_add_up(compared):
    for c in compared:
        assert c.inputs, c.study
        assert all(i.origin in inputorigin.CLASSES and i.note for i in c.inputs), c.study
        assert sum(c.count(k) for k in inputorigin.CLASSES) == len(c.inputs)
        sizes = [abs(i.elasticity) for i in c.inputs]
        assert sizes == sorted(sizes, reverse=True)
        assert all(s > inputorigin.ACTIVE for s in sizes)


def test_a_listed_value_wins_over_the_library_and_the_library_over_a_pattern(lib):
    origin = inputorigin.ORIGINS["algal_oil"]
    scn = reconstructions.build("algal_oil", lib)

    def cls(path):
        return inputorigin.classify(origin, path, scn, lib)[0]

    assert cls("economics.labor_cost_per_year") == "source"   # listed, and under economics.*
    assert scn.economics.installation_factor == lib.economics.installation_factor
    assert cls("economics.installation_factor") == "library"
    assert scn.economics.overhead_frac != lib.economics.overhead_frac
    assert cls("economics.overhead_frac") == "fitted"         # economics.*


def test_a_library_value_calibrated_on_the_same_source_counts_as_fitted(lib):
    origin = inputorigin.ORIGINS["heterotrophic_powder"]
    scn = reconstructions.build("heterotrophic_powder", lib)
    cls, note = inputorigin.classify(origin, "system.productivity", scn, lib)
    assert cls == "fitted"
    assert "calibrated on Russo et al. (2022)" in note
    assert inputorigin.classify(origin, "harvesting.recovery", scn, lib)[0] == "library"


def test_an_input_with_no_recorded_origin_is_an_error(lib):
    scn = reconstructions.build("tredici2016", lib)
    with pytest.raises(KeyError):
        inputorigin.classify(inputorigin.Origin(source="nobody"), "system.productivity",
                             scn, lib)


def test_a_recovery_of_one_is_stepped_down_not_up(lib):
    scn = reconstructions.build("tredici2016", lib)
    assert scn.harvesting.recovery == 1.0
    priced = []

    def result(s):
        y = _cost_of(s)
        priced.append(s.harvesting.recovery)
        return y

    e = {p: x for p, _, x in inputorigin.elasticities(scn, result)}
    assert max(priced) == 1.0
    # Every cost of this plant is a yearly cost, so the cost per kg goes as
    # 1/recovery and the 1% step down gives (1/0.99 - 1)/(-0.01).
    assert e["harvesting.recovery"] == pytest.approx((1 / 0.99 - 1) / -0.01, rel=1e-9)
    assert e["system.productivity"] == pytest.approx(e["system.operating_days"], rel=1e-12)


def test_every_cost_comparison_lists_its_coefficients_and_plant(coefficients, compared,
                                                                 dataset):
    cost = {c.builder for c in compared if c.result in COST_RESULTS}
    assert {b.builder for b in coefficients} == cost
    for b in coefficients:
        assert b.plant and b.run_at and b.basis, b.builder
        assert all(c.origin in inputorigin.CLASSES and c.note for c in b.coefficients)
    gwp_only = set(inputorigin.gwp_only(dataset))
    assert gwp_only and gwp_only.isdisjoint(cost)


def test_the_sizes_the_report_quotes_are_those_of_the_scenarios(lib):
    """S4.6.1 says every cost reconstruction runs at its source plant but two."""
    at_source = {"tredici2016": 10_000, "vazquez2022": 10_000, "vazquez2022b_nas": 10_000,
                 "vazquez2022b_tiso_pht": 10_000, "vazquez2022b_nas_10ha": 100_000,
                 "heterotrophic_powder": 150, "spirulina_padi": 116_000}
    for builder, scale in at_source.items():
        assert reconstructions.build(builder, lib).scale == scale, builder

    oil = run_scenario(reconstructions.build("algal_oil", lib)).main_product.annual_kg
    assert round(oil / 1000) == 67_671
    assert round(oil / 1000 / 65_487 - 1, 2) == 0.03                  # "3% more oil"
    assert reconstructions.build("omega3", lib).scale == 2_000
    assert round(2_000 / 1_800 - 1, 2) == 0.11                        # "11% more volume"
    assert round(1 - (2_000 / 1_800) ** 0.6 / (2_000 / 1_800), 2) == 0.04   # "4% less"


def test_the_report_names_every_comparison_and_fits_the_page(coefficients, compared,
                                                              dataset):
    gwp_only = inputorigin.gwp_only(dataset)
    text = report.input_origin(coefficients, compared, gwp_only, inputorigin.CLASSES)
    for c in compared:
        assert c.study in text
    for b in coefficients:
        assert f"({b.builder})" in text
    for builder in gwp_only:
        assert builder in text
    assert supplementary._widest_table_row(text) <= supplementary.PRINT_WIDTH
