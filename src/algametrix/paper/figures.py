"""Figure generation. Every figure is written as vector PDF and 600-dpi PNG.

Design rules enforced here, each answering a specific review point:

* Figure 1 separates the three input layers, so prices and characterization
  factors are visibly *not* inputs to the physical balance.
* Figure 2 plots a model/reference **ratio** against a line at 1, keeps range
  checks visually distinct from point predictions, and never puts two functional
  units on one axis.
* Figure 3 shows n at every stage and never draws a line from a full-cohort
  spread into a matched-cohort spread.
* Figure 4 carries bootstrap confidence intervals and is drawn only when the
  Sobol implementation validation passed.
* Figure 5 shows the four uncertainty modes side by side and carries no
  maturity ordering.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.lines import Line2D                  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter  # noqa: E402

DPI = 600

# A restrained, colour-blind-safe palette.
C_FOREGROUND = "#2f6f8f"
C_TEA = "#b8860b"
C_LCA = "#3f7d55"
C_NEUTRAL = "#6b6b6b"
C_WARN = "#a33b3b"
C_JOINT = "#4a4a6a"

plt.rcParams.update({
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 110,
    "savefig.bbox": "tight",
})


def _decade_ticks(lo: float, hi: float) -> list[float]:
    """1-2-5 ticks spanning [lo, hi]. A default log axis over less than a decade
    labels every minor tick as 3x10^1, which collides at this figure width."""
    import math

    ticks = []
    exp = math.floor(math.log10(lo))
    while True:
        for m in (1, 2, 5):
            v = m * 10.0 ** exp
            if lo / 1.6 <= v <= hi * 1.6:
                ticks.append(v)
        if 10.0 ** exp > hi * 1.6:
            break
        exp += 1
    return ticks


def _tidy_log_axis(ax, lo: float, hi: float) -> None:
    ax.set_xscale("log")
    ticks = _decade_ticks(lo, hi)
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    fmt = ScalarFormatter()
    fmt.set_scientific(False)
    ax.xaxis.set_major_formatter(fmt)
    ax.xaxis.set_minor_formatter(NullFormatter())


def _save(fig, outdir: Path, stem: str, tight_bbox: bool = True) -> list[Path]:
    """Write PDF + PNG. ``tight_bbox=False`` keeps the figure's own margins, which
    is what a layout that reserves space for a footnote needs: a tight bounding
    box would crop that reserved band back out and let the text collide."""
    outdir.mkdir(parents=True, exist_ok=True)
    bbox = "tight" if tight_bbox else None
    made = []
    for ext, kw in (("pdf", {}), ("png", {"dpi": DPI})):
        p = outdir / f"{stem}.{ext}"
        fig.savefig(p, bbox_inches=bbox, **kw)
        made.append(p)
    plt.close(fig)
    return made


# ======================================================================
# Figure 1 - architecture
# ======================================================================

def figure1_architecture(outdir: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    def box(x, y, w, h, text, color, alpha=0.12, weight="normal", size=8):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.08", linewidth=1.1,
            edgecolor=color, facecolor=color, alpha=alpha, zorder=1))
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.08", linewidth=1.1,
            edgecolor=color, facecolor="none", zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=size, color="#1a1a1a", zorder=3, fontweight=weight)

    def arrow(x1, y1, x2, y2, color, style="-|>", lw=1.2, ls="-"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                     mutation_scale=11, linewidth=lw,
                                     color=color, linestyle=ls, zorder=4))

    # Layer 1: what enters the physical balance.
    ax.text(5.0, 6.22, "ORGANISM AND PROCESS PARAMETERS", ha="center", fontsize=8.2,
            color=C_FOREGROUND, fontweight="bold")
    box(0.5, 5.15, 9.0, 0.85,
        "strain composition (C, N, P) · productivity · operating days · reactor/pond type\n"
        "harvesting recovery · drying · extraction · plant scale",
        C_FOREGROUND, size=7.2)

    # Layer 2: the balance itself.
    box(2.3, 3.55, 5.4, 0.95,
        "SHARED MASS AND ENERGY BALANCE\nflows per kg of product + annual production",
        C_FOREGROUND, alpha=0.24, weight="bold", size=8.2)
    arrow(5.0, 5.15, 5.0, 4.5, C_FOREGROUND)
    # Kept clear of the two branching arrows rather than centred across them.
    ax.text(9.6, 3.25, "computed ONCE; both layers read it",
            ha="right", va="center", fontsize=7.0, style="italic", color=C_NEUTRAL)

    # Layer 3: the two interpretation layers, each with its own inputs.
    box(0.4, 1.75, 4.3, 1.15,
        "TEA LAYER\nprices · CAPEX factors · labour · installation and indirect\n"
        "factors · depreciation · discount rate · tax",
        C_TEA, size=6.9)
    box(5.3, 1.75, 4.3, 1.15,
        "LCA LAYER\ncharacterization factors · grid mix\n"
        "biogenic-carbon convention · system boundary",
        C_LCA, size=6.9)
    arrow(4.2, 3.55, 2.9, 2.95, C_FOREGROUND)
    arrow(5.8, 3.55, 7.1, 2.95, C_FOREGROUND)

    # Layer 4: outputs.
    box(0.4, 0.45, 4.3, 0.85,
        "production cost · CAPEX\nNPV · IRR · MEPP", C_TEA, alpha=0.24, size=7.4)
    box(5.3, 0.45, 4.3, 0.85,
        "gross GWP · biogenic adjustment · net GWP\nCED · water · land · eutrophication",
        C_LCA, alpha=0.24, size=7.4)
    arrow(2.55, 1.75, 2.55, 1.32, C_TEA)
    arrow(7.45, 1.75, 7.45, 1.32, C_LCA)

    ax.text(5.0, 0.10,
            "prices and characterization factors are NOT inputs to the physical balance",
            ha="center", va="center", fontsize=7.2, style="italic", color=C_NEUTRAL)
    return _save(fig, outdir, "fig1_architecture")


# ======================================================================
# Figure 2 - validation
# ======================================================================

def figure2_validation(rows, blocked, outdir: Path) -> list[Path]:
    point_rows = [r for r in rows if r.comparison_kind == "point" and r.ratio]
    range_rows = [r for r in rows if r.comparison_kind == "range"]
    other_rows = [r for r in rows if r.comparison_kind not in ("point", "range")]

    fig, axes = plt.subplots(
        1, 2, figsize=(7.2, 0.55 * max(len(point_rows), len(range_rows), 3) + 1.6),
        gridspec_kw={"width_ratios": [1.05, 1.0]},
    )
    marker = {"blind": "o", "calibrated": "s", "range": "^", "none": "D"}

    # --- panel a: point reproductions as a ratio -------------------------
    ax = axes[0]
    ax.axvline(1.0, color="#333333", lw=1.0, zorder=1)
    ax.axvspan(0.9, 1.1, color="#333333", alpha=0.07, zorder=0)
    labels = []
    any_bounds = False
    for i, r in enumerate(point_rows):
        color = C_TEA if r.metric == "cost" else C_LCA
        bounds = r.ratio_bounds
        if bounds is not None:
            # A mixed price set has two defensible currency readings; the bar is
            # the interval they span, not a confidence interval.
            any_bounds = True
            ax.plot(bounds, [i, i], color=color, lw=2.2, alpha=0.55,
                    solid_capstyle="butt", zorder=2)
        ax.plot(r.ratio, i, marker.get(r.validation_mode, "o"), color=color,
                markersize=6, markeredgecolor="white", markeredgewidth=0.6, zorder=3)
        labels.append(f"{r.study_id}  [{r.metric}]\n{r.basis_label}")
    ax.set_yticks(range(len(point_rows)))
    ax.set_yticklabels(labels, fontsize=6.4)
    ax.set_xlabel("AlgaMetrix / source  (both in the source's own currency\n"
                  "and price year; dimensionless)")
    ax.set_title("a  point reproductions", loc="left")
    ax.set_xlim(0.5, 1.5)
    ax.invert_yaxis()
    handles = [
        Line2D([], [], marker="o", ls="", color=C_NEUTRAL, label="blind"),
        Line2D([], [], marker="s", ls="", color=C_NEUTRAL, label="calibrated"),
        Line2D([], [], marker="o", ls="", color=C_TEA, label="cost endpoint"),
        Line2D([], [], marker="o", ls="", color=C_LCA, label="GWP endpoint"),
    ]
    if any_bounds:
        handles.append(Line2D([], [], ls="-", lw=2.2, color=C_NEUTRAL, alpha=0.55,
                              label="mixed price set: interval over\nthe two currency readings"))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.22),
              ncol=2, frameon=False)

    # --- panel b: range checks, drawn as envelopes ------------------------
    ax = axes[1]
    labels = []
    for i, r in enumerate(range_rows):
        color = C_TEA if r.metric == "cost" else C_LCA
        lo, hi = r.ref_low, r.ref_high
        span = hi - lo if hi and lo else 1.0
        # Normalise each envelope to 0-1 so different units never share a scale.
        ax.plot([0, 1], [i, i], color=color, lw=6, alpha=0.25, solid_capstyle="butt")
        pos = (r.model - lo) / span if span else 0.5
        inside = r.in_range
        ax.plot(min(max(pos, -0.12), 1.12), i, "^" if inside else "X",
                color=color if inside else C_WARN, markersize=7,
                markeredgecolor="white", markeredgewidth=0.6, zorder=3)
        labels.append(f"{r.study_id}  [{r.metric}]\n{lo:g}-{hi:g} {r.unit}")
    ax.set_yticks(range(len(range_rows)))
    ax.set_yticklabels(labels, fontsize=6.2)
    # Same row pitch as panel a. Without this, two range checks are stretched over
    # the height of twelve point reproductions and read as if they were spread out.
    ax.set_ylim(max(len(point_rows), len(range_rows)) - 0.5, -0.5)
    ax.set_xlim(-0.25, 1.25)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["envelope\nlower bound", "envelope\nupper bound"], fontsize=6.6)
    ax.set_title("b  range plausibility checks (NOT point predictions)", loc="left")
    ax.spines["left"].set_visible(False)

    n_blocked_basis = sum(1 for r in other_rows if r.comparison_kind == "not_comparable")
    note = (
        f"{len(point_rows)} point reproduction(s), {len(range_rows)} range check(s), "
        f"{len(other_rows)} not comparable"
        + (f" (of which {n_blocked_basis} because the engine output and the source value "
           "cannot be brought to one currency and price year)" if n_blocked_basis else "")
        + f". {len(blocked)} declared Tier-B study(ies) cannot be reproduced: scenario "
        "definition missing from the repository."
    )
    fig.text(0.01, -0.02, note, fontsize=6.6, color=C_WARN, va="top")
    fig.tight_layout()
    return _save(fig, outdir, "fig2_validation")


# ======================================================================
# Figure 3 - harmonization
# ======================================================================

def figure3_harmonization(a, b, pops, outdir: Path) -> list[Path]:
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 4.3),
                             gridspec_kw={"width_ratios": [0.95, 1.15, 1.05],
                                          "wspace": 0.50})

    def strip(ax, stages, title, ylabel, color):
        drawn = [(i, sp) for i, (_, sp) in enumerate(stages) if sp.n]
        for i, sp in drawn:
            ax.scatter([i] * sp.n, sp.values, s=16, color=color, alpha=0.55,
                       edgecolor="white", linewidth=0.4, zorder=3)
            ax.plot([i - 0.22, i + 0.22], [sp.median, sp.median], color=color,
                    lw=1.8, zorder=4)
            ax.plot([i, i], [sp.minimum, sp.maximum], color=color, lw=0.8,
                    alpha=0.5, zorder=2)
        ax.set_yscale("log")
        # Reserve headroom above the data so the n / ratio annotations never
        # collide with the points or with the panel title.
        pos = [v for _, sp in drawn for v in sp.values if v > 0]
        if pos:
            ax.set_ylim(min(pos) / 2.2, max(pos) * 6.0)
        for i, sp in drawn:
            ratio = f"{sp.max_min_ratio:,.4g}x" if sp.max_min_ratio else "n/a"
            ax.text(i, 0.985, f"n={sp.n}\n{ratio}", ha="center", va="top",
                    fontsize=6.6, color=color, transform=ax.get_xaxis_transform())
        ax.set_xticks(range(len(stages)))
        ax.set_xticklabels([s[0] for s in stages], fontsize=6.1)
        ax.set_title(title, loc="left", pad=6, fontsize=8.0)
        ax.set_ylabel(ylabel)
        ax.set_xlim(-0.6, len(stages) - 0.4)

    strip(axes[0],
          [("reported,\ncommon currency", a.stage_common_currency),
           (f"price-year\nnorm. {a.target_price_year}", a.stage_price_normalized)],
          "a1  full literature cohort", "production cost (EUR/kg, log)", C_TEA)

    if b.n:
        strip(axes[1],
              [("source\nvalue", b.stage_source_value),
               ("engine,\nsource acct.", b.stage_source_accounting),
               ("engine,\ncommon acct.", b.stage_common_accounting)],
              "a2  matched Tier-B cohort", "", C_TEA)
    else:
        axes[1].axis("off")
    axes[1].text(0.5, -0.30,
                 f"separate analysis: cohort n={b.n}\nnot a continuation of a1",
                 transform=axes[1].transAxes, ha="center", va="top", fontsize=6.4,
                 color=C_WARN, style="italic")

    ax = axes[2]
    gwp_stages = [
        ("published\nliterature", pops.published_spread_net),
        ("executable,\nnative bg", pops.executable_spread_native_gross),
        ("executable,\ncommon bg", pops.executable_spread_common_gross),
    ]
    strip(ax, gwp_stages, "b  GWP populations", "GWP (kg CO$_2$-eq/kg, log)", C_LCA)
    ax.text(0.5, -0.30,
            f"GWP-reproduced subset n={pops.n_reproduced}\n"
            f"{len(pops.blocked)} blocked by missing scenarios",
            transform=ax.transAxes, ha="center", va="top", fontsize=6.4, color=C_WARN,
            style="italic")

    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return _save(fig, outdir, "fig3_harmonization")


# ======================================================================
# Figure 4 - Sobol
# ======================================================================

def figure4_sobol(blocks, mode_key, validated: bool, outdir: Path) -> list[Path]:
    if not validated:
        raise RuntimeError("Figure 4 must not be drawn before the Sobol validation passes")
    n_arch = len(blocks)
    outputs = [r.output for r in blocks[0]["modes"][mode_key]]
    fig, axes = plt.subplots(n_arch, len(outputs),
                             figsize=(7.4, 1.9 * n_arch + 0.9), squeeze=False)
    for i, block in enumerate(blocks):
        for j, res in enumerate(block["modes"][mode_key]):
            ax = axes[i][j]
            ranked = res.ranked()[:6][::-1]
            names = [n for n, _, _ in ranked]
            vals = [st.value for _, _, st in ranked]
            err_lo = [max(st.value - st.ci_low, 0) for _, _, st in ranked]
            err_hi = [max(st.ci_high - st.value, 0) for _, _, st in ranked]
            color = (C_TEA if "cost" in res.output or "NPV" in res.output else C_LCA)
            ax.barh(range(len(names)), vals, xerr=[err_lo, err_hi],
                    color=color, alpha=0.75, height=0.62,
                    error_kw={"ecolor": "#333333", "elinewidth": 0.8, "capsize": 2})
            ax.set_yticks(range(len(names)))
            ax.set_yticklabels(names, fontsize=6.2)
            ax.set_xlim(0, 1.02)
            if i == 0:
                ax.set_title(res.output, fontsize=7.6)
            if j == 0:
                # N differs between archetypes: each was chosen by its own
                # convergence study, so it is labelled per row, not once.
                label = block["archetype_label"].split(" (")[0]
                ax.set_ylabel(f"{label}\nN={res.n_base}", fontsize=6.8)
            if i == n_arch - 1:
                ax.set_xlabel("total-order index $S_T$ (95% CI)", fontsize=7)
            if block["archetype_kind"] == "library_default" and j == 0:
                ax.text(0.02, -0.42, "library-default archetype, not a study",
                        transform=ax.transAxes, fontsize=5.8, color=C_WARN)
    fig.suptitle(f"Sobol total-order indices - mode {mode_key} "
                 "(base sample size N chosen per archetype by convergence)",
                 fontsize=8.5, y=1.0)
    fig.tight_layout()
    return _save(fig, outdir, "fig4_sobol_tornado")


def figure_si_sobol_convergence(conv_blocks, outdir: Path) -> list[Path]:
    fig, axes = plt.subplots(1, len(conv_blocks), figsize=(7.4, 2.6), squeeze=False)
    for j, (title, rows, chosen) in enumerate(conv_blocks):
        ax = axes[0][j]
        top = rows[-1].result.ranking()[:3]
        for name in top:
            xs = [r.n_base for r in rows]
            ys = []
            los = []
            his = []
            for r in rows:
                idx = r.result.parameters.index(name)
                e = r.result.st[idx]
                ys.append(e.value)
                los.append(e.ci_low)
                his.append(e.ci_high)
            ax.plot(xs, ys, marker="o", ms=3, lw=1.0, label=name)
            ax.fill_between(xs, los, his, alpha=0.15)
        if chosen:
            ax.axvline(chosen.n_base, color=C_WARN, ls="--", lw=0.9)
            ax.text(chosen.n_base, 1.02, f"chosen N={chosen.n_base}", fontsize=6,
                    color=C_WARN, ha="center", transform=ax.get_xaxis_transform())
        ax.set_xscale("log", base=2)
        ax.set_ylim(-0.05, 1.05)
        ax.set_xlabel("base sample size N")
        if j == 0:
            ax.set_ylabel("$S_T$ (95% CI band)")
        ax.set_title(title.split(" - ")[0], fontsize=7)
        ax.legend(frameon=False, fontsize=5.8)
    fig.tight_layout()
    return _save(fig, outdir, "figS1_sobol_convergence")


# ======================================================================
# Figure 5 - uncertainty by source
# ======================================================================

def figure5_uncertainty(blocks, outdir: Path) -> list[Path]:
    from .mcuncertainty import MODE_BACKGROUND, MODE_ECONOMIC, MODE_FOREGROUND, MODE_JOINT

    modes = [MODE_FOREGROUND, MODE_ECONOMIC, MODE_BACKGROUND, MODE_JOINT]
    labels = {MODE_FOREGROUND: "foreground", MODE_ECONOMIC: "economic",
              MODE_BACKGROUND: "LCIA background", MODE_JOINT: "joint"}
    colors = {MODE_FOREGROUND: C_FOREGROUND, MODE_ECONOMIC: C_TEA,
              MODE_BACKGROUND: C_LCA, MODE_JOINT: C_JOINT}
    metrics = list(blocks[0]["metrics"].keys())

    # Short names for the bar-chart axis; the full label stays on the band panel.
    def short(block) -> str:
        name = block["archetype_label"].split(" (")[0]
        return {"Open raceway pond": "raceway\npond",
                "Heterotrophic fermenter": "hetero.\nfermenter",
                "LED-assisted tubular PBR": "LED\nPBR"}.get(name, name.replace(" ", "\n"))

    n_rows = len(metrics)
    fig, axes = plt.subplots(n_rows, 2, figsize=(7.4, 2.35 * n_rows + 1.25),
                             squeeze=False,
                             gridspec_kw={"width_ratios": [1.55, 1.0],
                                          "wspace": 0.32, "hspace": 0.62})

    for mi, metric in enumerate(metrics):
        # --- left: P10-P90 band per uncertainty source --------------------
        ax = axes[mi][0]
        for bi, block in enumerate(blocks):
            dec = block["metrics"][metric]
            for k, mode in enumerate(modes):
                res = dec.results[mode]
                y = bi + (k - 1.5) * 0.17
                lo, hi = res.p10.value, res.p90.value
                if hi <= lo:            # a group that cannot move this metric
                    ax.plot(lo, y, "|", color=colors[mode], ms=6, mew=1.4)
                else:
                    ax.plot([lo, hi], [y, y], color=colors[mode], lw=3.4,
                            solid_capstyle="butt", alpha=0.9)
                    ax.plot(res.p50.value, y, "|", color="white", ms=7, mew=1.3)
            ax.plot(dec.joint.nominal, bi + 0.42, "v", color="#222222", ms=4.5,
                    clip_on=False)
        ax.set_yticks(range(len(blocks)))
        ax.set_yticklabels([b["archetype_label"].split(" (")[0] for b in blocks],
                           fontsize=7)
        ax.set_ylim(len(blocks) - 0.45, -0.55)      # inverted, with margin for the marker
        ax.set_xlabel(metric, fontsize=7.5)
        ax.set_title(f"{'ab'[mi]}1  P10-P90 by uncertainty source", loc="left", fontsize=8)
        # Log axis whenever every band is strictly positive: the archetypes span an
        # order of magnitude and a linear axis hides the narrow ones entirely.
        p10s = [block["metrics"][metric].results[m].p10.value
                for block in blocks for m in modes]
        p90s = [block["metrics"][metric].results[m].p90.value
                for block in blocks for m in modes]
        if min(p10s) > 0:
            _tidy_log_axis(ax, min(p10s), max(p90s))

        # --- right: variance decomposition --------------------------------
        ax = axes[mi][1]
        bottoms = [0.0] * len(blocks)
        for mode in (MODE_FOREGROUND, MODE_ECONOMIC, MODE_BACKGROUND):
            vals = []
            for block in blocks:
                s = block["metrics"][metric].conditional_variance_ratios().get(mode)
                vals.append(max(0.0, min(s or 0.0, 1.0)))
            ax.bar(range(len(blocks)), vals, 0.62, bottom=bottoms,
                   color=colors[mode], alpha=0.9)
            # Label a slice in place once it is thick enough to hold text.
            for x, (v, b) in enumerate(zip(vals, bottoms)):
                if v >= 0.16:
                    ax.text(x, b + v / 2, f"{v:.0%}", ha="center", va="center",
                            fontsize=6, color="white", fontweight="bold")
            bottoms = [b + v for b, v in zip(bottoms, vals)]
        ax.set_xticks(range(len(blocks)))
        ax.set_xticklabels([short(b) for b in blocks], fontsize=6.6)
        ax.set_ylabel("share of joint variance", fontsize=7.5)
        ax.set_ylim(0, 1.08)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_title(f"{'ab'[mi]}2  variance decomposition", loc="left", fontsize=8)

    # One shared legend for the whole figure, outside every axes.
    fig.legend(
        handles=[Line2D([], [], color=colors[m], lw=3.4, label=labels[m]) for m in modes]
        + [Line2D([], [], marker="v", ls="", color="#222222", label="nominal")],
        loc="lower center", bbox_to_anchor=(0.5, 0.955), ncol=5, frameon=False,
        fontsize=7, handlelength=1.6, columnspacing=1.6,
    )
    fig.text(0.5, 0.012,
             "Archetypes are shown in a fixed order for readability: no maturity ordering "
             "is implied and none is tested here.\nThe LED PBR is a library-default "
             "configuration, not a published plant.",
             fontsize=6.5, color=C_WARN, ha="center", va="bottom")
    fig.tight_layout(rect=(0, 0.06, 1, 0.945))
    return _save(fig, outdir, "fig5_uncertainty")


# ======================================================================
# Driver
# ======================================================================

def build_all(run, outdir: Path) -> list[Path]:
    from . import reproduction

    made: list[Path] = []
    made += figure1_architecture(outdir)

    rows = reproduction.build_rows(run.dataset, run.lib)
    made += figure2_validation(rows, reproduction.blocked_rows(run.dataset), outdir)

    made += figure3_harmonization(run.artifacts["analysis_a"],
                                  run.artifacts["analysis_b"],
                                  run.artifacts["gwp"], outdir)

    if run.sobol_validation_passed and "sobol_blocks" in run.artifacts:
        from .parameters import MODE_A_SHARED_FOREGROUND
        made += figure4_sobol(run.artifacts["sobol_blocks"], MODE_A_SHARED_FOREGROUND,
                              run.sobol_validation_passed, outdir)
        made += figure_si_sobol_convergence(run.artifacts["sobol_convergence"], outdir)
    else:
        print("  figure 4 SKIPPED: Sobol validation did not pass")

    if "mc_blocks" in run.artifacts:
        made += figure5_uncertainty(run.artifacts["mc_blocks"], outdir)
    return made
