"""Internal verification — construction identities and physical admissibility.

*Verification* (is the maths self-consistent?) is distinct from *validation* (does it match
an external reference — see :mod:`validation`). This module reports two families of check
that answer different questions and must not be presented as one.

**Construction identities** (:class:`IdentityCheck`). Each restates a field of the inventory
as a closed form of the scenario, written here independently of :mod:`inventory`, and
compares the two. They close at machine precision *by construction*: ``build_inventory``
derives the nitrogen supply as ``org.nitrogen x gpp / uptake``, so ``supply x uptake ==
org.nitrogen x gpp`` cannot fail for any parameter values. What they can catch is a change to
:mod:`inventory` that is not mirrored here — they are specification tests, and their tiny
residuals are evidence that the implementation matches its specification, **not** that a
conservation law holds. They were previously named as carbon, nitrogen and phosphorus
"balances", which claimed more than they test.

**Physical admissibility** (:class:`InvariantCheck`). Inequalities that a scenario can
genuinely violate:

* the elemental composition cannot exceed the dry mass it is a fraction of;
* recovery, nutrient uptake and carbon utilization are fractions in (0, 1];
* a heterotroph cannot put more carbon into biomass than its substrate supplied — the
  quantity the construction identity above does *not* test, since it never mentions carbon;
* the downstream products never sum to more than the biomass fed;
* per-kg flows do not depend on the absolute plant scale (continuous mode).

These are the checks that can fail, so they are the ones that carry evidential weight. They
are booleans, not residuals, and are reported as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .inventory import CO2_PER_C, MIN_CARBON_UTILIZATION, NAHCO3_PER_C, build_inventory
from .models import CarbonSource, Scenario, TrophicMode

TOL = 1e-9


@dataclass
class IdentityCheck:
    """An inventory field against a closed form of the scenario, written here.

    Not a conservation law. See the module docstring: the equality holds by
    construction, and the residual measures floating-point round-off plus any
    drift between :mod:`inventory` and this restatement of it.
    """

    name: str
    lhs: float
    rhs: float

    @property
    def residual(self) -> float:
        denom = max(abs(self.lhs), abs(self.rhs), 1e-12)
        return abs(self.lhs - self.rhs) / denom

    @property
    def closes(self) -> bool:
        return self.residual < TOL

    # Retained so existing readers of the older field names keep working.
    @property
    def inflow(self) -> float:
        return self.lhs

    @property
    def outflow(self) -> float:
        return self.rhs


#: Previous name of :class:`IdentityCheck`, kept as an alias so that external
#: code importing it does not break on the rename.
BalanceCheck = IdentityCheck


@dataclass
class InvariantCheck:
    """A boolean structural invariant (not an equality residual)."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    #: Construction identities. ``balances`` is retained as the attribute name
    #: because it is what the figure and report code already read; what it holds
    #: is documented at the top of this module and is not a set of balances.
    balances: list[IdentityCheck] = field(default_factory=list)
    invariants: list[InvariantCheck] = field(default_factory=list)

    @property
    def identities(self) -> list[IdentityCheck]:
        """Preferred name for :attr:`balances`."""
        return self.balances

    @property
    def max_residual(self) -> float:
        return max((c.residual for c in self.balances), default=0.0)

    @property
    def admissibility(self) -> list[InvariantCheck]:
        """The checks that can actually fail."""
        return self.invariants

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

    balances: list[IdentityCheck] = []

    # --- carbon --------------------------------------------------------------
    if sys.mode == TrophicMode.PHOTOTROPHIC:
        util = min(max(sys.co2_utilization, MIN_CARBON_UTILIZATION), 1.0)
        balances.append(IdentityCheck(
            "Identity: CO2 fixed / M(CO2:C) == biomass C",
            inv.co2_fixed_per_kg / CO2_PER_C, org.carbon * gpp))
        if sys.carbon_source == CarbonSource.BICARBONATE:
            supplied_as_co2 = inv.bicarbonate_supply_per_kg * util * (CO2_PER_C / NAHCO3_PER_C)
        else:
            supplied_as_co2 = inv.co2_supply_per_kg * util
        balances.append(IdentityCheck(
            "Identity: inorganic C supplied x utilization == fixed",
            supplied_as_co2, inv.co2_fixed_per_kg))
    else:
        # Deliberately no longer called a carbon check: it never mentions carbon.
        # It restates how the substrate demand is derived from the mass yield.
        # The carbon question this used to be presented as answering is the
        # admissibility constraint below.
        yield_ = max(sys.substrate_yield, 1e-6)
        balances.append(IdentityCheck(
            "Identity: substrate x mass yield == gross biomass",
            inv.substrate_per_kg * yield_, gpp))

    # --- nitrogen & phosphorus ----------------------------------------------
    balances.append(IdentityCheck(
        "Identity: N supplied x uptake == biomass N",
        inv.nitrogen_per_kg * uptake, org.nitrogen * gpp))
    balances.append(IdentityCheck(
        "Identity: N supplied == assimilated + emitted",
        inv.nitrogen_per_kg, inv.nitrogen_per_kg * uptake + inv.nitrogen_emitted_per_kg))
    balances.append(IdentityCheck(
        "Identity: P supplied x uptake == biomass P",
        inv.phosphorus_per_kg * uptake, org.phosphorus * gpp))
    balances.append(IdentityCheck(
        "Identity: P supplied == assimilated + emitted",
        inv.phosphorus_per_kg, inv.phosphorus_per_kg * uptake + inv.phosphorus_emitted_per_kg))

    invariants: list[InvariantCheck] = []

    # --- physical admissibility ---------------------------------------------
    # Unlike the identities above, every one of these can fail.
    composition = org.carbon + org.nitrogen + org.phosphorus
    invariants.append(InvariantCheck(
        "Admissible: biomass C+N+P <= 1 kg/kg dry",
        composition <= 1.0 + TOL,
        f"C+N+P = {composition:.3f} kg/kg dry"))

    for label, value in (("harvesting recovery", scenario.harvesting.recovery),
                         ("nutrient uptake", sys.nutrient_uptake)):
        invariants.append(InvariantCheck(
            f"Admissible: {label} in (0, 1]",
            0.0 < value <= 1.0 + TOL, f"{value:.4g}"))
    if sys.mode == TrophicMode.PHOTOTROPHIC:
        invariants.append(InvariantCheck(
            "Admissible: carbon utilization in (0, 1]",
            0.0 < sys.co2_utilization <= 1.0 + TOL, f"{sys.co2_utilization:.4g}"))

    # The elemental carbon constraint the old "Carbon:" identity did not test:
    # a heterotroph cannot incorporate more carbon than its substrate carried.
    # The remainder is respired, and is reported rather than assumed away.
    if sys.mode != TrophicMode.PHOTOTROPHIC and inv.substrate_co2_supplied_per_kg > 0:
        c_in = inv.substrate_co2_supplied_per_kg
        c_biomass = inv.biogenic_co2_in_gross_biomass_per_kg
        fraction = c_biomass / c_in
        invariants.append(InvariantCheck(
            "Admissible: biomass C <= substrate C (heterotrophic)",
            c_biomass <= c_in * (1.0 + TOL),
            f"{fraction:.3f} of substrate carbon into biomass; "
            f"{inv.biogenic_co2_respired_per_kg:.3f} kg CO2-eq/kg respired"))

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
    """Human-readable verification report (for the reproduce script / paper appendix).

    The two families are printed under separate headings on purpose: reading a
    machine-precision residual as though it were a conservation result is the
    misreading this module exists to prevent.
    """
    lines = [f"Verification - {scenario_name}: "
             f"{'PASS' if report.all_pass else 'FAIL'} "
             f"(max identity residual {report.max_residual:.1e}; "
             f"{sum(1 for i in report.invariants if i.passed)}/{len(report.invariants)} "
             f"admissibility constraints hold)"]
    lines.append("  construction identities - hold by construction; a residual above "
                 "round-off means inventory.py and verification.py have diverged")
    for c in report.balances:
        lines.append(f"    [{'ok' if c.closes else 'XX'}] {c.name:52s} residual {c.residual:.1e}")
    lines.append("  physical admissibility - these can fail")
    for i in report.invariants:
        lines.append(f"    [{'ok' if i.passed else 'XX'}] {i.name:52s} {i.detail}")
    return "\n".join(lines)
