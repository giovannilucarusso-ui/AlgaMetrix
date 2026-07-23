"""Auto-generate a process flowsheet from a TEA/LCA :class:`Scenario`.

This is the bridge between the parametric case study (built by the setup wizard
and edited on the *Scenario* tab) and the visual *Process Designer*. Given the
same :class:`~microalgae_tea_lca.models.Scenario` that feeds the TEA and LCA, it
lays out an engineering-style process train — feeds, cultivation, dewatering,
drying and (optional) extraction — wired left-to-right with product and effluent
sinks, so the researcher always starts from *their* case instead of a generic
example.

The mapping is deliberately transparent:

* cultivation block   <- ``scenario.system``   (reactor/pond type & trophic mode)
* dewatering block(s) <- ``scenario.harvesting`` (may expand to a 2-stage train)
* drying block        <- ``scenario.drying``     (skipped when "wet paste")
* disruption + extractor <- ``scenario.extraction``

When a solved :class:`~microalgae_tea_lca.scenario.Results` is passed, the block
parameters and feed flows are seeded with the case's real numbers (from the
per-kg :class:`~microalgae_tea_lca.inventory.Inventory`), so the first-pass
balance on the canvas lands in the same ballpark as the rigorous engine.

The function is pure (no Qt): it returns a :class:`~desktop.flowsheet.model.Flowsheet`
and can be unit-tested against the engine alone.
"""

from __future__ import annotations

from microalgae_tea_lca.models import CarbonSource, Scenario, TrophicMode

from . import model as M

# --------------------------------------------------------------------------- #
# Layout geometry (scene coordinates; a NodeItem is ~182 x 122)
# --------------------------------------------------------------------------- #
DX = 250.0          # horizontal spacing between spine columns
DY = 170.0          # vertical spacing for feeds / sinks off the spine
X0 = -560.0         # x of the feed column (spine starts one column to its right)
Y_SPINE = -20.0     # baseline y of the main process spine
Y_FEED_HI = Y_SPINE - 78.0   # upper feed (media / water)
Y_FEED_LO = Y_SPINE + 78.0   # lower feed (carbon source / substrate)
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
    # raceway, open pond, thin-layer cascade, and any other open system
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
    if "screen" in n or "rotary" in n or "drum filter" in n or "press" in n or "filter" in n:
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


class _Flows:
    """Hourly stream flows derived from the case (per-hour, not per-kg)."""

    def __init__(self, scn: Scenario, results) -> None:
        op_h = _op_hours(scn)
        rec = _clamp(scn.harvesting.recovery, 1e-3, 1.0)
        # Extraction yield that makes the canvas product stream equal the engine's
        # main product rate: main_kg = biomass_kg * (main_annual / biomass_annual).
        self.extract_yield = None
        if results is not None and results.inventory.annual_biomass_kg > 0:
            inv = results.inventory
            self.net_kg_h = inv.annual_biomass_kg / op_h        # product leaving the gate
            self.gross_kg_h = self.net_kg_h / rec               # biomass out of cultivation
            self.water_kg_h = inv.water_m3_per_kg * 1000.0 * self.net_kg_h
            self.co2_kg_h = inv.co2_supply_per_kg * self.net_kg_h
            self.bicarb_kg_h = inv.bicarbonate_supply_per_kg * self.net_kg_h
            self.substrate_kg_h = inv.substrate_per_kg * self.net_kg_h
            self.nutrients_kg_h = (inv.nitrogen_per_kg + inv.phosphorus_per_kg) * self.net_kg_h
            mp = getattr(results, "main_product", None)
            if mp is not None and mp.annual_kg > 0:
                self.extract_yield = _clamp(mp.annual_kg / inv.annual_biomass_kg, 1e-4, 1.0)
            self.known = True
        else:
            self.gross_kg_h = 100.0
            self.net_kg_h = self.gross_kg_h * rec
            conc = _clamp(scn.system.biomass_conc, 1e-3, 1e6)
            self.water_kg_h = self.gross_kg_h * (1000.0 / conc - 1.0)
            self.co2_kg_h = 200.0
            self.bicarb_kg_h = 0.0
            self.substrate_kg_h = 0.0
            self.nutrients_kg_h = self.gross_kg_h * 0.02
            self.known = False
        self.solvent_kg_h = scn.extraction.solvent_kg_per_kg * self.net_kg_h
        # Recipe chemicals (media components, process aids) and a seed inoculum.
        self.chemicals_kg_h = sum(m.amount_per_kg for m in scn.materials) * self.net_kg_h
        self.inoculum_kg_h = self.gross_kg_h * 0.05


