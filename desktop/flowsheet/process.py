"""Live link between the Process Designer and the engine.

The canvas draws blocks; this module says what each generated block stands for
in the :class:`~algametrix.models.Scenario`, which scenario fields it exposes as
process variables, and how the engine's results break down over the blocks
(power, heat duty, annual cost, capital, GWP). It is plain Python on top of
:func:`algametrix.scenario.run_scenario`, so it is tested without Qt.

The per-block figures are attributions of the engine's own totals, not a second
calculation: block annual costs plus the plant-wide items add up to the TEA's
annual operating cost, and block GWP adds up to the LCA's net GWP. Where the
engine has one number for two blocks (a two-stage dewatering train, for
instance) both blocks show the same figure and the section total counts it once.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field

from algametrix.inputcheck import InadmissibleScenarioError, InputIssue, check_inputs
from algametrix.models import Basis, CarbonSource, Scenario, TrophicMode
from algametrix.scenario import Results, run_scenario

from . import builder as B

# --------------------------------------------------------------------------- #
# Sections (plant areas)
# --------------------------------------------------------------------------- #
PLANT = "plant"   # not a block: the plant-wide variables and costs


@dataclass(frozen=True)
class Section:
    code: str
    label: str
    roles: tuple[str, ...]
    color: str


SECTIONS: tuple[Section, ...] = (
    Section("100", "Feed preparation",
            (B.FEED_WATER, B.FEED_NUTRIENTS, B.FEED_CHEMICALS, B.FEED_INOCULUM,
             B.FEED_CARBON, B.FEED_SUBSTRATE, B.FEED_WASTE, B.MEDIA_PREP), "#607d8b"),
    Section("200", "Cultivation", (B.CULTIVATION,), "#2e7d32"),
    Section("300", "Harvesting", (B.HARVEST, B.EFFLUENT), "#1565c0"),
    Section("400", "Drying", (B.DRYING, B.VAPOUR), "#e65100"),
    Section("500", "Downstream processing",
            (B.DISRUPTION, B.EXTRACTION, B.FEED_SOLVENT, B.SPENT), "#6a1b9a"),
)

ROLE_LABELS: dict[str, str] = {
    B.CULTIVATION: "Cultivation",
    B.HARVEST: "Harvesting",
    B.DRYING: "Drying",
    B.DISRUPTION: "Cell disruption",
    B.EXTRACTION: "Extraction",
    B.MEDIA_PREP: "Media preparation",
    B.FEED_WATER: "Process water",
    B.FEED_NUTRIENTS: "Nutrients (N, P)",
    B.FEED_CHEMICALS: "Media chemicals",
    B.FEED_INOCULUM: "Inoculum",
    B.FEED_CARBON: "Carbon source",
    B.FEED_SUBSTRATE: "Organic substrate",
    B.FEED_WASTE: "Waste-derived feed",
    B.FEED_SOLVENT: "Solvent make-up",
    B.PRODUCT: "Product",
    B.EFFLUENT: "Effluent",
    B.VAPOUR: "Evaporated water",
    B.SPENT: "Spent biomass",
    PLANT: "Plant-wide (labour, overhead, other)",
}


def role_base(role: str) -> str:
    """``"harvest:2"`` -> ``"harvest"``: later stages share the first one's link."""
    return role.split(":", 1)[0] if role else ""


def section_of(role: str) -> Section | None:
    base = role_base(role)
    for sec in SECTIONS:
        if base in sec.roles:
            return sec
    return None


# --------------------------------------------------------------------------- #
# Process variables
# --------------------------------------------------------------------------- #
# Two paths do not name a single field: the selling price lives on the main
# product when the case has a product list and on the scenario otherwise, and
# the main product's recovery only exists with a product list.
SELLING_PRICE = "@selling_price"
MAIN_RECOVERY = "@main_recovery"

_INDEXED = re.compile(r"^(\w+)\[(\d+)\]$")


@dataclass(frozen=True)
class Variable:
    """One scenario field exposed as a knob on a block.

    ``path`` is the dotted path into the scenario, spelled the way
    :mod:`algametrix.inputcheck` names fields, so an input issue can be traced
    back to the block that owns it. Values are stored in engine units and shown
    times ``factor`` (fractions are shown in percent).
    """

    path: str
    label: str
    unit: str = ""
    lo: float = 0.0
    hi: float = 1.0
    decimals: int = 2
    factor: float = 1.0
    group: str = "Operation"
    log: bool = False
    limit_lo: float | None = None   # physical bounds in engine units
    limit_hi: float | None = None
    help: str = ""

    @property
    def key(self) -> str:
        return self.path

    def span(self, value: float) -> tuple[float, float]:
        """Slider range in engine units, widened to include ``value``."""
        lo, hi = min(self.lo, value), max(self.hi, value)
        if self.log:
            lo = max(lo, 1e-9)
        return lo, hi

    def clip(self, value: float) -> float:
        if self.limit_lo is not None:
            value = max(value, self.limit_lo)
        if self.limit_hi is not None:
            value = min(value, self.limit_hi)
        return value


GROUPS = ("Operation", "Performance", "Composition", "Energy", "Economics", "Environment")


def _main(scn: Scenario):
    if not scn.products:
        return None
    return next((p for p in scn.products if p.is_main), scn.products[0])


def _walk(scn: Scenario, path: str):
    """Return ``(parent, attribute)`` for a dotted path such as ``materials[0].price``."""
    parts = path.split(".")
    obj = scn
    for part in parts[:-1]:
        m = _INDEXED.match(part)
        obj = getattr(obj, m.group(1))[int(m.group(2))] if m else getattr(obj, part)
    return obj, parts[-1]


def get_value(scn: Scenario, path: str) -> float:
    if path == SELLING_PRICE:
        main = _main(scn)
        return float(main.price if main is not None else scn.product_price)
    if path == MAIN_RECOVERY:
        main = _main(scn)
        return float(main.recovery) if main is not None else 1.0
    parent, attr = _walk(scn, path)
    return float(getattr(parent, attr))


def set_value(scn: Scenario, path: str, value: float) -> None:
    value = float(value)
    if path == SELLING_PRICE:
        main = _main(scn)
        if main is not None:
            main.price = value
        scn.product_price = value
        return
    if path == MAIN_RECOVERY:
        main = _main(scn)
        if main is not None:
            main.recovery = value
        return
    parent, attr = _walk(scn, path)
    setattr(parent, attr, value)


