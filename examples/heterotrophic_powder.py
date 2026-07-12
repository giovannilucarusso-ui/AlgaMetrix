"""Heterotrophic microalgae powder — SuperPro "standard cultivation" (Case 1).

Whole-biomass product (spray-dried powder), no fractionation. Calibrated to the
SuperPro reference: ~285 t/yr, ~$9.4M investment, ~$16.5/kg.

    python examples/heterotrophic_powder.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Scenario
from microalgae_tea_lca.scenario import run_scenario
from microalgae_tea_lca.validation import compare, parse_reference_csv


def main() -> None:
    lib = load_library()
    # capex_per_unit represents the whole sterile fermenter train (seed + staggered
    # production units + media prep/sterilisers), not a single 150 m3 vessel.
    system = replace(
        lib.systems["Stirred-tank fermenter (heterotrophic)"],
        capex_per_unit=10_000.0,
    )
    economics = replace(
        lib.economics,
        labor_cost_per_year=743_000.0,   # SuperPro labour
        substrate_price=0.65,            # glucose $0.65/kg
    )
    scenario = Scenario(
        organism=lib.organisms["Schizochytrium sp."],
        system=system,
        harvesting=lib.harvesting["Settling + centrifugation"],   # lower-energy dewatering
        drying=lib.drying["Spray drying"],
        economics=economics,
        lcia=lib.lcia,
        scale=150.0,        # m3 main fermenter working volume
        materials=list(system.materials),
        utilities=list(system.utilities),
        product_price=20.0,  # powder selling price
    )

    r = run_scenario(scenario)
    print("Heterotrophic microalgae powder (Case 1)")
    print(f"  Annual powder        : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr  (SuperPro ~285)")
    print(f"  Total investment     : $ {r.tea.total_investment/1e6:,.1f} M  (SuperPro 9.4)")
    print(f"  Annual operating cost : $ {r.tea.annual_opex/1e6:,.1f} M/yr (SuperPro 4.7)")
    print(f"  Production cost      : $ {r.tea.production_cost_eur_per_kg:,.2f}/kg (SuperPro 16.46)")
    print(f"  Electricity          : {r.inventory.elec_kwh_per_kg:.2f} kWh/kg (SuperPro 3.83)")
    print(f"  Glucose              : {r.inventory.substrate_per_kg:.2f} kg/kg (SuperPro 3.0)")
    print("\n  vs SuperPro reference:")
    ref = parse_reference_csv(Path(__file__).resolve().parents[1] / "data" / "reference_superpro_heterotrophic.csv")
    for row in compare(ref, r):
        if row.reference is None:
            continue
        pct = "-" if row.pct_diff is None else f"{row.pct_diff:+.0f}%"
        print(f"    {row.label:26s} model {row.model:>14,.1f}  ref {row.reference:>14,.1f}  [{pct}] {row.status}")


if __name__ == "__main__":
    main()
