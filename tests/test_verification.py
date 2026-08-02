"""Tests for internal balance-closure verification."""

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


def test_balances_close_for_every_cultivation_system():
    """Every scenario the engine can run must conserve carbon, N and P."""
    lib = load_library()
    for name, system in lib.systems.items():
        scn = Scenario(
            organism=_organism_for(lib, system),
            system=system,
            harvesting=lib.harvesting["Settling + centrifugation"],
            drying=lib.drying["Spray drying"],
            economics=lib.economics, lcia=lib.lcia, scale=100_000.0,
        )
        rep = verify(scn)
        assert rep.all_pass, "\n" + format_report(name, rep)
        assert rep.max_residual < 1e-9


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
