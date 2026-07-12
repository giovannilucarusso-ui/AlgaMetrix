"""Astaxanthin from Haematococcus pluvialis — high-value carotenoid biorefinery.

Two-stage phototrophic cultivation (green growth then red stress), cell disruption
of the thick-walled cysts and extraction of astaxanthin, with spent biomass as a
co-product. Reference: production cost ~$718/kg astaxanthin at 2.5% content
(Panis & Carreon 2016); dried-powder market $500-1500/kg; downstream ~60% of cost.

    python examples/astaxanthin_biorefinery.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Extraction, Product, Scenario
from microalgae_tea_lca.scenario import run_scenario


def main() -> None:
    lib = load_library()
    extraction = Extraction(
        enabled=True, name="Cyst disruption + astaxanthin extraction",
        disruption_elec_kwh_per_kg=3.0, elec_kwh_per_kg=2.0, heat_mj_per_kg=2.0,
        solvent_name="Ethanol/CO2", solvent_kg_per_kg=1.0, solvent_recovery=0.98,
        solvent_price=1.0, solvent_gwp=1.0, solvent_ced=30.0,
        capex_per_kgyr=10.0, allocation="economic",
    )
    products = [
        Product("Astaxanthin", "custom", yield_override=0.025, price=1000.0, is_main=True),
        Product("Spent biomass", "custom", yield_override=0.95, price=0.3),
    ]
    economics = replace(lib.economics, labor_cost_per_year=300_000.0)
    scenario = Scenario(
        organism=lib.organisms["Haematococcus pluvialis"],
        system=lib.systems["Flat-panel photobioreactor"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["No drying (wet paste)"],
        economics=economics,
        lcia=lib.lcia,
        scale=4_000.0,      # m2 PBR
        extraction=extraction,
        products=products,
    )

    r = run_scenario(scenario)
    mp = r.main_product
    print("Astaxanthin biorefinery (Haematococcus pluvialis)")
    print(f"  Dry biomass          : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr")
    print(f"  Astaxanthin output   : {mp.annual_kg:,.0f} kg/yr")
    print(f"  Total investment     : $ {r.tea.total_investment/1e6:,.1f} M")
    print(f"  Astaxanthin cost     : $ {mp.production_cost_eur_per_kg:,.0f}/kg "
          f"(published ~$718/kg; market $500-1500/kg powder)")
    print(f"  NPV / payback / ROI  : $ {r.tea.npv/1e6:,.1f} M / "
          f"{r.tea.payback_years:.1f} yr / {r.tea.roi*100:.0f}%")
    print("  Products:")
    for p in r.products:
        print(f"    {p.name:20s} {p.annual_kg:>9,.0f} kg/yr  cost {p.production_cost_eur_per_kg:>8,.1f}  "
              f"alloc {p.allocation_share*100:>5.1f}%")


if __name__ == "__main__":
    main()
