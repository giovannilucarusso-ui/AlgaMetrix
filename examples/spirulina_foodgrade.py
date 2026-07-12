"""Food-grade Spirulina (Arthrospira) powder in an open raceway pond.

An authoritative food/nutraceutical reference point. Instead of a proprietary
target, this scenario is checked against OPEN-LITERATURE benchmark ranges and
against indicative market prices — the transparency angle.

Spirulina is alkaliphilic and grows on dissolved sodium bicarbonate (NaHCO3),
not gaseous CO2, so this scenario uses the bicarbonate-fed raceway calibrated to
Padi et al. (2023), Algal Research 74:103190 (~5 kg NaHCO3/kg spirulina).

    python examples/spirulina_foodgrade.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dataclasses import replace

from microalgae_tea_lca.benchmarks import check_benchmarks, load_market_prices
from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Scenario
from microalgae_tea_lca.scenario import minimum_selling_price, run_scenario


def main() -> None:
    lib = load_library()
    scenario = Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"],
        system=lib.systems["Open raceway pond (Spirulina, NaHCO3)"],
        harvesting=lib.harvesting["Membrane filtration"],   # Spirulina: easy, low-energy harvest
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000.0,     # m2 pond (10 ha)
        product_price=15.0,  # food-grade retail (lower bound)
    )

    r = run_scenario(scenario)
    mepp = minimum_selling_price(scenario)
    print("Food-grade Spirulina powder (bicarbonate-fed raceway, greenhouse-heated)")
    print(f"  Annual powder        : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr")
    print(f"  Production cost      : $ {r.tea.production_cost_eur_per_kg:,.2f}/kg")
    print(f"  Break-even price MEPP : $ {mepp:,.2f}/kg" if mepp else "  Break-even price MEPP : n/a")
    print(f"  NaHCO3 supplied      : {r.inventory.bicarbonate_supply_per_kg:,.2f} kg/kg biomass")
    print(f"  GWP                  : {r.lca.gwp_kg_co2eq_per_kg:,.2f} kg CO2-eq/kg")
    print(f"  Water use            : {r.lca.water_m3_per_kg:,.2f} m3/kg")
    print(f"  NPV / payback        : $ {r.tea.npv/1e6:,.1f} M / {r.tea.payback_years:.1f} yr")

    print("\n  Open-literature benchmark check (per kg biomass):")
    for row in check_benchmarks(r):
        print(f"    {row.metric:16s} model {row.model:>8.2f} {row.unit:12s} "
              f"[{row.low:g}-{row.high:g}]  {row.status}")

    print("\n  Market context:")
    for p in load_market_prices():
        if "Spirulina" in p.product or "food" in p.product.lower():
            print(f"    {p.product}: {p.low:g}-{p.high:g} {p.unit}  ({p.source})")

    reproduce_padi_2023(lib)


def reproduce_padi_2023(lib) -> None:
    """Reproduce Padi et al. (2023) Scenario I (dried spirulina food product).

    Applies the paper's financial basis (20-yr straight-line depreciation, 1%
    maintenance, 0.6% insurance, civil-works installation factor, salt-based N/P
    prices, 26.5% tax) at the paper's ~1 t MA/d footprint (~11.6 ha).
    """
    eco = replace(
        lib.economics,
        depreciation_years=20.0,   # Padi: 20-yr linear equipment depreciation
        maintenance_frac=0.01,     # 1% of FCI
        insurance_frac=0.006,      # 0.6% of FCI
        installation_factor=1.5,   # civil-works ponds (not 2.5x process plant)
        tax_rate=0.265,            # Irish corporate tax
        nitrogen_price=4.8,        # effective, via KNO3 (0.67 EUR/kg / 0.139 N)
        phosphorus_price=8.0,      # effective, via K4O7P2 (1.50 EUR/kg / 0.188 P)
        labor_cost_per_year=500_000.0,
    )
    scenario = Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"],
        system=lib.systems["Open raceway pond (Spirulina, NaHCO3)"],
        harvesting=lib.harvesting["Vibrating screen filter"],   # the paper's VFS
        drying=lib.drying["Spray drying"],
        economics=eco,
        lcia=lib.lcia,
        scale=116_000.0,      # ~1 t MA/d footprint (11.6 ha)
        product_price=65.0,   # DSFP market price (Padi)
    )
    r = run_scenario(scenario)
    mepp = minimum_selling_price(scenario)
    print("\n  Padi et al. (2023) Scenario I reproduction (DSFP, ~1 t MA/d):")
    print(f"    Annual biomass     : {r.inventory.annual_biomass_kg/1000:,.0f} t/yr   (paper ~330)")
    print(f"    Production cost    : {r.tea.production_cost_eur_per_kg:,.2f} EUR/kg   (paper MEPP 13.2-17.3)")
    print(f"    Break-even MEPP    : {mepp:,.2f} EUR/kg   (paper MEPP 13.2-17.3)")
    print(f"    Total investment   : {r.tea.total_investment/1e6:,.1f} M EUR   (paper TCI ~16.8)")
    print(f"    NaHCO3 cost        : {r.inventory.bicarbonate_supply_per_kg*eco.bicarbonate_price:,.2f} EUR/kg   (paper ~1.38)")
    print(f"    GWP                : {r.lca.gwp_kg_co2eq_per_kg:,.2f} kg CO2-eq/kg   (Italian Spirulina LCA 15-20)")


if __name__ == "__main__":
    main()
