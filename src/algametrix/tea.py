"""Techno-economic analysis (SuperPro-Designer-aligned).

Combines an :class:`~algametrix.inventory.Inventory` with the
:class:`~algametrix.models.Economics` assumptions plus any explicit
:class:`~algametrix.models.Material` / :class:`Utility` line items to produce:

* a capital structure  — equipment -> installed -> DFC -> total investment
  (direct fixed capital + working capital + start-up), and
* an annual operating cost (AOC) split into raw materials, utilities, labour and
  facility-dependent cost (straight-line depreciation + maintenance + insurance), and
* the minimum biomass production cost (EUR/kg), and
* a profitability analysis — revenues, gross/net profit, ROI, payback, NPV, IRR.

The category structure mirrors a SuperPro Economic Evaluation Report so results
can be validated against it (see :mod:`algametrix.validation`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .inventory import Inventory
from .models import Scenario, WasteBurdenConvention


def capital_recovery_factor(rate: float, lifetime: float) -> float:
    """Annualisation factor ``i(1+i)^n / ((1+i)^n - 1)`` (straight-line if i≈0)."""
    if lifetime <= 0:
        raise ValueError("lifetime must be > 0")
    if abs(rate) < 1e-9:
        return 1.0 / lifetime
    f = (1.0 + rate) ** lifetime
    return rate * f / (f - 1.0)


def npv(rate: float, cash_flows: list[float]) -> float:
    """Net present value of ``cash_flows`` (index 0 = now) at ``rate``."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))


