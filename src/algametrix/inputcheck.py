"""Is this scenario physically possible?

The engine will compute something for almost any numbers it is given, and some
of those numbers describe nothing. A productivity of zero returns a cost of
``inf``; a substrate yield of zero is floored internally to 1e-6 and returns a
million kilograms of glucose per kilogram of biomass. Both are arithmetic on an
input that was a mistake, and neither looks like an error to a reader.

This module is the layer that says no. It runs on the :class:`Scenario` alone —
before any inventory is built — and returns what is wrong with it, so the client
can refuse to run, refuse to export, and say which field to fix.

Two severities, and the distinction is deliberate:

``error``
    The scenario is not admissible. The number that would come out has no
    physical meaning. The client must not present it as a result.
``warning``
    Admissible but surprising, or a place where the engine applies a floor that
    the user should know about rather than discover. The result stands.

The rules are conservative on purpose. A tool that blocks a legitimate case is
worse than one that flags it, so the error thresholds catch inputs that cannot
be right — never inputs that are merely unusual.
"""

from __future__ import annotations

from dataclasses import dataclass

from .inventory import MIN_CARBON_UTILIZATION
from .models import Basis, Scenario, TrophicMode
from .products import product_yield

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class InputIssue:
    """One thing wrong with a scenario, and where."""

    field: str        # dotted path into the scenario, e.g. "system.productivity"
    message: str      # what is wrong, in the terms the user entered it
    severity: str = ERROR

    @property
    def is_error(self) -> bool:
        return self.severity == ERROR

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


def _composition(scn: Scenario) -> list[InputIssue]:
    org = scn.organism
    issues: list[InputIssue] = []
    total = org.protein + org.lipid + org.carbohydrate + org.ash
    if total > 1.1:
        issues.append(InputIssue(
            "organism.composition",
            f"protein + lipid + carbohydrate + ash = {total:.0%} of dry weight. "
            f"A kilogram of biomass cannot contain more than a kilogram of "
            f"components; check the fractions.",
        ))
    elif total < 0.5:
        issues.append(InputIssue(
            "organism.composition",
            f"protein + lipid + carbohydrate + ash = {total:.0%} of dry weight. "
            f"More than half the biomass is unaccounted for; check the fractions.",
        ))
    elif not 0.95 <= total <= 1.05:
        issues.append(InputIssue(
            "organism.composition",
            f"the four fractions sum to {total:.0%}, not ~100%. The mass balance "
            f"still runs, but any yield taken from the composition inherits the gap.",
            WARNING,
        ))

    elemental = org.carbon + org.nitrogen + org.phosphorus
    if elemental > 1.0:
        issues.append(InputIssue(
            "organism.carbon",
            f"C + N + P = {elemental:.0%} of dry weight, which exceeds the "
            f"biomass itself.",
        ))
    if org.carbon <= 0:
        issues.append(InputIssue(
            "organism.carbon",
            "carbon fraction is zero: the carbon balance has nothing to work with.",
        ))
    if org.nitrogen <= 0:
        issues.append(InputIssue(
            "organism.nitrogen",
            "nitrogen fraction is zero, so the culture is modelled as needing no "
            "nitrogen at all.", WARNING,
        ))
    return issues


def _cultivation(scn: Scenario) -> list[InputIssue]:
    sys = scn.system
    issues: list[InputIssue] = []
    continuous = not (scn.batch_mode and scn.batch_cycle_time_h > 0)

    if sys.productivity <= 0 and continuous:
        unit = "g/m²/d" if sys.basis == Basis.AREA else "g/L/d"
        issues.append(InputIssue(
            "system.productivity",
            f"productivity is zero ({unit}), so the plant makes nothing and the "
            f"production cost is infinite.",
        ))
    if not 0 < sys.operating_days <= 366:
        issues.append(InputIssue(
            "system.operating_days",
            f"{sys.operating_days:g} operating days per year is outside 1-366.",
        ))
    if scn.scale <= 0:
        issues.append(InputIssue(
            "scale",
            "the plant has no cultivation area or volume.",
        ))
    if not 0 < sys.nutrient_uptake <= 1:
        issues.append(InputIssue(
            "system.nutrient_uptake",
            f"nutrient uptake efficiency is {sys.nutrient_uptake:g}; it is a "
            f"fraction and must be above 0 and at most 1.",
        ))

    if sys.mode == TrophicMode.HETEROTROPHIC:
        if sys.substrate_yield <= 0:
            issues.append(InputIssue(
                "system.substrate_yield",
                "substrate yield is zero: no amount of substrate would make any "
                "biomass. Enter kg biomass per kg substrate (typically 0.3-0.5).",
            ))
        elif sys.substrate_yield > 1:
            issues.append(InputIssue(
                "system.substrate_yield",
                f"substrate yield is {sys.substrate_yield:g} kg biomass per kg "
                f"substrate: more biomass than the substrate fed to make it.",
            ))
    else:
        if sys.co2_utilization <= 0:
            issues.append(InputIssue(
                "system.co2_utilization",
                "carbon utilisation is zero, which implies an infinite carbon feed.",
            ))
        elif sys.co2_utilization < MIN_CARBON_UTILIZATION:
            issues.append(InputIssue(
                "system.co2_utilization",
                f"carbon utilisation of {sys.co2_utilization:.0%} is below the "
                f"{MIN_CARBON_UTILIZATION:.0%} floor the balance applies, so the "
                f"carbon feed is computed at {MIN_CARBON_UTILIZATION:.0%}.",
                WARNING,
            ))
        if sys.co2_utilization > 1:
            issues.append(InputIssue(
                "system.co2_utilization",
                "carbon utilisation above 100% would fix more carbon than is fed.",
            ))
    return issues


