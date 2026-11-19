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
from algametrix.serialization import functional_unit, reference_product  # noqa: E402

from . import resources, theme  # noqa: E402
from .flowsheet import model as M  # noqa: E402
from .fmt import sig  # noqa: E402

PORTRAIT = (8.27, 11.69)  # A4 portrait, inches

# Palette: the same tokens as the screens (desktop/theme.py).
GREEN = theme.ACCENT          # table header fill (the name predates the blue accent)
BAR = theme.CHART_PRIMARY
INK = theme.INK
SUBTLE = theme.INK_2
RULE = theme.LINE
ALT = theme.SURFACE_2
BURDEN = theme.BURDEN
CREDIT = theme.CREDIT
PIE_COLORS = list(theme.SERIES)

#: What the price figures are denominated in. docs/PRICE_BASIS.md.
PRICE_BASIS = "EUR as entered; no inflation, currency conversion or price year applied"

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
    ref = reference_product(results)
    mp = results.main_product
    allocation = (f"{scenario.extraction.allocation}: {mp.allocation_share:.0%} of cost and "
                  f"burden to {mp.name}" if mp else "single product, none")
    meta = [f"Organism:  {scenario.organism.name}",
            f"System:  {scenario.system.name}  ·  {scenario.scale:,.0f} {unit}",
            f"Functional unit:  {functional_unit(results)} at the plant gate",
            "System boundary:  cradle-to-gate, attributional",
            f"Allocation:  {allocation}",
            f"Price basis:  {PRICE_BASIS}"]
    y = 0.785
    for line in meta:
        ax.text(0.07, y, line, fontsize=11, color=INK, transform=ax.transAxes)
        y -= 0.024

    ax.text(0.07, 0.615, "Key results", fontsize=16, fontweight="bold", color=INK,
            transform=ax.transAxes)

    m = _product_metrics(results)
    tea = results.tea
    rows = [
        ("Production cost", f"{m['cost']:,.2f}", f"€ / kg {ref}"),
        ("NPV", f"{tea.npv / 1e6:,.1f}", "€ M, after tax"),
        ("Payback", f"{tea.payback_years:,.1f}" if tea.payback_years and tea.payback_years > 0 else "n/a", "years"),
        ("ROI", f"{tea.roi * 100:,.0f}", "% / yr"),
        ("GWP", f"{m['gwp']:,.2f}", f"kg CO₂-eq / kg {ref}"),
        ("Annual output", f"{m['annual_t']:,.0f}", f"t {ref} / yr"),
    ]
    _table(ax, ["Metric", "Value", "Unit and basis"], rows, [0.34, 0.16, 0.36],
           y_top=0.58, cell_h=0.038, aligns=["left", "right", "left"])

    # techno-economic text block
    ax.text(0.07, 0.275, "Techno-economics", fontsize=13, fontweight="bold", color=INK,
            transform=ax.transAxes)
    irr_str = f"{tea.irr * 100:,.1f}%" if tea.irr is not None else "n/a"
    te = (
        f"Total investment: {_money(tea.total_investment)}    ·    "
        f"AOC: {_money(tea.annual_opex)}/yr    ·    Revenues: {_money(tea.revenues)}/yr    ·    "
        f"Net profit: {_money(tea.net_profit)}/yr\n"
        f"NPV: {_money(tea.npv)}    ·    IRR: {irr_str}    ·    "
        f"ROI: {tea.roi * 100:,.1f}%    ·    Payback: {tea.payback_years:,.1f} yr\n"
        f"Net production cost: € {tea.net_production_cost_eur_per_kg:,.2f}/kg dry biomass")
    ax.text(0.07, 0.25, te, fontsize=9.5, color=INK, transform=ax.transAxes, va="top")

    # life-cycle text block
    ax.text(0.07, 0.15, "Life-cycle (per kg dry biomass processed)", fontsize=13,
            fontweight="bold", color=INK, transform=ax.transAxes)
    lca = results.lca
    lc = (f"Net GWP: {lca.gwp_kg_co2eq_per_kg:,.2f} kg CO₂-eq/kg    ·    "
          f"CED: {lca.ced_mj_per_kg:,.1f} MJ/kg    ·    "
          f"Water: {lca.water_m3_per_kg:,.2f} m³/kg    ·    "
          f"Land: {lca.land_m2a_per_kg:,.2f} m²·a/kg")
    ax.text(0.07, 0.125, lc, fontsize=9.5, color=INK, transform=ax.transAxes, va="top")

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
    ax1.barh(labels, vals, color=BAR, height=0.62)
    ax1.set_title("Annual operating cost by item (M€ / yr, plant total)", fontsize=11,
                  color=INK, loc="left")
    ax1.set_xlabel("M€ / yr")
    ax1.tick_params(labelsize=8.5)
    ax1.grid(True, axis="x", color=theme.CHART_GRID, linewidth=0.8)
    ax1.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax1.spines[s].set_visible(False)

    # CAPEX as ranked bars: a pie with seven slices cannot be read to the percent.
    citems = sorted(((k, v) for k, v in tea.capex_breakdown.items() if v > 0),
                    key=lambda kv: kv[1])
    ax2 = fig.add_axes([0.30, 0.10, 0.62, 0.34])
    total = tea.total_investment or 1.0
    ax2.barh([k for k, _ in citems], [v / 1e6 for _, v in citems], color=BAR, height=0.62)
    for i, (_, v) in enumerate(citems):
        ax2.annotate(f"{v / 1e6:,.2f}  ({v / total * 100:.0f}%)", xy=(v / 1e6, i),
                     xytext=(4, 0), textcoords="offset points", va="center", fontsize=8,
                     color=SUBTLE)
    ax2.set_xlim(0, max(v for _, v in citems) / 1e6 * 1.3)
    ax2.set_title("Capital investment by item (M€)", fontsize=11, color=INK, loc="left")
    ax2.set_xlabel("M€")
    ax2.tick_params(labelsize=8.5)
    ax2.grid(True, axis="x", color=theme.CHART_GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax2.spines[s].set_visible(False)

    _footer(fig, page, total)
    return fig


def _cost_table(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Production cost breakdown", fontsize=16, fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    tea = results.tea
    # The € / kg column is per kg of the reported product and carries the same
    # allocation share as the cover's production cost, so the last row of this
    # table is that number. The € / yr column is the plant total.
    mp = results.main_product
    ref = reference_product(results)
    denom = max(mp.annual_kg if mp else results.inventory.annual_biomass_kg, 1e-9)
    share = mp.allocation_share if mp else 1.0
    aoc = tea.annual_opex
    items = sorted(tea.opex_breakdown.items(), key=lambda kv: kv[1], reverse=True)
    rows = []
    for name, v in items:
        rows.append((name, f"{v * share / denom:,.3f}", _money(v) + "/yr",
                     f"{100 * v / aoc:,.1f}%"))
    raw = tea.opex_categories.get("Raw materials", 0.0)
    rows.append(("Raw materials (subtotal)", f"{raw * share / denom:,.3f}", _money(raw) + "/yr",
                 f"{100 * raw / aoc:,.1f}%"))
    rows.append(("Annual operating cost", f"{aoc * share / denom:,.3f}", _money(aoc) + "/yr",
                 "100.0%"))
    _table(ax, ["Cost item", f"€ / kg {ref}", "€ / yr (plant)", "% of total"], rows,
           [0.36, 0.22, 0.18, 0.12], y_top=0.90, cell_h=0.05,
           aligns=["left", "right", "right", "right"])
    note = (f"The € / kg column is allocated: {share * 100:.0f}% of each line goes to {ref} "
            f"under {results.scenario.extraction.allocation} allocation." if mp else
            "Single product: the whole operating cost is carried by the dry biomass.")
    ax.text(0.07, 0.90 - 0.05 * (len(rows) + 1) - 0.03, note + f"  Amounts: {PRICE_BASIS}.",
            fontsize=8.5, color=SUBTLE, transform=ax.transAxes, wrap=True)

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
    colors = [CREDIT if v < 0 else BURDEN for v in vals]
    ax1 = fig.add_axes([0.34, 0.58, 0.58, 0.32])
    ax1.barh(labels, vals, color=colors, height=0.62)
    ax1.axvline(0, color=theme.CHART_AXIS, lw=0.8)
    ax1.axvline(lca.gwp_kg_co2eq_per_kg, color=INK, lw=1)
    ax1.annotate(f"net {lca.gwp_kg_co2eq_per_kg:,.2f}", xy=(lca.gwp_kg_co2eq_per_kg, 1.0),
                 xycoords=("data", "axes fraction"), xytext=(4, -2), textcoords="offset points",
                 va="top", fontsize=8.5, color=INK)
    ax1.set_title("GWP contributions (kg CO₂-eq / kg dry biomass processed)", fontsize=11,
                  color=INK, loc="left")
    ax1.set_xlabel("kg CO₂-eq / kg dry biomass processed")
    ax1.tick_params(labelsize=8.5)
    ax1.grid(True, axis="x", color=theme.CHART_GRID, linewidth=0.8)
    ax1.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax1.spines[s].set_visible(False)
    from matplotlib.patches import Patch

    ax1.legend(handles=[Patch(color=BURDEN, label="Burden"), Patch(color=CREDIT, label="Credit")],
               loc="lower right", frameon=False, fontsize=8.5)

    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.text(0.07, 0.50, "Impact categories (per kg dry biomass processed)", fontsize=12,
            fontweight="bold", color=INK, transform=ax.transAxes)
    rows = [(k, sig(v, 3)) for k, v in lca.impacts.items()]
    _table(ax, ["Impact category (unit)", "per kg dry biomass"], rows, [0.56, 0.28],
           y_top=0.46, cell_h=0.05, aligns=["left", "right"])

    _footer(fig, page, total)
    return fig


def _lca_method(results, scenario, page, total):
    """The declaration that has to travel with the impact numbers.

    A report that leaves the building carries its own scope statement: what the
    boundary is, what it excludes, where the factors came from, and which
    categories are incomplete for *this* scenario. Read from data/lcia.yaml, so
    a user who replaces the background sees their own declaration here.
    """
    from algametrix.lciamethod import completeness, load_method

    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Life-cycle method and limitations", fontsize=16,
             fontweight="bold", color=INK)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    method = load_method()
    scope = method.scope if method else {}
    rows = [
        ("Standard", "ISO 14040:2006 / ISO 14044:2006 structure"),
        ("Study type", _one_line(scope.get("study_type", "attributional"))),
        ("Boundary", _one_line(scope.get("boundary", "cradle-to-gate"))),
        ("Functional unit", _one_line(scope.get("functional_unit", ""), 62)),
        ("Geography", _one_line((scope.get("geography") or {}).get("default", ""))),
        ("Reference period", _one_line((scope.get("reference_period") or {}).get("default", ""))),
        ("Background", _one_line((scope.get("database") or {}).get("name", ""))),
        ("Cut-off", _one_line((method.cutoff if method else {}).get("rule", ""))),
    ]
    _table(ax, ["Scope", "As declared"], rows, [0.30, 0.54], y_top=0.90,
           cell_h=0.038, aligns=["left", "left"])

    y = 0.90 - 0.038 * (len(rows) + 1) - 0.042
    ax.text(0.07, y, "Outside the boundary", fontsize=12, fontweight="bold",
            color=INK, transform=ax.transAxes)
    y -= 0.028
    excluded = [str(x.get("item", "")) for x in (method.excluded if method else [])]
    for item in excluded:
        ax.text(0.09, y, f"• {item}", fontsize=9.5, color=INK, transform=ax.transAxes)
        y -= 0.022

    y -= 0.020
    ax.text(0.07, y, "Incomplete for this scenario", fontsize=12, fontweight="bold",
            color=INK, transform=ax.transAxes)
    y -= 0.028
    # Grouped by flow rather than by category: a material that carries no factor
    # anywhere is one line here instead of five.
    by_flow: dict[str, list[str]] = {}
    for gap in completeness(scenario):
        by_flow.setdefault(gap.item, []).append(_SHORT_CATEGORY.get(gap.indicator, gap.indicator))
    if by_flow:
        # The closing note is anchored to the bottom of the page, so the list has
        # to stop above it however many flows a scenario leaves open.
        rows = list(by_flow.items())
        room = max(1, int((y - 0.165) / 0.024))
        for item, categories in rows[:room]:
            ax.text(0.09, y, _one_line(f"• {item}: no {', '.join(categories)} factor", 92),
                    fontsize=9.5, color=BURDEN, transform=ax.transAxes)
            y -= 0.024
        if len(rows) > room:
            ax.text(0.09, y, f"• and {len(rows) - room} more — see the method statement",
                    fontsize=9.5, color=BURDEN, transform=ax.transAxes)
            y -= 0.024
        y -= 0.008
        ax.text(0.09, y, "These flows contribute nothing to the categories listed.",
                fontsize=9, color=SUBTLE, transform=ax.transAxes)
    else:
        ax.text(0.09, y, "Every declared material, utility and solvent carries a factor "
                         "in every category.", fontsize=9.5, color=INK, transform=ax.transAxes)

    n_ind = len(method.indicative_factors()) if method else 0
    n_all = len(method.factors) if method else 0
    note = (f"{n_ind} of the {n_all} shipped background factors are literature-typical "
            "values with no traceable dataset behind them. Water and land are inventory "
            "totals, not characterized impact indicators. Acidification, eutrophication, "
            "water and land have not been compared against any published study. Replace "
            "the background with a declared database before publishing a plant-specific "
            "result — see data/lcia.yaml.")
    ax.text(0.07, 0.062, _wrap_text(note, 92), fontsize=9, color=SUBTLE, va="bottom",
            transform=ax.transAxes)

    _footer(fig, page, total)
    return fig


#: Compact category names for the report's completeness list, where the full
#: indicator labels would truncate before the list is readable.
_SHORT_CATEGORY = {
    "gwp": "GWP", "ced": "energy", "water": "water", "land": "land",
    "eutroph_n": "marine eutr.", "eutroph_p": "freshwater eutr.",
    "acid": "acidification",
}


def _one_line(text, limit: int = 46) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _wrap_text(text: str, width: int) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(" ".join(text.split()), width=width))


