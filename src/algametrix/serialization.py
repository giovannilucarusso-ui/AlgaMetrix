"""Read and write a :class:`~algametrix.models.Scenario` as JSON.

One serialisation, used by the desktop client's *Save scenario* and *Open
scenario* and by any script that wants to hand a case to somebody else. It is
deliberately exhaustive: a saved file carries **every** field of the scenario,
including the ones no widget shows, because a case that comes back missing its
extraction step or its waste feed is worse than one that never saved.

The format is a flat JSON object — the dataclass fields at the top level, plus
``format`` and ``version`` — so a reader can see what a file holds without this
module. Reading follows two rules:

* **Unknown keys are ignored.** A file written by a later patch release that
  added a field still loads here.
* **Missing keys keep the dataclass default.** A file written before a field
  existed still loads, and the field takes the value it would have had.

A file declaring a *newer* format version is refused rather than partially
loaded: silently dropping half a case is the failure this module exists to
prevent. :data:`VERSION` 1 was the desktop client's original nine-key file; it
is migrated on read.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, ForwardRef, Union, get_args, get_origin, get_type_hints

from . import models
from .models import Scenario

#: What the ``format`` key of a saved file says.
FORMAT = "algametrix.scenario"
#: Bumped when a field is renamed or its meaning changes — not when one is added.
VERSION = 2


class ScenarioFormatError(ValueError):
    """A file is not a scenario this version can read."""


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #
def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def scenario_to_dict(scenario: Scenario) -> dict:
    """The scenario as a JSON-compatible dict, every field included."""
    return {"format": FORMAT, "version": VERSION, **_encode(scenario)}


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #
def _resolve(tp: Any) -> Any:
    """Turn a forward reference into the class it names.

    ``models.py`` writes ``list["Material"]``. Python 3.11 and later resolve that
    inner string through :func:`get_type_hints`; 3.10 leaves it as a
    ``ForwardRef``, and a ForwardRef matches none of the branches below — so
    every material and utility came back out of a file as a plain ``dict``,
    silently, on the oldest Python this project supports.
    """
    if isinstance(tp, ForwardRef):
        tp = tp.__forward_arg__
    if isinstance(tp, str):
        return getattr(models, tp, tp)
    return tp


def _optional_of(tp: Any) -> Any:
    """The ``X`` of an ``X | None`` annotation, or ``None`` if it is not one."""
    if get_origin(tp) not in (Union, UnionType):
        return None
    args = [a for a in get_args(tp) if a is not type(None)]
    return args[0] if len(args) == 1 else None


def _decode(tp: Any, value: Any) -> Any:
    tp = _resolve(tp)
    if _optional_of(tp) is not None:
        # `float | None` on a material's water or acidification factor: None is
        # "no factor declared", which the LCA reports rather than treating as a
        # zero burden, so it has to survive a save and a reload as None.
        return None if value is None else _decode(_optional_of(tp), value)
    if get_origin(tp) is list:
        (item_tp,) = get_args(tp) or (Any,)
        return [_decode(item_tp, v) for v in (value or [])]
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if is_dataclass(tp):
        return _build(tp, value or {})
    if tp is bool:
        return bool(value)
    if tp is float:
        return float(value)
    if tp is int:
        return int(value)
    if tp is str:
        return "" if value is None else str(value)
    return value


def _build(cls: type, data: dict) -> Any:
    if not isinstance(data, dict):
        raise ScenarioFormatError(f"expected an object for {cls.__name__}, got {type(data).__name__}")
    hints = get_type_hints(cls, vars(models))
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue  # absent -> the dataclass default, which is the point
        try:
            kwargs[f.name] = _decode(hints[f.name], data[f.name])
        except (TypeError, ValueError) as exc:
            raise ScenarioFormatError(f"{cls.__name__}.{f.name}: {exc}") from exc
    try:
        return cls(**kwargs)
    except TypeError as exc:  # a required field the file does not carry
        raise ScenarioFormatError(f"{cls.__name__}: {exc}") from exc


def _migrate(data: dict) -> dict:
    """Bring an older file up to the current field names."""
    version = int(data.get("version", 1))
    if version > VERSION:
        raise ScenarioFormatError(
            f"this file was written by a newer version of AlgaMetrix "
            f"(scenario format {version}, this build reads up to {VERSION}). "
            f"Update AlgaMetrix rather than load it partially."
        )
    if version < 2:
        # v1: the desktop client wrote nine keys and shortened one field name.
        if "coproduct_revenue" in data and "coproduct_revenue_per_year" not in data:
            data["coproduct_revenue_per_year"] = data["coproduct_revenue"]
    return data


def scenario_from_dict(data: dict) -> Scenario:
    """Rebuild a scenario from :func:`scenario_to_dict` output (or an older file)."""
    if not isinstance(data, dict):
        raise ScenarioFormatError("a scenario file must contain a JSON object")
    fmt = data.get("format", FORMAT)
    if fmt != FORMAT:
        raise ScenarioFormatError(f"not an AlgaMetrix scenario file (format: {fmt!r})")
    return _build(Scenario, _migrate(dict(data)))


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def save_scenario(scenario: Scenario, path: Path | str) -> None:
    """Write ``scenario`` to ``path`` as JSON."""
    Path(path).write_text(
        json.dumps(scenario_to_dict(scenario), indent=2), encoding="utf-8"
    )


def load_scenario(path: Path | str) -> Scenario:
    """Read a scenario written by :func:`save_scenario` (or an older file)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioFormatError(f"not valid JSON: {exc}") from exc
    return scenario_from_dict(data)


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
#: What the ``format`` key of an exported result file says.
RESULTS_FORMAT = "algametrix.results"
RESULTS_VERSION = 1


