"""Starting-point templates: the validated cases, as ready-made scenarios.

The setup wizard offers these so a researcher can begin from the case closest to
their own study instead of a blank form. Each template also records which
validation it corresponds to.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from .library import Library, load_library
from .models import Basis, Extraction, Material, Product, Scenario
from .products import main_product, product_yield

# Product goals used by the wizard to group templates and preset the downstream.
GOALS = ["biomass", "oil", "protein", "pigment", "biofuel"]


def apply_goal(scn: Scenario, goal: str) -> None:
    """Configure products & extraction for a product goal (keeps organism/system)."""
    if goal in ("biomass", "protein"):
        scn.extraction = Extraction(enabled=False)
        scn.products = []
        scn.product_price = 8.0
    elif goal == "oil":
        scn.extraction = Extraction(enabled=True, name="Hexane extraction",
                                    disruption_elec_kwh_per_kg=0.5, elec_kwh_per_kg=0.3,
                                    heat_mj_per_kg=1.5, solvent_name="Hexane",
                                    solvent_kg_per_kg=3.0, solvent_recovery=0.995,
                                    solvent_price=1.5, solvent_gwp=0.9, solvent_ced=55.0,
                                    capex_per_kgyr=1.0)
        scn.products = [Product("Oil", "lipid", recovery=0.9, price=5.0, is_main=True),
                        Product("Protein meal", "protein", recovery=0.8, price=0.6),
                        Product("Residual biomass", "residual", recovery=1.0, price=0.1)]
    elif goal == "pigment":
        scn.extraction = Extraction(enabled=True, name="Extraction + purification",
                                    disruption_elec_kwh_per_kg=1.0, elec_kwh_per_kg=2.0,
                                    heat_mj_per_kg=3.0, capex_per_kgyr=15.0)
        scn.products = [Product("Pigment", "custom", yield_override=0.06, price=250.0, is_main=True),
                        Product("Spent biomass", "custom", yield_override=0.9, price=1.0)]
    elif goal == "biofuel":
        scn.extraction = Extraction(enabled=True, name="Extraction + transesterification",
                                    disruption_elec_kwh_per_kg=0.1, elec_kwh_per_kg=0.1,
                                    heat_mj_per_kg=0.6, solvent_name="Hexane",
                                    solvent_kg_per_kg=2.0, solvent_recovery=0.995,
                                    solvent_price=2.0, solvent_gwp=0.9, solvent_ced=55.0,
                                    capex_per_kgyr=0.03)
        scn.products = [Product("Biodiesel (FAME)", "custom", yield_override=0.31, price=1.0, is_main=True),
                        Product("Glycerol", "custom", yield_override=0.03, price=0.4),
                        Product("Residual", "custom", yield_override=0.6, price=0.05)]


def set_scale_from_target(scn: Scenario, target_t_yr: float) -> None:
    """Size the plant so it makes ``target_t_yr`` of the main product (or biomass)."""
    mp = main_product(scn)
    yld = max(product_yield(scn, mp) if mp else 1.0, 1e-6)
    biomass_kg = target_t_yr * 1000.0 / yld
    gross = biomass_kg / max(scn.harvesting.recovery, 1e-6)
    sys = scn.system
    if scn.batch_mode and scn.batch_cycle_time_h > 0:
        batches = sys.operating_days * 24.0 / scn.batch_cycle_time_h
        scn.batch_size_kg = gross / max(batches, 1e-6)
    elif sys.basis == Basis.AREA:
        scn.scale = gross / max(sys.productivity * sys.operating_days / 1000.0, 1e-9)
    else:
        scn.scale = gross / max(sys.productivity * sys.operating_days, 1e-9)


@dataclass
class Template:
    name: str
    goal: str
    description: str
    validation: str                       # what it was validated against
    build: Callable[[Library], Scenario]


def _biomass_food(lib: Library) -> Scenario:
    sysm = lib.systems["Open raceway pond"]
    return Scenario(
        organism=lib.organisms["Chlorella vulgaris"], system=sysm,
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=100_000.0, materials=list(sysm.materials), product_price=8.0,
    )


def _scp_protein(lib: Library) -> Scenario:
    return Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"], economics=lib.economics, lcia=lib.lcia,
        scale=200_000.0, product_price=8.0,
    )


def _omega3(lib: Library) -> Scenario:
    system = replace(lib.systems["Stirred-tank fermenter (heterotrophic)"],
                     substrate_yield=0.35, elec_kwh_per_kg=2.6, operating_days=330.0,
                     materials=[], utilities=[])
    economics = replace(lib.economics, labor_cost_per_year=11_500_000.0)
    ext = Extraction(enabled=True, name="Hexane extraction + refining",
                     disruption_elec_kwh_per_kg=1.2, elec_kwh_per_kg=0.6, heat_mj_per_kg=1.5,
                     solvent_name="Hexane", solvent_kg_per_kg=3.0, solvent_recovery=0.999,
                     solvent_price=1.5, solvent_gwp=0.9, solvent_ced=55.0, capex_per_kgyr=1.0)
    products = [Product("Omega-3 oil", "lipid", recovery=0.70, price=30.0, is_main=True),
                Product("Protein meal", "protein", recovery=0.80, price=0.15),
                Product("Residual biomass", "residual", recovery=1.0, price=0.05)]
    return Scenario(organism=lib.organisms["Schizochytrium sp."], system=system,
                    harvesting=lib.harvesting["Centrifugation only"],
                    drying=lib.drying["No drying (wet paste)"], economics=economics, lcia=lib.lcia,
                    scale=2000.0, extraction=ext, products=products,
                    batch_mode=True, batch_size_kg=25_000.0, batch_cycle_time_h=24.0)


def _heterotrophic_powder(lib: Library) -> Scenario:
    system = replace(lib.systems["Stirred-tank fermenter (heterotrophic)"], capex_per_unit=10_000.0)
    economics = replace(lib.economics, labor_cost_per_year=743_000.0, substrate_price=0.65)
    return Scenario(organism=lib.organisms["Schizochytrium sp."], system=system,
                    harvesting=lib.harvesting["Settling + centrifugation"],
                    drying=lib.drying["Spray drying"], economics=economics, lcia=lib.lcia,
                    scale=150.0, materials=list(system.materials), utilities=list(system.utilities),
                    product_price=20.0)


def _algal_oil(lib: Library) -> Scenario:
    system = replace(lib.systems["Open raceway pond"], capex_per_unit=2.0,
                     water_m3_per_kg=0.08, elec_kwh_per_kg=0.15)
    economics = replace(lib.economics, labor_cost_per_year=5_500_000.0,
                        harvest_capex_per_kgyr=0.05, drying_capex_per_kgyr=0.0,
                        nitrogen_price=0.9, water_price=1.0, co2_price=0.0,
                        electricity_price=0.10, land_price=0.5, overhead_frac=0.05)
    ext = Extraction(enabled=True, name="Hexane extraction",
                     disruption_elec_kwh_per_kg=0.1, elec_kwh_per_kg=0.1, heat_mj_per_kg=0.5,
                     solvent_name="Hexane", solvent_kg_per_kg=2.0, solvent_recovery=0.995,
                     solvent_price=2.0, solvent_gwp=0.9, solvent_ced=55.0, capex_per_kgyr=0.02)
    products = [Product("Algal oil", "lipid", recovery=0.90, price=1.80, is_main=True),
                Product("Protein for feed", "protein", recovery=0.75, price=0.181),
                Product("Residual biomass", "residual", recovery=1.0, price=0.05)]
    return Scenario(organism=lib.organisms["Nannochloropsis sp."], system=system,
                    harvesting=lib.harvesting["Membrane filtration"],
                    drying=lib.drying["No drying (wet paste)"], economics=economics, lcia=lib.lcia,
                    scale=35_000_000.0, extraction=ext, products=products,
                    materials=[Material("Flocculant", 0.005, 1.0, 1.5, 25.0)],
                    credits_per_year=16_000_000.0)


def _phycocyanin(lib: Library) -> Scenario:
    ext = Extraction(enabled=True, name="Extraction + chromatographic purification",
                     disruption_elec_kwh_per_kg=1.0, elec_kwh_per_kg=2.0, heat_mj_per_kg=3.0,
                     solvent_name="Water/buffer", solvent_kg_per_kg=0.0, solvent_recovery=1.0,
                     capex_per_kgyr=15.0)
    products = [Product("C-phycocyanin (food grade)", "custom", yield_override=0.06, price=250.0, is_main=True),
                Product("Spent biomass (protein)", "custom", yield_override=0.90, price=1.0)]
    economics = replace(lib.economics, labor_cost_per_year=500_000.0)
    return Scenario(organism=lib.organisms["Arthrospira platensis (Spirulina)"],
                    system=lib.systems["Open raceway pond"],
                    harvesting=lib.harvesting["Membrane filtration"],
                    drying=lib.drying["No drying (wet paste)"], economics=economics, lcia=lib.lcia,
                    scale=8000.0, extraction=ext, products=products)


def _astaxanthin(lib: Library) -> Scenario:
    ext = Extraction(enabled=True, name="Cyst disruption + astaxanthin extraction",
                     disruption_elec_kwh_per_kg=3.0, elec_kwh_per_kg=2.0, heat_mj_per_kg=2.0,
                     solvent_name="Ethanol/CO2", solvent_kg_per_kg=1.0, solvent_recovery=0.98,
                     solvent_price=1.0, solvent_gwp=1.0, solvent_ced=30.0, capex_per_kgyr=10.0)
    products = [Product("Astaxanthin", "custom", yield_override=0.025, price=1000.0, is_main=True),
                Product("Spent biomass", "custom", yield_override=0.95, price=0.3)]
    economics = replace(lib.economics, labor_cost_per_year=300_000.0)
    return Scenario(organism=lib.organisms["Haematococcus pluvialis"],
                    system=lib.systems["Flat-panel photobioreactor"],
                    harvesting=lib.harvesting["Settling + centrifugation"],
                    drying=lib.drying["No drying (wet paste)"], economics=economics, lcia=lib.lcia,
                    scale=4000.0, extraction=ext, products=products)


def _biodiesel(lib: Library) -> Scenario:
    system = replace(lib.systems["Open raceway pond"], capex_per_unit=2.0, water_m3_per_kg=0.08,
                     elec_kwh_per_kg=0.15, productivity=25.0)
    economics = replace(lib.economics, labor_cost_per_year=5_000_000.0,
                        harvest_capex_per_kgyr=0.05, drying_capex_per_kgyr=0.0,
                        nitrogen_price=0.9, water_price=1.0, co2_price=0.0,
                        electricity_price=0.10, land_price=0.5, overhead_frac=0.05)
    ext = Extraction(enabled=True, name="Extraction + transesterification",
                     disruption_elec_kwh_per_kg=0.1, elec_kwh_per_kg=0.1, heat_mj_per_kg=0.6,
                     solvent_name="Hexane", solvent_kg_per_kg=2.0, solvent_recovery=0.995,
                     solvent_price=2.0, solvent_gwp=0.9, solvent_ced=55.0, capex_per_kgyr=0.03)
    products = [Product("Biodiesel (FAME)", "custom", yield_override=0.31, price=1.0, is_main=True),
                Product("Glycerol", "custom", yield_override=0.03, price=0.4),
                Product("Residual (feed/AD)", "custom", yield_override=0.6, price=0.05)]
    return Scenario(organism=lib.organisms["Nannochloropsis sp."], system=system,
                    harvesting=lib.harvesting["Membrane filtration"],
                    drying=lib.drying["No drying (wet paste)"], economics=economics, lcia=lib.lcia,
                    scale=40_000_000.0, extraction=ext, products=products,
                    materials=[Material("Methanol", 0.04, 0.4, 0.8, 35.0)],
                    credits_per_year=10_000_000.0)


TEMPLATES: list[Template] = [
    Template("Whole biomass — food (Chlorella, raceway)", "biomass",
             "Spray-dried whole biomass for food/feed.", "open-literature benchmarks", _biomass_food),
    Template("Single-cell protein (Chlorella, raceway)", "protein",
             "Whole high-protein biomass as a protein source.",
             "SCP TEA 5.5-6.1 EUR/kg; 22-44 t protein/ha/yr", _scp_protein),
    Template("Omega-3 oil (heterotrophic fermentation)", "oil",
             "Glucose-fed fermentation, extraction and refining to omega-3 oil.",
             "SuperPro/INTELLIGEN, unit cost +6%", _omega3),
    Template("Heterotrophic microalgae powder", "biomass",
             "Sterile fed-batch fermentation to dry powder.",
             "SuperPro, unit cost +5%", _heterotrophic_powder),
    Template("Algal-oil biorefinery (phototrophic)", "oil",
             "Large open ponds, extraction to oil + protein co-product.",
             "SuperPro EER, unit cost +1%", _algal_oil),
    Template("C-phycocyanin (Spirulina)", "pigment",
             "Blue pigment extraction and purification from Spirulina.",
             "van der Walt 2025, EUR 283-544/kg", _phycocyanin),
    Template("Astaxanthin (Haematococcus)", "pigment",
             "Carotenoid from Haematococcus in a flat-panel PBR.",
             "Panis & Carreon 2016, ~$718/kg", _astaxanthin),
    Template("Biodiesel (Nannochloropsis)", "biofuel",
             "Large open-pond biofuel with transesterification.",
             "NREL $0.42-0.97/L; MDSP < $1.85/L", _biodiesel),
]


def template_names() -> list[str]:
    return [t.name for t in TEMPLATES]


def get_template(name: str) -> Template | None:
    return next((t for t in TEMPLATES if t.name == name), None)


def build_template(name: str, lib: Library | None = None) -> Scenario:
    tpl = get_template(name)
    if tpl is None:
        raise KeyError(name)
    return tpl.build(lib or load_library())