def variables_for(role: str, scn: Scenario) -> list[Variable]:
    """The knobs a block of ``role`` exposes for the scenario as it stands."""
    base = role_base(role)
    sys = scn.system
    area = sys.basis == Basis.AREA
    photo = sys.mode == TrophicMode.PHOTOTROPHIC
    cap_unit = "m²" if area else "m³"
    out: list[Variable] = []

    scale = Variable("scale", "Cultivation area" if area else "Culture volume", cap_unit,
                     1e3 if area else 1.0, 1e8 if area else 1e5, 0, group="Operation",
                     log=True, limit_lo=1e-6,
                     help="Installed pond/reactor area or volume. Sizes the whole plant.")
    days = Variable("system.operating_days", "Operating days", "d/yr", 100, 366, 0,
                    group="Operation", limit_lo=1, limit_hi=366)
    uptake = Variable("system.nutrient_uptake", "Nutrient uptake", "%", 0.3, 1.0, 1, 100.0,
                      "Performance", limit_lo=1e-3, limit_hi=1.0,
                      help="Share of the N and P supplied that ends up in the biomass.")
    carbon_util = Variable("system.co2_utilization", "Carbon utilisation", "%", 0.3, 1.0, 1,
                           100.0, "Performance", limit_lo=0.05, limit_hi=1.0,
                           help="Share of the supplied inorganic carbon fixed by the culture.")
    substrate_yield = Variable("system.substrate_yield", "Substrate yield", "kg/kg", 0.1, 0.6, 3,
                               group="Performance", limit_lo=1e-3, limit_hi=1.0,
                               help="kg dry biomass per kg of organic substrate.")
    water_use = Variable("system.water_m3_per_kg", "Net water use", "m³/kg", 0.0, 5.0, 3,
                         group="Performance", limit_lo=0.0,
                         help="Make-up water per kg of gross biomass (evaporation, bleed).")
    solvent_rec = Variable("extraction.solvent_recovery", "Solvent recovery", "%", 0.8, 1.0, 2,
                           100.0, "Performance", limit_lo=0.0, limit_hi=1.0,
                           help="Share of the solvent contacted that is recovered and recycled.")

    if base == B.CULTIVATION:
        out.append(scale)
        if scn.batch_mode and scn.batch_cycle_time_h > 0:
            out += [
                Variable("batch_size_kg", "Batch size", "kg", 10, 1e7, 0, group="Operation",
                         log=True, limit_lo=1e-6, help="Gross dry biomass harvested per batch."),
                Variable("batch_cycle_time_h", "Batch cycle time", "h", 4, 400, 1,
                         group="Operation", limit_lo=1e-3,
                         help="Total cycle time including turnaround."),
            ]
        else:
            out.append(Variable("system.productivity", "Productivity",
                                "g/m²/d" if area else "g/L/d",
                                1.0 if area else 0.05, 60.0 if area else 20.0, 2,
                                group="Operation", limit_lo=1e-6,
                                help="Biomass produced per unit area or volume and day."))
        out += [
            days,
            Variable("system.biomass_conc", "Harvest concentration", "g/L", 0.1, 200.0, 2,
                     group="Operation", log=True, limit_lo=1e-3,
                     help="Culture density at harvest. Sets the broth flow to dewatering; "
                          "the engine's harvesting energy is per kg of biomass, so on its "
                          "own it does not move cost or GWP."),
        ]
        out.append(carbon_util if photo else substrate_yield)
        out += [uptake, water_use,
                Variable("system.elec_kwh_per_kg", "Mixing & aeration electricity", "kWh/kg",
                         0.0, 15.0, 2, group="Energy", limit_lo=0.0),
                Variable("system.cultivation_heat_mj_per_kg", "Culture heating", "MJ/kg",
                         0.0, 100.0, 1, group="Energy", limit_lo=0.0),
                Variable("system.capex_per_unit", "Cultivation CAPEX", f"€/{cap_unit}",
                         1.0, 2000.0, 1, group="Economics", log=True, limit_lo=0.0),
                Variable("system.land_m2_per_unit", "Land per unit", f"m²/{cap_unit}",
                         0.0, 3.0, 2, group="Economics", limit_lo=0.0)]
    elif base == B.HARVEST:
        out += [
            Variable("harvesting.recovery", "Biomass recovery", "%", 0.5, 1.0, 1, 100.0,
                     "Performance", limit_lo=1e-3, limit_hi=1.0,
                     help="Share of the cultivated biomass that reaches the product."),
            Variable("harvesting.final_solids", "Concentrate solids", "% DS", 0.02, 0.40, 1,
                     100.0, "Performance", limit_lo=1e-3, limit_hi=1.0,
                     help="Dry-solids content of the concentrate sent on."),
            Variable("harvesting.elec_kwh_per_kg", "Specific electricity", "kWh/kg", 0.0, 6.0, 2,
                     group="Energy", limit_lo=0.0),
            Variable("economics.harvest_capex_per_kgyr", "Equipment cost", "€ per kg/yr",
                     0.0, 10.0, 2, group="Economics", limit_lo=0.0),
        ]
    elif base == B.DRYING and scn.drying.enabled:
        out += [
            Variable("drying.final_solids", "Product solids", "% DS", 0.80, 0.99, 1, 100.0,
                     "Performance", limit_lo=1e-3, limit_hi=1.0),
            Variable("drying.thermal_mj_per_kg_water", "Specific heat", "MJ/kg H₂O",
                     2.4, 6.0, 2, group="Energy", limit_lo=0.0,
                     help="Heat per kg of water evaporated (latent heat is about 2.4)."),
            Variable("drying.elec_kwh_per_kg", "Electricity", "kWh/kg", 0.0, 2.0, 2,
                     group="Energy", limit_lo=0.0),
            Variable("economics.drying_capex_per_kgyr", "Equipment cost", "€ per kg/yr",
                     0.0, 10.0, 2, group="Economics", limit_lo=0.0),
        ]
    elif base == B.DISRUPTION and scn.extraction.enabled:
        out.append(Variable("extraction.disruption_elec_kwh_per_kg", "Disruption electricity",
                            "kWh/kg", 0.0, 5.0, 2, group="Energy", limit_lo=0.0))
    elif base == B.EXTRACTION and scn.extraction.enabled:
        out += [Variable("extraction.solvent_kg_per_kg", "Solvent-to-biomass ratio", "kg/kg",
                         0.0, 60.0, 1, group="Operation", limit_lo=0.0),
                solvent_rec]
        if _main(scn) is not None:
            out.append(Variable(MAIN_RECOVERY, "Main product recovery", "%", 0.3, 1.0, 1, 100.0,
                                "Performance", limit_lo=1e-3, limit_hi=1.0,
                                help="Share of the target fraction recovered into the main "
                                     "product."))
        out += [Variable("extraction.elec_kwh_per_kg", "Electricity", "kWh/kg", 0.0, 10.0, 2,
                         group="Energy", limit_lo=0.0),
                Variable("extraction.heat_mj_per_kg", "Heat (solvent recovery)", "MJ/kg",
                         0.0, 10.0, 2, group="Energy", limit_lo=0.0),
                Variable("extraction.capex_per_kgyr", "Equipment cost", "€ per kg/yr",
                         0.0, 30.0, 2, group="Economics", limit_lo=0.0)]
    elif base == B.FEED_SOLVENT and scn.extraction.enabled:
        out += [solvent_rec,
                Variable("extraction.solvent_price", "Solvent price", "€/kg", 0.0, 10.0, 2,
                         group="Economics"),
                Variable("extraction.solvent_gwp", "Solvent GWP", "kg CO₂-eq/kg", 0.0, 5.0, 2,
                         group="Environment", limit_lo=0.0)]
    elif base == B.FEED_WATER:
        out += [water_use,
                Variable("economics.water_price", "Water price", "€/m³", 0.0, 5.0, 2,
                         group="Economics")]
    elif base == B.FEED_NUTRIENTS:
        out += [
            Variable("organism.nitrogen", "Biomass nitrogen", "% DW", 0.01, 0.14, 2, 100.0,
                     "Composition", limit_lo=0.0, limit_hi=1.0),
            Variable("organism.phosphorus", "Biomass phosphorus", "% DW", 0.002, 0.03, 2, 100.0,
                     "Composition", limit_lo=0.0, limit_hi=1.0),
            uptake,
            Variable("economics.nitrogen_price", "Nitrogen price", "€/kg N", 0.0, 5.0, 2,
                     group="Economics"),
            Variable("economics.phosphorus_price", "Phosphorus price", "€/kg P", 0.0, 10.0, 2,
                     group="Economics"),
            Variable("lcia.nitrogen_gwp", "N fertiliser GWP", "kg CO₂-eq/kg N", 0.0, 15.0, 2,
                     group="Environment", limit_lo=0.0),
            Variable("lcia.phosphorus_gwp", "P fertiliser GWP", "kg CO₂-eq/kg P", 0.0, 10.0, 2,
                     group="Environment", limit_lo=0.0),
        ]
    elif base == B.FEED_CARBON and photo:
        out.append(Variable("organism.carbon", "Biomass carbon", "% DW", 0.35, 0.60, 1, 100.0,
                            "Composition", limit_lo=0.0, limit_hi=1.0))
        out.append(carbon_util)
        if sys.carbon_source == CarbonSource.BICARBONATE:
            out += [Variable("economics.bicarbonate_price", "NaHCO₃ price", "€/kg", 0.0, 1.0, 3,
                             group="Economics"),
                    Variable("lcia.bicarbonate_gwp", "NaHCO₃ GWP", "kg CO₂-eq/kg", 0.0, 3.0, 2,
                             group="Environment", limit_lo=0.0)]
        else:
            out += [Variable("economics.co2_price", "CO₂ price", "€/kg", -0.1, 0.5, 3,
                             group="Economics",
                             help="May be zero or negative for waste or credited CO₂."),
                    Variable("lcia.co2_supply_gwp", "CO₂ supply GWP", "kg CO₂-eq/kg", 0.0, 1.0, 3,
                             group="Environment", limit_lo=0.0)]
    elif base == B.FEED_SUBSTRATE and not photo:
        out += [substrate_yield,
                Variable("economics.substrate_price", "Substrate price", "€/kg", 0.0, 2.0, 3,
                         group="Economics"),
                Variable("lcia.substrate_gwp", "Substrate GWP", "kg CO₂-eq/kg", 0.0, 3.0, 2,
                         group="Environment", limit_lo=0.0)]
    elif base == B.FEED_CHEMICALS:
        for i, m in enumerate(scn.materials[:8]):
            out += [Variable(f"materials[{i}].amount_per_kg", f"{m.name} dose", "kg/kg",
                             0.0, max(1.0, m.amount_per_kg * 3.0), 4, group="Operation",
                             limit_lo=0.0),
                    Variable(f"materials[{i}].price", f"{m.name} price", "€/kg",
                             0.0, max(10.0, m.price * 3.0), 3, group="Economics")]
    elif base == B.FEED_WASTE and scn.waste_feed.enabled:
        unit = scn.waste_feed.unit
        out += [
            Variable("waste_feed.coverage", "Coverage of demand", "%", 0.0, 1.0, 1, 100.0,
                     "Operation", limit_lo=0.0, limit_hi=1.0,
                     help=f"Share of the {scn.waste_feed.dosed_on} demand the stream covers."),
            Variable("waste_feed.price_per_unit", "Price (negative = gate fee)", f"€/{unit}",
                     -2.0, 2.0, 3, group="Economics"),
        ]
    elif base == B.PRODUCT:
        out.append(Variable(SELLING_PRICE, "Selling price", "€/kg", 0.0, 50.0, 2,
                            group="Economics", limit_lo=0.0,
                            help="Price of the main product (whole biomass if the case has "
                                 "no product list)."))
    elif base == PLANT:
        out += [
            scale, days,
            Variable("economics.electricity_price", "Electricity price", "€/kWh", 0.02, 0.40, 3,
                     group="Economics", limit_lo=0.0),
            Variable("economics.heat_price", "Heat price", "€/MJ", 0.0, 0.10, 4,
                     group="Economics", limit_lo=0.0),
            Variable("economics.labor_cost_per_year", "Labour", "€/yr", 0.0, 3e6, 0,
                     group="Economics", limit_lo=0.0),
            Variable("economics.installation_factor", "Installation factor", "×", 1.0, 5.0, 2,
                     group="Economics", limit_lo=0.0),
            Variable("economics.indirect_factor", "Indirect costs", "% of installed", 0.0, 1.0, 1,
                     100.0, "Economics", limit_lo=0.0),
            Variable("economics.maintenance_frac", "Maintenance", "% DFC/yr", 0.0, 0.10, 1,
                     100.0, "Economics", limit_lo=0.0),
            Variable("economics.discount_rate", "Discount rate", "%", 0.0, 0.25, 1, 100.0,
                     "Economics"),
            Variable("economics.plant_lifetime", "Plant lifetime", "yr", 5.0, 40.0, 0,
                     group="Economics", limit_lo=1.0),
            Variable("economics.tax_rate", "Income tax", "%", 0.0, 0.5, 1, 100.0, "Economics",
                     limit_lo=0.0, limit_hi=1.0),
            Variable("lcia.elec_gwp", "Grid electricity GWP", "kg CO₂-eq/kWh", 0.0, 1.2, 3,
                     group="Environment", limit_lo=0.0),
            Variable("lcia.heat_gwp", "Heat GWP", "kg CO₂-eq/MJ", 0.0, 0.12, 4,
                     group="Environment", limit_lo=0.0),
        ]
    return out


