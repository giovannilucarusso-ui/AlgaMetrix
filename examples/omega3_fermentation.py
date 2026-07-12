"""Omega-3 oils via heterotrophic microalgal fermentation (INTELLIGEN Case A).

Schizochytrium-type fermentation on glucose with N-limited lipid accumulation,
cell disruption, hexane extraction and refining to omega-3 oil, with a
protein-rich algae meal co-product. Batch process.

    python examples/omega3_fermentation.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Extraction, Product, Scenario
from microalgae_tea_lca.scenario import run_scenario
from microalgae_tea_lca.validation import compare, parse_reference_csv


def main() -> None:
    lib = load_library()

    # Fermentation: 100 glucose -> 35 biomass  =>  yield 0.35 kg/kg.
    system = replace(
        lib.systems["Stirred-tank fermenter (heterotrophic)"],
        substrate_yield=0.35,
        elec_kwh_per_kg=2.6,
        operating_days=330.0,
        materials=[],   # omega-3 media set explicitly below (per kg biomass)
        utilities=[],
    )

    extraction = Extraction(
        enabled=True, name="Hexane extraction + refining",
        disruption_elec_kwh_per_kg=1.2,     # 2-stage high-pressure homogenisation
        elec_kwh_per_kg=0.6,
        heat_mj_per_kg=1.5,                 # solvent recovery
        solvent_name="Hexane",
        solvent_kg_per_kg=3.0, solvent_recovery=0.999,  # hexane almost fully recycled
        solvent_price=1.5, solvent_gwp=0.9, solvent_ced=55.0,
        capex_per_kgyr=1.0, allocation="economic",
    )
    # Products (per the disruption stoichiometry: 40% PUFA, 10% protein of biomass).
    products = [
        Product("Omega-3 oil", "lipid", recovery=0.70, price=30.0, is_main=True),
        Product("Protein meal", "protein", recovery=0.80, price=0.15),   # $150/MT
        Product("Residual biomass", "residual", recovery=1.0, price=0.05),
    ]

    # Sterile fermentation is labour-intensive (SuperPro: ~$10M labour + $1.5M QC).
    economics = replace(lib.economics, labor_cost_per_year=11_500_000.0)

    scenario = Scenario(
        organism=lib.organisms["Schizochytrium sp."],   # lipid 0.55
        system=system,
        harvesting=lib.harvesting["Centrifugation only"],   # 0.95 recovery
        drying=lib.drying["No drying (wet paste)"],
        economics=economics,
        lcia=lib.lcia,
        scale=2000.0,   # m3 of fermenter train (for CAPEX sizing)
        extraction=extraction,
        products=products,
        batch_mode=True,
        batch_size_kg=25_000.0,     # ~25 MT dry cell mass per batch
        batch_cycle_time_h=24.0,    # ~1 day recipe cycle (staggered fermenters)
    )

    r = run_scenario(scenario)
    mp = r.main_product

    print("Omega-3 oils via heterotrophic fermentation (Case A)")
    print(f"  Batches/yr           : {r.inventory.batches_per_year:,.0f}")
    print(f"  Dry biomass          : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr")
    print(f"  Omega-3 oil output   : {mp.annual_kg/1000:,.0f} t/yr   (SuperPro ~2,963)")
    print(f"  Glucose use          : {r.inventory.substrate_per_kg:.2f} kg/kg biomass")
    print(f"  Electricity          : {r.inventory.elec_kwh_per_kg:.2f} kWh/kg biomass")
    print()
    print(f"  Total investment     : $ {r.tea.total_investment/1e6:,.0f} M   (SuperPro 85)")
    print(f"  Annual operating cost : $ {r.tea.annual_opex/1e6:,.0f} M/yr (SuperPro 49)")
    print(f"  Omega-3 oil cost     : $ {mp.production_cost_eur_per_kg:,.2f}/kg (SuperPro 16.57)")
    print(f"  Revenues             : $ {r.tea.revenues/1e6:,.0f} M/yr  (SuperPro 91)")
    print(f"  NPV / payback / ROI  : $ {r.tea.npv/1e6:,.0f} M / "
          f"{r.tea.payback_years:.1f} yr / {r.tea.roi*100:.0f}%")
    print()
    print("  Products:")
    for p in r.products:
        print(f"    {p.name:22s} {p.annual_kg/1000:>8,.0f} t/yr  "
              f"cost {p.production_cost_eur_per_kg:>7.2f}  alloc {p.allocation_share*100:>5.1f}%")

    ref = parse_reference_csv(Path(__file__).resolve().parents[1] / "data" / "reference_superpro_omega3.csv")
    print("\n  vs SuperPro omega-3 reference:")
    for row in compare(ref, r):
        if row.reference is None:
            continue
        pct = "-" if row.pct_diff is None else f"{row.pct_diff:+.0f}%"
        print(f"    {row.label:26s} model {row.model:>14,.1f}  ref {row.reference:>14,.1f}  "
              f"[{pct}] {row.status}")


if __name__ == "__main__":
    main()
