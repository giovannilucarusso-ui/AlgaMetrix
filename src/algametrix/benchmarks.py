"""Check a scenario's dry-biomass results against open-literature benchmark ranges.

This complements the SuperPro validation with *transparent, citable* ranges from
open-access / peer-reviewed studies, so a user can see whether the model output is
plausible against the published literature — not only against proprietary software.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .library import DEFAULT_DATA_DIR
from .models import Basis, TrophicMode
from .scenario import Results

# Per-kg-dry-biomass model values compared against the benchmarks.
_MODEL_VALUES = {
    "production_cost": lambda r: r.tea.production_cost_eur_per_kg,
    "gwp": lambda r: r.lca.gwp_kg_co2eq_per_kg,
    "ced": lambda r: r.lca.ced_mj_per_kg,
    "electricity": lambda r: r.inventory.elec_kwh_per_kg,
    "water": lambda r: r.lca.water_m3_per_kg,
}


@dataclass
class Benchmark:
    metric: str
    category: str
    low: float
    high: float
    unit: str
    note: str
    source: str
    url: str
    typical_low: float | None = None
    typical_high: float | None = None


@dataclass
class BenchmarkRow:
    metric: str
    unit: str
    model: float
    low: float
    high: float
    status: str          # within | above | below
    source: str
    url: str

    @property
    def in_range(self) -> bool:
        return self.status == "within"


@dataclass
class MarketPrice:
    product: str
    low: float
    high: float
    unit: str
    note: str
    source: str
    url: str


@dataclass
class ValidationReference:
    """One published TEA/LCA result the model has been checked against."""

    paper: str
    type: str          # TEA | LCA
    system: str
    metric: str
    paper_value: str
    model_value: str
    match: str
    url: str


def load_validation_references(data_dir: Path | str | None = None) -> list[ValidationReference]:
    """Published Spirulina/microalgae studies this model has been validated against."""
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    path = base / "validation_references.yaml"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return [
        ValidationReference(
            paper=d["paper"], type=d.get("type", ""), system=d.get("system", ""),
            metric=d.get("metric", ""), paper_value=str(d.get("paper_value", "")),
            model_value=str(d.get("model_value", "")), match=d.get("match", ""),
            url=d.get("url", ""),
        )
        for d in raw
    ]


def load_market_prices(data_dir: Path | str | None = None) -> list[MarketPrice]:
    """Indicative product market / production-cost ranges, for sanity-checking prices."""
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    with (base / "market_prices.yaml").open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return [
        MarketPrice(
            product=d["product"], low=float(d["low"]), high=float(d["high"]),
            unit=d.get("unit", "$/kg"), note=d.get("note", ""),
            source=d.get("source", ""), url=d.get("url", ""),
        )
        for d in raw
    ]


def load_benchmarks(data_dir: Path | str | None = None) -> list[Benchmark]:
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    with (base / "benchmarks.yaml").open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return [
        Benchmark(
            metric=d["metric"], category=d["category"],
            low=float(d["low"]), high=float(d["high"]), unit=d.get("unit", ""),
            note=d.get("note", ""), source=d.get("source", ""), url=d.get("url", ""),
            typical_low=d.get("typical_low"), typical_high=d.get("typical_high"),
        )
        for d in raw
    ]


def infer_category(system) -> str:
    """Map a cultivation system to a benchmark category."""
    if system.mode == TrophicMode.HETEROTROPHIC:
        return "heterotrophic"
    name = system.name.lower()
    if any(k in name for k in ("raceway", "cascade", "pond", "open")):
        return "open_pond"
    if any(k in name for k in ("photobioreactor", "pbr", "column", "panel", "tubular")):
        return "pbr"
    # Fall back on the sizing basis: area -> open, volume -> closed.
    return "open_pond" if system.basis == Basis.AREA else "pbr"


def check_benchmarks(results: Results, category: str | None = None,
                     benchmarks: list[Benchmark] | None = None) -> list[BenchmarkRow]:
    """Compare the scenario's per-kg-biomass metrics to the literature ranges."""
    cat = category or infer_category(results.scenario.system)
    bms = benchmarks if benchmarks is not None else load_benchmarks()
    rows: list[BenchmarkRow] = []
    for bm in bms:
        if bm.category not in (cat, "any"):
            continue
        getter = _MODEL_VALUES.get(bm.metric)
        if getter is None:
            continue
        value = getter(results)
        if value < bm.low:
            status = "below"
        elif value > bm.high:
            status = "above"
        else:
            status = "within"
        rows.append(BenchmarkRow(
            metric=bm.metric, unit=bm.unit, model=value,
            low=bm.low, high=bm.high, status=status, source=bm.source, url=bm.url,
        ))
    return rows