def all_variables(scn: Scenario, roles) -> list[Variable]:
    """Every distinct knob of the given roles plus the plant-wide ones."""
    seen: dict[str, Variable] = {}
    for role in list(roles) + [PLANT]:
        for v in variables_for(role, scn):
            seen.setdefault(v.path, v)
    return list(seen.values())


def owner_roles(path: str, scn: Scenario, roles) -> list[str]:
    """Roles whose blocks expose ``path`` (used to put an input issue on the drawing)."""
    out = []
    for role in roles:
        if any(v.path == path for v in variables_for(role, scn)):
            out.append(role)
    return out


# --------------------------------------------------------------------------- #
# Technology presets
# --------------------------------------------------------------------------- #
def technology_options(role: str, scn: Scenario, lib) -> tuple[str, list[str]] | None:
    """``(current, choices)`` for a block whose technology comes from the library."""
    if lib is None:
        return None
    base = role_base(role)
    if base == B.CULTIVATION:
        return scn.system.name, list(lib.systems)
    if base == B.HARVEST:
        return scn.harvesting.name, list(lib.harvesting)
    if base == B.DRYING:
        return scn.drying.name, list(lib.drying)
    if base in (B.EXTRACTION, B.DISRUPTION) and scn.extraction.enabled:
        return scn.extraction.name, list(lib.extraction)
    return None


