"""Phototrophic algal-oil biorefinery with co-product allocation.

Nannochloropsis grown in open ponds, harvested, disrupted and solvent-extracted
into algal oil (main product) with a protein meal co-product and a residual
biomass stream. Demonstrates the downstream extraction + allocation module.

    python examples/algal_oil_biorefinery.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.models import Extraction, Product, Scenario
from algametrix.scenario import run_scenario


def main() -> None:
    lib = load_library()

    extraction = Extraction(
        enabled=True,
        name="Hexane extraction",
        disruption_elec_kwh_per_kg=0.5,   # homogeniser
        elec_kwh_per_kg=0.3,              # extraction + phase separation
        heat_mj_per_kg=2.0,               # solvent recovery (distillation)
        solvent_name="Hexane",
        solvent_kg_per_kg=5.0,
        solvent_recovery=0.99,            # -> 0.05 kg make-up per kg biomass
        solvent_price=1.5,
        solvent_gwp=0.9,
        solvent_ced=55.0,
        capex_per_kgyr=1.0,
        allocation="economic",
    )
    products = [
        Product("Algal oil", fraction="lipid", recovery=0.90, price=2.5, is_main=True),
        Product("Protein meal", fraction="protein", recovery=0.80, price=0.60),
        Product("Residual biomass", fraction="residual", recovery=1.0, price=0.10),
    ]

    system = lib.systems["Open raceway pond"]
    scenario = Scenario(
        organism=lib.organisms["Nannochloropsis sp."],
        system=system,
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["No drying (wet paste)"],  # extract from wet paste
        economics=lib.economics,
        lcia=lib.lcia,
        scale=2_000_000,          # m2 of pond (200 ha)
        extraction=extraction,
        products=products,
    )

    r = run_scenario(scenario)

    print(f"Biorefinery: {scenario.organism.name} -> algal oil (+ co-products)")
    print(f"  Dry biomass          : {r.inventory.annual_biomass_kg / 1000:,.0f} t/yr")
    print(f"  Total investment     : EUR {r.tea.total_investment / 1e6:,.1f} M")
    print(f"  Annual operating cost : EUR {r.tea.annual_opex / 1e6:,.1f} M/yr")
    print(f"  Total revenues       : EUR {r.tea.revenues / 1e6:,.1f} M/yr")
    print(f"  NPV                  : EUR {r.tea.npv / 1e6:,.1f} M   IRR: "
          f"{'n/a' if r.tea.irr is None else f'{r.tea.irr*100:.1f}%'}")
    print(f"  Allocation method    : {scenario.extraction.allocation}")
    print()
    print(f"  {'Product':18s} {'t/yr':>10s} {'€/kg cost':>10s} "
          f"{'€/kg price':>10s} {'alloc %':>8s} {'kgCO2/kg':>9s}")
    for p in r.products:
        print(f"  {p.name:18s} {p.annual_kg/1000:>10,.0f} "
              f"{p.production_cost_eur_per_kg:>10.2f} {p.price:>10.2f} "
              f"{p.allocation_share*100:>7.1f}% {p.gwp_kg_co2eq_per_kg:>9.2f}")
    if r.main_product:
        mp = r.main_product
        print()
        print(f"  MAIN PRODUCT: {mp.name}  ->  "
              f"€ {mp.production_cost_eur_per_kg:.2f}/kg (allocated), "
              f"{mp.gwp_kg_co2eq_per_kg:.2f} kg CO2-eq/kg")


if __name__ == "__main__":
    main()
