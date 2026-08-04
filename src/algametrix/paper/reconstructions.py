"""Engine scenarios that reconstruct a source study's foreground.

A study is *executable* only if a builder is registered here. The registry is
deliberately explicit: a study record may claim Tier B, but if no builder exists
the study cannot enter any analysis that requires running the engine, and
:mod:`algametrix.paper.studies` will say so rather than substituting a
similar scenario.

Provenance of each builder is recorded in :data:`BUILDER_PROVENANCE` so a reader
can see where the scenario definition came from.

.. note::
   Five builders (``tredici2016``, ``vazquez2022``, ``iceland_spirulina``,
   ``spiralg2019``, ``mckuin_schizo``) existed only on the feature branch
   ``m2-harmonization`` (PR #1), which was never merged into ``main`` even though
   their *outputs* were copied onto ``main`` as files. They are ported here
   verbatim from that branch rather than re-derived, so their numbers remain the
   published ones. See ``docs/STUDY_SELECTION.md``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Callable

from ..library import Library, load_library
from ..models import (
    Basis,
    CarbonSource,
    CultivationSystem,
    Drying,
    Economics,
    Harvesting,
    LCIAFactors,
    Organism,
    Scenario,
    TrophicMode,
)
from ..templates import build_template
from .basis import LIBRARY_PRICE_BASIS, PriceBasis

#: builder name -> callable(Library) -> Scenario
Builder = Callable[[Library], Scenario]

_REGISTRY: dict[str, Builder] = {}
BUILDER_PROVENANCE: dict[str, str] = {}

#: builder name -> the currency and price year of the price set it is run with.
#: See :mod:`algametrix.paper.basis`: the engine returns a cost in the
#: unit of the prices it was fed, so this is what makes an engine output
#: comparable with a published number rather than merely numerically similar.
BUILDER_PRICE_BASIS: dict[str, PriceBasis] = {}


def register(name: str, provenance: str, basis: PriceBasis = LIBRARY_PRICE_BASIS):
    def deco(fn: Builder) -> Builder:
        _REGISTRY[name] = fn
        BUILDER_PROVENANCE[name] = provenance
        BUILDER_PRICE_BASIS[name] = basis
        return fn
    return deco


# --------------------------------------------------------------------------
# Price bases of the template-backed builders
# --------------------------------------------------------------------------
# The three SuperPro/vendor cases are calibrated against sources denominated in
# US dollars, and the calibration was done by typing the source's own prices into
# the template - see data/reference_superpro_*.csv, whose column names say `_eur_`
# while their own header line says "Values in USD". Those templates therefore
# return a cost in USD, not in EUR. What each one leaves at the shipped library
# default is listed, because that is the part of the price set that is *not* in
# the declared currency and that :func:`build_in_basis` exists to bound.

_USD_2022_RUSSO = PriceBasis(
    currency="USD", price_year=2022, kind="mixed_price_set",
    provenance=("substrate and labour prices as published by Russo et al. (2022), "
                "USD 2022 (data/reference_superpro_heterotrophic.csv)"),
    library_priced=("electricity_price", "heat_price", "co2_price", "nitrogen_price",
                    "phosphorus_price", "water_price", "land_price",
                    "harvest_capex_per_kgyr", "drying_capex_per_kgyr"),
)

_USD_2021_OMEGA3 = PriceBasis(
    currency="USD", price_year=2021, kind="mixed_price_set",
    provenance=("labour and product prices from the Intelligen omega-3 case, USD 2021 "
                "(data/reference_superpro_omega3.csv header)"),
    library_priced=("electricity_price", "heat_price", "co2_price", "nitrogen_price",
                    "phosphorus_price", "water_price", "substrate_price", "land_price",
                    "harvest_capex_per_kgyr", "drying_capex_per_kgyr"),
)

_USD_2015_ALGALOIL = PriceBasis(
    currency="USD", price_year=2015, kind="mixed_price_set",
    provenance=("electricity, nitrogen, water, CO2, land, labour and the harvest/drying "
                "capital factors from the Intelligen algal-oil case, USD 2015 "
                "(data/reference_superpro_phototrophic.csv header)"),
    library_priced=("heat_price", "bicarbonate_price", "phosphorus_price",
                    "substrate_price"),
)


# --------------------------------------------------------------------------
# Builders backed by the shipped templates
# --------------------------------------------------------------------------

@register("scp_protein", "templates.TEMPLATES 'Single-cell protein (Chlorella, raceway)'")
def _scp_protein(lib: Library) -> Scenario:
    return build_template("Single-cell protein (Chlorella, raceway)", lib)


@register("heterotrophic_powder", "templates.TEMPLATES 'Heterotrophic microalgae powder'",
          basis=_USD_2022_RUSSO)
def _heterotrophic_powder(lib: Library) -> Scenario:
    return build_template("Heterotrophic microalgae powder", lib)


@register("omega3", "templates.TEMPLATES 'Omega-3 oil (heterotrophic fermentation)'",
          basis=_USD_2021_OMEGA3)
def _omega3(lib: Library) -> Scenario:
    return build_template("Omega-3 oil (heterotrophic fermentation)", lib)


@register("algal_oil", "templates.TEMPLATES 'Algal-oil biorefinery (phototrophic)'",
          basis=_USD_2015_ALGALOIL)
def _algal_oil(lib: Library) -> Scenario:
    return build_template("Algal-oil biorefinery (phototrophic)", lib)


@register("phycocyanin", "templates.TEMPLATES 'C-phycocyanin (Spirulina)'")
def _phycocyanin(lib: Library) -> Scenario:
    """Shipped template, *not* a reconstruction of van der Walt et al. (2025).

    Every price except labour is a library default, so the output is in the
    library basis whatever currency the source envelope is quoted in.
    """
    return build_template("C-phycocyanin (Spirulina)", lib)


@register("astaxanthin", "templates.TEMPLATES 'Astaxanthin (Haematococcus)'")
def _astaxanthin(lib: Library) -> Scenario:
    """Shipped template, not a reconstruction of Panis & Carreon (2016).

    Library price set; the source envelope is in USD, so the comparison needs a
    currency step and therefore the source's price year.
    """
    return build_template("Astaxanthin (Haematococcus)", lib)


# --------------------------------------------------------------------------
# Builder lifted verbatim from an example script
# --------------------------------------------------------------------------

@register(
    "spirulina_padi",
    "examples/spirulina_foodgrade.py:reproduce_padi_2023 (Padi et al. 2023 Scenario I); "
    "the bicarbonate raceway system itself is data/systems.yaml "
    "'Open raceway pond (Spirulina, NaHCO3)', calibrated to the same paper",
    basis=PriceBasis(
        currency="EUR", price_year=None, kind="mixed_price_set",
        provenance="salt-based N/P prices and labour from Padi et al. (2023), EUR",
        library_priced=("electricity_price", "heat_price", "bicarbonate_price",
                        "water_price", "land_price", "harvest_capex_per_kgyr",
                        "drying_capex_per_kgyr"),
        notes="the source's price year is not recorded, so no price-year alignment "
              "with the library defaults can be demonstrated",
    ),
)
def _spirulina_padi(lib: Library) -> Scenario:
    """Padi et al. (2023) Scenario I: dried spirulina food product, ~1 t MA/d.

    Financial basis as published: 20-yr straight-line depreciation, 1% maintenance,
    0.6% insurance, civil-works installation factor, salt-based effective N/P prices,
    26.5% corporate tax.
    """
    eco = replace(
        lib.economics,
        depreciation_years=20.0,
        maintenance_frac=0.01,
        insurance_frac=0.006,
        installation_factor=1.5,
        tax_rate=0.265,
        nitrogen_price=4.8,
        phosphorus_price=8.0,
        labor_cost_per_year=500_000.0,
    )
    return Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"],
        system=lib.systems["Open raceway pond (Spirulina, NaHCO3)"],
        harvesting=lib.harvesting["Vibrating screen filter"],
        drying=lib.drying["Spray drying"],
        economics=eco,
        lcia=lib.lcia,
        scale=116_000.0,
        product_price=65.0,
    )


# --------------------------------------------------------------------------
# Builders recovered from the unmerged `m2-harmonization` branch
# --------------------------------------------------------------------------
# These five scenarios existed only on a feature branch (PR #1) that was never
# merged into main, while their *outputs* were copied onto main as files. They
# are ported here verbatim from
# `m2-harmonization:src/algametrix/reference_studies.py`, so the numbers
# they produce are the published ones, not values fitted to a known answer.
#
# Each carries the study's own electricity characterization factor, which is what
# makes the native-background / common-background comparison meaningful.

#: Minimal LCIA used by the branch for TEA-only reproductions. The values do not
#: affect a production cost; the grid factor is overridden per study.
_TEA_ONLY_LCIA = LCIAFactors(
    elec_gwp=0.3, elec_ced=9.0, elec_water=0.0, heat_gwp=0.07, heat_ced=1.1,
    nitrogen_gwp=5.0, nitrogen_ced=45.0, phosphorus_gwp=2.0, phosphorus_ced=20.0,
    co2_supply_gwp=0.1, substrate_gwp=0.8, substrate_ced=15.0,
)

_BRANCH = ("ported from m2-harmonization:src/algametrix/reference_studies.py"
           " (branch never merged into main)")


@register("tredici2016", f"{_BRANCH}:_build_tredici2016",
          basis=PriceBasis(
              currency="EUR", price_year=2016, kind="source_price_set",
              provenance="every price fed as published by Tredici et al. (2016), EUR 2016",
          ))
def _tredici2016(lib: Library) -> Scenario:
    """Tredici et al. 2016 - T. suecica, 1-ha GWP-II flat-panel PBR, Tuscany.

    Bottom-up TEA fed as published; the production cost is an emergent output.
    Native grid: Italy 2016, 0.34 kg CO2-eq/kWh.
    """
    organism = Organism(
        "Tetraselmis suecica", "microalga",
        protein=0.45, lipid=0.20, carbohydrate=0.27, ash=0.08,
        carbon=0.50, nitrogen=0.07, phosphorus=0.007,
    )
    system = CultivationSystem(
        "GWP-II flat panel", TrophicMode.PHOTOTROPHIC, Basis.AREA,
        productivity=15.0, operating_days=240.0, biomass_conc=1.0,
        elec_kwh_per_kg=214_434 / 36_000.0,          # 37,526 EUR / 0.175 EUR/kWh
        co2_utilization=0.9, nutrient_uptake=1.0,
        water_m3_per_kg=0.0, substrate_yield=0.0,    # seawater / flue gas, not charged
        capex_per_unit=1_345_497 / 10_000.0,         # direct equipment (TDC) / land area
        land_m2_per_unit=1.0, carbon_source=CarbonSource.CO2,
    )
    economics = Economics(
        electricity_price=0.175, heat_price=0.03, co2_price=0.0,
        nitrogen_price=6120 / 2520.0, phosphorus_price=1500 / 252.0,
        water_price=0.0, substrate_price=0.0, land_price=10.0,
        harvest_capex_per_kgyr=0.0, drying_capex_per_kgyr=0.0,
        installation_factor=1.0, indirect_factor=0.1607,     # indirect 216,280 / TDC
        labor_cost_per_year=179_400.0, maintenance_frac=0.05, overhead_frac=0.20,
        discount_rate=0.05, plant_lifetime=25.0,
        depreciation_years=25.0, insurance_frac=0.01,
        working_capital_frac=0.0, startup_frac=0.0,
    )
    return Scenario(
        organism=organism, system=system,
        harvesting=Harvesting("Centrifuge (Westfalia)", recovery=1.0,
                              elec_kwh_per_kg=0.0, final_solids=0.20),
        drying=Drying("Wet paste (no drying)", enabled=False, final_solids=0.20,
                      thermal_mj_per_kg_water=0.0),
        economics=economics, lcia=replace(_TEA_ONLY_LCIA, elec_gwp=0.34),
        scale=10_000.0,
        other_opex_per_year=6_980.0,   # consumables (probes, filter cartridges)
    )


@register("vazquez2022", f"{_BRANCH}:_build_vazquez2022",
          basis=PriceBasis(
              currency="EUR", price_year=2021, kind="source_price_set",
              provenance="every price fed as published by Vazquez-Romero et al. (2022), "
                         "EUR 2021",
          ))
def _vazquez2022(lib: Library) -> Scenario:
    """Vazquez-Romero et al. 2022 - P. tricornutum, 1-ha tubular PBR + LED, Norway.

    Artificial-light dominated (141.6 kWh/kg). Native grid: Norwegian hydro,
    0.019 kg CO2-eq/kWh - the clean-grid case.
    """
    organism = Organism(
        "Phaeodactylum tricornutum", "microalga",
        protein=0.439, lipid=0.1258, carbohydrate=0.267, ash=0.141,
        carbon=0.524, nitrogen=0.092, phosphorus=0.0128,
    )
    system = CultivationSystem(
        "Tubular PBR (Norway, LED)", TrophicMode.PHOTOTROPHIC, Basis.AREA,
        productivity=29_480 / (10_000 * 300 / 1000.0), operating_days=300.0,
        biomass_conc=1.0,
        elec_kwh_per_kg=141.59,                      # LED-dominated
        co2_utilization=0.9, nutrient_uptake=1.0,
        water_m3_per_kg=0.0, substrate_yield=0.0,
        capex_per_unit=3_935_850 / 10_000.0,         # major equipment cost / area
        land_m2_per_unit=0.0, carbon_source=CarbonSource.CO2,
    )
    paper_opex = 2_228_066.0
    economics = Economics(
        electricity_price=0.093, heat_price=0.0158, co2_price=0.0,
        nitrogen_price=1.0, phosphorus_price=3.0, water_price=0.0, substrate_price=0.0,
        land_price=0.0, harvest_capex_per_kgyr=0.0, drying_capex_per_kgyr=0.0,
        installation_factor=1.0, indirect_factor=2.087,   # investment 12.15 M / MEC - 1
        labor_cost_per_year=0.3879 * paper_opex, maintenance_frac=0.05, overhead_frac=0.15,
        discount_rate=0.07, plant_lifetime=15.0,
        depreciation_years=15.0, insurance_frac=0.0,
        working_capital_frac=0.0, startup_frac=0.0,
    )
    # thermal utilities + consumables + wastewater, as published shares of OPEX
    other_opex = (0.0863 + 0.0055 + 0.0031) * paper_opex
    return Scenario(
        organism=organism, system=system,
        harvesting=Harvesting("Centrifuge (SPT/disc)", recovery=1.0,
                              elec_kwh_per_kg=0.0, final_solids=0.20),
        drying=Drying("Wet paste (no drying)", enabled=False, final_solids=0.20,
                      thermal_mj_per_kg_water=0.0),
        economics=economics, lcia=replace(_TEA_ONLY_LCIA, elec_gwp=0.019),
        scale=10_000.0, other_opex_per_year=other_opex,
    )


@register("iceland_spirulina", f"{_BRANCH}:_build_iceland_spirulina")
def _iceland_spirulina(lib: Library) -> Scenario:
    """Hellisheidi/VAXA geothermal Spirulina - LED PBR on a geothermal grid.

    Compared per kg DRY on an operational basis: the paper's headline is per kg
    wet and includes construction, which this engine does not model. Native grid:
    0.0084 kg CO2-eq/kWh; CO2 is a geothermal by-product (supply burden 0).
    """
    organism = replace(lib.organisms["Arthrospira platensis (Spirulina)"], carbon=0.46)
    system = replace(
        lib.systems["Flat-panel photobioreactor"],
        elec_kwh_per_kg=139.7,               # paper total electricity, LED-dominated
        cultivation_heat_mj_per_kg=0.0,      # geothermal waste heat
        carbon_source=CarbonSource.CO2,
    )
    lcia = replace(lib.lcia, elec_gwp=0.0084, co2_supply_gwp=0.0,
                   nitrogen_gwp=0.05, phosphorus_gwp=0.05, heat_gwp=0.0)
    return Scenario(
        organism=organism, system=system,
        harvesting=replace(lib.harvesting["Vibrating screen filter"], elec_kwh_per_kg=0.0),
        drying=lib.drying["No drying (wet paste)"],
        economics=lib.economics, lcia=lcia, scale=100_000.0, product_price=15.0,
    )


@register("spiralg2019", f"{_BRANCH}:_build_spiralg2019")
def _spiralg2019(lib: Library) -> Scenario:
    """SpiralG pilot Spirulina biorefinery, subsystem S1, 2019 inventory.

    Published LCI (Zenodo 17311472), Brightway2 / ecoinvent 3.6. Native grid:
    Italian pilot, 0.43 kg CO2-eq/kWh. No biogenic credit, as published.
    """
    system = replace(lib.systems["Open raceway pond (Spirulina, NaHCO3)"],
                     co2_utilization=0.85, cultivation_heat_mj_per_kg=0.0,
                     elec_kwh_per_kg=16.2)
    lcia = replace(lib.lcia, elec_gwp=0.43, bicarbonate_gwp=0.87, nitrogen_gwp=9.6,
                   heat_gwp=0.0, count_biogenic_uptake=False)
    return Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"], system=system,
        harvesting=replace(lib.harvesting["Vibrating screen filter"], elec_kwh_per_kg=0.0),
        drying=lib.drying["No drying (wet paste)"],
        economics=lib.economics, lcia=lcia, scale=100_000.0, product_price=15.0,
    )


@register("mckuin_schizo", f"{_BRANCH}:_build_mckuin_schizo",
          basis=PriceBasis(
              currency="USD", price_year=None, kind="mixed_price_set",
              provenance="substrate price from McKuin et al. (2022), USD; the labour "
                         "figure is carried over from the heterotrophic template and is "
                         "not the source's",
              library_priced=("electricity_price", "heat_price", "nitrogen_price",
                              "phosphorus_price", "water_price"),
              notes="GWP-only comparison: no economic value from this source enters any "
                    "cost statistic, so the basis is recorded but never exercised",
          ))
def _mckuin_schizo(lib: Library) -> Scenario:
    """McKuin et al. 2022 - whole-cell Schizochytrium in a sugar-biorefinery context.

    Sugarcane sucrose (0.45 kg CO2-eq/kg) and bagasse electricity (0.05
    kg CO2-eq/kWh); yeast extract and sterilization steam removed because the
    published system is bagasse-powered. Distinct from the `heterotrophic_powder`
    builder, which reconstructs Russo et al. (2022) on grid power and corn glucose.
    """
    system = replace(lib.systems["Stirred-tank fermenter (heterotrophic)"],
                     capex_per_unit=10_000.0)
    lcia = replace(lib.lcia, substrate_gwp=0.45, elec_gwp=0.05, heat_gwp=0.01)
    economics = replace(lib.economics, labor_cost_per_year=743_000.0, substrate_price=0.4)
    return Scenario(
        organism=lib.organisms["Schizochytrium sp."], system=system,
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=economics, lcia=lcia, scale=150.0,
        materials=[m for m in system.materials if "yeast" not in m.name.lower()],
        utilities=[u for u in system.utilities if "steril" not in u.name.lower()],
        product_price=20.0,
    )


# --------------------------------------------------------------------------
# Vazquez-Romero et al. (2022), Sci. Total Environ. 837:155742 - open access
# --------------------------------------------------------------------------
# Added to widen the matched cohort, which previously rested on two external
# primary studies, one self-citation and one benchmark with no primary source.
#
# This paper is reconstructable to an unusual degree because it is CC-BY and its
# supplementary material publishes the whole financial convention, not just the
# answer:
#
#   CAPEX   Lang factors on the major equipment cost (MEC): installation 20%,
#           instrumentation 15%, piping 20%, electrical 10%, buildings 23%,
#           land improvements 12%, service facilities 20%  ->  DC = 2.20 MEC
#           indirect = 10% DC + 30% MEC                     ->  IC = 0.52 MEC
#           contractor 5% DC + contingency 15% (DC+IC)      ->  OC = 0.518 MEC
#           total investment = DC+IC+OC = 3.238 MEC
#   annual  depreciation (DC+IC+OC)/15 yr; interest 8% of depreciation;
#           property tax 1% and insurance 0.6% of (depreciation + interest);
#           land 1184 EUR/ha/yr
#   OPEX    maintenance 4% MEC; overheads 55% of (labour + maintenance);
#           operating supplies 0.4% and contingencies 15% of consumables
#   prices  electricity 0.0781 EUR/kWh, natural gas 0.0225 EUR/kWh, freshwater
#           0.4728 EUR/m3, wastewater 0.639 EUR/m3, CO2 1.16 EUR/kg,
#           urea 713.69 EUR/t, triple superphosphate 1243.31 EUR/t,
#           labour 183 992 EUR/yr at 1 ha (8 operators + 1 plant manager)
#
# Reading the CAPEX chain back against the paper's own published CAPEX per kg
# reproduces it to within 0.5% for cases 1a, 1b and 3a, which is how this
# transcription is verified. The biomass cost itself is NOT used to set any
# input: it is what the reconstruction is compared against.

#: Total investment as a multiple of the major equipment cost, from the Lang
#: factors above. Used to express the paper's MEC-based fractions on the
#: engine's DFC base.
_VR_INVESTMENT_OVER_MEC = 3.238

#: Annual capital charges other than straight-line depreciation, as a fraction of
#: the total investment: interest 8% of depreciation, plus property tax 1% and
#: insurance 0.6% of (depreciation + interest). The engine has one field for
#: "capital charges that are not depreciation or maintenance", so they are summed
#: into ``insurance_frac`` and the composition is recorded here.
_VR_NON_DEPRECIATION_CAPITAL_FRAC = (
    0.08 / 15.0                       # interest
    + 0.01 * 1.08 / 15.0              # property tax
    + 0.006 * 1.08 / 15.0             # insurance
)

_VR_BASIS = PriceBasis(
    currency="EUR", price_year=2021, kind="source_price_set",
    provenance=("every price fed from Vazquez-Romero et al. (2022) supplementary "
                "tables 3, 5 and 7; the paper's own sources are dated 2021"),
    notes=("the paper corrects equipment prices for inflation to an unnamed "
           "reference year; its price sources were all retrieved in 2021"),
)


def _vr_economics(labour_per_year: float, land_ha: float) -> Economics:
    """The paper's financial conventions, expressed on the engine's bases."""
    return Economics(
        electricity_price=0.0781,
        heat_price=0.0225 / 3.6,          # 0.0225 EUR/kWh of natural gas -> EUR/MJ
        co2_price=1.16,
        nitrogen_price=713.69 / 1000.0 / 0.46,      # urea, 46% N
        phosphorus_price=1243.31 / 1000.0 / 0.196,  # triple superphosphate, ~19.6% P
        water_price=0.4728,
        substrate_price=0.0,
        land_price=0.0,                   # charged as an annual rent, see other_opex
        harvest_capex_per_kgyr=0.0,       # harvesting and drying are inside the MEC
        drying_capex_per_kgyr=0.0,
        installation_factor=2.20,         # DC / MEC
        indirect_factor=(_VR_INVESTMENT_OVER_MEC - 2.20) / 2.20,   # (IC + OC) / DC
        labor_cost_per_year=labour_per_year,
        maintenance_frac=0.04 / _VR_INVESTMENT_OVER_MEC,           # 4% of MEC, on DFC
        overhead_frac=0.55,               # the paper's own rate; see the note below
        discount_rate=0.08,
        plant_lifetime=15.0,
        depreciation_years=15.0,
        insurance_frac=_VR_NON_DEPRECIATION_CAPITAL_FRAC,
        working_capital_frac=0.0,
        startup_frac=0.0,
    )


def _vr_scenario(lib: Library, organism: Organism, productivity: float,
                 elec_kwh_per_kg: float, investment_eur: float, area_m2: float,
                 labour_per_year: float,
                 harvesting: Harvesting | None = None,
                 drying: Drying | None = None) -> Scenario:
    """One Vazquez-Romero case: stacked tubular PBRs, Olhao, Portugal.

    ``elec_kwh_per_kg`` is the case's ELECTRICAL energy per kg. Cases that
    freeze-dry are electric throughout, so it is the paper's whole energy figure;
    the spray-drying case carries its natural gas in the drying term instead.
    """
    system = CultivationSystem(
        "Stacked tubular PBR (Olhao, PT)", TrophicMode.PHOTOTROPHIC, Basis.AREA,
        productivity=productivity, operating_days=365.0, biomass_conc=1.0,
        elec_kwh_per_kg=elec_kwh_per_kg,
        co2_utilization=0.9, nutrient_uptake=1.0,
        water_m3_per_kg=0.0, substrate_yield=0.0,
        # The whole MEC sits on the cultivation line because the paper reports one
        # MEC for the plant; splitting it would need the per-unit table.
        capex_per_unit=investment_eur / _VR_INVESTMENT_OVER_MEC / area_m2,
        land_m2_per_unit=0.0, carbon_source=CarbonSource.CO2,
    )
    return Scenario(
        organism=organism, system=system,
        harvesting=harvesting or Harvesting("Centrifuge", recovery=1.0,
                                            elec_kwh_per_kg=0.0, final_solids=0.32),
        drying=drying or Drying("Freeze drying (electric, in the electricity term)",
                                enabled=False, final_solids=0.32,
                                thermal_mj_per_kg_water=0.0),
        economics=_vr_economics(labour_per_year, area_m2 / 10_000.0),
        # TEA-only: the source publishes no GWP and no grid factor, so none is
        # claimed here. Any GWP the engine computes for this scenario is model
        # output, classified as such by paper/gwp.py.
        lcia=_TEA_ONLY_LCIA,
        scale=area_m2,
        other_opex_per_year=1184.0 * area_m2 / 10_000.0,   # land rent
    )


@register(
    "vazquez2022b_nas",
    "Vazquez-Romero et al. 2022 (Sci. Total Environ. 837:155742) case 1b, "
    "supplementary tables 1, 3, 4, 5, 7 and 9",
    basis=_VR_BASIS,
)
def _vazquez2022b_nas(lib: Library) -> Scenario:
    """Case 1b - Nannochloropsis oceanica, 1 ha, year-round, 27.61 t/yr.

    Published biomass cost 53.32 EUR/kg; the engine is given the physical data
    and the financial conventions, never the answer.
    """
    organism = replace(
        lib.organisms["Nannochloropsis sp."],
        name="Nannochloropsis oceanica",
        protein=0.453, lipid=0.115, carbohydrate=0.245, ash=0.187,
        nitrogen=0.453 / 6.25,       # Jones factor on the published protein content
    )
    return _vr_scenario(
        lib, organism,
        productivity=27_610.0 * 1000.0 / (10_000.0 * 365.0),   # 7.56 g/m2/d
        elec_kwh_per_kg=50.82,
        investment_eur=8.23e6, area_m2=10_000.0, labour_per_year=183_992.0,
    )


@register(
    "vazquez2022b_tiso_pht",
    "Vazquez-Romero et al. 2022 (Sci. Total Environ. 837:155742) case 1a, "
    "supplementary tables 1, 3, 4, 5, 7 and 9",
    basis=_VR_BASIS,
)
def _vazquez2022b_tiso_pht(lib: Library) -> Scenario:
    """Case 1a - Phaeodactylum tricornutum and Tisochrysis lutea alternating.

    Six months of each strain per year. The engine models one organism, so the
    composition is the unweighted mean of the two published compositions - the
    two seasons are of equal length. Published biomass cost 105.19 EUR/kg.
    """
    organism = Organism(
        "P. tricornutum / T. lutea (alternating)", "microalga",
        protein=(0.5423 + 0.5377) / 2, lipid=(0.2083 + 0.1463) / 2,
        carbohydrate=(0.15 + 0.188) / 2, ash=(0.0995 + 0.128) / 2,
        carbon=0.52, nitrogen=((0.5423 + 0.5377) / 2) / 6.25, phosphorus=0.0128,
    )
    return _vr_scenario(
        lib, organism,
        productivity=12_940.0 * 1000.0 / (10_000.0 * 365.0),    # 3.55 g/m2/d
        elec_kwh_per_kg=131.30,
        investment_eur=7.72e6, area_m2=10_000.0, labour_per_year=183_992.0,
    )


@register(
    "vazquez2022b_nas_10ha",
    "Vazquez-Romero et al. 2022 (Sci. Total Environ. 837:155742) case 4a, "
    "supplementary tables 1, 3, 4, 5, 7 and 9",
    basis=_VR_BASIS,
)
def _vazquez2022b_nas_10ha(lib: Library) -> Scenario:
    """Case 4a - N. oceanica, 10 ha, ultrafiltration + spray drying, fertilisers.

    The best-matched case in the paper for this engine: it is the one that buys
    urea and triple superphosphate rather than a commercial nutrient solution, so
    the engine's own nitrogen and phosphorus terms are priced with the source's
    own prices and carry no medium bias. Published biomass cost 36.21 EUR/kg.

    Energy split: the paper reports 62.71 kWh/kg total. Spray drying accounts for
    36.45 kWh/kg and is supplied by natural gas at 80% efficiency from steam;
    the remaining 26.26 kWh/kg is electricity. Ultrafiltration concentrates the
    biomass to 5.21% DW, from which the water the dryer removes follows.
    """
    organism = replace(
        lib.organisms["Nannochloropsis sp."],
        name="Nannochloropsis oceanica",
        protein=0.453, lipid=0.115, carbohydrate=0.245, ash=0.187,
        nitrogen=0.453 / 6.25,
    )
    water_per_kg_product = 1.0 / 0.0521 - 1.0 / 0.95      # UF paste -> 95% DW powder
    return _vr_scenario(
        lib, organism,
        productivity=300_100.0 * 1000.0 / (100_000.0 * 365.0),   # 8.22 g/m2/d
        elec_kwh_per_kg=62.71 - 36.45,
        investment_eur=81.61e6, area_m2=100_000.0, labour_per_year=341_996.0,
        harvesting=Harvesting("Ultrafiltration", recovery=1.0, elec_kwh_per_kg=0.0,
                              final_solids=0.0521),
        drying=Drying("Spray drying (natural gas)", enabled=True, final_solids=0.95,
                      thermal_mj_per_kg_water=36.45 * 3.6 / water_per_kg_product),
    )


# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------

#: Tier-B studies whose scenario definition is absent from the repository.
#: Kept as data so reports and tests can name them instead of silently omitting
#: them. Empty since the five branch builders were recovered.
MISSING_SCENARIOS: dict[str, str] = {}


def available() -> list[str]:
    return sorted(_REGISTRY)


def has_builder(name: str | None) -> bool:
    return bool(name) and name in _REGISTRY


def build(name: str, lib: Library | None = None) -> Scenario:
    """Build the scenario registered under ``name``.

    The result is deep-copied before it is returned. A :class:`Library` hands the
    *same* ``LCIAFactors`` and ``Economics`` objects to every scenario built from
    it, so without this a caller that changes, say, a carbon-accounting mode on
    one scenario would silently change it on all the others. The carbon and
    uncertainty analyses do exactly that kind of mutation.
    """
    if name not in _REGISTRY:
        raise KeyError(
            f"no scenario builder registered for {name!r}. "
            f"Available: {available()}"
        )
    return deepcopy(_REGISTRY[name](lib or load_library()))


def price_basis(name: str) -> PriceBasis:
    """Currency and price year the scenario registered under ``name`` returns."""
    if name not in BUILDER_PRICE_BASIS:
        raise KeyError(f"no price basis declared for builder {name!r}")
    return BUILDER_PRICE_BASIS[name]


def build_in_basis(name: str, lib: Library | None = None, registry=None,
                   shares=None) -> tuple[Scenario, object]:
    """Build ``name`` with the shipped default prices expressed in its own basis.

    Only meaningful for a ``mixed_price_set`` builder, where part of the price set
    is the source's own currency and part is the library's. Running the scenario
    both ways brackets the error that mixing introduces, so a deviation computed
    on a mixed basis can be reported as an interval rather than as a point that
    quietly assumes the mixing is negligible.

    Returns the scenario and the :class:`~algametrix.paper.indices.BasisTransfer`
    that moved the library defaults, so the factor is auditable.
    """
    from . import indices as _indices  # local: indices imports this module lazily

    basis = price_basis(name)
    lib = lib or load_library()
    economics, tr = _indices.convert_economics(
        lib.economics, LIBRARY_PRICE_BASIS, basis, registry, shares)
    converted = replace(lib, economics=economics)
    return deepcopy(_REGISTRY[name](converted)), tr
