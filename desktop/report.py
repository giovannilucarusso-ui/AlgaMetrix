"""Process report (PDF) — a shareable, branded summary of a case study.

Rebuilds the multi-page A4 AlgaMetrix report (cover with KPIs, techno-economic
charts, cost-breakdown table, life-cycle charts, energy/mass inventory) and adds
the auto-generated **Process Flow Diagram** and its stream table. The module is
**Qt-free** — matplotlib plus the pure :mod:`desktop.flowsheet.model` solver — so
it can be unit-tested head-less. The Qt front-end renders the flow diagram to a
PNG and passes the path in; everything else is computed from the engine results.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no interactive/Qt backend in the report path
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from algametrix import __version__ as VERSION  # noqa: E402
from algametrix.models import Basis  # noqa: E402

from . import resources  # noqa: E402
from .flowsheet import model as M  # noqa: E402

PORTRAIT = (8.27, 11.69)  # A4 portrait, inches

# palette
GREEN = "#2e7d32"
INK = "#1f2d3a"
SUBTLE = "#6b7a88"
RULE = "#d5dde3"
ALT = "#f4f7f9"
BURDEN = "#c0392b"
PIE_COLORS = ["#1565c0", "#e67e22", "#2e7d32", "#c0392b", "#8e44ad", "#7f8c8d", "#d81b8c"]

_LOGO_CACHE: list = []


def _logo():
    """Load the logo image once (RGBA array) or return ``None``."""
    if not _LOGO_CACHE:
        p = resources.logo_path()
        try:
            _LOGO_CACHE.append(mpimg.imread(p) if p else None)
        except Exception:
            _LOGO_CACHE.append(None)
    return _LOGO_CACHE[0]


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def _money(v: float) -> str:
    if abs(v) >= 1e6:
        return f"€ {v / 1e6:,.2f} M"
    if abs(v) >= 1e3:
        return f"€ {v / 1e3:,.1f} k"
    return f"€ {v:,.0f}"


def _flow(kg_h: float) -> str:
    if kg_h >= 1000.0:
        return f"{kg_h / 1000.0:,.2f} t/h"
    if kg_h >= 1.0:
        return f"{kg_h:,.0f} kg/h"
    if kg_h > 0.0:
        return f"{kg_h:,.2f} kg/h"
    return "0"


def _composition(fl) -> str:
    parts = [f"{c} {v:,.1f}" for c, v in fl.items() if v > 0.01]
    return ", ".join(parts) if parts else "—"


def _product_metrics(results):
    mp = results.main_product
    inv, tea, lca = results.inventory, results.tea, results.lca
    return {
        "name": mp.name if mp else "Dry biomass",
        "annual_t": (mp.annual_kg if mp else inv.annual_biomass_kg) / 1000.0,
        "cost": mp.production_cost_eur_per_kg if mp else tea.production_cost_eur_per_kg,
        "gwp": mp.gwp_kg_co2eq_per_kg if mp else lca.gwp_kg_co2eq_per_kg,
        "ced": mp.ced_mj_per_kg if mp else lca.ced_mj_per_kg,
    }


# --------------------------------------------------------------------------- #
# common page furniture
# --------------------------------------------------------------------------- #
def _footer(fig, page: int, total: int) -> None:
    fig.text(0.07, 0.028, f"AlgaMetrix v{VERSION}   ·   {date.today():%Y-%m-%d}",
             fontsize=8, color=SUBTLE)
    fig.text(0.93, 0.028, f"{page} / {total}", fontsize=8, color=SUBTLE, ha="right")


def _watermark(fig) -> None:
    img = _logo()
    if img is None:
        return
    ax = fig.add_axes([0.22, 0.40, 0.56, 0.22]); ax.axis("off")
    ax.imshow(img, alpha=0.05)


def _portrait():
    return plt.figure(figsize=PORTRAIT)


def _table(ax, col_labels, rows, col_widths, y_top=0.92, cell_h=0.055,
           aligns=None):
    """Draw a simple striped table with a green header, top-anchored."""
    n = len(rows)
    x = [sum(col_widths[:i]) for i in range(len(col_widths))]
    total_w = sum(col_widths)
    x0 = (1 - total_w) / 2.0
    aligns = aligns or (["left"] + ["right"] * (len(col_labels) - 1))

    def cell(cx, cy, w, text, *, header=False, align="left"):
        color = GREEN if header else "none"
        ax.add_patch(plt.Rectangle((cx, cy - cell_h), w, cell_h, transform=ax.transAxes,
                                   facecolor=color, edgecolor=RULE, lw=0.8, zorder=1))
        tx = cx + 0.012 if align == "left" else cx + w - 0.012
        ha = align
        ax.text(tx, cy - cell_h / 2, text, transform=ax.transAxes, va="center", ha=ha,
                fontsize=9.5, color="white" if header else INK,
                fontweight="bold" if header else "normal", zorder=2)

    y = y_top
    for j, lab in enumerate(col_labels):
        cell(x0 + x[j], y, col_widths[j], lab, header=True, align=aligns[j])
    y -= cell_h
    for r, row in enumerate(rows):
        if r % 2 == 1:
            ax.add_patch(plt.Rectangle((x0, y - cell_h), total_w, cell_h,
                                       transform=ax.transAxes, facecolor=ALT,
                                       edgecolor="none", zorder=0))
        for j, val in enumerate(row):
            cell(x0 + x[j], y, col_widths[j], str(val), align=aligns[j])
        y -= cell_h


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def _cover(results, scenario, page, total):
    fig = _portrait()
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    img = _logo()
    if img is not None:
        la = fig.add_axes([0.07, 0.885, 0.34, 0.085]); la.axis("off")
        la.imshow(img)
    else:
        ax.text(0.07, 0.915, "AlgaMetrix", fontsize=26, fontweight="bold", color=GREEN,
                transform=ax.transAxes)

    ax.text(0.07, 0.855, "Techno-economic & Life-cycle Assessment report",
            fontsize=17, color=INK, transform=ax.transAxes)
    ax.text(0.07, 0.828, f"Generated {date.today():%Y-%m-%d}   ·   version {VERSION}",
            fontsize=10, color=SUBTLE, transform=ax.transAxes)
    ax.plot([0.07, 0.93], [0.815, 0.815], color=RULE, lw=1, transform=ax.transAxes)

    unit = "m²" if scenario.system.basis == Basis.AREA else "m³"
    meta = [f"Organism:  {scenario.organism.name}",
            f"System:  {scenario.system.name}",
            f"Scale:  {scenario.scale:,.0f} {unit}",
            "Functional unit:  1 kg " + ("product" if results.main_product else "dry biomass")]
    y = 0.785
    for line in meta:
        ax.text(0.07, y, line, fontsize=12, color=INK, transform=ax.transAxes)
        y -= 0.026

    ax.text(0.07, 0.655, "Key results", fontsize=16, fontweight="bold", color=INK,
            transform=ax.transAxes)

    m = _product_metrics(results)
    tea = results.tea
    rows = [
        ("Production cost", f"{m['cost']:,.2f}", "€ / kg"),
        ("NPV", f"{tea.npv / 1e6:,.1f}", "€ M"),
        ("Payback", f"{tea.payback_years:,.1f}" if tea.payback_years and tea.payback_years > 0 else "n/a", "years"),
        ("ROI", f"{tea.roi * 100:,.0f}", "% / yr"),
        ("GWP", f"{m['gwp']:,.2f}", "kg CO₂-eq / kg"),
        ("Annual output", f"{m['annual_t']:,.0f}", "t / yr"),
    ]
    _table(ax, ["Metric", "Value", "Unit"], rows, [0.46, 0.20, 0.20],
           y_top=0.62, cell_h=0.043, aligns=["left", "right", "right"])

    # techno-economic text block
    ax.text(0.07, 0.285, "Techno-economics", fontsize=13, fontweight="bold", color=INK,
            transform=ax.transAxes)
    irr_str = f"{tea.irr * 100:,.1f}%" if tea.irr is not None else "n/a"
    te = (
        f"Total investment: {_money(tea.total_investment)}    ·    "
        f"AOC: {_money(tea.annual_opex)}/yr    ·    Revenues: {_money(tea.revenues)}/yr    ·    "
        f"Net profit: {_money(tea.net_profit)}/yr\n"
        f"NPV: {_money(tea.npv)}    ·    IRR: {irr_str}    ·    "
        f"ROI: {tea.roi * 100:,.1f}%    ·    Payback: {tea.payback_years:,.1f} yr\n"
        f"Net production cost: {_money(tea.net_production_cost_eur_per_kg)}/kg")
    ax.text(0.07, 0.26, te, fontsize=9.5, color=INK, transform=ax.transAxes, va="top")

    # life-cycle text block
    ax.text(0.07, 0.155, "Life-cycle", fontsize=13, fontweight="bold", color=INK,
            transform=ax.transAxes)
    lca = results.lca
    lc = (f"Net GWP: {lca.gwp_kg_co2eq_per_kg:,.2f} kg CO₂-eq/kg    ·    "
          f"CED: {lca.ced_mj_per_kg:,.1f} MJ/kg    ·    "
          f"Water: {lca.water_m3_per_kg:,.2f} m³/kg    ·    "
          f"Land: {lca.land_m2a_per_kg:,.2f} m²·a/kg")
    ax.text(0.07, 0.13, lc, fontsize=9.5, color=INK, transform=ax.transAxes, va="top")

    _footer(fig, page, total)
    return fig


def _tea_charts(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Techno-economic analysis", fontsize=16, fontweight="bold", color=INK)

    tea = results.tea
    # OPEX horizontal bar (€ M/yr)
    items = sorted(tea.opex_breakdown.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    vals = [v / 1e6 for _, v in items]
    ax1 = fig.add_axes([0.30, 0.56, 0.62, 0.34])
    ax1.barh(labels, vals, color=GREEN)
    ax1.set_title("Annual operating cost breakdown (€ M/yr)", fontsize=11, color=INK)
    ax1.tick_params(labelsize=8.5)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    # CAPEX pie
    citems = [(k, v) for k, v in tea.capex_breakdown.items() if v > 0]
    ax2 = fig.add_axes([0.16, 0.06, 0.68, 0.42])
    ax2.set_title("CAPEX breakdown", fontsize=11, color=INK)
    ax2.pie([v for _, v in citems], labels=[k for k, _ in citems],
            autopct="%1.0f%%", startangle=90, colors=PIE_COLORS,
            textprops={"fontsize": 8.5}, pctdistance=0.75)
    ax2.axis("equal")

    _footer(fig, page, total)
    return fig


def _cost_table(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Production cost breakdown", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    tea = results.tea
    annual_kg = max(results.inventory.annual_biomass_kg, 1e-9)
    aoc = tea.annual_opex
    items = sorted(tea.opex_breakdown.items(), key=lambda kv: kv[1], reverse=True)
    rows = []
    for name, v in items:
        rows.append((name, f"{v / annual_kg:,.3f}", _money(v) + "/yr",
                     f"{100 * v / aoc:,.1f}%"))
    raw = tea.opex_categories.get("Raw materials", 0.0)
    rows.append(("Raw materials (subtotal)", f"{raw / annual_kg:,.3f}", _money(raw) + "/yr",
                 f"{100 * raw / aoc:,.1f}%"))
    rows.append(("Annual operating cost", f"{aoc / annual_kg:,.3f}", _money(aoc) + "/yr", "100.0%"))
    _table(ax, ["Cost item", "€ / kg", "€ / yr", "% of total"], rows,
           [0.40, 0.16, 0.20, 0.14], y_top=0.90, cell_h=0.05,
           aligns=["left", "right", "right", "right"])

    _footer(fig, page, total)
    return fig


def _lca(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Life-cycle assessment", fontsize=16, fontweight="bold", color=INK)

    lca = results.lca
    items = sorted(lca.gwp_breakdown.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    colors = [GREEN if v < 0 else BURDEN for v in vals]
    ax1 = fig.add_axes([0.34, 0.58, 0.58, 0.32])
    ax1.barh(labels, vals, color=colors)
    ax1.axvline(lca.gwp_kg_co2eq_per_kg, ls="--", color=INK, lw=1)
    ax1.set_title("GWP contribution (kg CO₂-eq / kg)", fontsize=11, color=INK)
    ax1.tick_params(labelsize=8.5)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.text(0.07, 0.50, "Impact categories (per kg product)", fontsize=12,
            fontweight="bold", color=INK, transform=ax.transAxes)
    rows = [(k, f"{v:,.4g}") for k, v in lca.impacts.items()]
    _table(ax, ["Impact category", "per kg product"], rows, [0.56, 0.28],
           y_top=0.46, cell_h=0.05, aligns=["left", "right"])

    _footer(fig, page, total)
    return fig


def _inventory_chart(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Energy & mass inventory", fontsize=16, fontweight="bold", color=INK)

    eb = results.inventory.elec_breakdown
    ax = fig.add_axes([0.12, 0.42, 0.78, 0.44])
    ax.bar(list(eb.keys()), list(eb.values()), color=GREEN, width=0.6)
    ax.set_title("Electricity by stage (kWh/kg)", fontsize=11, color=INK)
    ax.tick_params(labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    _footer(fig, page, total)
    return fig


def _inventory_table(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Inventory — per kg dry biomass", fontsize=16,
             fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    inv = results.inventory
    rows = [
        ("Electricity", f"{inv.elec_kwh_per_kg:,.3f}", "kWh"),
        ("Heat (drying)", f"{inv.heat_mj_per_kg:,.3f}", "MJ"),
        ("CO₂ supplied", f"{inv.co2_supply_per_kg:,.3f}", "kg"),
        ("Bicarbonate (NaHCO₃) supplied", f"{inv.bicarbonate_supply_per_kg:,.3f}", "kg"),
        ("CO₂ fixed (biogenic)", f"{inv.co2_fixed_per_kg:,.3f}", "kg"),
        ("Nitrogen", f"{inv.nitrogen_per_kg:,.3f}", "kg"),
        ("Phosphorus", f"{inv.phosphorus_per_kg:,.3f}", "kg"),
        ("Water", f"{inv.water_m3_per_kg:,.3f}", "m³"),
        ("Substrate", f"{inv.substrate_per_kg:,.3f}", "kg"),
        ("Land occupation", f"{inv.land_m2a_per_kg:,.3f}", "m²·a"),
    ]
    _table(ax, ["Flow", "Value", "Unit"], rows, [0.52, 0.18, 0.16],
           y_top=0.90, cell_h=0.05, aligns=["left", "right", "right"])

    _footer(fig, page, total)
    return fig


def _flowsheet(pfd_png, page, total):
    try:
        img = mpimg.imread(pfd_png)
        ih, iw = img.shape[0], img.shape[1]
    except Exception:
        fig = _portrait()
        _footer(fig, page, total)
        return fig
    title_h = 0.9
    fig_w = 11.69
    fig_h = fig_w * ih / iw + title_h
    if fig_h > 8.27:
        fig_h = 8.27
        fig_w = (fig_h - title_h) * iw / ih
    fig = plt.figure(figsize=(fig_w, fig_h))
    fig.text(0.03, 1.0 - 0.5 * title_h / fig_h, "Process flow diagram",
             fontsize=15, fontweight="bold", color=INK)
    ax = fig.add_axes([0.02, 0.03, 0.96, (fig_h - title_h) / fig_h - 0.03])
    ax.imshow(img); ax.axis("off")
    _footer(fig, page, total)
    return fig


def _streams(flowsheet, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Stream table", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    rows = _stream_rows(flowsheet)
    _table(ax, ["S#", "From → To", "Flow", "Composition (kg/h)"],
           rows, [0.07, 0.24, 0.15, 0.42], y_top=0.90, cell_h=0.042,
           aligns=["center", "left", "right", "left"])
    _footer(fig, page, total)
    return fig


def _stream_rows(flowsheet: M.Flowsheet):
    result = M.solve(flowsheet)
    numbering = {lid: i + 1 for i, lid in enumerate(flowsheet.links)}
    rows = []
    for lid, link in flowsheet.links.items():
        fl = result.stream_flows.get(lid, M.empty_flow())
        src = flowsheet.nodes.get(link.src_node)
        dst = flowsheet.nodes.get(link.dst_node)
        src_tag = (src.tag or src.name) if src else "?"
        dst_tag = (dst.tag or dst.name) if dst else "?"
        rows.append((numbering[lid], f"{src_tag} → {dst_tag}",
                     _flow(M.flow_total(fl)), _composition(fl)))
    rows.sort(key=lambda r: r[0])
    return rows


def _products(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Products & allocation", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    prods = results.products
    rows = []
    for p in prods:
        rows.append((p.name + ("  *" if p.is_main else ""),
                     f"{p.annual_kg / 1000:,.1f}", f"{p.price:,.2f}",
                     _money(p.revenue) + "/yr", f"{p.production_cost_eur_per_kg:,.2f}",
                     f"{p.gwp_kg_co2eq_per_kg:,.2f}"))
    _table(ax, ["Product", "t/yr", "€/kg", "Revenue", "Cost €/kg", "GWP kg/kg"], rows,
           [0.30, 0.12, 0.12, 0.18, 0.14, 0.14], y_top=0.90, cell_h=0.05,
           aligns=["left", "right", "right", "right", "right", "right"])
    ax.text(0.07, 0.90 - (len(rows) + 1) * 0.05 - 0.02,
            "*  main product — carries the reported production cost.",
            fontsize=9, color=SUBTLE, transform=ax.transAxes)

    revs = [(p.name, p.revenue) for p in prods if p.revenue > 0]
    if revs:
        axp = fig.add_axes([0.20, 0.08, 0.60, 0.34])
        axp.set_title("Revenue share", fontsize=11, color=INK)
        axp.pie([v for _, v in revs], labels=[k for k, _ in revs], autopct="%1.0f%%",
                colors=PIE_COLORS, textprops={"fontsize": 8.5})
        axp.axis("equal")
    _footer(fig, page, total)
    return fig


def _sensitivity(sens, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Sensitivity analysis", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0.14, 0.42, 0.78, 0.44])
    ax.plot(sens["xs"], sens["ys"], marker="o", color=GREEN)
    ax.axhline(0, color="#bbbbbb", lw=0.8)
    ax.set_xlabel(f"{sens['param']} ({sens['unit']})", fontsize=10)
    ax.set_ylabel(sens["output"], fontsize=10)
    ax.set_title(f"{sens['output']} vs {sens['param']}", fontsize=11, color=INK)
    ax.grid(True, alpha=0.3); ax.tick_params(labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    _footer(fig, page, total)
    return fig


def _uncertainty(unc, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Uncertainty (Monte Carlo)", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0.14, 0.44, 0.78, 0.42])
    ax.hist(unc["vals"], bins=30, color=GREEN, alpha=0.85)
    s = unc["stats"]
    for q, col in ((s["p10"], "#888888"), (s["p50"], BURDEN), (s["p90"], "#888888")):
        ax.axvline(q, color=col, ls="--", lw=1)
    ax.set_title(f"{unc['output']}   (n = {unc['n']})", fontsize=11, color=INK)
    ax.set_xlabel(unc["output"], fontsize=10); ax.tick_params(labelsize=9)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.text(0.14, 0.38,
             f"P10: {s['p10']:,.2f}    ·    P50 (median): {s['p50']:,.2f}    ·    "
             f"P90: {s['p90']:,.2f}    ·    mean: {s['mean']:,.2f}    ·    std: {s['std']:,.2f}",
             fontsize=9.5, color=INK)
    _footer(fig, page, total)
    return fig


def _compare(cmp_data, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Scenario comparison", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    order = cmp_data["order"]
    snaps = cmp_data["snapshots"][:6]
    col_w = min(0.17, 0.64 / max(len(snaps), 1))
    budget = max(6, int(col_w * 78))  # chars that fit the column
    labels = [(lbl if len(lbl) <= budget else lbl[:budget - 1] + "…") for lbl, _ in snaps]
    rows = [[metric] + [f"{k.get(metric, float('nan')):,.2f}" for _, k in snaps]
            for metric in order]
    _table(ax, ["KPI"] + labels, rows, [0.30] + [col_w] * len(snaps),
           y_top=0.90, cell_h=0.05, aligns=["left"] + ["right"] * len(snaps))
    _footer(fig, page, total)
    return fig


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def build_process_report(pdf_path: str | Path, results, scenario,
                         flowsheet: M.Flowsheet | None = None,
                         pfd_png: str | None = None,
                         title: str = "Process report",
                         extras: dict | None = None) -> None:
    """Write the multi-page branded process report to ``pdf_path``.

    ``extras`` optionally carries analyses the user has run so every available
    output makes it into the report: ``{"sensitivity": {...}, "uncertainty":
    {...}, "compare": {"order": [...], "snapshots": [(label, kpis), ...]}}``.
    Multi-product output is taken from ``results.products`` automatically.
    """
    extras = extras or {}
    builders = [
        (_cover, (results, scenario)),
        (_tea_charts, (results,)),
        (_cost_table, (results,)),
        (_lca, (results,)),
        (_inventory_chart, (results,)),
        (_inventory_table, (results,)),
    ]
    if results.products and len(results.products) > 1:
        builders.append((_products, (results,)))
    if pfd_png and Path(pfd_png).exists():
        builders.append((_flowsheet, (pfd_png,)))
    if flowsheet is not None and flowsheet.links:
        builders.append((_streams, (flowsheet,)))
    if extras.get("sensitivity"):
        builders.append((_sensitivity, (extras["sensitivity"],)))
    if extras.get("uncertainty"):
        builders.append((_uncertainty, (extras["uncertainty"],)))
    if extras.get("compare") and extras["compare"].get("snapshots"):
        builders.append((_compare, (extras["compare"],)))

    total = len(builders)
    with PdfPages(str(pdf_path)) as pdf:
        for i, (fn, args) in enumerate(builders):
            fig = fn(*args, page=i + 1, total=total)
            pdf.savefig(fig)
            plt.close(fig)
