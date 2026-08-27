"""Run a full scenario: inventory -> TEA + LCA (+ product allocation)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .inputcheck import InadmissibleScenarioError, errors
from .inventory import Inventory, build_inventory
from .lca import LCAResult, run_lca
from .models import Scenario
from .products import ProductResult, compute_products, main_product
from .tea import TEAResult, run_tea


@dataclass
class Results:
    """Bundle of everything computed for a scenario."""

    scenario: Scenario
    inventory: Inventory
    tea: TEAResult
    lca: LCAResult
    products: list[ProductResult] = field(default_factory=list)
    main_product: ProductResult | None = None


def run_scenario(scenario: Scenario, *, validate: bool = True) -> Results:
    """Build the inventory once and run both analyses on it.

    The balance has to divide by harvesting recovery, carbon utilization,
    nutrient uptake and substrate yield, so it bounds each of them before use. A
    scenario that needs one of those bounds is not a scenario the numbers
    describe: with ``validate=True`` — the default — it is refused, and
    :class:`~algametrix.inputcheck.InadmissibleScenarioError` names the fields.
    The desktop client has always blocked on the same rules; this puts the same
    guarantee under any script that imports the engine.

    Pass ``validate=False`` where computing past the bound is the point — a
    sweep exploring a range, a sampler that may step outside it. The bounds that
    actually fired are then on ``results.inventory.clamps``, one record each,
    with the value given and the value used.
    """
    if validate:
        bad = errors(scenario)
        if bad:
            raise InadmissibleScenarioError(bad)
    inv = build_inventory(scenario)
    tea = run_tea(scenario, inv)
    lca = run_lca(scenario, inv)
    products, main = compute_products(
        scenario, inv, tea.annual_opex,
        lca.gwp_kg_co2eq_per_kg, lca.ced_mj_per_kg,
    )
    return Results(
        scenario=scenario,
        inventory=inv,
        tea=tea,
        lca=lca,
        products=products,
        main_product=main,
    )


def minimum_selling_price(
    scenario: Scenario, price_tol: float = 1e-3, max_iter: int = 100
) -> float | None:
    """Minimum expected product price (MEPP) giving NPV = 0 — the break-even price.

    Bisects the selling price of the **main product** (EUR/kg): ``product_price``
    for a whole-biomass scenario, or the main :class:`Product`'s price for a
    multi-product one (co-product prices held fixed). NPV rises monotonically with
    price, so bisection is exact. Returns ``None`` if no positive price balances NPV.
    This mirrors the MEPP that Padi et al. (2023) report as their headline metric.
    """

    def npv_at(price: float) -> float:
        scn = copy.deepcopy(scenario)
        if scn.products:
            mp = main_product(scn)
            for p in scn.products:
                if mp is not None and p.name == mp.name:
                    p.price = price
        else:
            scn.product_price = price
        return run_scenario(scn).tea.npv

    if npv_at(0.0) >= 0:
        return 0.0  # co-products / credits already cover the investment

    lo, hi = 0.0, max(scenario.product_price or 0.0, 1.0)
    for _ in range(60):                 # grow an upper bound until NPV turns positive
        if npv_at(hi) >= 0:
            break
        hi *= 2.0
    else:
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if npv_at(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < price_tol:
            break
    return 0.5 * (lo + hi)