def reference_product(results) -> str:
    """The product the headline cost and GWP are per."""
    mp = getattr(results, "main_product", None)
    if mp is not None:
        return mp.name
    return results.scenario.product_name or "dry biomass"


def functional_unit(results) -> str:
    """The functional unit, spelled the way it should appear on a figure."""
    return f"1 kg {reference_product(results)}"


def _finite(value):
    """JSON has no infinity. An unreachable payback is ``null``, not ``Infinity``."""
    if value is None:
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _method_summary() -> dict:
    """Name, version and scope of the life-cycle background in force."""
    from .lciamethod import load_method

    method = load_method()
    if method is None:
        return {}
    scope = method.scope
    return {
        "background": f"{method.name} v{method.version}",
        "standard": list(method.standard),
        "boundary": " ".join(str(scope.get("boundary", "")).split()),
        "functional_unit": " ".join(str(scope.get("functional_unit", "")).split()),
        "geography": (scope.get("geography") or {}).get("default", ""),
        "reference_period": (scope.get("reference_period") or {}).get("default", ""),
        "database": (scope.get("database") or {}).get("name", ""),
        "cutoff": method.cutoff.get("rule", ""),
        "excluded": [str(x.get("item", "")) for x in method.excluded],
        "indicative_factors": f"{len(method.indicative_factors())} of {len(method.factors)}",
    }


