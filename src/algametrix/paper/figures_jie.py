"""The four figures of the Journal of Industrial Ecology manuscript.

Kept separate from :mod:`algametrix.paper.figures`, which draws the figure set
of the cross-study harmonization work. The two papers make different arguments
and should not share a numbering scheme.

Figure 1  architecture: scenario -> shared inventory -> TEA + LCA -> sensitivity
          and uncertainty
Figure 2  shared-inventory consistency and internal verification, with the
          controlled duplicated-inventory counter-example on the same residual axis
Figure 3  external validation: deviations from point references
Figure 4  model evaluation: the same physical parameter set driving an economic
          and an environmental output differently, the propagated uncertainty on
          both, and a group-wise Sobol' decomposition of that uncertainty

Every panel is drawn from objects produced by ``reproduce.py`` in the same
process. Nothing is transcribed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .figures import (
    C_FOREGROUND,
    C_JOINT,
    C_LCA,
    C_NEUTRAL,
    C_TEA,
    C_WARN,
    _save,
    _sublabels,
    plt,
)
from matplotlib.lines import Line2D                              # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch   # noqa: E402

#: Floating-point resolution, drawn on every precision axis so the reader can
#: see that the residuals sit on it rather than merely near zero.
EPS = np.finfo(float).eps


def _panel_label(ax, letter: str, pad: float = 6.0) -> None:
    """A bare bold panel letter. The panel is described in the caption, so the
    axes carry the identifier and nothing else."""
    ax.set_title(letter, loc="left", x=0.0, fontsize=9.5, fontweight="bold",
                 color="#1a1a1a", pad=pad)


# ======================================================================
# Figure 1 - architecture
# ======================================================================

def figure1_architecture(outdir: Path) -> list[Path]:
    """Scenario -> shared inventory -> TEA + LCA -> sensitivity and uncertainty."""
    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    ax.set_xlim(-0.75, 10)
    ax.set_ylim(0, 7.9)
    ax.axis("off")

    def box(x, y, w, h, text, color, alpha=0.12, weight="normal", size=8):
        for face, z in ((color, 1), ("none", 2)):
            ax.add_patch(FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.08", linewidth=1.1,
                edgecolor=color, facecolor=face,
                alpha=alpha if face != "none" else 1.0, zorder=z))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=size, color="#1a1a1a", zorder=3, fontweight=weight)

    def arrow(x1, y1, x2, y2, color, lw=1.2, ls="-"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                     mutation_scale=11, linewidth=lw,
                                     color=color, linestyle=ls, zorder=4))

    # --- layer 1: the scenario -------------------------------------------
    ax.text(5.0, 7.70, "SCENARIO  —  physical and operational description",
            ha="center", fontsize=8.2, color=C_FOREGROUND, fontweight="bold")
    box(0.5, 6.62, 9.0, 0.86,
        "strain composition (C, N, P) · productivity · operating days · reactor or pond type\n"
        "harvesting recovery · drying · downstream extraction · plant scale",
        C_FOREGROUND, size=7.2)

    # --- layer 2: the shared inventory ------------------------------------
    box(1.25, 4.90, 7.5, 1.20, "", C_FOREGROUND, alpha=0.26)
    ax.text(5.0, 5.83, "SHARED MASS AND ENERGY INVENTORY", ha="center", va="center",
            fontsize=8.4, fontweight="bold", color="#1a1a1a", zorder=3)
    ax.text(5.0, 5.50, "electricity · heat · carbon source · N · P · substrate · "
                       "water · solvent · land\nplus the annual production the plant "
                       "delivers",
            ha="center", va="center", fontsize=7.0, color="#1a1a1a", zorder=3)
    ax.text(5.0, 5.06, "built ONCE; both interpretation layers read the same object",
            ha="center", va="center", fontsize=7.0, style="italic", color=C_NEUTRAL,
            zorder=3)
    arrow(5.0, 6.62, 5.0, 6.10, C_FOREGROUND)

    # --- layer 3: the two interpretation layers ---------------------------
    box(0.4, 3.15, 4.3, 1.20,
        "TEA LAYER\nprices · CAPEX factors · labour\ninstallation and indirect factors\n"
        "depreciation · discount rate · tax",
        C_TEA, size=6.9)
    box(5.3, 3.15, 4.3, 1.20,
        "LCA LAYER\ncharacterization factors · grid mix\n"
        "biogenic-carbon convention\nsystem boundary",
        C_LCA, size=6.9)
    arrow(4.1, 4.90, 2.9, 4.35, C_FOREGROUND)
    arrow(5.9, 4.90, 7.1, 4.35, C_FOREGROUND)

    # --- layer 4: outputs --------------------------------------------------
    box(0.4, 1.80, 4.3, 0.90,
        "production cost · CAPEX\nNPV · IRR · break-even price", C_TEA, alpha=0.26, size=7.4)
    box(5.3, 1.80, 4.3, 0.90,
        "gross GWP · biogenic adjustment · net GWP\nCED · water · land · eutrophication",
        C_LCA, alpha=0.26, size=7.4)
    arrow(2.55, 3.15, 2.55, 2.70, C_TEA)
    arrow(7.45, 3.15, 7.45, 2.70, C_LCA)

    # --- layer 5: sensitivity and uncertainty ------------------------------
    box(1.6, 0.50, 6.8, 0.92,
        "GLOBAL SENSITIVITY (Sobol') AND UNCERTAINTY PROPAGATION (Monte Carlo)\n"
        "one parameter set, sampled once, carried through the whole chain",
        C_JOINT, alpha=0.18, weight="bold", size=7.6)
    arrow(2.55, 1.80, 3.4, 1.42, C_TEA)
    arrow(7.45, 1.80, 6.6, 1.42, C_LCA)
    # the feedback edge: a parameter draw re-enters at the scenario
    for a, b in (((1.6, 0.96), (-0.62, 0.96)), ((-0.62, 0.96), (-0.62, 7.05))):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-", linewidth=1.0,
                                     color=C_JOINT, linestyle=(0, (4, 2)), zorder=4))
    arrow(-0.62, 7.05, 0.5, 7.05, C_JOINT, ls=(0, (4, 2)))
    ax.text(-0.28, 3.60, "each parameter draw re-enters at the scenario, so the cost "
                         "and the impact\nit produces always describe one and the same "
                         "plant",
            rotation=90, ha="center", va="center", fontsize=6.3,
            style="italic", color=C_JOINT)

    ax.text(5.0, 0.12,
            "prices and characterization factors are NOT inputs to the physical inventory",
            ha="center", va="center", fontsize=7.2, style="italic", color=C_NEUTRAL)
    return _save(fig, outdir, "jie_fig1_architecture")


# ======================================================================
# Figure 2 - consistency and internal verification
# ======================================================================

def _safe_log10(values, floor: float) -> np.ndarray:
    v = np.asarray([max(float(x), floor) for x in values], dtype=float)
    return np.log10(v)


def figure2_consistency(consistency_reports, verification_reports,
                        benchmark_reports, demos, outdir: Path,
                        brightway_json: Path | None = None) -> list[Path]:
    """(a) recovered quantities on the 1:1 line, (b) every residual on one axis.

    The duplicated-inventory counter-example used to have a panel of its own. It
    did not earn one: every flow diverged by the same 15 %, so the panel carried
    two numbers rather than a distribution, and the numbers are in the table
    anyway. It is now a fifth series in panel (b), which is where it belongs -
    the whole point of the counter-example is *how far it sits* from the
    verification residuals, and panel (b) is already the axis that measures that.

    The panels carry no prose: what each one is, how many comparisons it holds,
    what the counter-example changed and which bw2calc build it was checked
    against are stated in the caption. Only the two reference lines and the
    tinted band beyond the acceptance criterion are annotated on the axes, since
    they cannot be read off the data.
    """
    # Equal cells and a square box on both panels: the two data areas are then
    # the same size and share a baseline, so the panel letters line up. The
    # surplus vertical space is cropped by the tight bounding box on save.
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6),
                             gridspec_kw={"wspace": 0.42, "width_ratios": [1.0, 1.0]})

    # ---------------------------------------------------------------- (a)
    ax = axes[0]
    tea, lca, kinds = [], [], []
    for rep in consistency_reports:
        for f in rep.active_flows:
            if f.tea_quantity > 0 and f.lca_quantity > 0:
                tea.append(f.tea_quantity)
                lca.append(f.lca_quantity)
                kinds.append(f.kind)
    tea_a, lca_a = np.array(tea), np.array(lca)
    lo = min(tea_a.min(), lca_a.min()) / 3
    hi = max(tea_a.max(), lca_a.max()) * 3
    ax.grid(True, which="major", color="#e6e6e6", lw=0.5, zorder=0)
    ax.plot([lo, hi], [lo, hi], color="#555555", lw=0.9, zorder=1)
    direct = np.array([k == "direct" for k in kinds])
    ax.scatter(tea_a[~direct], lca_a[~direct], s=20, facecolor=C_FOREGROUND,
               edgecolor="white", linewidth=0.4, alpha=0.85, zorder=3,
               label="metered by a price and a factor")
    ax.scatter(tea_a[direct], lca_a[direct], s=24, marker="^", facecolor=C_LCA,
               edgecolor="white", linewidth=0.4, alpha=0.9, zorder=3,
               label="carried directly (water)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    # Identical limits on both axes plus a square box: the 1:1 line is then a
    # true 45 degrees, which is the whole claim of the panel.
    ax.set_box_aspect(1)
    ax.set_axisbelow(True)
    ax.set_xlabel("quantity implied by the TEA\n(per kg dry biomass)")
    ax.set_ylabel("quantity implied by the LCA\n(per kg dry biomass)")
    _panel_label(ax, "a", pad=14)
    ax.legend(loc="upper left", frameon=False, fontsize=6.6, handletextpad=0.4,
              borderpad=0.2)

    # ---------------------------------------------------------------- (b)
    ax = axes[1]
    floor = EPS / 4
    series = [
        # Not "mass balances": these residuals come from construction identities
        # that hold by construction. The physical admissibility constraints, which
        # can fail, are booleans and have no residual to plot - they are reported
        # in the text and in results/verification.txt.
        ("inventory\nidentities",
         [c.residual for rep in verification_reports for c in rep.identities], C_FOREGROUND),
        ("TEA vs LCA\nshared flows",
         [f.discrepancy for rep in consistency_reports for f in rep.active_flows], C_JOINT),
        ("sequential vs\nmatrix LCA",
         [r.rel_diff for rep in benchmark_reports for r in rep.rows], C_LCA),
    ]
    if brightway_json and brightway_json.exists():
        payload = json.loads(brightway_json.read_text(encoding="utf-8"))
        series.append(("matrix vs\nbw2calc",
                       payload["all_relative_differences"], C_TEA))
    # The counter-example, on the same axis: this is the contrast the paper rests on.
    demo_vals = [d.discrepancy for demo in demos for d in demo.duplicated
                 if d.discrepancy > 0]
    if demo_vals:
        series.append(("duplicated\ninventories", demo_vals, C_WARN))

    right = 0.6
    ax.set_xlim(math.log10(floor) - 0.7, right)
    ax.set_ylim(-0.62, len(series) - 0.38)
    ax.set_box_aspect(1)
    # Everything to the right of the acceptance criterion is a failure. Tinting
    # that half of the axis says so without a sentence on the plot.
    ax.axvspan(-9, right, color=C_WARN, alpha=0.06, lw=0, zorder=0)

    rng = np.random.default_rng(0)      # jitter only; no result depends on it
    for i, (_label, values, color) in enumerate(series):
        x = _safe_log10(values, floor)
        y = i + (rng.random(len(x)) - 0.5) * 0.30
        ax.scatter(x, y, s=9, color=color, alpha=0.6, edgecolor="none", zorder=3)
        ax.plot([x.max()], [i], "|", color=color, markersize=14, markeredgewidth=1.8,
                zorder=4)
    # The two reference lines are labelled horizontally above the axis rather
    # than rotated inside it: inside, either label would have to run through the
    # data it is there to put in context.
    for xline, style, text in ((math.log10(EPS), ":", "double precision"),
                               (-9, "--", "acceptance criterion")):
        ax.axvline(xline, color="#555555", lw=0.8, ls=style, zorder=2)
        ax.text(xline + 0.2, 1.012, text, transform=ax.get_xaxis_transform(),
                fontsize=6.0, color="#555555", va="bottom", ha="left")
    ax.set_yticks(range(len(series)))
    ax.set_yticklabels([s[0] for s in series], fontsize=6.4)
    # Each row label carries its series colour, which is what ties the counter-
    # example to the tinted band without a legend or a note.
    for tick, (_label, _values, color) in zip(ax.get_yticklabels(), series):
        tick.set_color(color)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("relative residual  (log$_{10}$)")
    _panel_label(ax, "b", pad=14)
    return _save(fig, outdir, "jie_fig2_consistency", tight_bbox=True)


# Figure 3 - external validation
# ======================================================================

def figure3_validation(rows, blocked, outdir: Path, excluded=None) -> list[Path]:
    """Point reproductions as a model/source ratio against a line at 1.

    The range checks used to occupy a second panel. After two records were
    excluded for untraceable provenance only one remains, and a panel for a
    single point is worse than a sentence: it is stated in the caption and in
    full in ``results/validation.txt``.

    How many cases there are, how they split between blind and calibrated, what
    the blind spreads are, and what happened to the range check and the excluded
    records are all caption material and are not written on the axes. That is
    why ``blocked`` and ``excluded`` are still accepted and no longer drawn: the
    counts belong to the caller's caption, and the reasons to
    ``results/validation.txt``.

    Each row is named by its citation and by which scenario of that source it is
    ("Russo et al., 2022 — Heterotrophic"), because a reader has to be able to
    find the reference. The internal ``study_id`` is a join key for
    ``results/validation.txt`` and appears nowhere a reader is expected to read.
    """
    point_rows = [r for r in rows if r.comparison_kind == "point" and r.ratio]
    point_rows = sorted(point_rows, key=lambda r: (r.validation_mode != "blind",
                                                   r.metric, r.label))

    fig, ax = plt.subplots(figsize=(7.2, 0.34 * max(len(point_rows), 6) + 1.4))
    marker = {"blind": "o", "calibrated": "s", "range": "^", "none": "D"}

    ax.grid(axis="x", color="#e6e6e6", lw=0.5)
    ax.grid(axis="y", color="#eeeeee", lw=0.5, ls=":")
    ax.set_axisbelow(True)
    ax.axvspan(0.9, 1.1, color="#333333", alpha=0.07, lw=0, zorder=0)
    ax.axvline(1.0, color="#333333", lw=1.0, zorder=1)
    labels, any_bounds = [], False
    for i, r in enumerate(point_rows):
        color = C_TEA if r.metric == "cost" else C_LCA
        bounds = r.ratio_bounds
        if bounds is not None:
            any_bounds = True
            ax.plot(bounds, [i, i], color=color, lw=2.4, alpha=0.55,
                    solid_capstyle="butt", zorder=2)
        ax.plot(r.ratio, i, marker.get(r.validation_mode, "o"), color=color,
                markersize=6.5, markeredgecolor="white", markeredgewidth=0.6, zorder=3)
        labels.append(r.citation or r.study_id)
    # Two lines, not one: the citation is the tick label, so the layout reserves
    # room for it, and which scenario of that source this is, in what unit, is a
    # quieter line under it. On one line the longest row is half the figure wide
    # and the reader parses a sentence to find a name.
    ax.set_yticks(range(len(point_rows)))
    ax.set_yticklabels(labels, fontsize=6.9, color="#1a1a1a")
    ax.tick_params(axis="y", length=0)
    # The metric is not written out on the second line: colour and the legend
    # already carry it, and the basis says it again in the unit.
    _sublabels(ax, [" · ".join(x for x in (r.scenario, r.basis_label) if x)
                    for r in point_rows], fig)
    ax.set_xlabel("AlgaMetrix / source     (dimensionless)")

    # Symmetric about parity and no wider than the data need: on a fixed 0.5-1.5
    # axis every point sat in the middle fifth, which made a 14 % miss look like
    # a rounding error.
    extremes = [r.ratio for r in point_rows]
    for r in point_rows:
        if r.ratio_bounds is not None:
            extremes.extend(r.ratio_bounds)
    half = max(abs(min(extremes) - 1.0), abs(max(extremes) - 1.0), 0.12) * 1.22
    ax.set_xlim(1.0 - half, 1.0 + half)
    ax.set_ylim(len(point_rows) - 0.4, -0.95)      # inverted: row 0 on top
    ax.text(1.1, -0.85, "±10 %", fontsize=6.2, color=C_NEUTRAL, ha="left", va="center")

    handles = [
        Line2D([], [], marker="o", ls="", color=C_NEUTRAL, label="blind"),
        Line2D([], [], marker="s", ls="", color=C_NEUTRAL, label="calibrated"),
        Line2D([], [], marker="o", ls="", color=C_TEA, label="cost endpoint"),
        Line2D([], [], marker="o", ls="", color=C_LCA, label="GWP endpoint"),
    ]
    if any_bounds:
        handles.append(Line2D([], [], ls="-", lw=2.4, color=C_NEUTRAL, alpha=0.55,
                              label="mixed price set: two currency readings"))
    # Above the axis, in the band the panel title used to occupy: inside the axis
    # the legend sat on top of the last two rows.
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.005),
              frameon=False, fontsize=6.6, ncol=3, columnspacing=1.6,
              handletextpad=0.4)
    fig.tight_layout()
    return _save(fig, outdir, "jie_fig3_validation")


# ======================================================================
# Figure 4 - model evaluation
# ======================================================================

def figure4_evaluation(sobol_blocks, mc_blocks, group_sobol, mode_key,
                       validated: bool, outdir: Path) -> list[Path]:
    """(a) drivers per parameter, (b) propagated uncertainty, (c) group Sobol'.

    The panels carry their letter and nothing else. What each column is, how the
    Sobol' and Monte-Carlo supports relate and why the two sets of numbers are
    not interchangeable are stated in the caption. The one piece of text kept on
    the figure is the archetype name, which is not a description of a panel but
    the identity of the row - without it the reader cannot tell which case a row
    reports - and it is drawn once per row rather than three times.
    """
    if not validated:
        raise RuntimeError("Sobol implementation validation did not pass; "
                           "figure 4 must not be drawn")

    cost_key = "Production cost (EUR/kg)"
    gwp_key = "GWP net (kg CO2-eq/kg)"
    n = len(sobol_blocks)

    fig = plt.figure(figsize=(7.2, 2.1 + 1.5 * n))
    gs = fig.add_gridspec(n, 3, wspace=0.36, hspace=0.78,
                          width_ratios=[1.30, 0.85, 0.85], top=0.90, bottom=0.10)

    # One bold header per row, spanning the three columns: the row is a case, the
    # columns are three views of it. It has to clear the panel letters, which are
    # titles on the same top edge, so the offset is measured in points against
    # the letter's own pad and height rather than guessed as a figure fraction.
    letter_pad, letter_size = 6.0, 9.5
    header_offset = (letter_pad + letter_size * 1.2 + 6.0) / 72 / fig.get_figheight()
    for row, block in enumerate(sobol_blocks):
        span = gs[row, 0].get_position(fig)
        fig.text(0.5 * (span.x0 + gs[row, 2].get_position(fig).x1),
                 span.y1 + header_offset, block["archetype_label"],
                 ha="center", va="bottom", fontsize=8.2, fontweight="bold",
                 color="#1a1a1a")

    # --------------------------------------------------------------- (a)
    for row, block in enumerate(sobol_blocks):
        ax = fig.add_subplot(gs[row, 0])
        results = {r.output: r for r in block["modes"][mode_key]}
        cost, gwp = results[cost_key], results[gwp_key]
        names = [nm for nm, _, _ in cost.ranked()]
        st = {r.output: dict(zip(r.parameters, r.st)) for r in (cost, gwp)}
        y = np.arange(len(names))
        for offset, key, color, label in ((0.19, cost_key, C_TEA, "production cost"),
                                          (-0.19, gwp_key, C_LCA, "net GWP")):
            vals = [st[key][nm].value for nm in names]
            los = [max(st[key][nm].value - st[key][nm].ci_low, 0) for nm in names]
            his = [max(st[key][nm].ci_high - st[key][nm].value, 0) for nm in names]
            ax.barh(y + offset, vals, height=0.34, color=color, alpha=0.85, label=label)
            ax.errorbar(vals, y + offset, xerr=[los, his], fmt="none",
                        ecolor="#333333", elinewidth=0.7, capsize=1.6, zorder=4)
        ax.set_yticks(y)
        ax.set_yticklabels(names, fontsize=6.2)
        ax.tick_params(axis="y", length=0)
        ax.invert_yaxis()
        ax.set_xlim(0, 1.05)
        ax.grid(axis="x", color="#e9e9e9", lw=0.5)
        ax.set_axisbelow(True)
        _panel_label(ax, f"a{row + 1}")
        if row == n - 1:
            ax.set_xlabel("total-order Sobol' index $S_T$ per parameter\n"
                          "(95% bootstrap CI)")
            ax.legend(loc="lower right", frameon=False, fontsize=6.4,
                      bbox_to_anchor=(1.0, 0.08))

    # --------------------------------------------------------------- (b)
    for row, block in enumerate(mc_blocks):
        ax = fig.add_subplot(gs[row, 1])
        for k, (metric, color) in enumerate(((cost_key, C_TEA), (gwp_key, C_LCA))):
            joint = block["metrics"][metric].joint
            p10, p50, p90 = joint.p10.value, joint.p50.value, joint.p90.value
            centre = p50 if p50 else 1.0
            ax.plot([p10 / centre, p90 / centre], [k, k], color=color, lw=7, alpha=0.35,
                    solid_capstyle="butt", zorder=2)
            ax.plot([1.0], [k], "|", color=color, markersize=15, markeredgewidth=1.8,
                    zorder=3)
            ax.text(0.5 * (p10 + p90) / centre, k - 0.34,
                    f"{'cost' if metric == cost_key else 'net GWP'}  "
                    f"{p10:,.3g}–{p90:,.3g}",
                    ha="center", va="bottom", fontsize=6.0, color=color)
        ax.axvline(1.0, color="#333333", lw=0.9, zorder=1)
        ax.set_yticks([])
        ax.set_ylim(1.7, -0.75)
        _panel_label(ax, f"b{row + 1}")
        ax.spines["left"].set_visible(False)
        if row == n - 1:
            ax.set_xlabel("value / median")

    # --------------------------------------------------------------- (c)
    group_colour = {"foreground": C_FOREGROUND, "economic": C_TEA,
                    "lcia_background": C_LCA}
    group_label = {"foreground": "shared physics", "economic": "economic",
                   "lcia_background": "LCIA background"}

    for row, block in enumerate(mc_blocks):
        ax = fig.add_subplot(gs[row, 2])
        labels = []
        for k, metric in enumerate((cost_key, gwp_key)):
            gr = (group_sobol or {}).get((block["archetype_label"], metric))
            labels.append("cost" if metric == cost_key else "net GWP")
            if gr is None:
                continue
            left = 0.0
            for g, (s, _st) in gr.by_group().items():
                w = max(0.0, min(float(s.value), 1.0))
                if w <= 0:
                    continue
                ax.barh(k, w, height=0.5, left=left,
                        color=group_colour.get(g, C_NEUTRAL), alpha=0.88, zorder=2)
                if w > 0.20:
                    ax.text(left + w / 2, k, f"{s.value:.0%}", ha="center", va="center",
                            fontsize=5.8, color="white", fontweight="bold", zorder=3)
                left += w
            inter = max(0.0, min(gr.interactions, 1.0))
            if inter > 0.004:
                ax.barh(k, inter, height=0.5, left=left, color="#b9b9b9", alpha=0.95,
                        zorder=2)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=6.4)
        ax.tick_params(axis="y", length=0)
        ax.set_ylim(1.7, -0.75)
        ax.set_xlim(0, 1.0)
        _panel_label(ax, f"c{row + 1}")
        if row == n - 1:
            ax.set_xlabel("share of output variance")
            # Under the last c panel, in the band the footnote used to occupy.
            # Above the first one it now collides with the row header.
            ax.legend(handles=[
                Line2D([], [], lw=5, color=group_colour[g], alpha=0.88,
                       label=group_label[g]) for g in group_colour
            ] + [Line2D([], [], lw=5, color="#b9b9b9",
                        label="between-group\ninteractions")],
                loc="upper center", bbox_to_anchor=(0.5, -0.42), frameon=False,
                fontsize=5.8, ncol=2, columnspacing=1.0, handletextpad=0.5)

    return _save(fig, outdir, "jie_fig4_evaluation", tight_bbox=True)


# ======================================================================

def build_all(run, outdir: Path, results_dir: Path) -> list[Path]:
    """Draw the four JIE figures from the artifacts a ``reproduce.py`` run holds."""
    from .parameters import MODE_A_SHARED_FOREGROUND

    made: list[Path] = []
    made += figure1_architecture(outdir)
    made += figure2_consistency(
        run.artifacts["consistency"], run.artifacts["verification_reports"],
        run.artifacts["benchmark"], run.artifacts["consistency_demos"], outdir,
        brightway_json=results_dir / "brightway_crosscheck.json",
    )
    made += figure3_validation(run.artifacts["reproduction_rows"],
                               run.artifacts["reproduction_blocked"], outdir,
                               excluded=run.artifacts.get("reproduction_excluded"))
    made += figure4_evaluation(run.artifacts["sobol_blocks"], run.artifacts["mc_blocks"],
                               run.artifacts.get("group_sobol"),
                               MODE_A_SHARED_FOREGROUND, run.sobol_validation_passed,
                               outdir)
    return made
