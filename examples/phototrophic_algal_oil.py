"""Phototrophic algal-oil biorefinery — SuperPro EER (Case 2), best-effort calibration.

Large open-pond plant -> harvesting -> hexane extraction -> algal oil, with a
protein co-product. This is the hardest case for a lumped model: it is biofuel-scale
and the real plant recovers energy via anaerobic digestion + a steam turbine
(a ~$16M/yr credit) which this model does not represent, so expect a rougher fit
than the omega-3 or powder cases.

    python examples/phototrophic_algal_oil.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Extraction, Material, Product, Scenario
from microalgae_tea_lca.scenario import run_scenario
from microalgae_tea_lca.validation import compare, parse_reference_csv


def main() -> None:
    lib = load_library()
    # Biofuel-scale open ponds: cheap per m2; downstream capex spread over a huge output.
    system = replace(
        lib.systems["Open raceway pond"],
        capex_per_unit=2.0,        # EUR/m2 at biofuel scale
        water_m3_per_kg=0.08,
        elec_kwh_per_kg=0.15,      # low-energy paddlewheel at scale
    )
    economics = replace(
        lib.economics,
        labor_cost_per_year=5_500_000.0,
        harvest_capex_per_kgyr=0.05,
        drying_capex_per_kgyr=0.0,
        nitrogen_price=0.9,
        water_price=1.0,
        co2_price=0.0,             # flue-gas CO2 taken as free
        electricity_price=0.10,    # SuperPro $0.10/kWh
        land_price=0.5,            # cheap land at biofuel scale
        overhead_frac=0.05,
    )
    extraction = Extraction(
        enabled=True, name="Hexane extraction",
        disruption_elec_kwh_per_kg=0.1, elec_kwh_per_kg=0.1, heat_mj_per_kg=0.5,
        solvent_name="Hexane", solvent_kg_per_kg=2.0, solvent_recovery=0.995,
        solvent_price=2.0, solvent_gwp=0.9, solvent_ced=55.0,
        capex_per_kgyr=0.02, allocation="economic",
    )
    products = [
        Product("Algal oil", "lipid", recovery=0.90, price=1.80, is_main=True),
        Product("Protein for feed", "protein", recovery=0.75, price=0.181),   # $181/MT
        Product("Residual biomass", "residual", recovery=1.0, price=0.05),
    ]
    scenario = Scenario(
        organism=lib.organisms["Nannochloropsis sp."],   # lipid 0.35
        system=system,
        harvesting=lib.harvesting["Membrane filtration"],   # low-energy dewatering
        drying=lib.drying["No drying (wet paste)"],
        economics=economics,
        lcia=lib.lcia,
        scale=35_000_000.0,   # m2 of pond (~3,500 ha)
        extraction=extraction,
        products=products,
        materials=[Material("Flocculant", amount_per_kg=0.005, price=1.0, gwp=1.5, ced=25.0)],
        credits_per_year=16_000_000.0,   # anaerobic-digestion energy recovery credit
    )

    r = run_scenario(scenario)
    mp = r.main_product
    print("Phototrophic algal-oil biorefinery (Case 2, best-effort)")
    print(f"  Dry biomass          : {r.inventory.annual_biomass_kg/1e6:,.2f} Mt/yr")
    print(f"  Algal oil output     : {mp.annual_kg/1000:,.0f} t/yr  (SuperPro ~65,487)")
    print(f"  Total investment     : $ {r.tea.total_investment/1e6:,.0f} M  (SuperPro 306)")
    print(f"  Annual operating cost : $ {r.tea.annual_opex/1e6:,.0f} M/yr (SuperPro 111)")
    print(f"  Oil production cost  : $ {mp.production_cost_eur_per_kg:,.2f}/kg (SuperPro 1.70)")
    print("\n  vs SuperPro reference:")
    ref = parse_reference_csv(Path(__file__).resolve().parents[1] / "data" / "reference_superpro_phototrophic.csv")
    for row in compare(ref, r):
        if row.reference is None:
            continue
        pct = "-" if row.pct_diff is None else f"{row.pct_diff:+.0f}%"
        print(f"    {row.label:26s} model {row.model:>16,.1f}  ref {row.reference:>16,.1f}  [{pct}] {row.status}")


if __name__ == "__main__":
    main()
