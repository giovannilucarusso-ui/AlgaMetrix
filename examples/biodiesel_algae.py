"""Algal biodiesel — large open-pond biofuel case.

Open ponds -> harvesting -> extraction -> transesterification to biodiesel (FAME)
with a glycerol co-product. Reference: NREL/updated algal biodiesel cost
$0.42-0.97/L; a for-profit minimum diesel selling price under ~$1.85/L; biomass
cost target < $500/t at areal productivity > 25 g/m2/day. Algal biodiesel is
famously not yet cost-competitive — the model reflects that honestly.

    python examples/biodiesel_algae.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Extraction, Material, Product, Scenario
from microalgae_tea_lca.scenario import run_scenario

FAME_DENSITY = 0.88  # kg/L


def main() -> None:
    lib = load_library()
    system = replace(
        lib.systems["Open raceway pond"],
        capex_per_unit=2.0, water_m3_per_kg=0.08, elec_kwh_per_kg=0.15,
        productivity=25.0,   # NREL productivity target
    )
    economics = replace(
        lib.economics, labor_cost_per_year=5_000_000.0,
        harvest_capex_per_kgyr=0.05, drying_capex_per_kgyr=0.0,
        nitrogen_price=0.9, water_price=1.0, co2_price=0.0,
        electricity_price=0.10, land_price=0.5, overhead_frac=0.05,
    )
    extraction = Extraction(
        enabled=True, name="Extraction + transesterification",
        disruption_elec_kwh_per_kg=0.1, elec_kwh_per_kg=0.1, heat_mj_per_kg=0.6,
        solvent_name="Hexane", solvent_kg_per_kg=2.0, solvent_recovery=0.995,
        solvent_price=2.0, solvent_gwp=0.9, solvent_ced=55.0,
        capex_per_kgyr=0.03, allocation="economic",
    )
    # lipid 0.35 * extraction 0.9 * transesterification 0.98 ~ 0.31 kg FAME / kg biomass
    products = [
        Product("Biodiesel (FAME)", "custom", yield_override=0.31, price=1.0, is_main=True),
        Product("Glycerol", "custom", yield_override=0.03, price=0.4),
        Product("Residual (feed/AD)", "custom", yield_override=0.6, price=0.05),
    ]
    scenario = Scenario(
        organism=lib.organisms["Nannochloropsis sp."],
        system=system,
        harvesting=lib.harvesting["Membrane filtration"],
        drying=lib.drying["No drying (wet paste)"],
        economics=economics,
        lcia=lib.lcia,
        scale=40_000_000.0,   # m2 pond (4,000 ha)
        extraction=extraction,
        products=products,
        materials=[Material("Methanol", amount_per_kg=0.04, price=0.4, gwp=0.8, ced=35.0)],
        credits_per_year=10_000_000.0,   # anaerobic digestion of residual
    )

    r = run_scenario(scenario)
    mp = r.main_product
    cost_l = mp.production_cost_eur_per_kg * FAME_DENSITY
    print("Algal biodiesel (large open-pond biorefinery)")
    print(f"  Dry biomass          : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr")
    print(f"  Biodiesel output     : {mp.annual_kg/1000:,.0f} t/yr")
    print(f"  Biodiesel cost       : $ {mp.production_cost_eur_per_kg:,.2f}/kg "
          f"= $ {cost_l:,.2f}/L  (NREL $0.42-0.97/L; MDSP < $1.85/L)")
    print(f"  Total investment     : $ {r.tea.total_investment/1e6:,.0f} M")
    print(f"  GWP (allocated)      : {mp.gwp_kg_co2eq_per_kg:,.2f} kg CO2-eq/kg biodiesel")
    print("  Products:")
    for p in r.products:
        print(f"    {p.name:22s} {p.annual_kg/1000:>9,.0f} t/yr  cost {p.production_cost_eur_per_kg:>7,.2f}  "
              f"alloc {p.allocation_share*100:>5.1f}%")


if __name__ == "__main__":
    main()
