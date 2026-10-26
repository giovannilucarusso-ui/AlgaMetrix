"""Where the inputs of each study reconstruction come from (SI S4.6).

For every reconstruction that is compared with a published value, this module
reports

* the origin of its cost coefficients, and the plant they refer to where the
  source states one;
* how many of the inputs the compared result depends on come from the source,
  how many are library defaults, how many were fitted and how many assumed;
* the inputs the compared result is most sensitive to.

An input is a numeric field of the scenario. The compared result depends on an
input when a 1% change in it moves the result, and the elasticity
d ln(result) / d ln(input) is estimated from that change. An input at zero, a
free CO2 supply for example, has no elasticity and is not counted.

Every input is put in one of four classes:

* source: the source's own figure, or one that follows from its figures by a
  stated conversion;
* library: a default shipped with AlgaMetrix;
* fitted: set so that the scenario reproduces a published result of the source,
  or taken from one, such as a published total operating cost. Part of the
  compared value is then on both sides of the comparison;
* assumed: set by the reconstruction with no location in the source recorded
  for it, including values taken from other publications or databases.

:data:`ORIGINS` records, for each builder, the class of the values it sets and
where in the source each was found. A value the builder takes unchanged from a
library entry is classed as library without being listed, unless that library
entry was itself calibrated on the same source; it is then classed as fitted.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from types import SimpleNamespace

from ..inputcheck import InadmissibleScenarioError
from ..library import Library, load_library
from ..models import Basis, CostScaling, Scenario
from ..scenario import minimum_selling_price, run_scenario
from . import reconstructions, studies, suite
from .endpoints import PRIMARY_ENDPOINT
from .reproduction import _ENGINE_ENDPOINT, _cost_of
from .schema import EVIDENCE_CLASSES

CLASSES = ("source", "library", "fitted", "assumed")

#: Relative change applied to one input at a time.
STEP = 0.01

#: Below this an elasticity is taken as zero.
ACTIVE = 1e-6

#: Bisection tolerance of the break-even price here. The solver's default, 1e-3
#: per kg, is coarser than the change a 1% step makes in the smaller elasticities.
PRICE_TOL = 1e-9

#: Fields the engine does not read: the recipe and the price a library system
#: offers to seed a new scenario.
_NOT_READ = {"system.materials", "system.utilities", "system.product_price"}


# --------------------------------------------------------------------------
# Inputs of a scenario
# --------------------------------------------------------------------------

def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def inputs(scn: Scenario) -> list[tuple[str, float]]:
    """Every numeric input of ``scn`` the engine reads, as (path, value).

    Text, switches and enumerations are left out, and so are the optional
    capacity-scaling laws, which no reconstruction uses. A disabled extraction
    or waste feed and the batch schedule of a continuous scenario are left out
    because the engine does not read them.
    """
    out: list[tuple[str, float]] = []

    def walk(obj, prefix: str) -> None:
        for f in fields(obj):
            path = prefix + f.name
            value = getattr(obj, f.name)
            if path in _NOT_READ or isinstance(value, CostScaling):
                continue
            if _numeric(value):
                out.append((path, float(value)))
            elif is_dataclass(value):
                if f.name in ("extraction", "waste_feed") and not value.enabled:
                    continue
                walk(value, path + ".")
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if is_dataclass(item):
                        walk(item, f"{path}[{i}].")

    walk(scn, "")
    if not scn.batch_mode:
        out = [(p, v) for p, v in out if not p.startswith("batch_")]
    return out


_PART = re.compile(r"(\w+)(?:\[(\d+)\])?")


def _steps(path: str):
    for part in path.split("."):
        name, index = _PART.fullmatch(part).groups()
        yield name
        if index is not None:
            yield int(index)


def _get(obj, steps):
    for s in steps:
        obj = obj[s] if isinstance(s, int) else getattr(obj, s)
    return obj


def value_at(scn: Scenario, path: str) -> float:
    return _get(scn, _steps(path))


def _set(scn: Scenario, path: str, value: float) -> None:
    steps = list(_steps(path))
    setattr(_get(scn, steps[:-1]), steps[-1], value)


def label(scn: Scenario, path: str) -> str:
    """The path, with the name of the material, utility or product it points into."""
    m = re.match(r"(materials|utilities|products)\[(\d+)\]", path)
    if m:
        return f"{path} ({getattr(scn, m.group(1))[int(m.group(2))].name})"
    return path


def elasticities(scn: Scenario, result) -> list[tuple[str, float, float]]:
    """(path, value, elasticity) for every input ``result`` depends on.

    The input is raised by :data:`STEP`; where that makes the scenario
    inadmissible, a recovery of 1.0 for example, it is lowered instead.
    """
    y0 = result(scn)
    out = []
    for path, value in inputs(scn):
        if value == 0.0:
            continue
        e = None
        for step in (STEP, -STEP):
            trial = deepcopy(scn)
            _set(trial, path, value * (1.0 + step))
            try:
                y = result(trial)
            except InadmissibleScenarioError:
                continue
            e = (y / y0 - 1.0) / step
            break
        if e is None:
            raise ValueError(f"{path}: neither a 1% rise nor a 1% fall is admissible")
        if abs(e) > ACTIVE:
            out.append((path, value, e))
    return sorted(out, key=lambda t: -abs(t[2]))


# --------------------------------------------------------------------------
# Where each builder's values come from
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Origin:
    """How one builder sets its inputs and where it found them.

    ``base`` names the library entry each component starts from (an empty string
    for the library's economics and LCIA factors). ``calibrated`` lists the
    components whose library entry was calibrated on this same source.
    ``entries`` maps an input path to its class and to where the value was found;
    ``*`` in a path stands for any field name or index. A listed path wins over
    the library, and the library over a pattern.
    """

    source: str                     # the publication the builder reconstructs, short
    plant: str = ""                 # the plant the source costs, as it states it
    base: dict[str, str] = field(default_factory=dict)
    calibrated: frozenset[str] = frozenset()
    entries: dict[str, tuple[str, str]] = field(default_factory=dict)


def _pattern(key: str) -> re.Pattern:
    return re.compile(re.escape(key).replace(r"\[\*\]", r"\[\d+\]")
                      .replace(r"\*", r"\w+") + "$")


def _library_object(lib: Library, component: str, entry: str):
    if component == "organism":
        return lib.organisms[entry]
    if component == "system":
        return lib.systems[entry]
    if component == "harvesting":
        return lib.harvesting[entry]
    if component == "drying":
        return lib.drying[entry]
    if component == "economics":
        return lib.economics
    if component == "lcia":
        return lib.lcia
    if component in ("materials", "utilities"):
        return SimpleNamespace(**{component: getattr(lib.systems[entry], component)})
    raise KeyError(component)


def _library_note(component: str, entry: str) -> str:
    if component in ("economics", "lcia"):
        return f"library {'LCIA factors' if component == 'lcia' else 'economics'}"
    if component in ("materials", "utilities"):
        return f"recipe of library system '{entry}'"
    return f"library {component} '{entry}'"


def classify(origin: Origin, path: str, scn: Scenario, lib: Library) -> tuple[str, str]:
    """The class of the input at ``path`` and where its value comes from."""
    if path in origin.entries:
        return origin.entries[path]
    component = path.split(".")[0].split("[")[0]
    entry = origin.base.get(component)
    if entry is not None:
        steps = list(_steps(path))
        base = _library_object(lib, component, entry)
        try:
            library_value = _get(base, steps if component in ("materials", "utilities")
                                 else steps[1:])
        except (IndexError, AttributeError):
            library_value = None
        if library_value is not None and math.isclose(
                library_value, value_at(scn, path), rel_tol=1e-12, abs_tol=0.0):
            note = _library_note(component, entry)
            if component in origin.calibrated:
                return "fitted", f"{note}, calibrated on {origin.source}"
            return "library", note
    matches = [k for k in origin.entries if "*" in k and _pattern(k).match(path)]
    if matches:
        return origin.entries[min(matches, key=lambda k: (k.count("*"), -len(k)))]
    raise KeyError(f"no origin recorded for {path}")


FERMENTER = "Stirred-tank fermenter (heterotrophic)"
SPIRULINA = "Arthrospira platensis (Spirulina)"
NAHCO3_POND = "Open raceway pond (Spirulina, NaHCO3)"
_LIBRARY_ECONOMICS = {"economics": "", "lcia": ""}

_TEMPLATE_FIT = "set with the other template values to reproduce the reference design"
_VR_OTHERS = ("not located: the source gives maintenance, supplies, contingencies and "
              "overheads together, 33.77% of operating cost (Fig. 6)")
_VR_SUPPLEMENT = ("given as published by the ported builder; the supplementary table "
                  "was not available to check it")


def _vr2022b(case: str, area: str, output: str, investment: str, labour: str,
             own_nutrients: bool) -> dict[str, tuple[str, str]]:
    """Entries shared by the three cases of Vazquez-Romero et al. (2022b)."""
    if own_nutrients:
        n_price = ("source", "urea, EUR 713.69/t at 46% N")
        p_price = ("source", "triple superphosphate, EUR 1,243.31/t at 19.6% P")
    else:
        why = (f"the {{}} price of the paper's case 4a; case {case} buys a nutrient "
               "solution whose use is not published")
        n_price = ("assumed", why.format("urea"))
        p_price = ("assumed", why.format("triple superphosphate"))
    lang = "Lang factors on the major equipment cost (supplementary tables)"
    return {
        "scale": ("source", area),
        "system.productivity": ("source", f"{output} t/yr over {area}"),
        "system.operating_days": ("source", "year-round operation"),
        "harvesting.recovery": ("source", "the published output is net of the harvest loss "
                                          "(section 2.2.5)"),
        "system.capex_per_unit": ("source", f"investment EUR {investment} M through the "
                                            "Lang factors, all on the cultivation line"),
        "economics.installation_factor": ("source", f"direct cost 2.20 x MEC; {lang}"),
        "economics.indirect_factor": ("source", f"indirect, contractor and contingency; {lang}"),
        "economics.harvest_capex_per_kgyr": ("source", "inside the major equipment cost"),
        "economics.drying_capex_per_kgyr": ("source", "inside the major equipment cost"),
        "economics.labor_cost_per_year": ("source", labour),
        "economics.maintenance_frac": ("source", "4% of the major equipment cost"),
        "economics.overhead_frac": ("source", "55% of labour and maintenance; applied here to "
                                              "materials, utilities and labour"),
        "economics.insurance_frac": ("source", "interest 8% of depreciation, property tax 1% "
                                               "and insurance 0.6%"),
        "economics.depreciation_years": ("source", "15 years"),
        "system.elec_kwh_per_kg": ("source", "electricity per kg (supplementary tables)"),
        "economics.electricity_price": ("source", "EUR 0.0781/kWh"),
        "economics.heat_price": ("source", "natural gas, EUR 0.0225/kWh"),
        "economics.co2_price": ("source", "EUR 1.16/kg"),
        "economics.water_price": ("source", "EUR 0.4728/m3"),
        "system.co2_utilization": ("assumed", "not given by the source"),
        "system.nutrient_uptake": ("assumed", "not given by the source"),
        "organism.nitrogen": ("source", "published protein / 6.25"),
        "economics.nitrogen_price": n_price,
        "economics.phosphorus_price": p_price,
        "other_opex_per_year": ("source", "land rent, EUR 1,184/ha a year"),
    }


ORIGINS: dict[str, Origin] = {
    "tredici2016": Origin(
        source="Tredici et al. (2016)",
        plant="1 ha, 36 t/yr of dry biomass",
        entries={
            "scale": ("source", "1 ha"),
            "system.productivity": ("source", "15 g/m2/d over the season (section 3.3.2)"),
            "system.operating_days": ("source", "240-day season (section 4.3.3)"),
            "harvesting.recovery": ("source", "the 36 t/yr is biomass collected as paste "
                                              "(section 3.3.2)"),
            "system.elec_kwh_per_kg": ("source", "EUR 37,526 a year at EUR 0.175/kWh "
                                                 "(section 4.3.3)"),
            "economics.electricity_price": ("source", "EUR 0.175/kWh (section 3.2.2)"),
            "system.capex_per_unit": ("source", "direct capital EUR 1,345,497 for 1 ha "
                                                "(Table 6)"),
            "economics.installation_factor": ("source", "installation is in the indirect "
                                                        "capital (Table 6)"),
            "economics.indirect_factor": ("source", "indirect capital EUR 216,280 over the "
                                                    "direct capital (Table 6)"),
            "economics.harvest_capex_per_kgyr": ("source", "the centrifuges are in the direct "
                                                           "capital (Table 6)"),
            "economics.drying_capex_per_kgyr": ("source", "no drying: the product is wet paste"),
            "economics.labor_cost_per_year": ("source", "six staff (Table 7)"),
            "economics.maintenance_frac": ("source", "5% of direct capital (section 3.2.4); "
                                                     "applied here to fixed capital, indirect "
                                                     "and land included"),
            "economics.overhead_frac": ("source", "overhead and administration, 10% each of "
                                                  "direct operating cost (section 3.2.4)"),
            "economics.depreciation_years": ("source", "25-year plant life (section 3.1); the "
                                                       "source depreciates each item over its "
                                                       "own life, and not the land"),
            "economics.insurance_frac": ("assumed", "the source's taxes and insurance, 1% once, "
                                                    "are in the indirect capital (Table 6); "
                                                    "charged again here, 1% a year"),
            "system.land_m2_per_unit": ("source", "land, EUR 100,000 for 1 ha (Table 6)"),
            "economics.land_price": ("source", "land, EUR 100,000 for 1 ha (Table 6)"),
            "system.nutrient_uptake": ("source", "100% uptake (section 3.2.3)"),
            "organism.nitrogen": ("source", "7% N (section 3.2.3)"),
            "organism.phosphorus": ("source", "0.7% P (section 3.2.3)"),
            "economics.nitrogen_price": ("source", "NaNO3, EUR 6,120 a year for 2,520 kg N "
                                                   "(Table 8)"),
            "economics.phosphorus_price": ("source", "NaH2PO4, EUR 1,500 a year for 252 kg P "
                                                     "(Table 8)"),
            "other_opex_per_year": ("source", "consumables (Table 10)"),
        },
    ),
    "vazquez2022": Origin(
        source="Vázquez-Romero et al. (2022a)",
        plant="1 ha, 29.48 t/yr of dry biomass",
        entries={
            "scale": ("source", "1 ha"),
            "system.productivity": ("source", "29.48 t/ha/yr (section 3.1)"),
            "system.operating_days": ("source", "300 operating days (section 2.4.1)"),
            "harvesting.recovery": ("source", "the 29.48 t/yr is harvested biomass (section 3.1)"),
            "system.capex_per_unit": ("source", "major equipment cost EUR 3,935,850 for 1 ha "
                                                "(Fig. 5)"),
            "economics.installation_factor": ("source", "the investment is carried by the "
                                                        "indirect factor"),
            "economics.indirect_factor": ("source", "investment EUR 12.15 M over the major "
                                                    "equipment cost (section 3.1)"),
            "economics.harvest_capex_per_kgyr": ("source", "the centrifuge is in the major "
                                                           "equipment cost (Fig. 5)"),
            "economics.drying_capex_per_kgyr": ("source", "no drying: the product is wet paste"),
            "economics.labor_cost_per_year": ("fitted", "38.79% of the published operating cost, "
                                                        "EUR 2,228,066 (Fig. 6)"),
            "other_opex_per_year": ("fitted", "utilities, consumables and wastewater, 9.49% of "
                                              "the published operating cost (Fig. 6)"),
            "economics.depreciation_years": ("source", "15-year amortisation (section 2.4.4)"),
            "economics.maintenance_frac": ("assumed", _VR_OTHERS),
            "economics.overhead_frac": ("assumed", _VR_OTHERS),
            "system.elec_kwh_per_kg": ("source", "141.59 kWh/kg (section 3.1)"),
            "economics.electricity_price": ("source", "EUR 0.093/kWh, Norway, 1 ha (Table 1)"),
            "system.nutrient_uptake": ("source", "100% assimilation (section 2.1)"),
            "organism.nitrogen": ("source", "formula C106H181O45N16P (section 2.1)"),
            "organism.phosphorus": ("source", "formula C106H181O45N16P (section 2.1)"),
            "economics.nitrogen_price": ("assumed", _VR_SUPPLEMENT),
            "economics.phosphorus_price": ("assumed", _VR_SUPPLEMENT),
        },
    ),
    "vazquez2022b_nas": Origin(
        source="Vázquez-Romero et al. (2022b)",
        plant="1 ha, 27.61 t/yr of dry biomass",
        base={"organism": "Nannochloropsis sp."},
        entries=_vr2022b("1b", "1 ha", "27.61", "8.23",
                         "8 operators and a plant manager", own_nutrients=False),
    ),
    "vazquez2022b_tiso_pht": Origin(
        source="Vázquez-Romero et al. (2022b)",
        plant="1 ha, 12.94 t/yr of dry biomass",
        entries={
            **_vr2022b("1a", "1 ha", "12.94", "7.72",
                       "8 operators and a plant manager", own_nutrients=False),
            "organism.nitrogen": ("source", "mean published protein of the two strains / 6.25"),
            "organism.carbon": ("assumed", "0.52, the library value for Nannochloropsis sp."),
            "organism.phosphorus": ("assumed", "not given by the source"),
        },
    ),
    "vazquez2022b_nas_10ha": Origin(
        source="Vázquez-Romero et al. (2022b)",
        plant="10 ha, 300.1 t/yr of dry biomass",
        base={"organism": "Nannochloropsis sp."},
        entries={
            **_vr2022b("4a", "10 ha", "300.1", "81.61", "EUR 341,996 a year at 10 ha",
                       own_nutrients=True),
            "system.elec_kwh_per_kg": ("source", "62.71 kWh/kg in all, less the 36.45 of "
                                                 "drying gas"),
            "harvesting.final_solids": ("source", "ultrafiltration to 5.21% dry weight"),
            "drying.thermal_mj_per_kg_water": ("source", "spray drying on natural gas, 36.45 "
                                                         "kWh per kg of product"),
            "drying.final_solids": ("source", "powder at 95% dry weight"),
        },
    ),
    "heterotrophic_powder": Origin(
        source="Russo et al. (2022)",
        plant="150 m3 of fermenter, 285 t/yr of dry powder",
        base={"organism": "Schizochytrium sp.", "system": FERMENTER,
              "harvesting": "Settling + centrifugation", "drying": "Spray drying",
              "materials": FERMENTER, "utilities": FERMENTER, **_LIBRARY_ECONOMICS},
        calibrated=frozenset({"system", "materials", "utilities"}),
        entries={
            "scale": ("source", "the SuperPro plant's 150 m3"),
            "system.capex_per_unit": ("fitted", "set to the SuperPro capital cost at 150 m3"),
            "economics.labor_cost_per_year": ("source", "the SuperPro labour cost"),
            "economics.substrate_price": ("source", "the SuperPro glucose price"),
            "system.water_m3_per_kg": ("source", "about 65 kg of process water per kg (SuperPro)"),
            "materials[0].amount_per_kg": ("source", "0.61 kg per kg (SuperPro)"),
        },
    ),
    "algal_oil": Origin(
        source="Carmichael and Petrides (2020)",
        plant="65,487 t/yr of algal oil",
        base={"organism": "Nannochloropsis sp.", "system": "Open raceway pond",
              "harvesting": "Membrane filtration", "drying": "No drying (wet paste)",
              **_LIBRARY_ECONOMICS},
        entries={
            "economics.labor_cost_per_year": ("source", "the report's labour cost"),
            "economics.electricity_price": ("source", "USD 0.10/kWh (the report)"),
            "economics.nitrogen_price": ("source", "the report's price"),
            "economics.water_price": ("source", "the report's price"),
            "economics.co2_price": ("source", "flue-gas CO2 at no cost (the report)"),
            "economics.land_price": ("source", "the report's price"),
            "economics.harvest_capex_per_kgyr": ("source", "the report's harvesting capital per "
                                                           "unit of capacity"),
            "economics.drying_capex_per_kgyr": ("source", "no drying"),
            "products[1].price": ("source", "USD 181/t (the report)"),
            "credits_per_year": ("source", "anaerobic-digestion energy recovery, about USD 16 M "
                                           "a year (the report)"),
            "scale": ("fitted", "sized to the report's oil output: 67,671 against 65,487 t/yr"),
            "system.*": ("fitted", _TEMPLATE_FIT),
            "economics.*": ("fitted", _TEMPLATE_FIT),
            "extraction.*": ("fitted", _TEMPLATE_FIT),
            "products[*].*": ("fitted", _TEMPLATE_FIT),
            "materials[*].*": ("fitted", _TEMPLATE_FIT),
        },
    ),
    "omega3": Origin(
        source="Flevaris et al. (2021)",
        plant="6 fermenters of 300 m3, 2,963 t/yr of omega-3 oil",
        base={"organism": "Schizochytrium sp.", "system": FERMENTER,
              "harvesting": "Centrifugation only", "drying": "No drying (wet paste)",
              **_LIBRARY_ECONOMICS},
        entries={
            "economics.labor_cost_per_year": ("source", "the report's labour cost"),
            "products[0].price": ("source", "the report's oil price"),
            "products[1].price": ("source", "algae meal, USD 150/t (the report)"),
            "batch_cycle_time_h": ("source", "about one day per batch (the report)"),
            "scale": ("fitted", "2,000 m3 against the report's 1,800 m3"),
            "batch_size_kg": ("fitted", _TEMPLATE_FIT),
            "system.*": ("fitted", _TEMPLATE_FIT),
            "economics.*": ("fitted", _TEMPLATE_FIT),
            "extraction.*": ("fitted", _TEMPLATE_FIT),
            "products[*].*": ("fitted", _TEMPLATE_FIT),
        },
    ),
    "spirulina_padi": Origin(
        source="Padi et al. (2023)",
        plant="about 1 t of biomass a day, some 330 t/yr",
        base={"organism": SPIRULINA, "system": NAHCO3_POND,
              "harvesting": "Vibrating screen filter", "drying": "Spray drying",
              **_LIBRARY_ECONOMICS},
        calibrated=frozenset({"system"}),
        entries={
            "scale": ("source", "the footprint of about 1 t a day, 11.6 ha"),
            "product_price": ("source", "market price of the dried product, EUR 65/kg"),
            "system.productivity": ("source", "8.6 g/m2/d achieved"),
            "economics.depreciation_years": ("source", "20-year straight-line depreciation"),
            "economics.maintenance_frac": ("source", "1% of fixed capital"),
            "economics.insurance_frac": ("source", "0.6% of fixed capital"),
            "economics.installation_factor": ("source", "civil-works ponds"),
            "economics.tax_rate": ("source", "Irish corporate tax, 26.5%"),
            "economics.nitrogen_price": ("source", "via KNO3, EUR 0.67/kg at 13.9% N"),
            "economics.phosphorus_price": ("source", "via K4P2O7, EUR 1.50/kg at 18.8% P"),
            "economics.labor_cost_per_year": ("source", "the paper's labour cost"),
        },
    ),
    "iceland_spirulina": Origin(
        source="Tzachor et al. (2022)",
        base={"organism": SPIRULINA, "system": "Flat-panel photobioreactor",
              "harvesting": "Vibrating screen filter", "drying": "No drying (wet paste)",
              **_LIBRARY_ECONOMICS},
        entries={
            "system.elec_kwh_per_kg": ("source", "54.48 kWh per kg wet at 39% solids, as "
                                                 "corrected: 139.7 per kg dry, entered per kg "
                                                 "grown"),
            "system.cultivation_heat_mj_per_kg": ("source", "geothermal waste heat"),
            "harvesting.elec_kwh_per_kg": ("source", "inside the total electricity"),
            "lcia.elec_gwp": ("source", "geothermal grid, 0.0084 kg CO2-eq/kWh"),
            "lcia.co2_supply_gwp": ("source", "CO2 is a geothermal by-product"),
            "lcia.heat_gwp": ("source", "geothermal waste heat"),
            "lcia.nitrogen_gwp": ("assumed", "placeholder 0.05; the source gives nutrients and "
                                             "lye as 0.082 kg CO2-eq per kg dry (Table 4)"),
            "lcia.phosphorus_gwp": ("assumed", "placeholder 0.05, as for nitrogen"),
        },
    ),
    "spiralg2019": Origin(
        source="Braud et al. (2025)",
        base={"organism": SPIRULINA, "system": NAHCO3_POND,
              "harvesting": "Vibrating screen filter", "drying": "No drying (wet paste)",
              **_LIBRARY_ECONOMICS},
        entries={
            "system.elec_kwh_per_kg": ("source", "S1.A1-A5 of the inventory, 428.22 kWh for "
                                                 "28.78 kg, entered per kg grown"),
            "system.co2_utilization": ("source", "set so that 4.206 kg NaHCO3 is bought per kg; "
                                                 "the inventory has 4.208"),
            "system.cultivation_heat_mj_per_kg": ("source", "no heating in the inventory"),
            "harvesting.elec_kwh_per_kg": ("source", "inside the S1 electricity"),
            "lcia.elec_gwp": ("source", "0.43 kg CO2-eq/kWh (section 3.5)"),
            "lcia.heat_gwp": ("source", "no heat in the inventory"),
            "lcia.bicarbonate_gwp": ("assumed", "AGRIBALYSE 3.2, item 11507; the source names its "
                                                "dataset but not the factor"),
            "lcia.nitrogen_gwp": ("assumed", "9.6 per kg N; the source's potassium nitrate "
                                             "implies about 18"),
        },
    ),
    "mckuin_schizo": Origin(
        source="McKuin et al. (2022)",
        base={"organism": "Schizochytrium sp.", "system": FERMENTER, **_LIBRARY_ECONOMICS},
        entries={
            "scale": ("source", "155.2 m3 (Table S1)"),
            "system.productivity": ("source", "141.4 g/L every 85.8 h (Table S1)"),
            "system.operating_days": ("source", "330 days (Table S1)"),
            "system.biomass_conc": ("source", "141.4 g/L (Table S1)"),
            "system.elec_kwh_per_kg": ("source", "pump, sparger and impeller (Table S23)"),
            "system.cultivation_heat_mj_per_kg": ("source", "sterilization and thermal control "
                                                            "(Table S23)"),
            "system.water_m3_per_kg": ("source", "medium and salinity dilution "
                                                 "(Tables S23, S24)"),
            "system.substrate_yield": ("source", "sucrose (Table S23)"),
            "system.substrate_carbon_fraction": ("source", "sucrose, C12H22O11"),
            "harvesting.recovery": ("source", "decanter centrifuge (Table S4)"),
            "harvesting.elec_kwh_per_kg": ("source", "Table S24"),
            "harvesting.final_solids": ("assumed", "20% solids out of the decanter; no "
                                                   "table is cited for it"),
            "drying.thermal_mj_per_kg_water": ("source", "3.65 MJ per litre of water left after "
                                                         "the centrifuge (Table S4)"),
            "drying.final_solids": ("source", "dried to 95% (Table S4)"),
            "materials[*].amount_per_kg": ("source", "medium (Table S23)"),
            "materials[*].gwp": ("source", "Table S36, Brazil"),
            "utilities[*].amount_per_kg": ("source", "water supply and wastewater "
                                                     "(Tables S23, S24)"),
            "utilities[*].gwp": ("source", "Table S36, Brazil"),
            "lcia.elec_gwp": ("source", "Table S36, given per MJ"),
            "lcia.heat_gwp": ("source", "bagasse cogeneration (Table S36)"),
            "lcia.substrate_gwp": ("source", "cane sucrose (Table S36)"),
            "economics.labor_cost_per_year": ("assumed", "carried over from the heterotrophic "
                                                         "template"),
            "economics.substrate_price": ("source", "the source's sucrose price"),
        },
    ),
}


# --------------------------------------------------------------------------
# Compared results
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Input:
    """One input a compared result depends on."""

    path: str
    label: str
    value: float
    elasticity: float
    origin: str                   # one of CLASSES
    note: str


@dataclass(frozen=True)
class Comparison:
    """One compared result and the inputs it depends on, most influential first."""

    study_id: str
    study: str                    # citation and scenario of the compared record
    builder: str
    reconstructs: str             # the publication the inputs are classed against
    result: str                   # the engine quantity compared
    evidence_class: str
    inputs: tuple[Input, ...]

    def count(self, origin: str) -> int:
        return sum(i.origin == origin for i in self.inputs)

    def drivers(self, n: int = 5) -> tuple[Input, ...]:
        return self.inputs[:n]


def _break_even(scn: Scenario) -> float:
    return minimum_selling_price(scn, price_tol=PRICE_TOL)


def _gross_gwp(scn: Scenario) -> float:
    return run_scenario(scn).lca.gwp_gross_kg_co2eq_per_kg


def _net_gwp(scn: Scenario) -> float:
    return run_scenario(scn).lca.gwp_kg_co2eq_per_kg


def compared_results(rec) -> list[tuple[str, object]]:
    """The engine quantities :mod:`reproduction` compares with ``rec``, named."""
    out = []
    endpoint = rec.economic_endpoint_type
    if rec.reported_value is not None and endpoint in _ENGINE_ENDPOINT:
        if endpoint == PRIMARY_ENDPOINT:
            out.append(("production cost", _cost_of))
        else:
            out.append(("break-even price", _break_even))
    if rec.has_published_gwp:
        if rec.reported_gwp_gross is not None:
            out.append(("gross GWP", _gross_gwp))
        else:
            out.append(("net GWP", _net_gwp))
    return out


def comparisons(lib: Library | None = None, dataset=None) -> list[Comparison]:
    """Every comparison of a reconstruction with a published value, by evidence class."""
    lib = lib or load_library()
    dataset = dataset if dataset is not None else studies.default_dataset()
    rank = {c: i for i, c in enumerate(EVIDENCE_CLASSES)}
    records = sorted((r for r in dataset if r.is_executable),
                     key=lambda r: (rank.get(r.evidence_class, len(rank)), r.short_citation,
                                    r.study_id))
    out = []
    for rec in records:
        builder = rec.reconstruction_builder
        origin = ORIGINS[builder]
        for name, result in compared_results(rec):
            scn = reconstructions.build(builder, lib)
            found = []
            for path, value, e in elasticities(scn, result):
                cls, note = classify(origin, path, scn, lib)
                found.append(Input(path, label(scn, path), value, e, cls, note))
            out.append(Comparison(
                study_id=rec.study_id,
                study=f"{rec.short_citation}, {rec.scenario_label}",
                builder=builder, reconstructs=origin.source, result=name,
                evidence_class=rec.evidence_class or "none",
                inputs=tuple(found)))
    return out


# --------------------------------------------------------------------------
# Cost coefficients
# --------------------------------------------------------------------------

#: The cost coefficients reported for every reconstruction, in print order.
COEFFICIENTS = (
    ("cultivation equipment", "system.capex_per_unit"),
    ("harvesting equipment", "economics.harvest_capex_per_kgyr"),
    ("drying equipment", "economics.drying_capex_per_kgyr"),
    ("extraction equipment", "extraction.capex_per_kgyr"),
    ("installation factor", "economics.installation_factor"),
    ("indirect factor", "economics.indirect_factor"),
    ("labour", "economics.labor_cost_per_year"),
)


@dataclass(frozen=True)
class Coefficient:
    item: str
    value: float
    unit: str
    origin: str
    note: str


@dataclass(frozen=True)
class CostCoefficients:
    """The cost coefficients of one reconstruction whose cost is compared."""

    builder: str
    source: str
    basis: str                    # currency and price year of its price set
    plant: str                    # the plant the source costs
    run_at: str                   # the scenario's capacity and output
    coefficients: tuple[Coefficient, ...]


def _unit(scn: Scenario, path: str) -> str:
    if path == "system.capex_per_unit":
        return "per m2" if scn.system.basis == Basis.AREA else "per m3"
    if path.endswith("_per_kgyr"):
        return "per kg/yr"
    if path == "economics.labor_cost_per_year":
        return "per yr"
    return ""


def _tonnes(kg: float) -> str:
    t = kg / 1000.0
    return f"{t:,.0f}" if t >= 1000 else f"{t:.1f}"


def _run_at(scn: Scenario) -> str:
    res = run_scenario(scn)
    unit = "m2" if scn.system.basis == Basis.AREA else "m3"
    text = (f"{scn.scale:,.0f} {unit}, "
            f"{_tonnes(res.inventory.annual_biomass_kg)} t/yr of dry biomass")
    if res.main_product is not None:
        text += f", {_tonnes(res.main_product.annual_kg)} t/yr of {res.main_product.name}"
    return text


def cost_builders(dataset=None) -> list[str]:
    """Builders whose cost is compared with a published value."""
    dataset = dataset if dataset is not None else studies.default_dataset()
    return sorted({r.reconstruction_builder for r in dataset if r.is_executable
                   and r.reported_value is not None
                   and r.economic_endpoint_type in _ENGINE_ENDPOINT})


def gwp_only(dataset=None) -> list[str]:
    """Builders compared on GWP alone, whose cost coefficients enter no comparison."""
    dataset = dataset if dataset is not None else studies.default_dataset()
    compared = {r.reconstruction_builder for r in dataset if r.is_executable}
    return sorted(compared - set(cost_builders(dataset)))


def cost_coefficients(lib: Library | None = None, dataset=None) -> list[CostCoefficients]:
    lib = lib or load_library()
    dataset = dataset if dataset is not None else studies.default_dataset()
    out = []
    for builder in cost_builders(dataset):
        origin = ORIGINS[builder]
        scn = reconstructions.build(builder, lib)
        rows = []
        for item, path in COEFFICIENTS:
            if path.startswith("extraction.") and not scn.extraction.enabled:
                continue
            cls, note = classify(origin, path, scn, lib)
            rows.append(Coefficient(item, value_at(scn, path), _unit(scn, path), cls, note))
        out.append(CostCoefficients(
            builder=builder,
            source=suite.study_label(builder, dataset) or origin.source,
            basis=reconstructions.price_basis(builder).label,
            plant=origin.plant, run_at=_run_at(scn), coefficients=tuple(rows)))
    return out