def apply_technology(scn: Scenario, role: str, name: str, lib) -> None:
    """Swap the preset behind a block, the way the Scenario tab does."""
    base = role_base(role)
    if base == B.CULTIVATION and name in lib.systems:
        old = scn.system
        new = copy.deepcopy(lib.systems[name])
        own = {m.name for m in old.materials}
        scn.materials = list(new.materials) + [m for m in scn.materials if m.name not in own]
        scn.utilities = list(new.utilities)
        if new.basis != old.basis:
            scn.scale = 100_000.0 if new.basis == Basis.AREA else 500.0
        if new.product_price and not scn.products:
            scn.product_price = new.product_price
        scn.system = new
    elif base == B.HARVEST and name in lib.harvesting:
        scn.harvesting = copy.deepcopy(lib.harvesting[name])
    elif base == B.DRYING and name in lib.drying:
        scn.drying = copy.deepcopy(lib.drying[name])
    elif base in (B.EXTRACTION, B.DISRUPTION) and name in lib.extraction:
        allocation = scn.extraction.allocation
        scn.extraction = copy.deepcopy(lib.extraction[name])
        scn.extraction.enabled = True
        scn.extraction.allocation = allocation


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(scn: Scenario) -> tuple[Results | None, list[InputIssue]]:
    """Run the engine; ``None`` results when the inputs are not admissible."""
    issues = check_inputs(scn)
    if any(i.is_error for i in issues):
        return None, issues
    try:
        return run_scenario(scn), issues
    except InadmissibleScenarioError:
        return None, issues


def headline(r: Results) -> tuple[float, float]:
    """Cost and GWP per kg of the reference product, as the KPI cards show them."""
    if r.main_product is not None:
        return r.main_product.production_cost_eur_per_kg, r.main_product.gwp_kg_co2eq_per_kg
    return r.tea.production_cost_eur_per_kg, r.lca.gwp_kg_co2eq_per_kg


@dataclass(frozen=True)
class KPI:
    key: str
    label: str
    unit: str
    lower_is_better: bool
    decimals: int = 2


KPIS: tuple[KPI, ...] = (
    KPI("cost", "Production cost", "€/kg", True),
    KPI("gwp", "GWP", "kg CO₂-eq/kg", True),
    KPI("output", "Output", "t/yr", False, 0),
    KPI("capex", "Total investment", "M€", True, 1),
    KPI("opex", "Operating cost", "M€/yr", True, 2),
    KPI("npv", "NPV", "M€", False, 1),
    KPI("energy", "Specific energy", "kWh/kg DW", True, 2),
    KPI("water", "Water", "m³/kg DW", True, 3),
)


def kpis(r: Results) -> dict[str, float]:
    cost, gwp = headline(r)
    out_kg = r.main_product.annual_kg if r.main_product else r.inventory.annual_biomass_kg
    inv = r.inventory
    return {
        "cost": cost,
        "gwp": gwp,
        "output": out_kg / 1000.0,
        "capex": r.tea.total_investment / 1e6,
        "opex": r.tea.annual_opex / 1e6,
        "npv": r.tea.npv / 1e6,
        "energy": inv.elec_kwh_per_kg + inv.heat_mj_per_kg / 3.6,
        "water": r.lca.water_m3_per_kg,
    }


# --------------------------------------------------------------------------- #
# Attribution of the engine totals to blocks
# --------------------------------------------------------------------------- #
@dataclass
class UnitPerformance:
    role: str
    power_kw: float = 0.0           # electricity
    heat_kw: float = 0.0            # thermal duty drawn from the heat account
    annual_cost: float = 0.0        # EUR/yr
    capital: float = 0.0            # EUR, share of the direct fixed capital
    purchase_cost: float = 0.0      # EUR, equipment as purchased
    units_parallel: int = 0
    gwp: float = 0.0                # kg CO2-eq per kg dry biomass
    elec_kwh_per_kg: float = 0.0
    heat_mj_per_kg: float = 0.0
    cost_items: dict = field(default_factory=dict)   # EUR/yr by line
    gwp_items: dict = field(default_factory=dict)    # kg CO2-eq/kg by line


@dataclass
class Attribution:
    units: dict[str, UnitPerformance]   # by base role, PLANT included
    annual_opex: float
    gwp: float
    annual_kg: float
    op_hours: float

    def share(self, role: str, metric: str = "annual_cost") -> float:
        """Fraction of the plant total (signed for GWP credits)."""
        u = self.units.get(role_base(role))
        if u is None:
            return 0.0
        total = self.annual_opex if metric == "annual_cost" else self.gwp
        value = getattr(u, metric)
        if metric in ("power_kw", "heat_kw"):
            total = sum(getattr(x, metric) for x in self.units.values())
        return value / total if total else 0.0

    def section_total(self, sec: Section, metric: str) -> float:
        return sum(getattr(self.units[r], metric) for r in sec.roles if r in self.units)


def gross_per_product(scn: Scenario) -> float:
    """kg of biomass cultivated per kg leaving the gate (same bound as the inventory)."""
    return 1.0 / min(max(scn.harvesting.recovery, 1e-6), 1.0)


def stage_energy(r: Results) -> tuple[dict[str, float], dict[str, float]]:
    """Electricity (kWh/kg) and heat-account energy (MJ/kg) by block role."""
    scn, inv = r.scenario, r.inventory
    eb = inv.elec_breakdown
    ext = scn.extraction
    disruption = ext.disruption_elec_kwh_per_kg if ext.enabled else 0.0
    elec = {
        B.CULTIVATION: eb.get("cultivation", 0.0),
        B.HARVEST: eb.get("harvesting", 0.0),
        B.DRYING: eb.get("drying", 0.0),
        B.DISRUPTION: disruption,
        B.EXTRACTION: eb.get("extraction", 0.0) - disruption,
    }
    sys, dry = scn.system, scn.drying
    heat = {B.CULTIVATION: 0.0, B.DRYING: 0.0, B.EXTRACTION: 0.0}
    if sys.cultivation_heat_fuel != "electricity":
        heat[B.CULTIVATION] = sys.cultivation_heat_mj_per_kg * gross_per_product(scn)
    if dry.enabled and dry.fuel != "electricity":
        heat[B.DRYING] = inv.water_evaporated_per_kg * dry.thermal_mj_per_kg_water
    if ext.enabled:
        heat[B.EXTRACTION] = ext.heat_mj_per_kg
    return elec, heat


