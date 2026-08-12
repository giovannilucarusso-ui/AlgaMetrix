"""Shared-inventory consistency — recovering the physical flows each analysis used.

:mod:`verification` asks whether the mass balance closes. This module asks a
different question, and the one the shared-inventory architecture actually rests
on:

    *Is the quantity of each physical flow that the techno-economic analysis
    prices identical to the quantity of the same flow that the life-cycle
    analysis characterizes?*

What this is, and what it is not
--------------------------------
:func:`~algametrix.scenario.run_scenario` builds one
:class:`~algametrix.inventory.Inventory` and hands *the same object* to
:func:`~algametrix.tea.run_tea` and :func:`~algametrix.lca.run_lca`. Agreement is
therefore an **architectural invariant**, not an empirical finding: the checks
here are a *verification* that the invariant holds and stays holding, in the same
sense that a unit test verifies an interface contract. They are not an external
validation and say nothing about whether either analysis is *right*.

They are still worth running, and worth reporting, for three reasons:

1. Sharing an object does not by itself guarantee that both analyses read the
   *same field* of it. ``run_tea`` could price ``co2_supply_per_kg`` while
   ``run_lca`` characterizes ``co2_fixed_per_kg`` — both are on the inventory,
   both are plausible, and the two differ by the carbon-utilization efficiency.
   The recovery below would catch that; passing the same object would not.
2. The recovery is made from the **published results**, not from the inventory,
   so it also verifies that nothing between the inventory and the reported
   number (overheads, allocation, the functional unit) silently re-bases one
   analysis and not the other.
3. It converts a design claim into a number that a reader can check.

How a quantity is recovered
---------------------------
Both analyses are exactly affine in their own coupling coefficient: the cost is
linear in each unit price, the impact is linear in each characterization factor.
The physical quantity is therefore the derivative, and a central difference
recovers it exactly up to floating-point rounding::

    q_TEA(k) = [ d(production cost) / d(unit price of k) ] / (1 + overhead_frac)
    q_LCA(k) =   d(gross GWP)       / d(GWP factor of k)

Both are in *physical units of k per kg of dry biomass* and are read off two
different result objects produced by two different code paths.

One point of precision, so a careful reader is not misled. The two recoveries
each rebuild an inventory from the scenario rather than sharing one object the
way :func:`~algametrix.scenario.run_scenario` does. That is deliberate and is
the stronger test: ``build_inventory`` is a pure function of the scenario, so
the two inventories are identical by construction, and what the comparison then
isolates is whether ``run_tea`` and ``run_lca`` *read the same fields of it* and
report on the same basis. The single-object path itself is exercised by the
structural checks below, which go through ``run_scenario``.

The only non-physical term in the recovery is ``economics.overhead_frac``:
overhead is *defined* in :mod:`algametrix.tea` as a multiple of the priced
flows, so a price rise inflates it too. It is a declared economic input, and
dividing it out is what leaves a physical quantity behind. Nothing else about
the economics enters.

Flows with no characterization factor
-------------------------------------
Water and land occupation are carried into the impact result directly rather
than through a factor. They are recovered instead by zeroing the one factor that
also contributes (``elec_water``) for water, and from the capital base for land,
and are marked ``direct`` in the report.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

from .lca import run_lca
from .inventory import build_inventory
from .models import Scenario
from .scenario import run_scenario
from .tea import run_tea

#: Relative agreement below which two recovered quantities are called identical.
#: Set at 1e-9, i.e. seven orders of magnitude looser than the ~1e-15 the central
#: difference actually achieves, so the criterion is a genuine bound and not a
#: restatement of the observed value.
CONSISTENCY_TOL = 1e-9


# =====================================================================
# Probes: how to perturb one flow's price and its characterization factor
# =====================================================================

@dataclass
class FlowProbe:
    """One physical flow, with the price and the factor that meter it."""

    name: str
    unit: str                                   # physical unit of the flow, per kg biomass
    set_price: Callable[[Scenario, float], None]
    get_price: Callable[[Scenario], float]
    set_factor: Callable[[Scenario, float], None] | None
    get_factor: Callable[[Scenario], float] | None
    #: Set for flows the LCA carries without a characterization factor.
    lca_direct: Callable[[Scenario], float] | None = None
    kind: str = "characterized"                 # "characterized" | "direct"


def _eco(attr: str):
    return (lambda s, v: setattr(s.economics, attr, v),
            lambda s: float(getattr(s.economics, attr)))


def _lcia(attr: str):
    return (lambda s, v: setattr(s.lcia, attr, v),
            lambda s: float(getattr(s.lcia, attr)))


def _ext(attr: str):
    return (lambda s, v: setattr(s.extraction, attr, v),
            lambda s: float(getattr(s.extraction, attr)))


def _water_direct(scn: Scenario) -> float:
    """Water in the impact result once the electricity contribution is removed.

    ``lca.run_lca`` reports ``water = inv.water_m3_per_kg + elec * f.elec_water``.
    Zeroing ``elec_water`` leaves the process water flow alone.
    """
    s = copy.deepcopy(scn)
    s.lcia.elec_water = 0.0
    return run_lca(s, build_inventory(s)).water_m3_per_kg


def _list_probes(scn: Scenario) -> list[FlowProbe]:
    """The probes that are meaningful for this scenario."""
    sp, gp = _eco("electricity_price")
    probes: list[FlowProbe] = [
        FlowProbe("Electricity", "kWh", sp, gp, *_lcia("elec_gwp")),
        FlowProbe("Heat", "MJ", *_eco("heat_price"), *_lcia("heat_gwp")),
        # The purchased quantity, which is what both sides multiply. With no
        # waste feed it is the whole demand and the probe is unchanged.
        FlowProbe("Nitrogen", "kg N", *_eco("nitrogen_price"), *_lcia("nitrogen_gwp")),
        FlowProbe("Phosphorus", "kg P", *_eco("phosphorus_price"), *_lcia("phosphorus_gwp")),
        FlowProbe("CO2 supply", "kg CO2", *_eco("co2_price"), *_lcia("co2_supply_gwp")),
        FlowProbe("Bicarbonate", "kg NaHCO3",
                  *_eco("bicarbonate_price"), *_lcia("bicarbonate_gwp")),
        FlowProbe("Substrate", "kg", *_eco("substrate_price"), *_lcia("substrate_gwp")),
        FlowProbe("Water", "m3", *_eco("water_price"), None, None,
                  lca_direct=_water_direct, kind="direct"),
    ]
    if scn.extraction.enabled:
        probes.append(FlowProbe("Extraction solvent", "kg",
                                *_ext("solvent_price"), *_ext("solvent_gwp")))
    if scn.waste_feed.enabled:
        # The received stream is a shared flow like any other: the cost side
        # multiplies it by a price that may be a gate fee, the impact side by a
        # handling burden. Both must recover the same quantity.
        probes.append(FlowProbe(
            "Waste feed", scn.waste_feed.unit,
            lambda s, v: setattr(s.waste_feed, "price_per_unit", v),
            lambda s: float(s.waste_feed.price_per_unit),
            lambda s, v: setattr(s.waste_feed, "gwp_per_unit", v),
            lambda s: float(s.waste_feed.gwp_per_unit)))
    # Explicit recipe line items: media, chemicals, extra utilities.
    for i, m in enumerate(scn.materials):
        probes.append(FlowProbe(
            f"Material: {m.name}", "kg",
            (lambda idx: lambda s, v: setattr(s.materials[idx], "price", v))(i),
            (lambda idx: lambda s: float(s.materials[idx].price))(i),
            (lambda idx: lambda s, v: setattr(s.materials[idx], "gwp", v))(i),
            (lambda idx: lambda s: float(s.materials[idx].gwp))(i),
        ))
    for i, u in enumerate(scn.utilities):
        probes.append(FlowProbe(
            f"Utility: {u.name}", u.unit,
            (lambda idx: lambda s, v: setattr(s.utilities[idx], "price", v))(i),
            (lambda idx: lambda s: float(s.utilities[idx].price))(i),
            (lambda idx: lambda s, v: setattr(s.utilities[idx], "gwp", v))(i),
            (lambda idx: lambda s: float(s.utilities[idx].gwp))(i),
        ))
    return probes


# =====================================================================
# Recovery
# =====================================================================

def _step(x: float) -> float:
    """Central-difference step.

    The response is exactly affine, so a *large* step is the accurate one: it
    keeps the difference well above the rounding noise of the two evaluations.
    """
    return max(abs(x), 1.0)


def _derivative(scn: Scenario, setter, getter, readout: Callable[[Scenario], float]) -> float:
    x = getter(scn)
    h = _step(x)
    up, dn = copy.deepcopy(scn), copy.deepcopy(scn)
    setter(up, x + h)
    setter(dn, x - h)
    return (readout(up) - readout(dn)) / (2.0 * h)


def _tea_cost_per_kg(scn: Scenario) -> float:
    inv = build_inventory(scn)
    return run_tea(scn, inv).production_cost_eur_per_kg


def _lca_gwp_gross_per_kg(scn: Scenario) -> float:
    inv = build_inventory(scn)
    return run_lca(scn, inv).gwp_gross_kg_co2eq_per_kg


@dataclass
class FlowConsistency:
    """One flow, as the TEA saw it and as the LCA saw it."""

    flow: str
    unit: str
    kind: str
    tea_quantity: float
    lca_quantity: float
    inventory_quantity: float | None = None   # reference value read off the Inventory
    active: bool = True                        # False when the flow is absent (both zero)

    @property
    def discrepancy(self) -> float:
        """Relative |TEA - LCA| on the recovered quantity."""
        denom = max(abs(self.tea_quantity), abs(self.lca_quantity), 1e-30)
        return abs(self.tea_quantity - self.lca_quantity) / denom

    @property
    def inventory_discrepancy(self) -> float | None:
        """Relative gap between the recovered quantity and the inventory field."""
        if self.inventory_quantity is None:
            return None
        denom = max(abs(self.inventory_quantity), abs(self.tea_quantity), 1e-30)
        return abs(self.tea_quantity - self.inventory_quantity) / denom

    @property
    def consistent(self) -> bool:
        return self.discrepancy <= CONSISTENCY_TOL


@dataclass
class ConsistencyReport:
    """Every flow of one scenario, plus the structural cross-checks."""

    scenario_name: str
    flows: list[FlowConsistency] = field(default_factory=list)
    #: (name, passed, detail) for checks that are not per-flow quantities.
    structural: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def active_flows(self) -> list[FlowConsistency]:
        return [f for f in self.flows if f.active]

    @property
    def max_discrepancy(self) -> float:
        return max((f.discrepancy for f in self.active_flows), default=0.0)

    @property
    def max_inventory_discrepancy(self) -> float:
        """Worst gap between a recovered quantity and the inventory field itself."""
        return max((f.inventory_discrepancy for f in self.active_flows
                    if f.inventory_discrepancy is not None), default=0.0)

    @property
    def all_pass(self) -> bool:
        return (all(f.consistent for f in self.active_flows)
                and all(ok for _, ok, _ in self.structural))


def check_scenario(scenario: Scenario, name: str = "scenario") -> ConsistencyReport:
    """Recover every shared flow from the TEA and from the LCA, and compare."""
    inv = build_inventory(scenario)
    overhead = 1.0 + float(scenario.economics.overhead_frac)

    #: Inventory field holding each flow, for the third (reference) reading.
    # Nitrogen, phosphorus and substrate reference the *purchased* quantity: it
    # is what the price and the fertiliser-production factor both multiply, and
    # it equals the demand whenever no waste feed is enabled.
    inv_field = {
        "Electricity": "elec_kwh_per_kg",
        "Heat": "heat_mj_per_kg",
        "Nitrogen": "nitrogen_purchased_per_kg",
        "Phosphorus": "phosphorus_purchased_per_kg",
        "CO2 supply": "co2_supply_per_kg",
        "Bicarbonate": "bicarbonate_supply_per_kg",
        "Substrate": "substrate_purchased_per_kg",
        "Water": "water_m3_per_kg",
        "Extraction solvent": "solvent_net_per_kg",
        "Waste feed": "waste_feed_per_kg",
    }

    rows: list[FlowConsistency] = []
    for probe in _list_probes(scenario):
        q_tea = _derivative(scenario, probe.set_price, probe.get_price,
                            _tea_cost_per_kg) / overhead
        if probe.kind == "direct":
            q_lca = probe.lca_direct(scenario)
        else:
            q_lca = _derivative(scenario, probe.set_factor, probe.get_factor,
                                _lca_gwp_gross_per_kg)
        ref = None
        if probe.name in inv_field:
            ref = float(getattr(inv, inv_field[probe.name]))
        elif probe.name.startswith("Material: "):
            ref = next((m.amount_per_kg for m in scenario.materials
                        if f"Material: {m.name}" == probe.name), None)
        elif probe.name.startswith("Utility: "):
            ref = next((u.amount_per_kg for u in scenario.utilities
                        if f"Utility: {u.name}" == probe.name), None)
        rows.append(FlowConsistency(
            flow=probe.name, unit=probe.unit, kind=probe.kind,
            tea_quantity=q_tea, lca_quantity=q_lca, inventory_quantity=ref,
            active=(abs(q_tea) > 1e-30 or abs(q_lca) > 1e-30),
        ))

    return ConsistencyReport(
        scenario_name=name, flows=rows,
        structural=_structural_checks(scenario, inv),
    )


# =====================================================================
# Structural cross-checks: basis, land, allocation, propagation
# =====================================================================

def _structural_checks(scenario: Scenario, inv) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    res = run_scenario(scenario)

    # --- the two analyses are referred to the same annual production ----------
    # TEA: production cost x annual production == annual operating cost.
    # LCA: results are per kg of that same annual production.
    implied = (res.tea.annual_opex / res.tea.production_cost_eur_per_kg
               if res.tea.production_cost_eur_per_kg else 0.0)
    rel = abs(implied - inv.annual_biomass_kg) / max(inv.annual_biomass_kg, 1e-30)
    out.append((
        "Functional unit: TEA cost denominator == LCA reference flow",
        rel <= CONSISTENCY_TOL,
        f"{implied:,.6g} vs {inv.annual_biomass_kg:,.6g} kg/yr (rel {rel:.1e})",
    ))

    # --- land occupation: the capital base and the impact see one area --------
    # d(DFC)/d(land price) is the area the TEA bought; the LCA occupies
    # land_m2a_per_kg x annual production over one year.
    area_tea = _derivative(
        scenario, *_eco("land_price"),
        lambda s: run_tea(s, build_inventory(s)).dfc,
    )
    area_lca = inv.land_m2a_per_kg * inv.annual_biomass_kg
    denom = max(abs(area_tea), abs(area_lca), 1e-30)
    vacuous = area_tea == 0.0 and area_lca == 0.0
    out.append((
        "Land: area capitalised by TEA == area occupied in LCA",
        abs(area_tea - area_lca) / denom <= CONSISTENCY_TOL,
        "no land declared for this system - check is vacuous" if vacuous else
        f"{area_tea:,.6g} vs {area_lca:,.6g} m2 "
        f"(rel {abs(area_tea - area_lca) / denom:.1e})",
    ))

    # --- multi-product allocation: cost and impact split by the same key ------
    if res.products:
        worst, detail = 0.0, []
        total_gwp = res.lca.gwp_kg_co2eq_per_kg * inv.annual_biomass_kg
        for p in res.products:
            if p.annual_kg <= 0:
                continue
            share_cost = p.production_cost_eur_per_kg * p.annual_kg / res.tea.annual_opex
            share_gwp = (p.gwp_kg_co2eq_per_kg * p.annual_kg / total_gwp
                         if total_gwp else share_cost)
            gap = abs(share_cost - share_gwp) / max(abs(share_cost), 1e-30)
            worst = max(worst, gap)
            detail.append(f"{p.name}: {share_cost:.6f}/{share_gwp:.6f}")
        out.append((
            "Allocation: cost share == impact share, per product",
            worst <= CONSISTENCY_TOL,
            "; ".join(detail) + f" (max rel {worst:.1e})",
        ))
    return out


def check_propagation(
    scenario: Scenario, name: str = "scenario", recovery_delta: float = -0.10
) -> tuple[ConsistencyReport, dict[str, tuple[float, float]]]:
    """Change ONE physical assumption once, and confirm both analyses move together.

    Harvesting recovery is the assumption used because it is upstream of
    everything: every cultivation flow is scaled by ``1 / recovery``. The
    scenario is re-run with the recovery moved by ``recovery_delta`` (relative)
    and the full flow recovery is repeated on the perturbed system.

    Returns the report for the perturbed scenario and, per flow, the
    ``(before, after)`` TEA-recovered quantities, so a caller can show that the
    flows genuinely moved rather than that the test was vacuous.
    """
    before = check_scenario(scenario, name)
    moved = copy.deepcopy(scenario)
    moved.harvesting.recovery = min(
        max(scenario.harvesting.recovery * (1.0 + recovery_delta), 1e-6), 1.0)
    after = check_scenario(moved, f"{name} [recovery {recovery_delta:+.0%}]")
    by_name = {f.flow: f.tea_quantity for f in before.flows}
    deltas = {f.flow: (by_name.get(f.flow, 0.0), f.tea_quantity)
              for f in after.flows if f.active}
    return after, deltas


def format_report(report: ConsistencyReport) -> str:
    """Human-readable block for the reproduce script and the paper appendix."""
    head = (f"Shared-inventory consistency - {report.scenario_name}: "
            f"{'PASS' if report.all_pass else 'FAIL'} "
            f"(max relative discrepancy {report.max_discrepancy:.1e})")
    lines = [head,
             f"    {'flow':22s} {'unit':10s} {'TEA-implied':>14s} {'LCA-implied':>14s} "
             f"{'inventory':>14s} {'rel. diff':>10s}"]
    for f in report.flows:
        if not f.active:
            continue
        mark = "ok" if f.consistent else "XX"
        ref = ("%14.8g" % f.inventory_quantity) if f.inventory_quantity is not None else " " * 14
        lines.append(
            f"    [{mark}] {f.flow:17s} {f.unit:10s} {f.tea_quantity:14.8g} "
            f"{f.lca_quantity:14.8g} {ref} {f.discrepancy:10.1e}"
            + ("  (direct)" if f.kind == "direct" else "")
        )
    inactive = [f.flow for f in report.flows if not f.active]
    if inactive:
        lines.append(f"    not present in this scenario: {', '.join(inactive)}")
    for nm, ok, detail in report.structural:
        lines.append(f"    [{'ok' if ok else 'XX'}] {nm}")
        lines.append(f"         {detail}")
    return "\n".join(lines)


# =====================================================================
# Controlled counter-example: what a duplicated inventory would do
# =====================================================================

@dataclass
class DriftResult:
    """One flow under a duplicated-inventory implementation after a single edit."""

    flow: str
    unit: str
    tea_quantity: float
    lca_quantity: float

    @property
    def discrepancy(self) -> float:
        denom = max(abs(self.tea_quantity), abs(self.lca_quantity), 1e-30)
        return abs(self.tea_quantity - self.lca_quantity) / denom


@dataclass
class DriftDemonstration:
    scenario_name: str
    assumption: str
    old_value: float
    new_value: float
    shared: list[FlowConsistency]
    duplicated: list[DriftResult]
    cost_shared: float
    cost_duplicated: float
    gwp_shared: float
    gwp_duplicated: float

    @property
    def max_shared_discrepancy(self) -> float:
        return max((f.discrepancy for f in self.shared if f.active), default=0.0)

    @property
    def max_duplicated_discrepancy(self) -> float:
        return max((d.discrepancy for d in self.duplicated), default=0.0)


def duplicated_inventory_drift(
    scenario: Scenario, name: str = "scenario", new_recovery: float | None = None
) -> DriftDemonstration:
    """Show what a *single* un-mirrored edit costs when the inventories are duplicated.

    This is a controlled demonstration of a failure mode, run on this engine
    against itself. It is **not** a claim about any other software: no existing
    tool is inspected or implicated here, and a duplicated inventory is only a
    hazard, not an inevitability.

    The construction is deliberately minimal. A duplicated-inventory
    implementation is emulated by giving the TEA and the LCA their own copies of
    the scenario. One physical assumption — the harvesting recovery — is then
    updated in the TEA copy only, exactly as a maintainer would if the two
    inventories lived in two files and only one was edited. The engine's own
    single-inventory path is run on the same edit for contrast.

    The point is the *magnitude*: the reported cost and GWP still look like a
    matched pair, and nothing in either number reveals that they now describe
    two different plants.
    """
    old = scenario.harvesting.recovery
    new = new_recovery if new_recovery is not None else max(old * 0.85, 1e-6)

    # --- the architecture as built: one inventory, one edit, both analyses move
    shared_scn = copy.deepcopy(scenario)
    shared_scn.harvesting.recovery = new
    shared_report = check_scenario(shared_scn, name)
    shared_res = run_scenario(shared_scn)

    # --- the emulated duplicate: the LCA copy never received the edit ---------
    tea_scn = copy.deepcopy(scenario)
    tea_scn.harvesting.recovery = new
    lca_scn = copy.deepcopy(scenario)          # stale: still at the old recovery

    tea_inv = build_inventory(tea_scn)
    lca_inv = build_inventory(lca_scn)
    tea_res = run_tea(tea_scn, tea_inv)
    lca_res = run_lca(lca_scn, lca_inv)

    overhead = 1.0 + float(tea_scn.economics.overhead_frac)
    drift: list[DriftResult] = []
    for probe in _list_probes(scenario):
        q_tea = _derivative(tea_scn, probe.set_price, probe.get_price,
                            _tea_cost_per_kg) / overhead
        if probe.kind == "direct":
            q_lca = probe.lca_direct(lca_scn)
        else:
            q_lca = _derivative(lca_scn, probe.set_factor, probe.get_factor,
                                _lca_gwp_gross_per_kg)
        if abs(q_tea) > 1e-30 or abs(q_lca) > 1e-30:
            drift.append(DriftResult(probe.name, probe.unit, q_tea, q_lca))

    return DriftDemonstration(
        scenario_name=name,
        assumption="harvesting recovery",
        old_value=old, new_value=new,
        shared=shared_report.flows,
        duplicated=drift,
        cost_shared=shared_res.tea.production_cost_eur_per_kg,
        cost_duplicated=tea_res.production_cost_eur_per_kg,
        gwp_shared=shared_res.lca.gwp_gross_kg_co2eq_per_kg,
        gwp_duplicated=lca_res.gwp_gross_kg_co2eq_per_kg,
    )
