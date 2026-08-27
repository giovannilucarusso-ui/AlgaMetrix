"""Monte-Carlo uncertainty analysis.

Sample several uncertain inputs simultaneously and propagate them through the
whole model to obtain the distribution (and P10/P50/P90) of the outputs. Uses a
triangular distribution around each nominal value with a user-set relative width.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass

import numpy as np

from .inputcheck import InadmissibleScenarioError
from .models import Scenario
from .scenario import run_scenario
from .sensitivity import OUTPUTS, PARAMETERS, SweepParam


@dataclass
class MonteCarloResult:
    """Sampled output series and their summary statistics.

    ``n`` is the number of draws that produced a result. ``skipped`` counts the
    draws that did not: a triangular support around a nominal recovery of 0.9
    reaches past 1, and a recovery above 1 is not a sample of anything. Those
    draws are dropped rather than bounded, because bounding them would pile
    probability mass onto the limit itself and report it as the model's answer.
    A large ``skipped`` means the declared width crosses a physical limit and the
    support, not the result, is what needs revisiting.
    """

    n: int
    series: dict[str, list[float]]              # output name -> sampled values
    skipped: int = 0                            # draws refused as inadmissible

    def stats(self, output: str) -> dict[str, float]:
        vals = np.asarray(self.series[output], dtype=float)
        return {
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals)),
            "p10": float(np.percentile(vals, 10)),
            "p50": float(np.percentile(vals, 50)),
            "p90": float(np.percentile(vals, 90)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
        }


def run_montecarlo(
    base: Scenario,
    selected: list[tuple[SweepParam, float]],
    outputs: dict | None = None,
    n: int = 1000,
    seed: int | None = 42,
) -> MonteCarloResult:
    """Run ``n`` samples varying each ``(param, relative_width)`` triangularly.

    ``relative_width`` = 0.2 means the parameter is sampled on
    ``[nominal*0.8, nominal*1.2]`` with the mode at the nominal value.
    """
    outs = outputs if outputs is not None else OUTPUTS
    rng = random.Random(seed)
    series: dict[str, list[float]] = {name: [] for name in outs}
    skipped = 0

    for _ in range(n):
        scn = copy.deepcopy(base)
        for param, rel in selected:
            nominal = param.read(scn) if param.read else 0.0
            lo = nominal * (1.0 - rel)
            hi = nominal * (1.0 + rel)
            if hi <= lo:
                value = nominal
            else:
                value = rng.triangular(lo, hi, nominal)
            param.apply(scn, max(value, 0.0))
        try:
            r = run_scenario(scn)
        except InadmissibleScenarioError:
            skipped += 1
            continue
        for name, getter in outs.items():
            series[name].append(getter(r))

    return MonteCarloResult(n=n - skipped, series=series, skipped=skipped)