def irr(cash_flows: list[float]) -> float | None:
    """Internal rate of return by bisection; ``None`` if it does not exist in range."""
    lo, hi = -0.9, 10.0
    f_lo, f_hi = npv(lo, cash_flows), npv(hi, cash_flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = npv(mid, cash_flows)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


@dataclass
class TEAResult:
    """Economic and profitability results for a scenario."""

    # capital
    equipment_cost: float
    dfc: float                              # direct fixed capital
    working_capital: float
    startup_cost: float
    total_investment: float
    # operating
    annual_opex: float                      # AOC
    depreciation: float
    facility_dependent: float
    raw_materials_cost: float
    utilities_cost: float
    production_cost_eur_per_kg: float       # AOC / production
    net_production_cost_eur_per_kg: float   # (AOC - co-product revenue) / production
    # profitability
    revenues: float
    gross_profit: float
    taxes: float
    net_profit: float                       # after tax
    annual_cash_flow: float                 # after tax + depreciation add-back
    roi: float
    payback_years: float
    npv: float
    irr: float | None
    # EUR/yr of conventional treatment this plant displaces, >= 0 and non-zero
    # only where the scenario declares system expansion. Deliberately outside
    # ``annual_opex``: no money changes hands for it. It lowers the net
    # production cost and the profit, and is reported here so the choice can be
    # undone - the economic counterpart of the LCA's avoided-treatment line.
    avoided_treatment_credit: float = 0.0
    capex_breakdown: dict = field(default_factory=dict)
    opex_breakdown: dict = field(default_factory=dict)
    opex_categories: dict = field(default_factory=dict)

    @property
    def total_capex(self) -> float:
        """Backward-compatible alias for the total investment."""
        return self.total_investment


def run_tea(scenario: Scenario, inv: Inventory) -> TEAResult:
    eco = scenario.economics
    sys = scenario.system
    annual_kg = inv.annual_biomass_kg

    # ---- CAPITAL --------------------------------------------------------
    cultivation_equip = scenario.scale * sys.capex_per_unit
    harvest_equip = eco.harvest_capex_per_kgyr * annual_kg
    drying_equip = eco.drying_capex_per_kgyr * annual_kg if scenario.drying.enabled else 0.0
    extraction_equip = (
        scenario.extraction.capex_per_kgyr * annual_kg if scenario.extraction.enabled else 0.0
    )
    equipment = cultivation_equip + harvest_equip + drying_equip + extraction_equip

    installed = equipment * eco.installation_factor
    indirect = installed * eco.indirect_factor
    land_cost = scenario.scale * sys.land_m2_per_unit * eco.land_price
    dfc = installed + indirect + land_cost

    working_capital = eco.working_capital_frac * dfc
    startup_cost = eco.startup_frac * dfc
    total_investment = dfc + working_capital + startup_cost

    capex_breakdown = {
        "Cultivation equipment": cultivation_equip * eco.installation_factor,
        "Harvesting equipment": harvest_equip * eco.installation_factor,
        "Drying equipment": drying_equip * eco.installation_factor,
        "Extraction equipment": extraction_equip * eco.installation_factor,
        "Indirect (eng. + contingency)": indirect,
        "Land": land_cost,
        "Working capital": working_capital,
        "Start-up": startup_cost,
    }

    # ---- OPERATING COST -------------------------------------------------
    # Raw materials: physics-derived flows + explicit media / chemicals.
    # Nutrients and substrate are priced on what is *bought*: a waste-derived
    # feed does not make the culture need less nitrogen, it makes the plant buy
    # less of it. With no waste feed the purchased quantity equals the demand
    # and these lines are what they always were.
    derived_materials = {
        "CO2": inv.co2_supply_per_kg * eco.co2_price,
        "Bicarbonate (NaHCO3)": inv.bicarbonate_supply_per_kg * eco.bicarbonate_price,
        "Nitrogen": inv.nitrogen_purchased_per_kg * eco.nitrogen_price,
        "Phosphorus": inv.phosphorus_purchased_per_kg * eco.phosphorus_price,
        "Water": inv.water_m3_per_kg * eco.water_price,
        "Substrate": inv.substrate_purchased_per_kg * eco.substrate_price,
        "Solvent": inv.solvent_net_per_kg * scenario.extraction.solvent_price,
    }
    if inv.waste_feed_per_kg > 0:
        # Its own line, and it may be negative: a plant accepting municipal
        # effluent is paid a gate fee. Kept in raw materials rather than netted
        # against the nutrient lines, so the reader sees both the fertiliser not
        # bought and the money the stream brings or costs.
        wf = scenario.waste_feed
        derived_materials[wf.name or "Waste feed"] = (
            inv.waste_feed_per_kg * wf.price_per_unit)
    extra_materials = {m.name: m.amount_per_kg * m.price for m in scenario.materials}
    material_unit_costs = {**derived_materials, **extra_materials}  # EUR/kg product
    raw_materials_cost = sum(material_unit_costs.values()) * annual_kg

    # Utilities: electricity + drying heat + explicit utilities.
    derived_utilities = {
        "Electricity": inv.elec_kwh_per_kg * eco.electricity_price,
        "Heat (drying)": inv.heat_mj_per_kg * eco.heat_price,
    }
    extra_utilities = {u.name: u.amount_per_kg * u.price for u in scenario.utilities}
    utility_unit_costs = {**derived_utilities, **extra_utilities}
    utilities_cost = sum(utility_unit_costs.values()) * annual_kg

    labour = eco.labor_cost_per_year
    depreciation = dfc / eco.depreciation_years if eco.depreciation_years > 0 else 0.0
    facility_dependent = depreciation + dfc * (eco.maintenance_frac + eco.insurance_frac)
    overhead = (raw_materials_cost + utilities_cost + labour) * eco.overhead_frac
    other_opex = scenario.other_opex_per_year

    annual_opex = (raw_materials_cost + utilities_cost + labour
                   + facility_dependent + overhead + other_opex)

    # Itemised breakdown (sums to AOC) and grouped categories.
    opex_breakdown = {
        **{k: v * annual_kg for k, v in utility_unit_costs.items()},
        **{k: v * annual_kg for k, v in material_unit_costs.items()},
        "Labour": labour,
        "Facility-dependent": facility_dependent,
        "Overhead": overhead,
        "Other operating": other_opex,
    }
    opex_categories = {
        "Raw materials": raw_materials_cost,
        "Utilities": utilities_cost,
        "Labour": labour,
        "Facility-dependent": facility_dependent,
        "Overhead": overhead,
        "Other operating": other_opex,
    }

    production_cost = annual_opex / annual_kg if annual_kg > 0 else float("inf")

    # Revenues: from the product list if defined, else whole-biomass selling price.
    # ``coproduct_revenue_per_year`` is money from by-products that are *not* in
    # the product list - sold residue, spent media, recovered heat - so it is
    # added in both modes. Dropping it whenever a product list existed made the
    # field silently inert in exactly the cases where a biorefinery is most
    # likely to have one.
    if scenario.products:
        from .products import main_product, product_masses

        masses = product_masses(scenario, inv)
        revenues = (sum(masses[p.name] * p.price for p in scenario.products)
                    + scenario.coproduct_revenue_per_year)
        mp = main_product(scenario)
        main_revenue = masses[mp.name] * mp.price if mp else 0.0
        credits = revenues - main_revenue  # everything but the main product
    else:
        revenues = scenario.product_price * annual_kg + scenario.coproduct_revenue_per_year
        credits = scenario.coproduct_revenue_per_year

    # The treatment this plant performs instead of somebody else, where the
    # scenario declares system expansion. It is deliberately NOT in the annual
    # operating cost: no money changes hands for it, and a production cost that
    # quietly nets off a service the plant was never paid for is not a
    # production cost. It lowers the net cost and the profit, on its own line,
    # exactly where the co-product credits already sit - and under the same
    # convention that governs the LCA credit, so the two analyses cannot end up
    # describing different systems.
    wf = scenario.waste_feed
    avoided_treatment_credit = 0.0
    if (inv.waste_feed_per_kg > 0
            and wf.convention == WasteBurdenConvention.AVOIDED_TREATMENT):
        avoided_treatment_credit = (
            inv.waste_feed_per_kg * wf.avoided_treatment_cost_per_unit * annual_kg)

    # Energy/heat-recovery and waste-valorisation savings lower the net operating cost.
    credits += scenario.credits_per_year + avoided_treatment_credit
    net_opex = annual_opex - credits
    net_production_cost = net_opex / annual_kg if annual_kg > 0 else float("inf")

    # ---- PROFITABILITY --------------------------------------------------
    gross_profit = (revenues - annual_opex + scenario.credits_per_year
                    + avoided_treatment_credit)
    taxes = eco.tax_rate * max(gross_profit, 0.0)
    net_profit = gross_profit - taxes
    annual_cash_flow = net_profit + depreciation  # add back non-cash depreciation

    roi = net_profit / total_investment if total_investment > 0 else 0.0
    payback = total_investment / annual_cash_flow if annual_cash_flow > 0 else float("inf")

    n = int(round(eco.plant_lifetime))
    cash_flows = [-total_investment] + [annual_cash_flow] * n
    cash_flows[-1] += working_capital  # recover working capital at end of life
    npv_value = npv(eco.discount_rate, cash_flows)
    irr_value = irr(cash_flows)

    return TEAResult(
        equipment_cost=equipment,
        dfc=dfc,
        working_capital=working_capital,
        startup_cost=startup_cost,
        total_investment=total_investment,
        annual_opex=annual_opex,
        depreciation=depreciation,
        facility_dependent=facility_dependent,
        raw_materials_cost=raw_materials_cost,
        utilities_cost=utilities_cost,
        production_cost_eur_per_kg=production_cost,
        net_production_cost_eur_per_kg=net_production_cost,
        avoided_treatment_credit=avoided_treatment_credit,
        revenues=revenues,
        gross_profit=gross_profit,
        taxes=taxes,
        net_profit=net_profit,
        annual_cash_flow=annual_cash_flow,
        roi=roi,
        payback_years=payback,
        npv=npv_value,
        irr=irr_value,
        capex_breakdown={k: v for k, v in capex_breakdown.items() if v},
        opex_breakdown={k: v for k, v in opex_breakdown.items() if v},
        opex_categories={k: v for k, v in opex_categories.items() if v},
    )
