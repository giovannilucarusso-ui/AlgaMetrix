"""The regional electricity values behind the setup's region picker.

Each value the picker can put into a scenario must say where it comes from, for
which year and for which geography, the same rule data/lcia.yaml follows for the
background factors.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.regions import describe, load_regions, statement
from algametrix.templates import build_template

QUALITY = {"sourced", "derived"}


@pytest.fixture(scope="module")
def regional():
    data = load_regions()
    assert data is not None, "data/regions.yaml is missing"
    return data


def test_every_value_carries_its_provenance(regional):
    assert regional.regions
    assert len(set(regional.names())) == len(regional.regions), "duplicate region name"
    for r in regional.regions:
        values = [r.grid] + ([r.price] if r.price is not None else [])
        for v in values:
            assert v.source, r.name
            assert v.geography, r.name
            assert v.quality in QUALITY, r.name
            assert v.year == regional.reference_year, r.name
        if r.price is None:
            # A missing price has to say why, or it reads as an oversight.
            assert r.price_note, f"{r.name} has no price and no note saying why"
    for text in (regional.price_scope, regional.grid_scope, regional.grid_source):
        assert text


def test_values_are_in_a_physical_range(regional):
    for r in regional.regions:
        assert 0.005 <= r.grid.value <= 1.2, r.name
        if r.price is not None:
            assert 0.02 <= r.price.value <= 0.6, r.name


def test_a_region_sets_both_inputs_or_only_the_grid_factor(regional):
    lib = load_library()
    scn = build_template("Single-cell protein (Chlorella, raceway)", lib)
    italy = regional.get("Italy")
    italy.apply(scn)
    assert scn.lcia.elec_gwp == italy.grid.value
    assert scn.economics.electricity_price == italy.price.value

    before = scn.economics.electricity_price
    china = regional.get("China")
    assert china.price is None
    china.apply(scn)
    assert scn.lcia.elec_gwp == china.grid.value
    assert scn.economics.electricity_price == before


def test_the_statement_lists_every_region_with_its_scope(regional):
    text = statement(regional)
    for r in regional.regions:
        assert r.name in text
    assert "generation-based" in " ".join(text.split())
    assert "band ID" in text
    assert "Price not set" in describe(regional.get("World"))
