"""Helpers to compare several scenarios side by side."""

from __future__ import annotations

from .scenario import Results

# Ordered KPIs used for side-by-side scenario comparison.
KPI_ORDER = [
    "Production cost (€/kg)",
    "NPV (€M)",
    "IRR (%)",
    "Payback (yr)",
    "Total investment (€M)",
    "Annual output (t/yr)",
    "GWP (kg CO₂-eq/kg)",
    "Energy demand (MJ/kg)",
    "Water (m³/kg)",
]


def scenario_kpis(results: Results) -> dict[str, float]:
    """Extract the comparable KPIs from a scenario's results.

    Cost and GWP refer to the main product when a biorefinery is defined,
    otherwise to 1 kg of dry biomass.
    """
    r = results
    if r.main_product:
        cost = r.main_product.production_cost_eur_per_kg
        gwp = r.main_product.gwp_kg_co2eq_per_kg
    else:
        cost = r.tea.production_cost_eur_per_kg
        gwp = r.lca.gwp_kg_co2eq_per_kg
    irr = r.tea.irr * 100 if r.tea.irr is not None else float("nan")
    return {
        "Production cost (€/kg)": cost,
        "NPV (€M)": r.tea.npv / 1e6,
        "IRR (%)": irr,
        "Payback (yr)": r.tea.payback_years,
        "Total investment (€M)": r.tea.total_investment / 1e6,
        "Annual output (t/yr)": r.inventory.annual_biomass_kg / 1000,
        "GWP (kg CO₂-eq/kg)": gwp,
        "Energy demand (MJ/kg)": r.lca.ced_mj_per_kg,
        "Water (m³/kg)": r.lca.water_m3_per_kg,
    }