_CAPEX_GROUPS = {
    B.CULTIVATION: "Cultivation equipment",
    B.HARVEST: "Harvesting equipment",
    B.DRYING: "Drying equipment",
    B.EXTRACTION: "Extraction equipment",
}


def _line_label(name: str) -> str:
    # The engine books all process heat on one line named after drying; once it
    # is split over the blocks that use it (dryer, solvent recovery) it is just heat.
    return "Heat" if name == "Heat (drying)" else name


def _split(total: float, weights: dict[str, float]) -> dict[str, float]:
    s = sum(weights.values())
    if not s:
        return {}
    return {k: total * w / s for k, w in weights.items() if w}


def attribute(r: Results) -> Attribution:
    """Break the TEA and LCA totals down by block role."""
    scn, inv, tea, lca = r.scenario, r.inventory, r.tea, r.lca
    annual_kg = inv.annual_biomass_kg
    op_hours = max(scn.system.operating_days, 1.0) * 24.0
    units: dict[str, UnitPerformance] = {}

    def unit(role: str) -> UnitPerformance:
        return units.setdefault(role, UnitPerformance(role))

    elec, heat = stage_energy(r)
    for role, kwh in elec.items():
        if kwh:
            u = unit(role)
            u.elec_kwh_per_kg = kwh
            u.power_kw = kwh * annual_kg / op_hours
    for role, mj in heat.items():
        if mj:
            u = unit(role)
            u.heat_mj_per_kg = mj
            u.heat_kw = mj * annual_kg / op_hours / 3.6

    # Capital: each group's share of the direct fixed capital. Indirect cost is
    # proportional to installed cost, and land belongs to cultivation.
    eco = scn.economics
    land = scn.scale * scn.system.land_m2_per_unit * eco.land_price
    capital: dict[str, float] = {}
    for role, group in _CAPEX_GROUPS.items():
        installed = tea.capex_breakdown.get(group, 0.0)
        cap = installed * (1.0 + eco.indirect_factor) + (land if role == B.CULTIVATION else 0.0)
        if cap or group in tea.cost_scaling:
            u = unit(role)
            u.capital = cap
            sc = tea.cost_scaling.get(group)
            if sc is not None and cap:
                u.purchase_cost = sc.cost
                u.units_parallel = sc.units
            capital[role] = cap

    wf = scn.waste_feed
    waste_name = (wf.name or "Waste feed") if inv.waste_feed_per_kg > 0 else None
    materials = {m.name for m in scn.materials}
    utilities = {u.name for u in scn.utilities}
    feed_lines = {
        "CO2": B.FEED_CARBON, "Bicarbonate (NaHCO3)": B.FEED_CARBON,
        "Nitrogen": B.FEED_NUTRIENTS, "Phosphorus": B.FEED_NUTRIENTS,
        "Water": B.FEED_WATER, "Substrate": B.FEED_SUBSTRATE, "Solvent": B.FEED_SOLVENT,
    }

    def route_cost(name: str, value: float) -> None:
        if name == "Electricity":
            parts = _split(value, elec)
        elif name == "Heat (drying)":
            parts = _split(value, heat)
        elif name == "Facility-dependent":
            parts = _split(value, capital)
        elif name in feed_lines:
            parts = {feed_lines[name]: value}
        elif waste_name is not None and name == waste_name:
            parts = {B.FEED_WASTE: value}
        elif name in materials:
            parts = {B.FEED_CHEMICALS: value}
        elif name in utilities:
            parts = {B.CULTIVATION: value}
        else:   # labour, overhead, other operating
            parts = {}
        if not parts:
            parts = {PLANT: value}
        item = _line_label(name)
        for role, v in parts.items():
            u = unit(role)
            u.annual_cost += v
            u.cost_items[item] = u.cost_items.get(item, 0.0) + v

    for name, value in tea.opex_breakdown.items():
        route_cost(name, value)

    solvent = scn.extraction.solvent_name if scn.extraction.enabled else None
    gwp_lines = {
        "CO2 supply": B.FEED_CARBON, "Bicarbonate (NaHCO3)": B.FEED_CARBON,
        "Nitrogen": B.FEED_NUTRIENTS, "Phosphorus": B.FEED_NUTRIENTS,
        "Substrate": B.FEED_SUBSTRATE, "Biogenic CO2 uptake": B.CULTIVATION,
        "Avoided treatment (system expansion)": B.FEED_WASTE,
    }
    for name, value in lca.gwp_breakdown.items():
        if name == "Electricity":
            parts = _split(value, elec)
        elif name == "Heat (drying)":
            parts = _split(value, heat)
        elif name in gwp_lines:
            parts = {gwp_lines[name]: value}
        elif solvent is not None and name == solvent:
            parts = {B.FEED_SOLVENT: value}
        elif waste_name is not None and name == waste_name:
            parts = {B.FEED_WASTE: value}
        elif name in materials:
            parts = {B.FEED_CHEMICALS: value}
        elif name in utilities:
            parts = {B.CULTIVATION: value}
        else:
            parts = {}
        if not parts:
            parts = {PLANT: value}
        item = _line_label(name)
        for role, v in parts.items():
            u = unit(role)
            u.gwp += v
            u.gwp_items[item] = u.gwp_items.get(item, 0.0) + v

    return Attribution(units=units, annual_opex=tea.annual_opex, gwp=lca.gwp_kg_co2eq_per_kg,
                       annual_kg=annual_kg, op_hours=op_hours)


# --------------------------------------------------------------------------- #
# Hourly flows and block specifications
# --------------------------------------------------------------------------- #
def fmt_rate(kg_h: float) -> str:
    a = abs(kg_h)
    if a >= 1e6:
        return f"{kg_h / 1e6:,.2f} kt/h"
    if a >= 1000.0:
        return f"{kg_h / 1000.0:,.2f} t/h"
    if a >= 1.0:
        return f"{kg_h:,.0f} kg/h"
    if a > 0.0:
        return f"{kg_h:,.2f} kg/h"
    return "0 kg/h"


def fmt_power(kw: float) -> str:
    a = abs(kw)
    if a >= 1000.0:
        return f"{kw / 1000.0:,.2f} MW"
    if a >= 10.0:
        return f"{kw:,.0f} kW"
    return f"{kw:,.1f} kW"


def fmt_money(eur: float) -> str:
    a = abs(eur)
    if a >= 1e9:
        return f"{eur / 1e9:,.2f} bn€"
    if a >= 1e6:
        return f"{eur / 1e6:,.2f} M€"
    if a >= 1e3:
        return f"{eur / 1e3:,.0f} k€"
    return f"{eur:,.0f} €"


def fmt_value(value: float, decimals: int) -> str:
    if value != 0 and abs(value) < 10 ** (-decimals):
        return f"{value:.2g}"
    return f"{value:,.{decimals}f}"


