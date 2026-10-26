"""Production cost, net cost, allocated cost and break-even price.

Four economic indicators answer four different questions, and the paper reports
them apart:

* the production cost per kg of dry biomass: annual operating cost, including
  straight-line depreciation, over annual output, before any revenue;
* the net production cost per kg of dry biomass: the same after co-product
  revenue and other credits are subtracted;
* the allocated production cost per kg of a product: the operating cost times
  the product's allocation share, over its annual mass. With the allocation
  ``"none"`` the main product carries all of it and no revenue is subtracted;
* the break-even price of the main product: the price at which the NPV over the
  plant life is zero after tax, with the prices of the co-products held fixed
  (:func:`algametrix.scenario.minimum_selling_price`).

The first three involve no discount rate. The break-even price does, and it also
carries tax, working capital, start-up cost and the end of depreciation, so it
sits above the production cost by an amount set by the financial assumptions.

Table D of the manuscript gives the production cost and the break-even price of
the archetypes and of the single-product reconstructions whose cost is compared
with a source. Table C gives the four indicators, and the gross GWP per kg of
main product under economic and under mass allocation, for the multi-product
scenarios of the verification suite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..library import Library, load_library
from ..models import Scenario
from ..scenario import minimum_selling_price, run_scenario
from . import archetypes, reconstructions, studies, suite
from .basis import LIBRARY_PRICE_BASIS

#: Allocation bases reported in Table C, in print order.
ALLOCATIONS = ("economic", "mass", "none")


def crf(rate: float, years: float) -> float:
    """Capital recovery factor, i (1 + i)^n / ((1 + i)^n - 1); 1/n at i = 0."""
    if rate == 0:
        return 1.0 / years
    growth = (1.0 + rate) ** years
    return rate * growth / (growth - 1.0)


def simplified_gap(scenario: Scenario) -> float:
    """C_DFC [CRF(i, n) - 1/n_dep] / (m c_prod).

    The relative gap between break-even price and production cost of a
    single-product plant with no tax, working capital or start-up cost. With
    those set to zero the engine returns exactly this, which the tests check.
    """
    res = run_scenario(scenario)
    eco = scenario.economics
    dep_rate = 1.0 / eco.depreciation_years if eco.depreciation_years > 0 else 0.0
    extra = res.tea.dfc * (crf(eco.discount_rate, eco.plant_lifetime) - dep_rate)
    return extra / res.tea.annual_opex


# --------------------------------------------------------------------------
# Table D: production cost and break-even price
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BreakEven:
    """Both economic endpoints of one single-product scenario."""

    key: str
    label: str
    group: str                    # "archetype" | "reconstruction"
    basis: str                    # currency and price year of the price set
    production_cost: float        # per kg dry biomass
    break_even: float             # per kg dry biomass, NPV = 0 after tax
    discount_rate: float
    lifetime: float
    depreciation_years: float
    tax_rate: float
    depreciation_share: float     # depreciation / annual operating cost
    simplified_gap: float
    same_as: str = ""             # the reconstruction an archetype is built from

    @property
    def gap(self) -> float:
        return self.break_even / self.production_cost - 1.0


def _break_even(key: str, label: str, group: str, basis: str, scn: Scenario,
                same_as: str = "") -> BreakEven:
    res = run_scenario(scn)
    eco = scn.economics
    p_star = minimum_selling_price(scn)
    if p_star is None:
        raise ValueError(f"{key}: no positive price balances the NPV")
    return BreakEven(
        key=key, label=label, group=group, basis=basis,
        production_cost=res.tea.production_cost_eur_per_kg,
        break_even=p_star,
        discount_rate=eco.discount_rate,
        lifetime=eco.plant_lifetime,
        depreciation_years=eco.depreciation_years,
        tax_rate=eco.tax_rate,
        depreciation_share=res.tea.depreciation / res.tea.annual_opex,
        simplified_gap=simplified_gap(scn),
        same_as=same_as,
    )


def break_even_rows(lib: Library | None = None, dataset=None) -> list[BreakEven]:
    """The archetypes, then every single-product reconstruction with a compared cost.

    A reconstruction that builds the same scenario as an archetype is printed
    once, on the archetype's row. The GWP-only reconstructions are left out:
    their prices are defaults that describe no study.
    """
    lib = lib or load_library()
    dataset = dataset if dataset is not None else studies.default_dataset()
    single = [name for name in reconstructions.cost_builders()
              if not reconstructions.build(name, lib).products]
    built = {name: reconstructions.build(name, lib) for name in single}

    rows: list[BreakEven] = []
    absorbed: set[str] = set()
    for arch in archetypes.ARCHETYPES:
        scn = archetypes.build(arch.key, lib)
        twin = next((name for name, other in built.items() if other == scn), "")
        if twin:
            absorbed.add(twin)
            basis = reconstructions.price_basis(twin).label
        else:
            basis = LIBRARY_PRICE_BASIS.label
        rows.append(_break_even(f"arch_{arch.key}", arch.label, "archetype", basis, scn,
                                same_as=twin))
    for name in single:
        if name in absorbed:
            continue
        label = suite.study_label(name, dataset) or name
        rows.append(_break_even(f"rec_{name}", label, "reconstruction",
                                reconstructions.price_basis(name).label, built[name]))
    return rows


def left_out_of_break_even() -> list[str]:
    """Reconstructions built for a GWP comparison only, named so the omission shows."""
    return sorted(reconstructions.GWP_ONLY)


# --------------------------------------------------------------------------
# Table C: multi-product scenarios
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Allocated:
    """The main product under one allocation basis."""

    share: float                  # share of operating cost and burden
    cost: float                   # allocated production cost per kg main product
    gwp_gross: float              # gross GWP per kg main product


@dataclass(frozen=True)
class MultiProduct:
    """The four cost indicators and the allocated GWP of one multi-product scenario."""

    key: str
    label: str
    basis: str
    main_product: str
    main_price: float             # per kg main product
    main_yield: float             # kg main product per kg dry biomass
    production_cost: float        # per kg dry biomass
    net_production_cost: float    # per kg dry biomass
    break_even: float             # per kg main product, co-product prices fixed
    gwp_gross: float              # per kg dry biomass
    gwp_net: float                # per kg dry biomass
    allocated: dict[str, Allocated]

    @property
    def gwp_ratio(self) -> float:
        """Economic over mass allocation; the same for the gross and the net value."""
        return self.allocated["economic"].gwp_gross / self.allocated["mass"].gwp_gross


def _allocated(scn: Scenario, method: str) -> Allocated:
    scn = replace(scn, extraction=replace(scn.extraction, allocation=method))
    res = run_scenario(scn)
    main = res.main_product
    total_gross = res.lca.gwp_gross_kg_co2eq_per_kg * res.inventory.annual_biomass_kg
    return Allocated(share=main.allocation_share,
                     cost=main.production_cost_eur_per_kg,
                     gwp_gross=total_gross * main.allocation_share / main.annual_kg)


def multi_product_rows(lib: Library | None = None) -> list[MultiProduct]:
    """Every structurally distinct suite scenario with more than one product."""
    lib = lib or load_library()
    cases, _ = suite.distinct_cases(lib)
    rows: list[MultiProduct] = []
    for case in cases:
        scn = case.scenario(lib)
        if len(scn.products) < 2:
            continue
        res = run_scenario(scn)
        main = res.main_product
        if case.kind == "reconstruction":
            basis = reconstructions.price_basis(case.key.removeprefix("rec_")).label
        else:
            basis = LIBRARY_PRICE_BASIS.label
        p_star = minimum_selling_price(scn)
        if p_star is None:
            raise ValueError(f"{case.key}: no positive price balances the NPV")
        rows.append(MultiProduct(
            key=case.key,
            label=case.label,
            basis=basis,
            main_product=main.name,
            main_price=main.price,
            main_yield=main.annual_kg / res.inventory.annual_biomass_kg,
            production_cost=res.tea.production_cost_eur_per_kg,
            net_production_cost=res.tea.net_production_cost_eur_per_kg,
            break_even=p_star,
            gwp_gross=res.lca.gwp_gross_kg_co2eq_per_kg,
            gwp_net=res.lca.gwp_kg_co2eq_per_kg,
            allocated={m: _allocated(scn, m) for m in ALLOCATIONS},
        ))
    return rows
