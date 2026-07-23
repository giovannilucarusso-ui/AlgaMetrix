"""Tests for the Scenario -> Flowsheet auto-generator (desktop.flowsheet.builder).

These are pure-model tests: the builder and the mass-balance solver do not touch
Qt, so they run headless in CI. They check that every validated template maps to
a solvable flowsheet and that the topology reflects the scenario's key choices.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from desktop.flowsheet import builder, model as M  # noqa: E402
from microalgae_tea_lca.library import load_library  # noqa: E402
from microalgae_tea_lca.models import Basis, CarbonSource, Scenario, TrophicMode  # noqa: E402
from microalgae_tea_lca.scenario import run_scenario  # noqa: E402
from microalgae_tea_lca.templates import TEMPLATES, apply_goal  # noqa: E402


@pytest.fixture(scope="module")
def lib():
    return load_library()


def _kinds(fs: M.Flowsheet) -> list[str]:
    return [n.kind for n in fs.nodes.values()]


def test_all_templates_build_a_solvable_flowsheet(lib):
    """Every wizard template yields a connected, single-pass-solvable flowsheet."""
    for t in TEMPLATES:
        scn = t.build(lib)
        results = run_scenario(scn)
        fs = builder.flowsheet_from_scenario(scn, results)

        assert fs.nodes, f"{t.name}: empty flowsheet"
        # exactly one product sink, at least one cultivation block
        kinds = _kinds(fs)
        assert kinds.count("product") == 1, f"{t.name}: expected one product sink"
        assert any(k in M.UNIT_TYPES and M.UNIT_TYPES[k].category == "cultivation"
                   for k in kinds), f"{t.name}: no cultivation block"

        # the balance solver runs without raising and numbers every stream
        result = M.solve(fs)
        assert not result.warnings, f"{t.name}: solver warnings {result.warnings}"
        # the product sink receives a positive flow
        prod_flows = result.product_flows(fs)
        assert prod_flows, f"{t.name}: no product flow"
        assert any(M.flow_total(f) > 0 for f in prod_flows.values()), \
            f"{t.name}: product sink is dry"


def test_phototrophic_gets_co2_feed(lib):
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000,
    )
    fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
    assert "co2_supply" in _kinds(fs)
    # "Settling + centrifugation" expands into a two-block dewatering train
    assert "settler" in _kinds(fs) and "centrifuge" in _kinds(fs)
    assert "spray_dryer" in _kinds(fs)


def test_bicarbonate_source_uses_a_reagent_feed_not_co2(lib):
    name = "Open raceway pond (Spirulina, NaHCO3)"
    if name not in lib.systems:
        pytest.skip("bicarbonate system not in library")
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems[name],
        harvesting=lib.harvesting["Centrifugation only"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000,
    )
    assert scn.system.carbon_source == CarbonSource.BICARBONATE
    fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
    assert "co2_supply" not in _kinds(fs)
    assert any("NaHCO" in n.name for n in fs.nodes.values())


def test_media_prep_nutrients_and_inoculum_are_present(lib):
    """Raw-material inputs the engine accounts for now appear on the diagram."""
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Centrifugation only"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000,
    )
    res = run_scenario(scn)
    fs = builder.flowsheet_from_scenario(scn, res)
    names = {n.name for n in fs.nodes.values()}
    assert "media_prep" in _kinds(fs)
    assert any("Nutrient" in n for n in names), "no nutrient (N,P) feed"
    assert any("Inoculum" in n for n in names), "no inoculum feed"
    # the media-prep tank feeds the reactor's media port
    prep = next(n for n in fs.nodes.values() if n.kind == "media_prep")
    cult = next(n for n in fs.nodes.values()
                if M.UNIT_TYPES[n.kind].category == "cultivation")
    assert any(lk.src_node == prep.id and lk.dst_node == cult.id and lk.dst_port == "media"
               for lk in fs.links.values())
    # the reactor still solves cleanly (no recycle warnings)
    assert not M.solve(fs).warnings


def test_heterotrophic_gets_fermenter_and_substrate(lib):
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Stirred-tank fermenter (heterotrophic)"],
        harvesting=lib.harvesting["Centrifugation only"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=500,
    )
    assert scn.system.mode == TrophicMode.HETEROTROPHIC
    fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
    assert "fermenter" in _kinds(fs)
    assert any(n.name == "Organic substrate" for n in fs.nodes.values())
    assert "co2_supply" not in _kinds(fs)


def test_extraction_goal_adds_an_extractor(lib):
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000,
    )
    apply_goal(scn, "oil")           # enables extraction + a lipid/oil product
    assert scn.extraction.enabled
    fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
    assert ("extraction" in _kinds(fs)) or ("supercritical_co2" in _kinds(fs))


def test_no_drying_leaves_a_wet_paste(lib):
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Centrifugation only"],
        drying=lib.drying["No drying (wet paste)"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000,
    )
    assert not scn.drying.enabled
    fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
    assert not any(M.UNIT_TYPES[k].category == "thermal" for k in _kinds(fs))


def test_generated_product_matches_engine_main_product(lib):
    """The canvas product stream reproduces the engine's main-product rate."""
    template = next((t for t in TEMPLATES if "omega-3" in t.name.lower()), None)
    if template is None:
        pytest.skip("no extraction template available")
    scn = template.build(lib)
    res = run_scenario(scn)
    assert res.main_product is not None
    fs = builder.flowsheet_from_scenario(scn, res)

    sol = M.solve(fs)
    prod = next(n for n in fs.nodes.values() if n.kind == "product")
    agg = M.empty_flow()
    for lk in fs.links.values():
        if lk.dst_node == prod.id:
            agg = M.flow_add(agg, sol.stream_flows.get(lk.id, M.empty_flow()))

    expected_kg_h = res.main_product.annual_kg / builder._op_hours(scn)
    assert agg["product"] == pytest.approx(expected_kg_h, rel=1e-3)


def test_flows_scale_with_the_case(lib):
    """A larger plant should push a proportionally larger product stream."""
    def product_flow(scale: float) -> float:
        scn = Scenario(
            organism=lib.organisms["Chlorella vulgaris"],
            system=lib.systems["Open raceway pond"],
            harvesting=lib.harvesting["Centrifugation only"],
            drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
            scale=scale,
        )
        fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
        res = M.solve(fs)
        return max(M.flow_total(f) for f in res.product_flows(fs).values())

    assert product_flow(200_000) > 1.9 * product_flow(100_000)
