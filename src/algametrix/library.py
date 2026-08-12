"""Load the editable YAML data files into typed objects.

The YAML files under ``data/`` are the single source of truth for the built-in
organisms, cultivation systems, harvesting/drying presets, prices and LCIA
factors. :func:`load_library` reads them and returns ready-to-use dataclasses.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import (
    Basis,
    CarbonAccounting,
    CarbonSource,
    CultivationSystem,
    Drying,
    Economics,
    Extraction,
    Harvesting,
    LCIAFactors,
    Material,
    Organism,
    TrophicMode,
    Utility,
    WasteBurdenConvention,
    WasteFeed,
)

# Where the built-in YAML library lives, in each of the three ways it is shipped:
#   * PyInstaller bundle — alongside the executable;
#   * repository checkout — <root>/data, next to <root>/src/algametrix/library.py;
#   * installed distribution — algametrix/data, placed there by `package-dir`
#     (the checkout path would resolve to <site-packages>/../data, which is wrong).
if getattr(sys, "frozen", False):
    DEFAULT_DATA_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "data"
else:
    _CHECKOUT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
    _INSTALLED_DATA_DIR = Path(__file__).resolve().parent / "data"
    DEFAULT_DATA_DIR = (
        _CHECKOUT_DATA_DIR if _CHECKOUT_DATA_DIR.is_dir() else _INSTALLED_DATA_DIR
    )


@dataclass
class Library:
    """Named collections of the built-in building blocks."""

    organisms: dict[str, Organism]
    systems: dict[str, CultivationSystem]
    harvesting: dict[str, Harvesting]
    drying: dict[str, Drying]
    extraction: dict[str, Extraction]
    waste_feeds: dict[str, WasteFeed]
    economics: Economics
    lcia: LCIAFactors


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _organism(d: dict) -> Organism:
    return Organism(
        name=d["name"],
        group=d.get("group", ""),
        protein=float(d["protein"]),
        lipid=float(d["lipid"]),
        carbohydrate=float(d["carbohydrate"]),
        ash=float(d["ash"]),
        carbon=float(d["carbon"]),
        nitrogen=float(d["nitrogen"]),
        phosphorus=float(d["phosphorus"]),
        notes=d.get("notes", ""),
        phycocyanin=float(d.get("phycocyanin", 0.0)),
    )


def _material(d: dict) -> Material:
    return Material(
        name=d["name"],
        amount_per_kg=float(d["amount_per_kg"]),
        price=float(d.get("price", 0.0)),
        gwp=float(d.get("gwp", 0.0)),
        ced=float(d.get("ced", 0.0)),
        notes=d.get("notes", ""),
    )


def _utility(d: dict) -> Utility:
    return Utility(
        name=d["name"],
        amount_per_kg=float(d["amount_per_kg"]),
        unit=d.get("unit", ""),
        price=float(d.get("price", 0.0)),
        gwp=float(d.get("gwp", 0.0)),
        ced=float(d.get("ced", 0.0)),
        notes=d.get("notes", ""),
    )


def _system(d: dict) -> CultivationSystem:
    return CultivationSystem(
        name=d["name"],
        mode=TrophicMode(d["mode"]),
        basis=Basis(d["basis"]),
        productivity=float(d["productivity"]),
        operating_days=float(d["operating_days"]),
        biomass_conc=float(d["biomass_conc"]),
        elec_kwh_per_kg=float(d["elec_kwh_per_kg"]),
        co2_utilization=float(d.get("co2_utilization", 0.0)),
        nutrient_uptake=float(d.get("nutrient_uptake", 1.0)),
        water_m3_per_kg=float(d.get("water_m3_per_kg", 0.0)),
        substrate_yield=float(d.get("substrate_yield", 0.0)),
        capex_per_unit=float(d["capex_per_unit"]),
        land_m2_per_unit=float(d.get("land_m2_per_unit", 0.0)),
        carbon_source=CarbonSource(d.get("carbon_source", "co2")),
        cultivation_heat_mj_per_kg=float(d.get("cultivation_heat_mj_per_kg", 0.0)),
        cultivation_heat_fuel=d.get("cultivation_heat_fuel", "natural_gas"),
        notes=d.get("notes", ""),
        materials=[_material(m) for m in d.get("materials", [])],
        utilities=[_utility(u) for u in d.get("utilities", [])],
        product_price=float(d.get("product_price", 0.0)),
    )


def _harvesting(d: dict) -> Harvesting:
    return Harvesting(
        name=d["name"],
        recovery=float(d["recovery"]),
        elec_kwh_per_kg=float(d["elec_kwh_per_kg"]),
        final_solids=float(d["final_solids"]),
        notes=d.get("notes", ""),
    )


def _drying(d: dict) -> Drying:
    return Drying(
        name=d["name"],
        enabled=bool(d["enabled"]),
        final_solids=float(d["final_solids"]),
        thermal_mj_per_kg_water=float(d["thermal_mj_per_kg_water"]),
        elec_kwh_per_kg=float(d.get("elec_kwh_per_kg", 0.0)),
        fuel=d.get("fuel", "natural_gas"),
        notes=d.get("notes", ""),
    )


def _extraction(d: dict) -> Extraction:
    """Build a catalogued downstream extraction preset (always enabled=True)."""
    return Extraction(
        enabled=True,
        name=d["name"],
        disruption_elec_kwh_per_kg=float(d.get("disruption_elec_kwh_per_kg", 0.0)),
        elec_kwh_per_kg=float(d.get("elec_kwh_per_kg", 0.0)),
        heat_mj_per_kg=float(d.get("heat_mj_per_kg", 0.0)),
        solvent_name=d.get("solvent_name", "Hexane"),
        solvent_kg_per_kg=float(d.get("solvent_kg_per_kg", 0.0)),
        solvent_recovery=float(d.get("solvent_recovery", 0.95)),
        solvent_price=float(d.get("solvent_price", 0.0)),
        solvent_gwp=float(d.get("solvent_gwp", 0.0)),
        solvent_ced=float(d.get("solvent_ced", 0.0)),
        capex_per_kgyr=float(d.get("capex_per_kgyr", 0.0)),
        allocation=d.get("allocation", "economic"),
        notes=d.get("notes", ""),
    )


def _waste_feed(d: dict) -> WasteFeed:
    """Build a catalogued waste-derived feed (always enabled=True).

    Like the extraction presets, a catalogue entry is a thing you have chosen to
    use; the disabled default lives on :class:`~algametrix.models.WasteFeed`.
    """
    return WasteFeed(
        enabled=True,
        name=d["name"],
        kind=d.get("kind", "wastewater"),
        unit=d.get("unit", "m3"),
        nitrogen_per_unit=float(d.get("nitrogen_per_unit", 0.0)),
        phosphorus_per_unit=float(d.get("phosphorus_per_unit", 0.0)),
        substrate_per_unit=float(d.get("substrate_per_unit", 0.0)),
        dosed_on=d.get("dosed_on", "nitrogen"),
        coverage=float(d.get("coverage", 1.0)),
        price_per_unit=float(d.get("price_per_unit", 0.0)),
        elec_kwh_per_unit=float(d.get("elec_kwh_per_unit", 0.0)),
        gwp_per_unit=float(d.get("gwp_per_unit", 0.0)),
        ced_per_unit=float(d.get("ced_per_unit", 0.0)),
        convention=WasteBurdenConvention(d.get("convention", "cut_off")),
        avoided_treatment_gwp_per_unit=float(d.get("avoided_treatment_gwp_per_unit", 0.0)),
        avoided_treatment_ced_per_unit=float(d.get("avoided_treatment_ced_per_unit", 0.0)),
        avoided_treatment_cost_per_unit=float(d.get("avoided_treatment_cost_per_unit", 0.0)),
        notes=d.get("notes", ""),
    )


def _economics(d: dict) -> Economics:
    return Economics(**{k: float(v) for k, v in d.items()})


def _lcia(d: dict) -> LCIAFactors:
    d = dict(d)
    count = bool(d.pop("count_biogenic_uptake", True))
    mode = CarbonAccounting(d.pop("carbon_accounting", CarbonAccounting.SOURCE_SPECIFIC_CREDIT.value))
    return LCIAFactors(
        count_biogenic_uptake=count,
        carbon_accounting=mode,
        **{k: float(v) for k, v in d.items()},
    )


def load_library(data_dir: Path | str | None = None) -> Library:
    """Load all built-in data. Pass ``data_dir`` to use a custom data folder."""
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR

    organisms = [_organism(x) for x in _load_yaml(base / "organisms.yaml")]
    systems = [_system(x) for x in _load_yaml(base / "systems.yaml")]
    params = _load_yaml(base / "parameters.yaml")
    harvesting = [_harvesting(x) for x in params["harvesting"]]
    drying = [_drying(x) for x in params["drying"]]
    extraction = [_extraction(x) for x in params.get("downstream", [])]

    # Optional file: a checkout without it still loads, with an empty catalogue.
    feeds_path = base / "waste_feeds.yaml"
    feeds_doc = _load_yaml(feeds_path) if feeds_path.is_file() else {}
    waste_feeds = [_waste_feed(x) for x in (feeds_doc or {}).get("waste_feeds", [])]

    return Library(
        organisms={o.name: o for o in organisms},
        systems={s.name: s for s in systems},
        harvesting={h.name: h for h in harvesting},
        drying={d.name: d for d in drying},
        extraction={e.name: e for e in extraction},
        waste_feeds={w.name: w for w in waste_feeds},
        economics=_economics(params["economics"]),
        lcia=_lcia(params["lcia"]),
    )