def _inventory_chart(results, page, total):
    fig = _portrait()
    _watermark(fig)
    fig.text(0.07, 0.945, "Energy & mass inventory", fontsize=16, fontweight="bold", color=INK)

    eb = results.inventory.elec_breakdown
    ax = fig.add_axes([0.12, 0.42, 0.78, 0.44])
    ax.bar(list(eb.keys()), list(eb.values()), color=BAR, width=0.6)
    ax.set_title("Electricity by stage (kWh / kg dry biomass)", fontsize=11, color=INK,
                 loc="left")
    ax.set_ylabel("kWh / kg dry biomass")
    ax.tick_params(labelsize=9)
    ax.grid(True, axis="y", color=theme.CHART_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
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
    ax.plot(sens["xs"], sens["ys"], marker="o", color=BAR, lw=2, ms=6)
    ax.axhline(0, color=theme.CHART_AXIS, lw=0.8)
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
    ax.hist(unc["vals"], bins=30, color=BAR, edgecolor="white", linewidth=0.8)
    s = unc["stats"]
    for name, q, col in (("P10", s["p10"], SUBTLE), ("P50", s["p50"], INK),
                         ("P90", s["p90"], SUBTLE)):
        ax.axvline(q, color=col, lw=1)
        ax.annotate(name, xy=(q, 1.0), xycoords=("data", "axes fraction"), xytext=(3, -2),
                    textcoords="offset points", va="top", fontsize=8, color=col)
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
        (_lca_method, (results, scenario)),
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
