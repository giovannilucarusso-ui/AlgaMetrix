"""Auto-generate a process flowsheet from a TEA/LCA :class:`Scenario`.

This is the bridge between the parametric case study (built by the setup wizard
and edited on the *Scenario* tab) and the visual *Process Designer*. Given the
same :class:`~algametrix.models.Scenario` that feeds the TEA and LCA, it
lays out an engineering-style process train — feeds, cultivation, dewatering,
drying and (optional) extraction — wired left-to-right with product and effluent
sinks, so the researcher always starts from *their* case instead of a generic
example.

The mapping is deliberately transparent:

* cultivation block   <- ``scenario.system``   (reactor/pond type & trophic mode)
* dewatering block(s) <- ``scenario.harvesting`` (may expand to a 2-stage train)
* drying block        <- ``scenario.drying``     (skipped when "wet paste")
* disruption + extractor <- ``scenario.extraction``

Every generated block carries a ``role`` naming what it stands for in the
scenario (see the constants below). The designer uses it to tie the block to the
engine: which fields it exposes, and which share of the results it carries.

When a solved :class:`~algametrix.scenario.Results` is passed, the block
parameters and feed flows are seeded with the case's real numbers (from the
per-kg :class:`~algametrix.inventory.Inventory`), so the first-pass
balance on the canvas lands in the same ballpark as the rigorous engine.
:func:`seed_flows` repeats that seeding on an existing diagram, which is how the
designer keeps the drawing in step with the engine without moving any block.

The module is pure (no Qt): it returns a :class:`~desktop.flowsheet.model.Flowsheet`
and can be unit-tested against the engine alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from algametrix.models import CarbonSource, Scenario, TrophicMode

from . import model as M

# --------------------------------------------------------------------------- #
# Roles: what a generated block stands for in the scenario
# --------------------------------------------------------------------------- #
CULTIVATION = "cultivation"
HARVEST = "harvest"            # a second dewatering stage is "harvest:2"
DRYING = "drying"
DISRUPTION = "disruption"
EXTRACTION = "extraction"
MEDIA_PREP = "media_prep"
FEED_WATER = "feed_water"
FEED_NUTRIENTS = "feed_nutrients"
FEED_CHEMICALS = "feed_chemicals"
FEED_INOCULUM = "feed_inoculum"
FEED_CARBON = "feed_carbon"
FEED_SUBSTRATE = "feed_substrate"
FEED_WASTE = "feed_waste"
FEED_SOLVENT = "feed_solvent"
PRODUCT = "product"
EFFLUENT = "effluent"          # one per dewatering stage: "effluent", "effluent:2"
VAPOUR = "vapour"
SPENT = "spent_biomass"

# Plant area of each role, used for the equipment tag numbers (FD-101, PD-201...).
_AREA = {
    FEED_WATER: 1, FEED_NUTRIENTS: 1, FEED_CHEMICALS: 1, FEED_INOCULUM: 1, FEED_CARBON: 1,
    FEED_SUBSTRATE: 1, FEED_WASTE: 1, MEDIA_PREP: 1,
    CULTIVATION: 2,
    HARVEST: 3, EFFLUENT: 3,
    DRYING: 4, VAPOUR: 4,
    DISRUPTION: 5, EXTRACTION: 5, FEED_SOLVENT: 5, SPENT: 5,
    PRODUCT: 6,
}

# --------------------------------------------------------------------------- #
# Layout geometry (scene coordinates; a block is about 190 x 150)
# --------------------------------------------------------------------------- #
DX = 280.0          # horizontal spacing between spine columns
DY = 205.0          # vertical spacing for feeds / sinks off the spine
X0 = -560.0         # x of the feed column (spine starts one column to its right)
Y_SPINE = -20.0     # baseline y of the main process spine
Y_SINK = Y_SPINE + DY        # effluent / waste sinks sit below their source
Y_SOLVENT = Y_SPINE - DY     # solvent feed sits above the extractor


def _col_x(col: int) -> float:
    return X0 + col * DX


# --------------------------------------------------------------------------- #
# Scenario -> unit-type mapping (keyword based, tolerant of library renames)
# --------------------------------------------------------------------------- #
def cultivation_kind(scn: Scenario) -> str:
    """Pick the reactor/pond block that best matches the cultivation system."""
    if scn.system.mode == TrophicMode.HETEROTROPHIC:
        return "fermenter"
    n = scn.system.name.lower()
    if "tubular" in n:
        return "tubular_pbr"
    if "flat" in n or "panel" in n:
        return "flat_panel_pbr"
    if "bubble" in n or "airlift" in n or "column" in n:
        return "bubble_column_pbr"
    if "thin" in n or "cascade" in n:
        return "thin_layer"
    # raceway, open pond, and any other open system
    return "raceway"


def _dewater_kind(name: str) -> str:
    """Single dewatering block for a harvesting-preset name."""
    n = name.lower()
    if "cross-flow" in n or "crossflow" in n or "ultrafiltration" in n or "tangential" in n:
        return "crossflow_uf"
    if "membrane" in n:
        return "membrane"
    if "decanter" in n:
        return "decanter"
    if "centrifug" in n:
        return "centrifuge"
    if "screen" in n:
        return "screen_filter"
    if "rotary" in n or "drum filter" in n:
        return "drum_filter"
    if "press" in n or "filter" in n:
        return "filter_press"
    if "settl" in n or "floccul" in n:
        return "settler"
    return "centrifuge"


def harvest_chain(scn: Scenario) -> list[str]:
    """One or two dewatering blocks that reproduce the harvesting preset.

    Presets that name two operations ("Settling + centrifugation", the
    "2-stage" cross-flow + centrifuge route) expand into a short train so the
    canvas mirrors the real dewatering sequence."""
    n = scn.harvesting.name.lower()
    if "settling" in n and "centrifug" in n:
        return ["settler", "centrifuge"]
    if "2-stage" in n or ("+" in n and "centrifug" in n):
        # e.g. "Cross-flow membrane + centrifuge (2-stage)"
        first = "crossflow_uf" if ("cross" in n or "membrane" in n) else "membrane"
        return [first, "centrifuge"]
    return [_dewater_kind(n)]


def dryer_kind(scn: Scenario) -> str | None:
    """Drying block, or ``None`` when the product leaves as a wet paste."""
    if not scn.drying.enabled:
        return None
    n = scn.drying.name.lower()
    if "spray" in n:
        return "spray_dryer"
    if "drum" in n:
        return "drum_dryer"
    if "freeze" in n or "lyo" in n:
        return "freeze_dryer"
    return "spray_dryer"


def disruption_kind(scn: Scenario) -> str | None:
    """Cell-disruption block preceding extraction, if the recipe uses one."""
    ext = scn.extraction
    if not ext.enabled or ext.disruption_elec_kwh_per_kg <= 0.0:
        return None
    hint = f"{ext.name} {ext.solvent_name}".lower()
    if "homogen" in hint:
        return "homogenizer"
    return "bead_mill"


def extractor_kind(scn: Scenario) -> str:
    """Extraction block: supercritical CO2 vs a stirred solvent contactor."""
    hint = f"{scn.extraction.name} {scn.extraction.solvent_name}".lower()
    if "co2" in hint or "supercritical" in hint or "scco2" in hint:
        return "supercritical_co2"
    return "extraction"


# --------------------------------------------------------------------------- #
# Flow seeding from the solved inventory
# --------------------------------------------------------------------------- #
def _op_hours(scn: Scenario) -> float:
    return max(scn.system.operating_days, 1.0) * 24.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class HourlyFlows:
    """Stream rates of the generated diagram, in kg/h (not per kg of product)."""

    net: float              # dry biomass leaving the gate
    gross: float            # dry biomass out of cultivation
    water: float
    co2: float
    bicarbonate: float
    substrate: float
    nutrients: float
    chemicals: float
    inoculum: float
    solvent: float          # solvent contacted in the extractor
    solvent_makeup: float
    waste_feed: float
    extract_yield: float | None   # main product per kg biomass entering extraction
    main_product: float | None
    known: bool             # False when there was no solved case to read


def hourly_flows(scn: Scenario, results=None) -> HourlyFlows:
    op_h = _op_hours(scn)
    rec = _clamp(scn.harvesting.recovery, 1e-3, 1.0)
    chem_per_kg = sum(m.amount_per_kg for m in scn.materials)
    if results is not None and results.inventory.annual_biomass_kg > 0:
        inv = results.inventory
        net = inv.annual_biomass_kg / op_h
        mp = getattr(results, "main_product", None)
        extract_yield = main = None
        if mp is not None and mp.annual_kg > 0:
            # Makes the canvas product stream equal the engine's main product rate.
            extract_yield = _clamp(mp.annual_kg / inv.annual_biomass_kg, 1e-4, 1.0)
            main = mp.annual_kg / op_h
        per_unit = 1000.0 if scn.waste_feed.unit == "m3" else 1.0
        return HourlyFlows(
            net=net, gross=net / rec,
            water=inv.water_m3_per_kg * 1000.0 * net,
            co2=inv.co2_supply_per_kg * net,
            bicarbonate=inv.bicarbonate_supply_per_kg * net,
            substrate=inv.substrate_purchased_per_kg * net,
            nutrients=(inv.nitrogen_purchased_per_kg + inv.phosphorus_purchased_per_kg) * net,
            chemicals=chem_per_kg * net,
            inoculum=net / rec * 0.05,
            solvent=scn.extraction.solvent_kg_per_kg * net,
            solvent_makeup=inv.solvent_net_per_kg * net,
            waste_feed=inv.waste_feed_per_kg * net * per_unit,
            extract_yield=extract_yield, main_product=main, known=True,
        )
    gross = 100.0
    net = gross * rec
    conc = _clamp(scn.system.biomass_conc, 1e-3, 1e6)
    return HourlyFlows(
        net=net, gross=gross, water=gross * (1000.0 / conc - 1.0), co2=200.0,
        bicarbonate=0.0, substrate=0.0, nutrients=gross * 0.02,
        chemicals=chem_per_kg * net, inoculum=gross * 0.05,
        solvent=scn.extraction.solvent_kg_per_kg * net, solvent_makeup=0.0, waste_feed=0.0,
        extract_yield=None, main_product=None, known=False,
    )


# Concentrate solids after the first stage of a two-stage train: gravity
# settling or flocculation reaches a few percent, a membrane pre-concentration
# somewhat more. Only the drawing uses it; the engine has one harvesting step.
_STAGE1_SOLIDS = {"settler": 0.02, "crossflow_uf": 0.06, "membrane": 0.06}


def _set(node: M.UnitNode, **params: float) -> None:
    """Set only the parameters the node's spec actually declares."""
    valid = {p.key for p in node.spec.params}
    for k, v in params.items():
        if k in valid:
            node.params[k] = float(v)


