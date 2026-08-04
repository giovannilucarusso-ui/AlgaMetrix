"""Turn a scenario plus a parameter list into a vectorised model callable.

Both the Sobol analysis and the Monte-Carlo propagation need the same thing: a
function that takes a matrix of parameter values and returns one output per row,
computed through the *whole* engine so that TEA and LCA stay on the shared
inventory. It is defined once, here.
"""

from __future__ import annotations

import copy
from typing import Callable, Sequence

import numpy as np

from ..models import Scenario
from ..scenario import Results, run_scenario
from .parameters import UncertainParameter


def _main_cost(r: Results) -> float:
    """Production cost of the main product where one is defined, else of biomass."""
    if r.main_product is not None:
        return r.main_product.production_cost_eur_per_kg
    return r.tea.production_cost_eur_per_kg


#: Outputs available to the sensitivity and uncertainty analyses.
OUTPUTS: dict[str, Callable[[Results], float]] = {
    "Production cost (EUR/kg)": _main_cost,
    "NPV (EUR)": lambda r: r.tea.npv,
    "GWP net (kg CO2-eq/kg)": lambda r: r.lca.gwp_kg_co2eq_per_kg,
    "GWP gross (kg CO2-eq/kg)": lambda r: r.lca.gwp_gross_kg_co2eq_per_kg,
    "Electricity (kWh/kg)": lambda r: r.inventory.elec_kwh_per_kg,
}

#: Which outputs a given uncertainty group can possibly move. Used to check that
#: a decomposition adds up: LCIA factors cannot change a cost, and prices cannot
#: change a GWP, so a non-zero contribution there is a bug.
GROUP_AFFECTS: dict[str, tuple[str, ...]] = {
    "foreground": (
        "Production cost (EUR/kg)", "NPV (EUR)",
        "GWP net (kg CO2-eq/kg)", "GWP gross (kg CO2-eq/kg)", "Electricity (kWh/kg)",
    ),
    "economic": ("Production cost (EUR/kg)", "NPV (EUR)"),
    "lcia_background": ("GWP net (kg CO2-eq/kg)", "GWP gross (kg CO2-eq/kg)"),
}


def apply_row(base: Scenario, params: Sequence[UncertainParameter], row) -> Scenario:
    """Deep-copy ``base`` and apply one parameter vector to it."""
    scn = copy.deepcopy(base)
    for p, value in zip(params, row):
        p.apply(scn, float(value))
    return scn


def evaluate_rows(
    base: Scenario,
    params: Sequence[UncertainParameter],
    X: np.ndarray,
    getter: Callable[[Results], float],
) -> np.ndarray:
    """Run the engine once per row of ``X``.

    A row that makes the engine raise returns ``nan`` rather than aborting the
    study; the caller counts and reports the non-finite rows.
    """
    out = np.empty(X.shape[0], dtype=float)
    for j in range(X.shape[0]):
        try:
            out[j] = getter(run_scenario(apply_row(base, params, X[j])))
        except Exception:
            out[j] = np.nan
    return out


def make_model(
    base: Scenario, params: Sequence[UncertainParameter], output: str
) -> Callable[[np.ndarray], np.ndarray]:
    """Vectorised model callable for :func:`algametrix.paper.sobol.analyze`."""
    getter = OUTPUTS[output]

    def model(X: np.ndarray) -> np.ndarray:
        return evaluate_rows(base, params, X, getter)

    return model


def nominal(base: Scenario, output: str) -> float:
    return OUTPUTS[output](run_scenario(base))


def sobol_parameters(base: Scenario, params: Sequence[UncertainParameter]):
    """Adapt scenario parameters to the Sobol sampler's uniform ``[low, high]`` form.

    The Sobol decomposition is taken over a UNIFORM distribution on each
    parameter's support, while the Monte-Carlo propagation uses a triangular
    distribution on the same support. That is deliberate and is stated in the
    reports: a variance decomposition answers "which input, varied across its
    plausible range, moves the output", for which the uniform is the neutral
    choice; the uncertainty band answers "how likely is each value", for which a
    mode at the nominal is the informative one. The two therefore share supports,
    not densities, and their numbers are not interchangeable.
    """
    from .sobol import Parameter

    out = []
    for p in params:
        lo, _mode, hi = p.bounds(base)
        out.append(Parameter(name=p.name, low=lo, high=hi, group=p.group,
                             unit=p.unit, source=p.source))
    return out
