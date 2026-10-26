"""Regional electricity values offered by the desktop guided setup.

Picking a region fills two scenario inputs: the electricity price the TEA
charges and the grid emission factor the LCA applies. Both are read from
``data/regions.yaml``, where every value carries its source, reference year,
geography and quality flag, like the background factors in ``data/lcia.yaml``.
A region with no national price statistic sets the grid factor only.

The library and the paper do not use these values; a scenario only picks them
up when a user chooses a region.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

import yaml

FILENAME = "regions.yaml"


@dataclass(frozen=True)
class RegionalValue:
    """One number with the provenance it must carry."""

    value: float
    year: int
    geography: str
    quality: str          # sourced | derived
    source: str


@dataclass(frozen=True)
class Region:
    name: str
    grid: RegionalValue                  # kg CO2-eq per kWh generated
    price: RegionalValue | None = None   # EUR per kWh; None where no statistic exists
    price_note: str = ""

    def apply(self, scenario) -> None:
        """Set the scenario's grid factor, and its electricity price if there is one."""
        scenario.lcia.elec_gwp = self.grid.value
        if self.price is not None:
            scenario.economics.electricity_price = self.price.value


@dataclass(frozen=True)
class RegionalElectricity:
    """The contents of ``regions.yaml``."""

    regions: tuple[Region, ...]
    reference_year: int
    accessed: str
    price_unit: str
    price_scope: str
    grid_unit: str
    grid_scope: str
    grid_source: str

    def names(self) -> list[str]:
        return [r.name for r in self.regions]

    def get(self, name: str) -> Region:
        for r in self.regions:
            if r.name == name:
                return r
        raise KeyError(name)


def _text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _value(d: dict | None) -> RegionalValue | None:
    if not d:
        return None
    return RegionalValue(
        value=float(d["value"]),
        year=int(d["year"]),
        geography=_text(d.get("geography")),
        quality=_text(d.get("quality")),
        source=_text(d.get("source")),
    )


def load_regions(data_dir: Path | str | None = None) -> RegionalElectricity | None:
    """Read ``regions.yaml`` from ``data_dir``. ``None`` when the file is absent."""
    from .library import DEFAULT_DATA_DIR

    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    path = base / FILENAME
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    price = doc.get("price") or {}
    grid = doc.get("grid") or {}
    regions = tuple(
        Region(
            name=_text(d["name"]),
            grid=_value(d["grid"]),
            price=_value(d.get("price")),
            price_note=_text(d.get("price_note")),
        )
        for d in doc.get("regions") or []
    )
    return RegionalElectricity(
        regions=regions,
        reference_year=int(doc.get("reference_year", 0)),
        accessed=_text(doc.get("accessed")),
        price_unit=_text(price.get("unit")),
        price_scope=_text(price.get("scope")),
        grid_unit=_text(grid.get("unit")),
        grid_scope=_text(grid.get("scope")),
        grid_source=_text(grid.get("source")),
    )


def describe(region: Region) -> str:
    """One line per value, for the setup page: what was set and where it comes from."""
    lines = [f"Grid factor {region.grid.value:g} kg CO2-eq/kWh, {region.grid.year}: "
             f"{region.grid.source}"]
    if region.price is not None:
        lines.append(f"Price {region.price.value:g} EUR/kWh, {region.price.year}: "
                     f"{region.price.source}")
    else:
        lines.append(f"Price not set. {region.price_note}")
    return "\n".join(lines)


def statement(data: RegionalElectricity, *, width: int = 88) -> str:
    """The regional values as a table with their sources, for the method statement."""
    def wrap(text: str, indent: str = "  ") -> str:
        return textwrap.fill(text, width=width, initial_indent=indent,
                             subsequent_indent=indent)

    rows = [("region", f"price {data.price_unit}", "year", f"grid {data.grid_unit}", "year")]
    for r in data.regions:
        rows.append((
            r.name,
            f"{r.price.value:g}" if r.price is not None else "-",
            str(r.price.year) if r.price is not None else "",
            f"{r.grid.value:g}",
            str(r.grid.year),
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    for n, row in enumerate(rows):
        out.append("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
        if n == 0:
            out.append("  " + "  ".join("-" * w for w in widths))
    out += ["", wrap(f"Price: {data.price_scope}"), "",
            wrap(f"Grid factor: {data.grid_scope} Source: {data.grid_source}"), ""]
    out.append("  Price sources:")
    for r in data.regions:
        note = r.price.source if r.price is not None else f"not set. {r.price_note}"
        out.append(textwrap.fill(f"{r.name}: {note}", width=width,
                                 initial_indent="    - ", subsequent_indent="      "))
    return "\n".join(out)
