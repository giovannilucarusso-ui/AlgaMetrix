"""Biogenic-carbon accounting: the six quantities that must travel together.

A cradle-to-gate GWP for photosynthetic biomass is meaningless as a single
number. This module computes, for any scenario:

1. gross cradle-to-gate GWP, before any biogenic-carbon adjustment
2. biogenic carbon incorporated into the biomass that leaves the gate
3. carbon supplied to the culture and the resulting utilization efficiency
4. the upstream burden of supplying that carbon
5. the temporary-storage / uptake adjustment under the declared convention
6. net cradle-to-gate GWP

and does it for every convention, so a reader can see the whole sensitivity
rather than one chosen point.

The three feed routes are handled explicitly and separately:

*CO2-fed* - the supply burden (capture, purification, delivery) is separated
from the carbon physically incorporated, which is separated again from whether
that incorporation is credited.

*Bicarbonate-fed* - the earlier code credited nothing here and justified it as
"avoiding double counting". That is a conclusion, not a derivation. What is
actually true is narrower and is what this module reports: the NaHCO3 production
burden and the incorporated carbon are two different flows, and whether the
second is credited is a boundary convention. Under
``temporary_storage_credit_at_gate`` the carbon in the product is credited for a
bicarbonate-fed system exactly as for a CO2-fed one, and the reader can compare.

*Heterotrophic* - carbon arrives in the organic substrate. The substrate's
production burden is counted upstream; the fraction of substrate carbon that ends
up in the product is reported, and any downstream release of that carbon lies
outside the cradle-to-gate boundary.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from ..models import CarbonAccounting, CarbonSource, Scenario, TrophicMode
from ..scenario import run_scenario

#: The conventions reported side by side for every scenario.
REPORTED_MODES = (
    CarbonAccounting.NO_BIOGENIC_CREDIT,
    CarbonAccounting.SOURCE_SPECIFIC_CREDIT,
    CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE,
)


@dataclass
class CarbonReport:
    """Complete carbon picture for one scenario, per kg of product."""

    label: str
    trophic_mode: str
    carbon_feed: str                      # co2 | bicarbonate | organic_substrate
    gross_gwp: float
    carbon_supply_gwp: float
    biogenic_co2_in_product: float        # CO2-equivalent of carbon leaving the gate
    co2_fixed_gross_biomass: float        # CO2 fixed by the biomass cultivated
    inorganic_co2_supplied: float
    substrate_co2_supplied: float
    carbon_utilization: float | None      # incorporated / supplied, None if no C feed
    net_by_mode: dict[str, float] = field(default_factory=dict)
    adjustment_by_mode: dict[str, float] = field(default_factory=dict)
    declared_mode: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def net_declared(self) -> float:
        return self.net_by_mode[self.declared_mode]

    @property
    def net_no_credit(self) -> float:
        return self.net_by_mode[CarbonAccounting.NO_BIOGENIC_CREDIT.value]


def _feed_label(scenario: Scenario) -> str:
    if scenario.system.mode == TrophicMode.HETEROTROPHIC:
        return "organic_substrate"
    return ("bicarbonate" if scenario.system.carbon_source == CarbonSource.BICARBONATE
            else "co2")


def carbon_report(scenario: Scenario, label: str) -> CarbonReport:
    """Run ``scenario`` under every reported convention and assemble the picture."""
    base = run_scenario(scenario)
    inv = base.inventory
    feed = _feed_label(scenario)

    supplied = inv.inorganic_co2_supplied_per_kg + inv.substrate_co2_supplied_per_kg
    utilization = (inv.biogenic_co2_in_product_per_kg / supplied) if supplied > 0 else None

    report = CarbonReport(
        label=label,
        trophic_mode=scenario.system.mode.value,
        carbon_feed=feed,
        gross_gwp=base.lca.gwp_gross_kg_co2eq_per_kg,
        carbon_supply_gwp=base.lca.carbon_supply_gwp_kg_co2eq_per_kg,
        biogenic_co2_in_product=inv.biogenic_co2_in_product_per_kg,
        co2_fixed_gross_biomass=inv.co2_fixed_per_kg,
        inorganic_co2_supplied=inv.inorganic_co2_supplied_per_kg,
        substrate_co2_supplied=inv.substrate_co2_supplied_per_kg,
        carbon_utilization=utilization,
        declared_mode=base.lca.carbon_accounting_mode,
    )

    for mode in REPORTED_MODES:
        scn = deepcopy(scenario)
        scn.lcia.count_biogenic_uptake = True
        scn.lcia.carbon_accounting = mode
        res = run_scenario(scn)
        report.net_by_mode[mode.value] = res.lca.gwp_kg_co2eq_per_kg
        report.adjustment_by_mode[mode.value] = res.lca.biogenic_adjustment_kg_co2eq_per_kg

    if report.declared_mode not in report.net_by_mode:
        scn = deepcopy(scenario)
        res = run_scenario(scn)
        report.net_by_mode[report.declared_mode] = res.lca.gwp_kg_co2eq_per_kg
        report.adjustment_by_mode[report.declared_mode] = (
            res.lca.biogenic_adjustment_kg_co2eq_per_kg
        )

    # --- route-specific notes --------------------------------------------
    gross_credit = report.co2_fixed_gross_biomass
    at_gate = report.biogenic_co2_in_product
    if gross_credit > 0 and abs(gross_credit - at_gate) > 1e-9:
        report.notes.append(
            f"source_specific_credit credits {gross_credit:.3f} kg CO2-eq (fixed by the "
            f"gross biomass cultivated) but only {at_gate:.3f} kg CO2-eq of carbon leaves "
            f"the gate in the product; the difference is carbon in biomass lost at "
            f"harvesting ({(gross_credit - at_gate):.3f} kg CO2-eq)."
        )
    if feed == "bicarbonate":
        report.notes.append(
            "bicarbonate-fed: the NaHCO3 production burden "
            f"({report.carbon_supply_gwp:.3f} kg CO2-eq/kg) and the carbon incorporated "
            f"({at_gate:.3f} kg CO2-eq/kg) are separate flows. Crediting the second is a "
            "boundary convention, not an automatic double count; both conventions are "
            "reported above."
        )
    if feed == "organic_substrate":
        report.notes.append(
            "heterotrophic: carbon enters as organic substrate "
            f"({report.substrate_co2_supplied:.3f} kg CO2-eq/kg as CO2), its production "
            f"burden is counted upstream ({report.carbon_supply_gwp:.3f} kg CO2-eq/kg), "
            f"and {at_gate:.3f} kg CO2-eq/kg leaves the gate in the product. Downstream "
            "release of that carbon lies outside the cradle-to-gate boundary."
        )
    if report.net_declared < 0:
        report.notes.append(
            f"NET GWP IS NEGATIVE ({report.net_declared:.3f}) under the declared "
            f"convention while the gross value is {report.gross_gwp:.3f}. The sign is "
            "produced by the convention, not by the inventory."
        )
    return report


def format_carbon_report(r: CarbonReport, indent: str = "  ") -> str:
    """Text block for ``results/*.txt``."""
    lines = [
        f"{indent}{r.label}  [{r.trophic_mode}, carbon feed: {r.carbon_feed}]",
        f"{indent}  gross GWP (pre-adjustment)      : {r.gross_gwp:9.3f} kg CO2-eq/kg",
        f"{indent}  carbon-supply upstream burden   : {r.carbon_supply_gwp:9.3f} kg CO2-eq/kg",
        f"{indent}  inorganic C supplied (as CO2)   : {r.inorganic_co2_supplied:9.3f} kg/kg",
        f"{indent}  substrate C supplied (as CO2)   : {r.substrate_co2_supplied:9.3f} kg/kg",
        f"{indent}  biogenic C in product (as CO2)  : {r.biogenic_co2_in_product:9.3f} kg/kg",
        f"{indent}  C fixed by gross biomass        : {r.co2_fixed_gross_biomass:9.3f} kg/kg",
    ]
    if r.carbon_utilization is None:
        lines.append(f"{indent}  carbon utilization              :       n/a (no carbon feed)")
    else:
        lines.append(
            f"{indent}  carbon utilization (in/supplied): {r.carbon_utilization:9.3f}"
        )
    lines.append(f"{indent}  --- net GWP by convention ---")
    for mode, net in r.net_by_mode.items():
        adj = r.adjustment_by_mode.get(mode, 0.0)
        star = "  <- declared" if mode == r.declared_mode else ""
        lines.append(
            f"{indent}    {mode:36s} adj={adj:8.3f}  net={net:9.3f}{star}"
        )
    for n in r.notes:
        lines.append(f"{indent}  note: {n}")
    return "\n".join(lines)
