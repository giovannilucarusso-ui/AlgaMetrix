"""Variance-based global sensitivity analysis (Sobol indices).

Why this module replaces the previous one
-----------------------------------------
The committed ``results/sensitivity.txt`` contains first-order indices of 1.13
and 1.81 and a first-order index of -0.15. A first-order Sobol index is a
fraction of the output variance: it lies in [0, 1], and it can never exceed the
corresponding total-order index. Those values are not noisy estimates of a
correct quantity - they indicate an estimator or a sampling scheme that is not
computing Sobol indices at all. Nothing derived from them can be reported.

What is implemented
-------------------
The standard Saltelli cross-sampling design with the estimators recommended by
Saltelli et al. (2010), *Comput. Phys. Commun.* 181:259-270:

    S_i  = (1/N) sum_j  f(B)_j [ f(AB_i)_j - f(A)_j ]  / Var(Y)      (Eq. b)
    ST_i = (1/2N) sum_j [ f(A)_j - f(AB_i)_j ]^2       / Var(Y)      (Jansen)

with

* A and B drawn from a scrambled Sobol' sequence (``scipy.stats.qmc``), so N
  should be a power of two;
* AB_i equal to A with column i replaced by column i of B;
* N(k+2) model evaluations in total;
* Var(Y) taken over the pooled A and B outputs;
* bootstrap confidence intervals by resampling the N rows jointly, which keeps
  the A/B/AB pairing intact;
* rows containing a non-finite output dropped jointly across all matrices, with
  the count reported rather than silently absorbed.

Every result carries the sample size, the seed, the number of dropped rows and a
bootstrap interval. Estimates are *not* clipped into [0, 1]: a negative estimate
is information about convergence and hiding it would hide exactly the failure
that motivated this rewrite.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

#: Default bootstrap replicates for the confidence intervals.
DEFAULT_BOOTSTRAP = 500

#: Convergence gate: an S1 point estimate this far above 1, or this far below 0,
#: is treated as an implementation or sample-size failure rather than noise.
INDEX_TOLERANCE = 0.05


@dataclass
class Parameter:
    """One uncertain input, sampled uniformly on ``[low, high]``."""

    name: str
    low: float
    high: float
    group: str = ""          # "foreground" | "economic" | "lcia_background"
    unit: str = ""
    source: str = ""

    def map_unit(self, u: np.ndarray) -> np.ndarray:
        return self.low + u * (self.high - self.low)


@dataclass
class IndexEstimate:
    """One index with its bootstrap interval."""

    name: str
    value: float
    ci_low: float
    ci_high: float

    @property
    def ci_width(self) -> float:
        return self.ci_high - self.ci_low


@dataclass
class SobolResult:
    """First- and total-order indices for one output."""

    output: str
    parameters: list[str]
    n_base: int
    n_evaluations: int
    seed: int
    s1: list[IndexEstimate] = field(default_factory=list)
    st: list[IndexEstimate] = field(default_factory=list)
    variance: float = 0.0
    mean: float = 0.0
    dropped_rows: int = 0
    runtime_s: float = 0.0
    bootstrap: int = DEFAULT_BOOTSTRAP

    def ranked(self) -> list[tuple[str, IndexEstimate, IndexEstimate]]:
        """(name, S1, ST) sorted by descending ST."""
        rows = list(zip(self.parameters, self.s1, self.st))
        return sorted(rows, key=lambda r: r[2].value, reverse=True)

    def ranking(self) -> list[str]:
        return [name for name, _, _ in self.ranked()]

    def violations(self, tol: float = INDEX_TOLERANCE) -> list[str]:
        """Point estimates that are impossible for a Sobol index, beyond ``tol``."""
        out = []
        for name, s1, st in zip(self.parameters, self.s1, self.st):
            if s1.value > 1 + tol:
                out.append(f"S1[{name}]={s1.value:.3f} > 1")
            if s1.value < -tol:
                out.append(f"S1[{name}]={s1.value:.3f} < 0")
            if st.value > 1 + tol:
                out.append(f"ST[{name}]={st.value:.3f} > 1")
            if st.value < -tol:
                out.append(f"ST[{name}]={st.value:.3f} < 0")
            if s1.value > st.value + tol:
                out.append(f"S1[{name}]={s1.value:.3f} > ST[{name}]={st.value:.3f}")
        return out

    @property
    def converged(self) -> bool:
        return not self.violations()


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------

def saltelli_matrices(
    k: int, n_base: int, seed: int
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Return ``(A, B, [AB_0 ... AB_{k-1}])`` on the unit hypercube.

    A and B are the two halves of a single scrambled Sobol' sequence of length
    ``2 * n_base`` in ``2k`` dimensions, which is what keeps the two samples
    independent while both remain low-discrepancy.
    """
    from scipy.stats import qmc

    if n_base & (n_base - 1):
        raise ValueError(
            f"n_base={n_base} is not a power of two; a Sobol' sequence loses its "
            "balance properties otherwise"
        )
    sampler = qmc.Sobol(d=2 * k, scramble=True, seed=seed)
    pts = sampler.random(n_base)
    A = pts[:, :k]
    B = pts[:, k:]
    AB = []
    for i in range(k):
        m = A.copy()
        m[:, i] = B[:, i]
        AB.append(m)
    return A, B, AB


