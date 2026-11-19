"""What every input field is: label, unit, admissible range, meaning, source.

The main window builds its spin boxes from this catalogue, so a field cannot
appear on screen without a unit and a tooltip, and the range the control
accepts is written in one place. The ranges and steps are the ones the window
has always used; the engine's own admissibility rules (``algametrix.inputcheck``)
still decide what is physically possible, and the window marks a field that
breaks one of them.

The provenance shown in a tooltip is whatever the data files declare: the
``source`` of a life-cycle factor in ``data/lcia.yaml``, the ``notes`` of a
preset, the ``source`` of a declared cost-scaling block. Where a default has no
declared source - the prices in ``data/parameters.yaml`` are literature-typical
placeholders by the file's own header - the tooltip says so rather than
inventing one. Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass

from algametrix.inventory import MIN_CARBON_UTILIZATION

from .fmt import sig

#: The two sizing bases and the units that change with them.
AREA, VOLUME = "area", "volume"

PLACEHOLDER_NOTE = ("Default from data/parameters.yaml: a literature-typical placeholder "
                    "with no single source. Replace it with your own figure and cite it.")


@dataclass(frozen=True)
class FieldSpec:
    """One numeric input."""

    obj: str
    attr: str
    label: str
    unit: str
    lo: float
    hi: float
    step: float
    decimals: int
    description: str
    typical: str = ""
    #: ``(area unit, volume unit)`` for a field whose unit follows the basis.
    basis_units: tuple[str, str] | None = None
    #: Where the default lives, when it is not a preset the user picked.
    origin: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.obj, self.attr)

    def unit_for(self, basis: str) -> str:
        if self.basis_units is None:
            return self.unit
        return self.basis_units[0] if basis == AREA else self.basis_units[1]

    def range_text(self, basis: str = AREA) -> str:
        unit = self.unit_for(basis)
        lo, hi = sig(self.lo, 4), sig(self.hi, 4)
        return f"{lo} to {hi} {unit}".strip()


def _f(obj, attr, label, unit, lo, hi, step, decimals, description, typical="",
       basis_units=None, origin=""):
    return FieldSpec(obj, attr, label, unit, lo, hi, step, decimals, description,
                     typical, basis_units, origin)


_FRACTION = "fraction (0-1)"
_DW = "kg/kg dry weight"
_ECON = "Economic default (data/parameters.yaml)"
_LCIA = "Background factor (data/lcia.yaml)"

SPECS: tuple[FieldSpec, ...] = (
    # --- organism -----------------------------------------------------------
    _f("organism", "carbon", "Carbon", _DW, 0.0, 1.0, 0.01, 3,
       "Elemental carbon as a mass fraction of dry weight. It drives the carbon "
       "demand: CO₂ or bicarbonate for a phototrophic culture, substrate for a "
       "heterotrophic one.",
       "0.45 to 0.55 for most microalgae; higher in lipid-rich cells."),
    _f("organism", "nitrogen", "Nitrogen", _DW, 0.0, 0.3, 0.005, 3,
       "Elemental nitrogen as a mass fraction of dry weight. It sets the nitrogen "
       "demand; protein-rich strains sit near 0.10.",
       "0.03 to 0.11; protein ÷ nitrogen between 3.5 and 6.5 for the same biomass."),
    _f("organism", "phosphorus", "Phosphorus", _DW, 0.0, 0.1, 0.001, 3,
       "Elemental phosphorus as a mass fraction of dry weight. It sets the "
       "phosphorus demand.",
       "0.005 to 0.015."),
    _f("organism", "phycocyanin", "Phycocyanin", _DW, 0.0, 0.3, 0.01, 3,
       "C-phycocyanin as a mass fraction of dry weight, a subset of the protein pool. "
       "Only a pigment product reads it.",
       "0.10 to 0.15 in Arthrospira; zero elsewhere."),
    # --- cultivation --------------------------------------------------------
    _f("system", "productivity", "Productivity", "g/m²/d", 0.0, 300.0, 1.0, 1,
       "Dry-biomass productivity of the cultivation system, averaged over the "
       "operating days: per m² of illuminated footprint for an area-based system, "
       "per litre of culture for a volume-based one.",
       "Raceway 10 to 25 g/m²/d; closed photobioreactor 20 to 40 g/m²/d; "
       "fermenter 2 to 10 g/L/d.",
       basis_units=("g/m²/d", "g/L/d")),
    _f("system", "operating_days", "Operating days", "d/yr", 1.0, 365.0, 5.0, 0,
       "Days per year the plant produces. The annual output scales with it.",
       "300 to 340 for an outdoor system in a temperate climate."),
    _f("system", "elec_kwh_per_kg", "Cultivation electricity", "kWh/kg", 0.0, 50.0, 0.1, 2,
       "Electricity of the cultivation step per kg of dry biomass: mixing, pumping, "
       "aeration, artificial light.",
       "Raceway 0.5 to 1.5; tubular photobioreactor 3 to 8."),
    _f("system", "co2_utilization", "Carbon utilization", _FRACTION, 0.05, 1.0, 0.05, 2,
       "Share of the inorganic carbon supplied (CO₂ or NaHCO₃) that the culture fixes; "
       "the rest is lost to the atmosphere or the blowdown. An efficiency, not an "
       f"amount: the balance applies a floor of {MIN_CARBON_UTILIZATION:.0%}.",
       "0.5 to 0.9 depending on the sparging design."),
    _f("system", "nutrient_uptake", "Nutrient uptake", _FRACTION, 0.1, 1.0, 0.05, 2,
       "Share of the nitrogen and phosphorus supplied that the biomass assimilates. "
       "The remainder leaves with the spent medium and counts towards eutrophication.",
       "0.8 to 0.95."),
    _f("system", "water_m3_per_kg", "Water use", "m³/kg", 0.0, 5.0, 0.05, 2,
       "Net water consumed per kg of dry biomass: evaporation plus blowdown, minus "
       "what is recycled.",
       "Open pond 0.3 to 1.0; closed reactor 0.1 to 0.2."),
    _f("system", "cultivation_heat_mj_per_kg", "Cultivation heat", "MJ/kg", 0.0, 200.0, 2.0, 1,
       "Thermal energy to keep the culture at temperature, per kg of dry biomass. "
       "Zero for an unheated system in a warm climate; the dominant burden of a "
       "heated pond or greenhouse in a temperate one."),
    _f("system", "substrate_yield", "Substrate yield", "kg/kg", 0.0, 1.0, 0.05, 2,
       "kg of dry biomass per kg of organic substrate, for a heterotrophic system. "
       "Bounded by the carbon the substrate carries: the input check refuses a yield "
       "that would put more carbon in the biomass than in the feed.",
       "0.3 to 0.5 on glucose."),
    _f("system", "capex_per_unit", "Cultivation CAPEX", "€/m²", 0.0, 5000.0, 5.0, 1,
       "Purchased equipment cost of the cultivation system per m² of pond or m³ of "
       "reactor, before the installation factor.",
       "Raceway 20 to 40 €/m²; tubular photobioreactor 100 to 200 €/m²; "
       "stirred fermenter several hundred €/m³.",
       basis_units=("€/m²", "€/m³")),
    _f("scenario", "scale", "Plant scale", "m²", 1.0, 1e9, 1000.0, 0,
       "Cultivation area (m²) or reactor volume (m³) of the whole plant. Every "
       "annual quantity follows from it.",
       basis_units=("m²", "m³")),
    # --- harvest and drying -------------------------------------------------
    _f("harvesting", "recovery", "Biomass recovery", _FRACTION, 0.1, 1.0, 0.02, 2,
       "Share of the biomass leaving the culture that reaches the next step; the "
       "rest is lost with the spent medium.",
       "0.85 to 0.95."),
    _f("harvesting", "elec_kwh_per_kg", "Harvesting electricity", "kWh/kg", 0.0, 20.0, 0.1, 2,
       "Electricity of the dewatering step per kg of dry biomass processed.",
       "Micro-screen 0.2; membrane 0.4 to 1; disc-stack centrifuge 1 to 3.5."),
    _f("harvesting", "final_solids", "Concentrate solids", _FRACTION, 0.02, 0.5, 0.01, 2,
       "Dry-matter content of the concentrate leaving the harvest step. With the "
       "dryer's final solids it fixes how much water the dryer has to evaporate.",
       "0.08 to 0.25."),
    _f("drying", "thermal_mj_per_kg_water", "Drying heat", "MJ/kg water", 0.0, 6.0, 0.1, 2,
       "Heat to evaporate one kg of water in the dryer.",
       "Spray dryer 3.5 to 4.5; drum dryer about 3."),
    _f("drying", "final_solids", "Dried product solids", _FRACTION, 0.5, 1.0, 0.01, 2,
       "Dry-matter content of the dried product.",
       "0.90 to 0.96."),
    # --- economics: prices --------------------------------------------------
    _f("economics", "electricity_price", "Electricity price", "€/kWh", 0.0, 1.0, 0.01, 3,
       "What the plant pays per kWh of grid electricity. A region in the setup "
       "wizard fills it from data/regions.yaml with its source.", origin=_ECON),
    _f("economics", "heat_price", "Heat price", "€/MJ", 0.0, 0.2, 0.005, 3,
       "Price of process heat per MJ delivered (natural gas or electric heat).",
       origin=_ECON),
    _f("economics", "co2_price", "CO₂ price", "€/kg CO₂", -0.2, 1.0, 0.01, 3,
       "Price per kg of CO₂ delivered to the culture. Zero or negative for a waste "
       "stream the plant is paid to take.", origin=_ECON),
    _f("economics", "bicarbonate_price", "Bicarbonate price", "€/kg NaHCO₃", 0.0, 2.0, 0.01, 3,
       "Price per kg of sodium bicarbonate, the carbon source of alkaline cultures "
       "such as Arthrospira.", origin=_ECON),
    _f("economics", "nitrogen_price", "Nitrogen price", "€/kg N", 0.0, 10.0, 0.1, 2,
       "Price of mineral nitrogen per kg of N, whatever the fertiliser.", origin=_ECON),
    _f("economics", "phosphorus_price", "Phosphorus price", "€/kg P", 0.0, 15.0, 0.1, 2,
       "Price of mineral phosphorus per kg of P (not per kg of P₂O₅).", origin=_ECON),
    _f("economics", "substrate_price", "Substrate price", "€/kg", 0.0, 3.0, 0.05, 2,
       "Price per kg of the organic substrate of a heterotrophic system.", origin=_ECON),
    _f("economics", "water_price", "Water price", "€/m³", 0.0, 5.0, 0.05, 2,
       "Price of process water per m³ consumed.", origin=_ECON),
    _f("economics", "land_price", "Land price", "€/m²", 0.0, 200.0, 1.0, 1,
       "One-time purchase price of land per m² occupied; the system's land factor "
       "sets how many m² a m² of pond or a m³ of reactor takes.", origin=_ECON),
    # --- economics: capital -------------------------------------------------
    _f("economics", "harvest_capex_per_kgyr", "Harvest CAPEX", "€ per kg/yr", 0.0, 50.0, 0.5, 2,
       "Harvesting equipment cost per kg/yr of annual dry-biomass capacity, before "
       "the installation factor.", origin=_ECON),
    _f("economics", "drying_capex_per_kgyr", "Drying CAPEX", "€ per kg/yr", 0.0, 50.0, 0.5, 2,
       "Drying equipment cost per kg/yr of annual dry-biomass capacity, before the "
       "installation factor.", origin=_ECON),
    _f("economics", "installation_factor", "Installation factor", "×", 1.0, 6.0, 0.1, 2,
       "Installed cost = purchased equipment × this factor: piping, instrumentation, "
       "civil and electrical work.", "2 to 4 for a process plant.", origin=_ECON),
    _f("economics", "labor_cost_per_year", "Labour", "€/yr", 0.0, 1e7, 10000.0, 0,
       "Total labour cost per year at the reference capacity, before any labour "
       "scaling the data declares.", origin=_ECON),
    _f("economics", "maintenance_frac", "Maintenance", "fraction of CAPEX/yr", 0.0, 0.2, 0.005, 3,
       "Annual maintenance as a fraction of the total capital investment.",
       "0.02 to 0.06.", origin=_ECON),
    # --- economics: finance -------------------------------------------------
    _f("economics", "discount_rate", "Discount rate", _FRACTION, 0.0, 0.25, 0.005, 3,
       "Discount rate for the NPV and the capital recovery factor.",
       "0.06 to 0.12.", origin=_ECON),
    _f("economics", "plant_lifetime", "Plant lifetime", "yr", 1.0, 40.0, 1.0, 0,
       "Project evaluation horizon.", "15 to 25 years.", origin=_ECON),
    _f("economics", "depreciation_years", "Depreciation period", "yr", 1.0, 30.0, 1.0, 0,
       "Straight-line depreciation period of the fixed capital.", "10 years.",
       origin=_ECON),
    _f("economics", "tax_rate", "Tax rate", _FRACTION, 0.0, 0.6, 0.05, 2,
       "Income tax applied to the gross profit.", origin=_ECON),
    # --- life-cycle background ---------------------------------------------
    _f("lcia", "elec_gwp", "Electricity GWP", "kg CO₂-eq/kWh", 0.0, 1.5, 0.01, 3,
       "Cradle-to-gate climate-change factor of the grid electricity consumed.",
       origin=_LCIA),
    _f("lcia", "elec_ced", "Electricity CED", "MJ/kWh", 0.0, 15.0, 0.5, 2,
       "Cumulative energy demand of the grid electricity consumed.", origin=_LCIA),
    _f("lcia", "heat_gwp", "Heat GWP", "kg CO₂-eq/MJ", 0.0, 0.3, 0.005, 3,
       "Climate-change factor of process heat per MJ delivered.", origin=_LCIA),
    _f("lcia", "nitrogen_gwp", "N fertiliser GWP", "kg CO₂-eq/kg N", 0.0, 20.0, 0.5, 2,
       "Climate-change factor of mineral nitrogen fertiliser production, per kg N.",
       origin=_LCIA),
    _f("lcia", "phosphorus_gwp", "P fertiliser GWP", "kg CO₂-eq/kg P", 0.0, 10.0, 0.5, 2,
       "Climate-change factor of phosphate fertiliser production, per kg P.",
       origin=_LCIA),
    _f("lcia", "co2_supply_gwp", "CO₂ supply GWP", "kg CO₂-eq/kg CO₂", 0.0, 1.0, 0.01, 3,
       "Burden of capturing, compressing and delivering the CO₂ fed to the culture.",
       origin=_LCIA),
    _f("lcia", "bicarbonate_gwp", "Bicarbonate GWP", "kg CO₂-eq/kg NaHCO₃", 0.0, 3.0, 0.05, 2,
       "Climate-change factor of sodium bicarbonate production.", origin=_LCIA),
    _f("lcia", "substrate_gwp", "Substrate GWP", "kg CO₂-eq/kg", 0.0, 5.0, 0.05, 2,
       "Climate-change factor of the organic substrate, per kg.", origin=_LCIA),
)

BY_KEY: dict[tuple[str, str], FieldSpec] = {s.key: s for s in SPECS}


def spec(obj: str, attr: str) -> FieldSpec:
    return BY_KEY[(obj, attr)]


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def lcia_source(lib, attr: str) -> str:
    """The declared provenance of one background factor, or an empty string."""
    method = getattr(lib, "lcia_method", None)
    if method is None:
        return ""
    for f in method.factors:
        if f.name == attr:
            parts = [f"{f.quality}"]
            if f.geography:
                parts.append(f.geography)
            if f.reference_period:
                parts.append(f.reference_period)
            head = " · ".join(parts)
            return f"{head}. {' '.join(str(f.source).split())}"
    return ""


def scaling_source(scaling) -> str:
    """The source of a declared cost-scaling block, if it carries one."""
    src = getattr(scaling, "source", "") if scaling is not None else ""
    return " ".join(str(src).split())


def preset_notes(preset) -> str:
    """The ``notes`` a catalogue entry carries, cleaned up."""
    return " ".join(str(getattr(preset, "notes", "") or "").split())


# --------------------------------------------------------------------------- #
# Tooltips
# --------------------------------------------------------------------------- #
def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def tooltip(fs: FieldSpec, *, basis: str = AREA, default=None, default_label: str = "",
            source: str = "") -> str:
    """Rich-text tooltip: what the field is, what it accepts, where its default is from."""
    unit = fs.unit_for(basis)
    lines = [f"<b>{_esc(fs.label)}</b>" + (f" <span style='color:#667283'>[{_esc(unit)}]</span>"
                                           if unit else ""),
             f"<p style='margin:4px 0'>{_esc(fs.description)}</p>"]
    facts = [f"Accepts {_esc(fs.range_text(basis))}."]
    if fs.typical:
        facts.append(f"Typical: {_esc(fs.typical)}")
    if default is not None:
        shown = sig(default, 4) if isinstance(default, (int, float)) else str(default)
        who = f" ({_esc(default_label)})" if default_label else ""
        facts.append(f"Default{who}: {_esc(shown)} {_esc(unit)}".rstrip())
    lines.append("<br/>".join(facts))
    if source:
        lines.append(f"<p style='margin:4px 0'><i>Source:</i> {_esc(source)}</p>")
    elif fs.origin:
        note = PLACEHOLDER_NOTE if fs.origin == _ECON else fs.origin
        lines.append(f"<p style='margin:4px 0; color:#667283'>{_esc(note)}</p>")
    return "<div style='max-width: 380px'>" + "".join(lines) + "</div>"


def plain_tooltip(title: str, body: str, note: str = "") -> str:
    """A tooltip for a control that is not a catalogued numeric field."""
    html = f"<b>{_esc(title)}</b><p style='margin:4px 0'>{_esc(body)}</p>"
    if note:
        html += f"<p style='margin:4px 0; color:#667283'>{_esc(note)}</p>"
    return "<div style='max-width: 380px'>" + html + "</div>"
