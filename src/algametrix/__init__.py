"""AlgaMetrix: open-source techno-economic analysis and LCA for microalgae
and aquatic protist biomass.

Typical usage::

    from algametrix.library import load_library
    from algametrix.models import Scenario
    from algametrix.scenario import run_scenario

    lib = load_library()
    scenario = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000,
    )
    results = run_scenario(scenario)
"""

from __future__ import annotations

from .inventory import Inventory, build_inventory
from .lca import LCAResult, run_lca
from .lciamethod import (
    LCIAMethod,
    completeness,
    completeness_report,
    load_method,
    method_statement,
)
from .library import Library, load_library
from .models import (
    Basis,
    CarbonSource,
    CultivationSystem,
    Drying,
    Economics,
    Extraction,
    Harvesting,
    LCIAFactors,
    Material,
    Organism,
    Product,
    Scenario,
    TrophicMode,
    Utility,
)
from .benchmarks import (
    check_benchmarks,
    infer_category,
    load_benchmarks,
    load_market_prices,
    load_validation_references,
)
from .comparison import scenario_kpis
from .products import ProductResult, compute_products, product_masses
from .scenario import Results, minimum_selling_price, run_scenario
from .sensitivity import PARAMETERS, run_sweep
from .tea import TEAResult, capital_recovery_factor, irr, npv, run_tea
from .uncertainty import MonteCarloResult, run_montecarlo

# Single source of truth for the version: pyproject.toml reads it from here
# (`[tool.setuptools.dynamic]`), so bumping this line is enough for the package
# metadata, the desktop PDF report cover and the console `--version` alike.
__version__ = "1.5.0"

__all__ = [
    "Basis",
    "CarbonSource",
    "CultivationSystem",
    "Drying",
    "Economics",
    "Harvesting",
    "Inventory",
    "Extraction",
    "LCAResult",
    "LCIAFactors",
    "LCIAMethod",
    "Library",
    "Material",
    "MonteCarloResult",
    "Organism",
    "PARAMETERS",
    "Product",
    "ProductResult",
    "Results",
    "Scenario",
    "TEAResult",
    "TrophicMode",
    "Utility",
    "build_inventory",
    "capital_recovery_factor",
    "check_benchmarks",
    "completeness",
    "completeness_report",
    "compute_products",
    "infer_category",
    "irr",
    "load_benchmarks",
    "load_market_prices",
    "load_library",
    "load_method",
    "load_validation_references",
    "method_statement",
    "minimum_selling_price",
    "npv",
    "product_masses",
    "run_lca",
    "run_montecarlo",
    "run_scenario",
    "run_sweep",
    "run_tea",
    "scenario_kpis",
]
