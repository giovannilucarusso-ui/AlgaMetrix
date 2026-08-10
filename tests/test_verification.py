"""Tests for internal verification.

Two families, tested differently on purpose. The construction identities hold by
construction, so asserting that they close proves only that ``inventory.py`` and
``verification.py`` still agree — worth having, but it is a regression test. The
admissibility constraints are the ones that carry evidential weight, so the tests
that matter are the ones showing they **fail** when a scenario is physically
impossible. A constraint that has never been observed to fail is indistinguishable
from a constraint that cannot.
"""

from __future__ import annotations

from dataclasses import replace

from algametrix.library import load_library
from algametrix.models import (
    CarbonSource, Drying, Extraction, Harvesting, Product, Scenario, TrophicMode,
)
from algametrix.verification import format_report, verify


def _organism_for(lib, system):
    """An organism that is actually grown the way `system` grows it."""
    if system.mode is TrophicMode.HETEROTROPHIC:
        return lib.organisms["Schizochytrium sp."]
    if system.carbon_source is CarbonSource.BICARBONATE:
        return lib.organisms["Arthrospira platensis (Spirulina)"]
    return lib.organisms["Chlorella vulgaris"]


def _system_scenario(lib, system) -> Scenario:
    return Scenario(
        organism=_organism_for(lib, system),
        system=system,
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics, lcia=lib.lcia, scale=100_000.0,
    )


def test_every_cultivation_system_passes_both_families():
    lib = load_library()
    for name, system in lib.systems.items():
        rep = verify(_system_scenario(lib, system))
        assert rep.all_pass, "\n" + format_report(name, rep)
        assert rep.max_residual < 1e-9
        assert rep.invariants, f"{name}: no admissibility constraint was evaluated"


def test_identities_are_labelled_as_identities_not_as_balances():
    """The naming is the substance here, so it is asserted.

    These checks never mention carbon on the heterotrophic path - the equality is
    substrate x mass yield == gross biomass - and calling them carbon balances
    claimed evidence they do not provide.
    """
    lib = load_library()
    het = next(s for s in lib.systems.values() if s.mode is TrophicMode.HETEROTROPHIC)
    rep = verify(_system_scenario(lib, het))

    names = [c.name for c in rep.identities]
    assert all(n.startswith("Identity:") for n in names), names
    assert not any("balance" in n.lower() for n in names), names
    assert not any(n.lower().startswith("identity: carbon") for n in names), names


def test_the_carbon_constraint_fails_on_a_thermodynamically_impossible_yield():
    """The check the identities could not make.

    One kilogram of glucose carries 0.40 kg of carbon and the biomass is 58 %
    carbon, so no mass yield above ~0.69 can be closed on carbon whatever the
    respiration. The construction identity closes at machine precision for any
    yield whatsoever; the admissibility constraint must not.
    """
    lib = load_library()
    het = next(s for s in lib.systems.values() if s.mode is TrophicMode.HETEROTROPHIC)
    scn = _system_scenario(lib, het)

    ok = verify(scn)
    assert ok.all_pass, "\n" + format_report("as shipped", ok)

    impossible = replace(scn, system=replace(scn.system, substrate_yield=0.95))
    rep = verify(impossible)
    carbon = [i for i in rep.admissibility if "substrate C" in i.name]
    assert carbon, [i.name for i in rep.admissibility]
    assert not carbon[0].passed, carbon[0].detail
    assert not rep.all_pass
    # And the identity is untouched by the same edit, which is the whole point.
    assert rep.max_residual < 1e-9


def test_the_composition_constraint_fails_on_an_impossible_organism():
    """C + N + P above 1 kg per kg dry mass is not a biomass."""
    scn = _raceway()
    bad = replace(scn, organism=replace(scn.organism, carbon=2.0, nitrogen=0.9,
                                        phosphorus=0.9))
    rep = verify(bad)
    comp = [i for i in rep.admissibility if "C+N+P" in i.name]
    assert comp and not comp[0].passed, [i.name for i in rep.admissibility]
    assert rep.max_residual < 1e-9, "the identities cannot see this, by construction"


def test_respired_carbon_is_reported_and_not_summed_into_the_gwp():
    """Under the biogenic 0/0 convention it is bookkeeping, not an emission."""
    from algametrix.inventory import build_inventory
    from algametrix.lca import run_lca

    lib = load_library()
    het = next(s for s in lib.systems.values() if s.mode is TrophicMode.HETEROTROPHIC)
    scn = _system_scenario(lib, het)
    inv = build_inventory(scn)

    assert inv.biogenic_co2_respired_per_kg > 0
    assert inv.biogenic_co2_respired_per_kg == (
        inv.substrate_co2_supplied_per_kg - inv.biogenic_co2_in_gross_biomass_per_kg)

    # The GWP must be unchanged by a field nothing prices or characterizes: the
    # gross value is the sum over the priced/characterized flows only.
    gross = run_lca(scn, inv).gwp_gross_kg_co2eq_per_kg
    inflated = replace(inv, biogenic_co2_respired_per_kg=inv.biogenic_co2_respired_per_kg * 10)
    assert run_lca(scn, inflated).gwp_gross_kg_co2eq_per_kg == gross


def _raceway(**kw) -> Scenario:
    lib = load_library()
    return Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics, lcia=lib.lcia, scale=100_000.0, **kw,
    )


def test_bicarbonate_carbon_balance_closes():
    lib = load_library()
    scn = _raceway()
    scn = replace(scn, system=replace(scn.system, carbon_source=CarbonSource.BICARBONATE))
    rep = verify(scn)
    assert rep.all_pass, "\n" + format_report("bicarbonate raceway", rep)


def test_downstream_product_mass_never_exceeds_biomass():
    scn = _raceway(
        extraction=Extraction(enabled=True, solvent_kg_per_kg=2.0, solvent_recovery=0.99,
                              capex_per_kgyr=0.1, allocation="economic"),
        products=[
            Product("Oil", "lipid", recovery=0.8, price=5.0, is_main=True),
            Product("Residual", "residual", recovery=1.0, price=0.1),
        ],
    )
    rep = verify(scn)
    names = [i.name for i in rep.invariants]
    assert any("Product mass" in n for n in names)
    assert rep.all_pass, "\n" + format_report("raceway + products", rep)


def test_scale_invariance_invariant_is_checked_and_holds():
    rep = verify(_raceway())
    assert any("scale-invariant" in i.name for i in rep.invariants)
    assert all(i.passed for i in rep.invariants)