def _set(node: M.UnitNode, **params: float) -> None:
    """Set only the parameters the node's spec actually declares."""
    valid = {p.key for p in node.spec.params}
    for k, v in params.items():
        if k in valid:
            node.params[k] = float(v)


# --------------------------------------------------------------------------- #
# The builder
# --------------------------------------------------------------------------- #
def flowsheet_from_scenario(scn: Scenario, results=None) -> M.Flowsheet:
    """Construct a process :class:`Flowsheet` mirroring ``scn``.

    ``results`` (an optional solved :class:`~microalgae_tea_lca.scenario.Results`)
    seeds realistic flows; without it, nominal defaults keep the canvas sensible.
    """
    fs = M.Flowsheet()
    flows = _Flows(scn, results)
    phototrophic = scn.system.mode == TrophicMode.PHOTOTROPHIC

    # -- cultivation (spine column 2) ----------------------------------- #
    cult = fs.add_node(cultivation_kind(scn), _col_x(2), Y_SPINE, scn.system.name)
    _set(cult, biomass_kg_h=flows.gross_kg_h, harvest_conc_g_l=scn.system.biomass_conc)

    # -- media preparation (column 1) ----------------------------------- #
    # Water + nutrient salts + recipe chemicals are blended in a prep tank whose
    # medium feeds the reactor; the seed inoculum and the carbon source connect
    # to the reactor directly.
    prep = fs.add_node("media_prep", _col_x(1), Y_SPINE, "Media prep")
    fs.add_link(prep.id, "media", cult.id, "media")

    water = fs.add_node("feed", _col_x(0), Y_SPINE - DY, "Water")
    _set(water, component=1, flow_kg_h=flows.water_kg_h)
    fs.add_link(water.id, "out", prep.id, "water")

    nutrients = fs.add_node("feed", _col_x(0), Y_SPINE, "Nutrients (N, P)")
    _set(nutrients, component=5, flow_kg_h=flows.nutrients_kg_h)
    fs.add_link(nutrients.id, "out", prep.id, "nutrients")

    if flows.chemicals_kg_h > 0.0:
        label = scn.materials[0].name if len(scn.materials) == 1 else "Media chemicals"
        chem = fs.add_node("feed", _col_x(0), Y_SPINE + DY, label)
        _set(chem, component=5, flow_kg_h=flows.chemicals_kg_h)
        fs.add_link(chem.id, "out", prep.id, "chemicals")

    # seed inoculum -> reactor (above the prep tank)
    inoc = fs.add_node("feed", _col_x(1), Y_SPINE - DY, "Inoculum (seed)")
    _set(inoc, component=0, flow_kg_h=flows.inoculum_kg_h)
    fs.add_link(inoc.id, "out", cult.id, "inoculum")

    # carbon source -> reactor (below the prep tank)
    if phototrophic:
        if scn.system.carbon_source == CarbonSource.BICARBONATE:
            carbon = fs.add_node("feed", _col_x(1), Y_SPINE + DY, "NaHCO₃ (carbon source)")
            _set(carbon, component=2, flow_kg_h=flows.bicarb_kg_h)
        else:
            carbon = fs.add_node("co2_supply", _col_x(1), Y_SPINE + DY, "CO₂ supply")
            _set(carbon, flow_kg_h=flows.co2_kg_h)
        fs.add_link(carbon.id, "out", cult.id, "co2")
    else:
        substrate = fs.add_node("feed", _col_x(1), Y_SPINE + DY, "Organic substrate")
        _set(substrate, component=2, flow_kg_h=flows.substrate_kg_h)
        fs.add_link(substrate.id, "out", cult.id, "substrate")

    # The spine advances one node at a time; ``prev`` tracks the live outlet.
    col = 3
    prev_node, prev_port = cult.id, "broth"

    # -- dewatering train ----------------------------------------------- #
    stages = harvest_chain(scn)
    for i, kind in enumerate(stages):
        name = scn.harvesting.name if len(stages) == 1 else f"{scn.harvesting.name} ({i + 1})"
        dw = fs.add_node(kind, _col_x(col), Y_SPINE, name)
        _set(dw, solids_recovery=scn.harvesting.recovery, final_solids=scn.harvesting.final_solids)
        fs.add_link(prev_node, prev_port, dw.id, "feed")
        eff = fs.add_node("waste", _col_x(col), Y_SINK, "Effluent" if i == 0 else f"Effluent {i + 1}")
        fs.add_link(dw.id, "effluent", eff.id, "in")
        prev_node, prev_port = dw.id, "concentrate"
        col += 1

    # -- drying --------------------------------------------------------- #
    dk = dryer_kind(scn)
    if dk is not None:
        dry = fs.add_node(dk, _col_x(col), Y_SPINE, scn.drying.name)
        _set(dry, final_solids=scn.drying.final_solids)
        fs.add_link(prev_node, prev_port, dry.id, "feed")
        vap = fs.add_node("waste", _col_x(col), Y_SINK, "Evaporated water")
        fs.add_link(dry.id, "vapour", vap.id, "in")
        prev_node, prev_port = dry.id, "dry"
        col += 1

    # -- downstream: disruption + extraction ---------------------------- #
    if scn.extraction.enabled:
        drk = disruption_kind(scn)
        if drk is not None:
            disr = fs.add_node(drk, _col_x(col), Y_SPINE, "Cell disruption")
            fs.add_link(prev_node, prev_port, disr.id, "feed")
            prev_node, prev_port = disr.id, "out"
            col += 1

        ext = fs.add_node(extractor_kind(scn), _col_x(col), Y_SPINE, scn.extraction.name)
        _set(ext, solvent_recovery=scn.extraction.solvent_recovery)
        if flows.extract_yield is not None:
            _set(ext, extract_yield=flows.extract_yield)
        fs.add_link(prev_node, prev_port, ext.id, "feed")
        if flows.solvent_kg_h > 0.0 or scn.extraction.solvent_kg_per_kg > 0.0:
            solv = fs.add_node("feed", _col_x(col), Y_SOLVENT, scn.extraction.solvent_name)
            _set(solv, component=4, flow_kg_h=flows.solvent_kg_h)
            fs.add_link(solv.id, "out", ext.id, "solvent")
        raff = fs.add_node("waste", _col_x(col), Y_SINK, "Spent biomass")
        fs.add_link(ext.id, "raffinate", raff.id, "in")
        prev_node, prev_port = ext.id, "extract"
        col += 1

    # -- product sink --------------------------------------------------- #
    prod = fs.add_node("product", _col_x(col), Y_SPINE, _product_name(scn, results))
    fs.add_link(prev_node, prev_port, prod.id, "in")

    return fs


def _product_name(scn: Scenario, results) -> str:
    if results is not None and getattr(results, "main_product", None) is not None:
        return results.main_product.name
    if scn.products:
        main = next((p for p in scn.products if p.is_main), scn.products[0])
        return main.name
    return (scn.product_name or "Dry biomass").strip().capitalize()
