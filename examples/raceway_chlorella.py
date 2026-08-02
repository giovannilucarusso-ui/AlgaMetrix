"""Scripted example: Chlorella vulgaris in a 10-hectare open raceway pond.

Run from the repository root::

    python examples/raceway_chlorella.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable when running the script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.models import Scenario
from algametrix.scenario import run_scenario


def main() -> None:
    lib = load_library()

    system = lib.systems["Open raceway pond"]
    scenario = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=system,
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000,  # m2 of pond  (10 ha)
        materials=list(system.materials),
        utilities=list(system.utilities),
        product_price=system.product_price,  # seed selling price (EUR/kg)
    )

    r = run_scenario(scenario)

    print(f"Scenario: {scenario.organism.name} in {scenario.system.name}")
    print(f"  Pond area                : {scenario.scale:,.0f} m2")
    print(f"  Annual dry biomass       : {r.inventory.annual_biomass_kg / 1000:,.1f} t/yr")
    print()
    print("Inventory (per kg dry biomass)")
    print(f"  Electricity              : {r.inventory.elec_kwh_per_kg:6.2f} kWh")
    print(f"  Heat (drying)            : {r.inventory.heat_mj_per_kg:6.2f} MJ")
    print(f"  CO2 supplied             : {r.inventory.co2_supply_per_kg:6.2f} kg")
    print(f"  Nitrogen                 : {r.inventory.nitrogen_per_kg:6.3f} kg")
    print(f"  Phosphorus               : {r.inventory.phosphorus_per_kg:6.3f} kg")
    print(f"  Water                    : {r.inventory.water_m3_per_kg:6.2f} m3")
    print()
    print("Techno-economic")
    print(f"  Total investment         : EUR {r.tea.total_investment/1e6:8.2f} M")
    print(f"  Annual operating cost     : EUR {r.tea.annual_opex/1e6:8.2f} M/yr")
    print(f"  Production cost          : EUR {r.tea.production_cost_eur_per_kg:8.2f} /kg")
    print()
    print("Profitability")
    irr_txt = "n/a" if r.tea.irr is None else f"{r.tea.irr*100:8.1f} %"
    print(f"  Revenues                 : EUR {r.tea.revenues/1e6:8.2f} M/yr")
    print(f"  Net profit               : EUR {r.tea.net_profit/1e6:8.2f} M/yr")
    print(f"  NPV                      : EUR {r.tea.npv/1e6:8.2f} M")
    print(f"  IRR                      : {irr_txt}")
    print(f"  Payback time             : {r.tea.payback_years:8.1f} yr")
    print()
    print("Life-cycle assessment (per kg dry biomass)")
    print(f"  GWP                      : {r.lca.gwp_kg_co2eq_per_kg:8.2f} kg CO2-eq")
    print(f"  Cumulative energy demand : {r.lca.ced_mj_per_kg:8.2f} MJ")
    print(f"  Water use                : {r.lca.water_m3_per_kg:8.2f} m3")
    print(f"  Land use                 : {r.lca.land_m2a_per_kg:8.2f} m2*a")


if __name__ == "__main__":
    main()