def _downstream(scn: Scenario) -> list[InputIssue]:
    issues: list[InputIssue] = []
    harv = scn.harvesting
    if not 0 < harv.recovery <= 1:
        issues.append(InputIssue(
            "harvesting.recovery",
            f"biomass recovery is {harv.recovery:g}; it is a fraction and must be "
            f"above 0 and at most 1.",
        ))
    if not 0 < harv.final_solids <= 1:
        issues.append(InputIssue(
            "harvesting.final_solids",
            f"concentrate solids of {harv.final_solids:g} is not a fraction of 1.",
        ))
    if scn.drying.enabled:
        if not 0 < scn.drying.final_solids <= 1:
            issues.append(InputIssue(
                "drying.final_solids",
                f"dried-product solids of {scn.drying.final_solids:g} is not a "
                f"fraction of 1.",
            ))
        elif scn.drying.final_solids <= harv.final_solids:
            issues.append(InputIssue(
                "drying.final_solids",
                "the dryer leaves the product no drier than it arrived, so it "
                "evaporates nothing and costs only its electricity.", WARNING,
            ))
    return issues


def _batch(scn: Scenario) -> list[InputIssue]:
    if not scn.batch_mode:
        return []
    issues: list[InputIssue] = []
    if scn.batch_cycle_time_h <= 0:
        issues.append(InputIssue(
            "batch_cycle_time_h",
            "batch mode is on but the cycle time is zero, so the schedule falls "
            "back to continuous operation.",
        ))
    if scn.batch_size_kg <= 0:
        issues.append(InputIssue(
            "batch_size_kg",
            "batch mode is on but each batch produces nothing.",
        ))
    return issues


def _products(scn: Scenario) -> list[InputIssue]:
    issues: list[InputIssue] = []
    if not scn.products:
        return issues
    if sum(1 for p in scn.products if p.is_main) > 1:
        issues.append(InputIssue(
            "products",
            "more than one product is flagged as the main product; the cost and "
            "GWP can only be reported per one of them.",
        ))
    if not any(p.is_main for p in scn.products):
        issues.append(InputIssue(
            "products",
            f"no product is flagged as main, so the first one "
            f"({scn.products[0].name}) carries the reported cost.", WARNING,
        ))
    total_yield = 0.0
    for p in scn.products:
        if not 0 <= p.recovery <= 1:
            issues.append(InputIssue(
                f"products.{p.name}.recovery",
                f"recovery is {p.recovery:g}; it is a fraction and cannot exceed 1.",
            ))
        total_yield += product_yield(scn, p)
    if total_yield > 1.001:
        issues.append(InputIssue(
            "products",
            f"the products together account for {total_yield:.2f} kg per kg of "
            f"biomass: more product than biomass to make it from.",
        ))
    return issues


def _economics(scn: Scenario) -> list[InputIssue]:
    eco = scn.economics
    issues: list[InputIssue] = []
    if eco.plant_lifetime <= 0:
        issues.append(InputIssue("economics.plant_lifetime",
                                 "the project horizon must be at least one year."))
    if eco.depreciation_years <= 0:
        issues.append(InputIssue("economics.depreciation_years",
                                 "the depreciation period must be at least one year.",
                                 WARNING))
    if not 0 <= eco.tax_rate < 1:
        issues.append(InputIssue("economics.tax_rate",
                                 f"a tax rate of {eco.tax_rate:g} is not a fraction below 1."))
    if eco.installation_factor < 1:
        issues.append(InputIssue(
            "economics.installation_factor",
            "installed capital below the equipment cost it installs.", WARNING))
    return issues


def _waste(scn: Scenario) -> list[InputIssue]:
    wf = scn.waste_feed
    if not wf.enabled:
        return []
    issues: list[InputIssue] = []
    if not 0 <= wf.coverage <= 1:
        issues.append(InputIssue(
            "waste_feed.coverage",
            f"coverage of {wf.coverage:g} is not a fraction of the demand.",
        ))
    carried = {"nitrogen": wf.nitrogen_per_unit,
               "phosphorus": wf.phosphorus_per_unit,
               "substrate": wf.substrate_per_unit}.get(wf.dosed_on, 0.0)
    if carried <= 0:
        issues.append(InputIssue(
            "waste_feed.dosed_on",
            f"the stream is dosed on {wf.dosed_on} but carries none, so nothing "
            f"is received and every nutrient is still bought.", WARNING,
        ))
    return issues


def check_inputs(scenario: Scenario) -> list[InputIssue]:
    """Everything wrong with ``scenario``, errors first."""
    issues: list[InputIssue] = []
    for check in (_composition, _cultivation, _downstream, _batch,
                  _products, _economics, _waste):
        issues.extend(check(scenario))
    return sorted(issues, key=lambda i: 0 if i.is_error else 1)


def errors(scenario: Scenario) -> list[InputIssue]:
    """Only the issues that make the scenario inadmissible."""
    return [i for i in check_inputs(scenario) if i.is_error]


def is_admissible(scenario: Scenario) -> bool:
    """True when the scenario describes something that could exist."""
    return not errors(scenario)


def format_issues(issues: list[InputIssue]) -> str:
    """One line per issue, for a message box or a console."""
    return "\n".join(
        f"{'ERROR  ' if i.is_error else 'WARNING'}  {i.field}: {i.message}"
        for i in issues
    )
