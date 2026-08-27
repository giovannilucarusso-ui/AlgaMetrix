"""The life-cycle method declaration: what the LCA is, and what it is not.

``data/lcia.yaml`` holds both the characterization factors the LCA uses and the
declaration that has to travel with them - goal and scope, functional unit,
boundary, cut-off, allocation, impact assessment method, geography, reference
period, and the list of what sits outside the boundary. ISO 14044 clause 4.2.3
asks a study for that declaration; before this module the factors were numbers
in a YAML file and a few defaults hard-coded in :mod:`algametrix.models`, with
nothing saying where they came from.

Three things live here:

* :func:`load_method` reads the file into typed objects, and
  :meth:`LCIAMethod.lcia_factors` builds the :class:`~algametrix.models.LCIAFactors`
  the engine runs on, so the declaration and the numbers cannot drift apart;
* :func:`method_statement` renders the whole declaration as text, for a report,
  a supplementary file or ``python -m algametrix.lciamethod``;
* :func:`completeness` answers the question a coverage table raises - for *this*
  scenario, which flows entered which impact category, and which carry no factor
  and were therefore left out rather than counted as zero.

The background is aggregated: one already-characterized number per input per
category, no elementary flows, no licensed database. That is a deliberate
constraint - the software has to run without a database licence - and it costs
substance-level contribution analysis, regionalization and any characterization
of its own. The limitations are declared in the file and printed with the
statement.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import CarbonAccounting, LCIAFactors

#: Name of the declaration file inside a data directory.
FILENAME = "lcia.yaml"

#: Impact categories a declared material or utility can carry, mapped to the
#: field that carries them. The keys are the indicator keys of ``lcia.yaml``.
ITEM_FACTOR_FIELDS = {
    "gwp": "gwp",
    "ced": "ced",
    "water": "water",
    "land": "land",
    "eutroph_n": "eutroph_n",
    "eutroph_p": "eutroph_p",
    "acid": "acid",
}


@dataclass(frozen=True)
class Indicator:
    """One reported impact category and the characterization behind it."""

    key: str
    label: str
    unit: str
    method: str
    kind: str          # "characterized" or "inventory"
    note: str = ""


@dataclass(frozen=True)
class InputSpec:
    """One background input the factor table can characterize."""

    key: str
    label: str
    unit: str
    note: str = ""


@dataclass(frozen=True)
class Factor:
    """One characterization factor, with the provenance it must carry."""

    name: str            # the LCIAFactors field it fills
    input: str
    indicator: str
    value: float
    unit: str
    quality: str         # sourced | derived | indicative
    source: str
    geography: str = ""
    reference_period: str = ""


@dataclass(frozen=True)
class LCIAMethod:
    """The declaration in ``data/lcia.yaml``, read into objects."""

    name: str
    version: int
    released: str
    standard: tuple[str, ...]
    scope: dict                       # the rest of the `method:` block
    indicators: tuple[Indicator, ...]
    inputs: tuple[InputSpec, ...]
    factors: tuple[Factor, ...]
    inventory_assumptions: dict
    conventions: dict
    included: tuple[str, ...]
    excluded: tuple[dict, ...]
    cutoff: dict
    allocation: dict
    limitations: tuple[dict, ...]
    path: Path | None = None
    _extra_values: dict = field(default_factory=dict)

    # -- the numbers -------------------------------------------------------
    def factor_values(self) -> dict[str, float]:
        """Every value the file declares, keyed by its ``LCIAFactors`` field."""
        values = {f.name: f.value for f in self.factors}
        values.update(self._extra_values)
        return values

    def lcia_factors(self) -> LCIAFactors:
        """The :class:`LCIAFactors` this declaration describes."""
        values = self.factor_values()
        conventions = dict(self.conventions)
        count = bool(conventions.pop("count_biogenic_uptake", True))
        mode = CarbonAccounting(
            conventions.pop("carbon_accounting", CarbonAccounting.SOURCE_SPECIFIC_CREDIT.value)
        )
        values.update({k: float(v) for k, v in conventions.items()})
        return LCIAFactors(count_biogenic_uptake=count, carbon_accounting=mode, **values)

    # -- what it covers ----------------------------------------------------
    def indicator(self, key: str) -> Indicator | None:
        return next((i for i in self.indicators if i.key == key), None)

    def coverage(self) -> dict[str, dict[str, str | None]]:
        """``{input key: {indicator key: factor name or None}}``.

        A ``None`` is the point of the table: that input carries no factor for
        that category, so it contributes nothing to it. Nothing in the engine
        distinguishes an absent factor from a zero one, which is why the table
        is generated from the declaration rather than written by hand.
        """
        table: dict[str, dict[str, str | None]] = {
            inp.key: {ind.key: None for ind in self.indicators} for inp in self.inputs
        }
        for f in self.factors:
            table.setdefault(f.input, {ind.key: None for ind in self.indicators})
            table[f.input][f.indicator] = f.name
        # Two inputs enter their category directly from the inventory, with no
        # factor in between: process water and the site's own land occupation.
        if "process_water" in table:
            table["process_water"]["water"] = "(direct)"
        if "land" in table:
            table["land"]["land"] = "(direct)"
        # Declared materials and utilities carry their factors on the scenario.
        for key in ("material", "utility"):
            if key in table:
                for ind in self.indicators:
                    table[key][ind.key] = "(per item)"
        if "waste_feed" in table:
            table["waste_feed"]["gwp"] = "(per feed)"
            table["waste_feed"]["ced"] = "(per feed)"
        if "solvent" in table:
            table["solvent"]["gwp"] = "(per preset)"
            table["solvent"]["ced"] = "(per preset)"
        return table

    def indicative_factors(self) -> tuple[Factor, ...]:
        """The factors that carry no traceable dataset."""
        return tuple(f for f in self.factors if f.quality == "indicative")


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def load_method(data_dir: Path | str | None = None) -> LCIAMethod | None:
    """Read ``lcia.yaml`` from ``data_dir``. ``None`` when the file is absent.

    A data directory without the declaration still loads elsewhere - the factors
    then come from the ``lcia:`` block of ``parameters.yaml`` - so this returns
    ``None`` rather than raising.
    """
    from .library import DEFAULT_DATA_DIR

    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    path = base / FILENAME
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return _build(doc, path)


def _build(doc: dict, path: Path | None) -> LCIAMethod:
    meta = dict(doc.get("method") or {})
    name = _text(meta.pop("name", "unnamed background"))
    version = int(meta.pop("version", 0))
    released = _text(meta.pop("released", ""))
    standard = tuple(_text(s) for s in meta.pop("standard", []) or [])

    indicators = tuple(
        Indicator(
            key=_text(d["key"]),
            label=_text(d.get("label", d["key"])),
            unit=_text(d.get("unit", "")),
            method=_text(d.get("method", "")),
            kind=_text(d.get("kind", "characterized")),
            note=_text(d.get("note", "")),
        )
        for d in doc.get("indicators") or []
    )
    inputs = tuple(
        InputSpec(
            key=_text(d["key"]),
            label=_text(d.get("label", d["key"])),
            unit=_text(d.get("unit", "")),
            note=_text(d.get("note", "")),
        )
        for d in doc.get("inputs") or []
    )
    factors = tuple(
        Factor(
            name=key,
            input=_text(d.get("input", "")),
            indicator=_text(d.get("indicator", "")),
            value=float(d["value"]),
            unit=_text(d.get("unit", "")),
            quality=_text(d.get("quality", "")),
            source=_text(d.get("source", "")),
            geography=_text(d.get("geography", "")),
            reference_period=_text(d.get("reference_period", "")),
        )
        for key, d in (doc.get("factors") or {}).items()
    )
    assumptions = dict(doc.get("inventory_assumptions") or {})
    return LCIAMethod(
        name=name,
        version=version,
        released=released,
        standard=standard,
        scope=meta,
        indicators=indicators,
        inputs=inputs,
        factors=factors,
        inventory_assumptions=assumptions,
        conventions=dict(doc.get("conventions") or {}),
        included=tuple(_text(x) for x in doc.get("included") or []),
        excluded=tuple(doc.get("excluded") or []),
        cutoff=dict(doc.get("cutoff") or {}),
        allocation=dict(doc.get("allocation") or {}),
        limitations=tuple(doc.get("limitations") or []),
        path=path,
        _extra_values={k: float(v["value"]) for k, v in assumptions.items()},
    )


# --------------------------------------------------------------------------- #
# The statement
# --------------------------------------------------------------------------- #
def _wrap(text: str, width: int, indent: str = "  ") -> str:
    return textwrap.fill(" ".join(text.split()), width=width,
                         initial_indent=indent, subsequent_indent=indent)


def _heading(title: str, width: int) -> str:
    return f"\n{title}\n{'-' * min(len(title), width)}"


def _labelled(label: str, text: str, width: int, pad: int = 16) -> str:
    """``  label : text``, wrapped under the text rather than under the label."""
    head = f"  {label:<{pad}}: "
    return textwrap.fill(" ".join(text.split()), width=width,
                         initial_indent=head, subsequent_indent=" " * len(head))


def _bullet(text: str, width: int, indent: str = "    ") -> str:
    return textwrap.fill(" ".join(text.split()), width=width,
                         initial_indent=f"{indent}- ", subsequent_indent=f"{indent}  ")


def method_statement(method: LCIAMethod, *, width: int = 88) -> str:
    """The whole declaration as text, in the order ISO 14040 puts its phases."""
    out: list[str] = []
    title = f"{method.name} v{method.version}"
    out.append("LIFE-CYCLE ASSESSMENT - METHOD STATEMENT")
    out.append("=" * width)
    out.append(f"Background   : {title}" + (f"  (released {method.released})" if method.released else ""))
    if method.path is not None:
        out.append(f"Declared in  : {method.path.name}")
    for s in method.standard:
        out.append(textwrap.fill(s, width=width, initial_indent="Standard     : ",
                                 subsequent_indent=" " * 15))

    scope = method.scope
    out.append(_heading("1  Goal and scope", width))
    for key in ("study_type", "modelling", "boundary", "functional_unit",
                "reference_flow", "gate"):
        if scope.get(key):
            out.append(_labelled(key.replace("_", " ").capitalize(), _text(scope[key]), width))
    for key in ("geography", "reference_period", "database"):
        block = scope.get(key) or {}
        if isinstance(block, dict):
            head = _text(block.get("default") or block.get("name"))
            out.append(_labelled(key.replace("_", " ").capitalize(), head, width))
            if block.get("note"):
                out.append(_wrap(_text(block["note"]), width, indent=" " * 20))
    if scope.get("conformance"):
        out.append("")
        out.append(_wrap(_text(scope["conformance"]), width))

    out.append(_heading("2  System boundary", width))
    out.append("  Inside:")
    for item in method.included:
        out.append(_bullet(item, width))
    out.append("  Outside:")
    for item in method.excluded:
        out.append(_bullet(f"{_text(item.get('item'))}: {_text(item.get('note'))}", width))
    if method.cutoff:
        out.append(f"  Cut-off rule: {_text(method.cutoff.get('rule'))}")
        for key in ("note", "recycled_content"):
            if method.cutoff.get(key):
                out.append(_wrap(_text(method.cutoff[key]), width, indent="    "))

    out.append(_heading("3  Allocation", width))
    if method.allocation.get("hierarchy"):
        out.append(_wrap(_text(method.allocation["hierarchy"]), width))
    for step in method.allocation.get("implemented") or []:
        out.append(f"  Step {_text(step.get('step'))}")
        out.append(_wrap(_text(step.get("how")), width, indent="    "))
    for key in ("sensitivity", "biogenic_carbon"):
        if method.allocation.get(key):
            out.append(f"  {key.replace('_', ' ').capitalize()}:")
            out.append(_wrap(_text(method.allocation[key]), width, indent="    "))

    out.append(_heading("4  Impact assessment", width))
    for ind in method.indicators:
        out.append(f"  {ind.label} [{ind.unit}]")
        out.append(_labelled("method", f"{ind.method}  ({ind.kind})", width, pad=8))
        if ind.note:
            out.append(_wrap(ind.note, width, indent="    "))

    out.append(_heading("5  Background factors", width))
    out.append(_factor_table(method))
    out.append("")
    out.append("  Foreground partitioning (inventory, not characterization):")
    for key, entry in method.inventory_assumptions.items():
        out.append(f"    {key} = {entry.get('value')}  [{_text(entry.get('unit'))}] ({_text(entry.get('quality'))})")
        out.append(_wrap(_text(entry.get("source")), width, indent="      "))

    out.append(_heading("6  Coverage", width))
    out.append(_coverage_table(method, width))

    out.append(_heading("7  Declared limitations", width))
    for lim in method.limitations:
        out.append(f"  [{_text(lim.get('id'))}]")
        out.append(_wrap(_text(lim.get("text")), width, indent="    "))

    indicative = method.indicative_factors()
    out.append("")
    out.append(_wrap(
        f"{len(indicative)} of {len(method.factors)} factors are flagged `indicative`: "
        "literature-typical values with no traceable dataset behind them. Replace them "
        "with data from a declared database before publishing a plant-specific result.",
        width, indent="  "))
    return "\n".join(out)


def _factor_table(method: LCIAMethod) -> str:
    rows = [("factor", "value", "unit", "geography", "period", "quality")]
    rows += [
        (f.name, f"{f.value:g}", f.unit, f.geography, f.reference_period, f.quality)
        for f in sorted(method.factors, key=lambda x: (x.input, x.indicator))
    ]
    return _grid(rows, indent="  ")


def _coverage_table(method: LCIAMethod, width: int) -> str:
    """Input x indicator, so an empty cell is visible rather than implied."""
    cov = method.coverage()
    header = ["input"] + [ind.key for ind in method.indicators]
    rows = [tuple(header)]
    for inp in method.inputs:
        cells = []
        for ind in method.indicators:
            mark = cov.get(inp.key, {}).get(ind.key)
            cells.append("-" if mark is None else ("x" if mark.isidentifier() else mark))
        rows.append(tuple([inp.key] + cells))
    legend = ("    x = a factor in this file; (direct) = carried straight from the inventory; "
              "(per item)/(per preset)/(per feed) = declared on the scenario; - = not "
              "characterized, so the input contributes nothing to that category.")
    return _grid(rows, indent="  ") + "\n" + textwrap.fill(
        " ".join(legend.split()), width=width, initial_indent="    ", subsequent_indent="    ")


def _grid(rows: list[tuple[str, ...]], indent: str = "") -> str:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    out = []
    for n, row in enumerate(rows):
        out.append(indent + "  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())
        if n == 0:
            out.append(indent + "  ".join("-" * w for w in widths))
    return "\n".join(out)


def factor_rows(method: LCIAMethod) -> list[dict]:
    """The factor table as records, for a CSV export."""
    rows = [
        {
            "factor": f.name,
            "input": f.input,
            "indicator": f.indicator,
            "value": f.value,
            "unit": f.unit,
            "geography": f.geography,
            "reference_period": f.reference_period,
            "quality": f.quality,
            "source": " ".join(f.source.split()),
        }
        for f in sorted(method.factors, key=lambda x: (x.input, x.indicator))
    ]
    rows += [
        {
            "factor": key,
            "input": "foreground",
            "indicator": "inventory partitioning",
            "value": entry.get("value"),
            "unit": _text(entry.get("unit")),
            "geography": "",
            "reference_period": "",
            "quality": _text(entry.get("quality")),
            "source": " ".join(_text(entry.get("source")).split()),
        }
        for key, entry in method.inventory_assumptions.items()
    ]
    return rows


# --------------------------------------------------------------------------- #
# Completeness of one scenario
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Gap:
    """One flow that carries no factor for one impact category."""

    item: str
    kind: str          # "material" | "utility" | "solvent"
    indicator: str

    def __str__(self) -> str:
        return f"{self.item} ({self.kind}): no {self.indicator} factor"


def completeness(scenario) -> list[Gap]:
    """Flows this scenario declares that no factor characterizes.

    Materials and utilities carry their own factors, and a category left
    undeclared contributes nothing to that category - which is not the same as
    contributing zero. This lists those gaps so a result can say which of its
    categories are incomplete for the case at hand, rather than only which ones
    the background covers in general.

    ``gwp`` and ``ced`` are plain floats defaulting to 0.0, so a declared zero
    reads here as undeclared. That is the conservative direction: a burden left
    at zero because nobody supplied a number is reported, and one that is
    genuinely nil costs a line in the completeness report. The five newer
    factors distinguish the two properly, being ``None`` until declared.
    """
    gaps: list[Gap] = []
    for kind, items in (("material", scenario.materials), ("utility", scenario.utilities)):
        for item in items:
            if not item.amount_per_kg:
                continue
            for indicator, attr in ITEM_FACTOR_FIELDS.items():
                if not getattr(item, attr, None):
                    gaps.append(Gap(item=item.name, kind=kind, indicator=indicator))
    ext = getattr(scenario, "extraction", None)
    if ext is not None and getattr(ext, "enabled", False) and ext.solvent_kg_per_kg:
        for indicator in ("water", "land", "eutroph_n", "eutroph_p"):
            gaps.append(Gap(item=ext.solvent_name or "solvent", kind="solvent", indicator=indicator))
    return gaps


def completeness_report(scenario, *, width: int = 88) -> str:
    """The gaps of :func:`completeness`, grouped by impact category."""
    gaps = completeness(scenario)
    if not gaps:
        return "Every declared material, utility and solvent carries a factor in every category."
    by_indicator: dict[str, list[Gap]] = {}
    for gap in gaps:
        by_indicator.setdefault(gap.indicator, []).append(gap)
    out = ["Flows declared by this scenario that no factor characterizes:"]
    for indicator, items in by_indicator.items():
        names = ", ".join(sorted({g.item for g in items}))
        out.append(_wrap(f"{indicator}: {names}", width, indent="  "))
    out.append(_wrap(
        "These contribute nothing to the categories listed, which understates them by an "
        "unknown amount. Declare the missing factors on the material or utility, or report "
        "those categories as incomplete.", width, indent="  "))
    return "\n".join(out)


if __name__ == "__main__":  # pragma: no cover - a convenience entry point
    _method = load_method()
    print(method_statement(_method) if _method else "No lcia.yaml in the data directory.")
