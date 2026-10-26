"""Production cost against plant size for the heterotrophic archetype.

Up to 1.5 every equipment group was costed in proportion to capacity and labour
was a fixed annual cost. This module shows how much that choice matters once a
plant moves away from the size its costs were set at, by running the same
plant over a range of sizes with the default cost model and with power laws
taken from the literature.

The heterotrophic archetype is used because its fermentation-section cost
(10,000 per m3) was calibrated against a costed plant of known size: the
SuperPro case of Russo et al. (2022), 150 m3. Every exponent is anchored at that
plant - cultivation at its volume, harvesting, drying and labour at its annual
output - so all cases give the archetype's own result at 150 m3 and differ only
away from it.

Sizes run from a tenth to ten times the reference, the range over which
power-law cost correlations are normally used and inside which the input check
raises no warning. No largest unit size is declared, so each group is costed as
one unit at every size.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product

from ..library import Library, load_library
from ..models import CostScaling, LabourScaling, Scenario
from ..scenario import run_scenario
from . import archetypes

ARCHETYPE = "heterotrophic_fermenter"

#: Exponent ranges, lowest and highest.
EQUIPMENT_EXPONENTS = (0.6, 0.7)
LABOUR_EXPONENTS = (0.2, 0.25)

EQUIPMENT_SOURCE = (
    "typical range for process equipment enlarged as a single unit "
    "(six-tenths rule, Williams 1947; Peters, Timmerhaus and West 2003)")
LABOUR_SOURCE = (
    "typical range for operating labour against plant capacity "
    "(Peters, Timmerhaus and West 2003, after Wessel 1952)")

#: Sizes in the printed table, as multiples of the reference volume.
TABLE_MULTIPLES = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)

#: Sizes drawn in the figure: 81 points, evenly spaced on a log axis.
FIGURE_MULTIPLES = tuple(10.0 ** (k / 40.0) for k in range(-40, 41))


@dataclass(frozen=True)
class Case:
    """One cost model and the exponents it spans."""

    key: str
    label: str
    equipment: tuple[float, ...]
    labour: tuple[float, ...]


CASES = (
    Case("default", "default: equipment n = 1, labour fixed", (1.0,), (0.0,)),
    Case("equipment", "equipment n = 0.6-0.7, labour fixed", EQUIPMENT_EXPONENTS, (0.0,)),
    Case("equipment_labour", "equipment n = 0.6-0.7, labour n_L = 0.2-0.25",
         EQUIPMENT_EXPONENTS, LABOUR_EXPONENTS),
)


@dataclass(frozen=True)
class Point:
    """One size under one case.

    Each range is the lowest and highest result over the combinations of the
    ends of the case's exponent ranges; for the default the two coincide.
    """

    volume_m3: float
    output_kg: float
    investment: tuple[float, float]
    cost: tuple[float, float]


@dataclass(frozen=True)
class Reference:
    """The plant every exponent is anchored at."""

    scenario: Scenario
    label: str
    provenance: str
    volume_m3: float
    output_kg: float
    cultivation_cost_per_m3: float
    investment: float
    cost: float


def reference(lib: Library | None = None) -> Reference:
    arch = archetypes.get(ARCHETYPE)
    scn = archetypes.build(ARCHETYPE, lib or load_library())
    res = run_scenario(scn)
    return Reference(scn, arch.label, arch.provenance, scn.scale,
                     res.inventory.annual_biomass_kg, scn.system.capex_per_unit,
                     res.tea.total_investment, res.tea.production_cost_eur_per_kg)


def resized(ref: Reference, volume: float, n: float, n_labour: float) -> Scenario:
    """The reference plant at ``volume``, with every equipment group on exponent
    ``n`` and labour on ``n_labour``.

    With the default exponents only the volume changes, which is the calculation
    of the earlier releases.
    """
    base = ref.scenario
    if n == 1.0 and n_labour == 0.0:
        return replace(base, scale=volume)

    def law(capacity: float) -> CostScaling:
        return CostScaling(exponent=n, reference_capacity=capacity, source=EQUIPMENT_SOURCE)

    economics = replace(
        base.economics,
        harvest_capex_scaling=law(ref.output_kg),
        drying_capex_scaling=law(ref.output_kg),
        labor_scaling=LabourScaling(exponent=n_labour, reference_capacity=ref.output_kg,
                                    source=LABOUR_SOURCE),
    )
    return replace(base, scale=volume,
                   system=replace(base.system, capex_scaling=law(ref.volume_m3)),
                   extraction=replace(base.extraction, capex_scaling=law(ref.output_kg)),
                   economics=economics)


def sweep(ref: Reference, multiples=TABLE_MULTIPLES) -> dict[str, list[Point]]:
    """Every case at every size, keyed by :attr:`Case.key`."""
    curves: dict[str, list[Point]] = {}
    for case in CASES:
        points = []
        for k in multiples:
            volume = ref.volume_m3 * k
            runs = [run_scenario(resized(ref, volume, n, n_labour))
                    for n, n_labour in product(case.equipment, case.labour)]
            investment = [r.tea.total_investment for r in runs]
            cost = [r.tea.production_cost_eur_per_kg for r in runs]
            points.append(Point(volume, runs[0].inventory.annual_biomass_kg,
                                (min(investment), max(investment)), (min(cost), max(cost))))
        curves[case.key] = points
    return curves
