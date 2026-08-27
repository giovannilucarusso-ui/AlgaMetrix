"""Dataclasses describing a production scenario.

A :class:`Scenario` is a plain, serialisable description of *what* is being
produced and *how*. It carries no calculation logic; the physics, economics and
environmental accounting live in :mod:`inventory`, :mod:`tea` and :mod:`lca`.
All units are stated explicitly in the field comments and are SI-based
(kg, m2, m3, kWh, MJ, EUR, year).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TrophicMode(str, Enum):
    """How the organism obtains carbon and energy."""

    PHOTOTROPHIC = "phototrophic"    # light + CO2 (raceway, PBR)
    HETEROTROPHIC = "heterotrophic"  # organic substrate (fermenter)


class CarbonSource(str, Enum):
    """Inorganic-carbon feed for a phototrophic culture.

    ``CO2`` is gaseous CO2 enrichment (flue gas, pure CO2). ``BICARBONATE`` is
    dissolved sodium bicarbonate (NaHCO3) — the standard carbon source for
    alkaliphilic strains such as Arthrospira (Spirulina) grown at pH 9-10.
    Ignored for heterotrophic systems (carbon comes from the substrate).
    """

    CO2 = "co2"
    BICARBONATE = "bicarbonate"


class Basis(str, Enum):
    """What the cultivation `scale` and `productivity` are expressed per."""

    AREA = "area"      # scale in m2, productivity in g/m2/day
    VOLUME = "volume"  # scale in m3, productivity in g/L/day


class CarbonAccounting(str, Enum):
    """How carbon fixed into the biomass is treated at the cradle-to-gate boundary.

    A cradle-to-gate GWP that credits the carbon locked into the biomass is only
    meaningful together with the convention that produced it: the biomass leaves
    the gate carrying that carbon, and whether it counts as a removal depends on
    what happens downstream and on the study's temporary-storage rules. The mode
    is therefore explicit, and the gross (pre-adjustment) result is always
    reported alongside the net one.

    ``NO_BIOGENIC_CREDIT``
        No adjustment. Gross == net. The conservative default for comparisons.
    ``TEMPORARY_STORAGE_CREDIT_AT_GATE``
        Credit the carbon physically incorporated into the biomass, whatever fed
        it. Represents "the product carries this much carbon out of the gate".
    ``SOURCE_SPECIFIC_CREDIT``
        Credit only carbon taken up as atmospheric/flue-gas CO2. Carbon arriving
        as a manufactured or mined reagent (NaHCO3) or as an organic substrate is
        not credited, because its production burden is already counted upstream.
        This reproduces the behaviour of earlier versions of this engine.
    ``CUSTOM``
        Credit ``custom_biogenic_credit_fraction`` of the incorporated carbon.
    """

    NO_BIOGENIC_CREDIT = "no_biogenic_credit"
    TEMPORARY_STORAGE_CREDIT_AT_GATE = "temporary_storage_credit_at_gate"
    SOURCE_SPECIFIC_CREDIT = "source_specific_credit"
    CUSTOM = "custom"


class WasteBurdenConvention(str, Enum):
    """How a waste-derived feed's upstream burden is treated.

    A culture fed on somebody else's effluent gets its nitrogen without a Haber-
    Bosch plant behind it, and that is worth a great deal to the result — which
    is exactly why the rule producing it has to be stated rather than assumed.
    The two conventions below answer different questions and are not
    interchangeable, so the choice is recorded on the scenario and reported with
    the result.

    ``CUT_OFF``
        The waste enters burden-free: its producer carries everything up to the
        point of discard, and this system carries only what it does itself —
        transport, pumping, screening. The conservative default, and the one
        that keeps a cradle-to-gate result comparable with studies that buy
        fertiliser.
    ``AVOIDED_TREATMENT``
        System expansion. The stream would otherwise have been treated and
        discharged, so the treatment this process displaces is credited. It
        makes the result a *difference between two systems* rather than the
        footprint of one, and the credit is always reported on its own line —
        never folded into the feed's own burden.
    """

    CUT_OFF = "cut_off"
    AVOIDED_TREATMENT = "avoided_treatment"


@dataclass
class WasteFeed:
    """A waste stream covering part of the culture's nutrient or carbon demand.

    Municipal and industrial effluents, and food-industry side-streams such as
    whey permeate, vinasse or potato fruit juice, arrive with nitrogen,
    phosphorus and often biodegradable organic carbon already in them. What they
    replace is the *purchase* of those inputs, not the demand for them: the
    biomass still needs the same nitrogen, and :mod:`inventory` splits the
    demand into the part the stream delivers and the part still bought.

    **One stream has one composition.** The quantity dosed is set by a single
    nutrient — ``dosed_on`` — and whatever the same quantity happens to carry of
    the others follows from it. A stream dosed on nitrogen that is rich in
    phosphorus over-delivers phosphorus, and that surplus is reported as an
    emission rather than quietly discarded, because in a real pond it is
    discharged. Choosing coverage of two nutrients independently would describe
    a stream nobody can buy.

    All ``*_per_unit`` quantities are per ``unit`` of the stream: per m3 for an
    effluent, per kg for a slurry or a solid by-product.
    """

    enabled: bool = False
    name: str = ""
    #: ``wastewater`` (municipal or industrial effluent) or ``food_byproduct``
    #: (a side-stream of food processing). Labelling only: the physics is the
    #: composition below, and the accounting is ``convention``.
    kind: str = "wastewater"
    unit: str = "m3"                     # m3 (liquid) | kg (slurry or solid)
    nitrogen_per_unit: float = 0.0       # kg N per unit of stream
    phosphorus_per_unit: float = 0.0     # kg P per unit
    #: Biodegradable organic carbon expressed as kg of the substrate the
    #: heterotrophic yield is defined on, so it enters the balance through the
    #: same ``substrate_yield`` as purchased feedstock and needs no second yield.
    substrate_per_unit: float = 0.0      # kg substrate-equivalent per unit
    #: Which demand fixes the quantity dosed: ``nitrogen`` | ``phosphorus`` |
    #: ``substrate``.
    dosed_on: str = "nitrogen"
    #: Fraction of *that* demand the stream is dosed to cover (0-1). The rest is
    #: bought. Below 1 for a stream that cannot be supplied year-round, or whose
    #: contaminant load caps how much of the culture it may make up.
    coverage: float = 1.0
    #: EUR per unit. **Negative means a gate fee**: the plant is paid to accept
    #: the stream, which is how a works treating municipal effluent earns. A
    #: wider credit for displacing a treatment plant belongs in
    #: ``Scenario.credits_per_year``, not here.
    price_per_unit: float = 0.0
    elec_kwh_per_unit: float = 0.0       # pumping, screening, mixing
    #: Handling burden the *receiving* system causes — transport, pre-treatment.
    #: Zero under a strict cut-off with the stream available at the fence line.
    gwp_per_unit: float = 0.0            # kg CO2-eq per unit
    ced_per_unit: float = 0.0            # MJ per unit
    #: Governs **both** analyses. Crediting the displaced treatment in the LCA
    #: but not in the economics would have the two describe different systems,
    #: which is the failure this engine exists to prevent: one boundary, one
    #: inventory, two contractions of it.
    convention: WasteBurdenConvention = WasteBurdenConvention.CUT_OFF
    #: Applied only under ``AVOIDED_TREATMENT`` and reported on its own line.
    #: Enter as positive numbers: the burden and the cost avoided, which the LCA
    #: and the TEA respectively subtract.
    avoided_treatment_gwp_per_unit: float = 0.0
    avoided_treatment_ced_per_unit: float = 0.0
    #: EUR per unit of what treating this stream conventionally would have cost
    #: somebody. Distinct from ``price_per_unit``, which is the fee actually
    #: invoiced: a works may be paid EUR 0.15/m3 while displacing EUR 0.30/m3 of
    #: treatment, and only the first is money that changes hands. It therefore
    #: never enters the annual operating cost, only the net cost and the profit.
    avoided_treatment_cost_per_unit: float = 0.0
    notes: str = ""                      # provenance / citation for a preset


@dataclass
class Organism:
    """A strain and its composition. Elemental fractions drive the nutrient balance."""

    name: str
    group: str                 # microalga | cyanobacterium | thraustochytrid | protist
    protein: float             # mass fraction of ash-free dry weight
    lipid: float
    carbohydrate: float
    ash: float
    carbon: float              # elemental mass fraction of dry weight
    nitrogen: float
    phosphorus: float
    notes: str = ""
    # Optional pigment fraction (mass fraction of dry weight) for pigment
    # biorefineries, e.g. C-phycocyanin in Spirulina. NB: this is a subset of the
    # protein pool, not additive to it — see products.py when modelling both.
    phycocyanin: float = 0.0


@dataclass
class CultivationSystem:
    """A reactor/pond type and its operating and cost characteristics."""

    name: str
    mode: TrophicMode
    basis: Basis
    productivity: float        # g/m2/d (area) or g/L/d (volume)
    operating_days: float      # d/yr
    biomass_conc: float        # g/L at harvest
    elec_kwh_per_kg: float     # cultivation electricity per kg dry biomass
    co2_utilization: float     # fraction of supplied inorganic carbon (CO2 or NaHCO3) fixed
    nutrient_uptake: float     # fraction of supplied N, P assimilated
    water_m3_per_kg: float     # net water consumption per kg dry biomass
    substrate_yield: float     # kg biomass / kg substrate (heterotrophic)
    capex_per_unit: float      # EUR per m2 (area) or per m3 (volume)
    land_m2_per_unit: float    # m2 land per m2 pond or per m3 reactor
    #: Fraction of the nominal reactor volume the culture occupies (headspace,
    #: foam and impeller clearance take the rest). Used by the batch sizing, which
    #: ties one batch to the reactor that holds it:
    #: ``batch_size_kg = scale x working_volume x biomass_conc``, with g/L and
    #: kg/m3 numerically equal. Continuous operation does not read it.
    working_volume: float = 0.8
    #: What the organic substrate is, and how much carbon a kilogram of it
    #: carries. Only heterotrophic systems read them. The default is glucose
    #: (C6H12O6, 6 x 12.011 / 180.156 = 0.4001 kg C/kg), which is what the
    #: carbon bookkeeping assumed for every substrate before this was a field —
    #: wrongly for glycerol (0.391), crude glycerol (~0.31), ethanol (0.521) or
    #: a wet side-stream taken at face value. It sets the respired-carbon report
    #: and the "biomass C <= substrate C" admissibility check; it does not enter
    #: any cost or impact sum, which are per kilogram of substrate.
    #:
    #: A waste-derived feed declares its organics as glucose-equivalent
    #: kilograms (see data/waste_feeds.yaml), so it stays consistent with
    #: whatever fraction the system declares.
    substrate_name: str = "glucose"
    substrate_carbon_fraction: float = 6 * 12.011 / 180.156   # kg C / kg substrate
    notes: str = ""
    # Inorganic-carbon feed for phototrophic systems (CO2 gas vs NaHCO3 solution).
    carbon_source: CarbonSource = CarbonSource.CO2
    # Optional thermal conditioning of the culture (e.g. seasonal pond/greenhouse
    # heating). Dominant hotspot for heated temperate Spirulina ponds; leave 0 for
    # warm-climate unheated systems. Fuel routes the burden like Drying.fuel.
    cultivation_heat_mj_per_kg: float = 0.0   # thermal MJ per kg dry biomass
    cultivation_heat_fuel: str = "natural_gas"  # natural_gas | electricity
    # Optional recipe travelling with the system.
    # Unquoted although Material and Utility are defined further down: with
    # `from __future__ import annotations` nothing here is evaluated at class
    # creation, and a quoted forward reference inside a subscript is what
    # Python 3.10 fails to resolve for anything reading these hints.
    materials: list[Material] = field(default_factory=list)
    utilities: list[Utility] = field(default_factory=list)
    product_price: float = 0.0   # typical EUR/kg selling price (seeds the UI)


@dataclass
class Harvesting:
    """Dewatering / concentration step."""

    name: str
    recovery: float            # fraction of biomass recovered (0-1)
    elec_kwh_per_kg: float     # per kg dry biomass entering the step
    final_solids: float        # solids fraction of the concentrate (0-1)
    notes: str = ""


@dataclass
class Drying:
    """Optional thermal drying step."""

    name: str
    enabled: bool
    final_solids: float            # solids fraction of the dried product (0-1)
    thermal_mj_per_kg_water: float # heat to evaporate 1 kg water
    elec_kwh_per_kg: float = 0.0   # per kg dry biomass
    fuel: str = "natural_gas"      # natural_gas | electricity
    notes: str = ""


@dataclass
class Material:
    """An explicit raw-material / media line item (e.g. yeast extract, hexane, nitrate).

    Complements the physics-derived flows (CO2, N, P, substrate): use it for the
    specific media components and process chemicals a real recipe needs.
    """

    name: str
    amount_per_kg: float   # kg of material per kg of dry product
    price: float           # EUR/kg
    gwp: float = 0.0        # kg CO2-eq / kg (cradle-to-gate)
    ced: float = 0.0        # MJ / kg
    # The other five impact categories. ``None`` means no factor was declared:
    # the material then contributes nothing to that category and the
    # completeness check (algametrix.lciamethod) reports it. That is not the
    # same as a declared zero, which says the burden is genuinely nil.
    water: float | None = None       # m3 / kg
    land: float | None = None        # m2*a / kg
    acid: float | None = None        # kg SO2-eq / kg
    eutroph_n: float | None = None   # kg N-eq / kg
    eutroph_p: float | None = None   # kg P-eq / kg
    notes: str = ""


@dataclass
class Utility:
    """An explicit utility line item beyond electricity and drying heat.

    e.g. sterilization steam, fermentation cooling water / chilled water.
    """

    name: str
    amount_per_kg: float   # utility units per kg of dry product
    unit: str              # "kg", "MJ", "m3", ...
    price: float           # EUR per unit
    gwp: float = 0.0        # kg CO2-eq / unit
    ced: float = 0.0        # MJ / unit
    # As for Material: ``None`` is an undeclared factor, not a zero burden.
    water: float | None = None       # m3 / unit
    land: float | None = None        # m2*a / unit
    acid: float | None = None        # kg SO2-eq / unit
    eutroph_n: float | None = None   # kg N-eq / unit
    eutroph_p: float | None = None   # kg P-eq / unit
    notes: str = ""


@dataclass
class Extraction:
    """Optional downstream: cell disruption + solvent extraction of the biomass.

    Flows are expressed per kg of dry biomass entering the step. When enabled its
    electricity, heat and net solvent make-up are added to the inventory and its
    equipment to the CAPEX. The split of the biomass into products is described by
    the :class:`Product` list on the scenario.
    """

    enabled: bool = False
    name: str = "Solvent extraction"
    disruption_elec_kwh_per_kg: float = 0.0  # cell disruption (homogeniser/bead mill)
    elec_kwh_per_kg: float = 0.0             # extraction + phase separation
    heat_mj_per_kg: float = 0.0              # solvent recovery (distillation)
    solvent_name: str = "Hexane"
    solvent_kg_per_kg: float = 0.0           # solvent contacted per kg biomass
    solvent_recovery: float = 0.95           # fraction of solvent recycled
    solvent_price: float = 0.0               # EUR/kg
    solvent_gwp: float = 0.0                 # kg CO2-eq / kg
    solvent_ced: float = 0.0                 # MJ / kg
    capex_per_kgyr: float = 0.0              # EUR per (kg biomass/yr)
    allocation: str = "economic"             # economic | mass | none (all to main product)
    notes: str = ""                          # provenance / citation for a catalogued preset


@dataclass
class Product:
    """An output fraction that can be sold. Yields link to the organism composition."""

    name: str
    fraction: str = "biomass"   # lipid | protein | carbohydrate | ash | biomass | residual | custom
    recovery: float = 1.0       # fraction of that component recovered into this product
    price: float = 0.0          # EUR/kg
    is_main: bool = False       # the main product carries the reported production cost
    yield_override: float = 0.0  # if >0, kg product / kg biomass directly (ignores `fraction`)


@dataclass
class Economics:
    """Prices and financial assumptions for the techno-economic analysis."""

    electricity_price: float       # EUR/kWh
    heat_price: float              # EUR/MJ
    co2_price: float               # EUR/kg CO2 (may be <=0 for waste/credited CO2)
    nitrogen_price: float          # EUR/kg N
    phosphorus_price: float        # EUR/kg P
    water_price: float             # EUR/m3
    substrate_price: float         # EUR/kg substrate
    land_price: float              # EUR/m2 (one-time)
    harvest_capex_per_kgyr: float  # EUR per (kg/yr) capacity
    drying_capex_per_kgyr: float   # EUR per (kg/yr) capacity
    installation_factor: float     # installed CAPEX = equipment * factor
    indirect_factor: float         # engineering+contingency, fraction of installed
    labor_cost_per_year: float     # EUR/yr
    maintenance_frac: float        # fraction of total CAPEX per year
    overhead_frac: float           # fraction of (variable+labour+maintenance)
    discount_rate: float           # for NPV / capital recovery factor
    plant_lifetime: float          # yr (project evaluation horizon)
    # --- profitability & SuperPro-style capital structure (defaults provided) ---
    bicarbonate_price: float = 0.28    # EUR/kg NaHCO3 (sodium bicarbonate carbon source)
    depreciation_years: float = 10.0   # straight-line depreciation period
    insurance_frac: float = 0.01       # per year, as fraction of DFC
    working_capital_frac: float = 0.05  # working capital as fraction of DFC
    startup_frac: float = 0.05          # start-up cost as fraction of DFC
    tax_rate: float = 0.30              # income tax rate


@dataclass
class LCIAFactors:
    """Cradle-to-gate characterization factors for the impact assessment.

    The values, their units, provenance, geography, reference period and quality
    flag are declared in ``data/lcia.yaml``, together with the boundary, cut-off
    and allocation statement they belong to; :mod:`algametrix.lciamethod` reads
    that file and builds this object from it. The defaults written here are the
    fallback for code that constructs the class directly and are the same numbers
    the file declares — the declaration is where a reader should look for what
    they mean and where they came from.
    """

    elec_gwp: float        # kg CO2-eq / kWh
    elec_ced: float        # MJ / kWh
    elec_water: float      # m3 / kWh
    heat_gwp: float        # kg CO2-eq / MJ
    heat_ced: float        # MJ / MJ
    nitrogen_gwp: float    # kg CO2-eq / kg N
    nitrogen_ced: float    # MJ / kg N
    phosphorus_gwp: float  # kg CO2-eq / kg P
    phosphorus_ced: float  # MJ / kg P
    co2_supply_gwp: float  # kg CO2-eq / kg CO2 supplied
    substrate_gwp: float   # kg CO2-eq / kg substrate
    substrate_ced: float   # MJ / kg substrate
    count_biogenic_uptake: bool = True  # master switch; False forces NO_BIOGENIC_CREDIT
    # Which biogenic-carbon convention applies when the master switch is on.
    # The default reproduces the historical behaviour (credit CO2-fed carbon only).
    carbon_accounting: CarbonAccounting = CarbonAccounting.SOURCE_SPECIFIC_CREDIT
    # Fraction of incorporated carbon credited under CarbonAccounting.CUSTOM.
    custom_biogenic_credit_fraction: float = 1.0
    # --- sodium bicarbonate carbon source (defaults provided) -------------
    bicarbonate_gwp: float = 0.87  # kg CO2-eq / kg NaHCO3 (Solvay/trona production)
    bicarbonate_ced: float = 11.0  # MJ / kg NaHCO3
    # --- eutrophication & acidification -----------------------------------
    # Declared, with their provenance and quality flag, in data/lcia.yaml. The
    # two partitioning fractions are inventory assumptions rather than
    # characterization factors and are marked as such in that file.
    n_to_water_frac: float = 0.3   # fraction of un-assimilated N reaching water
    p_to_water_frac: float = 0.5   # fraction of un-assimilated P reaching water
    elec_acid: float = 0.0018      # kg SO2-eq / kWh
    heat_acid: float = 0.00007     # kg SO2-eq / MJ
    nitrogen_acid: float = 0.008   # kg SO2-eq / kg N (fertilizer production)
    phosphorus_acid: float = 0.006  # kg SO2-eq / kg P
    substrate_acid: float = 0.002  # kg SO2-eq / kg substrate
    solvent_acid: float = 0.004    # kg SO2-eq / kg solvent
    nitrogen_eutroph_n: float = 0.012   # kg N-eq / kg N (upstream fertilizer)
    phosphorus_eutroph_p: float = 0.03  # kg P-eq / kg P (upstream fertilizer)
    elec_eutroph_p: float = 0.00005     # kg P-eq / kWh


@dataclass
class Scenario:
    """A complete, self-contained production scenario."""

    organism: Organism
    system: CultivationSystem
    harvesting: Harvesting
    drying: Drying
    economics: Economics
    lcia: LCIAFactors
    scale: float                    # m2 (area basis) or m3 (volume basis)
    product_name: str = "dry biomass"
    # Explicit media / chemicals and utilities on top of the derived flows.
    materials: list[Material] = field(default_factory=list)
    utilities: list[Utility] = field(default_factory=list)
    # Profitability inputs (0 => not sold, production-cost analysis only).
    product_price: float = 0.0                # EUR/kg of product (whole-biomass mode)
    coproduct_revenue_per_year: float = 0.0   # EUR/yr from co-products / by-products
    # Optional waste-derived nutrient / carbon feed (effluent, food by-product).
    waste_feed: WasteFeed = field(default_factory=WasteFeed)
    # Optional downstream extraction and multi-product output with allocation.
    extraction: Extraction = field(default_factory=Extraction)
    products: list[Product] = field(default_factory=list)
    # Optional batch scheduling (else throughput = scale x productivity x days).
    batch_mode: bool = False
    batch_size_kg: float = 0.0        # gross dry biomass harvested per batch
    batch_cycle_time_h: float = 0.0   # total batch cycle time (incl. turnaround)
    # Operating-cost credits (energy/heat recovery, biogas, waste valorisation).
    credits_per_year: float = 0.0     # EUR/yr that reduce the net operating cost
    # Lump-sum annual operating costs that are neither per-kg materials/utilities
    # nor labour — e.g. consumables (probes, filters), miscellaneous utilities,
    # wastewater treatment, contingencies. Many published TEA studies report such
    # items as an annual figure; this adds them to the AOC as its own category.
    other_opex_per_year: float = 0.0  # EUR/yr
