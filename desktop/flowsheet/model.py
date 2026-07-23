"""Flowsheet data model, unit-operation registry and mass-balance solver.

The model is deliberately UI-agnostic and JSON-serialisable so it can be saved,
reloaded and (later) mapped onto the calculation engine in ``microalgae_tea_lca``.

A :class:`Flowsheet` is a bag of :class:`UnitNode` blocks connected by
:class:`StreamLink` streams. Every unit type is described by a :class:`UnitSpec`
in :data:`UNIT_TYPES`, which declares its ports, editable parameters and a
``transfer`` function. :func:`solve` walks the graph in topological order and
propagates material flows so every stream carries a plausible number.

Flows are plain dicts ``{component: kg_per_h}`` over :data:`COMPONENTS`. The
balance is first-pass (no recycle convergence, no energy closure); it exists to
make the canvas feel alive and to sanity-check the topology, not to replace the
rigorous per-kg inventory in :mod:`microalgae_tea_lca.inventory`.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Material flow: a dict of component -> kg/h
# --------------------------------------------------------------------------- #
# Dry active biomass, its associated water, extraction solvent, an extracted
# product/oil, an organic substrate (heterotrophic feed), CO2, and a catch-all.
COMPONENTS: tuple[str, ...] = (
    "biomass",
    "water",
    "solvent",
    "product",
    "substrate",
    "co2",
    "other",
)

Flow = dict[str, float]


def empty_flow() -> Flow:
    return {c: 0.0 for c in COMPONENTS}


def flow_from(**parts: float) -> Flow:
    f = empty_flow()
    for k, v in parts.items():
        if k in f:
            f[k] += float(v)
        else:
            f["other"] += float(v)
    return f


def flow_add(a: Mapping[str, float], b: Mapping[str, float]) -> Flow:
    out = empty_flow()
    for k in COMPONENTS:
        out[k] = float(a.get(k, 0.0)) + float(b.get(k, 0.0))
    return out


def flow_scale(a: Mapping[str, float], k: float) -> Flow:
    return {c: float(a.get(c, 0.0)) * k for c in COMPONENTS}


def flow_total(a: Mapping[str, float]) -> float:
    return sum(float(a.get(c, 0.0)) for c in COMPONENTS)


# --------------------------------------------------------------------------- #
# Parameter + unit-type specifications
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ParamSpec:
    """One editable parameter of a unit operation."""

    key: str
    label: str
    default: float
    unit: str = ""
    lo: float = 0.0
    hi: float = 1e12
    decimals: int = 3


# A transfer function maps (params, inputs) -> outputs.
#   params : the node's current parameter dict
#   inputs : {input_port_name: aggregated inbound Flow}
#   return : {output_port_name: outbound Flow}
Transfer = Callable[[Mapping[str, float], Mapping[str, Flow]], dict[str, Flow]]


@dataclass(frozen=True)
class UnitSpec:
    key: str
    label: str
    emoji: str
    category: str            # drives palette grouping and node colour
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    params: tuple[ParamSpec, ...]
    transfer: Transfer
    hint: str = ""
    icon: str = ""           # key into desktop.flowsheet.icons.ICONS
    tag_prefix: str = "U"    # equipment-tag class code, e.g. "FR" -> FR-101

    def default_params(self) -> dict[str, float]:
        return {p.key: p.default for p in self.params}


# Category -> header colour (hex). Kept in sync with the palette legend.
CATEGORY_COLORS: dict[str, str] = {
    "io": "#607d8b",           # feeds / products
    "cultivation": "#2e7d32",  # reactors, ponds, fermenters
    "separation": "#1565c0",   # dewatering, filtration, splitters
    "thermal": "#e65100",      # drying, evaporation
    "downstream": "#6a1b9a",   # disruption, extraction, purification
    "logic": "#455a64",        # mixer / splitter helpers
}


def _first_in(inputs: Mapping[str, Flow]) -> Flow:
    """Aggregate everything arriving at a single-input node."""
    total = empty_flow()
    for f in inputs.values():
        total = flow_add(total, f)
    return total


# --------------------------------------------------------------------------- #
# Transfer functions (first-pass balances)
# --------------------------------------------------------------------------- #
_FEED_COMPONENT = {0: "biomass", 1: "water", 2: "substrate", 3: "co2", 4: "solvent", 5: "other"}


def _t_feed(p, _inputs):
    """A source stream of a single component."""
    comp = _FEED_COMPONENT.get(int(p.get("component", 1)), "water")
    return {"out": flow_from(**{comp: p.get("flow_kg_h", 0.0)})}


def _t_cultivation(p, inputs):
    """Reactor/pond/fermenter: produce dry biomass at a target broth concentration.

    Output broth = produced biomass + the water needed to hit ``harvest_conc``
    (g/L ~ kg/m3, water taken as 1000 kg/m3), plus any inbound substrate/CO2 that
    is not converted is dropped (first-pass: producer node)."""
    biomass = max(p.get("biomass_kg_h", 0.0), 0.0)
    conc = max(p.get("harvest_conc_g_l", 1.0), 1e-3)
    water = biomass * (1000.0 / conc - 1.0)
    return {"broth": flow_from(biomass=biomass, water=max(water, 0.0))}


def _t_dewatering(p, inputs):
    """Concentrate biomass to ``final_solids`` recovering ``solids_recovery``.

    Concentrate carries the recovered solids plus the water implied by the target
    solids fraction; the balance leaves in the effluent."""
    f = _first_in(inputs)
    rec = min(max(p.get("solids_recovery", 0.95), 0.0), 1.0)
    fs = min(max(p.get("final_solids", 0.2), 1e-3), 1.0)
    solids_in = f["biomass"]
    solids_out = solids_in * rec
    water_with_solids = solids_out * (1.0 - fs) / fs
    water_out = min(water_with_solids, f["water"])
    concentrate = flow_from(biomass=solids_out, water=water_out)
    effluent = flow_from(
        biomass=solids_in - solids_out,
        water=max(f["water"] - water_out, 0.0),
    )
    return {"concentrate": concentrate, "effluent": effluent}


def _t_drying(p, inputs):
    """Thermal drying to ``final_solids``; evaporated water leaves as vapour."""
    f = _first_in(inputs)
    fs = min(max(p.get("final_solids", 0.92), 1e-3), 1.0)
    solids = f["biomass"]
    water_out = solids * (1.0 - fs) / fs
    water_out = min(water_out, f["water"])
    dry = flow_from(biomass=solids, water=water_out, product=f["product"])
    vapour = flow_from(water=max(f["water"] - water_out, 0.0))
    return {"dry": dry, "vapour": vapour}


def _t_disruption(p, inputs):
    """Cell disruption: mass is conserved (adds energy only)."""
    return {"out": _first_in(inputs)}


def _t_extraction(p, inputs):
    """Solvent extraction: split a product fraction out of the biomass.

    ``extract_yield`` of the inbound biomass reports to the extract as product;
    the rest stays with the raffinate. Net solvent make-up = solvent in *
    (1 - recovery); the recovered solvent is assumed recycled (not tracked)."""
    f = _first_in(inputs)
    y = min(max(p.get("extract_yield", 0.25), 0.0), 1.0)
    rec = min(max(p.get("solvent_recovery", 0.95), 0.0), 1.0)
    product = f["biomass"] * y
    extract = flow_from(product=product, solvent=f["solvent"] * (1.0 - rec))
    raffinate = flow_from(
        biomass=f["biomass"] * (1.0 - y),
        water=f["water"],
    )
    return {"extract": extract, "raffinate": raffinate}


def _t_mixer(p, inputs):
    return {"out": _first_in(inputs)}


def _t_media_prep(p, inputs):
    """Media preparation tank: blend water, nutrients and chemicals into media."""
    return {"media": _first_in(inputs)}


def _t_splitter(p, inputs):
    f = _first_in(inputs)
    frac = min(max(p.get("split_fraction", 0.5), 0.0), 1.0)
    return {"out_a": flow_scale(f, frac), "out_b": flow_scale(f, 1.0 - frac)}


def _t_product(p, inputs):
    """Sink: nothing leaves. The inbound flow is the reported product."""
    return {}


def _t_feed_co2(p, _inputs):
    """A CO2 gas source."""
    return {"out": flow_from(co2=p.get("flow_kg_h", 0.0))}


def _t_evaporator(p, inputs):
    """Concentrate a liquid stream by boiling off ``water_removal`` of its water."""
    f = _first_in(inputs)
    removal = min(max(p.get("water_removal", 0.8), 0.0), 1.0)
    vapour = flow_from(water=f["water"] * removal)
    concentrate = flow_from(
        biomass=f["biomass"],
        water=f["water"] * (1.0 - removal),
        product=f["product"],
        substrate=f["substrate"],
        solvent=f["solvent"],
    )
    return {"concentrate": concentrate, "vapour": vapour}


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
# Shared parameter groups (kept DRY across similar equipment).
def _p_cult(conc: float) -> tuple[ParamSpec, ...]:
    return (
        ParamSpec("biomass_kg_h", "Biomass produced", 100.0, "kg/h", 0, 1e12, 2),
        ParamSpec("harvest_conc_g_l", "Harvest concentration", conc, "g/L", 0.01, 1e6, 3),
    )


def _p_dewater(rec: float, fs: float) -> tuple[ParamSpec, ...]:
    return (
        ParamSpec("solids_recovery", "Solids recovery", rec, "frac", 0, 1, 3),
        ParamSpec("final_solids", "Final solids", fs, "frac", 0.001, 1, 3),
    )


def _p_dry(fs: float) -> tuple[ParamSpec, ...]:
    return (ParamSpec("final_solids", "Final solids", fs, "frac", 0.001, 1, 3),)


UNIT_TYPES: dict[str, UnitSpec] = {
    # --- feeds & products (io) ---------------------------------------- #
    "feed": UnitSpec(
        "feed", "Feed / Media", "🚰", "io",
        inputs=(), outputs=("out",),
        params=(
            ParamSpec("component", "Component (0=biomass 1=water 2=substrate 3=CO2 4=solvent 5=other)", 1, "", 0, 5, 0),
            ParamSpec("flow_kg_h", "Flow", 1000.0, "kg/h", 0, 1e12, 1),
        ),
        transfer=_t_feed, icon="tank", tag_prefix="FD",
        hint="A raw-material source: water/media, nutrients, substrate, CO2 or solvent.",
    ),
    "co2_supply": UnitSpec(
        "co2_supply", "CO₂ supply", "🫧", "io",
        inputs=(), outputs=("out",),
        params=(ParamSpec("flow_kg_h", "CO₂ flow", 200.0, "kg/h", 0, 1e12, 1),),
        transfer=_t_feed_co2, icon="gas", tag_prefix="GS",
        hint="A CO2 gas source feeding phototrophic reactors.",
    ),
    "product": UnitSpec(
        "product", "Product", "📦", "io",
        inputs=("in",), outputs=(),
        params=(), transfer=_t_product, icon="drum", tag_prefix="PR",
        hint="A product sink. Its inbound flow is the reported yield.",
    ),
    "waste": UnitSpec(
        "waste", "Waste / effluent", "🗑", "io",
        inputs=("in",), outputs=(),
        params=(), transfer=_t_product, icon="waste", tag_prefix="WS",
        hint="A waste / effluent sink (spent water, residual solids).",
    ),

    # --- cultivation / bioreactors ------------------------------------ #
    "raceway": UnitSpec(
        "raceway", "Raceway pond", "🦠", "cultivation",
        inputs=("inoculum", "media", "co2"), outputs=("broth",),
        params=_p_cult(0.5), transfer=_t_cultivation, icon="raceway", tag_prefix="PD",
        hint="Open raceway pond (phototrophic, low cell density).",
    ),
    "tubular_pbr": UnitSpec(
        "tubular_pbr", "Tubular PBR", "🦠", "cultivation",
        inputs=("inoculum", "media", "co2"), outputs=("broth",),
        params=_p_cult(2.0), transfer=_t_cultivation, icon="tubular", tag_prefix="TPB",
        hint="Closed tubular photobioreactor.",
    ),
    "flat_panel_pbr": UnitSpec(
        "flat_panel_pbr", "Flat-panel PBR", "🦠", "cultivation",
        inputs=("inoculum", "media", "co2"), outputs=("broth",),
        params=_p_cult(3.0), transfer=_t_cultivation, icon="flat_panel", tag_prefix="FPB",
        hint="Flat-panel photobioreactor (high areal productivity).",
    ),
    "bubble_column_pbr": UnitSpec(
        "bubble_column_pbr", "Bubble-column PBR", "🦠", "cultivation",
        inputs=("inoculum", "media", "co2"), outputs=("broth",),
        params=_p_cult(1.5), transfer=_t_cultivation, icon="bubble_column", tag_prefix="BCR",
        hint="Bubble-column / airlift photobioreactor.",
    ),
    "fermenter": UnitSpec(
        "fermenter", "Stirred-tank fermenter", "🧫", "cultivation",
        inputs=("inoculum", "media", "substrate"), outputs=("broth",),
        params=_p_cult(100.0), transfer=_t_cultivation, icon="stirred_tank", tag_prefix="FR",
        hint="Heterotrophic stirred-tank fermenter (high cell density).",
    ),

    # --- separation / dewatering -------------------------------------- #
    "centrifuge": UnitSpec(
        "centrifuge", "Disk-stack centrifuge", "💧", "separation",
        inputs=("feed",), outputs=("concentrate", "effluent"),
        params=_p_dewater(0.95, 0.22), transfer=_t_dewatering, icon="centrifuge", tag_prefix="CF",
        hint="Disk-stack centrifuge: continuous biomass concentration.",
    ),
    "decanter": UnitSpec(
        "decanter", "Decanter centrifuge", "💧", "separation",
        inputs=("feed",), outputs=("concentrate", "effluent"),
        params=_p_dewater(0.93, 0.25), transfer=_t_dewatering, icon="decanter", tag_prefix="DC",
        hint="Horizontal decanter centrifuge for thicker slurries.",
    ),
    "membrane": UnitSpec(
        "membrane", "Membrane filtration", "💧", "separation",
        inputs=("feed",), outputs=("concentrate", "effluent"),
        params=_p_dewater(0.98, 0.15), transfer=_t_dewatering, icon="membrane", tag_prefix="MF",
        hint="Micro/ultra-filtration membrane pre-concentration.",
    ),
    "crossflow_uf": UnitSpec(
        "crossflow_uf", "Cross-flow UF (tangential)", "💧", "separation",
        inputs=("feed",), outputs=("concentrate", "effluent"),
        params=_p_dewater(0.95, 0.08), transfer=_t_dewatering, icon="membrane", tag_prefix="UF",
        hint="Tangential cross-flow ultrafiltration: low-energy pre-concentration, gentle on cells.",
    ),
    "filter_press": UnitSpec(
        "filter_press", "Filter press", "💧", "separation",
        inputs=("feed",), outputs=("concentrate", "effluent"),
        params=_p_dewater(0.97, 0.30), transfer=_t_dewatering, icon="filter_press", tag_prefix="FP",
        hint="Plate-and-frame filter press producing a dewatered cake.",
    ),
    "settler": UnitSpec(
        "settler", "Settling tank", "💧", "separation",
        inputs=("feed",), outputs=("concentrate", "effluent"),
        params=_p_dewater(0.85, 0.08), transfer=_t_dewatering, icon="settler", tag_prefix="ST",
        hint="Gravity settler / flocculation thickener (cheap, low solids).",
    ),

    # --- thermal ------------------------------------------------------- #
    "spray_dryer": UnitSpec(
        "spray_dryer", "Spray dryer", "🔥", "thermal",
        inputs=("feed",), outputs=("dry", "vapour"),
        params=_p_dry(0.95), transfer=_t_drying, icon="spray_dryer", tag_prefix="SD",
        hint="Spray dryer: atomised feed dried to a free-flowing powder.",
    ),
    "drum_dryer": UnitSpec(
        "drum_dryer", "Drum dryer", "🔥", "thermal",
        inputs=("feed",), outputs=("dry", "vapour"),
        params=_p_dry(0.92), transfer=_t_drying, icon="drum_dryer", tag_prefix="DD",
        hint="Drum dryer: paste dried on a heated rotating drum.",
    ),
    "freeze_dryer": UnitSpec(
        "freeze_dryer", "Freeze dryer", "🔥", "thermal",
        inputs=("feed",), outputs=("dry", "vapour"),
        params=_p_dry(0.97), transfer=_t_drying, icon="freeze_dryer", tag_prefix="FZ",
        hint="Lyophiliser: gentle drying that preserves heat-labile actives.",
    ),
    "evaporator": UnitSpec(
        "evaporator", "Evaporator", "🔥", "thermal",
        inputs=("feed",), outputs=("concentrate", "vapour"),
        params=(ParamSpec("water_removal", "Water removed", 0.8, "frac", 0, 1, 3),),
        transfer=_t_evaporator, icon="evaporator", tag_prefix="EV",
        hint="Evaporator: boil off water to concentrate a liquid stream.",
    ),

    # --- downstream ---------------------------------------------------- #
    "bead_mill": UnitSpec(
        "bead_mill", "Bead mill", "⚙", "downstream",
        inputs=("feed",), outputs=("out",),
        params=(), transfer=_t_disruption, icon="bead_mill", tag_prefix="BM",
        hint="Bead mill: mechanical cell disruption. Mass-conserving.",
    ),
    "homogenizer": UnitSpec(
        "homogenizer", "High-pressure homogenizer", "⚙", "downstream",
        inputs=("feed",), outputs=("out",),
        params=(), transfer=_t_disruption, icon="homogenizer", tag_prefix="HG",
        hint="High-pressure homogeniser: cell disruption. Mass-conserving.",
    ),
    "extraction": UnitSpec(
        "extraction", "Solvent extraction", "🧪", "downstream",
        inputs=("feed", "solvent"), outputs=("extract", "raffinate"),
        params=(
            ParamSpec("extract_yield", "Extract yield (of biomass)", 0.25, "frac", 0, 1, 3),
            ParamSpec("solvent_recovery", "Solvent recovery", 0.95, "frac", 0, 1, 3),
        ),
        transfer=_t_extraction, icon="extraction_column", tag_prefix="EX",
        hint="Solvent extraction: pull a product fraction out of the biomass.",
    ),
    "supercritical_co2": UnitSpec(
        "supercritical_co2", "Supercritical CO2 extractor", "🧪", "downstream",
        inputs=("feed", "solvent"), outputs=("extract", "raffinate"),
        params=(
            ParamSpec("extract_yield", "Extract yield (of biomass)", 0.15, "frac", 0, 1, 3),
            ParamSpec("solvent_recovery", "CO2 recovery", 0.98, "frac", 0, 1, 3),
        ),
        transfer=_t_extraction, icon="extraction_column", tag_prefix="SCX",
        hint="Supercritical CO2 (20-45 MPa): solvent-free extract; CO2 recycled >98%.",
    ),

    # --- logic / auxiliary -------------------------------------------- #
    "media_prep": UnitSpec(
        "media_prep", "Media prep", "🧪", "logic",
        inputs=("water", "nutrients", "chemicals"), outputs=("media",),
        params=(), transfer=_t_media_prep, icon="stirred_tank", tag_prefix="MP",
        hint="Media preparation tank: blends water, nutrient salts and chemicals "
             "into the culture medium fed to the reactor.",
    ),
    "mixer": UnitSpec(
        "mixer", "Mixer", "➕", "logic",
        inputs=("in_a", "in_b"), outputs=("out",),
        params=(), transfer=_t_mixer, icon="mixer", tag_prefix="MX",
        hint="Combine two or more streams into one.",
    ),
    "splitter": UnitSpec(
        "splitter", "Splitter", "🔀", "logic",
        inputs=("feed",), outputs=("out_a", "out_b"),
        params=(ParamSpec("split_fraction", "Fraction to A", 0.5, "frac", 0, 1, 3),),
        transfer=_t_splitter, icon="splitter", tag_prefix="SP",
        hint="Split one stream into two by a fixed fraction.",
    ),
    "pump": UnitSpec(
        "pump", "Pump", "🔄", "logic",
        inputs=("in",), outputs=("out",),
        params=(), transfer=_t_disruption, icon="pump", tag_prefix="PU",
        hint="Transfer pump (visual only; mass-conserving).",
    ),
    "heat_exchanger": UnitSpec(
        "heat_exchanger", "Heat exchanger", "♨", "logic",
        inputs=("in",), outputs=("out",),
        params=(), transfer=_t_disruption, icon="hx", tag_prefix="HX",
        hint="Heat exchanger (visual only; mass-conserving).",
    ),
}


def spec(kind: str) -> UnitSpec:
    return UNIT_TYPES[kind]


# --------------------------------------------------------------------------- #
# Graph data model
# --------------------------------------------------------------------------- #
@dataclass
class UnitNode:
    id: str
    kind: str
    name: str
    x: float = 0.0
    y: float = 0.0
    params: dict[str, float] = field(default_factory=dict)
    tag: str = ""              # equipment tag, e.g. "FR-101"

    @property
    def spec(self) -> UnitSpec:
        return UNIT_TYPES[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "tag": self.tag,
            "x": self.x,
            "y": self.y,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "UnitNode":
        node = cls(
            id=str(d["id"]),
            kind=str(d["kind"]),
            name=str(d.get("name", "")),
            tag=str(d.get("tag", "")),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            params=dict(d.get("params", {})),
        )
        # Backfill any parameters added since the file was saved.
        for k, v in node.spec.default_params().items():
            node.params.setdefault(k, v)
        return node


def _next_tag(nodes: Mapping[str, "UnitNode"], prefix: str) -> str:
    """Next free area-100 equipment tag for ``prefix`` (FR-101, FR-102, …)."""
    nums = []
    for n in nodes.values():
        if n.tag.startswith(prefix + "-"):
            try:
                nums.append(int(n.tag.split("-", 1)[1]))
            except ValueError:
                pass
    return f"{prefix}-{(max(nums) if nums else 100) + 1}"


@dataclass
class StreamLink:
    id: str
    src_node: str
    src_port: str
    dst_node: str
    dst_port: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "src_node": self.src_node,
            "src_port": self.src_port,
            "dst_node": self.dst_node,
            "dst_port": self.dst_port,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StreamLink":
        return cls(
            id=str(d["id"]),
            src_node=str(d["src_node"]),
            src_port=str(d["src_port"]),
            dst_node=str(d["dst_node"]),
            dst_port=str(d["dst_port"]),
        )


@dataclass
class Flowsheet:
    nodes: dict[str, UnitNode] = field(default_factory=dict)
    links: dict[str, StreamLink] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1), repr=False)

    # -- node / link mutation ------------------------------------------- #
    def new_id(self, prefix: str) -> str:
        while True:
            cand = f"{prefix}{next(self._ids)}"
            if cand not in self.nodes and cand not in self.links:
                return cand

    def add_node(self, kind: str, x: float, y: float, name: str | None = None) -> UnitNode:
        sp = UNIT_TYPES[kind]
        nid = self.new_id("n")
        node = UnitNode(
            id=nid,
            kind=kind,
            name=name or sp.label,
            tag=_next_tag(self.nodes, sp.tag_prefix),
            x=x, y=y,
            params=sp.default_params(),
        )
        self.nodes[nid] = node
        return node

    def add_link(self, src_node: str, src_port: str, dst_node: str, dst_port: str) -> StreamLink | None:
        if src_node not in self.nodes or dst_node not in self.nodes:
            return None
        if src_node == dst_node:
            return None
        # One inbound link per input port (a port cannot be fed twice).
        for lk in list(self.links.values()):
            if lk.dst_node == dst_node and lk.dst_port == dst_port:
                del self.links[lk.id]
        lid = self.new_id("s")
        link = StreamLink(lid, src_node, src_port, dst_node, dst_port)
        self.links[lid] = link
        return link

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        for lid in [lid for lid, lk in self.links.items()
                    if lk.src_node == node_id or lk.dst_node == node_id]:
            del self.links[lid]

    def remove_link(self, link_id: str) -> None:
        self.links.pop(link_id, None)

    # -- serialisation --------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "links": [lk.to_dict() for lk in self.links.values()],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Flowsheet":
        fs = cls()
        max_num = 0
        for nd in d.get("nodes", []):
            if nd.get("kind") not in UNIT_TYPES:
                continue  # tolerate flowsheets saved with equipment we no longer ship
            node = UnitNode.from_dict(nd)
            if not node.tag:
                node.tag = _next_tag(fs.nodes, node.spec.tag_prefix)
            fs.nodes[node.id] = node
            max_num = max(max_num, _id_num(node.id))
        for ld in d.get("links", []):
            link = StreamLink.from_dict(ld)
            if link.src_node in fs.nodes and link.dst_node in fs.nodes:
                fs.links[link.id] = link
                max_num = max(max_num, _id_num(link.id))
        fs._ids = itertools.count(max_num + 1)
        return fs


def _id_num(ident: str) -> int:
    digits = "".join(ch for ch in ident if ch.isdigit())
    return int(digits) if digits else 0


# --------------------------------------------------------------------------- #
# Solver
# --------------------------------------------------------------------------- #
@dataclass
class SolveResult:
    stream_flows: dict[str, Flow]              # link_id -> Flow on that stream
    node_outputs: dict[str, dict[str, Flow]]   # node_id -> {out_port: Flow}
    warnings: list[str]

    def product_flows(self, fs: Flowsheet) -> dict[str, Flow]:
        """Inbound flow at every ``product`` sink, keyed by node name."""
        out: dict[str, Flow] = {}
        for node in fs.nodes.values():
            if node.kind != "product":
                continue
            agg = empty_flow()
            for lk in fs.links.values():
                if lk.dst_node == node.id and lk.id in self.stream_flows:
                    agg = flow_add(agg, self.stream_flows[lk.id])
            out[node.name] = agg
        return out


def _topo_order(fs: Flowsheet) -> tuple[list[str], list[str]]:
    """Kahn's algorithm. Returns (ordered_node_ids, nodes_in_cycles)."""
    indeg = {nid: 0 for nid in fs.nodes}
    succ: dict[str, list[str]] = {nid: [] for nid in fs.nodes}
    for lk in fs.links.values():
        if lk.src_node in fs.nodes and lk.dst_node in fs.nodes:
            indeg[lk.dst_node] += 1
            succ[lk.src_node].append(lk.dst_node)
    queue = [nid for nid, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for m in succ[nid]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    in_cycle = [nid for nid, d in indeg.items() if d > 0]
    return order, in_cycle


def solve(fs: Flowsheet) -> SolveResult:
    """Propagate material flows through the graph in topological order.

    Recycle loops are not converged: any node inside a cycle is evaluated once
    with whatever inbound flow is available and reported as a warning."""
    order, in_cycle = _topo_order(fs)
    warnings: list[str] = []
    if in_cycle:
        names = ", ".join(fs.nodes[n].name for n in in_cycle if n in fs.nodes)
        warnings.append(f"Recycle loop not converged (single pass): {names}")
        order = order + in_cycle  # still evaluate them once, after the acyclic part

    node_outputs: dict[str, dict[str, Flow]] = {}
    stream_flows: dict[str, Flow] = {lid: empty_flow() for lid in fs.links}

    for nid in order:
        node = fs.nodes[nid]
        sp = node.spec
        # Aggregate inbound flows per input port.
        inbound: dict[str, Flow] = {port: empty_flow() for port in sp.inputs}
        for lk in fs.links.values():
            if lk.dst_node != nid:
                continue
            if lk.dst_port not in inbound:
                inbound[lk.dst_port] = empty_flow()
            src_out = node_outputs.get(lk.src_node, {})
            inbound[lk.dst_port] = flow_add(
                inbound[lk.dst_port], src_out.get(lk.src_port, empty_flow())
            )
        try:
            outs = sp.transfer(node.params, inbound)
        except Exception as exc:  # keep the canvas usable on a bad parameter
            warnings.append(f"{node.name}: {exc}")
            outs = {port: empty_flow() for port in sp.outputs}
        # Normalise: guarantee every declared output port has a Flow.
        node_outputs[nid] = {port: outs.get(port, empty_flow()) for port in sp.outputs}
        # Push onto outbound streams.
        for lk in fs.links.values():
            if lk.src_node == nid:
                stream_flows[lk.id] = node_outputs[nid].get(lk.src_port, empty_flow())

    return SolveResult(stream_flows=stream_flows, node_outputs=node_outputs, warnings=warnings)


# --------------------------------------------------------------------------- #
# Starter flowsheet
# --------------------------------------------------------------------------- #
def starter_flowsheet() -> Flowsheet:
    """A small ready-made train so the canvas is never empty on first open:

    Media feed -> Cultivation -> Dewatering -> Drying -> Product,
    with the dewatering effluent going to a waste sink."""
    fs = Flowsheet()
    feed = fs.add_node("feed", -600, -30, "Media feed")
    cult = fs.add_node("fermenter", -350, -30, "Fermenter")
    dew = fs.add_node("centrifuge", -90, -30, "Centrifuge")
    dry = fs.add_node("spray_dryer", 170, -70, "Spray dryer")
    prod = fs.add_node("product", 430, -70, "Dry biomass")
    waste = fs.add_node("waste", 170, 110, "Effluent")

    fs.add_link(feed.id, "out", cult.id, "media")
    fs.add_link(cult.id, "broth", dew.id, "feed")
    fs.add_link(dew.id, "concentrate", dry.id, "feed")
    fs.add_link(dew.id, "effluent", waste.id, "in")
    fs.add_link(dry.id, "dry", prod.id, "in")
    return fs
