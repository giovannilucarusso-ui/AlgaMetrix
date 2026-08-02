"""Internal verification — mass-balance closure and model invariants.

*Verification* (is the maths self-consistent?) is distinct from *validation* (does it match
an external reference — see :mod:`validation`). This module checks that the conserved
quantities close and that structural invariants hold:

* **Carbon** — supplied inorganic carbon x utilization equals the carbon fixed into biomass
  (phototrophic), or substrate x yield equals the biomass grown (heterotrophic);
* **Nitrogen / Phosphorus** — supplied x uptake equals the nutrient in the biomass, and the
  supplied amount equals assimilated + emitted;
* **Product mass** — the downstream products never sum to more than the biomass fed;
* **Scale invariance** — per-kg flows do not depend on the absolute plant scale (continuous).

A correct model closes the balances to numerical tolerance; the residuals are reportable as
the paper's Verification section.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .inventory import CO2_PER_C, MIN_CARBON_UTILIZATION, NAHCO3_PER_C, build_inventory
from .models import CarbonSource, Scenario, TrophicMode

TOL = 1e-9


@dataclass
class BalanceCheck:
    """An equality that a conserved quantity must satisfy (inflow == outflow)."""

    name: str
    inflow: float
    outflow: float

    @property
    def residual(self) -> float:
        denom = max(abs(self.inflow), abs(self.outflow), 1e-12)
        return abs(self.inflow - self.outflow) / denom

    @property
    def closes(self) -> bool:
        return self.residual < TOL


@dataclass
class InvariantCheck:
    """A boolean structural invariant (not an equality residual)."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    balances: list[BalanceCheck] = field(default_factory=list)
    invariants: list[InvariantCheck] = field(default_factory=list)

    @property
    def max_residual(self) -> float:
        return max((c.residual for c in self.balances), default=0.0)

    @property
    def all_pass(self) -> bool:
        return all(c.closes for c in self.balances) and all(i.passed for i in self.invariants)


def verify(scenario: Scenario) -> VerificationReport:
    """Run all balance-closure and invariant checks for ``scenario``."""
    inv = build_inventory(scenario)
    org, sys = scenario.organism, scenario.system
    recovery = min(max(scenario.harvesting.recovery, 1e-6), 1.0)
    gpp = 1.0 / recovery                       # gross biomass per kg product
    uptake = min(max(sys.nutrient_uptake, 1e-6), 1.0)

    balances: list[BalanceCheck] = []

    # --- carbon --------------------------------------------------------------
    if sys.mode == TrophicMode.PHOTOTROPHIC:
        util = min(max(sys.co2_utilization, MIN_CARBON_UTILIZATION), 1.0)
        balances.append(BalanceCheck(
            "Carbon: fixed == biomass C",
            inv.co2_fixed_per_kg / CO2_PER_C, org.carbon * gpp))
        if sys.carbon_source == CarbonSource.BICARBONATE:
            supplied_as_co2 = inv.bicarbonate_supply_per_kg * util * (CO2_PER_C / NAHCO3_PER_C)
        else:
            supplied_as_co2 = inv.co2_supply_per_kg * util
        balances.append(BalanceCheck(
            "Carbon: supplied x utilization == fixed",
            supplied_as_co2, inv.co2_fixed_per_kg))
    else:  # heterotrophic: carbon from substrate
        yield_ = max(sys.substrate_yield, 1e-6)
        balances.append(BalanceCheck(
            "Carbon: substrate x yield == biomass",
            inv.substrate_per_kg * yield_, gpp))

    # --- nitrogen & phosphorus ----------------------------------------------
    balances.append(BalanceCheck(
        "Nitrogen: supplied x uptake == biomass N",
        inv.nitrogen_per_kg * uptake, org.nitrogen * gpp))
    balances.append(BalanceCheck(
        "Nitrogen: supplied == assimilated + emitted",
        inv.nitrogen_per_kg, inv.nitrogen_per_kg * uptake + inv.nitrogen_emitted_per_kg))
    balances.append(BalanceCheck(
        "Phosphorus: supplied x uptake == biomass P",
        inv.phosphorus_per_kg * uptake, org.phosphorus * gpp))
    balances.append(BalanceCheck(
        "Phosphorus: supplied == assimilated + emitted",
        inv.phosphorus_per_kg, inv.phosphorus_per_kg * uptake + inv.phosphorus_emitted_per_kg))

    invariants: list[InvariantCheck] = []

    # --- downstream product mass never exceeds the biomass fed ---------------
    if scenario.products:
        from .products import product_masses
        masses = product_masses(scenario, inv)
        total = sum(masses.values())
        biomass = inv.annual_biomass_kg
        invariants.append(InvariantCheck(
            "Product mass <= biomass fed",
            total <= biomass * (1.0 + 1e-9),
            f"{total:.1f} / {biomass:.1f} kg/yr"))

    # --- per-kg intensities are invariant to absolute plant scale (continuous) ---
    if not scenario.batch_mode:
        inv2 = build_inventory(replace(scenario, scale=scenario.scale * 2.0))
        fields = ("elec_kwh_per_kg", "co2_supply_per_kg", "bicarbonate_supply_per_kg",
                  "nitrogen_per_kg", "phosphorus_per_kg", "water_m3_per_kg", "substrate_per_kg")
        ok = all(
            abs(getattr(inv, f) - getattr(inv2, f)) <= TOL * max(abs(getattr(inv, f)), 1e-12)
            for f in fields
        )
        invariants.append(InvariantCheck(
            "Per-kg intensities scale-invariant (2x scale)", ok))

    return VerificationReport(balances=balances, invariants=invariants)


def format_report(scenario_name: str, report: VerificationReport) -> str:
    """Human-readable verification report (for the reproduce script / paper appendix)."""
    lines = [f"Verification - {scenario_name}: "
             f"{'PASS' if report.all_pass else 'FAIL'} (max residual {report.max_residual:.1e})"]
    for c in report.balances:
        lines.append(f"    [{'ok' if c.closes else 'XX'}] {c.name:44s} residual {c.residual:.1e}")
    for i in report.invariants:
        lines.append(f"    [{'ok' if i.passed else 'XX'}] {i.name:44s} {i.detail}")
    return "\n".join(lines)
