"""The mathematical specification of the model, and a check that it is honest.

Peer review asked for the governing equations, symbols, units and financial
assumptions, on the grounds that reproducibility through source code does not
remove the need to *define* the model being evaluated. That is right, and it
raises a problem of its own: a specification written by hand drifts from the
code it describes, and a specification that has drifted is worse than none,
because a reader who trusts it is misled rather than merely unserved.

So every equation here is declared once, as an :class:`Equation` carrying both
the LaTeX that the Supplementary Information prints **and** a callable that
recomputes the same quantity from the scenario. ``tests/test_specification.py``
runs every callable over the whole scenario suite and compares it against what
the engine actually returns. The two are written from the same intent but not
from the same expression, so a transcription error in the printed equation shows
up as a failing test rather than as a wrong line in a published document.

A note on what that check is and is not, because this repository has been
careless about exactly this distinction before (see
:mod:`algametrix.verification`): comparing a restatement against the engine
verifies **documentation fidelity**, not physics. It answers "does the paper
print the equations the software runs?" and nothing else. It is the right test
for that question and the wrong test for any other.

Units are SI unless stated. The functional unit is one kilogram of dry biomass
leaving the gate; ``gpp`` denotes gross biomass cultivated per kilogram of
product, and every upstream flow is referred to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..inventory import CO2_PER_C, build_inventory
from ..models import Basis, CarbonAccounting, CarbonSource, TrophicMode


@dataclass(frozen=True)
class Symbol:
    """One symbol of the specification, with where its value comes from."""

    latex: str
    description: str
    unit: str
    source: str


@dataclass
class Equation:
    """One governing equation: what is printed, and how it is checked.

    ``stated`` recomputes the left-hand side from the scenario, following the
    printed formula. ``engine`` returns the same quantity as the software
    reports it. They must agree to :data:`REL_TOL` on every scenario in the
    suite; where an equation does not apply (a phototrophic scenario has no
    substrate) ``applies`` returns ``False`` and the pair is skipped.
    """

    key: str
    latex: str
    description: str
    implemented_in: str
    stated: Callable | None = None
    engine: Callable | None = None
    applies: Callable | None = None
    note: str = ""

    def evaluate(self, scenario, inv, tea, lca) -> tuple[float, float] | None:
        if self.stated is None or self.engine is None:
            return None
        if self.applies is not None and not self.applies(scenario, inv):
            return None
        return (float(self.stated(scenario, inv, tea, lca)),
                float(self.engine(scenario, inv, tea, lca)))


#: Relative tolerance for the specification check. Both sides are floating-point
#: evaluations of the same algebra in a different order, so the difference is
#: round-off; the tolerance is not slack for a disagreement in substance.
REL_TOL = 1e-9


def _gpp(scenario) -> float:
    return 1.0 / min(max(scenario.harvesting.recovery, 1e-6), 1.0)


def _uptake(scenario) -> float:
    return min(max(scenario.system.nutrient_uptake, 1e-6), 1.0)


def _is_photo(scenario, inv=None) -> bool:
    return scenario.system.mode == TrophicMode.PHOTOTROPHIC


def _is_hetero(scenario, inv=None) -> bool:
    return scenario.system.mode != TrophicMode.PHOTOTROPHIC


# ======================================================================
# Symbols
# ======================================================================

SYMBOLS: list[Symbol] = [
    # --- scenario: cultivation -------------------------------------------
    Symbol(r"P", "areal or volumetric productivity", "g m$^{-2}$ d$^{-1}$ or g L$^{-1}$ d$^{-1}$",
           "system.productivity (data/systems.yaml)"),
    Symbol(r"A", "plant scale: cultivation area or volume", "m$^2$ or m$^3$",
           "scenario.scale"),
    Symbol(r"d_{\mathrm{op}}", "operating days per year", "d yr$^{-1}$",
           "system.operating_days"),
    Symbol(r"\eta_h", "harvesting recovery", "kg kg$^{-1}$", "harvesting.recovery"),
    Symbol(r"g", r"gross biomass cultivated per kg of product, $g = 1/\eta_h$",
           "kg kg$^{-1}$", "derived"),
    Symbol(r"w_\mathrm{C}, w_\mathrm{N}, w_\mathrm{P}",
           "carbon, nitrogen and phosphorus mass fractions of the dry biomass",
           "kg kg$^{-1}$", "organism.carbon / .nitrogen / .phosphorus (data/organisms.yaml)"),
    Symbol(r"\eta_\mathrm{C}", "inorganic carbon utilization efficiency",
           "kg kg$^{-1}$", "system.co2_utilization, floored at 0.05"),
    Symbol(r"\eta_\mathrm{N}", "nutrient uptake efficiency", "kg kg$^{-1}$",
           "system.nutrient_uptake"),
    Symbol(r"Y_{X/S}", "biomass yield on substrate (heterotrophic)", "kg kg$^{-1}$",
           "system.substrate_yield"),
    Symbol(r"w_\mathrm{C}^{S}", "carbon mass fraction of the substrate (glucose)",
           "kg kg$^{-1}$", "constant 0.4001"),
    # --- scenario: energy and downstream ---------------------------------
    Symbol(r"e_\mathrm{cult}, e_\mathrm{harv}, e_\mathrm{dry}, e_\mathrm{ext}",
           "electricity intensity of each stage", "kWh kg$^{-1}$",
           "system / harvesting / drying / extraction"),
    Symbol(r"s_\mathrm{in}, s_\mathrm{out}",
           "solids fraction entering and leaving drying", "kg kg$^{-1}$",
           "harvesting.final_solids, drying.final_solids"),
    Symbol(r"h_\mathrm{ev}", "thermal energy per kg of water evaporated", "MJ kg$^{-1}$",
           "drying.thermal_mj_per_kg_water"),
    Symbol(r"\sigma, \rho_\sigma", "solvent use and solvent recovery", "kg kg$^{-1}$",
           "extraction.solvent_kg_per_kg, .solvent_recovery"),
    # --- economics --------------------------------------------------------
    Symbol(r"c_k", "unit price of flow $k$", "EUR per unit of $k$", "Economics"),
    Symbol(r"C_\mathrm{eq}", "delivered equipment cost", "EUR", "derived"),
    Symbol(r"f_\mathrm{inst}", "installation factor", "-", "economics.installation_factor"),
    Symbol(r"f_\mathrm{ind}", "indirect (engineering + contingency) factor", "-",
           "economics.indirect_factor"),
    Symbol(r"f_\mathrm{wc}, f_\mathrm{su}",
           "working capital and start-up, as fractions of DFC", "-",
           "economics.working_capital_frac, .startup_frac"),
    Symbol(r"f_\mathrm{mt}, f_\mathrm{ins}",
           "maintenance and insurance, as fractions of DFC per year", "yr$^{-1}$",
           "economics.maintenance_frac, .insurance_frac"),
    Symbol(r"f_\mathrm{ov}", "overhead, as a fraction of materials + utilities + labour",
           "-", "economics.overhead_frac"),
    Symbol(r"n_\mathrm{dep}", "straight-line depreciation period", "yr",
           "economics.depreciation_years"),
    Symbol(r"n", "project evaluation horizon", "yr", "economics.plant_lifetime"),
    Symbol(r"i", "discount rate", "-", "economics.discount_rate"),
    Symbol(r"\tau", "income tax rate", "-", "economics.tax_rate"),
    Symbol(r"L", "annual labour cost", "EUR yr$^{-1}$", "economics.labor_cost_per_year"),
    # --- LCIA -------------------------------------------------------------
    Symbol(r"\gamma_k", "characterization factor of flow $k$ for the impact category",
           "impact unit per unit of $k$", "LCIAFactors (data/lcia.yaml)"),
    Symbol(r"q_k", "quantity of flow $k$ per kg of product", "unit of $k$ kg$^{-1}$",
           "Inventory"),
]


# ======================================================================
# Equations
# ======================================================================

def _equations_inventory() -> list[Equation]:
    return [
        Equation(
            "inv.production",
            r"m_\mathrm{gross} = \begin{cases}"
            r" P\,A\,d_\mathrm{op}/1000 & \text{area basis}\\"
            r" P\,(1000\,A)\,d_\mathrm{op}/1000 & \text{volume basis}\\"
            r" m_\mathrm{batch}\,N_\mathrm{batch} & \text{batch}"
            r"\end{cases}\qquad m_\mathrm{prod} = \eta_h\, m_\mathrm{gross}",
            "Annual gross biomass cultivated and annual product leaving the gate. "
            "In batch mode the number of batches is set by the cycle time over the "
            r"operating window, $N_\mathrm{batch} = 24\,d_\mathrm{op}/t_\mathrm{cycle}$.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: _stated_annual_kg(s),
            engine=lambda s, inv, tea, lca: inv.annual_biomass_kg,
        ),
        Equation(
            "inv.gpp",
            r"g = 1/\eta_h",
            "Gross biomass required per kilogram of product. Every cultivation-stage "
            "flow below is referred to this factor, so harvesting losses propagate "
            "upstream and only upstream.",
            "inventory.build_inventory",
        ),
        Equation(
            "inv.carbon.photo",
            r"q_{\mathrm{CO_2},\mathrm{fix}} = w_\mathrm{C}\,g\,\frac{M_{\mathrm{CO_2}}}{M_\mathrm{C}}"
            r"\qquad q_{\mathrm{CO_2},\mathrm{sup}} = q_{\mathrm{CO_2},\mathrm{fix}}/\eta_\mathrm{C}",
            "Phototrophic carbon. The carbon locked into the biomass is fixed by the "
            "composition; the supply exceeds it by the utilization efficiency. With a "
            r"bicarbonate feed the reagent is dosed on the same carbon basis, "
            r"$q_\mathrm{NaHCO_3} = w_\mathrm{C}\,g\,(M_\mathrm{NaHCO_3}/M_\mathrm{C})/\eta_\mathrm{C}$.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: (
                s.organism.carbon * _gpp(s) * CO2_PER_C),
            engine=lambda s, inv, tea, lca: inv.co2_fixed_per_kg,
            applies=_is_photo,
        ),
        Equation(
            "inv.carbon.hetero",
            r"q_S = g/Y_{X/S} \qquad "
            r"q_{\mathrm{CO_2},\mathrm{resp}} = \left(q_S\,w_\mathrm{C}^{S} - w_\mathrm{C}\,g\right)"
            r"\frac{M_{\mathrm{CO_2}}}{M_\mathrm{C}}",
            "Heterotrophic carbon. The substrate demand follows the mass yield; the "
            "substrate carbon not incorporated into biomass is respired. The respired "
            "term is reported and is **not** summed into the GWP: substrate carbon "
            "enters biogenic and leaves biogenic, so both sides are excluded under the "
            "0/0 convention. Its sign is the admissibility constraint of SI S2.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: _gpp(s) / max(s.system.substrate_yield, 1e-6),
            engine=lambda s, inv, tea, lca: inv.substrate_per_kg,
            applies=_is_hetero,
        ),
        Equation(
            "inv.nutrients",
            r"q_\mathrm{N} = \frac{w_\mathrm{N}\,g}{\eta_\mathrm{N}},\qquad "
            r"q_\mathrm{P} = \frac{w_\mathrm{P}\,g}{\eta_\mathrm{N}},\qquad "
            r"q_{j,\mathrm{em}} = q_j\,(1-\eta_\mathrm{N})",
            "Nitrogen and phosphorus supply, and the unassimilated fraction that leaves "
            "as a potential water emission.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: s.organism.nitrogen * _gpp(s) / _uptake(s),
            engine=lambda s, inv, tea, lca: inv.nitrogen_per_kg,
        ),
        Equation(
            "inv.water",
            r"q_\mathrm{W} = v_\mathrm{W}\,g",
            "Net water consumption, referred to the gross biomass cultivated.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: s.system.water_m3_per_kg * _gpp(s),
            engine=lambda s, inv, tea, lca: inv.water_m3_per_kg,
        ),
        Equation(
            "inv.electricity",
            r"q_E = \underbrace{(e_\mathrm{cult} + e_\mathrm{harv})\,g}_{\text{referred to gross biomass}}"
            r" + \underbrace{e_\mathrm{dry} + e_\mathrm{ext}}_{\text{referred to the product}}",
            "Electricity. Cultivation and harvesting act on the gross biomass and carry "
            "the factor $g$; drying and downstream extraction act on what survives "
            "harvesting and do not. This is why an error in the harvesting recovery "
            "propagates unevenly across the flows (SI S3).",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: _stated_electricity(s),
            engine=lambda s, inv, tea, lca: inv.elec_kwh_per_kg,
        ),
        Equation(
            "inv.drying",
            r"m_\mathrm{ev} = \frac{1-s_\mathrm{in}}{s_\mathrm{in}} - \frac{1-s_\mathrm{out}}{s_\mathrm{out}},"
            r"\qquad q_H = m_\mathrm{ev}\,h_\mathrm{ev} + h_\mathrm{cult}\,g + h_\mathrm{ext}",
            "Water removed in drying, from the solids fractions on either side of the "
            "step, and the thermal demand it drives. When the dryer or the cultivation "
            "heater is electric the corresponding term is moved to $q_E$ at "
            "3.6 MJ kWh$^{-1}$ instead.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: _stated_heat(s),
            engine=lambda s, inv, tea, lca: inv.heat_mj_per_kg,
        ),
        Equation(
            "inv.solvent",
            r"q_\sigma = \sigma\,(1-\rho_\sigma)",
            "Net solvent make-up: only what is not recovered is consumed.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: (
                s.extraction.solvent_kg_per_kg
                * (1.0 - min(max(s.extraction.solvent_recovery, 0.0), 1.0))),
            engine=lambda s, inv, tea, lca: inv.solvent_net_per_kg,
            applies=lambda s, inv: s.extraction.enabled,
        ),
        Equation(
            "inv.land",
            r"q_A = \frac{A\,a_\mathrm{unit}}{m_\mathrm{prod}}",
            "Land occupation per kilogram of product.",
            "inventory.build_inventory",
            stated=lambda s, inv, tea, lca: (
                s.scale * s.system.land_m2_per_unit / inv.annual_biomass_kg),
            engine=lambda s, inv, tea, lca: inv.land_m2a_per_kg,
            applies=lambda s, inv: inv.annual_biomass_kg > 0,
        ),
    ]


def _equations_capital() -> list[Equation]:
    return [
        Equation(
            "tea.equipment",
            r"C_\mathrm{eq} = \underbrace{A\,c_\mathrm{cult}}_{\text{cultivation}}"
            r" + \left(c_\mathrm{harv} + c_\mathrm{dry} + c_\mathrm{ext}\right) m_\mathrm{prod}",
            "Delivered equipment cost. Cultivation equipment scales with the "
            "cultivation area or volume; the downstream sections scale with annual "
            "capacity. **The scaling is linear: there is no power-law exponent and no "
            "reference capacity.** See the assumptions note below, because this is a "
            "modelling choice with a validity range and not a neutral default.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: _stated_equipment(s, inv),
            engine=lambda s, inv, tea, lca: tea.equipment_cost,
        ),
        Equation(
            "tea.dfc",
            r"C_\mathrm{DFC} = f_\mathrm{inst}\,C_\mathrm{eq}\,(1 + f_\mathrm{ind})"
            r" + A\,a_\mathrm{unit}\,c_\mathrm{land}",
            "Direct fixed capital: equipment installed, then engineering and "
            "contingency applied to the installed cost, plus the one-off land purchase.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: _stated_dfc(s, inv),
            engine=lambda s, inv, tea, lca: tea.dfc,
        ),
        Equation(
            "tea.investment",
            r"C_\mathrm{TI} = C_\mathrm{DFC}\,(1 + f_\mathrm{wc} + f_\mathrm{su})",
            "Total investment: direct fixed capital plus working capital and start-up, "
            "both taken as fractions of it. Working capital is recovered in the final "
            "year of the cash-flow series; start-up is not.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: (
                tea.dfc * (1 + s.economics.working_capital_frac + s.economics.startup_frac)),
            engine=lambda s, inv, tea, lca: tea.total_investment,
        ),
    ]


def _equations_operating() -> list[Equation]:
    return [
        Equation(
            "tea.materials",
            r"C_\mathrm{RM} = m_\mathrm{prod} \sum_{k \in \mathrm{materials}} q_k\,c_k",
            "Raw materials: the physics-derived flows (CO$_2$ or bicarbonate, N, P, "
            "water, substrate, solvent make-up) priced at their unit costs, plus any "
            "explicit media or chemical line items the scenario declares.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: _stated_materials(s, inv),
            engine=lambda s, inv, tea, lca: tea.raw_materials_cost,
        ),
        Equation(
            "tea.utilities",
            r"C_\mathrm{UT} = m_\mathrm{prod}\left(q_E\,c_E + q_H\,c_H"
            r" + \sum_{k \in \mathrm{utilities}} q_k\,c_k\right)",
            "Utilities: electricity and process heat at their unit prices, plus "
            "explicit utility line items.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: _stated_utilities(s, inv),
            engine=lambda s, inv, tea, lca: tea.utilities_cost,
        ),
        Equation(
            "tea.facility",
            r"D = C_\mathrm{DFC}/n_\mathrm{dep}, \qquad "
            r"C_\mathrm{FD} = D + C_\mathrm{DFC}\,(f_\mathrm{mt} + f_\mathrm{ins})",
            "Facility-dependent cost: straight-line depreciation plus maintenance and "
            "insurance. **Depreciation, not an annualised capital charge.** The module "
            r"provides a capital recovery factor $\mathrm{CRF}(i,n) = i(1+i)^n/((1+i)^n-1)$ "
            "but the production cost does not use it, so the reported cost carries no "
            "required return on capital; the return is evaluated separately through NPV "
            "and IRR. Which endpoint a published figure corresponds to is recorded in `results/economic_endpoint_audit.txt`.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: (
                tea.dfc / s.economics.depreciation_years
                + tea.dfc * (s.economics.maintenance_frac + s.economics.insurance_frac)),
            engine=lambda s, inv, tea, lca: tea.facility_dependent,
            applies=lambda s, inv: s.economics.depreciation_years > 0,
        ),
        Equation(
            "tea.aoc",
            r"\mathrm{AOC} = C_\mathrm{RM} + C_\mathrm{UT} + L + C_\mathrm{FD}"
            r" + f_\mathrm{ov}\,(C_\mathrm{RM} + C_\mathrm{UT} + L) + C_\mathrm{other}",
            "Annual operating cost. **Labour is a fixed annual figure independent of "
            "plant capacity**, so the only economy of scale in the model reaches the "
            "unit cost through this term; see the assumptions note.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: _stated_aoc(s, inv, tea),
            engine=lambda s, inv, tea, lca: tea.annual_opex,
        ),
        Equation(
            "tea.cost",
            r"c_\mathrm{prod} = \frac{\mathrm{AOC}}{m_\mathrm{prod}}, \qquad "
            r"c_\mathrm{prod}^\mathrm{net} = \frac{\mathrm{AOC} - R_\mathrm{co}}{m_\mathrm{prod}}",
            "Minimum biomass production cost, gross and net of co-product revenue. "
            "Which of the two a published figure corresponds to is exactly the "
            "classification the economic-endpoint audit records.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: tea.annual_opex / inv.annual_biomass_kg,
            engine=lambda s, inv, tea, lca: tea.production_cost_eur_per_kg,
            applies=lambda s, inv: inv.annual_biomass_kg > 0,
        ),
    ]


def _equations_profitability() -> list[Equation]:
    return [
        Equation(
            "tea.profit",
            r"\Pi_\mathrm{gross} = R - \mathrm{AOC} + R_\mathrm{cr},\qquad "
            r"T = \tau\max(\Pi_\mathrm{gross},0),\qquad "
            r"\Pi_\mathrm{net} = \Pi_\mathrm{gross} - T",
            "Gross profit, tax and net profit. Tax is charged on positive gross profit "
            "only and losses are not carried forward.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: (
                tea.revenues - tea.annual_opex + s.credits_per_year
                - s.economics.tax_rate * max(
                    tea.revenues - tea.annual_opex + s.credits_per_year, 0.0)),
            engine=lambda s, inv, tea, lca: tea.net_profit,
        ),
        Equation(
            "tea.cashflow",
            r"\mathrm{CF} = \Pi_\mathrm{net} + D, \qquad "
            r"\mathbf{cf} = \left(-C_\mathrm{TI},\ \mathrm{CF},\ \dots,\ "
            r"\mathrm{CF} + f_\mathrm{wc}C_\mathrm{DFC}\right)",
            "Annual cash flow, with depreciation added back as a non-cash charge, and "
            "the cash-flow series used for NPV and IRR: one investment outflow at "
            r"$t=0$, then $n$ equal annual inflows, with the working capital recovered "
            "in the final year. There is no construction period, no salvage value, no "
            "escalation and no ramp-up.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: tea.net_profit + tea.depreciation,
            engine=lambda s, inv, tea, lca: tea.annual_cash_flow,
        ),
        Equation(
            "tea.npv",
            r"\mathrm{NPV} = \sum_{t=0}^{n} \frac{\mathrm{cf}_t}{(1+i)^t}, \qquad "
            r"\mathrm{IRR}: \ \mathrm{NPV}(\mathrm{IRR}) = 0",
            "Net present value at the declared discount rate, and the internal rate of "
            "return as the root of the same series, found by bisection on "
            r"$[-0.9, 10]$ and reported as undefined when no sign change exists there.",
            "tea.npv / tea.irr",
            stated=lambda s, inv, tea, lca: _stated_npv(s, tea),
            engine=lambda s, inv, tea, lca: tea.npv,
        ),
        Equation(
            "tea.roi",
            r"\mathrm{ROI} = \frac{\Pi_\mathrm{net}}{C_\mathrm{TI}}, \qquad "
            r"t_\mathrm{pb} = \frac{C_\mathrm{TI}}{\mathrm{CF}}",
            "Return on investment and simple payback period, both undiscounted.",
            "tea.run_tea",
            stated=lambda s, inv, tea, lca: tea.net_profit / tea.total_investment,
            engine=lambda s, inv, tea, lca: tea.roi,
            applies=lambda s, inv: True,
        ),
    ]


def _equations_lca() -> list[Equation]:
    return [
        Equation(
            "lca.impact",
            r"I = \sum_k q_k\,\gamma_k",
            "Every impact category is the inventory contracted with the "
            "characterization factors of that category: GWP, cumulative energy demand, "
            "acidification and the two eutrophication categories all take this form. "
            "Water adds the direct process water to the electricity-borne term, and "
            "land is carried directly from the inventory.",
            "lca.run_lca",
            stated=lambda s, inv, tea, lca: _stated_gwp_gross(s, inv),
            engine=lambda s, inv, tea, lca: lca.gwp_gross_kg_co2eq_per_kg,
        ),
        Equation(
            "lca.biogenic",
            r"\Delta_\mathrm{bio} = \begin{cases}"
            r" 0 & \text{no credit}\\"
            r" -q_{\mathrm{CO_2},\mathrm{fix}} & \text{source-specific, CO}_2\text{ feed}\\"
            r" -q_{\mathrm{CO_2},\mathrm{prod}} & \text{at-gate storage}\\"
            r" -\phi\,q_{\mathrm{CO_2},\mathrm{prod}} & \text{custom, } \phi\in[0,1]"
            r"\end{cases} \qquad I_\mathrm{GWP} = I_\mathrm{GWP}^\mathrm{gross} + \Delta_\mathrm{bio}",
            "The biogenic-carbon adjustment, which is never applied silently: the gross "
            "value, the adjustment and the convention in force are all reported. The "
            "source-specific and at-gate quantities differ by the harvesting recovery — "
            "carbon fixed by biomass lost at harvest never reaches the gate — and both "
            "remain on the inventory so the difference is explicit.",
            "lca._biogenic_adjustment",
            stated=lambda s, inv, tea, lca: _stated_biogenic(s, inv),
            engine=lambda s, inv, tea, lca: lca.biogenic_adjustment_kg_co2eq_per_kg,
        ),
    ]


def _equations_allocation() -> list[Equation]:
    return [
        Equation(
            "alloc.yield",
            r"y_p = \begin{cases}"
            r" \bar{y}_p & \text{override declared}\\"
            r" \left(1 - \sum_{j\neq p} w_j\,\rho_j\right)\rho_p & p \text{ is the residual}\\"
            r" w_p\,\rho_p & \text{otherwise}\end{cases}"
            r"\qquad m_p = y_p\,m_\mathrm{prod}",
            "Product yield per kilogram of dry biomass: the mass fraction of the "
            "biomass fraction it is made from, times the recovery of the step that "
            "makes it. The residual product takes what the others leave, so the split "
            "cannot create mass. A declared override replaces the composition route "
            "entirely, for products whose yield is measured rather than derived.",
            "products.product_yield",
            stated=lambda s, inv, tea, lca: _stated_product_masses(s, inv),
            engine=lambda s, inv, tea, lca: _engine_product_masses(s, inv),
            applies=lambda s, inv: bool(s.products),
        ),
        Equation(
            "alloc.share",
            r"\alpha_p = \frac{m_p\,c_p}{\sum_j m_j\,c_j} \ \text{(economic)}, \qquad "
            r"\alpha_p = \frac{m_p}{\sum_j m_j} \ \text{(mass)}, \qquad "
            r"\sum_p \alpha_p = 1",
            "Allocation shares. Economic allocation is the default and falls back to "
            "mass when no product carries a price; ``none`` assigns the whole burden to "
            "the main product. The burden of each product is "
            r"$\alpha_p$ times the total, so no burden is created or destroyed by the "
            "split.",
            "products._allocation_shares",
            stated=lambda s, inv, tea, lca: 1.0,
            engine=lambda s, inv, tea, lca: _engine_share_sum(s, inv),
            applies=lambda s, inv: bool(s.products)
            and s.extraction.allocation in ("economic", "mass"),
        ),
    ]


def equations() -> list[Equation]:
    """Every governing equation, in the order the specification presents them."""
    return (_equations_inventory() + _equations_capital() + _equations_operating()
            + _equations_profitability() + _equations_lca() + _equations_allocation())


# ======================================================================
# Restatements used by the check. Written from the printed formulas.
# ======================================================================

def _stated_annual_kg(s) -> float:
    sysm = s.system
    if s.batch_mode and s.batch_cycle_time_h > 0:
        gross = s.batch_size_kg * (sysm.operating_days * 24.0 / s.batch_cycle_time_h)
    elif sysm.basis == Basis.AREA:
        gross = sysm.productivity * s.scale * sysm.operating_days / 1000.0
    else:
        gross = sysm.productivity * (s.scale * 1000.0) * sysm.operating_days / 1000.0
    return gross * min(max(s.harvesting.recovery, 1e-6), 1.0)


def _stated_electricity(s) -> float:
    g = _gpp(s)
    elec = (s.system.elec_kwh_per_kg + s.harvesting.elec_kwh_per_kg) * g
    cult_heat = s.system.cultivation_heat_mj_per_kg * g
    if s.system.cultivation_heat_fuel == "electricity":
        elec += cult_heat / 3.6
    if s.drying.enabled:
        elec += s.drying.elec_kwh_per_kg
        if s.drying.fuel == "electricity":
            elec += _evaporated(s) * s.drying.thermal_mj_per_kg_water / 3.6
    if s.extraction.enabled:
        elec += s.extraction.disruption_elec_kwh_per_kg + s.extraction.elec_kwh_per_kg
    return elec


def _evaporated(s) -> float:
    si = min(max(s.harvesting.final_solids, 1e-6), 1.0)
    so = min(max(s.drying.final_solids, 1e-6), 1.0)
    return max((1.0 - si) / si - (1.0 - so) / so, 0.0)


def _stated_heat(s) -> float:
    g = _gpp(s)
    heat = s.system.cultivation_heat_mj_per_kg * g
    if s.system.cultivation_heat_fuel == "electricity":
        heat = 0.0
    if s.drying.enabled and s.drying.fuel != "electricity":
        heat += _evaporated(s) * s.drying.thermal_mj_per_kg_water
    if s.extraction.enabled:
        heat += s.extraction.heat_mj_per_kg
    return heat


def _stated_equipment(s, inv) -> float:
    eco = s.economics
    m = inv.annual_biomass_kg
    return (s.scale * s.system.capex_per_unit
            + eco.harvest_capex_per_kgyr * m
            + (eco.drying_capex_per_kgyr * m if s.drying.enabled else 0.0)
            + (s.extraction.capex_per_kgyr * m if s.extraction.enabled else 0.0))


def _stated_dfc(s, inv) -> float:
    eco = s.economics
    installed = _stated_equipment(s, inv) * eco.installation_factor
    return (installed * (1.0 + eco.indirect_factor)
            + s.scale * s.system.land_m2_per_unit * eco.land_price)


def _stated_materials(s, inv) -> float:
    eco = s.economics
    per_kg = (inv.co2_supply_per_kg * eco.co2_price
              + inv.bicarbonate_supply_per_kg * eco.bicarbonate_price
              + inv.nitrogen_per_kg * eco.nitrogen_price
              + inv.phosphorus_per_kg * eco.phosphorus_price
              + inv.water_m3_per_kg * eco.water_price
              + inv.substrate_per_kg * eco.substrate_price
              + inv.solvent_net_per_kg * s.extraction.solvent_price
              + sum(m.amount_per_kg * m.price for m in s.materials))
    return per_kg * inv.annual_biomass_kg


def _stated_utilities(s, inv) -> float:
    eco = s.economics
    per_kg = (inv.elec_kwh_per_kg * eco.electricity_price
              + inv.heat_mj_per_kg * eco.heat_price
              + sum(u.amount_per_kg * u.price for u in s.utilities))
    return per_kg * inv.annual_biomass_kg


def _stated_aoc(s, inv, tea) -> float:
    eco = s.economics
    variable = _stated_materials(s, inv) + _stated_utilities(s, inv)
    return (variable + eco.labor_cost_per_year + tea.facility_dependent
            + (variable + eco.labor_cost_per_year) * eco.overhead_frac
            + s.other_opex_per_year)


def _stated_npv(s, tea) -> float:
    n = int(round(s.economics.plant_lifetime))
    flows = [-tea.total_investment] + [tea.annual_cash_flow] * n
    flows[-1] += tea.working_capital
    i = s.economics.discount_rate
    return sum(cf / (1.0 + i) ** t for t, cf in enumerate(flows))


def _stated_gwp_gross(s, inv) -> float:
    f = s.lcia
    total = (inv.elec_kwh_per_kg * f.elec_gwp
             + inv.heat_mj_per_kg * f.heat_gwp
             + inv.co2_supply_per_kg * f.co2_supply_gwp
             + inv.bicarbonate_supply_per_kg * f.bicarbonate_gwp
             + inv.nitrogen_per_kg * f.nitrogen_gwp
             + inv.phosphorus_per_kg * f.phosphorus_gwp
             + inv.substrate_per_kg * f.substrate_gwp)
    total += sum(m.amount_per_kg * m.gwp for m in s.materials if m.gwp)
    total += sum(u.amount_per_kg * u.gwp for u in s.utilities if u.gwp)
    if s.extraction.enabled and inv.solvent_net_per_kg > 0 and s.extraction.solvent_gwp:
        total += inv.solvent_net_per_kg * s.extraction.solvent_gwp
    return total


#: Biomass fractions a product can be made of. Mirrors ``products``; stated here
#: so the printed yield equation is restated rather than imported.
_FRACTIONS = ("lipid", "protein", "carbohydrate", "pigment")


def _stated_product_masses(s, inv) -> float:
    """Total annual product mass, from the printed yield formula."""
    total = 0.0
    for p in s.products:
        if p.yield_override > 0:
            y = p.yield_override
        elif p.fraction == "biomass":
            y = p.recovery
        elif p.fraction == "residual":
            taken = sum(getattr(s.organism, o.fraction, 0.0) * o.recovery
                        for o in s.products
                        if o is not p and o.fraction in _FRACTIONS)
            y = max(1.0 - taken, 0.0) * p.recovery
        elif p.fraction in _FRACTIONS:
            y = getattr(s.organism, p.fraction, 0.0) * p.recovery
        else:
            y = 0.0
        total += y * inv.annual_biomass_kg
    return total


def _engine_product_masses(s, inv) -> float:
    from ..products import product_masses
    return sum(product_masses(s, inv).values())


def _engine_share_sum(s, inv) -> float:
    from ..products import _allocation_shares, product_masses
    masses = product_masses(s, inv)
    revenues = {p.name: masses[p.name] * p.price for p in s.products}
    return sum(_allocation_shares(s, masses, revenues).values())


def _stated_biogenic(s, inv) -> float:
    f = s.lcia
    if not f.count_biogenic_uptake:
        return 0.0
    mode = f.carbon_accounting
    mode = mode if isinstance(mode, CarbonAccounting) else CarbonAccounting(mode)
    if mode is CarbonAccounting.NO_BIOGENIC_CREDIT:
        return 0.0
    if mode is CarbonAccounting.SOURCE_SPECIFIC_CREDIT:
        if s.system.carbon_source == CarbonSource.CO2 and inv.co2_fixed_per_kg > 0:
            return -inv.co2_fixed_per_kg
        return 0.0
    if mode is CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE:
        return -inv.biogenic_co2_in_product_per_kg
    if mode is CarbonAccounting.CUSTOM:
        phi = max(0.0, min(float(f.custom_biogenic_credit_fraction), 1.0))
        return -inv.biogenic_co2_in_product_per_kg * phi
    return 0.0


# ======================================================================
# The check
# ======================================================================

@dataclass
class SpecCheck:
    """One evaluation of a printed equation against the engine."""

    equation: str
    scenario: str
    stated: float
    engine: float

    @property
    def residual(self) -> float:
        denom = max(abs(self.stated), abs(self.engine), 1e-12)
        return abs(self.stated - self.engine) / denom

    @property
    def agrees(self) -> bool:
        return self.residual <= REL_TOL


def check_against_engine(scenario, label: str) -> list[SpecCheck]:
    """Evaluate every checkable equation on one scenario."""
    from ..lca import run_lca
    from ..tea import run_tea

    inv = build_inventory(scenario)
    tea = run_tea(scenario, inv)
    lca = run_lca(scenario, inv)

    out: list[SpecCheck] = []
    for eq in equations():
        got = eq.evaluate(scenario, inv, tea, lca)
        if got is None:
            continue
        out.append(SpecCheck(eq.key, label, got[0], got[1]))
    return out


#: The order the specification presents its sections in, and the heading each
#: gets. Keyed by the prefix of the equation keys that belong to it.
SECTIONS: list[tuple[str, str, str]] = [
    ("inv.", "Foreground inventory",
     "Everything below is per kilogram of dry biomass leaving the gate. The "
     "inventory is built once and both analyses read it; prices and "
     "characterization factors are applied to it and are never inputs to it."),
    ("tea.equipment|tea.dfc|tea.investment", "Capital",
     "Equipment, installed cost, direct fixed capital and total investment."),
    ("tea.materials|tea.utilities|tea.facility|tea.aoc|tea.cost", "Operating cost",
     "Annual operating cost and the production cost it defines."),
    ("tea.profit|tea.cashflow|tea.npv|tea.roi", "Profitability",
     "The cash-flow series and the profitability measures taken from it."),
    ("lca.", "Life-cycle impact assessment",
     "Impacts are linear in the inventory; the biogenic-carbon adjustment is the "
     "only term that depends on a declared convention."),
    ("alloc.", "Multi-product yield and allocation",
     "How the biomass is split into products, and how the burden follows."),
]


def _section_of(key: str) -> int:
    for i, (prefixes, _title, _intro) in enumerate(SECTIONS):
        for prefix in prefixes.split("|"):
            if key.startswith(prefix):
                return i
    return len(SECTIONS) - 1


def render_markdown(lib, cases) -> list[str]:
    """The specification as Markdown, with its fidelity check run at build time.

    ``cases`` are the scenario-suite members the check runs over, so the numbers
    printed in the closing paragraph are computed while the document is being
    written rather than quoted from a previous run.
    """
    checks = [c for case in cases
              for c in check_against_engine(case.scenario(lib), case.label)]
    worst = max((c.residual for c in checks), default=0.0)
    disagreeing = [c for c in checks if not c.agrees]

    eqs = equations()
    L: list[str] = [
        "The model is defined here, in symbols, before any evidence about it is "
        "presented. Source code specifies a model exactly but does not *define* "
        "one: a reader cannot check an assumption they have to reverse-engineer. "
        "Every equation below carries the module and function that implements it, "
        "and the closing note reports a check that the two agree.",
        "",
        "### Symbols",
        "",
        "| Symbol | Quantity | Unit | Where its value comes from |",
        "|---|---|---|---|",
    ]
    for sym in SYMBOLS:
        L.append(f"| ${sym.latex}$ | {sym.description} | {sym.unit} | {sym.source} |")
    L += ["", "The functional unit is one kilogram of dry biomass leaving the gate. "
              r"$m_\mathrm{prod}$ denotes the annual production and $g$ the gross "
              "biomass cultivated per kilogram of it, so a flow written with $g$ is "
              "one that harvesting losses act on.", ""]

    numbered = 0
    for idx, (_prefixes, title, intro) in enumerate(SECTIONS):
        members = [e for e in eqs if _section_of(e.key) == idx]
        if not members:
            continue
        L += [f"### {title}", "", intro, ""]
        for eq in members:
            numbered += 1
            L += [f"**({numbered})** {eq.description}", "",
                  f"$$ {eq.latex} $$", "",
                  f"*Implemented in* `{eq.implemented_in}`"
                  + (f" · {eq.note}" if eq.note else ""), ""]

    L += ["### Assumptions that are not neutral", "",
          "Each of these is a choice with a range over which it is defensible, and "
          "each is visible in the equations above only to a reader who already knows "
          "to look for it.", ""]
    for title, body in ASSUMPTIONS:
        L += [f"**{title}.** {body}", ""]

    L += ["### Does the software run these equations?", "",
          f"Every equation above that resolves to a number — {len({c.equation for c in checks})} "
          f"of the {numbered} — is restated independently from the printed formula and "
          f"compared against what the engine returns, on every member of the scenario "
          f"suite: **{len(checks)} evaluations, maximum relative difference "
          f"{worst:.1e}**"
          + (", every one agreeing to floating-point round-off."
             if not disagreeing else
             f", with {len(disagreeing)} DISAGREEING — this document should not be "
             "circulated until that is resolved."),
          "",
          "This is a documentation-fidelity check and nothing more: it answers "
          "whether the paper prints the equations the software runs, and says "
          "nothing about whether the model is right. The equations that do not "
          "resolve to a single number — the definition of $g$, and the case "
          "structure of the product yield — are exercised through the quantities "
          "that depend on them. The check runs in the test suite "
          "(`tests/test_specification.py`), so the specification cannot drift from "
          "the code without a test going red.",
          ""]
    return L


#: Assumptions the equations above make that a reader must be able to see
#: without deriving them. Each is stated with the range over which it is
#: defensible, because none of them is neutral.
ASSUMPTIONS: list[tuple[str, str]] = [
    ("Equipment cost is linear in capacity",
     "There is no power-law exponent and no reference capacity anywhere in the "
     "capital model: the cultivation section scales with area or volume and the "
     "downstream sections with annual capacity, both strictly proportionally. The "
     "unit costs are therefore only defensible near the capacities of the sources "
     "they were taken from, and the model must not be read as predicting the "
     "economies of scale of a plant an order of magnitude away from them. The "
     "consequence is visible in the sensitivity results: plant scale carries a "
     "small total-order index on production cost, and it does so only through the "
     "fixed labour term below."),
    ("Labour is a fixed annual cost",
     "Labour does not scale with capacity, so it is the only term through which "
     "plant scale reaches the unit production cost at all. On a plant much larger "
     "or smaller than the reference this is the assumption that will fail first."),
    ("The production cost carries no return on capital",
     "Facility-dependent cost uses straight-line depreciation. A capital recovery "
     "factor is implemented but is not applied to the production cost, so the "
     "reported figure is a cash-cost-plus-depreciation endpoint and is not "
     "comparable, without adjustment, to a minimum selling price that includes a "
     "required return. Return on capital is evaluated separately through NPV, IRR "
     "and ROI."),
    ("The cash-flow series is flat",
     "One investment outflow at t = 0 followed by n identical annual cash flows, "
     "with working capital recovered in the final year. No construction period, no "
     "production ramp-up, no salvage value, no price or cost escalation, and no "
     "loss carry-forward: tax is charged on positive gross profit only, year by "
     "year."),
    ("Impacts are linear in the inventory",
     "Every impact category is a contraction of the inventory with fixed "
     "characterization factors, so no background process responds to the scale or "
     "the location of the foreground. Marginal or consequential effects are out of "
     "scope by construction."),
    ("Parameters are sampled independently",
     "The uncertainty layer implements grouped dependence but leaves it switched "
     "off, because no correlation data exist for these systems. Correlated inputs "
     "would change the propagated bands and the group decomposition; this is an "
     "assumption, not a finding."),
]
