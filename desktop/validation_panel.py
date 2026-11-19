"""The validation page: reference cases, literature ranges and the evidence classes.

Four sub-pages, each a table with a caption that says what the comparison can
and cannot show. Nothing here is a modal dialog any more: the reference
comparison, the benchmark check and the validation library sit next to the
results they are about, and the evidence class of every published comparison
is printed in the row.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from algametrix.benchmarks import (
    check_benchmarks,
    infer_category,
    load_benchmarks,
    load_market_prices,
    load_validation_references,
)
from algametrix.validation import compare

from . import evidence, theme
from .fmt import DASH, sig
from .i18n import tr
from .widgets import Banner, EmptyState, button, fill_table, label, make_table

SUB_REFERENCE, SUB_BENCHMARKS, SUB_LIBRARY, SUB_MARKET = range(4)

_FIT_WORD = {"good": "within 10%", "fair": "within 25%", "poor": "beyond 25%",
             "n/a": "no reference"}
_FIT_COLOR = {"good": theme.SUCCESS, "fair": theme.WARNING, "poor": theme.DANGER,
              "n/a": theme.INK_3}
_RANGE_WORD = {"within": "within range", "above": "above range", "below": "below range"}
_RANGE_COLOR = {"within": theme.SUCCESS, "above": theme.DANGER, "below": theme.WARNING}
_CATEGORY_LABEL = {"open_pond": "open pond", "pbr": "closed photobioreactor",
                   "heterotrophic": "heterotrophic fermentation"}


def _page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(10)
    return w, lay


def build(win) -> QWidget:
    outer, lay = _page()
    lay.setContentsMargins(0, 0, 0, 0)
    win.val_tabs = QTabWidget()
    win.val_tabs.addTab(_reference(win), tr("Reference case"))
    win.val_tabs.addTab(_benchmarks(win), tr("Literature ranges"))
    win.val_tabs.addTab(_library(win), tr("Validation library"))
    win.val_tabs.addTab(_market(win), tr("Market prices"))
    lay.addWidget(win.val_tabs)
    refresh_library(win)
    refresh_market(win)
    return outer


# --------------------------------------------------------------------------- #
# Reference case (SuperPro or a CSV)
# --------------------------------------------------------------------------- #
def _reference(win) -> QWidget:
    w, lay = _page()
    lay.addWidget(label(
        tr("Compare this case with a reference simulation: a bundled SuperPro case, a "
           "SuperPro Excel report, or a CSV in the template under data/. Load the matching "
           "case first (File → New case study), then the reference."), "subtle", wrap=True))
    row = QHBoxLayout()
    row.setSpacing(8)
    for text, filename in (
        ("SuperPro: heterotrophic powder", "reference_superpro_heterotrophic.csv"),
        ("SuperPro: phototrophic algal oil", "reference_superpro_phototrophic.csv"),
        ("SuperPro: omega-3 fermentation", "reference_superpro_omega3.csv"),
    ):
        row.addWidget(button(text, "secondary",
                             lambda _=False, f=filename: win.load_bundled_reference(f),
                             f"Load the bundled reference values in data/{filename}"))
    row.addWidget(button(tr("Load reference CSV…"), "secondary", win.load_reference_csv))
    row.addWidget(button(tr("Import SuperPro Excel report…"), "secondary",
                         win.load_superpro_excel))
    row.addStretch(1)
    lay.addLayout(row)
    win.lbl_reference_name = label("", "caption", wrap=True)
    lay.addWidget(win.lbl_reference_name)
    win.empty_reference = EmptyState(
        tr("No reference loaded"),
        tr("Load one of the bundled SuperPro cases above, or your own CSV or Excel report."))
    lay.addWidget(win.empty_reference)
    win.tbl_reference = make_table([tr("Metric"), tr("Unit"), tr("Reference"), tr("This tool"),
                                    "Δ %", tr("Fit")])
    win.tbl_reference.setVisible(False)
    lay.addWidget(win.tbl_reference, 1)
    lay.addWidget(label(
        tr("Fit: within 10% of the reference, within 25%, or beyond 25%. The word carries "
           "the verdict; the colour only repeats it. Deviations are in the reference's own "
           "currency and price year, which this tool does not convert."), "caption", wrap=True))
    lay.addStretch(0)
    return w


def refresh_reference(win) -> None:
    has_ref = bool(win.reference)
    has_results = win.results is not None
    show = has_ref and has_results
    win.tbl_reference.setVisible(show)
    win.empty_reference.setVisible(not show)
    if has_ref and not has_results:
        win.empty_reference.set_text(
            tr("The case is not admissible"),
            tr("Fix the inputs flagged on the Overview page; the comparison runs on the "
               "computed result."))
    elif not has_ref:
        win.empty_reference.set_text(
            tr("No reference loaded"),
            tr("Load one of the bundled SuperPro cases above, or your own CSV or Excel report."))
    name = getattr(win, "reference_name", "")
    win.lbl_reference_name.setText(f"Reference: {name}" if name else "")
    if not show:
        return
    rows = compare(win.reference, win.results)
    table_rows, colors, tips = [], {}, {}
    for i, row in enumerate(rows):
        ref = DASH if row.reference is None else sig(row.reference, 4)
        pct = DASH if row.pct_diff is None else f"{row.pct_diff:+.1f}%"
        status = row.status
        table_rows.append([row.label, row.unit, ref, sig(row.model, 4), pct, _FIT_WORD[status]])
        colors[(i, 5)] = _FIT_COLOR[status]
        colors[(i, 4)] = _FIT_COLOR[status]
        tips[(i, 0)] = f"Key: {row.metric}"
    fill_table(win.tbl_reference, table_rows, numeric_from=2, colors=colors, tooltips=tips,
               fit=True)


# --------------------------------------------------------------------------- #
# Literature ranges
# --------------------------------------------------------------------------- #
def _benchmarks(win) -> QWidget:
    w, lay = _page()
    win.lbl_bench_intro = label("", "subtle", wrap=True)
    lay.addWidget(win.lbl_bench_intro)
    win.empty_bench = EmptyState(tr("Nothing to check yet"),
                                 tr("The literature check runs on a computed case."))
    lay.addWidget(win.empty_bench)
    win.tbl_bench = make_table([tr("Metric"), tr("Unit"), tr("This tool"), tr("Published range"),
                                tr("Fit"), tr("Source")])
    win.tbl_bench.setVisible(False)
    lay.addWidget(win.tbl_bench, 1)
    win.lbl_bench_summary = label("", "caption", wrap=True)
    lay.addWidget(win.lbl_bench_summary)
    lay.addWidget(label(
        tr("Per kg of dry biomass. Published ranges are wide on purpose: they span functional "
           "units, allocation choices, biogenic-carbon conventions, energy mixes and scales. "
           "Values in the sources are in USD, read here as approximately EUR. Hover a source "
           "for its link; read it before drawing a conclusion."), "caption", wrap=True))
    lay.addStretch(0)
    return w


def refresh_benchmarks(win) -> None:
    has_results = win.results is not None
    win.tbl_bench.setVisible(has_results)
    win.empty_bench.setVisible(not has_results)
    if not has_results:
        win.lbl_bench_intro.setText("")
        win.lbl_bench_summary.setText("")
        return
    # The benchmark table is read from disk once per window, not on every keystroke.
    if getattr(win, "_benchmarks", None) is None:
        win._benchmarks = load_benchmarks()
    rows = check_benchmarks(win.results, benchmarks=win._benchmarks)
    cat = infer_category(win.system)
    win.lbl_bench_intro.setText(
        tr("Does this case fall inside what open-access studies report for a "
           "{category} system?").format(category=_CATEGORY_LABEL.get(cat, cat.replace("_", " "))))
    labels = {"production_cost": tr("Production cost"), "gwp": "GWP",
              "ced": tr("Energy demand"), "electricity": tr("Electricity")}
    table_rows, colors, tips = [], {}, {}
    for i, r in enumerate(rows):
        table_rows.append([labels.get(r.metric, r.metric), r.unit, sig(r.model, 3),
                           f"{sig(r.low, 3)} to {sig(r.high, 3)}",
                           _RANGE_WORD.get(r.status, r.status), r.source])
        colors[(i, 4)] = _RANGE_COLOR.get(r.status, theme.INK)
        if r.url:
            tips[(i, 5)] = r.url
    fill_table(win.tbl_bench, table_rows, numeric_from=2, colors=colors, tooltips=tips,
               max_width=360, fit=True)
    n_ok = sum(1 for r in rows if r.in_range)
    win.lbl_bench_summary.setText(
        tr("{ok} of {n} metrics inside the published range.").format(ok=n_ok, n=len(rows)))


# --------------------------------------------------------------------------- #
# Validation library (published studies, with evidence classes)
# --------------------------------------------------------------------------- #
def _library(win) -> QWidget:
    w, lay = _page()
    lay.addWidget(label(
        tr("Published TEA, LCA and downstream studies this model has been checked against: "
           "the paper's reported value next to this model's output. The evidence class "
           "says what each comparison depends on; hover it for the definition."),
        "subtle", wrap=True))
    win.banner_caveat = Banner("warning", evidence.CAVEATS)
    lay.addWidget(win.banner_caveat)
    win.tbl_library = make_table([tr("Paper"), tr("Type"), tr("Evidence class"), tr("Metric"),
                                  tr("Paper value"), tr("This model"), tr("Match")])
    lay.addWidget(win.tbl_library, 1)
    legend = "   ·   ".join(
        f"<b>{evidence.CLASS_LABEL[k]}</b>: {evidence.CLASS_MEANING[k]}"
        for k in ("retrospective_untuned", "component_informed", "calibrated", "range"))
    lbl = label(legend, "caption", wrap=True)
    lbl.setTextFormat(Qt.RichText)
    lay.addWidget(lbl)
    lay.addWidget(label(
        tr("Rows not in the evidence set (data/studies/studies.yaml) carry no class: they "
           "are component checks of a downstream preset, not endpoint comparisons. Full "
           "audit: docs/VALIDATION.md."), "caption", wrap=True))
    return w


def refresh_library(win) -> None:
    refs = load_validation_references()
    pairs = evidence.classify(refs)
    rows, tips, colors = [], {}, {}
    for i, (r, rec) in enumerate(pairs):
        if rec is None:
            cls = "not in evidence set"
            colors[(i, 2)] = theme.INK_3
            tips[(i, 2)] = ("This row is not a study record in data/studies/studies.yaml, so it "
                            "carries no evidence class.")
        else:
            cls = rec.class_label
            if rec.author_overlap:
                cls += " (author overlap)"
            tips[(i, 2)] = (f"{rec.short_citation} — {rec.scenario_label}. {rec.class_meaning}"
                            + (" An author of AlgaMetrix is an author of the source."
                               if rec.author_overlap else ""))
            if rec.evidence_class == "calibrated":
                colors[(i, 2)] = theme.WARNING
        rows.append([r.paper, r.type, cls, r.metric, r.paper_value, r.model_value, r.match])
        if r.system or r.url:
            tips[(i, 0)] = f"{r.system}\n{r.url}".strip()
    fill_table(win.tbl_library, rows, numeric_from=4, tooltips=tips, colors=colors,
               max_width=250, fit=True)
    if not rows:
        win.tbl_library.setRowCount(0)


# --------------------------------------------------------------------------- #
# Market prices
# --------------------------------------------------------------------------- #
def _market(win) -> QWidget:
    w, lay = _page()
    lay.addWidget(label(
        tr("Order-of-magnitude selling-price ranges, to sanity-check the product price you "
           "enter. Broad and time-varying; USD read as approximately EUR. Hover a source "
           "for its link."), "subtle", wrap=True))
    win.tbl_market = make_table([tr("Product"), tr("Range"), tr("Unit"), tr("Source")])
    lay.addWidget(win.tbl_market, 1)
    return w


def refresh_market(win) -> None:
    prices = load_market_prices()
    rows, tips = [], {}
    for i, p in enumerate(prices):
        rows.append([p.product, f"{sig(p.low, 3)} to {sig(p.high, 3)}", p.unit, p.source])
        if p.note or p.url:
            tips[(i, 0)] = p.note
            tips[(i, 3)] = p.url
    fill_table(win.tbl_market, rows, numeric_from=1, tooltips=tips)
    win.tbl_market.horizontalHeader().setStretchLastSection(True)


def refresh_all(win) -> None:
    refresh_reference(win)
    refresh_benchmarks(win)