def _evaluate(model: Callable[[np.ndarray], np.ndarray], X: np.ndarray) -> np.ndarray:
    y = np.asarray(model(X), dtype=float)
    if y.shape[0] != X.shape[0]:
        raise ValueError(f"model returned {y.shape[0]} values for {X.shape[0]} rows")
    return y


# --------------------------------------------------------------------------
# Estimators
# --------------------------------------------------------------------------

def _indices(fA: np.ndarray, fB: np.ndarray, fAB: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Saltelli (2010) S1 and Jansen ST from paired evaluations.

    ``fAB`` has shape ``(N, k)``. Variance is taken over the pooled A and B
    outputs, which is the estimator SALib uses and is less noisy than using A
    alone.
    """
    pooled = np.concatenate([fA, fB])
    var = float(np.var(pooled, ddof=0))
    if var <= 0:
        k = fAB.shape[1]
        return np.zeros(k), np.zeros(k), 0.0
    s1 = np.mean(fB[:, None] * (fAB - fA[:, None]), axis=0) / var
    st = 0.5 * np.mean((fA[:, None] - fAB) ** 2, axis=0) / var
    return s1, st, var


def _bootstrap_ci(
    fA: np.ndarray,
    fB: np.ndarray,
    fAB: np.ndarray,
    replicates: int,
    seed: int,
    alpha: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Percentile bootstrap over jointly resampled rows."""
    rng = np.random.default_rng(seed + 1)
    n, k = fAB.shape
    s1_boot = np.empty((replicates, k))
    st_boot = np.empty((replicates, k))
    for b in range(replicates):
        idx = rng.integers(0, n, size=n)
        s1_b, st_b, _ = _indices(fA[idx], fB[idx], fAB[idx])
        s1_boot[b] = s1_b
        st_boot[b] = st_b
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    return (
        np.percentile(s1_boot, lo, axis=0),
        np.percentile(s1_boot, hi, axis=0),
        np.percentile(st_boot, lo, axis=0),
        np.percentile(st_boot, hi, axis=0),
    )


def analyze(
    parameters: Sequence[Parameter],
    model: Callable[[np.ndarray], np.ndarray],
    n_base: int,
    seed: int,
    output_name: str = "output",
    bootstrap: int = DEFAULT_BOOTSTRAP,
) -> SobolResult:
    """Full Sobol analysis of ``model`` over ``parameters``.

    ``model`` receives an ``(m, k)`` array of parameter values (already mapped
    out of the unit hypercube) and returns ``m`` outputs. It may return
    non-finite values; rows containing any are dropped from every matrix
    together and counted.
    """
    t0 = time.perf_counter()
    k = len(parameters)
    A_u, B_u, AB_u = saltelli_matrices(k, n_base, seed)

    def to_real(U: np.ndarray) -> np.ndarray:
        X = np.empty_like(U)
        for i, p in enumerate(parameters):
            X[:, i] = p.map_unit(U[:, i])
        return X

    fA = _evaluate(model, to_real(A_u))
    fB = _evaluate(model, to_real(B_u))
    fAB = np.column_stack([_evaluate(model, to_real(M)) for M in AB_u])

    finite = np.isfinite(fA) & np.isfinite(fB) & np.all(np.isfinite(fAB), axis=1)
    dropped = int((~finite).sum())
    fA, fB, fAB = fA[finite], fB[finite], fAB[finite]
    if fA.size < 8:
        raise ValueError(
            f"only {fA.size} finite rows remain out of {n_base}; the model is failing "
            "over most of the sampled space"
        )

    s1, st, var = _indices(fA, fB, fAB)
    s1_lo, s1_hi, st_lo, st_hi = _bootstrap_ci(fA, fB, fAB, bootstrap, seed)

    names = [p.name for p in parameters]
    return SobolResult(
        output=output_name,
        parameters=names,
        n_base=n_base,
        n_evaluations=n_base * (k + 2),
        seed=seed,
        s1=[IndexEstimate(n, float(v), float(lo), float(hi))
            for n, v, lo, hi in zip(names, s1, s1_lo, s1_hi)],
        st=[IndexEstimate(n, float(v), float(lo), float(hi))
            for n, v, lo, hi in zip(names, st, st_lo, st_hi)],
        variance=var,
        mean=float(np.mean(np.concatenate([fA, fB]))),
        dropped_rows=dropped,
        runtime_s=time.perf_counter() - t0,
        bootstrap=bootstrap,
    )


# --------------------------------------------------------------------------
# Synthetic benchmarks with known analytical indices
# --------------------------------------------------------------------------

@dataclass
class Benchmark:
    """A test function whose Sobol indices are known in closed form."""

    name: str
    parameters: list[Parameter]
    model: Callable[[np.ndarray], np.ndarray]
    s1_exact: list[float]
    st_exact: list[float]
    description: str = ""


def ishigami(a: float = 7.0, b: float = 0.1) -> Benchmark:
    """Ishigami function - the standard non-monotonic, interacting test case.

    ``f = sin(x1) + a sin^2(x2) + b x3^4 sin(x1)``, ``xi ~ U(-pi, pi)``.
    x3 has zero first-order effect but a non-zero total effect through its
    interaction with x1, which is exactly what a first-order-only method misses.
    """
    pi = math.pi
    v1 = 0.5 * (1 + b * pi ** 4 / 5) ** 2
    v2 = a ** 2 / 8
    v13 = 8 * b ** 2 * pi ** 8 / 225
    var = v1 + v2 + v13
    s1 = [v1 / var, v2 / var, 0.0]
    st = [(v1 + v13) / var, v2 / var, v13 / var]

    def model(X: np.ndarray) -> np.ndarray:
        x1, x2, x3 = X[:, 0], X[:, 1], X[:, 2]
        return np.sin(x1) + a * np.sin(x2) ** 2 + b * x3 ** 4 * np.sin(x1)

    params = [Parameter(f"x{i+1}", -pi, pi) for i in range(3)]
    return Benchmark("ishigami", params, model, s1, st,
                     f"Ishigami (a={a}, b={b}); x3 acts only through interaction with x1")


def additive_linear(coefficients: Sequence[float] = (1.0, 2.0, 3.0, 4.0)) -> Benchmark:
    """Purely additive: ``f = sum c_i x_i``, ``xi ~ U(0, 1)``.

    S1 == ST == c_i^2 / sum c_j^2 for every input, and they must sum to 1.
    Detects a scaling or variance-normalisation error immediately.
    """
    c = np.asarray(coefficients, dtype=float)
    shares = list((c ** 2) / float(np.sum(c ** 2)))

    def model(X: np.ndarray) -> np.ndarray:
        return X @ c

    params = [Parameter(f"x{i+1}", 0.0, 1.0) for i in range(len(c))]
    return Benchmark("additive_linear", params, model, shares, shares,
                     "additive linear; first-order indices must sum to 1")


def interaction_only() -> Benchmark:
    """Pure interaction: ``f = x1 * x2``, ``xi ~ U(-1, 1)``.

    Both first-order indices are exactly 0 and both total indices exactly 1.
    A method that reports a non-zero S1 here is confusing correlation of the
    sample with a main effect.
    """
    def model(X: np.ndarray) -> np.ndarray:
        return X[:, 0] * X[:, 1]

    params = [Parameter("x1", -1.0, 1.0), Parameter("x2", -1.0, 1.0)]
    return Benchmark("interaction_only", params, model, [0.0, 0.0], [1.0, 1.0],
                     "pure interaction; S1 = 0 and ST = 1 for both inputs")


BENCHMARKS: list[Callable[[], Benchmark]] = [
    ishigami,
    additive_linear,
    interaction_only,
]


@dataclass
class BenchmarkOutcome:
    benchmark: str
    n_base: int
    seed: int
    parameters: list[str]
    s1_exact: list[float]
    st_exact: list[float]
    result: SobolResult
    reference: dict | None = None      # SALib estimates, when SALib is installed

    @property
    def s1_abs_error(self) -> list[float]:
        return [abs(e.value - x) for e, x in zip(self.result.s1, self.s1_exact)]

    @property
    def st_abs_error(self) -> list[float]:
        return [abs(e.value - x) for e, x in zip(self.result.st, self.st_exact)]

    @property
    def max_abs_error(self) -> float:
        return max(self.s1_abs_error + self.st_abs_error)


def run_benchmark(
    benchmark: Benchmark, n_base: int, seed: int, bootstrap: int = DEFAULT_BOOTSTRAP
) -> BenchmarkOutcome:
    res = analyze(benchmark.parameters, benchmark.model, n_base, seed,
                  output_name=benchmark.name, bootstrap=bootstrap)
    return BenchmarkOutcome(
        benchmark=benchmark.name,
        n_base=n_base,
        seed=seed,
        parameters=[p.name for p in benchmark.parameters],
        s1_exact=list(benchmark.s1_exact),
        st_exact=list(benchmark.st_exact),
        result=res,
        reference=salib_reference(benchmark, n_base, seed),
    )


def _salib_version() -> str:
    try:
        from importlib.metadata import version
        return version("SALib")
    except Exception:  # pragma: no cover - environment dependent
        return "unknown"


def salib_available() -> bool:
    try:
        import SALib  # noqa: F401
        return True
    except Exception:
        return False


def salib_reference(benchmark: Benchmark, n_base: int, seed: int) -> dict | None:
    """Independent estimates from SALib, if it is installed.

    SALib is deliberately *not* a runtime dependency of AlgaMetrix. It is used
    here only as an external check on the internal estimator, and the comparison
    is reproducible with::

        pip install SALib
        python reproduce.py --only sobol

    Returns ``None`` when SALib is absent, and the report says so.
    """
    if not salib_available():
        return None
    try:
        from SALib.analyze import sobol as salib_sobol
        from SALib.sample import sobol as salib_sample

        problem = {
            "num_vars": len(benchmark.parameters),
            "names": [p.name for p in benchmark.parameters],
            "bounds": [[p.low, p.high] for p in benchmark.parameters],
        }
        X = salib_sample.sample(problem, n_base, calc_second_order=False, seed=seed)
        Y = benchmark.model(X)
        out = salib_sobol.analyze(problem, Y, calc_second_order=False, seed=seed,
                                  print_to_console=False)
        return {
            "library": "SALib",
            "version": _salib_version(),
            "S1": [float(v) for v in out["S1"]],
            "ST": [float(v) for v in out["ST"]],
            "S1_conf": [float(v) for v in out["S1_conf"]],
            "ST_conf": [float(v) for v in out["ST_conf"]],
        }
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"library": "SALib", "error": repr(exc)}


