"""Monte-Carlo uncertainty propagation, separated by source of uncertainty.

The question the previous version could not answer
--------------------------------------------------
It perturbed operating parameters and characterization factors together and
reported one P10/P50/P90 band. From that band you cannot tell whether a wide GWP
interval means "we do not know this process" or "we do not know this background
database" - and those have opposite implications for what to do next.

Four modes are therefore run for every archetype and every metric:

``foreground_only``      physical inventory parameters only
``economic_only``        prices, discount rate, labour, scale
``lcia_background_only`` characterization factors only
``joint``                all of the above together

Each is reported with bootstrap confidence intervals on the quantiles, and the
sample size is chosen from a convergence study rather than fixed at 1000.

Correlations
------------
Grouped dependence is implemented (parameters sharing a ``correlation_group``
can be driven by a common uniform draw). It is **off by default** because no
correlation data exist for these systems; the independence assumption is printed
in every report instead of being silent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..models import Scenario
from ..scenario import run_scenario
from .evaluate import GROUP_AFFECTS, OUTPUTS, evaluate_rows
from .parameters import (
    GROUP_BACKGROUND,
    GROUP_ECONOMIC,
    GROUP_FOREGROUND,
    UncertainParameter,
    active,
    by_group,
)

MODE_FOREGROUND = "foreground_only"
MODE_ECONOMIC = "economic_only"
MODE_BACKGROUND = "lcia_background_only"
MODE_JOINT = "joint"

MODES = (MODE_FOREGROUND, MODE_ECONOMIC, MODE_BACKGROUND, MODE_JOINT)

_MODE_GROUPS: dict[str, tuple[str, ...]] = {
    MODE_FOREGROUND: (GROUP_FOREGROUND,),
    MODE_ECONOMIC: (GROUP_ECONOMIC,),
    MODE_BACKGROUND: (GROUP_BACKGROUND,),
    MODE_JOINT: (GROUP_FOREGROUND, GROUP_ECONOMIC, GROUP_BACKGROUND),
}

DEFAULT_QUANTILE_BOOTSTRAP = 400


def mode_parameters(mode: str, scenario: Scenario) -> list[UncertainParameter]:
    params: list[UncertainParameter] = []
    for g in _MODE_GROUPS[mode]:
        params.extend(by_group(g))
    return active(params, scenario)


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------

def sample(
    params: Sequence[UncertainParameter],
    scenario: Scenario,
    n: int,
    seed: int,
    correlated: bool = False,
) -> np.ndarray:
    """``(n, k)`` triangular sample. Reproducible for a given ``(n, seed)``."""
    rng = np.random.default_rng(seed)
    k = len(params)
    X = np.empty((n, k))

    # One independent uniform stream per parameter, or one shared stream per
    # correlation group when grouped dependence is switched on.
    if correlated:
        groups = sorted({p.correlation_group for p in params if p.correlation_group})
        shared = {g: rng.random(n) for g in groups}
    else:
        shared = {}

    for i, p in enumerate(params):
        lo, mode, hi = p.bounds(scenario)
        if hi <= lo:
            X[:, i] = lo
            continue
        u = shared.get(p.correlation_group) if correlated else None
        if u is None:
            u = rng.random(n)
        X[:, i] = _triangular_ppf(u, lo, mode, hi)
    return X


def _triangular_ppf(u: np.ndarray, lo: float, mode: float, hi: float) -> np.ndarray:
    """Inverse CDF of the triangular distribution, so a uniform draw maps to it."""
    c = (mode - lo) / (hi - lo)
    out = np.empty_like(u)
    left = u < c
    out[left] = lo + np.sqrt(u[left] * (hi - lo) * (mode - lo))
    out[~left] = hi - np.sqrt((1 - u[~left]) * (hi - lo) * (hi - mode))
    return out


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass
class QuantileEstimate:
    q: float
    value: float
    ci_low: float
    ci_high: float


@dataclass
class ModeResult:
    """One (archetype, metric, mode) Monte-Carlo run."""

    archetype: str
    metric: str
    mode: str
    n: int
    seed: int
    correlated: bool
    parameters: list[str]
    nominal: float
    p10: QuantileEstimate
    p50: QuantileEstimate
    p90: QuantileEstimate
    variance: float
    mean: float
    n_failed: int = 0
    runtime_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def p90_p10(self) -> float | None:
        """Ratio, or ``None`` when the P10 is not strictly positive."""
        if self.p10.value <= 0:
            return None
        return self.p90.value / self.p10.value

    @property
    def absolute_band(self) -> float:
        return self.p90.value - self.p10.value


def _quantiles_with_ci(
    y: np.ndarray, seed: int, replicates: int
) -> tuple[QuantileEstimate, QuantileEstimate, QuantileEstimate]:
    rng = np.random.default_rng(seed + 7)
    qs = (10.0, 50.0, 90.0)
    point = np.percentile(y, qs)
    boot = np.empty((replicates, 3))
    n = y.size
    for b in range(replicates):
        boot[b] = np.percentile(y[rng.integers(0, n, size=n)], qs)
    lo = np.percentile(boot, 2.5, axis=0)
    hi = np.percentile(boot, 97.5, axis=0)
    return tuple(
        QuantileEstimate(q, float(point[i]), float(lo[i]), float(hi[i]))
        for i, q in enumerate(qs)
    )


def run_mode(
    scenario: Scenario,
    archetype: str,
    metric: str,
    mode: str,
    n: int,
    seed: int,
    correlated: bool = False,
    bootstrap: int = DEFAULT_QUANTILE_BOOTSTRAP,
) -> ModeResult:
    t0 = time.perf_counter()
    params = mode_parameters(mode, scenario)
    getter = OUTPUTS[metric]
    nominal_value = getter(run_scenario(scenario))

    notes: list[str] = []
    if not params:
        notes.append("no active parameter in this group for this archetype")
        y = np.full(1, nominal_value)
        p10, p50, p90 = (QuantileEstimate(q, nominal_value, nominal_value, nominal_value)
                         for q in (10.0, 50.0, 90.0))
        return ModeResult(archetype, metric, mode, 0, seed, correlated, [], nominal_value,
                          p10, p50, p90, 0.0, nominal_value, 0,
                          time.perf_counter() - t0, notes)

    X = sample(params, scenario, n, seed, correlated)
    y = evaluate_rows(scenario, params, X, getter)
    finite = np.isfinite(y)
    n_failed = int((~finite).sum())
    y = y[finite]
    if n_failed:
        notes.append(f"{n_failed} of {n} samples failed to evaluate and were dropped")

    p10, p50, p90 = _quantiles_with_ci(y, seed, bootstrap)

    if mode != MODE_JOINT:
        affects = GROUP_AFFECTS[_MODE_GROUPS[mode][0]]
        # Relative tolerance: a group that cannot influence a metric still leaves
        # floating-point noise in its variance, which is not a wiring error.
        scale = max(abs(float(np.mean(y))), 1e-12) ** 2
        if metric not in affects and float(np.var(y)) > 1e-18 * scale:
            notes.append(
                f"group '{_MODE_GROUPS[mode][0]}' produced variance in '{metric}', which it "
                "should not be able to influence - check the parameter assignment"
            )

    if not correlated:
        notes.append(
            "parameters sampled INDEPENDENTLY; no correlation data exist for these "
            "systems, so this is an assumption, not a finding"
        )

    return ModeResult(
        archetype=archetype, metric=metric, mode=mode, n=n, seed=seed,
        correlated=correlated, parameters=[p.name for p in params],
        nominal=nominal_value, p10=p10, p50=p50, p90=p90,
        variance=float(np.var(y)), mean=float(np.mean(y)),
        n_failed=n_failed, runtime_s=time.perf_counter() - t0, notes=notes,
    )


@dataclass
class Decomposition:
    """All four modes for one (archetype, metric), plus the variance shares."""

    archetype: str
    metric: str
    results: dict[str, ModeResult]

    @property
    def joint(self) -> ModeResult:
        return self.results[MODE_JOINT]

    def variance_shares(self) -> dict[str, float | None]:
        """Each group's variance as a share of the joint variance.

        Shares do not have to sum to 1: with a non-linear model the groups
        interact, and the residual is reported rather than forced away.
        """
        total = self.joint.variance
        out: dict[str, float | None] = {}
        for mode in (MODE_FOREGROUND, MODE_ECONOMIC, MODE_BACKGROUND):
            v = self.results[mode].variance
            out[mode] = (v / total) if total > 0 else None
        if total > 0:
            out["interaction_residual"] = 1.0 - sum(
                self.results[m].variance / total
                for m in (MODE_FOREGROUND, MODE_ECONOMIC, MODE_BACKGROUND)
            )
        else:
            out["interaction_residual"] = None
        return out


def decompose(
    scenario: Scenario,
    archetype: str,
    metric: str,
    n: int,
    seed: int,
    correlated: bool = False,
    bootstrap: int = DEFAULT_QUANTILE_BOOTSTRAP,
) -> Decomposition:
    results = {
        mode: run_mode(scenario, archetype, metric, mode, n, seed, correlated, bootstrap)
        for mode in MODES
    }
    return Decomposition(archetype, metric, results)


# --------------------------------------------------------------------------
# Convergence
# --------------------------------------------------------------------------

@dataclass
class MCConvergenceRow:
    n: int
    p10: float
    p50: float
    p90: float
    p90_p10: float | None
    ci_width_p90: float
    max_rel_shift_vs_largest: float | None = None
    runtime_s: float = 0.0


def quantile_convergence(
    scenario: Scenario,
    archetype: str,
    metric: str,
    mode: str,
    sizes: Sequence[int],
    seed: int,
    bootstrap: int = 200,
) -> list[MCConvergenceRow]:
    rows: list[MCConvergenceRow] = []
    for n in sorted(sizes):
        r = run_mode(scenario, archetype, metric, mode, n, seed, False, bootstrap)
        rows.append(MCConvergenceRow(
            n=n, p10=r.p10.value, p50=r.p50.value, p90=r.p90.value,
            p90_p10=r.p90_p10, ci_width_p90=r.p90.ci_high - r.p90.ci_low,
            runtime_s=r.runtime_s,
        ))
    ref = rows[-1]
    for row in rows:
        shifts = []
        for now, base in ((row.p10, ref.p10), (row.p50, ref.p50), (row.p90, ref.p90)):
            if base != 0:
                shifts.append(abs(now - base) / abs(base))
        row.max_rel_shift_vs_largest = max(shifts) if shifts else None
    return rows


def smallest_converged_n(
    rows: Sequence[MCConvergenceRow], max_rel_shift: float, max_ci_rel_width: float
) -> MCConvergenceRow | None:
    """Smallest n whose quantiles are within tolerance of the largest run."""
    for row in rows:
        if row.max_rel_shift_vs_largest is None or row.max_rel_shift_vs_largest > max_rel_shift:
            continue
        if row.p90 != 0 and row.ci_width_p90 / abs(row.p90) > max_ci_rel_width:
            continue
        return row
    return None
