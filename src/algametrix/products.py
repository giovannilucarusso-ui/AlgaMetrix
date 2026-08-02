"""Multi-product output and burden allocation.

When a scenario defines :class:`~algametrix.models.Product` fractions,
the biomass is split into a main product (e.g. algal oil from the lipid fraction)
and co-products (e.g. protein meal). The functional unit then becomes 1 kg of the
main product.

* **Cost** — SuperPro assigns the whole operating cost to the main product and
  treats co-products as revenue credits. Here that corresponds to
  ``allocation = "none"``. ``"economic"`` / ``"mass"`` instead split the cost
  across products (as ISO 14044 does for the environmental burden).
* **Environmental impact** — allocated between products by the chosen method.
"""

from __future__ import annotations

from dataclasses import dataclass

from .inventory import Inventory
from .models import Product, Scenario

_COMPOSITION_FRACTIONS = {"lipid", "protein", "carbohydrate", "ash", "phycocyanin"}


@dataclass
class ProductResult:
    """Allocated economics and impacts for one product."""

    name: str
    annual_kg: float
    price: float
    revenue: float
    allocation_share: float
    production_cost_eur_per_kg: float
    gwp_kg_co2eq_per_kg: float
    ced_mj_per_kg: float
    is_main: bool


def product_yield(scenario: Scenario, product: Product) -> float:
    """kg of ``product`` per kg of dry biomass."""
    if product.yield_override > 0:
        return product.yield_override
    if product.fraction == "biomass":
        base = 1.0
    elif product.fraction == "residual":
        # Whatever composition is not recovered into the other (non-residual) products.
        recovered = 0.0
        for other in scenario.products:
            if other is product or other.fraction not in _COMPOSITION_FRACTIONS:
                continue
            recovered += getattr(scenario.organism, other.fraction, 0.0) * other.recovery
        return max(1.0 - recovered, 0.0) * product.recovery
    elif product.fraction in _COMPOSITION_FRACTIONS:
        base = getattr(scenario.organism, product.fraction, 0.0)
    else:  # custom without an override -> zero
        base = 0.0
    return base * product.recovery


def product_masses(scenario: Scenario, inv: Inventory) -> dict[str, float]:
    """Annual kg produced of each product."""
    return {
        p.name: inv.annual_biomass_kg * product_yield(scenario, p) for p in scenario.products
    }


def main_product(scenario: Scenario) -> Product | None:
    if not scenario.products:
        return None
    for p in scenario.products:
        if p.is_main:
            return p
    return scenario.products[0]


def total_revenue(scenario: Scenario, inv: Inventory) -> float:
    """Total annual product-sales revenue (all products)."""
    masses = product_masses(scenario, inv)
    return sum(masses[p.name] * p.price for p in scenario.products)


def _allocation_shares(scenario, masses, revenues) -> dict[str, float]:
    method = scenario.extraction.allocation
    total_mass = sum(masses.values())
    total_rev = sum(revenues.values())
    mp = main_product(scenario)
    shares: dict[str, float] = {}
    for p in scenario.products:
        if method == "mass":
            shares[p.name] = masses[p.name] / total_mass if total_mass else 0.0
        elif method == "none":
            shares[p.name] = 1.0 if (mp and p.name == mp.name) else 0.0
        else:  # economic (default), falling back to mass if no revenue
            if total_rev > 0:
                shares[p.name] = revenues[p.name] / total_rev
            else:
                shares[p.name] = masses[p.name] / total_mass if total_mass else 0.0
    return shares


def compute_products(scenario: Scenario, inv: Inventory, aoc: float,
                     gwp_per_kg_biomass: float, ced_per_kg_biomass: float
                     ) -> tuple[list[ProductResult], ProductResult | None]:
    """Split annual cost and impacts across the products."""
    if not scenario.products:
        return [], None

    masses = product_masses(scenario, inv)
    revenues = {p.name: masses[p.name] * p.price for p in scenario.products}
    shares = _allocation_shares(scenario, masses, revenues)

    total_gwp = gwp_per_kg_biomass * inv.annual_biomass_kg
    total_ced = ced_per_kg_biomass * inv.annual_biomass_kg
    mp = main_product(scenario)

    results: list[ProductResult] = []
    for p in scenario.products:
        m = masses[p.name]
        share = shares[p.name]
        results.append(
            ProductResult(
                name=p.name,
                annual_kg=m,
                price=p.price,
                revenue=revenues[p.name],
                allocation_share=share,
                production_cost_eur_per_kg=(aoc * share / m) if m > 0 else 0.0,
                gwp_kg_co2eq_per_kg=(total_gwp * share / m) if m > 0 else 0.0,
                ced_mj_per_kg=(total_ced * share / m) if m > 0 else 0.0,
                is_main=(mp is not None and p.name == mp.name),
            )
        )
    main = next((r for r in results if r.is_main), results[0] if results else None)
    return results, main
