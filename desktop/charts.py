"""matplotlib helpers that give every chart in the app the same look and rules.

The rules are the ones a reader needs to trust a figure: one value axis with
its unit written on it, thin marks on a recessive hairline grid, the largest
values labelled at the tip and the rest left to the axis and the table next to
the chart, a legend whenever two kinds of mark share the plot, and colour that
follows the meaning (burden / credit) rather than the row number.

Every drawing function returns a list of ``(artist, text)`` pairs that
:class:`desktop.widgets.MplCanvas` turns into hover tooltips, so no value is
reachable only by reading the bar's length.
"""

from __future__ import annotations

import matplotlib
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

from . import theme
from .fmt import compact, sig

_DEFAULTS_APPLIED = False


def apply_defaults() -> None:
    """Install the type and colour defaults once per process."""
    global _DEFAULTS_APPLIED
    if _DEFAULTS_APPLIED:
        return
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.titlepad": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
        "legend.frameon": False,
        "axes.edgecolor": theme.CHART_AXIS,
        "axes.labelcolor": theme.CHART_INK_2,
        "xtick.color": theme.CHART_MUTED,
        "ytick.color": theme.CHART_INK_2,
        "text.color": theme.CHART_INK,
        "axes.facecolor": theme.CHART_SURFACE,
        "figure.facecolor": theme.CHART_SURFACE,
        "savefig.facecolor": theme.CHART_SURFACE,
        "axes.grid": False,
        "grid.color": theme.CHART_GRID,
        "grid.linewidth": 0.8,
        "grid.linestyle": "-",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
    })
    _DEFAULTS_APPLIED = True


def style_axes(ax) -> None:
    """Recessive axes: no top/right spine, hairline left/bottom, no tick marks."""
    ax.set_facecolor(theme.CHART_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.CHART_AXIS)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(length=0, pad=4)


def _compact_axis(axis) -> None:
    axis.set_major_formatter(FuncFormatter(lambda v, _pos: compact(v)))


def _label(ax, x, y, text, *, dx=4, ha="left"):
    ax.annotate(text, xy=(x, y), xytext=(dx, 0), textcoords="offset points",
                va="center", ha=ha, fontsize=8.5, color=theme.CHART_INK_2,
                annotation_clip=False)


def barh(ax, labels, values, *, unit: str = "", title: str = "",
         color: str = theme.CHART_PRIMARY, ranked: bool = True, label_top: int = 3,
         share_of: float | None = None, value_fmt=None) -> list:
    """Horizontal bars in one hue.

    ``ranked`` puts the largest value at the top; otherwise the given order is
    kept top-down (a process order, say). The ``label_top`` largest bars get
    their value at the tip, with a share of ``share_of`` when one is given.
    """
    pairs = list(zip(labels, values))
    if ranked:
        pairs.sort(key=lambda kv: kv[1])       # barh draws bottom-up
    else:
        pairs = pairs[::-1]
    names = [str(p[0]) for p in pairs]
    vals = [float(p[1]) for p in pairs]
    if not vals:
        return []
    bars = ax.barh(names, vals, color=color, height=0.62,
                   edgecolor=theme.CHART_SURFACE, linewidth=1.0)
    ax.grid(True, axis="x")
    ax.spines["left"].set_visible(False)
    ax.set_xlabel(unit)
    if title:
        ax.set_title(title)
    _compact_axis(ax.xaxis)
    fmt = value_fmt or (lambda v: sig(v, 3))
    top = set(sorted(range(len(vals)), key=lambda i: abs(vals[i]), reverse=True)[:label_top])
    span = max(abs(v) for v in vals) or 1.0
    lo = min(0.0, min(vals))
    ax.set_xlim(lo * 1.18 if lo < 0 else 0.0, span * 1.22)
    hover = []
    for i, (rect, name, v) in enumerate(zip(bars, names, vals)):
        text = fmt(v)
        if share_of:
            text += f" ({v / share_of * 100:.0f}%)"
        hover.append((rect, f"{name}: {text} {unit}".strip()))
        if i in top:
            _label(ax, v, rect.get_y() + rect.get_height() / 2, text)
    ax.margins(y=0.06)
    return hover