def seed_flows(fs: M.Flowsheet, scn: Scenario, results=None) -> None:
    """Write the case's rates and performance onto the role-tagged blocks.

    Positions, names and wiring are left alone. Blocks without a role (drawn by
    hand from the palette) keep whatever parameters they have.
    """
    f = hourly_flows(scn, results)
    harv = scn.harvesting
    stages = sorted((n for n in fs.nodes.values() if n.role.split(":")[0] == HARVEST),
                    key=lambda n: n.role)
    if len(stages) > 1:
        # Split the recovery evenly so the train as a whole recovers what the
        # engine assumes; the first stage stops short of the final solids.
        each = harv.recovery ** (1.0 / len(stages))
        for i, node in enumerate(stages):
            if i < len(stages) - 1:
                fs1 = min(_STAGE1_SOLIDS.get(node.kind, 0.05), 0.5 * harv.final_solids)
                _set(node, solids_recovery=each, final_solids=max(fs1, 1e-3))
            else:
                _set(node, solids_recovery=each, final_solids=harv.final_solids)
    elif stages:
        _set(stages[0], solids_recovery=harv.recovery, final_solids=harv.final_solids)

    for node in fs.nodes.values():
        role = node.role
        if role == CULTIVATION:
            _set(node, biomass_kg_h=f.gross, harvest_conc_g_l=scn.system.biomass_conc)
        elif role == FEED_WATER:
            _set(node, flow_kg_h=f.water)
        elif role == FEED_NUTRIENTS:
            _set(node, flow_kg_h=f.nutrients)
        elif role == FEED_CHEMICALS:
            _set(node, flow_kg_h=f.chemicals)
        elif role == FEED_INOCULUM:
            _set(node, flow_kg_h=f.inoculum)
        elif role == FEED_CARBON:
            bicarb = scn.system.carbon_source == CarbonSource.BICARBONATE
            _set(node, flow_kg_h=f.bicarbonate if bicarb else f.co2)
        elif role == FEED_SUBSTRATE:
            _set(node, flow_kg_h=f.substrate)
        elif role == FEED_WASTE:
            _set(node, flow_kg_h=f.waste_feed)
        elif role == DRYING:
            _set(node, final_solids=scn.drying.final_solids)
        elif role == EXTRACTION:
            _set(node, solvent_recovery=scn.extraction.solvent_recovery)
            if f.extract_yield is not None:
                _set(node, extract_yield=f.extract_yield)
        elif role == FEED_SOLVENT:
            _set(node, flow_kg_h=f.solvent)


