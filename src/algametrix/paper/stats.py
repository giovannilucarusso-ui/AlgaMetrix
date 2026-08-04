"""Spread statistics with explicit, printed conventions.

Two rules that the previous version of this analysis did not enforce:

1. **A ratio is never computed across zero or a negative value.** A cradle-to-gate
   GWP set that contains a carbon-neutral or net-negative point has no meaningful
   max/min ratio; the honest summary is an absolute range, or a ratio over the
   explicitly positive subset with the denominator convention written out.
2. **Every statistic reports its n and which member defines each extreme**, so a
   change in a spread can be attributed to a change in values or a change in
   membership.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (``numpy.percentile`` default), q in 0-100."""
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[int(pos)]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


#: Below this many points a 90th/10th percentile ratio interpolates so heavily
#: between the two extreme observations that it carries no information beyond
#: max/min. Reported as ``None`` with a stated reason instead.
MIN_N_FOR_P90_P10 = 8


@dataclass
class Spread:
    """Descriptive statistics of one stage of one cohort."""

    label: str
    ids: tuple[str, ...]
    values: tuple[float, ...]
    n: int = 0
    minimum: float = 0.0
    maximum: float = 0.0
    min_id: str = ""
    max_id: str = ""
    median: float = 0.0
    q1: float = 0.0
    q3: float = 0.0
    iqr: float = 0.0
    geometric_mean: float | None = None
    max_min_ratio: float | None = None
    p90_p10_ratio: float | None = None
    absolute_range: float = 0.0
    n_nonpositive: int = 0
    ratio_convention: str = ""
    notes: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return format_spread(self)


def compute_spread(label: str, pairs: list[tuple[str, float]]) -> Spread:
    """Descriptive statistics for ``[(study_id, value), ...]``.

    ``pairs`` must already be the cohort you intend to describe: this function
    never filters. Non-positive values are kept in every location statistic and
    excluded only from the ratios, which is stated in ``ratio_convention``.
    """
    if not pairs:
        return Spread(label=label, ids=(), values=(), n=0,
                      ratio_convention="undefined (empty cohort)",
                      notes=["empty cohort"])

    ordered = sorted(pairs, key=lambda p: p[1])
    ids = tuple(p[0] for p in ordered)
    vals = tuple(float(p[1]) for p in ordered)
    sorted_vals = list(vals)

    n = len(vals)
    minimum, maximum = vals[0], vals[-1]
    positives = [(i, v) for i, v in zip(ids, vals) if v > 0]
    n_nonpositive = n - len(positives)

    sp = Spread(
        label=label,
        ids=ids,
        values=vals,
        n=n,
        minimum=minimum,
        maximum=maximum,
        min_id=ids[0],
        max_id=ids[-1],
        median=_percentile(sorted_vals, 50),
        q1=_percentile(sorted_vals, 25),
        q3=_percentile(sorted_vals, 75),
        absolute_range=maximum - minimum,
        n_nonpositive=n_nonpositive,
    )
    sp.iqr = sp.q3 - sp.q1

    # --- ratios: only over strictly positive values -----------------------
    if n_nonpositive:
        sp.notes.append(
            f"{n_nonpositive} value(s) <= 0: ratios are computed over the "
            f"{len(positives)} strictly positive value(s) only, and the absolute "
            f"range is the primary summary."
        )
    if len(positives) >= 2:
        pos_vals = sorted(v for _, v in positives)
        pos_ids = [i for i, _ in sorted(positives, key=lambda p: p[1])]
        sp.max_min_ratio = pos_vals[-1] / pos_vals[0]
        sp.ratio_convention = (
            f"max/min over strictly positive values: "
            f"{pos_ids[-1]} ({pos_vals[-1]:g}) / {pos_ids[0]} ({pos_vals[0]:g})"
        )
        sp.geometric_mean = math.exp(sum(math.log(v) for v in pos_vals) / len(pos_vals))
        if n >= MIN_N_FOR_P90_P10:
            p10 = _percentile(pos_vals, 10)
            p90 = _percentile(pos_vals, 90)
            if p10 > 0:
                sp.p90_p10_ratio = p90 / p10
        else:
            sp.notes.append(
                f"P90/P10 not reported: n={n} < {MIN_N_FOR_P90_P10}, the percentiles "
                "would interpolate between the two extreme observations."
            )
    else:
        sp.ratio_convention = "undefined (fewer than two strictly positive values)"
        sp.notes.append("no ratio is defined for this cohort")
    return sp


def format_spread(sp: Spread, unit: str = "", indent: str = "  ") -> str:
    """Multi-line human-readable rendering, including the ratio convention."""
    u = f" {unit}" if unit else ""
    if sp.n == 0:
        return f"{indent}{sp.label}: empty cohort"
    lines = [
        f"{indent}{sp.label}",
        f"{indent}  n                 : {sp.n}",
        f"{indent}  min               : {sp.minimum:,.4g}{u}   [{sp.min_id}]",
        f"{indent}  max               : {sp.maximum:,.4g}{u}   [{sp.max_id}]",
        f"{indent}  absolute range    : {sp.absolute_range:,.4g}{u}",
        f"{indent}  median            : {sp.median:,.4g}{u}",
        f"{indent}  IQR (Q1-Q3)       : {sp.iqr:,.4g}{u}   "
        f"({sp.q1:,.4g} - {sp.q3:,.4g})",
    ]
    lines.append(
        f"{indent}  geometric mean    : "
        + (f"{sp.geometric_mean:,.4g}{u}" if sp.geometric_mean is not None else "n/a")
    )
    lines.append(
        f"{indent}  max/min ratio     : "
        + (f"{sp.max_min_ratio:,.4g}x" if sp.max_min_ratio is not None else "n/a")
    )
    lines.append(
        f"{indent}  P90/P10 ratio     : "
        + (f"{sp.p90_p10_ratio:,.4g}x" if sp.p90_p10_ratio is not None else "n/a")
    )
    lines.append(f"{indent}  ratio convention  : {sp.ratio_convention}")
    for note in sp.notes:
        lines.append(f"{indent}  note              : {note}")
    return "\n".join(lines)


@dataclass
class PairedChange:
    """Study-level change between two stages evaluated on the same study."""

    study_id: str
    before: float
    after: float

    @property
    def absolute(self) -> float:
        return self.after - self.before

    @property
    def relative(self) -> float | None:
        if self.before == 0:
            return None
        return self.after / self.before - 1.0


def paired_changes(
    before: list[tuple[str, float]], after: list[tuple[str, float]]
) -> list[PairedChange]:
    """Per-study change; raises if the two stages do not cover the same studies."""
    b = dict(before)
    a = dict(after)
    if set(b) != set(a):
        raise ValueError(
            "paired_changes requires identical study sets; "
            f"only before: {sorted(set(b) - set(a))}; "
            f"only after: {sorted(set(a) - set(b))}"
        )
    return [PairedChange(sid, b[sid], a[sid]) for sid in sorted(b)]