def results_to_dict(results) -> dict:
    """A complete, self-describing export of one run.

    Two things make this exhaustive rather than convenient. First, the file says
    what its numbers are *per*: a multiproduct case reports cost and GWP per kg
    of main product on screen, and an export that quietly switched to per kg of
    biomass had the reader publish a number the tool never showed them. Second,
    both bases are present — ``main_product_basis`` and ``biomass_basis`` — so
    the allocated result and the foreground inventory it came from can be read
    together instead of being confused for each other.

    ``headline`` is exactly what the KPI cards show, and nothing else.
    """
    from . import __version__

    scn, inv, tea, lca = results.scenario, results.inventory, results.tea, results.lca
    mp = getattr(results, "main_product", None)
    products = getattr(results, "products", []) or []

    biomass_basis = {
        "functional_unit": "1 kg dry biomass processed",
        "annual_dry_biomass_kg": inv.annual_biomass_kg,
        "production_cost_eur_per_kg": _finite(tea.production_cost_eur_per_kg),
        "net_production_cost_eur_per_kg": _finite(tea.net_production_cost_eur_per_kg),
        "gwp_kg_co2eq_per_kg": lca.gwp_kg_co2eq_per_kg,
        "gwp_gross_kg_co2eq_per_kg": lca.gwp_gross_kg_co2eq_per_kg,
        "biogenic_adjustment_kg_co2eq_per_kg": lca.biogenic_adjustment_kg_co2eq_per_kg,
        "avoided_treatment_kg_co2eq_per_kg": lca.avoided_treatment_kg_co2eq_per_kg,
        "ced_mj_per_kg": lca.ced_mj_per_kg,
        "water_m3_per_kg": lca.water_m3_per_kg,
        "land_m2a_per_kg": lca.land_m2a_per_kg,
        "gwp_breakdown": dict(lca.gwp_breakdown),
        "impacts": dict(lca.impacts),
        "carbon_accounting_mode": lca.carbon_accounting_mode,
        "waste_burden_convention": lca.waste_burden_convention,
        # Which categories this scenario leaves incomplete, and because of what.
        # An exported result travels without the software, so it has to carry
        # the qualification with it.
        "not_characterized": {k: list(v) for k, v in (lca.not_characterized or {}).items()},
        "method": _method_summary(),
    }

    main_product_basis = None
    if mp is not None:
        main_product_basis = {
            "functional_unit": f"1 kg {mp.name}",
            "reference_product": mp.name,
            "annual_kg": mp.annual_kg,
            "price_eur_per_kg": mp.price,
            "revenue_eur_per_year": mp.revenue,
            "allocation_share": mp.allocation_share,
            "production_cost_eur_per_kg": _finite(mp.production_cost_eur_per_kg),
            "gwp_kg_co2eq_per_kg": mp.gwp_kg_co2eq_per_kg,
            "ced_mj_per_kg": mp.ced_mj_per_kg,
        }

    headline_source = main_product_basis or biomass_basis
    headline = {
        # The KPI cards, verbatim. Anything that disagrees with these is a bug.
        "production_cost_eur_per_kg": headline_source["production_cost_eur_per_kg"],
        "gwp_kg_co2eq_per_kg": headline_source["gwp_kg_co2eq_per_kg"],
        "npv_eur": tea.npv,
        "roi": tea.roi,
        "payback_years": _finite(tea.payback_years),
        "irr": _finite(tea.irr),
        "annual_reference_product_kg": (mp.annual_kg if mp is not None
                                        else inv.annual_biomass_kg),
        "annual_dry_biomass_processed_kg": inv.annual_biomass_kg,
    }

    allocation = scn.extraction.allocation if products else "not applicable"
    if products and allocation == "none":
        allocation = "none (the main product carries the whole operating cost)"

    return {
        "format": RESULTS_FORMAT,
        "version": RESULTS_VERSION,
        "algametrix_version": __version__,
        "basis": {
            "functional_unit": functional_unit(results),
            "reference_product": reference_product(results),
            "allocation_method": allocation,
            "multiproduct": bool(products),
            "note": (
                "'headline' and 'main_product_basis' are per kg of the reference "
                "product. 'biomass_basis' and 'inventory_per_kg_biomass' are per kg "
                "of dry biomass processed — the foreground inventory the allocation "
                "was applied to, not a second result for the same thing."
            ),
        },
        "headline": headline,
        "main_product_basis": main_product_basis,
        "biomass_basis": biomass_basis,
        "products": [
            {
                "name": r.name,
                "annual_kg": r.annual_kg,
                "price_eur_per_kg": r.price,
                "revenue_eur_per_year": r.revenue,
                "allocation_share": r.allocation_share,
                "production_cost_eur_per_kg": _finite(r.production_cost_eur_per_kg),
                "gwp_kg_co2eq_per_kg": r.gwp_kg_co2eq_per_kg,
                "ced_mj_per_kg": r.ced_mj_per_kg,
                "is_main": r.is_main,
            }
            for r in products
        ],
        "tea_annual_eur": {
            "total_investment": tea.total_investment,
            "direct_fixed_capital": tea.dfc,
            "equipment_cost": tea.equipment_cost,
            "working_capital": tea.working_capital,
            "annual_operating_cost": tea.annual_opex,
            "raw_materials_cost": tea.raw_materials_cost,
            "utilities_cost": tea.utilities_cost,
            "depreciation": tea.depreciation,
            "revenues": tea.revenues,
            "gross_profit": tea.gross_profit,
            "net_profit": tea.net_profit,
            "avoided_treatment_credit": tea.avoided_treatment_credit,
            "opex_breakdown": dict(tea.opex_breakdown),
            "opex_categories": dict(tea.opex_categories),
            "capex_breakdown": dict(tea.capex_breakdown),
        },
        "inventory_per_kg_biomass": {
            k: v for k, v in _encode(inv).items() if not k.startswith("_")
        },
        "scenario": scenario_to_dict(scn),
    }


def save_results(results, path: Path | str) -> None:
    """Write a full result export to ``path`` as JSON."""
    Path(path).write_text(json.dumps(results_to_dict(results), indent=2), encoding="utf-8")