# --------------------------------------------------------------------------- #
# The builder
# --------------------------------------------------------------------------- #
def _tag(fs: M.Flowsheet, node: M.UnitNode) -> str:
    """Equipment tag numbered by plant area: FD-101, PD-201, ST-301, CF-302, ..."""
    area = _AREA.get(node.role.split(":")[0], 9)
    used = 0
    for n in fs.nodes.values():
        digits = n.tag.rsplit("-", 1)[-1]
        if n is not node and n.role and digits.isdigit() and int(digits) // 100 == area:
            used += 1
    return f"{node.spec.tag_prefix}-{area * 100 + used + 1}"


def _add(fs: M.Flowsheet, kind: str, col: int, y: float, name: str, role: str) -> M.UnitNode:
    node = fs.add_node(kind, _col_x(col), y, name)
    node.role = role
    node.tag = _tag(fs, node)
    return node


def flowsheet_from_scenario(scn: Scenario, results=None) -> M.Flowsheet:
    """Construct a process :class:`Flowsheet` mirroring ``scn``.

    ``results`` (an optional solved :class:`~algametrix.scenario.Results`)
    seeds realistic flows; without it, nominal defaults keep the canvas sensible.
    """
    fs = M.Flowsheet()
    phototrophic = scn.system.mode == TrophicMode.PHOTOTROPHIC

    # -- feeds (column 0) and media preparation (column 1) ---------------- #
    # Water + nutrient salts + recipe chemicals are blended in a prep tank whose
    # medium feeds the reactor; the seed inoculum and the carbon source connect
    # to the reactor directly.
    water = _add(fs, "feed", 0, Y_SPINE - DY, "Water", FEED_WATER)
    _set(water, component=1)
    nutrients = _add(fs, "feed", 0, Y_SPINE, "Nutrients (N, P)", FEED_NUTRIENTS)
    _set(nutrients, component=5)
    prep = _add(fs, "media_prep", 1, Y_SPINE, "Media prep", MEDIA_PREP)
    fs.add_link(water.id, "out", prep.id, "water")
    fs.add_link(nutrients.id, "out", prep.id, "nutrients")

    row = Y_SPINE + DY
    if scn.materials:
        label = scn.materials[0].name if len(scn.materials) == 1 else "Media chemicals"
        chem = _add(fs, "feed", 0, row, label, FEED_CHEMICALS)
        _set(chem, component=5)
        fs.add_link(chem.id, "out", prep.id, "chemicals")
        row += DY
    if scn.waste_feed.enabled:
        waste = _add(fs, "feed", 0, row, scn.waste_feed.name or "Waste-derived feed", FEED_WASTE)
        _set(waste, component=1)
        fs.add_link(waste.id, "out", prep.id, "waste")

    # -- cultivation (spine column 2) ----------------------------------- #
    cult = _add(fs, cultivation_kind(scn), 2, Y_SPINE, scn.system.name, CULTIVATION)
    fs.add_link(prep.id, "media", cult.id, "media")

    # seed inoculum -> reactor (above the prep tank)
    inoc = _add(fs, "feed", 1, Y_SPINE - DY, "Inoculum (seed)", FEED_INOCULUM)
    _set(inoc, component=0)
    fs.add_link(inoc.id, "out", cult.id, "inoculum")

    # carbon source -> reactor (below the prep tank)
    if phototrophic:
        if scn.system.carbon_source == CarbonSource.BICARBONATE:
            carbon = _add(fs, "feed", 1, Y_SPINE + DY, "NaHCO₃ (carbon source)", FEED_CARBON)
            _set(carbon, component=2)
        else:
            carbon = _add(fs, "co2_supply", 1, Y_SPINE + DY, "CO₂ supply", FEED_CARBON)
        fs.add_link(carbon.id, "out", cult.id, "co2")
    else:
        substrate = _add(fs, "feed", 1, Y_SPINE + DY, "Organic substrate", FEED_SUBSTRATE)
        _set(substrate, component=2)
        fs.add_link(substrate.id, "out", cult.id, "substrate")

    # The spine advances one node at a time; ``prev`` tracks the live outlet.
    col = 3
    prev_node, prev_port = cult.id, "broth"

    # -- dewatering train ----------------------------------------------- #
    stages = harvest_chain(scn)
    for i, kind in enumerate(stages):
        name = scn.harvesting.name if len(stages) == 1 else f"{scn.harvesting.name} ({i + 1})"
        dw = _add(fs, kind, col, Y_SPINE, name, HARVEST if i == 0 else f"{HARVEST}:{i + 1}")
        fs.add_link(prev_node, prev_port, dw.id, "feed")
        eff = _add(fs, "waste", col, Y_SINK, "Effluent" if i == 0 else f"Effluent {i + 1}",
                   EFFLUENT if i == 0 else f"{EFFLUENT}:{i + 1}")
        fs.add_link(dw.id, "effluent", eff.id, "in")
        prev_node, prev_port = dw.id, "concentrate"
        col += 1

    # -- drying --------------------------------------------------------- #
    dk = dryer_kind(scn)
    if dk is not None:
        dry = _add(fs, dk, col, Y_SPINE, scn.drying.name, DRYING)
        fs.add_link(prev_node, prev_port, dry.id, "feed")
        vap = _add(fs, "waste", col, Y_SINK, "Evaporated water", VAPOUR)
        fs.add_link(dry.id, "vapour", vap.id, "in")
        prev_node, prev_port = dry.id, "dry"
        col += 1

    # -- downstream: disruption + extraction ---------------------------- #
    if scn.extraction.enabled:
        drk = disruption_kind(scn)
        if drk is not None:
            disr = _add(fs, drk, col, Y_SPINE, "Cell disruption", DISRUPTION)
            fs.add_link(prev_node, prev_port, disr.id, "feed")
            prev_node, prev_port = disr.id, "out"
            col += 1

        ext = _add(fs, extractor_kind(scn), col, Y_SPINE, scn.extraction.name, EXTRACTION)
        fs.add_link(prev_node, prev_port, ext.id, "feed")
        if scn.extraction.solvent_kg_per_kg > 0.0:
            solv = _add(fs, "feed", col, Y_SOLVENT, scn.extraction.solvent_name, FEED_SOLVENT)
            _set(solv, component=4)
            fs.add_link(solv.id, "out", ext.id, "solvent")
        raff = _add(fs, "waste", col, Y_SINK, "Spent biomass", SPENT)
        fs.add_link(ext.id, "raffinate", raff.id, "in")
        prev_node, prev_port = ext.id, "extract"
        col += 1

    # -- product sink --------------------------------------------------- #
    prod = _add(fs, "product", col, Y_SPINE, _product_name(scn, results), PRODUCT)
    fs.add_link(prev_node, prev_port, prod.id, "in")

    seed_flows(fs, scn, results)
    return fs


def _product_name(scn: Scenario, results) -> str:
    if results is not None and getattr(results, "main_product", None) is not None:
        return results.main_product.name
    if scn.products:
        main = next((p for p in scn.products if p.is_main), scn.products[0])
        return main.name
    return (scn.product_name or "Dry biomass").strip().capitalize()


def harvest_recovery_on_canvas(fs: M.Flowsheet) -> float:
    """Overall solids recovery of the drawn dewatering train (for checks)."""
    stages = [n for n in fs.nodes.values() if n.role.split(":")[0] == HARVEST]
    return math.prod(n.params.get("solids_recovery", 1.0) for n in stages) if stages else 1.0