def diverging_barh(ax, labels, values, *, unit: str = "", title: str = "",
                   net: float | None = None, net_label: str = "net",
                   burden_label: str = "Burden", credit_label: str = "Credit") -> list:
    """Contributions above and below zero: burdens in red, credits in blue.

    Burdens are ranked largest-first at the top, credits below them. The net
    total is drawn as a hairline with its value, so the eye can add the bars
    and check it.
    """
    pairs = sorted(zip(labels, values), key=lambda kv: kv[1])
    names = [str(p[0]) for p in pairs]
    vals = [float(p[1]) for p in pairs]
    if not vals:
        return []
    colors = [theme.CREDIT if v < 0 else theme.BURDEN for v in vals]
    bars = ax.barh(names, vals, color=colors, height=0.62,
                   edgecolor=theme.CHART_SURFACE, linewidth=1.0)
    ax.grid(True, axis="x")
    ax.spines["left"].set_visible(False)
    ax.axvline(0, color=theme.CHART_AXIS, linewidth=0.8)
    ax.set_xlabel(unit)
    if title:
        ax.set_title(title)
    _compact_axis(ax.xaxis)
    hi = max(max(vals), 0.0)
    lo = min(min(vals), 0.0)
    if net is not None:
        hi = max(hi, net)
        lo = min(lo, net)
    span = (hi - lo) or 1.0
    ax.set_xlim(lo - span * 0.22, hi + span * 0.22)
    hover = []
    burdens = [i for i, v in enumerate(vals) if v > 0]
    credits = [i for i, v in enumerate(vals) if v < 0]
    marked = set()
    if burdens:
        marked.add(max(burdens, key=lambda i: vals[i]))
    if credits:
        marked.add(min(credits, key=lambda i: vals[i]))
    for i, (rect, name, v) in enumerate(zip(bars, names, vals)):
        text = sig(v, 3)
        hover.append((rect, f"{name}: {text} {unit}".strip()))
        if i in marked:
            y = rect.get_y() + rect.get_height() / 2
            if v >= 0:
                _label(ax, v, y, text)
            else:
                _label(ax, v, y, text, dx=-4, ha="right")
    if net is not None:
        # The net line is labelled at the foot of the plot: the top row holds
        # the largest burden and its own label.
        ax.axvline(net, color=theme.CHART_INK, linewidth=1.0)
        ax.annotate(f"{net_label} {sig(net, 3)}", xy=(net, 0.0), xycoords=("data", "axes fraction"),
                    xytext=(4, 2), textcoords="offset points", va="bottom", ha="left",
                    fontsize=8.5, color=theme.CHART_INK)
    handles = []
    if burdens:
        handles.append(Patch(color=theme.BURDEN, label=burden_label))
    if credits:
        handles.append(Patch(color=theme.CREDIT, label=credit_label))
    if len(handles) > 1:
        # Burdens sit at the top and reach right, credits at the bottom and reach
        # left, so the upper-left corner is the one place nothing is drawn.
        ax.legend(handles=handles, loc="upper left")
    ax.margins(y=0.06)
    return hover


def line(ax, xs, ys, *, xlabel: str, ylabel: str, title: str = "",
         nominal: float | None = None, nominal_label: str = "current case",
         color: str = theme.CHART_PRIMARY) -> list:
    """One series over a swept input, with the current case marked."""
    xs = [float(x) for x in xs]
    ys = [float(y) for y in ys]
    if not xs:
        return []
    (series,) = ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=6.5,
                        markerfacecolor=color, markeredgecolor=theme.CHART_SURFACE,
                        markeredgewidth=1.5, solid_joinstyle="round", solid_capstyle="round")
    ax.grid(True, axis="y")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    _compact_axis(ax.xaxis)
    _compact_axis(ax.yaxis)
    if min(ys) < 0 < max(ys):
        ax.axhline(0, color=theme.CHART_AXIS, linewidth=0.8)
    if nominal is not None and min(xs) <= nominal <= max(xs):
        ax.axvline(nominal, color=theme.CHART_EMPHASIS_GRAY, linewidth=1.0)
        ax.annotate(nominal_label, xy=(nominal, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(4, -2), textcoords="offset points", va="top", ha="left",
                    fontsize=8.5, color=theme.CHART_MUTED)
    _label(ax, xs[-1], ys[-1], sig(ys[-1], 3), dx=8)
    ax.margins(x=0.08, y=0.12)

    def _text(details) -> str:
        idx = details.get("ind", [])
        if len(idx) == 0:
            return ""
        i = int(idx[0])
        return f"{xlabel}: {sig(xs[i], 3)}\n{ylabel}: {sig(ys[i], 3)}"

    return [(series, _text)]


def histogram(ax, values, *, xlabel: str, title: str = "",
              percentiles: dict | None = None, color: str = theme.CHART_PRIMARY) -> list:
    """A distribution of Monte Carlo draws, with named percentiles as hairlines."""
    values = [float(v) for v in values]
    if not values:
        return []
    counts, edges, patches = ax.hist(values, bins=30, color=color,
                                     edgecolor=theme.CHART_SURFACE, linewidth=1.0)
    ax.grid(True, axis="y")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("draws")
    if title:
        ax.set_title(title)
    _compact_axis(ax.xaxis)
    ymax = max(counts) if len(counts) else 1
    for name, value in (percentiles or {}).items():
        ax.axvline(value, color=theme.CHART_INK if name.upper() == "P50" else theme.CHART_MUTED,
                   linewidth=1.0)
        ax.annotate(f"{name} {sig(value, 3)}", xy=(value, ymax), xytext=(3, 2),
                    textcoords="offset points", fontsize=8, color=theme.CHART_INK_2,
                    ha="left", va="bottom", rotation=0, annotation_clip=False)
    ax.margins(y=0.18)
    hover = []
    for rect, lo, hi, n in zip(patches, edges[:-1], edges[1:], counts):
        hover.append((rect, f"{sig(lo, 3)} to {sig(hi, 3)}: {int(n)} draws"))
    return hover
