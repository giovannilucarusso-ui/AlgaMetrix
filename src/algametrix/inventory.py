"""Mass and energy balance.

Turns a :class:`~algametrix.models.Scenario` into an :class:`Inventory`:
the physical flows required to make the product, expressed **per kilogram of dry
biomass** (the functional unit) plus the total **annual production**.

Both the techno-economic and the life-cycle analyses read this single inventory,
so the two are always consistent with each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Basis, CarbonSource, Scenario, TrophicMode

# CO2 fixed per unit of biomass carbon: molar mass ratio CO2 / C = 44.01 / 12.011
CO2_PER_C = 44.01 / 12.011
# NaHCO3 supplied per unit of biomass carbon: molar mass ratio NaHCO3 / C = 84.007 / 12.011
NAHCO3_PER_C = 84.007 / 12.011
# Lowest meaningful carbon-utilization efficiency. A phototrophic culture cannot
# run at 0 % efficiency (that implies an infinite carbon feed), so the balance is
# floored here to keep the supplied-carbon flow finite and physically sensible.
MIN_CARBON_UTILIZATION = 0.05
# Carbon mass fraction of the default organic substrate (glucose, C6H12O6:
# 6 x 12.011 / 180.156). Used only for the carbon bookkeeping that the
# biogenic-carbon accounting reports; it does not enter the cost or impact sums.
SUBSTRATE_CARBON_FRACTION = 6 * 12.011 / 180.156


@dataclass
class Inventory:
    """Physical flows per kg of dry biomass, plus annual production.

    Every ``*_per_kg`` field is referenced to 1 kg of dried product leaving the
    gate. ``breakdown`` holds per-stage electricity so the UI can show where the
    energy goes.
    """

    annual_biomass_kg: float          # kg dry biomass / yr leaving the gate
    elec_kwh_per_kg: float            # total electricity
    heat_mj_per_kg: float             # thermal energy (drying)
    co2_supply_per_kg: float          # CO2 gas supplied to the culture
    co2_fixed_per_kg: float           # CO2 biologically fixed by the GROSS biomass cultivated
    bicarbonate_supply_per_kg: float  # kg NaHCO3 supplied (bicarbonate carbon source)
    nitrogen_per_kg: float            # kg N supplied
    phosphorus_per_kg: float          # kg P supplied
    water_m3_per_kg: float            # net water consumption
    substrate_per_kg: float           # kg organic substrate (heterotrophic)
    land_m2a_per_kg: float            # m2*a land occupation
    solvent_net_per_kg: float = 0.0   # kg extraction solvent make-up (net of recycle)
    nitrogen_emitted_per_kg: float = 0.0    # kg N not assimilated (potential water emission)
    phosphorus_emitted_per_kg: float = 0.0  # kg P not assimilated
    # --- waste-derived feed (see models.WasteFeed) -------------------------
    # Quantity of the waste stream dosed, in its own unit (m3 or kg) per kg of
    # product. Zero when no waste feed is enabled, which leaves every field
    # below at zero and the ``*_purchased_per_kg`` fields equal to the demand.
    waste_feed_per_kg: float = 0.0
    nitrogen_from_waste_per_kg: float = 0.0    # kg N of the demand met by the stream
    phosphorus_from_waste_per_kg: float = 0.0
    substrate_from_waste_per_kg: float = 0.0
    # What is still bought. These, not the totals, are what the cost and the
    # fertiliser-production burden are computed from: nutrient arriving in a
    # waste stream has no fertiliser plant behind it.
    nitrogen_purchased_per_kg: float = 0.0
    phosphorus_purchased_per_kg: float = 0.0
    substrate_purchased_per_kg: float = 0.0
    # Nutrient the stream carries beyond what the culture can take up, because a
    # stream dosed on one nutrient delivers the others in whatever ratio it
    # happens to have. It is discharged, so it is reported here and enters
    # eutrophication - never silently dropped to make the balance look tidy.
    nitrogen_surplus_per_kg: float = 0.0
    phosphorus_surplus_per_kg: float = 0.0
    # --- carbon bookkeeping (biogenic-carbon accounting, see lca.CarbonAccounting) ---
    # Carbon that actually LEAVES THE GATE inside 1 kg of product, expressed as CO2.
    # Differs from ``co2_fixed_per_kg`` by the harvesting recovery: carbon fixed by
    # biomass that is lost during harvesting never reaches the product.
    biogenic_co2_in_product_per_kg: float = 0.0
    # Carbon fed as organic substrate, expressed as CO2 (heterotrophic systems).
    substrate_co2_supplied_per_kg: float = 0.0
    # Inorganic carbon supplied to the culture, expressed as CO2 (CO2 gas or NaHCO3).
    inorganic_co2_supplied_per_kg: float = 0.0
    # Carbon in the GROSS biomass cultivated, expressed as CO2 - i.e. including
    # the biomass that harvesting loses. ``biogenic_co2_in_product_per_kg`` is
    # the same quantity after those losses.
    biogenic_co2_in_gross_biomass_per_kg: float = 0.0
    # Substrate carbon NOT incorporated into biomass, expressed as CO2: what a
    # heterotrophic culture respires. Reported, never summed. Under the biogenic
    # 0/0 convention this carbon enters as biogenic substrate carbon and leaves
    # as biogenic CO2, so both sides are excluded from the GWP - the same
    # treatment ``substrate_co2_supplied_per_kg`` already receives. It is
    # computed so the carbon balance can be *stated* rather than assumed, and it
    # is signed: a negative value means more carbon leaves in the biomass than
    # entered with the substrate, which is physically impossible and is what
    # :func:`algametrix.verification.verify` tests for.
    biogenic_co2_respired_per_kg: float = 0.0
    batches_per_year: float = 0.0     # 0 in continuous mode
    batch_product_kg: float = 0.0     # final product per batch (batch mode)
    elec_breakdown: dict = field(default_factory=dict)  # kWh/kg by stage

    @property
    def water_evaporated_per_kg(self) -> float:
        """kg of water evaporated in drying, per kg dry biomass (diagnostic)."""
        return self._water_evaporated

    _water_evaporated: float = 0.0


def _water_to_evaporate(solids_in: float, solids_out: float) -> float:
    """kg water removed per kg dry solids, going from ``solids_in`` to ``solids_out``.

    Water associated with 1 kg dry solids at solids fraction ``s`` is ``(1-s)/s``.
    """
    solids_in = min(max(solids_in, 1e-6), 1.0)
    solids_out = min(max(solids_out, 1e-6), 1.0)
    water_in = (1.0 - solids_in) / solids_in
    water_out = (1.0 - solids_out) / solids_out
    return max(water_in - water_out, 0.0)


@dataclass
class _WasteSplit:
    """How much of each demand a waste stream covers, and what it over-delivers."""

    quantity: float = 0.0              # units of stream per kg product
    nitrogen: float = 0.0              # kg N of the demand met by the stream
    phosphorus: float = 0.0
    substrate: float = 0.0
    nitrogen_surplus: float = 0.0      # kg N delivered beyond the demand
    phosphorus_surplus: float = 0.0


def _waste_split(scenario: Scenario, nitrogen: float, phosphorus: float,
                 substrate: float) -> _WasteSplit:
    """Dose the waste stream against one demand and see what else it brings.

    The quantity follows from ``dosed_on`` alone. Everything the same quantity
    carries of the other two is then compared against their demands: what fits
    displaces a purchase, what does not is surplus.

    One limit is worth naming. Organic carbon beyond the substrate demand — all
    of it, for a phototrophic culture — is unused load left in the effluent, and
    it is capped here rather than tracked, because the impact set carries no
    oxygen-demand indicator to receive it. A stream chosen for its carbon and
    fed to a phototroph is therefore modelled as delivering only its nitrogen
    and phosphorus, which is the honest reading of what the culture does with it.
    """
    wf = scenario.waste_feed
    if not wf.enabled:
        return _WasteSplit()

    demand = {"nitrogen": nitrogen, "phosphorus": phosphorus, "substrate": substrate}
    per_unit = {"nitrogen": wf.nitrogen_per_unit,
                "phosphorus": wf.phosphorus_per_unit,
                "substrate": wf.substrate_per_unit}
    key = wf.dosed_on if wf.dosed_on in demand else "nitrogen"
    concentration = max(per_unit[key], 0.0)
    if concentration <= 0.0 or demand[key] <= 0.0:
        # Dosed against something the stream does not carry, or that the culture
        # does not need. Nothing is received, and nothing is silently rerouted
        # to a different nutrient: the scenario as written buys everything.
        return _WasteSplit()

    coverage = min(max(wf.coverage, 0.0), 1.0)
    quantity = coverage * demand[key] / concentration
    delivered = {k: quantity * max(per_unit[k], 0.0) for k in demand}
    met = {k: min(delivered[k], demand[k]) for k in demand}
    return _WasteSplit(
        quantity=quantity,
        nitrogen=met["nitrogen"],
        phosphorus=met["phosphorus"],
        substrate=met["substrate"],
        nitrogen_surplus=max(delivered["nitrogen"] - nitrogen, 0.0),
        phosphorus_surplus=max(delivered["phosphorus"] - phosphorus, 0.0),
    )


def build_inventory(scenario: Scenario) -> Inventory:
    """Compute the process inventory for ``scenario``."""
    org = scenario.organism
    sys = scenario.system
    harv = scenario.harvesting
    dry = scenario.drying

    # --- annual production ------------------------------------------------
    # Gross biomass cultivated before harvesting losses.
    batches_per_year = 0.0
    if scenario.batch_mode and scenario.batch_cycle_time_h > 0:
        # batches limited by cycle time over the annual operating window
        batches_per_year = sys.operating_days * 24.0 / scenario.batch_cycle_time_h
        gross_kg_yr = scenario.batch_size_kg * batches_per_year
    elif sys.basis == Basis.AREA:
        # g/m2/d * m2 * d/yr  ->  g/yr  ->  kg/yr
        gross_kg_yr = sys.productivity * scenario.scale * sys.operating_days / 1000.0
    else:  # VOLUME
        # g/L/d * (m3 * 1000 L/m3) * d/yr  ->  g/yr  ->  kg/yr
        gross_kg_yr = sys.productivity * (scenario.scale * 1000.0) * sys.operating_days / 1000.0
    total_land_m2 = scenario.scale * sys.land_m2_per_unit

    recovery = min(max(harv.recovery, 1e-6), 1.0)
    annual_kg = gross_kg_yr * recovery  # dry biomass leaving the gate
    batch_product_kg = scenario.batch_size_kg * recovery if scenario.batch_mode else 0.0

    # Cultivating enough gross biomass to yield 1 kg of product needs 1/recovery
    # kg of gross biomass; upstream flows are scaled by this factor.
    gross_per_product = 1.0 / recovery

    # --- carbon: CO2 gas or sodium bicarbonate ----------------------------
    # The carbon locked into the biomass is the same regardless of how it is
    # fed; only the make-up reagent (CO2 gas vs NaHCO3 solution) and its cost /
    # footprint differ. ``co2_utilization`` is the fraction of the supplied
    # inorganic carbon that is actually fixed.
    if sys.mode == TrophicMode.PHOTOTROPHIC:
        carbon_per_product = org.carbon * gross_per_product  # kg C fixed / kg product
        co2_fixed = carbon_per_product * CO2_PER_C
        util = min(max(sys.co2_utilization, MIN_CARBON_UTILIZATION), 1.0)
        if sys.carbon_source == CarbonSource.BICARBONATE:
            co2_supply = 0.0
            bicarbonate_supply = carbon_per_product * NAHCO3_PER_C / util
        else:  # CO2 gas enrichment
            co2_supply = co2_fixed / util
            bicarbonate_supply = 0.0
        substrate = 0.0
    else:  # HETEROTROPHIC: carbon comes from substrate, not CO2
        co2_fixed = 0.0
        co2_supply = 0.0
        bicarbonate_supply = 0.0
        yield_ = max(sys.substrate_yield, 1e-6)
        substrate = gross_per_product / yield_  # kg substrate / kg product

    # --- nutrients --------------------------------------------------------
    uptake = min(max(sys.nutrient_uptake, 1e-6), 1.0)
    nitrogen = org.nitrogen * gross_per_product / uptake
    phosphorus = org.phosphorus * gross_per_product / uptake
    nitrogen_emitted = nitrogen * (1.0 - uptake)
    phosphorus_emitted = phosphorus * (1.0 - uptake)

    # --- waste-derived feed -----------------------------------------------
    # A stream of fixed composition displaces part of what would be bought. The
    # demands above are untouched: the biomass needs the same nitrogen however
    # it arrives, and only the *purchase* moves.
    waste = _waste_split(scenario, nitrogen, phosphorus, substrate)
    nitrogen_emitted += waste.nitrogen_surplus
    phosphorus_emitted += waste.phosphorus_surplus

    # --- water ------------------------------------------------------------
    water = sys.water_m3_per_kg * gross_per_product

    # --- electricity by stage --------------------------------------------
    elec_cultivation = sys.elec_kwh_per_kg * gross_per_product
    # Pumping, screening and mixing the received stream sits with cultivation:
    # it is incurred to put the feed into the pond.
    elec_cultivation += waste.quantity * scenario.waste_feed.elec_kwh_per_unit
    elec_harvest = harv.elec_kwh_per_kg * gross_per_product
    elec_drying = dry.elec_kwh_per_kg if dry.enabled else 0.0

    # --- cultivation thermal conditioning (seasonal pond/greenhouse heating) ---
    # Scaled per gross biomass like the other cultivation flows. Routed to either
    # the heat account (fossil/biogas boiler) or electricity (resistive/heat pump),
    # so it flows through the existing TEA prices and LCA factors unchanged.
    cult_heat_mj = sys.cultivation_heat_mj_per_kg * gross_per_product
    if sys.cultivation_heat_fuel == "electricity":
        elec_cultivation += cult_heat_mj / 3.6  # MJ -> kWh
        cult_heat_mj = 0.0

    # --- drying heat ------------------------------------------------------
    heat_mj = cult_heat_mj
    water_evap = 0.0
    if dry.enabled:
        water_evap = _water_to_evaporate(harv.final_solids, dry.final_solids)
        drying_heat_mj = water_evap * dry.thermal_mj_per_kg_water
        if dry.fuel == "electricity":
            # Move the drying energy from the heat account to electricity.
            elec_drying += drying_heat_mj / 3.6  # MJ -> kWh
        else:
            heat_mj += drying_heat_mj

    # --- downstream extraction (per kg dry biomass entering the step) -----
    ext = scenario.extraction
    elec_extraction = 0.0
    solvent_net = 0.0
    if ext.enabled:
        elec_extraction = ext.disruption_elec_kwh_per_kg + ext.elec_kwh_per_kg
        heat_mj += ext.heat_mj_per_kg
        solvent_net = ext.solvent_kg_per_kg * (1.0 - min(max(ext.solvent_recovery, 0.0), 1.0))

    elec_total = elec_cultivation + elec_harvest + elec_drying + elec_extraction

    # --- carbon bookkeeping ------------------------------------------------
    # What leaves the gate: the carbon in 1 kg of product, with no recovery
    # factor - biomass lost at harvest never becomes product.
    biogenic_co2_in_product = org.carbon * CO2_PER_C
    substrate_co2_supplied = substrate * SUBSTRATE_CARBON_FRACTION * CO2_PER_C
    inorganic_co2_supplied = co2_supply + bicarbonate_supply * (12.011 / 84.007) * CO2_PER_C
    # Carbon into the gross biomass cultivated, and - for a heterotroph - the
    # substrate carbon left over, which is respired. For a phototroph the carbon
    # entering the biomass IS the carbon fixed, so there is no residual to
    # report: the model works on a net-fixation basis and does not resolve gross
    # photosynthesis from respiration.
    biogenic_co2_in_gross_biomass = org.carbon * gross_per_product * CO2_PER_C
    respired_co2 = (substrate_co2_supplied - biogenic_co2_in_gross_biomass
                    if substrate > 0 else 0.0)

    # --- land occupation --------------------------------------------------
    land_m2a = total_land_m2 / annual_kg if annual_kg > 0 else 0.0

    inv = Inventory(
        annual_biomass_kg=annual_kg,
        elec_kwh_per_kg=elec_total,
        heat_mj_per_kg=heat_mj,
        co2_supply_per_kg=co2_supply,
        co2_fixed_per_kg=co2_fixed,
        bicarbonate_supply_per_kg=bicarbonate_supply,
        nitrogen_per_kg=nitrogen,
        phosphorus_per_kg=phosphorus,
        water_m3_per_kg=water,
        substrate_per_kg=substrate,
        land_m2a_per_kg=land_m2a,
        solvent_net_per_kg=solvent_net,
        nitrogen_emitted_per_kg=nitrogen_emitted,
        phosphorus_emitted_per_kg=phosphorus_emitted,
        waste_feed_per_kg=waste.quantity,
        nitrogen_from_waste_per_kg=waste.nitrogen,
        phosphorus_from_waste_per_kg=waste.phosphorus,
        substrate_from_waste_per_kg=waste.substrate,
        nitrogen_purchased_per_kg=nitrogen - waste.nitrogen,
        phosphorus_purchased_per_kg=phosphorus - waste.phosphorus,
        substrate_purchased_per_kg=substrate - waste.substrate,
        nitrogen_surplus_per_kg=waste.nitrogen_surplus,
        phosphorus_surplus_per_kg=waste.phosphorus_surplus,
        biogenic_co2_in_product_per_kg=biogenic_co2_in_product,
        substrate_co2_supplied_per_kg=substrate_co2_supplied,
        inorganic_co2_supplied_per_kg=inorganic_co2_supplied,
        biogenic_co2_in_gross_biomass_per_kg=biogenic_co2_in_gross_biomass,
        biogenic_co2_respired_per_kg=respired_co2,
        batches_per_year=batches_per_year,
        batch_product_kg=batch_product_kg,
        elec_breakdown={
            "cultivation": elec_cultivation,
            "harvesting": elec_harvest,
            "drying": elec_drying,
            "extraction": elec_extraction,
        },
    )
    inv._water_evaporated = water_evap
    return inv
