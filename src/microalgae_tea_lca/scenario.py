"""Run a full scenario: inventory -> TEA + LCA (+ product allocation)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

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


def run_scenario(scenario: Scenario) -> Results:
    """Build the inventory once and run both analyses on it."""
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
