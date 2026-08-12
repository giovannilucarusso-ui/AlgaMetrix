"""Tests for waste-derived nutrient and carbon feeds.

What these hold, in one sentence each: a waste stream changes what is *bought*
and not what the biomass *needs*; one stream has one composition, so covering
one nutrient fixes what arrives of the others; and the system-expansion credit
only exists where the scenario says it does.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.consistency import check_scenario
from algametrix.inventory import build_inventory
from algametrix.lca import run_lca
from algametrix.library import load_library
from algametrix.models import Scenario, WasteBurdenConvention, WasteFeed
from algametrix.tea import run_tea
from algametrix.templates import build_template
from algametrix.verification import verify

TOL = 1e-12


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def photo(lib):
    """A phototrophic raceway: buys nitrogen, phosphorus and CO2."""
    return build_template("Single-cell protein (Chlorella, raceway)", lib)


@pytest.fixture(scope="module")
def hetero(lib):
    """A heterotrophic fermenter: buys substrate as well."""
    return build_template("Heterotrophic microalgae powder", lib)


def _feed(**kw) -> WasteFeed:
    base = dict(enabled=True, name="Test effluent", unit="m3",
                nitrogen_per_unit=0.04, phosphorus_per_unit=0.007,
                dosed_on="nitrogen", coverage=1.0)
    base.update(kw)
    return WasteFeed(**base)


# =====================================================================
# The default changes nothing
# =====================================================================

def test_no_waste_feed_leaves_every_number_where_it_was(photo):
    """The feature is invisible until it is switched on.

    Every published result was produced without it, so the disabled default has
    to reproduce them exactly - not nearly.
    """
    inv = build_inventory(photo)
    assert inv.waste_feed_per_kg == 0.0
    assert inv.nitrogen_purchased_per_kg == inv.nitrogen_per_kg
    assert inv.phosphorus_purchased_per_kg == inv.phosphorus_per_kg
    assert inv.substrate_purchased_per_kg == inv.substrate_per_kg
    assert inv.nitrogen_surplus_per_kg == 0.0
    assert run_lca(photo, inv).avoided_treatment_kg_co2eq_per_kg == 0.0


# =====================================================================
# What the stream covers, and what it drags along with it
# =====================================================================

def test_the_dosed_nutrient_is_covered_and_fixes_the_quantity(photo):
    scn = replace(photo, waste_feed=_feed())
    inv = build_inventory(scn)
    assert inv.nitrogen_purchased_per_kg == pytest.approx(0.0, abs=TOL)
    assert inv.nitrogen_from_waste_per_kg == pytest.approx(inv.nitrogen_per_kg)
    # quantity = demand / concentration, and nothing else.
    assert inv.waste_feed_per_kg == pytest.approx(inv.nitrogen_per_kg / 0.04)


def test_the_other_nutrient_arrives_in_the_ratio_the_stream_has(photo):
    """One composition, not two dials.

    A stream dosed on nitrogen delivers phosphorus in its own ratio. Here it
    over-delivers, and the excess has to show up as surplus rather than vanish.
    """
    scn = replace(photo, waste_feed=_feed())
    inv = build_inventory(scn)
    delivered_p = inv.waste_feed_per_kg * 0.007
    assert delivered_p > inv.phosphorus_per_kg          # this stream is P-rich
    assert inv.phosphorus_purchased_per_kg == pytest.approx(0.0, abs=TOL)
    assert inv.phosphorus_surplus_per_kg == pytest.approx(
        delivered_p - inv.phosphorus_per_kg)


def test_a_phosphorus_poor_stream_still_leaves_phosphorus_to_buy(photo):
    scn = replace(photo, waste_feed=_feed(phosphorus_per_unit=0.0005))
    inv = build_inventory(scn)
    assert inv.phosphorus_purchased_per_kg > 0
    assert inv.phosphorus_surplus_per_kg == 0.0
    assert (inv.phosphorus_purchased_per_kg + inv.phosphorus_from_waste_per_kg
            == pytest.approx(inv.phosphorus_per_kg))


def test_partial_coverage_displaces_proportionally(photo):
    scn = replace(photo, waste_feed=_feed(coverage=0.4))
    inv = build_inventory(scn)
    assert inv.nitrogen_from_waste_per_kg == pytest.approx(0.4 * inv.nitrogen_per_kg)
    assert inv.nitrogen_purchased_per_kg == pytest.approx(0.6 * inv.nitrogen_per_kg)


def test_a_stream_dosed_on_what_it_does_not_carry_does_nothing(photo):
    """Silence, not a guess.

    Dosing on substrate a stream with no substrate must not quietly fall back to
    nitrogen: the scenario as written buys everything, and the invariant says so.
    """
    scn = replace(photo, waste_feed=_feed(dosed_on="substrate", substrate_per_unit=0.0))
    inv = build_inventory(scn)
    assert inv.waste_feed_per_kg == 0.0
    assert inv.nitrogen_purchased_per_kg == inv.nitrogen_per_kg


def test_a_food_byproduct_can_displace_the_carbon_feed(hetero):
    """Whey permeate is a sugar first and a fertiliser second."""
    whey = _feed(name="Whey permeate", kind="food_byproduct", dosed_on="substrate",
                 substrate_per_unit=45.0, nitrogen_per_unit=0.35,
                 phosphorus_per_unit=0.35)
    scn = replace(hetero, waste_feed=whey)
    inv = build_inventory(scn)
    assert inv.substrate_per_kg > 0
    assert inv.substrate_purchased_per_kg == pytest.approx(0.0, abs=TOL)
    assert inv.waste_feed_per_kg == pytest.approx(inv.substrate_per_kg / 45.0)


# =====================================================================
# Money
# =====================================================================

def test_a_gate_fee_lowers_the_cost_and_shows_as_its_own_line(photo):
    fed = replace(photo, waste_feed=_feed(price_per_unit=-0.15))
    base_cost = run_tea(photo, build_inventory(photo)).production_cost_eur_per_kg
    inv = build_inventory(fed)
    tea = run_tea(fed, inv)
    assert tea.production_cost_eur_per_kg < base_cost
    line = tea.opex_breakdown["Test effluent"] / inv.annual_biomass_kg
    assert line == pytest.approx(inv.waste_feed_per_kg * -0.15)
    # The gate fee is its own line and is not netted into the nitrogen line,
    # which has simply gone to zero and is dropped from the breakdown with every
    # other zero. Nothing negative hides inside a materials line.
    assert tea.opex_breakdown.get("Nitrogen", 0.0) == pytest.approx(0.0, abs=TOL)
    assert run_tea(photo, build_inventory(photo)).opex_breakdown["Nitrogen"] > 0


def test_an_expensive_stream_can_cost_more_than_the_fertiliser_it_saves(photo):
    """Waste is not automatically cheap, and the model must be able to say so."""
    dear = replace(photo, waste_feed=_feed(price_per_unit=1.0))
    base_cost = run_tea(photo, build_inventory(photo)).production_cost_eur_per_kg
    assert run_tea(dear, build_inventory(dear)).production_cost_eur_per_kg > base_cost


def test_the_treatment_credit_stays_out_of_the_operating_cost(photo):
    """No money changes hands for it, so it cannot lower the production cost.

    The gate fee is invoiced and belongs in the AOC. The treatment displaced is
    a service the plant was never paid for: crediting it against the production
    cost would report a cost nobody could reproduce from an invoice.
    """
    scn = replace(photo, waste_feed=_feed(
        convention=WasteBurdenConvention.AVOIDED_TREATMENT,
        avoided_treatment_cost_per_unit=0.30))
    inv = build_inventory(scn)
    tea = run_tea(scn, inv)
    plain = run_tea(replace(photo, waste_feed=_feed()), build_inventory(scn))

    expected = inv.waste_feed_per_kg * 0.30 * inv.annual_biomass_kg
    assert tea.avoided_treatment_credit == pytest.approx(expected)
    # Gross AOC and gross production cost are untouched by the credit...
    assert tea.annual_opex == pytest.approx(plain.annual_opex)
    assert tea.production_cost_eur_per_kg == pytest.approx(
        plain.production_cost_eur_per_kg)
    # ...while the net cost and the profit both carry it.
    assert tea.net_production_cost_eur_per_kg < plain.net_production_cost_eur_per_kg
    assert tea.gross_profit == pytest.approx(plain.gross_profit + expected)


def test_cut_off_grants_no_treatment_credit_either(photo):
    """One convention governs both analyses; neither leaks under cut-off."""
    scn = replace(photo, waste_feed=_feed(
        convention=WasteBurdenConvention.CUT_OFF,
        avoided_treatment_cost_per_unit=99.0))
    tea = run_tea(scn, build_inventory(scn))
    assert tea.avoided_treatment_credit == 0.0


def test_the_gate_fee_and_the_treatment_credit_are_different_money(photo):
    """A works can be paid 0.15/m3 while displacing 0.30/m3 of treatment.

    Conflating the two would either invent revenue that is not invoiced or hide
    a service that is real; they move different numbers and must stay apart.
    """
    scn = replace(photo, waste_feed=_feed(
        price_per_unit=-0.15,
        convention=WasteBurdenConvention.AVOIDED_TREATMENT,
        avoided_treatment_cost_per_unit=0.30))
    inv = build_inventory(scn)
    tea = run_tea(scn, inv)
    fee = inv.waste_feed_per_kg * -0.15 * inv.annual_biomass_kg
    assert tea.opex_breakdown["Test effluent"] == pytest.approx(fee)      # invoiced
    assert tea.avoided_treatment_credit == pytest.approx(-2.0 * fee)     # not invoiced


# =====================================================================
# Burden
# =====================================================================

def test_waste_nitrogen_carries_no_fertiliser_burden(photo):
    scn = replace(photo, waste_feed=_feed())
    base_lca = run_lca(photo, build_inventory(photo))
    lca = run_lca(scn, build_inventory(scn))
    assert lca.gwp_breakdown.get("Nitrogen", 0.0) == pytest.approx(0.0, abs=TOL)
    assert lca.gwp_kg_co2eq_per_kg < base_lca.gwp_kg_co2eq_per_kg
    # The upstream-production term of eutrophication goes with the purchase; the
    # direct emission does not, and the surplus adds to it.
    assert lca.impacts["Marine eutrophication (kg N-eq)"] > 0


def test_handling_burden_is_charged_to_the_receiving_system(photo):
    scn = replace(photo, waste_feed=_feed(gwp_per_unit=0.5, ced_per_unit=4.0))
    inv = build_inventory(scn)
    lca = run_lca(scn, inv)
    assert lca.gwp_breakdown["Test effluent"] == pytest.approx(
        inv.waste_feed_per_kg * 0.5)


def test_pumping_the_stream_lands_on_the_cultivation_electricity(photo):
    scn = replace(photo, waste_feed=_feed(elec_kwh_per_unit=0.05))
    base_inv = build_inventory(photo)
    inv = build_inventory(scn)
    added = inv.waste_feed_per_kg * 0.05
    assert inv.elec_kwh_per_kg == pytest.approx(base_inv.elec_kwh_per_kg + added)
    assert inv.elec_breakdown["cultivation"] == pytest.approx(
        base_inv.elec_breakdown["cultivation"] + added)


# =====================================================================
# The convention has to be declared to have an effect
# =====================================================================

def test_cut_off_grants_no_credit_however_large_the_avoided_burden(photo):
    scn = replace(photo, waste_feed=_feed(
        convention=WasteBurdenConvention.CUT_OFF,
        avoided_treatment_gwp_per_unit=99.0))
    lca = run_lca(scn, build_inventory(scn))
    assert lca.avoided_treatment_kg_co2eq_per_kg == 0.0
    assert "Avoided treatment (system expansion)" not in lca.gwp_breakdown


def test_system_expansion_credits_on_its_own_line_and_outside_the_gross(photo):
    scn = replace(photo, waste_feed=_feed(
        convention=WasteBurdenConvention.AVOIDED_TREATMENT,
        avoided_treatment_gwp_per_unit=0.35))
    inv = build_inventory(scn)
    lca = run_lca(scn, inv)
    expected = -inv.waste_feed_per_kg * 0.35
    assert lca.avoided_treatment_kg_co2eq_per_kg == pytest.approx(expected)
    assert lca.gwp_breakdown["Avoided treatment (system expansion)"] == pytest.approx(expected)
    # Gross means "before credits": a reader can undo the choice by adding it back.
    assert lca.gwp_gross_kg_co2eq_per_kg > lca.gwp_kg_co2eq_per_kg
    assert lca.gwp_kg_co2eq_per_kg == pytest.approx(
        lca.gwp_gross_kg_co2eq_per_kg
        + lca.biogenic_adjustment_kg_co2eq_per_kg
        + lca.avoided_treatment_kg_co2eq_per_kg)
    assert lca.waste_burden_convention == "avoided_treatment"


# =====================================================================
# The checks that hold the rest together
# =====================================================================

@pytest.mark.parametrize("dosed_on,extra", [
    ("nitrogen", {}),
    ("phosphorus", {}),
    ("nitrogen", {"coverage": 0.35}),
    ("nitrogen", {"phosphorus_per_unit": 0.0005}),
])
def test_every_identity_still_closes(photo, dosed_on, extra):
    scn = replace(photo, waste_feed=_feed(dosed_on=dosed_on, **extra))
    report = verify(scn)
    assert report.all_pass, [c.name for c in report.balances if not c.closes]
    assert report.max_residual < 1e-9


@pytest.mark.parametrize("convention", list(WasteBurdenConvention))
def test_the_independent_matrix_implementation_agrees(photo, hetero, convention):
    """Two implementations, one answer.

    The sequential engine subtracts the credit on its own line; the matrix
    formalism carries it as a negative factor on the received stream. Agreeing
    is the only evidence that either of them is doing what it claims.
    """
    from algametrix.paper import matrixlca

    feeds = {
        "photo": _feed(price_per_unit=-0.15, gwp_per_unit=0.4, elec_kwh_per_unit=0.05,
                       convention=convention, avoided_treatment_gwp_per_unit=0.35),
        # Dosed on substrate, so it also exercises the heterotrophic branch and
        # arrives with more phosphorus than the culture can use.
        "hetero": _feed(dosed_on="substrate", substrate_per_unit=45.0,
                        nitrogen_per_unit=0.35, phosphorus_per_unit=0.35,
                        convention=convention, avoided_treatment_gwp_per_unit=0.2),
    }
    for host, feed in ((photo, feeds["photo"]), (hetero, feeds["hetero"])):
        scn = replace(host, waste_feed=feed)
        report = matrixlca.benchmark(scn, "waste feed")
        bad = [(r.label, r.engine, r.matrix, r.rel_diff)
               for r in report.rows if r.rel_diff > matrixlca.BENCHMARK_TOL]
        assert not bad, bad


def test_the_shared_flow_is_recovered_identically_from_cost_and_impact(photo):
    """The stream is a shared flow, so the consistency check must see it."""
    scn = replace(photo, waste_feed=_feed(price_per_unit=-0.15, gwp_per_unit=0.5))
    report = check_scenario(scn, "wastewater")
    assert report.all_pass
    names = {f.flow for f in report.active_flows}
    assert "Waste feed" in names


# =====================================================================
# The catalogue
# =====================================================================

def test_the_catalogue_loads_and_every_entry_is_usable(lib, photo, hetero):
    assert lib.waste_feeds, "no waste feeds in the library"
    for name, feed in lib.waste_feeds.items():
        assert feed.enabled, name
        assert feed.kind in ("wastewater", "food_byproduct"), name
        assert feed.unit in ("m3", "kg"), name
        assert feed.dosed_on in ("nitrogen", "phosphorus", "substrate"), name
        assert 0.0 <= feed.coverage <= 1.0, name
        assert feed.notes.strip(), f"{name} has no provenance"
        # Dosed on something it actually carries, or it would silently do nothing.
        carried = {"nitrogen": feed.nitrogen_per_unit,
                   "phosphorus": feed.phosphorus_per_unit,
                   "substrate": feed.substrate_per_unit}[feed.dosed_on]
        assert carried > 0, f"{name} is dosed on {feed.dosed_on} but carries none"
        # And it runs, on whichever trophic mode can use it.
        host = hetero if feed.dosed_on == "substrate" else photo
        scn = replace(host, waste_feed=feed)
        assert verify(scn).all_pass, name
        assert build_inventory(scn).waste_feed_per_kg > 0, name


def test_an_avoided_treatment_figure_is_never_entered_negative(lib):
    """It is subtracted by the engine, so a negative entry would add a burden."""
    for name, feed in lib.waste_feeds.items():
        assert feed.avoided_treatment_gwp_per_unit >= 0, name
        assert feed.avoided_treatment_ced_per_unit >= 0, name
        assert feed.avoided_treatment_cost_per_unit >= 0, name


def test_a_stream_that_displaces_treatment_says_so_in_both_currencies(lib):
    """A credit in one analysis and not the other would split the boundary.

    The two figures are independent numbers, but a stream that displaces a
    treatment displaces both its emissions and its cost. Declaring one without
    the other is the asymmetry that lets a TEA and an LCA drift into describing
    different systems.
    """
    for name, feed in lib.waste_feeds.items():
        has_burden = feed.avoided_treatment_gwp_per_unit > 0
        has_cost = feed.avoided_treatment_cost_per_unit > 0
        assert has_burden == has_cost, (
            f"{name}: avoided-treatment GWP and cost must be declared together")
