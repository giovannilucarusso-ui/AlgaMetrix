"""Life-cycle assessment (cradle-to-gate).

Combines an :class:`~microalgae_tea_lca.inventory.Inventory` with
:class:`~microalgae_tea_lca.models.LCIAFactors` to produce impact indicators
per kilogram of dry biomass:

* GWP  - Global Warming Potential (kg CO2-eq)
* CED  - Cumulative Energy Demand (MJ)
* Water use (m3)
* Land use (m2*a)

For phototrophic systems the CO2 biologically fixed into the biomass can be
credited at the gate (``count_biogenic_uptake``). Whether that credit is
appropriate depends on the goal & scope of the study and on how the downstream
use of the biomass is accounted for, so it is left configurable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .inventory import Inventory
from .models import CarbonSource, Scenario


@dataclass
class LCAResult:
    """Environmental results per kg of dry biomass."""

    gwp_kg_co2eq_per_kg: float
    ced_mj_per_kg: float
    water_m3_per_kg: float
    land_m2a_per_kg: float
    gwp_breakdown: dict = field(default_factory=dict)  # kg CO2-eq / kg, by contributor
    impacts: dict = field(default_factory=dict)         # all impact categories per kg


def run_lca(scenario: Scenario, inv: Inventory) -> LCAResult:
    """Compute the life-cycle impact result."""
    f = scenario.lcia

    # --- Global Warming Potential (contribution analysis) -----------------
    gwp_contrib = {
        "Electricity": inv.elec_kwh_per_kg * f.elec_gwp,
        "Heat (drying)": inv.heat_mj_per_kg * f.heat_gwp,
        "CO2 supply": inv.co2_supply_per_kg * f.co2_supply_gwp,
        "Bicarbonate (NaHCO3)": inv.bicarbonate_supply_per_kg * f.bicarbonate_gwp,
        "Nitrogen": inv.nitrogen_per_kg * f.nitrogen_gwp,
        "Phosphorus": inv.phosphorus_per_kg * f.phosphorus_gwp,
        "Substrate": inv.substrate_per_kg * f.substrate_gwp,
    }
    # Explicit media / chemicals and utilities carry their own factors.
    for m in scenario.materials:
        if m.gwp:
            gwp_contrib[m.name] = gwp_contrib.get(m.name, 0.0) + m.amount_per_kg * m.gwp
    for u in scenario.utilities:
        if u.gwp:
            gwp_contrib[u.name] = gwp_contrib.get(u.name, 0.0) + u.amount_per_kg * u.gwp

    ext = scenario.extraction
    if ext.enabled and inv.solvent_net_per_kg > 0 and ext.solvent_gwp:
        gwp_contrib[ext.solvent_name] = (
            gwp_contrib.get(ext.solvent_name, 0.0) + inv.solvent_net_per_kg * ext.solvent_gwp
        )

    # Biogenic uptake is only a real atmospheric drawdown when the carbon comes
    # from CO2. With a NaHCO3 feed the fixed carbon originates from a mined /
    # manufactured chemical (whose own production burden is counted above), so
    # crediting it here would double-count; hence the credit is CO2-only.
    carbon_from_co2 = scenario.system.carbon_source == CarbonSource.CO2
    if f.count_biogenic_uptake and inv.co2_fixed_per_kg > 0 and carbon_from_co2:
        gwp_contrib["Biogenic CO2 uptake"] = -inv.co2_fixed_per_kg

    gwp = sum(gwp_contrib.values())

    # --- Cumulative Energy Demand ----------------------------------------
    ced = (
        inv.elec_kwh_per_kg * f.elec_ced
        + inv.heat_mj_per_kg * f.heat_ced
        + inv.nitrogen_per_kg * f.nitrogen_ced
        + inv.phosphorus_per_kg * f.phosphorus_ced
        + inv.substrate_per_kg * f.substrate_ced
        + inv.bicarbonate_supply_per_kg * f.bicarbonate_ced
    )
    ced += sum(m.amount_per_kg * m.ced for m in scenario.materials)
    ced += sum(u.amount_per_kg * u.ced for u in scenario.utilities)
    if ext.enabled:
        ced += inv.solvent_net_per_kg * ext.solvent_ced

    # --- Water & land -----------------------------------------------------
    water = inv.water_m3_per_kg + inv.elec_kwh_per_kg * f.elec_water
    land = inv.land_m2a_per_kg

    # --- Eutrophication & acidification -----------------------------------
    solvent = inv.solvent_net_per_kg if scenario.extraction.enabled else 0.0
    marine_eutroph = (
        inv.nitrogen_emitted_per_kg * f.n_to_water_frac
        + inv.nitrogen_per_kg * f.nitrogen_eutroph_n
    )
    fresh_eutroph = (
        inv.phosphorus_emitted_per_kg * f.p_to_water_frac
        + inv.phosphorus_per_kg * f.phosphorus_eutroph_p
        + inv.elec_kwh_per_kg * f.elec_eutroph_p
    )
    acidification = (
        inv.elec_kwh_per_kg * f.elec_acid
        + inv.heat_mj_per_kg * f.heat_acid
        + inv.nitrogen_per_kg * f.nitrogen_acid
        + inv.phosphorus_per_kg * f.phosphorus_acid
        + inv.substrate_per_kg * f.substrate_acid
        + solvent * f.solvent_acid
    )

    impacts = {
        "GWP (kg CO₂-eq)": gwp,
        "Energy demand (MJ)": ced,
        "Water (m³)": water,
        "Land (m²·a)": land,
        "Marine eutrophication (kg N-eq)": marine_eutroph,
        "Freshwater eutrophication (kg P-eq)": fresh_eutroph,
        "Acidification (kg SO₂-eq)": acidification,
    }

    return LCAResult(
        gwp_kg_co2eq_per_kg=gwp,
        ced_mj_per_kg=ced,
        water_m3_per_kg=water,
        land_m2a_per_kg=land,
        gwp_breakdown={k: v for k, v in gwp_contrib.items() if abs(v) > 0},
        impacts=impacts,
    )
