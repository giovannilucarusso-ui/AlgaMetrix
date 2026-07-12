"""Validation against an external reference (e.g. SuperPro Designer).

SuperPro Designer stores projects in a proprietary binary format (``.spf`` /
``.dyn``) that cannot be read here. Instead, validation works from data the user
*exports* from SuperPro:

1. **Reference CSV** (recommended, always works) -- a small two-column file
   ``metric,value`` that the user fills in from any SuperPro report. A template
   is provided in ``data/superpro_reference_template.csv``.

2. **Excel export** (best-effort) -- SuperPro's "Economic Evaluation Report"
   exported to Excel. :func:`parse_superpro_excel` scans the sheet for known
   labels and pulls the adjacent number. Layouts vary between SuperPro versions,
   so always check the parsed values; fall back to the CSV if a metric is missed.

:func:`compare` then puts the reference next to this tool's results and reports
the percentage deviation, so you can see how well the model reproduces SuperPro.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .scenario import Results

# Canonical metric keys used throughout validation, with a human label and unit.
METRICS: dict[str, tuple[str, str]] = {
    "total_capex_eur": ("Total capital investment", "EUR"),
    "annual_opex_eur": ("Annual operating cost", "EUR/yr"),
    "production_cost_eur_per_kg": ("Unit production cost", "EUR/kg"),
    "annual_production_kg": ("Annual production", "kg/yr"),
    "electricity_kwh_per_kg": ("Electricity", "kWh/kg"),
    "annual_revenue_eur": ("Total revenues", "EUR/yr"),
    "npv_eur": ("Net present value", "EUR"),
}

# Keywords found in SuperPro Excel reports mapped to canonical metric keys.
# First match wins, so order from most specific to least specific.
_EXCEL_KEYWORDS: list[tuple[str, str]] = [
    ("total capital investment", "total_capex_eur"),
    ("direct fixed capital", "total_capex_eur"),
    ("capital investment", "total_capex_eur"),
    ("annual operating cost", "annual_opex_eur"),
    ("total operating cost", "annual_opex_eur"),
    ("operating cost", "annual_opex_eur"),
    ("unit production cost", "production_cost_eur_per_kg"),
    ("production cost", "production_cost_eur_per_kg"),
    ("cost basis annual rate", "annual_production_kg"),
    ("annual production rate", "annual_production_kg"),
    ("annual production", "annual_production_kg"),
    ("annual throughput", "annual_production_kg"),
    ("total revenues", "annual_revenue_eur"),
    ("main revenue", "annual_revenue_eur"),
    ("net present value", "npv_eur"),
    ("npv", "npv_eur"),
]


@dataclass
class ComparisonRow:
    """One metric compared between the reference and the model."""

    metric: str
    label: str
    unit: str
    reference: float | None
    model: float
    pct_diff: float | None  # (model - reference) / reference * 100

    @property
    def status(self) -> str:
        if self.pct_diff is None:
            return "n/a"
        a = abs(self.pct_diff)
        if a <= 10:
            return "good"       # within 10%
        if a <= 25:
            return "fair"       # within 25%
        return "poor"


def _to_number(text: str) -> float | None:
    """Extract a float from a messy cell like '$ 12,500,000' or '6.14 EUR/kg'."""
    if text is None:
        return None
    s = str(text).strip()
    # Keep digits, sign, decimal point and thousands separators; drop the rest.
    m = re.search(r"-?\d[\d,\.\s]*", s)
    if not m:
        return None
    raw = m.group(0).replace(" ", "")
    # Assume '.' is the decimal separator and ',' the thousands separator.
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def model_metrics(results: Results) -> dict[str, float]:
    """Extract the canonical metrics from this tool's results.

    In a biorefinery (a main product is defined) the unit production cost and the
    annual production rate refer to the main product, matching how SuperPro reports
    them against the "Main Product/Revenue" stream. Otherwise they refer to biomass.
    """
    if results.main_product:
        production_cost = results.main_product.production_cost_eur_per_kg
        annual_production = results.main_product.annual_kg
    else:
        production_cost = results.tea.production_cost_eur_per_kg
        annual_production = results.inventory.annual_biomass_kg
    return {
        "total_capex_eur": results.tea.total_investment,
        "annual_opex_eur": results.tea.annual_opex,
        "production_cost_eur_per_kg": production_cost,
        "annual_production_kg": annual_production,
        "electricity_kwh_per_kg": results.inventory.elec_kwh_per_kg,
        "annual_revenue_eur": results.tea.revenues,
        "npv_eur": results.tea.npv,
    }


def parse_reference_csv(path: Path | str) -> dict[str, float]:
    """Read a two-column ``metric,value`` reference file. Unknown keys are ignored."""
    ref: dict[str, float] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].strip().startswith("#"):
                continue
            key = row[0].strip()
            if key not in METRICS or len(row) < 2:
                continue
            # Re-join the remaining fields: a value like "15,630,000" is split by
            # the CSV reader on its thousands separators.
            val = _to_number(",".join(row[1:]))
            if val is not None:
                ref[key] = val
    return ref


def parse_superpro_excel(path: Path | str) -> dict[str, float]:
    """Best-effort scan of a SuperPro Excel report for the canonical metrics.

    Returns only the metrics it could locate. Always sanity-check the result.
    """
    import openpyxl

    wb = openpyxl.load_workbook(Path(path), data_only=True, read_only=True)
    found: dict[str, float] = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if not isinstance(cell, str):
                    continue
                label = cell.strip().lower()
                for keyword, metric in _EXCEL_KEYWORDS:
                    if metric in found or keyword not in label:
                        continue
                    value = _value_near(rows, r, c)
                    if value is not None:
                        found[metric] = value
    wb.close()
    return found


def _value_near(rows, r: int, c: int) -> float | None:
    """Find the first numeric value to the right of, or below, cell (r, c)."""
    row = rows[r]
    for cell in row[c + 1:]:                       # rest of the same row
        if isinstance(cell, (int, float)):
            return float(cell)
        num = _to_number(cell) if isinstance(cell, str) else None
        if num is not None:
            return num
    if r + 1 < len(rows) and c < len(rows[r + 1]):  # cell directly below
        below = rows[r + 1][c]
        if isinstance(below, (int, float)):
            return float(below)
        return _to_number(below) if isinstance(below, str) else None
    return None


def compare(reference: dict[str, float], results: Results) -> list[ComparisonRow]:
    """Build a side-by-side comparison for every known metric."""
    model = model_metrics(results)
    out: list[ComparisonRow] = []
    for key, (label, unit) in METRICS.items():
        ref = reference.get(key)
        mod = model[key]
        pct = ((mod - ref) / ref * 100.0) if ref not in (None, 0) else None
        out.append(ComparisonRow(key, label, unit, ref, mod, pct))
    return out
