"""Tests for the designer's link to the engine (desktop.flowsheet.process).

Pure-model tests, no Qt. The attribution checks are the important ones: the
designer colours blocks by cost and GWP, and those figures must be the engine's
totals split up, not numbers of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from desktop.flowsheet import builder as B, model as M, process as P  # noqa: E402
from algametrix.library import load_library  # noqa: E402
from algametrix.models import Basis  # noqa: E402
from algametrix.scenario import run_scenario  # noqa: E402
from algametrix.templates import TEMPLATES, build_template  # noqa: E402

WASTEWATER = "Biomass on municipal wastewater (raceway)"


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def cases(lib):
    return [(t.name, t.build(lib)) for t in TEMPLATES]


def test_block_costs_add_up_to_the_annual_operating_cost(cases):
    for name, scn in cases:
        r = run_scenario(scn)
        att = P.attribute(r)
        total = sum(u.annual_cost for u in att.units.values())
        assert total == pytest.approx(r.tea.annual_opex, rel=1e-9), name


def test_block_gwp_adds_up_to_the_net_gwp(cases):
    for name, scn in cases:
        r = run_scenario(scn)
        att = P.attribute(r)
        total = sum(u.gwp for u in att.units.values())
        assert total == pytest.approx(r.lca.gwp_kg_co2eq_per_kg, abs=1e-9), name


def test_stage_energy_adds_up_to_the_inventory(cases):
    for name, scn in cases:
        r = run_scenario(scn)
        elec, heat = P.stage_energy(r)
        assert sum(elec.values()) == pytest.approx(r.inventory.elec_kwh_per_kg, abs=1e-9), name
        assert sum(heat.values()) == pytest.approx(r.inventory.heat_mj_per_kg, abs=1e-9), name


def test_capital_shares_add_up_to_the_direct_fixed_capital(cases):
    for name, scn in cases:
        r = run_scenario(scn)
        att = P.attribute(r)
        assert sum(u.capital for u in att.units.values()) == pytest.approx(r.tea.dfc, rel=1e-9), name


def test_biogenic_credit_sits_on_cultivation(lib):
    r = run_scenario(TEMPLATES[0].build(lib))
    credit = r.lca.gwp_breakdown.get("Biogenic CO2 uptake", 0.0)
    if not credit:
        pytest.skip("no biogenic credit in this case")
    att = P.attribute(r)
    assert att.units[B.CULTIVATION].gwp_items["Biogenic CO2 uptake"] == pytest.approx(credit)


def test_every_generated_block_has_a_role_and_area_tag(cases):
    for name, scn in cases:
        fs = B.flowsheet_from_scenario(scn, run_scenario(scn))
        for node in fs.nodes.values():
            assert node.role, f"{name}: {node.name} has no role"
            base = P.role_base(node.role)
            assert base in P.ROLE_LABELS, f"{name}: unknown role {node.role}"
            assert base == B.PRODUCT or P.section_of(node.role) is not None, name
        cult = next(n for n in fs.nodes.values() if n.role == B.CULTIVATION)
        assert cult.tag.endswith("-201"), f"{name}: cultivation tagged {cult.tag}"
        tags = [n.tag for n in fs.nodes.values()]
        assert len(tags) == len(set(tags)), f"{name}: duplicate tags {tags}"


def test_two_stage_train_recovers_what_the_engine_assumes(lib):
    for t in TEMPLATES:
        scn = t.build(lib)
        if len(B.harvest_chain(scn)) < 2:
            continue
        fs = B.flowsheet_from_scenario(scn, run_scenario(scn))
        assert B.harvest_recovery_on_canvas(fs) == pytest.approx(scn.harvesting.recovery), t.name
        sol = M.solve(fs)
        prod = sol.product_flows(fs)
        # whole-biomass cases: the product sink receives the net dry biomass
        if not scn.products and scn.drying.enabled:
            expected = run_scenario(scn).inventory.annual_biomass_kg / B._op_hours(scn)
            got = max(f["biomass"] for f in prod.values())
            assert got == pytest.approx(expected, rel=1e-6), t.name


def test_waste_feed_is_drawn_into_media_prep(lib):
    scn = build_template(WASTEWATER, lib)
    assert scn.waste_feed.enabled
    fs = B.flowsheet_from_scenario(scn, run_scenario(scn))
    feed = next(n for n in fs.nodes.values() if n.role == B.FEED_WASTE)
    prep = next(n for n in fs.nodes.values() if n.role == B.MEDIA_PREP)
    assert any(lk.src_node == feed.id and lk.dst_node == prep.id and lk.dst_port == "waste"
               for lk in fs.links.values())
    assert feed.params["flow_kg_h"] > 0


def test_role_survives_a_save_and_reload(cases):
    _, scn = cases[0]
    fs = B.flowsheet_from_scenario(scn, run_scenario(scn))
    again = M.Flowsheet.from_dict(fs.to_dict())
    assert {n.id: n.role for n in again.nodes.values()} == {n.id: n.role for n in fs.nodes.values()}


def test_seeding_moves_flows_without_moving_blocks(lib):
    scn = TEMPLATES[0].build(lib)
    fs = B.flowsheet_from_scenario(scn, run_scenario(scn))
    where = {n.id: (n.x, n.y) for n in fs.nodes.values()}
    before = max(M.flow_total(f) for f in M.solve(fs).product_flows(fs).values())
    scn.scale *= 2
    B.seed_flows(fs, scn, run_scenario(scn))
    after = max(M.flow_total(f) for f in M.solve(fs).product_flows(fs).values())
    assert after == pytest.approx(2 * before, rel=1e-6)
    assert {n.id: (n.x, n.y) for n in fs.nodes.values()} == where


# --------------------------------------------------------------------------- #
# Variables
# --------------------------------------------------------------------------- #
def test_every_variable_reads_and_writes_its_field(cases):
    for name, scn in cases:
        fs = B.flowsheet_from_scenario(scn, run_scenario(scn))
        roles = {n.role for n in fs.nodes.values()} | {P.PLANT}
        for role in roles:
            for var in P.variables_for(role, scn):
                x = P.get_value(scn, var.path)
                trial = P._with(scn, var.path, x * 1.1 + 0.01)
                assert P.get_value(trial, var.path) == pytest.approx(x * 1.1 + 0.01), \
                    f"{name}: {var.path}"
                assert P.get_value(scn, var.path) == x, f"{name}: {var.path} leaked"


def test_variable_units_follow_the_cultivation_basis(lib):
    fermenter = build_template("Heterotrophic microalgae powder", lib)
    raceway = TEMPLATES[0].build(lib)
    assert fermenter.system.basis == Basis.VOLUME and raceway.system.basis == Basis.AREA
    assert not fermenter.batch_mode

    def unit(scn, path):
        return next(v.unit for v in P.variables_for(B.CULTIVATION, scn) if v.path == path)

    assert unit(fermenter, "system.productivity") == "g/L/d"
    assert unit(raceway, "system.productivity") == "g/m²/d"
    paths = {v.path for v in P.variables_for(B.CULTIVATION, fermenter)}
    assert "system.substrate_yield" in paths and "system.co2_utilization" not in paths


def test_a_batch_case_exposes_the_batch_schedule(lib):
    omega3 = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    assert omega3.batch_mode
    paths = {v.path for v in P.variables_for(B.CULTIVATION, omega3)}
    assert {"batch_size_kg", "batch_cycle_time_h"} <= paths
    assert "system.productivity" not in paths     # not read in batch mode


def test_selling_price_follows_the_main_product(lib):
    oil = next(t for t in TEMPLATES if "algal-oil" in t.name.lower()).build(lib)
    main = P._main(oil)
    assert main is not None
    P.set_value(oil, P.SELLING_PRICE, 12.5)
    assert main.price == 12.5
    r = run_scenario(oil)
    assert r.main_product.price == 12.5


def test_an_input_issue_finds_its_block(lib):
    scn = TEMPLATES[0].build(lib)
    scn.harvesting.recovery = 0.0
    results, issues = P.evaluate(scn)
    assert results is None
    bad = next(i for i in issues if i.field == "harvesting.recovery")
    fs = B.flowsheet_from_scenario(scn)
    roles = {n.role for n in fs.nodes.values()}
    owners = P.owner_roles(bad.field, scn, roles)
    assert B.HARVEST in owners


# --------------------------------------------------------------------------- #
# Sensitivities
# --------------------------------------------------------------------------- #
def _var(scn, role, path):
    return next(v for v in P.variables_for(role, scn) if v.path == path)


def test_elasticities_have_the_expected_sign(lib):
    scn = TEMPLATES[0].build(lib)
    price = _var(scn, P.PLANT, "economics.electricity_price")
    recovery = _var(scn, B.HARVEST, "harvesting.recovery")
    productivity = _var(scn, B.CULTIVATION, "system.productivity")
    conc = _var(scn, B.CULTIVATION, "system.biomass_conc")
    assert P.elasticity(scn, price)[0] > 0
    assert P.elasticity(scn, recovery)[0] < 0
    assert P.elasticity(scn, productivity)[0] < 0
    # the harvest concentration does not enter the cost or the GWP
    e_cost, e_gwp = P.elasticity(scn, conc)
    assert e_cost == pytest.approx(0.0, abs=1e-12) and e_gwp == pytest.approx(0.0, abs=1e-12)


def test_elasticity_respects_physical_bounds(lib):
    scn = TEMPLATES[0].build(lib)
    scn.harvesting.recovery = 1.0
    recovery = _var(scn, B.HARVEST, "harvesting.recovery")
    e_cost, _ = P.elasticity(scn, recovery)
    assert e_cost is not None and e_cost < 0     # one-sided, never above 100 %


def test_response_curve_rises_with_the_electricity_price(lib):
    scn = TEMPLATES[0].build(lib)
    price = _var(scn, P.PLANT, "economics.electricity_price")
    pts = P.response_curve(scn, price, n=11)
    costs = [c for _x, c, _g in pts]
    assert len(pts) == 11
    assert all(b > a for a, b in zip(costs, costs[1:]))


def test_tornado_puts_the_biggest_swing_first(lib):
    scn = TEMPLATES[0].build(lib)
    rows = P.tornado(scn, P.variables_for(P.PLANT, scn) + P.variables_for(B.CULTIVATION, scn))
    c0 = P.headline(run_scenario(scn))[0]
    swings = [max(abs(lo - c0), abs(hi - c0)) for _v, lo, hi in rows]
    assert swings == sorted(swings, reverse=True)


# --------------------------------------------------------------------------- #
# Editing session
# --------------------------------------------------------------------------- #
def test_session_works_on_a_copy(lib):
    scn = TEMPLATES[0].build(lib)
    s = P.DesignSession(scn, lib)
    var = _var(scn, B.HARVEST, "harvesting.recovery")
    s.set_value(var, 0.8)
    assert scn.harvesting.recovery != 0.8            # the case study is untouched
    assert s.scenario.harvesting.recovery == 0.8
    assert s.is_dirty and s.changed_paths() == {"harvesting.recovery"}


def test_a_slider_drag_is_one_undo_step(lib):
    s = P.DesignSession(TEMPLATES[0].build(lib), lib)
    var = _var(s.scenario, B.CULTIVATION, "system.productivity")
    x0 = P.get_value(s.scenario, var.path)
    for k in range(1, 6):
        s.set_value(var, x0 + k)
    assert len(s.history) == 2
    assert "→" in s.state.label and f"{x0:,.2f}" in s.state.label
    s.undo()
    assert P.get_value(s.scenario, var.path) == x0
    s.redo()
    assert P.get_value(s.scenario, var.path) == x0 + 5


def test_undo_then_edit_drops_the_redo_branch(lib):
    s = P.DesignSession(TEMPLATES[0].build(lib), lib)
    a = _var(s.scenario, B.HARVEST, "harvesting.recovery")
    b = _var(s.scenario, B.DRYING, "drying.final_solids")
    s.set_value(a, 0.8)
    s.set_value(b, 0.9)
    s.undo()
    s.set_value(a, 0.7, coalesce=False)
    assert not s.can_redo()
    assert s.scenario.drying.final_solids != 0.9


def test_an_inadmissible_edit_keeps_the_last_good_result(lib):
    s = P.DesignSession(TEMPLATES[0].build(lib), lib)
    good = s.results
    var = _var(s.scenario, B.CULTIVATION, "system.productivity")
    s.set_value(var, 0.0)
    assert s.results is None
    assert any(i.field == "system.productivity" for i in s.issues)
    assert s.last_good() is good


def test_reset_is_a_step_that_can_be_undone(lib):
    s = P.DesignSession(TEMPLATES[0].build(lib), lib)
    var = _var(s.scenario, B.HARVEST, "harvesting.recovery")
    s.set_value(var, 0.8)
    s.reset()
    assert s.scenario.harvesting.recovery == s.baseline.harvesting.recovery
    assert not s.is_dirty
    s.undo()
    assert s.scenario.harvesting.recovery == 0.8


def test_switching_technology_swaps_the_preset(lib):
    s = P.DesignSession(TEMPLATES[0].build(lib), lib)
    s.set_technology(B.HARVEST, "Centrifugation only")
    assert s.scenario.harvesting.name == "Centrifugation only"
    assert B.harvest_chain(s.scenario) == ["centrifuge"]
    s.set_technology(B.CULTIVATION, "Bubble-column / airlift PBR")
    assert s.scenario.system.basis == Basis.VOLUME
    assert s.scenario.scale == 500.0          # area-sized scale would be meaningless
    assert s.results is not None
