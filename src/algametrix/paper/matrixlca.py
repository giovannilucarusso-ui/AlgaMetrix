"""An independent LCA implementation, written from the matrix formalism.

Why this exists
---------------
:mod:`algametrix.lca` computes impacts by accumulating scalar products over the
flows of a pre-computed :class:`~algametrix.inventory.Inventory`. That is a
perfectly ordinary way to write a cradle-to-gate LCA, and it is also the only
implementation in the repository — so a systematic error in it would be
invisible.

This module recomputes the same result the other way round, from the textbook
formulation used by matrix-based LCA software (Heijungs & Suh 2002)::

    A s = f          scaling vector of the technosphere
    g   = B s        elementary-flow inventory
    h   = C g        characterized impacts

It shares **no code** with :mod:`algametrix.lca` and it never reads an
:class:`Inventory`. Both matrices are assembled from the primitive scenario
parameters — productivity, harvesting recovery, solids fractions, per-stage
energy, elemental composition — so agreement between the two implementations
tests :mod:`algametrix.inventory` as well as :mod:`algametrix.lca`.

What it is, and what it is not
------------------------------
This is **implementation verification**: two independent codings of the same
model specification, on identical foreground data, an identical functional unit,
identical system boundaries and identical characterization factors. Agreement
means the arithmetic is right. It does **not** mean the model is right, and it is
not an empirical validation of any kind.

Two honest caveats about the matrices themselves:

* **C is close to the identity.** AlgaMetrix ships *already characterized*
  cradle-to-gate factors (kg CO2-eq per kWh, not kg CH4 per kWh), so there is
  little characterization left for C to do. It is assembled and applied as a
  real matrix anyway, because that is the code path a user gets if they replace
  the background with uncharacterized elementary flows, and because freshwater
  eutrophication genuinely draws on three separate exchanges.
* **A is block-triangular.** The background is a cut-off unit-process system:
  each background activity carries its cradle-to-gate burden as a direct
  exchange and consumes nothing. The *foreground* chain, however, is a genuine
  multi-stage system — cultivation, harvesting, drying, extraction — solved with
  a general LU factorisation, and the harvesting recovery enters as an
  off-diagonal transfer coefficient rather than as a pre-multiplied ratio.

Relationship to Brightway
-------------------------
``A s = f`` solved by LU factorisation is what ``bw2calc`` does. Brightway was
not adopted as the benchmark engine because its value lies in coupling a model
to a licensed background database (ecoinvent), which this repository does not
ship and cannot redistribute; running Brightway over a hand-built foreground
with the same seven aggregated factors would exercise the same linear algebra
behind a much larger dependency surface. :func:`brightway_available` and
:func:`compare_with_brightway` are provided so that a user who does have
Brightway installed can run the cross-check, and the result is reported when
they do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..models import (
    Basis,
    CarbonAccounting,
    CarbonSource,
    Scenario,
    TrophicMode,
    WasteBurdenConvention,
)

# Molar-mass ratios. Restated here rather than imported, so that a change in
# algametrix.inventory does not silently propagate into its own benchmark.
_CO2_PER_C = 44.01 / 12.011
_NAHCO3_PER_C = 84.007 / 12.011
_MIN_CARBON_UTILIZATION = 0.05

#: Elementary-flow rows of B, in a fixed order.
ELEMENTARY_FLOWS = (
    "GHG to air (kg CO2-eq)",
    "Biogenic CO2 uptake (kg CO2)",
    "Primary energy (MJ)",
    "Water consumed (m3)",
    "Land occupied (m2*a)",
    "N to water (kg N)",
    "P to water (kg P)",
    "Upstream N-eq (kg N-eq)",
    "Upstream P-eq (kg P-eq)",
    "Acidifying emissions (kg SO2-eq)",
    # Kept apart from "GHG to air" for the same reason biogenic uptake is: it is
    # a burden another system no longer carries, not one this one causes, so it
    # must be outside the gross and visible on its own.
    "Avoided treatment (kg CO2-eq)",
)

#: Impact categories, named exactly as :mod:`algametrix.lca` names them.
IMPACT_CATEGORIES = (
    "GWP (kg CO₂-eq)",
    "Energy demand (MJ)",
    "Water (m³)",
    "Land (m²·a)",
    "Marine eutrophication (kg N-eq)",
    "Freshwater eutrophication (kg P-eq)",
    "Acidification (kg SO₂-eq)",
)


@dataclass
class MatrixSystem:
    """The assembled linear system, kept so a reader can inspect it."""

    processes: list[str]
    A: np.ndarray                    # technosphere, (n_proc, n_proc)
    B: np.ndarray                    # elementary flows, (n_flow, n_proc)
    C: np.ndarray                    # characterization, (n_cat, n_flow)
    f: np.ndarray                    # final demand, (n_proc,)
    scaling: np.ndarray = field(default_factory=lambda: np.empty(0))
    inventory: np.ndarray = field(default_factory=lambda: np.empty(0))

    @property
    def condition_number(self) -> float:
        return float(np.linalg.cond(self.A))


@dataclass
class MatrixLCAResult:
    """Impacts from the matrix implementation, per kg of dry biomass at the gate."""

    impacts: dict[str, float]
    gwp_gross: float
    gwp_net: float
    biogenic_adjustment: float
    system: MatrixSystem

    @property
    def elementary(self) -> dict[str, float]:
        return dict(zip(ELEMENTARY_FLOWS, self.system.inventory))


# =====================================================================
# Annual production — recomputed independently of inventory.build_inventory
# =====================================================================

def annual_production_kg(scenario: Scenario) -> float:
    """Dry biomass leaving the gate, kg/yr."""
    sys_ = scenario.system
    recovery = min(max(scenario.harvesting.recovery, 1e-6), 1.0)
    if scenario.batch_mode and scenario.batch_cycle_time_h > 0:
        batches = sys_.operating_days * 24.0 / scenario.batch_cycle_time_h
        gross = scenario.batch_size_kg * batches
    elif sys_.basis == Basis.AREA:
        gross = sys_.productivity * scenario.scale * sys_.operating_days / 1000.0
    else:
        gross = sys_.productivity * scenario.scale * 1000.0 * sys_.operating_days / 1000.0
    return gross * recovery


def _water_to_evaporate(solids_in: float, solids_out: float) -> float:
    a = min(max(solids_in, 1e-6), 1.0)
    b = min(max(solids_out, 1e-6), 1.0)
    return max((1.0 - a) / a - (1.0 - b) / b, 0.0)


# =====================================================================
# Assembly
# =====================================================================

def build_system(scenario: Scenario) -> MatrixSystem:
    """Assemble ``A``, ``B``, ``C`` and ``f`` from the scenario parameters alone."""
    org, sys_ = scenario.organism, scenario.system
    harv, dry, ext, f_ = scenario.harvesting, scenario.drying, scenario.extraction, scenario.lcia

    recovery = min(max(harv.recovery, 1e-6), 1.0)
    uptake = min(max(sys_.nutrient_uptake, 1e-6), 1.0)
    photo = sys_.mode == TrophicMode.PHOTOTROPHIC

    # ---- process index ---------------------------------------------------
    names = ["cultivation (1 kg gross dry biomass)",
             "harvesting (1 kg gross biomass processed)"]
    i_cult, i_harv, i_gate = 0, 1, 2
    i_ext = None
    names.append("drying (1 kg dry biomass at the gate)" if dry.enabled
                 else "dewatered product (1 kg dry biomass at the gate)")
    if ext.enabled:
        names.append("extraction (1 kg dry biomass, post-extraction)")
        i_ext = 3

    background = ["electricity (kWh)", "heat (MJ)", "CO2 supply (kg)",
                  "sodium bicarbonate (kg)", "nitrogen (kg N)", "phosphorus (kg P)",
                  "organic substrate (kg)", "process water (m3)"]
    if ext.enabled:
        background.append(f"{ext.solvent_name} (kg)")
    wf = scenario.waste_feed
    waste_name = f"waste feed: {wf.name or 'stream'} ({wf.unit})" if wf.enabled else None
    if waste_name:
        background.append(waste_name)
    mat_names = [f"material: {m.name} (kg)" for m in scenario.materials]
    util_names = [f"utility: {u.name} ({u.unit})" for u in scenario.utilities]
    background += mat_names + util_names

    b0 = len(names)
    names += background
    idx = {n: b0 + k for k, n in enumerate(background)}
    n = len(names)

    # ---- technosphere ----------------------------------------------------
    A = np.eye(n)
    last_stage = i_ext if ext.enabled else i_gate

    # harvesting draws 1 kg of gross biomass from cultivation
    A[i_cult, i_harv] = -1.0
    # the gate draws 1/recovery kg of processed gross biomass: the harvesting
    # loss is an off-diagonal transfer coefficient, nothing else
    A[i_harv, i_gate] = -1.0 / recovery
    if ext.enabled:
        A[i_gate, i_ext] = -1.0

    def use(flow: str, process: int, amount: float) -> None:
        if amount:
            A[idx[flow], process] -= amount

    # cultivation, per kg of GROSS dry biomass
    use("electricity (kWh)", i_cult, sys_.elec_kwh_per_kg)
    cult_heat = sys_.cultivation_heat_mj_per_kg
    if sys_.cultivation_heat_fuel == "electricity":
        use("electricity (kWh)", i_cult, cult_heat / 3.6)
    else:
        use("heat (MJ)", i_cult, cult_heat)
    # Demands per kg of GROSS biomass. A waste-derived feed displaces part of
    # each purchase; the matrix scales all of it to the product through the
    # harvesting transfer coefficient, exactly as it does for every other flow.
    n_demand = org.nitrogen / uptake
    p_demand = org.phosphorus / uptake
    s_demand = 0.0 if photo else 1.0 / max(sys_.substrate_yield, 1e-6)
    waste_qty = 0.0
    if wf.enabled:
        dosed = {"nitrogen": (n_demand, wf.nitrogen_per_unit),
                 "phosphorus": (p_demand, wf.phosphorus_per_unit),
                 "substrate": (s_demand, wf.substrate_per_unit)}.get(wf.dosed_on, (0.0, 0.0))
        demand_d, conc_d = dosed
        if conc_d > 0 and demand_d > 0:
            waste_qty = min(max(wf.coverage, 0.0), 1.0) * demand_d / conc_d
    n_buy = n_demand - min(waste_qty * max(wf.nitrogen_per_unit, 0.0), n_demand)
    p_buy = p_demand - min(waste_qty * max(wf.phosphorus_per_unit, 0.0), p_demand)
    s_buy = s_demand - min(waste_qty * max(wf.substrate_per_unit, 0.0), s_demand)

    use("nitrogen (kg N)", i_cult, n_buy)
    use("phosphorus (kg P)", i_cult, p_buy)
    use("process water (m3)", i_cult, sys_.water_m3_per_kg)
    if waste_name and waste_qty:
        use(waste_name, i_cult, waste_qty)
        use("electricity (kWh)", i_cult, waste_qty * wf.elec_kwh_per_unit)
    if photo:
        util = min(max(sys_.co2_utilization, _MIN_CARBON_UTILIZATION), 1.0)
        if sys_.carbon_source == CarbonSource.BICARBONATE:
            use("sodium bicarbonate (kg)", i_cult, org.carbon * _NAHCO3_PER_C / util)
        else:
            use("CO2 supply (kg)", i_cult, org.carbon * _CO2_PER_C / util)
    else:
        use("organic substrate (kg)", i_cult, s_buy)

    # harvesting, per kg of gross biomass processed
    use("electricity (kWh)", i_harv, harv.elec_kwh_per_kg)

    # drying / gate, per kg of dry biomass at the gate
    if dry.enabled:
        evap = _water_to_evaporate(harv.final_solids, dry.final_solids)
        drying_heat = evap * dry.thermal_mj_per_kg_water
        use("electricity (kWh)", i_gate, dry.elec_kwh_per_kg)
        if dry.fuel == "electricity":
            use("electricity (kWh)", i_gate, drying_heat / 3.6)
        else:
            use("heat (MJ)", i_gate, drying_heat)

    # extraction, per kg of dry biomass entering the step
    if ext.enabled:
        use("electricity (kWh)", i_ext,
            ext.disruption_elec_kwh_per_kg + ext.elec_kwh_per_kg)
        use("heat (MJ)", i_ext, ext.heat_mj_per_kg)
        use(f"{ext.solvent_name} (kg)", i_ext,
            ext.solvent_kg_per_kg * (1.0 - min(max(ext.solvent_recovery, 0.0), 1.0)))

    # explicit recipe items are declared per kg of dry product: they attach to
    # whichever process delivers the final demand
    for m, nm in zip(scenario.materials, mat_names):
        use(nm, last_stage, m.amount_per_kg)
    for u, nm in zip(scenario.utilities, util_names):
        use(nm, last_stage, u.amount_per_kg)

    # ---- elementary flows -------------------------------------------------
    B = np.zeros((len(ELEMENTARY_FLOWS), n))
    e = {name: k for k, name in enumerate(ELEMENTARY_FLOWS)}

    def emit(flow: str, process: int, amount: float) -> None:
        if amount:
            B[e[flow], process] += amount

    ghg, energy, water, land = (ELEMENTARY_FLOWS[0], ELEMENTARY_FLOWS[2],
                                ELEMENTARY_FLOWS[3], ELEMENTARY_FLOWS[4])
    acid, up_n, up_p = ELEMENTARY_FLOWS[9], ELEMENTARY_FLOWS[7], ELEMENTARY_FLOWS[8]

    bg_factors = {
        "electricity (kWh)": (f_.elec_gwp, f_.elec_ced, f_.elec_water, f_.elec_acid),
        "heat (MJ)": (f_.heat_gwp, f_.heat_ced, 0.0, f_.heat_acid),
        "CO2 supply (kg)": (f_.co2_supply_gwp, 0.0, 0.0, 0.0),
        "sodium bicarbonate (kg)": (f_.bicarbonate_gwp, f_.bicarbonate_ced, 0.0, 0.0),
        "nitrogen (kg N)": (f_.nitrogen_gwp, f_.nitrogen_ced, 0.0, f_.nitrogen_acid),
        "phosphorus (kg P)": (f_.phosphorus_gwp, f_.phosphorus_ced, 0.0, f_.phosphorus_acid),
        "organic substrate (kg)": (f_.substrate_gwp, f_.substrate_ced, 0.0, f_.substrate_acid),
        "process water (m3)": (0.0, 0.0, 1.0, 0.0),
    }
    if ext.enabled:
        bg_factors[f"{ext.solvent_name} (kg)"] = (
            ext.solvent_gwp, ext.solvent_ced, 0.0, f_.solvent_acid)
    if waste_name:
        # Only the handling burden characterises as a GHG emission. The credit
        # is a separate elementary flow below, so that the matrix's gross means
        # the same thing the engine's does.
        bg_factors[waste_name] = (wf.gwp_per_unit, wf.ced_per_unit, 0.0, 0.0)
    for m, nm in zip(scenario.materials, mat_names):
        bg_factors[nm] = (m.gwp, m.ced, 0.0, 0.0)
    for u, nm in zip(scenario.utilities, util_names):
        bg_factors[nm] = (u.gwp, u.ced, 0.0, 0.0)

    for nm, (g, c, w, a) in bg_factors.items():
        p = idx[nm]
        emit(ghg, p, g)
        emit(energy, p, c)
        emit(water, p, w)
        emit(acid, p, a)
    emit(up_n, idx["nitrogen (kg N)"], f_.nitrogen_eutroph_n)
    emit(up_p, idx["phosphorus (kg P)"], f_.phosphorus_eutroph_p)
    emit(up_p, idx["electricity (kWh)"], f_.elec_eutroph_p)

    # un-assimilated nutrients leave the cultivation stage, and so does whatever
    # the waste stream over-delivered: the culture cannot take it up, so it is
    # discharged whichever bucket it arrived in
    n_surplus = max(waste_qty * max(wf.nitrogen_per_unit, 0.0) - n_demand, 0.0)
    p_surplus = max(waste_qty * max(wf.phosphorus_per_unit, 0.0) - p_demand, 0.0)
    emit(ELEMENTARY_FLOWS[5], i_cult,
         (n_demand * (1.0 - uptake) + n_surplus) * f_.n_to_water_frac)
    emit(ELEMENTARY_FLOWS[6], i_cult,
         (p_demand * (1.0 - uptake) + p_surplus) * f_.p_to_water_frac)

    # the treatment this process displaces, where the scenario declares system
    # expansion: entered positive on its own flow and characterised negatively,
    # so it leaves the gross alone and can be taken back off
    if waste_name and wf.convention == WasteBurdenConvention.AVOIDED_TREATMENT:
        emit(ELEMENTARY_FLOWS[10], idx[waste_name], wf.avoided_treatment_gwp_per_unit)
        emit(energy, idx[waste_name], -wf.avoided_treatment_ced_per_unit)

    # land occupation is a plant-level quantity referred to the annual output
    annual = annual_production_kg(scenario)
    if annual > 0:
        emit(land, last_stage, scenario.scale * sys_.land_m2_per_unit / annual)

    # biogenic CO2 uptake: which process carries it *is* the accounting
    # convention. Fixed by the gross biomass grown (cultivation) under a
    # source-specific credit; carried out of the gate inside the product under
    # an at-gate storage credit.
    mode = _effective_mode(f_)
    if mode is CarbonAccounting.SOURCE_SPECIFIC_CREDIT:
        if photo and sys_.carbon_source == CarbonSource.CO2:
            emit(ELEMENTARY_FLOWS[1], i_cult, org.carbon * _CO2_PER_C)
    elif mode is CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE:
        emit(ELEMENTARY_FLOWS[1], i_gate, org.carbon * _CO2_PER_C)
    elif mode is CarbonAccounting.CUSTOM:
        frac = max(0.0, min(float(f_.custom_biogenic_credit_fraction), 1.0))
        emit(ELEMENTARY_FLOWS[1], i_gate, org.carbon * _CO2_PER_C * frac)

    # ---- characterization -------------------------------------------------
    C = np.zeros((len(IMPACT_CATEGORIES), len(ELEMENTARY_FLOWS)))
    C[0, e[ghg]] = 1.0
    C[0, e[ELEMENTARY_FLOWS[1]]] = -1.0        # uptake enters the GWP negatively
    C[0, e[ELEMENTARY_FLOWS[10]]] = -1.0       # so does the avoided treatment
    C[1, e[energy]] = 1.0
    C[2, e[water]] = 1.0
    C[3, e[land]] = 1.0
    C[4, e[ELEMENTARY_FLOWS[5]]] = 1.0
    C[4, e[up_n]] = 1.0
    C[5, e[ELEMENTARY_FLOWS[6]]] = 1.0
    C[5, e[up_p]] = 1.0
    C[6, e[acid]] = 1.0

    demand = np.zeros(n)
    demand[last_stage] = 1.0
    return MatrixSystem(processes=names, A=A, B=B, C=C, f=demand)


def _effective_mode(factors) -> CarbonAccounting:
    if not factors.count_biogenic_uptake:
        return CarbonAccounting.NO_BIOGENIC_CREDIT
    mode = factors.carbon_accounting
    return mode if isinstance(mode, CarbonAccounting) else CarbonAccounting(mode)


# =====================================================================
# Solve
# =====================================================================

def run_matrix_lca(scenario: Scenario) -> MatrixLCAResult:
    """Solve ``A s = f`` and characterize, per kg of dry biomass at the gate."""
    sysm = build_system(scenario)
    s = np.linalg.solve(sysm.A, sysm.f)
    g = sysm.B @ s
    h = sysm.C @ g
    sysm.scaling, sysm.inventory = s, g

    impacts = dict(zip(IMPACT_CATEGORIES, h))
    uptake = float(g[1])
    avoided = float(g[10])
    gwp_net = float(impacts[IMPACT_CATEGORIES[0]])
    return MatrixLCAResult(
        impacts=impacts,
        # Both credits come back off to give the gross, which therefore means
        # what it means in algametrix.lca: everything before any credit.
        gwp_gross=gwp_net + uptake + avoided,
        gwp_net=gwp_net,
        biogenic_adjustment=-uptake,
        system=sysm,
    )


# =====================================================================
# Benchmark against the engine
# =====================================================================

@dataclass
class BenchmarkRow:
    label: str
    engine: float
    matrix: float

    @property
    def abs_diff(self) -> float:
        return abs(self.engine - self.matrix)

    @property
    def rel_diff(self) -> float:
        denom = max(abs(self.engine), abs(self.matrix), 1e-30)
        return self.abs_diff / denom


@dataclass
class BenchmarkReport:
    scenario_name: str
    rows: list[BenchmarkRow]
    condition_number: float
    n_processes: int

    @property
    def max_rel_diff(self) -> float:
        return max((r.rel_diff for r in self.rows), default=0.0)

    def passed(self, tol: float) -> bool:
        return self.max_rel_diff <= tol


#: Agreement required between the two implementations. Loose enough to be a
#: real bound on a linear solve, tight enough that any modelling difference
#: would break it.
BENCHMARK_TOL = 1e-9


def benchmark(scenario: Scenario, name: str = "scenario") -> BenchmarkReport:
    """Compare :mod:`algametrix.lca` with the matrix implementation."""
    from ..inventory import build_inventory
    from ..lca import run_lca

    engine = run_lca(scenario, build_inventory(scenario))
    matrix = run_matrix_lca(scenario)

    rows = [BenchmarkRow(cat, float(engine.impacts[cat]), float(matrix.impacts[cat]))
            for cat in IMPACT_CATEGORIES]
    rows.append(BenchmarkRow("GWP gross (kg CO2-eq)",
                             engine.gwp_gross_kg_co2eq_per_kg, matrix.gwp_gross))
    rows.append(BenchmarkRow("Biogenic adjustment (kg CO2-eq)",
                             engine.biogenic_adjustment_kg_co2eq_per_kg,
                             matrix.biogenic_adjustment))
    return BenchmarkReport(name, rows, matrix.system.condition_number,
                           len(matrix.system.processes))


def format_report(report: BenchmarkReport, tol: float = BENCHMARK_TOL) -> str:
    lines = [
        f"Independent matrix LCA - {report.scenario_name}: "
        f"{'PASS' if report.passed(tol) else 'FAIL'} "
        f"(max relative difference {report.max_rel_diff:.1e}; "
        f"{report.n_processes} processes, cond(A) = {report.condition_number:.3g})",
        f"    {'indicator':36s} {'sequential':>16s} {'matrix':>16s} {'rel. diff':>10s}",
    ]
    for r in report.rows:
        mark = "ok" if r.rel_diff <= tol else "XX"
        lines.append(f"    [{mark}] {r.label:31s} {r.engine:16.9g} "
                     f"{r.matrix:16.9g} {r.rel_diff:10.1e}")
    return "\n".join(lines)


# =====================================================================
# Optional third-party cross-check
# =====================================================================

def brightway_available() -> bool:
    """True when ``bw2calc`` can be imported."""
    try:
        import bw2calc  # noqa: F401
    except Exception:
        return False
    return True


def compare_with_brightway(scenario: Scenario) -> dict | None:
    """Solve the same system with ``bw2calc``; ``None`` when it is not installed.

    Brightway is fed the matrices assembled above — the same foreground data,
    functional unit, boundaries and characterization factors — so what is
    compared is the linear solver, not the model.
    """
    if not brightway_available():
        return None
    import bw_processing as bwp
    import bw2calc

    sysm = build_system(scenario)
    n = len(sysm.processes)
    # bw2calc consumes the technosphere with production positive and inputs
    # negative, which is the sign convention A already uses.
    ti = np.array([(i, j) for i in range(n) for j in range(n) if sysm.A[i, j] != 0.0],
                  dtype=[("row", np.int32), ("col", np.int32)])
    td = np.array([sysm.A[i, j] for i, j in zip(ti["row"], ti["col"])], dtype=float)
    n_flow = sysm.B.shape[0]
    bi = np.array([(f, j) for f in range(n_flow) for j in range(n) if sysm.B[f, j] != 0.0],
                  dtype=[("row", np.int32), ("col", np.int32)])
    bd = np.array([sysm.B[f, j] for f, j in zip(bi["row"], bi["col"])], dtype=float)

    dp = bwp.create_datapackage()
    dp.add_persistent_vector(matrix="technosphere_matrix", indices_array=ti,
                             data_array=td, flip_array=np.zeros(len(td), dtype=bool))
    dp.add_persistent_vector(matrix="biosphere_matrix", indices_array=bi, data_array=bd)

    out: dict[str, float] = {}
    demand_idx = int(np.argmax(sysm.f))
    for k, cat in enumerate(IMPACT_CATEGORIES):
        rows = [f for f in range(n_flow) if sysm.C[k, f] != 0.0]
        if not rows:
            out[cat] = 0.0
            continue
        ci = np.array([(f, f) for f in rows],
                      dtype=[("row", np.int32), ("col", np.int32)])
        cd = np.array([sysm.C[k, f] for f in rows], dtype=float)
        cdp = bwp.create_datapackage()
        cdp.add_persistent_vector(matrix="characterization_matrix",
                                  indices_array=ci, data_array=cd)
        lca = bw2calc.LCA({demand_idx: 1.0}, data_objs=[dp, cdp])
        lca.lci()
        lca.lcia()
        out[cat] = float(lca.score)
    return out
