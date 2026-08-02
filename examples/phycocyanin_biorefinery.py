"""C-phycocyanin from Spirulina (Arthrospira) — high-value pigment biorefinery.

Aqueous extraction of the blue pigment C-phycocyanin from Spirulina, with a
protein-rich spent-biomass co-product. Reference range: production cost
EUR 283-544/kg, market EUR 170-280/kg (food/cosmetic grade); a C-PC content of
>=15% of the biomass is needed for a positive NPV.

    python examples/phycocyanin_biorefinery.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.models import Extraction, Product, Scenario
from algametrix.scenario import run_scenario


def main() -> None:
    lib = load_library()
    # Extraction + chromatographic purification to food/cosmetic grade (capital- and
    # labour-intensive; captured via a high downstream CAPEX and low purified yield).
    extraction = Extraction(
        enabled=True, name="Extraction + chromatographic purification",
        disruption_elec_kwh_per_kg=1.0, elec_kwh_per_kg=2.0, heat_mj_per_kg=3.0,
        solvent_name="Water/buffer", solvent_kg_per_kg=0.0, solvent_recovery=1.0,
        solvent_price=0.0, capex_per_kgyr=15.0, allocation="economic",
    )
    # Purified C-PC recovery ~6% of biomass; spent biomass sold as protein-rich meal.
    products = [
        Product("C-phycocyanin (food grade)", "custom", yield_override=0.06, price=250.0, is_main=True),
        Product("Spent biomass (protein)", "custom", yield_override=0.90, price=1.0),
    ]
    economics = replace(lib.economics, labor_cost_per_year=500_000.0)
    scenario = Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Membrane filtration"],
        drying=lib.drying["No drying (wet paste)"],
        economics=economics,
        lcia=lib.lcia,
        scale=8_000.0,     # m2 pond (0.8 ha) — commercial pigment plant
        extraction=extraction,
        products=products,
    )

    r = run_scenario(scenario)
    mp = r.main_product
    print("C-phycocyanin biorefinery (Spirulina)")
    print(f"  Dry biomass          : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr")
    print(f"  C-phycocyanin output : {mp.annual_kg/1000:,.1f} t/yr")
    print(f"  Total investment     : $ {r.tea.total_investment/1e6:,.1f} M")
    print(f"  C-PC production cost : $ {mp.production_cost_eur_per_kg:,.0f}/kg "
          f"(published EUR 283-544/kg; market EUR 170-280/kg)")
    print(f"  NPV / payback / ROI  : $ {r.tea.npv/1e6:,.1f} M / "
          f"{r.tea.payback_years:.1f} yr / {r.tea.roi*100:.0f}%")
    print("  Products:")
    for p in r.products:
        print(f"    {p.name:26s} {p.annual_kg/1000:>7,.1f} t/yr  cost {p.production_cost_eur_per_kg:>8,.1f}  "
              f"alloc {p.allocation_share*100:>5.1f}%")


if __name__ == "__main__":
    main()
