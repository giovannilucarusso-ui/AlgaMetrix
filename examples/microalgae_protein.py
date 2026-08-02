"""Microalgae single-cell protein (SCP) for food — Chlorella whole biomass.

Blue-food reference point: whole high-protein biomass as a sustainable protein
source. Checked against open single-cell-protein techno-economics: production cost
~5.5-6.1 EUR/kg (2028, declining to ~2 EUR/kg by 2050) and an areal protein
productivity of 22-44 t protein/ha/yr.

    python examples/microalgae_protein.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.benchmarks import check_benchmarks
from algametrix.library import load_library
from algametrix.models import Scenario
from algametrix.scenario import run_scenario


def main() -> None:
    lib = load_library()
    organism = lib.organisms["Chlorella vulgaris"]   # ~50% protein
    system = lib.systems["Open raceway pond"]
    scenario = Scenario(
        organism=organism,
        system=system,
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=200_000.0,     # m2 pond (20 ha)
        product_price=8.0,
    )

    r = run_scenario(scenario)
    biomass_kg = r.inventory.annual_biomass_kg
    protein_frac = organism.protein
    protein_kg = biomass_kg * protein_frac
    area_ha = scenario.scale / 10_000.0
    cost_kg = r.tea.production_cost_eur_per_kg

    print("Microalgae single-cell protein (Chlorella, open raceway)")
    print(f"  Protein content      : {protein_frac*100:.0f}% of dry weight")
    print(f"  Dry biomass          : {biomass_kg/1000:,.0f} t/yr")
    print(f"  Protein output       : {protein_kg/1000:,.0f} t protein/yr")
    print(f"  Protein productivity : {protein_kg/1000/area_ha:,.1f} t protein/ha/yr "
          f"(SCP literature 22-44)")
    print(f"  Biomass cost         : $ {cost_kg:,.2f}/kg  (SCP TEA 5.5-6.1 EUR/kg in 2028)")
    print(f"  Cost per kg protein  : $ {cost_kg/protein_frac:,.2f}/kg protein")
    print(f"  GWP                  : {r.lca.gwp_kg_co2eq_per_kg:,.2f} kg CO2-eq/kg biomass")

    print("\n  Open-literature benchmark check:")
    for row in check_benchmarks(r):
        print(f"    {row.metric:16s} model {row.model:>8.2f} {row.unit:12s} "
              f"[{row.low:g}-{row.high:g}]  {row.status}")


if __name__ == "__main__":
    main()
