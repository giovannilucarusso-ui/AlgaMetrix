"""Unit tests for the calculation engine.

Run with ``pytest`` from the repository root.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.inventory import (
    CO2_PER_C,
    MIN_CARBON_UTILIZATION,
    NAHCO3_PER_C,
    build_inventory,
)
from algametrix.lca import run_lca
from algametrix.library import load_library
from algametrix.models import CarbonSource, Scenario, TrophicMode
from algametrix.scenario import run_scenario
from algametrix.tea import capital_recovery_factor, run_tea


@pytest.fixture(scope="module")
def lib():
    return load_library()


def make_scenario(lib, system_name, organism_name, scale, drying_name="Spray drying"):
    return Scenario(
        organism=lib.organisms[organism_name],
        system=lib.systems[system_name],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying[drying_name],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=scale,
    )


def test_library_loads(lib):
    assert "Chlorella vulgaris" in lib.organisms
    assert "Open raceway pond" in lib.systems
    assert lib.economics.discount_rate > 0


def test_capital_recovery_factor():
    # Known value: 8% over 20 years ~ 0.1019
    assert capital_recovery_factor(0.08, 20) == pytest.approx(0.10185, abs=1e-4)
    # Zero rate falls back to straight-line depreciation.
    assert capital_recovery_factor(0.0, 10) == pytest.approx(0.1)


def test_annual_production_area_basis(lib):
    # 100,000 m2 * 20 g/m2/d * 330 d = 660,000,000 g = 660 t gross;
    # times 0.90 recovery = 594 t/yr.
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    inv = build_inventory(scn)
    assert inv.annual_biomass_kg == pytest.approx(594_000, rel=1e-6)


def test_co2_fixed_matches_carbon_content(lib):
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    inv = build_inventory(scn)
    recovery = scn.harvesting.recovery
    expected = scn.organism.carbon * CO2_PER_C / recovery
    assert inv.co2_fixed_per_kg == pytest.approx(expected, rel=1e-9)
    # Supplied CO2 exceeds fixed CO2 because utilization < 1.
    assert inv.co2_supply_per_kg > inv.co2_fixed_per_kg


def test_heterotrophic_uses_substrate_not_co2(lib):
    scn = make_scenario(
        lib, "Stirred-tank fermenter (heterotrophic)", "Schizochytrium sp.", scale=500
    )
    inv = build_inventory(scn)
    assert scn.system.mode == TrophicMode.HETEROTROPHIC
    assert inv.co2_supply_per_kg == 0.0
    assert inv.co2_fixed_per_kg == 0.0
    assert inv.bicarbonate_supply_per_kg == 0.0
    assert inv.substrate_per_kg > 0.0


@pytest.mark.parametrize("harvest", ["Vibrating screen filter", "Rotary drum filter"])
def test_screen_and_drum_filters_available(lib, harvest):
    """The vibrating-screen and rotary-drum harvesting presets load and run."""
    assert harvest in lib.harvesting
    h = lib.harvesting[harvest]
    assert 0.0 < h.recovery <= 1.0
    assert h.elec_kwh_per_kg >= 0.0
    assert 0.0 < h.final_solids < 1.0
    scn = Scenario(
        organism=lib.organisms["Arthrospira platensis (Spirulina)"],
        system=lib.systems["Open raceway pond (Spirulina, NaHCO3)"],
        harvesting=h,
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000.0,
    )
    r = run_scenario(scn)
    assert r.tea.production_cost_eur_per_kg > 0
    # Vibrating screen is the lowest-energy harvest here (0.2 kWh/kg).
    assert r.inventory.elec_breakdown["harvesting"] == pytest.approx(
        h.elec_kwh_per_kg / scn.harvesting.recovery, rel=1e-9
    )


def test_bicarbonate_carbon_source_balance(lib):
    """Spirulina fed with NaHCO3: no CO2 gas, and bicarbonate follows stoichiometry."""
    scn = make_scenario(
        lib, "Open raceway pond (Spirulina, NaHCO3)",
        "Arthrospira platensis (Spirulina)", scale=100_000,
    )
    inv = build_inventory(scn)
    assert scn.system.carbon_source == CarbonSource.BICARBONATE
    assert inv.co2_supply_per_kg == 0.0            # no gaseous CO2
    assert inv.co2_fixed_per_kg > 0.0              # carbon still fixed into biomass
    # NaHCO3 = carbon fixed * (NaHCO3/C molar ratio) / utilization, per kg product.
    util = scn.system.co2_utilization
    carbon_per_product = scn.organism.carbon / scn.harvesting.recovery
    expected = carbon_per_product * NAHCO3_PER_C / util
    assert inv.bicarbonate_supply_per_kg == pytest.approx(expected, rel=1e-9)
    # Calibrated to Padi et al. (2023): ~5 kg NaHCO3 per kg spirulina.
    assert 4.5 < inv.bicarbonate_supply_per_kg < 5.5


def test_bicarbonate_cost_enters_raw_materials(lib):
    scn = make_scenario(
        lib, "Open raceway pond (Spirulina, NaHCO3)",
        "Arthrospira platensis (Spirulina)", scale=100_000,
    )
    inv = build_inventory(scn)
    tea = run_tea(scn, inv)
    assert "Bicarbonate (NaHCO3)" in tea.opex_breakdown
    per_kg = inv.bicarbonate_supply_per_kg * scn.economics.bicarbonate_price
    assert per_kg > 0.0
    assert tea.opex_breakdown["Bicarbonate (NaHCO3)"] == pytest.approx(
        per_kg * inv.annual_biomass_kg, rel=1e-9
    )


def test_bicarbonate_carbon_not_credited_as_biogenic(lib):
    """NaHCO3 carbon is mined, not atmospheric, so it must not earn the gate credit."""
    scn = make_scenario(
        lib, "Open raceway pond (Spirulina, NaHCO3)",
        "Arthrospira platensis (Spirulina)", scale=100_000,
    )
    assert scn.lcia.count_biogenic_uptake is True
    inv = build_inventory(scn)
    lca = run_lca(scn, inv)
    assert "Biogenic CO2 uptake" not in lca.gwp_breakdown
    assert "Bicarbonate (NaHCO3)" in lca.gwp_breakdown
    assert lca.gwp_kg_co2eq_per_kg > 0.0          # not spuriously carbon-negative


def test_co2_gas_carbon_is_credited_as_biogenic(lib):
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    inv = build_inventory(scn)
    lca = run_lca(scn, inv)
    assert scn.system.carbon_source == CarbonSource.CO2
    assert lca.gwp_breakdown["Biogenic CO2 uptake"] < 0.0


def test_zero_utilization_does_not_blow_up(lib):
    """Regression: pushing CO2 utilization to 0 must not explode the CO2 supply."""
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    inv_ref = build_inventory(scn)
    for util in (0.0, -1.0, 1e-9):
        scn.system.co2_utilization = util
        inv = build_inventory(scn)
        # Floored to MIN_CARBON_UTILIZATION -> supply is finite and bounded.
        assert inv.co2_supply_per_kg == pytest.approx(
            inv_ref.co2_fixed_per_kg / MIN_CARBON_UTILIZATION, rel=1e-9
        )
        assert inv.co2_supply_per_kg < 1e3
        tea = run_tea(scn, inv)
        assert tea.production_cost_eur_per_kg < 1e6   # no runaway cost


def test_validation_references_load(lib):
    """The validation library loads and carries the seeded papers."""
    from algametrix.benchmarks import load_validation_references

    refs = load_validation_references()
    assert len(refs) >= 2
    papers = {r.paper for r in refs}
    assert any("Padi" in p for p in papers)        # TEA calibration/reproduction
    assert any("Frontiers" in p for p in papers)   # independent LCA validation
    assert any(r.type == "DSP" for r in refs)      # downstream-processing anchors
    for r in refs:
        assert r.type in ("TEA", "LCA", "DSP")
        assert r.metric and r.paper_value and r.model_value


def test_downstream_presets_load_and_run(lib):
    """The catalogued downstream presets load and drive the inventory correctly."""
    from algametrix.models import Product

    # Catalogue is populated and carries the key technologies the UI offers.
    names = set(lib.extraction)
    assert "Supercritical CO2 extraction" in names
    assert any("Hexane" in n for n in names)
    assert any("ultrafiltration" in n.lower() for n in names)
    # Tangential-membrane harvesting presets are available too.
    assert "Cross-flow ultrafiltration (tangential)" in lib.harvesting

    # Every preset is a ready-to-use, enabled Extraction with a citation.
    for ext in lib.extraction.values():
        assert ext.enabled and ext.notes

    # Supercritical CO2: high solvent-to-feed but recycled, so a small net make-up.
    sc = lib.extraction["Supercritical CO2 extraction"]
    scn = Scenario(
        organism=lib.organisms["Nannochloropsis sp."],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Cross-flow ultrafiltration (tangential)"],
        drying=lib.drying["No drying (wet paste)"],
        economics=lib.economics, lcia=lib.lcia, scale=200_000.0,
        extraction=sc,
        products=[Product("Oil", "lipid", recovery=0.9, price=5.0, is_main=True),
                  Product("Residual", "residual", recovery=1.0, price=0.1)],
    )
    inv = build_inventory(scn)
    expected_net = sc.solvent_kg_per_kg * (1.0 - sc.solvent_recovery)
    assert inv.solvent_net_per_kg == pytest.approx(expected_net, rel=1e-9)
    # Its extraction electricity (disruption + processing) shows up in the breakdown.
    assert inv.elec_breakdown["extraction"] == pytest.approx(
        sc.disruption_elec_kwh_per_kg + sc.elec_kwh_per_kg, rel=1e-9
    )
    run_scenario(scn)  # full pipeline must not raise


def test_cultivation_heat_routes_by_fuel(lib):
    """Cultivation heat goes to the heat account (gas) or electricity (electric)."""
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    base = build_inventory(scn)
    gpp = 1.0 / scn.harvesting.recovery

    scn.system.cultivation_heat_mj_per_kg = 50.0
    scn.system.cultivation_heat_fuel = "natural_gas"
    gas = build_inventory(scn)
    assert gas.heat_mj_per_kg == pytest.approx(base.heat_mj_per_kg + 50.0 * gpp, rel=1e-9)
    assert gas.elec_kwh_per_kg == pytest.approx(base.elec_kwh_per_kg, rel=1e-9)

    scn.system.cultivation_heat_fuel = "electricity"
    ele = build_inventory(scn)
    assert ele.heat_mj_per_kg == pytest.approx(base.heat_mj_per_kg, rel=1e-9)
    assert ele.elec_kwh_per_kg == pytest.approx(
        base.elec_kwh_per_kg + 50.0 * gpp / 3.6, rel=1e-9
    )


def test_cultivation_heat_zero_is_noop(lib):
    """Default (0 heat) leaves every existing system unchanged."""
    scn = make_scenario(lib, "Tubular photobioreactor", "Chlorella vulgaris", 100_000)
    assert scn.system.cultivation_heat_mj_per_kg == 0.0
    inv = build_inventory(scn)
    r = run_scenario(scn)
    assert r.tea.production_cost_eur_per_kg > 0


def test_minimum_selling_price_breaks_even(lib):
    """MEPP is the price at which NPV crosses zero."""
    from algametrix.scenario import minimum_selling_price

    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    scn.product_price = 10.0
    mepp = minimum_selling_price(scn)
    assert mepp is not None and mepp > 0
    scn.product_price = mepp
    npv0 = run_scenario(scn).tea.npv
    assert abs(npv0) < 0.02 * abs(run_scenario(scn).tea.total_investment)
    # Below MEPP the project is loss-making, above it is profitable.
    scn.product_price = mepp * 0.9
    assert run_scenario(scn).tea.npv < 0
    scn.product_price = mepp * 1.1
    assert run_scenario(scn).tea.npv > 0


def test_phycocyanin_is_a_composition_fraction(lib):
    """A product with fraction='phycocyanin' reads the organism's pigment fraction."""
    from algametrix.products import product_yield
    from algametrix.models import Product

    spir = lib.organisms["Arthrospira platensis (Spirulina)"]
    assert spir.phycocyanin > 0
    scn = make_scenario(
        lib, "Open raceway pond (Spirulina, NaHCO3)",
        "Arthrospira platensis (Spirulina)", 100_000,
    )
    p = Product("C-phycocyanin", fraction="phycocyanin", recovery=0.55, is_main=True)
    scn.products = [p]
    # yield = content (0.11) * recovery (0.55) -> Padi's ~6% achieved
    assert product_yield(scn, p) == pytest.approx(spir.phycocyanin * 0.55, rel=1e-9)


def test_production_cost_positive_and_finite(lib):
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    r = run_scenario(scn)
    assert r.tea.production_cost_eur_per_kg > 0
    assert r.tea.production_cost_eur_per_kg < 1e6
    # OPEX breakdown should sum (minus annualized capex) to annual OPEX.
    opex_only = sum(
        v for k, v in r.tea.opex_breakdown.items() if k != "Annualized CAPEX"
    )
    assert opex_only == pytest.approx(r.tea.annual_opex, rel=1e-9)


def test_biogenic_credit_lowers_gwp(lib):
    scn = make_scenario(lib, "Open raceway pond", "Chlorella vulgaris", 100_000)
    with_credit = run_scenario(scn).lca.gwp_kg_co2eq_per_kg

    scn.lcia.count_biogenic_uptake = False
    without_credit = run_scenario(scn).lca.gwp_kg_co2eq_per_kg

    assert with_credit < without_credit


def test_no_drying_has_no_heat(lib):
    scn = make_scenario(
        lib, "Open raceway pond", "Chlorella vulgaris", 100_000,
        drying_name="No drying (wet paste)",
    )
    inv = build_inventory(scn)
    assert inv.heat_mj_per_kg == 0.0