# --------------------------------------------------------------------------
# Convergence
# --------------------------------------------------------------------------

@dataclass
class ConvergenceRow:
    n_base: int
    n_evaluations: int
    runtime_s: float
    result: SobolResult
    max_ci_width_dominant: float = 0.0
    max_abs_shift_vs_largest: float | None = None
    ranking_matches_largest: bool | None = None


def convergence_study(
    parameters: Sequence[Parameter],
    model: Callable[[np.ndarray], np.ndarray],
    sizes: Sequence[int],
    seed: int,
    output_name: str = "output",
    bootstrap: int = DEFAULT_BOOTSTRAP,
    dominant_top_n: int = 2,
) -> list[ConvergenceRow]:
    """Run the analysis at increasing base sample sizes and compare to the largest."""
    rows = [
        ConvergenceRow(
            n_base=n,
            n_evaluations=n * (len(parameters) + 2),
            runtime_s=0.0,
            result=analyze(parameters, model, n, seed, output_name, bootstrap),
        )
        for n in sorted(sizes)
    ]
    for row in rows:
        row.runtime_s = row.result.runtime_s
        top = row.result.ranked()[:dominant_top_n]
        row.max_ci_width_dominant = max((st.ci_width for _, _, st in top), default=0.0)

    largest = rows[-1].result
    ref_st = {name: e.value for name, e in zip(largest.parameters, largest.st)}
    ref_rank = largest.ranking()
    for row in rows:
        st_now = {name: e.value for name, e in zip(row.result.parameters, row.result.st)}
        row.max_abs_shift_vs_largest = max(
            abs(st_now[n] - ref_st[n]) for n in ref_st
        )
        row.ranking_matches_largest = row.result.ranking() == ref_rank
    return rows


def smallest_converged(
    rows: Sequence[ConvergenceRow],
    max_ci_width: float,
    max_shift: float,
    tol: float = INDEX_TOLERANCE,
) -> ConvergenceRow | None:
    """The smallest sample size meeting every declared convergence criterion.

    Criteria, all of which must hold:

    * no impossible point estimate (S1 or ST outside [0, 1] beyond ``tol``,
      or S1 > ST beyond ``tol``);
    * no materially negative lower bootstrap bound on S1;
    * bootstrap CI width below ``max_ci_width`` for the dominant parameters;
    * total-order estimates within ``max_shift`` of the largest run;
    * the ranking of drivers identical to the largest run.
    """
    for row in rows:
        if row.result.violations(tol):
            continue
        if any(e.ci_low < -tol for e in row.result.s1):
            continue
        if row.max_ci_width_dominant > max_ci_width:
            continue
        if row.max_abs_shift_vs_largest is None or row.max_abs_shift_vs_largest > max_shift:
            continue
        if not row.ranking_matches_largest:
            continue
        return row
    return None
