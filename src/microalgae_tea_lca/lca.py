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
from .models import CarbonAccounting, CarbonSource, Scenario


@dataclass
class LCAResult:
    """Environmental results per kg of dry biomass.

    ``gwp_kg_co2eq_per_kg`` is the **net** result under the scenario's declared
    biogenic-carbon convention. It is never reported on its own: the gross value
    before any biogenic adjustment, the adjustment itself and the convention that
    produced it are all carried here so a reader can undo the choice.
    """

    gwp_kg_co2eq_per_kg: float
    ced_mj_per_kg: float
    water_m3_per_kg: float
    land_m2a_per_kg: float
    gwp_breakdown: dict = field(default_factory=dict)  # kg CO2-eq / kg, by contributor
    impacts: dict = field(default_factory=dict)         # all impact categories per kg
    # --- biogenic-carbon accounting --------------------------------------
    gwp_gross_kg_co2eq_per_kg: float = 0.0     # before any biogenic adjustment
    biogenic_adjustment_kg_co2eq_per_kg: float = 0.0   # <= 0; net = gross + adjustment
    carbon_accounting_mode: str = CarbonAccounting.NO_BIOGENIC_CREDIT.value
    carbon_supply_gwp_kg_co2eq_per_kg: float = 0.0     # upstream burden of the C feed

    @property
    def gwp_net_kg_co2eq_per_kg(self) -> float:
        """Explicit alias: the net GWP under the declared convention."""
        return self.gwp_kg_co2eq_per_kg


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

    # --- gross GWP: everything before any biogenic-carbon adjustment ------
    gwp_gross = sum(gwp_contrib.values())
    carbon_supply_gwp = (
        gwp_contrib.get("CO2 supply", 0.0)
        + gwp_contrib.get("Bicarbonate (NaHCO3)", 0.0)
        + gwp_contrib.get("Substrate", 0.0)
    )

    # --- biogenic adjustment under the declared convention ----------------
    mode = _effective_carbon_mode(f)
    adjustment = _biogenic_adjustment(scenario, inv, f, mode)
    if adjustment:
        gwp_contrib["Biogenic CO2 uptake"] = adjustment

    gwp = gwp_gross + adjustment

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
        gwp_gross_kg_co2eq_per_kg=gwp_gross,
        biogenic_adjustment_kg_co2eq_per_kg=adjustment,
        carbon_accounting_mode=mode.value,
        carbon_supply_gwp_kg_co2eq_per_kg=carbon_supply_gwp,
    )


def _effective_carbon_mode(factors) -> CarbonAccounting:
    """The convention actually in force.

    ``count_biogenic_uptake=False`` is the historical master switch and always
    wins, so scenarios written before the modes existed keep their behaviour.
    """
    if not factors.count_biogenic_uptake:
        return CarbonAccounting.NO_BIOGENIC_CREDIT
    mode = factors.carbon_accounting
    return mode if isinstance(mode, CarbonAccounting) else CarbonAccounting(mode)


def _biogenic_adjustment(
    scenario: Scenario, inv: Inventory, factors, mode: CarbonAccounting
) -> float:
    """kg CO2-eq per kg product, <= 0. Added to the gross GWP to give the net.

    The quantity credited differs between modes on purpose:

    * ``SOURCE_SPECIFIC_CREDIT`` credits ``co2_fixed_per_kg`` - the CO2 fixed by
      the gross biomass cultivated - and only when the carbon was fed as CO2.
      This is the historical behaviour and is retained so published results
      remain reproducible.
    * ``TEMPORARY_STORAGE_CREDIT_AT_GATE`` credits ``biogenic_co2_in_product_per_kg``
      - the carbon that actually leaves the gate inside the product, whatever fed
      it. For a system with harvesting losses this is the smaller, and physically
      the correct, at-gate quantity.

    The two differ by the harvesting recovery; both quantities stay available on
    the inventory (``co2_fixed_per_kg`` and ``biogenic_co2_in_product_per_kg``),
    so the difference is explicit rather than hidden.
    """
    if mode is CarbonAccounting.NO_BIOGENIC_CREDIT:
        return 0.0
    if mode is CarbonAccounting.SOURCE_SPECIFIC_CREDIT:
        from_co2 = scenario.system.carbon_source == CarbonSource.CO2
        if from_co2 and inv.co2_fixed_per_kg > 0:
            return -inv.co2_fixed_per_kg
        return 0.0
    if mode is CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE:
        return -inv.biogenic_co2_in_product_per_kg
    if mode is CarbonAccounting.CUSTOM:
        frac = max(0.0, min(float(factors.custom_biogenic_credit_fraction), 1.0))
        return -inv.biogenic_co2_in_product_per_kg * frac
    return 0.0