def specs(role: str, r: Results, att: Attribution | None = None) -> list[tuple[str, str]]:
    """Read-only figures that describe a block at the current operating point."""
    scn, inv = r.scenario, r.inventory
    base = role_base(role)
    f = B.hourly_flows(scn, r)
    sys = scn.system
    area = sys.basis == Basis.AREA
    u = att.units.get(base) if att is not None else None
    out: list[tuple[str, str]] = []

    def energy_rows():
        if u is None:
            return
        if u.power_kw:
            out.append(("Electric load", fmt_power(u.power_kw)))
        if u.heat_kw:
            out.append(("Heat duty", fmt_power(u.heat_kw) + " th"))

    if base == B.CULTIVATION:
        unit = "m²" if area else "m³"
        out.append(("Cultivation area" if area else "Culture volume", f"{scn.scale:,.0f} {unit}"))
        if inv.batches_per_year:
            out.append(("Batches", f"{inv.batches_per_year:,.0f}/yr × {scn.batch_size_kg:,.0f} kg"))
        else:
            out.append(("Productivity", f"{sys.productivity:,.2f} {'g/m²/d' if area else 'g/L/d'}"))
        out.append(("Biomass growth", fmt_rate(f.gross)))
        conc = max(sys.biomass_conc, 1e-9)
        out.append(("Broth to harvest", f"{f.gross / conc:,.1f} m³/h"))
        if not inv.batches_per_year:
            if area:
                out.append(("Harvest depth", f"{sys.productivity / conc:,.1f} mm/d"))
            else:
                d = sys.productivity / conc
                out.append(("Dilution rate", f"{d:,.3f} 1/d (HRT {1 / d:,.1f} d)" if d else "0"))
        if u is not None and u.units_parallel > 1:
            out.append(("Units in parallel", f"{u.units_parallel}"))
        out.append(("Land", f"{scn.scale * sys.land_m2_per_unit / 1e4:,.2f} ha"))
        if sys.mode == TrophicMode.PHOTOTROPHIC:
            out.append(("CO₂ fixed", fmt_rate(inv.co2_fixed_per_kg * f.net)))
        energy_rows()
    elif base == B.HARVEST:
        harv = scn.harvesting
        broth = max(sys.biomass_conc, 1e-9) / 1000.0
        out += [("Biomass recovery", f"{harv.recovery * 100:,.1f} %"),
                ("Concentrate", f"{harv.final_solids * 100:,.1f} % DS"),
                ("Broth feed", f"{f.gross / max(sys.biomass_conc, 1e-9):,.1f} m³/h"),
                ("Concentration factor", f"×{harv.final_solids / broth:,.0f}"),
                ("Biomass lost", fmt_rate(f.gross - f.net))]
        energy_rows()
    elif base == B.DRYING and scn.drying.enabled:
        out += [("Water evaporated", fmt_rate(inv.water_evaporated_per_kg * f.net)),
                ("Product solids", f"{scn.drying.final_solids * 100:,.1f} % DS"),
                ("Specific heat", f"{scn.drying.thermal_mj_per_kg_water:,.2f} MJ/kg H₂O"),
                ("Fuel", scn.drying.fuel.replace("_", " "))]
        energy_rows()
    elif base == B.DISRUPTION and scn.extraction.enabled:
        out.append(("Specific energy",
                    f"{scn.extraction.disruption_elec_kwh_per_kg:,.2f} kWh/kg"))
        energy_rows()
    elif base == B.EXTRACTION and scn.extraction.enabled:
        ext = scn.extraction
        out += [("Solvent", ext.solvent_name),
                ("Solvent circulation", fmt_rate(f.solvent)),
                ("Solvent make-up", fmt_rate(f.solvent_makeup)),
                ("Solvent recovery", f"{ext.solvent_recovery * 100:,.1f} %"),
                ("Allocation", ext.allocation)]
        if f.main_product is not None:
            out.append(("Main product", fmt_rate(f.main_product)))
        energy_rows()
    elif base == B.FEED_WATER:
        out += [("Flow", fmt_rate(f.water)),
                ("Specific use", f"{inv.water_m3_per_kg:,.3f} m³/kg DW")]
    elif base == B.FEED_NUTRIENTS:
        out += [("Nitrogen bought", fmt_rate(inv.nitrogen_purchased_per_kg * f.net)),
                ("Phosphorus bought", fmt_rate(inv.phosphorus_purchased_per_kg * f.net)),
                ("N not assimilated", fmt_rate(inv.nitrogen_emitted_per_kg * f.net)),
                ("P not assimilated", fmt_rate(inv.phosphorus_emitted_per_kg * f.net))]
    elif base == B.FEED_CARBON:
        if inv.bicarbonate_supply_per_kg:
            out.append(("NaHCO₃ supplied", fmt_rate(f.bicarbonate)))
            out.append(("Specific", f"{inv.bicarbonate_supply_per_kg:,.2f} kg/kg DW"))
        else:
            out.append(("CO₂ supplied", fmt_rate(f.co2)))
            out.append(("Specific", f"{inv.co2_supply_per_kg:,.2f} kg/kg DW"))
        out.append(("Utilisation", f"{sys.co2_utilization * 100:,.1f} %"))
    elif base == B.FEED_SUBSTRATE:
        out += [("Substrate", fmt_rate(f.substrate)),
                ("Specific", f"{inv.substrate_per_kg:,.2f} kg/kg DW"),
                ("Yield", f"{sys.substrate_yield:,.3f} kg/kg")]
    elif base == B.FEED_CHEMICALS:
        for m in scn.materials[:8]:
            out.append((m.name, fmt_rate(m.amount_per_kg * f.net)))
    elif base == B.FEED_WASTE and scn.waste_feed.enabled:
        unit = scn.waste_feed.unit
        out += [("Stream", scn.waste_feed.name or "waste feed"),
                ("Dosed", f"{inv.waste_feed_per_kg:,.4f} {unit}/kg DW"),
                ("N from stream", fmt_rate(inv.nitrogen_from_waste_per_kg * f.net)),
                ("P from stream", fmt_rate(inv.phosphorus_from_waste_per_kg * f.net))]
    elif base == B.FEED_INOCULUM:
        out.append(("Seed", fmt_rate(f.inoculum)))
        out.append(("Note", "drawn for completeness; not costed"))
    elif base == B.PRODUCT:
        cost, gwp = headline(r)
        name = r.main_product.name if r.main_product else (scn.product_name or "dry biomass")
        rate = f.main_product if f.main_product is not None else f.net
        price = get_value(scn, SELLING_PRICE)
        out += [("Product", name), ("Rate", fmt_rate(rate)),
                ("Annual", f"{rate * att.op_hours / 1000:,.0f} t/yr" if att else "—"),
                ("Production cost", f"{cost:,.2f} €/kg"),
                ("GWP", f"{gwp:,.2f} kg CO₂-eq/kg")]
        if price > 0:
            out.append(("Selling price", f"{price:,.2f} €/kg"))
            out.append(("Margin", f"{(price - cost) / price * 100:,.0f} %"))
    return out


