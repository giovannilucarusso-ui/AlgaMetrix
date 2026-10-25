"""Equipment and labour cost as a function of plant capacity.

Up to 1.5 every capital coefficient was applied in proportion to capacity: a
pond twice the area cost twice as much, and so did a dryer handling twice the
throughput. That is close to right for ponds and photobioreactors, which are
enlarged by adding modules of a fixed size, and wrong for fermenters,
centrifuges, dryers and extraction units, whose cost per unit of capacity falls
as the unit gets bigger. This module applies the power law used for those,

    C = c * S_ref * (S / S_ref) ** n,

to each equipment group, with the parameters declared on a
:class:`~algametrix.models.CostScaling`, and the same law to labour through a
:class:`~algametrix.models.LabourScaling`.

The defaults, n = 1 for equipment and n = 0 for labour, return exactly the
products the earlier releases computed (c * S and L_ref), so a scenario that
declares nothing gets the same numbers to the last bit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Basis, CostScaling, LabourScaling, Scenario

#: Capacity unit of the downstream groups and of labour.
KG_PER_YEAR = "kg/yr"


@dataclass(frozen=True)
class ScaledCost:
    """One cost group as the TEA computed it."""

    capacity: float                    # S, in ``capacity_unit``
    capacity_unit: str
    units: int                         # identical units in parallel
    exponent: float
    reference_capacity: float | None
    cost: float                        # EUR purchased (equipment) or EUR/yr (labour)

    @property
    def unit_capacity(self) -> float:
        """The size of each unit."""
        return self.capacity / self.units


@dataclass(frozen=True)
class CostGroup:
    """One equipment group of a scenario: its coefficient, capacity and scaling."""

    label: str            # as in the TEA's CAPEX breakdown
    path: str             # where the scaling sits in the scenario, for messages
    coefficient: float    # EUR per unit of capacity, at S_ref
    capacity: float
    capacity_unit: str
    scaling: CostScaling


def parallel_units(capacity: float, scaling: CostScaling) -> int:
    """How many identical units ``capacity`` is built as: one up to the largest unit size."""
    top = scaling.max_capacity
    if top is None or top <= 0 or capacity <= top:
        return 1
    # The offset stops a capacity of exactly k units, which the division can
    # put a hair above k, from being counted as k + 1.
    return max(1, math.ceil(capacity / top - 1e-9))


def equipment_cost(coefficient: float, capacity: float,
                   scaling: CostScaling) -> tuple[float, int]:
    """Purchased cost of one equipment group, and the number of units it is built as.

    Each of the N units has capacity S/N and costs c S_ref (S/(N S_ref))^n. With
    n = 1 the total is c S whatever S_ref and N are, so it is computed as that
    product and the proportional model is reproduced exactly.
    """
    units = parallel_units(capacity, scaling)
    if scaling.exponent == 1.0:
        return coefficient * capacity, units
    if coefficient == 0.0:
        return 0.0, units
    ref = scaling.reference_capacity
    if ref is None or ref <= 0:
        raise ValueError(
            f"a cost exponent of {scaling.exponent:g} needs the reference capacity "
            f"the coefficient was derived at")
    return units * coefficient * ref * (capacity / units / ref) ** scaling.exponent, units


def labour_cost(reference_cost: float, capacity: float, scaling: LabourScaling) -> float:
    """Annual labour cost, ``reference_cost`` taken from S_ref to ``capacity``."""
    if scaling.exponent == 0.0 or reference_cost == 0.0:
        return reference_cost
    ref = scaling.reference_capacity
    if ref is None or ref <= 0:
        raise ValueError(
            f"a labour exponent of {scaling.exponent:g} needs the reference capacity "
            f"the labour cost was taken at")
    return reference_cost * (capacity / ref) ** scaling.exponent


def cultivation_unit(scenario: Scenario) -> str:
    """What the cultivation capacity, ``scenario.scale``, is measured in."""
    return "m2" if scenario.system.basis == Basis.AREA else "m3"


def equipment_groups(scenario: Scenario, annual_kg: float) -> list[CostGroup]:
    """The equipment groups the scenario uses, in the order the CAPEX lists them.

    Cultivation is sized on the area or volume, the downstream groups on the
    dry biomass leaving the gate per year, as they always were.
    """
    sys, eco = scenario.system, scenario.economics
    groups = [
        CostGroup("Cultivation equipment", "system.capex_scaling", sys.capex_per_unit,
                  scenario.scale, cultivation_unit(scenario), sys.capex_scaling),
        CostGroup("Harvesting equipment", "economics.harvest_capex_scaling",
                  eco.harvest_capex_per_kgyr, annual_kg, KG_PER_YEAR,
                  eco.harvest_capex_scaling),
    ]
    if scenario.drying.enabled:
        groups.append(CostGroup("Drying equipment", "economics.drying_capex_scaling",
                                eco.drying_capex_per_kgyr, annual_kg, KG_PER_YEAR,
                                eco.drying_capex_scaling))
    if scenario.extraction.enabled:
        groups.append(CostGroup("Extraction equipment", "extraction.capex_scaling",
                                scenario.extraction.capex_per_kgyr, annual_kg, KG_PER_YEAR,
                                scenario.extraction.capex_scaling))
    return groups
