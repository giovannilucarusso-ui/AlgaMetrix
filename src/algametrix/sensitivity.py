"""One-dimensional sensitivity analysis.

Sweep a single input parameter over a range and recompute the whole scenario at
each point, so you can plot how an output (production cost, NPV, GWP, ...) responds
— the microalgae-TEA equivalent of a SuperPro "NPV vs throughput" sensitivity chart.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

from .inputcheck import InadmissibleScenarioError
from .models import Scenario
from .scenario import Results, run_scenario


def linspace(a: float, b: float, n: int = 11) -> list[float]:
    if n < 2:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


@dataclass
class SweepParam:
    """A parameter that can be swept, with how to apply/read it and a sensible range."""

    name: str
    unit: str
    apply: Callable[[Scenario, float], None]   # mutate a scenario copy in place
    default_range: Callable[[Scenario], list[float]]
    read: Callable[[Scenario], float] | None = None   # current nominal value


@dataclass
class SweepPoint:
    value: float
    results: Results


def run_sweep(base: Scenario, param: "SweepParam", values: list[float]) -> list[SweepPoint]:
    """Recompute ``base`` for each ``value`` of ``param``.

    A value that makes the scenario inadmissible is left out rather than plotted:
    the engine would have had to bound it, and a bounded point is a result for a
    different scenario than the one the axis says. The returned series is
    therefore shorter than ``values`` where that happens, and
    :func:`skipped_values` says which ones went.
    """
    points: list[SweepPoint] = []
    for v in values:
        scn = copy.deepcopy(base)
        param.apply(scn, v)
        try:
            points.append(SweepPoint(v, run_scenario(scn)))
        except InadmissibleScenarioError:
            continue
    return points


def skipped_values(values: list[float], points: list[SweepPoint]) -> list[float]:
    """The swept values that produced no point, for a caller that wants to say so."""
    kept = {p.value for p in points}
    return [v for v in values if v not in kept]


# Extractors for common outputs, for plotting a swept series.
OUTPUTS: dict[str, Callable[[Results], float]] = {
    "Production cost (€/kg)": lambda r: r.tea.production_cost_eur_per_kg,
    "NPV (€)": lambda r: r.tea.npv,
    "Net profit (€/yr)": lambda r: r.tea.net_profit,
    "GWP (kg CO₂-eq/kg)": lambda r: r.lca.gwp_kg_co2eq_per_kg,
    "Annual output (t/yr)": lambda r: r.inventory.annual_biomass_kg / 1000.0,
}


def _pct_range(x: float, lo: float = 0.5, hi: float = 1.5, n: int = 11) -> list[float]:
    x = x or 1.0
    return linspace(x * lo, x * hi, n)


# The parameters offered in the UI sensitivity tab.
PARAMETERS: list[SweepParam] = [
    SweepParam("Plant scale", "unit",
               lambda s, v: setattr(s, "scale", v),
               lambda s: _pct_range(s.scale, 0.3, 2.0),
               lambda s: s.scale),
    SweepParam("Product price", "€/kg",
               lambda s, v: setattr(s, "product_price", v),
               lambda s: linspace(0.0, max(s.product_price * 2, 5.0)),
               lambda s: s.product_price),
    SweepParam("Productivity", "g/m²/d or g/L/d",
               lambda s, v: setattr(s.system, "productivity", v),
               lambda s: _pct_range(s.system.productivity),
               lambda s: s.system.productivity),
    SweepParam("Substrate yield", "kg/kg",
               lambda s, v: setattr(s.system, "substrate_yield", v),
               lambda s: linspace(0.2, 0.6),
               lambda s: s.system.substrate_yield),
    SweepParam("Electricity price", "€/kWh",
               lambda s, v: setattr(s.economics, "electricity_price", v),
               lambda s: linspace(0.05, 0.30),
               lambda s: s.economics.electricity_price),
    SweepParam("Bicarbonate price", "€/kg",
               lambda s, v: setattr(s.economics, "bicarbonate_price", v),
               lambda s: linspace(0.15, 0.55),
               lambda s: s.economics.bicarbonate_price),
    SweepParam("Carbon utilization", "-",
               lambda s, v: setattr(s.system, "co2_utilization", v),
               lambda s: linspace(0.5, 0.9),
               lambda s: s.system.co2_utilization),
    SweepParam("Discount rate", "-",
               lambda s, v: setattr(s.economics, "discount_rate", v),
               lambda s: linspace(0.0, 0.20),
               lambda s: s.economics.discount_rate),
    SweepParam("Plant lifetime", "yr",
               lambda s, v: setattr(s.economics, "plant_lifetime", v),
               lambda s: linspace(5, 30, 6),
               lambda s: s.economics.plant_lifetime),
    SweepParam("Batch size (kg/batch)", "kg",
               lambda s, v: setattr(s, "batch_size_kg", v),
               lambda s: _pct_range(s.batch_size_kg or 1000.0),
               lambda s: s.batch_size_kg),
]