Segment = tuple[str, str]   # (glyph, text); glyph is "", "power", "heat" or "evap"


def faceplate(role: str, r: Results, att: Attribution) -> list[list[Segment]]:
    """Up to two short lines for the read-out plate under a block on the canvas.

    Each line is a list of segments; the canvas draws the glyph (a lightning
    bolt for electricity, a flame for heat) in front of its text.
    """
    scn, inv = r.scenario, r.inventory
    base = role_base(role)
    f = B.hourly_flows(scn, r)
    u = att.units.get(base)
    energy: list[Segment] = []
    if u is not None and u.power_kw:
        energy.append(("power", fmt_power(u.power_kw)))
    if u is not None and u.heat_kw:
        energy.append(("heat", fmt_power(u.heat_kw)))
    sys = scn.system
    if base == B.CULTIVATION:
        prod = (f"{sys.productivity:,.1f} {'g/m²/d' if sys.basis == Basis.AREA else 'g/L/d'}"
                if not inv.batches_per_year else f"{inv.batches_per_year:,.0f} batches/yr")
        return [[("", f"{prod}  ·  {sys.biomass_conc:,.2f} g/L")], energy]
    if base == B.HARVEST:
        h = scn.harvesting
        if role != B.HARVEST:   # a later stage: the train's figures sit on the first
            return [[("", "dewatering train, stage 2")]]
        return [[("", f"η {h.recovery * 100:,.1f} %  ·  {h.final_solids * 100:,.0f} % DS")],
                energy]
    if base == B.DRYING:
        return [[("evap", fmt_rate(inv.water_evaporated_per_kg * f.net))], energy]
    if base == B.DISRUPTION:
        return [[("", f"{scn.extraction.disruption_elec_kwh_per_kg:,.2f} kWh/kg")], energy]
    if base == B.EXTRACTION:
        ext = scn.extraction
        return [[("", f"S/B {ext.solvent_kg_per_kg:,.1f}  ·  rec {ext.solvent_recovery * 100:,.1f} %")],
                energy]
    if base == B.PRODUCT:
        cost, _ = headline(r)
        rate = f.main_product if f.main_product is not None else f.net
        return [[("", fmt_rate(rate))], [("", f"{cost:,.2f} €/kg")]]
    if base == B.MEDIA_PREP:
        return [[("", fmt_rate(f.water + f.nutrients + f.chemicals + f.waste_feed))],
                [("", "make-up medium")]]
    if base == B.FEED_WATER:
        return [[("", fmt_rate(f.water))], [("", f"{inv.water_m3_per_kg:,.2f} m³/kg DW")]]
    if base == B.FEED_NUTRIENTS:
        return [[("", fmt_rate(f.nutrients))],
                [("", f"uptake {sys.nutrient_uptake * 100:,.0f} %")]]
    if base == B.FEED_CARBON:
        rate = f.bicarbonate if inv.bicarbonate_supply_per_kg else f.co2
        return [[("", fmt_rate(rate))], [("", f"utilisation {sys.co2_utilization * 100:,.0f} %")]]
    if base == B.FEED_SUBSTRATE:
        return [[("", fmt_rate(f.substrate))], [("", f"Y {sys.substrate_yield:,.2f} kg/kg")]]
    if base == B.FEED_SOLVENT:
        return [[("", fmt_rate(f.solvent))], [("", f"make-up {fmt_rate(f.solvent_makeup)}")]]
    if base == B.FEED_CHEMICALS:
        n = len(scn.materials)
        return [[("", fmt_rate(f.chemicals))], [("", f"{n} reagent{'s' if n != 1 else ''}")]]
    if base == B.FEED_WASTE:
        wf = scn.waste_feed
        return [[("", fmt_rate(f.waste_feed))],
                [("", f"covers {wf.coverage * 100:,.0f} % of {wf.dosed_on}")]]
    if base == B.FEED_INOCULUM:
        return [[("", fmt_rate(f.inoculum))], [("", "drawn, not costed")]]
    return []


def stream_class(flow, src_port: str = "", src_role: str = "") -> str:
    """Which kind of stream a flow is, for its colour on the canvas."""
    total = sum(flow.values())
    if total <= 0:
        return "empty"
    base = role_base(src_role)
    if src_port == "vapour":
        return "vapour"
    if src_port == "effluent":
        return "effluent"
    if base == B.FEED_INOCULUM:
        return "broth"
    if base == B.FEED_CARBON:
        return "gas" if flow.get("co2", 0.0) > 0 else "nutrients"
    if base == B.FEED_WASTE:
        return "effluent"
    share = {k: v / total for k, v in flow.items()}
    if share.get("co2", 0.0) > 0.5:
        return "gas"
    prod, solv = share.get("product", 0.0), share.get("solvent", 0.0)
    if prod + solv > 0.5:
        return "extract" if prod >= solv else "solvent"
    if share.get("substrate", 0.0) > 0.5:
        return "substrate"
    if share.get("other", 0.0) > 0.5:
        return "nutrients"
    bio, water = flow.get("biomass", 0.0), flow.get("water", 0.0)
    if bio > 0:
        ds = bio / (bio + water) if bio + water > 0 else 1.0
        if ds >= 0.8:
            return "solids"
        if ds >= 0.03:
            return "slurry"
        return "broth"
    return "water"


# --------------------------------------------------------------------------- #
# Sensitivity around the operating point
# --------------------------------------------------------------------------- #
def _with(scn: Scenario, path: str, value: float) -> Scenario:
    trial = copy.deepcopy(scn)
    set_value(trial, path, value)
    return trial


def elasticity(scn: Scenario, var: Variable, step: float = 0.02):
    """Elasticity of the headline cost and GWP to ``var`` at the current point.

    ``(d ln y / d ln x)`` by central difference, one-sided where a bound is in
    the way. ``(None, None)`` when the variable is zero (no relative change is
    defined) or the neighbourhood is not admissible.
    """
    x0 = get_value(scn, var.path)
    if x0 == 0:
        return None, None
    base, _ = evaluate(scn)
    if base is None:
        return None, None
    c0, g0 = headline(base)
    xp = var.clip(x0 * (1 + step)) if x0 > 0 else var.clip(x0 * (1 - step))
    xm = var.clip(x0 * (1 - step)) if x0 > 0 else var.clip(x0 * (1 + step))
    rp, _ = evaluate(_with(scn, var.path, xp)) if xp != x0 else (base, None)
    rm, _ = evaluate(_with(scn, var.path, xm)) if xm != x0 else (base, None)
    if rp is None:
        rp, xp = base, x0
    if rm is None:
        rm, xm = base, x0
    dx = (xp - xm) / x0
    if dx == 0:
        return None, None
    cp, gp = headline(rp)
    cm, gm = headline(rm)
    e_cost = ((cp - cm) / c0) / dx if c0 and math.isfinite(c0) else None
    e_gwp = ((gp - gm) / g0) / dx if g0 and math.isfinite(g0) else None
    return e_cost, e_gwp


