"""Uncertain inputs, their ranges, and where each range comes from.

One definition serves both the global sensitivity analysis and the Monte-Carlo
uncertainty propagation, so the two can never disagree about what "productivity"
means or how wide its range is.

Every parameter carries the metadata the reviewer asked for: distribution,
bounds, mode, source, evidence quality and correlation group. ``evidence_quality``
is the field to read first:

``derived_from_repository``
    the range is the one already declared in ``sensitivity.py`` for the
    interactive sweep, i.e. it is part of this tool and is cited as such;
``scenario_assumption``
    a first-order relative band with no evidence behind it. It is a *choice*.
    Results that depend on it must be reported as conditional on it.

No range here is presented as an empirical distribution, because none of them is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..models import Scenario

#: Uncertainty groups. The point of the split is to answer "how much of the
#: output spread is physics, how much is prices, how much is the LCIA
#: background" - a question the previous joint-only sampling could not answer.
GROUP_FOREGROUND = "foreground"
GROUP_ECONOMIC = "economic"
GROUP_BACKGROUND = "lcia_background"

GROUPS = (GROUP_FOREGROUND, GROUP_ECONOMIC, GROUP_BACKGROUND)

EVIDENCE_QUALITIES = ("derived_from_repository", "scenario_assumption", "published")

#: The first-order band applied to characterization factors when nothing better
#: is available. Kept from the previous version so results stay comparable, but
#: it is a scenario assumption and is labelled as one everywhere it is used.
DEFAULT_CF_RELATIVE_BAND = 0.50


@dataclass
class UncertainParameter:
    """One uncertain input with a full provenance record."""

    name: str
    group: str
    apply: Callable[[Scenario, float], None]
    read: Callable[[Scenario], float]
    unit: str = ""
    distribution: str = "triangular"
    # Bounds are relative to the scenario's nominal value unless absolute_bounds
    # is given, because the same parameter has a different nominal value in each
    # archetype.
    relative_band: float | None = None          # +/- fraction of nominal
    absolute_bounds: tuple[float, float] | None = None
    physical_max: float | None = None           # hard cap, e.g. a recovery <= 1
    physical_min: float | None = 0.0
    source: str = ""
    evidence_quality: str = "scenario_assumption"
    correlation_group: str | None = None
    notes: str = ""

    def bounds(self, scenario: Scenario) -> tuple[float, float, float]:
        """``(lower, mode, upper)`` for this scenario, after physical clipping."""
        nominal = float(self.read(scenario))
        if self.absolute_bounds is not None:
            lo, hi = self.absolute_bounds
        else:
            band = self.relative_band if self.relative_band is not None else 0.0
            lo, hi = nominal * (1 - band), nominal * (1 + band)
        if self.physical_min is not None:
            lo = max(lo, self.physical_min)
        if self.physical_max is not None:
            hi = min(hi, self.physical_max)
            nominal = min(nominal, self.physical_max)
        lo, hi = min(lo, hi), max(lo, hi)
        mode = min(max(nominal, lo), hi)
        return lo, mode, hi

    def metadata(self, scenario: Scenario) -> dict:
        lo, mode, hi = self.bounds(scenario)
        return {
            "name": self.name,
            "group": self.group,
            "unit": self.unit,
            "distribution": self.distribution,
            "lower": lo,
            "mode_or_mean": mode,
            "upper_or_sd": hi,
            "source": self.source,
            "evidence_quality": self.evidence_quality,
            "correlation_group": self.correlation_group or "none (assumed independent)",
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# Setters / readers
# --------------------------------------------------------------------------

def _set_lcia(field_name: str) -> Callable[[Scenario, float], None]:
    def setter(s: Scenario, v: float) -> None:
        setattr(s.lcia, field_name, v)
    return setter


def _get_lcia(field_name: str) -> Callable[[Scenario], float]:
    def getter(s: Scenario) -> float:
        return float(getattr(s.lcia, field_name))
    return getter


_REPO_RANGE = "sensitivity.py:PARAMETERS (the range already shipped for the interactive sweep)"
_FIRST_ORDER = "first-order relative band; no evidence base"


# --------------------------------------------------------------------------
# Foreground physical parameters - shared by TEA and LCA
# --------------------------------------------------------------------------

FOREGROUND: list[UncertainParameter] = [
    UncertainParameter(
        "Productivity", GROUP_FOREGROUND,
        lambda s, v: setattr(s.system, "productivity", v),
        lambda s: s.system.productivity,
        unit="g/m2/d or g/L/d", relative_band=0.5,
        source=_REPO_RANGE, evidence_quality="derived_from_repository",
        correlation_group="productivity_energy",
        notes="Sets the annual output for a given footprint; drives every per-kg flow.",
    ),
    UncertainParameter(
        "Harvesting recovery", GROUP_FOREGROUND,
        lambda s, v: setattr(s.harvesting, "recovery", v),
        lambda s: s.harvesting.recovery,
        unit="-", relative_band=0.15, physical_max=1.0,
        source=_FIRST_ORDER,
        notes="Capped at 1. Scales every upstream flow by 1/recovery.",
    ),
    UncertainParameter(
        "Biomass concentration", GROUP_FOREGROUND,
        lambda s, v: setattr(s.system, "biomass_conc", v),
        lambda s: s.system.biomass_conc,
        unit="g/L", relative_band=0.3,
        source=_FIRST_ORDER,
        correlation_group="concentration_dewatering",
        notes="Diagnostic in the present balance; retained so the group is complete.",
    ),
    UncertainParameter(
        "Cultivation electricity", GROUP_FOREGROUND,
        lambda s, v: setattr(s.system, "elec_kwh_per_kg", v),
        lambda s: s.system.elec_kwh_per_kg,
        unit="kWh/kg", relative_band=0.4,
        source=_FIRST_ORDER,
        correlation_group="productivity_energy",
        notes="Dominant LCA flow for closed and illuminated systems.",
    ),
    UncertainParameter(
        "Drying heat demand", GROUP_FOREGROUND,
        lambda s, v: setattr(s.drying, "thermal_mj_per_kg_water", v),
        lambda s: s.drying.thermal_mj_per_kg_water,
        unit="MJ/kg water", relative_band=0.3,
        source=_FIRST_ORDER,
        correlation_group="concentration_dewatering",
    ),
    UncertainParameter(
        "Carbon utilization", GROUP_FOREGROUND,
        lambda s, v: setattr(s.system, "co2_utilization", v),
        lambda s: s.system.co2_utilization,
        unit="-", absolute_bounds=(0.5, 0.9), physical_max=1.0,
        source=_REPO_RANGE, evidence_quality="derived_from_repository",
        notes="Fraction of supplied inorganic carbon fixed. No effect on heterotrophic systems.",
    ),
    UncertainParameter(
        "Nutrient uptake", GROUP_FOREGROUND,
        lambda s, v: setattr(s.system, "nutrient_uptake", v),
        lambda s: s.system.nutrient_uptake,
        unit="-", relative_band=0.15, physical_max=1.0,
        source=_FIRST_ORDER,
    ),
    UncertainParameter(
        "Substrate yield", GROUP_FOREGROUND,
        lambda s, v: setattr(s.system, "substrate_yield", v),
        lambda s: s.system.substrate_yield,
        unit="kg/kg", relative_band=0.25,
        source=_FIRST_ORDER,
        notes="Heterotrophic only; nominal is 0 for phototrophic archetypes, so it is dropped there.",
    ),
    UncertainParameter(
        "Solvent recovery", GROUP_FOREGROUND,
        lambda s, v: setattr(s.extraction, "solvent_recovery", v),
        lambda s: s.extraction.solvent_recovery,
        unit="-", relative_band=0.02, physical_max=1.0,
        source=_FIRST_ORDER,
        notes="Only active when downstream extraction is enabled.",
    ),
]


# --------------------------------------------------------------------------
# Economic parameters - TEA only
# --------------------------------------------------------------------------

ECONOMIC: list[UncertainParameter] = [
    UncertainParameter(
        "Electricity price", GROUP_ECONOMIC,
        lambda s, v: setattr(s.economics, "electricity_price", v),
        lambda s: s.economics.electricity_price,
        unit="EUR/kWh", absolute_bounds=(0.05, 0.30),
        source=_REPO_RANGE, evidence_quality="derived_from_repository",
    ),
    UncertainParameter(
        "Heat price", GROUP_ECONOMIC,
        lambda s, v: setattr(s.economics, "heat_price", v),
        lambda s: s.economics.heat_price,
        unit="EUR/MJ", relative_band=0.5,
        source=_FIRST_ORDER,
    ),
    UncertainParameter(
        "Substrate price", GROUP_ECONOMIC,
        lambda s, v: setattr(s.economics, "substrate_price", v),
        lambda s: s.economics.substrate_price,
        unit="EUR/kg", relative_band=0.3,
        source=_FIRST_ORDER,
        notes="Heterotrophic only.",
    ),
    UncertainParameter(
        "Labour cost", GROUP_ECONOMIC,
        lambda s, v: setattr(s.economics, "labor_cost_per_year", v),
        lambda s: s.economics.labor_cost_per_year,
        unit="EUR/yr", relative_band=0.3,
        source=_FIRST_ORDER,
        correlation_group="scale_labour",
    ),
    UncertainParameter(
        "Product price", GROUP_ECONOMIC,
        lambda s, v: setattr(s, "product_price", v),
        lambda s: s.product_price,
        unit="EUR/kg", relative_band=0.5,
        source=_REPO_RANGE, evidence_quality="derived_from_repository",
        notes="Affects NPV and MEPP only; production cost is price-independent by construction.",
    ),
    UncertainParameter(
        "Discount rate", GROUP_ECONOMIC,
        lambda s, v: setattr(s.economics, "discount_rate", v),
        lambda s: s.economics.discount_rate,
        unit="-", absolute_bounds=(0.0, 0.20),
        source=_REPO_RANGE, evidence_quality="derived_from_repository",
    ),
    UncertainParameter(
        "Plant scale", GROUP_ECONOMIC,
        lambda s, v: setattr(s, "scale", v),
        lambda s: s.scale,
        unit="m2 or m3", absolute_bounds=None, relative_band=0.7,
        source=_REPO_RANGE, evidence_quality="derived_from_repository",
        correlation_group="scale_labour",
        notes=(
            "Physically a foreground quantity, but in this engine it moves cost through "
            "the CAPEX and the fixed-labour split, so it is reported with the economic "
            "group and flagged in the Mode-A/Mode-B split."
        ),
    ),
]


# --------------------------------------------------------------------------
# LCIA background - LCA only
# --------------------------------------------------------------------------

def _cf(name: str, attr: str, unit: str, note: str = "") -> UncertainParameter:
    return UncertainParameter(
        name, GROUP_BACKGROUND, _set_lcia(attr), _get_lcia(attr),
        unit=unit, relative_band=DEFAULT_CF_RELATIVE_BAND,
        source=(
            f"+/-{DEFAULT_CF_RELATIVE_BAND:.0%} first-order band around the default in "
            "data/parameters.yaml; SCENARIO ASSUMPTION, not a published distribution"
        ),
        evidence_quality="scenario_assumption",
        correlation_group="grid_background" if attr.startswith("elec") else None,
        notes=note,
    )


BACKGROUND: list[UncertainParameter] = [
    _cf("Electricity GWP factor", "elec_gwp", "kg CO2-eq/kWh",
        "Regional grids span two orders of magnitude (IS ~0.008 to coal-heavy >0.8); a "
        "symmetric +/-50% band around an EU average does not represent that."),
    _cf("Heat GWP factor", "heat_gwp", "kg CO2-eq/MJ"),
    _cf("Nitrogen GWP factor", "nitrogen_gwp", "kg CO2-eq/kg N"),
    _cf("Phosphorus GWP factor", "phosphorus_gwp", "kg CO2-eq/kg P"),
    _cf("Substrate GWP factor", "substrate_gwp", "kg CO2-eq/kg"),
    _cf("CO2 supply GWP factor", "co2_supply_gwp", "kg CO2-eq/kg CO2"),
    _cf("Bicarbonate GWP factor", "bicarbonate_gwp", "kg CO2-eq/kg NaHCO3"),
]


ALL_PARAMETERS: list[UncertainParameter] = FOREGROUND + ECONOMIC + BACKGROUND


def by_group(group: str) -> list[UncertainParameter]:
    return [p for p in ALL_PARAMETERS if p.group == group]


def active(params: list[UncertainParameter], scenario: Scenario) -> list[UncertainParameter]:
    """Drop parameters that cannot move anything in this scenario.

    A parameter whose nominal value is zero (substrate yield in a phototrophic
    pond, solvent recovery with no extraction step) contributes no variance and
    would appear as a spurious zero-index entry in the ranking.
    """
    out = []
    for p in params:
        try:
            nominal = float(p.read(scenario))
        except Exception:
            continue
        if nominal == 0.0:
            continue
        if p.name == "Solvent recovery" and not scenario.extraction.enabled:
            continue
        if p.name == "Drying heat demand" and not scenario.drying.enabled:
            continue
        lo, mode, hi = p.bounds(scenario)
        if hi <= lo:
            continue
        out.append(p)
    return out


# --------------------------------------------------------------------------
# Sensitivity modes (Task 5)
# --------------------------------------------------------------------------

#: Mode A - only parameters that physically enter the SHARED inventory, so the
#: ranking is comparable across TEA and LCA outputs. This is the mode in which a
#: statement like "the dominant driver differs between cost and GWP" is
#: meaningful, because both outputs see the same parameter set.
MODE_A_SHARED_FOREGROUND = "A_shared_foreground"

#: Mode B - foreground plus the output-specific parameters (prices, discount
#: rate, characterization factors). Rankings from Mode B depend on which
#: parameters were assigned to which output and must be read as such.
MODE_B_FULL_DECISION = "B_full_decision"

MODE_DESCRIPTIONS = {
    MODE_A_SHARED_FOREGROUND: (
        "shared physical foreground only; every output is a function of the same "
        "parameter set, so rankings are directly comparable between TEA and LCA"
    ),
    MODE_B_FULL_DECISION: (
        "foreground plus output-specific economic and LCIA parameters; rankings are "
        "conditional on the assignment of parameters to outputs and are NOT evidence "
        "that one physical driver matters more than another"
    ),
}


def mode_parameters(mode: str, scenario: Scenario) -> list[UncertainParameter]:
    if mode == MODE_A_SHARED_FOREGROUND:
        return active(FOREGROUND, scenario)
    if mode == MODE_B_FULL_DECISION:
        return active(ALL_PARAMETERS, scenario)
    raise KeyError(mode)
