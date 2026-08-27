"""Life-cycle assessment (cradle-to-gate).

Combines an :class:`~algametrix.inventory.Inventory` with
:class:`~algametrix.models.LCIAFactors` to produce impact indicators
per kilogram of dry biomass:

* GWP  - Global Warming Potential (kg CO2-eq)
* CED  - Cumulative Energy Demand (MJ)
* Water use (m3)
* Land use (m2*a)
* Marine and freshwater eutrophication (kg N-eq, kg P-eq)
* Acidification (kg SO2-eq)

The factors are aggregated cradle-to-gate values, one per input per category.
Where they came from, what boundary they assume, what is excluded from it, which
cut-off and allocation rules apply and which impact-assessment method each
indicator follows are declared in ``data/lcia.yaml`` and read by
:mod:`algametrix.lciamethod`. Coverage is not uniform across the categories, and
a flow with no factor for a category is reported in
:attr:`LCAResult.not_characterized` rather than counted as a zero burden.

For phototrophic systems the CO2 biologically fixed into the biomass can be
credited at the gate (``count_biogenic_uptake``). Whether that credit is
appropriate depends on the goal & scope of the study and on how the downstream
use of the biomass is accounted for, so it is left configurable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .inventory import Inventory
from .lciamethod import completeness
from .models import CarbonAccounting, CarbonSource, Scenario, WasteBurdenConvention


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
    # --- waste-derived feed ------------------------------------------------
    # <= 0, and non-zero only where the scenario declares system expansion.
    # Reported apart from the biogenic adjustment because the two credit
    # different things: one a carbon flow, the other a displaced process.
    avoided_treatment_kg_co2eq_per_kg: float = 0.0
    waste_burden_convention: str = ""    # empty when no waste feed is enabled
    # --- completeness ------------------------------------------------------
    # Flows this scenario declares for which no factor exists, keyed by impact
    # category ("acid", "water", ...). Those flows contribute nothing to those
    # categories, which understates them by an unknown amount; an empty dict
    # means every declared material, utility and solvent carried a factor.
    not_characterized: dict = field(default_factory=dict)

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
        # Purchased, not demanded: the fertiliser factors describe making
        # fertiliser, and nitrogen arriving in somebody's effluent had no
        # Haber-Bosch plant behind it. Without a waste feed the two are equal.
        "Nitrogen": inv.nitrogen_purchased_per_kg * f.nitrogen_gwp,
        "Phosphorus": inv.phosphorus_purchased_per_kg * f.phosphorus_gwp,
        "Substrate": inv.substrate_purchased_per_kg * f.substrate_gwp,
    }
    wf = scenario.waste_feed
    if inv.waste_feed_per_kg > 0:
        # What the receiving system does itself: transport, pre-treatment. Under
        # a strict cut-off with the stream at the fence line this is zero, and
        # the line simply does not appear.
        if wf.gwp_per_unit:
            gwp_contrib[wf.name or "Waste feed"] = inv.waste_feed_per_kg * wf.gwp_per_unit
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

    # --- avoided treatment, only where the scenario declares system expansion --
    # Kept out of the gross and given its own line, for the same reason the
    # biogenic credit is: it is not a burden this process causes but a burden
    # another one no longer does, and a reader has to be able to take it back off.
    avoided_gwp = 0.0
    if (inv.waste_feed_per_kg > 0
            and wf.convention == WasteBurdenConvention.AVOIDED_TREATMENT
            and wf.avoided_treatment_gwp_per_unit):
        avoided_gwp = -inv.waste_feed_per_kg * wf.avoided_treatment_gwp_per_unit
        gwp_contrib["Avoided treatment (system expansion)"] = avoided_gwp

    gwp = gwp_gross + adjustment + avoided_gwp

    # --- Cumulative Energy Demand ----------------------------------------
    ced = (
        inv.elec_kwh_per_kg * f.elec_ced
        + inv.heat_mj_per_kg * f.heat_ced
        + inv.nitrogen_purchased_per_kg * f.nitrogen_ced
        + inv.phosphorus_purchased_per_kg * f.phosphorus_ced
        + inv.substrate_purchased_per_kg * f.substrate_ced
        + inv.bicarbonate_supply_per_kg * f.bicarbonate_ced
    )
    ced += inv.waste_feed_per_kg * wf.ced_per_unit
    if (inv.waste_feed_per_kg > 0
            and wf.convention == WasteBurdenConvention.AVOIDED_TREATMENT):
        ced -= inv.waste_feed_per_kg * wf.avoided_treatment_ced_per_unit
    ced += sum(m.amount_per_kg * m.ced for m in scenario.materials)
    ced += sum(u.amount_per_kg * u.ced for u in scenario.utilities)
    if ext.enabled:
        ced += inv.solvent_net_per_kg * ext.solvent_ced

    # --- Water & land -----------------------------------------------------
    # Direct process water plus the water the electricity factor carries. No
    # other purchased input carries a water or a land factor unless the scenario
    # declares one on the material or utility itself, so both categories are
    # narrower than GWP and CED — see data/lcia.yaml.
    water = (
        inv.water_m3_per_kg
        + inv.elec_kwh_per_kg * f.elec_water
        + _declared(scenario.materials, "water")
        + _declared(scenario.utilities, "water")
    )
    land = (
        inv.land_m2a_per_kg
        + _declared(scenario.materials, "land")
        + _declared(scenario.utilities, "land")
    )

    # --- Eutrophication & acidification -----------------------------------
    solvent = inv.solvent_net_per_kg if scenario.extraction.enabled else 0.0
    # The direct term stays on everything emitted, surplus from the waste stream
    # included: nutrient the culture cannot take up reaches the water whatever
    # brought it there. Only the upstream-production term follows the purchase.
    marine_eutroph = (
        inv.nitrogen_emitted_per_kg * f.n_to_water_frac
        + inv.nitrogen_purchased_per_kg * f.nitrogen_eutroph_n
        + _declared(scenario.materials, "eutroph_n")
        + _declared(scenario.utilities, "eutroph_n")
    )
    fresh_eutroph = (
        inv.phosphorus_emitted_per_kg * f.p_to_water_frac
        + inv.phosphorus_purchased_per_kg * f.phosphorus_eutroph_p
        + inv.elec_kwh_per_kg * f.elec_eutroph_p
        + _declared(scenario.materials, "eutroph_p")
        + _declared(scenario.utilities, "eutroph_p")
    )
    acidification = (
        inv.elec_kwh_per_kg * f.elec_acid
        + inv.heat_mj_per_kg * f.heat_acid
        + inv.nitrogen_purchased_per_kg * f.nitrogen_acid
        + inv.phosphorus_purchased_per_kg * f.phosphorus_acid
        + inv.substrate_purchased_per_kg * f.substrate_acid
        + solvent * f.solvent_acid
        + _declared(scenario.materials, "acid")
        + _declared(scenario.utilities, "acid")
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

    gaps: dict[str, list[str]] = {}
    for gap in completeness(scenario):
        gaps.setdefault(gap.indicator, [])
        if gap.item not in gaps[gap.indicator]:
            gaps[gap.indicator].append(gap.item)

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
        avoided_treatment_kg_co2eq_per_kg=avoided_gwp,
        waste_burden_convention=(wf.convention.value if inv.waste_feed_per_kg > 0 else ""),
        not_characterized=gaps,
    )


def _declared(items, attr: str) -> float:
    """Sum ``amount x factor`` over the items that declare that factor.

    An item with no factor for a category adds nothing to it. That is not the
    same as adding zero, and the difference is reported: the names go into
    ``LCAResult.not_characterized`` instead of quietly reading as no burden.
    """
    return sum(item.amount_per_kg * getattr(item, attr) for item in items
               if getattr(item, attr, None))


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