def response_curve(scn: Scenario, var: Variable, n: int = 31):
    """``[(x, cost, gwp)]`` across the slider range; inadmissible points are skipped."""
    x0 = get_value(scn, var.path)
    lo, hi = var.span(x0)
    lo = var.clip(lo)
    hi = var.clip(hi)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        if var.log and lo > 0:
            x = lo * (hi / lo) ** t
        else:
            x = lo + (hi - lo) * t
        r, _ = evaluate(_with(scn, var.path, x))
        if r is not None:
            cost, gwp = headline(r)
            if math.isfinite(cost) and math.isfinite(gwp):
                pts.append((x, cost, gwp))
    return pts


def tornado(scn: Scenario, variables, swing: float = 0.2):
    """Headline cost at x(1 - swing) and x(1 + swing) for each variable.

    Returns ``[(variable, cost_low_x, cost_high_x)]`` sorted by the size of the
    swing, largest first. Variables at zero, or whose neighbourhood is not
    admissible, are left out.
    """
    base, _ = evaluate(scn)
    if base is None:
        return []
    rows = []
    for var in variables:
        x0 = get_value(scn, var.path)
        if x0 == 0:
            continue
        lo_r, _ = evaluate(_with(scn, var.path, var.clip(x0 * (1 - swing))))
        hi_r, _ = evaluate(_with(scn, var.path, var.clip(x0 * (1 + swing))))
        if lo_r is None or hi_r is None:
            continue
        rows.append((var, headline(lo_r)[0], headline(hi_r)[0]))
    c0 = headline(base)[0]
    rows.sort(key=lambda t: -max(abs(t[1] - c0), abs(t[2] - c0)))
    return rows


# --------------------------------------------------------------------------- #
# Editing session: baseline, undo/redo and the change log
# --------------------------------------------------------------------------- #
@dataclass
class State:
    label: str
    key: str                     # what was changed (variable path, "tech:<role>", ...)
    scenario: Scenario
    results: Results | None
    issues: list
    kpis: dict | None
    before: float | None = None  # value before the edit, for coalesced slider drags


class DesignSession:
    """The designer's working copy of the case, separate from the Scenario tab.

    Edits are applied to a deep copy, so nothing reaches the case study until it
    is applied explicitly. Every edit is a new state; consecutive moves of one
    slider are coalesced into a single state so a drag is one step to undo.
    """

    MAX_STATES = 200

    def __init__(self, scenario: Scenario, library=None):
        self.library = library
        self.baseline = copy.deepcopy(scenario)
        first = self._state("Case study", "", copy.deepcopy(scenario))
        self.baseline_kpis = first.kpis
        self._states: list[State] = [first]
        self._pos = 0

    @staticmethod
    def _state(label: str, key: str, scn: Scenario, before=None) -> State:
        results, issues = evaluate(scn)
        return State(label, key, scn, results, issues,
                     kpis(results) if results is not None else None, before)

    # -- current state --------------------------------------------------- #
    @property
    def state(self) -> State:
        return self._states[self._pos]

    @property
    def scenario(self) -> Scenario:
        return self.state.scenario

    @property
    def results(self) -> Results | None:
        return self.state.results

    @property
    def issues(self) -> list:
        return self.state.issues

    @property
    def history(self) -> list[State]:
        return list(self._states[: self._pos + 1])

    @property
    def position(self) -> int:
        return self._pos

    @property
    def all_states(self) -> list[State]:
        """Every state, including the ones an undo stepped back over."""
        return list(self._states)

    @property
    def is_dirty(self) -> bool:
        return self._pos > 0 and self.state.key != "reset"

    def last_good(self) -> Results | None:
        """The most recent admissible result at or before the current state."""
        for st in reversed(self._states[: self._pos + 1]):
            if st.results is not None:
                return st.results
        return None

    # -- edits ----------------------------------------------------------- #
    def _push(self, st: State, replace: bool) -> None:
        del self._states[self._pos + 1:]
        if replace:
            self._states[self._pos] = st
        else:
            self._states.append(st)
            if len(self._states) > self.MAX_STATES:
                self._states.pop(1)
            self._pos = len(self._states) - 1

    def set_value(self, var: Variable, value: float, label: str = "",
                  coalesce: bool = True) -> bool:
        cur = get_value(self.scenario, var.path)
        if value == cur:
            return False
        last = self.state
        replace = coalesce and self._pos > 0 and last.key == var.path
        before = last.before if replace else cur
        scn = copy.deepcopy(self.scenario)
        set_value(scn, var.path, value)
        shown = f"{fmt_value(before * var.factor, var.decimals)} → " \
                f"{fmt_value(value * var.factor, var.decimals)} {var.unit}".strip()
        text = f"{label + ' · ' if label else ''}{var.label}: {shown}"
        self._push(self._state(text, var.path, scn, before), replace)
        return True

    def mutate(self, key: str, label: str, fn) -> None:
        """Apply ``fn(scenario)`` to a copy of the current scenario as one state."""
        scn = copy.deepcopy(self.scenario)
        fn(scn)
        self._push(self._state(label, key, scn), False)

    def set_technology(self, role: str, name: str) -> None:
        self.mutate(f"tech:{role_base(role)}", f"{ROLE_LABELS.get(role_base(role), role)}: {name}",
                    lambda s: apply_technology(s, role, name, self.library))

    def reset(self) -> None:
        """Back to the case study as it was loaded, as a new step (so it can be undone)."""
        self._push(self._state("Reset to case study", "reset", copy.deepcopy(self.baseline)),
                   False)

    def rebase(self, scenario: Scenario) -> None:
        """Adopt ``scenario`` as the new baseline and drop the history."""
        self.__init__(scenario, self.library)

    # -- undo / redo ----------------------------------------------------- #
    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._states) - 1

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self._pos -= 1
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        self._pos += 1
        return True

    def jump(self, index: int) -> None:
        if 0 <= index < len(self._states):
            self._pos = index

    def changed_paths(self) -> set[str]:
        """Variable paths whose value now differs from the baseline."""
        out = set()
        roles = [B.CULTIVATION, B.HARVEST, B.DRYING, B.DISRUPTION, B.EXTRACTION, B.FEED_WATER,
                 B.FEED_NUTRIENTS, B.FEED_CARBON, B.FEED_SUBSTRATE, B.FEED_SOLVENT,
                 B.FEED_CHEMICALS, B.FEED_WASTE, B.PRODUCT]
        for var in all_variables(self.scenario, roles):
            try:
                a = get_value(self.scenario, var.path)
                b = get_value(self.baseline, var.path)
            except (AttributeError, IndexError):
                continue
            if abs(a - b) > 1e-12 * max(1.0, abs(b)):
                out.add(var.path)
        return out

    def baseline_value(self, path: str) -> float | None:
        try:
            return get_value(self.baseline, path)
        except (AttributeError, IndexError):
            return None
