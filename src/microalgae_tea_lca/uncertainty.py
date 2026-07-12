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

from .models import Scenario
from .scenario import run_scenario
from .sensitivity import OUTPUTS, PARAMETERS, SweepParam


@dataclass
class MonteCarloResult:
    """Sampled output series and their summary statistics."""

    n: int
    series: dict[str, list[float]]              # output name -> sampled values

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
        r = run_scenario(scn)
        for name, getter in outs.items():
            series[name].append(getter(r))

    return MonteCarloResult(n=n, series=series)
