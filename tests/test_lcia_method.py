"""The life-cycle method declaration: complete, honest, and actually in force.

Three things are checked here, and they are different claims.

* The declaration is **complete**: every field of :class:`LCIAFactors` is
  declared in ``data/lcia.yaml`` with a unit, a source, a geography, a period
  and a quality flag. No characterization factor may live as an undeclared
  default in ``models.py`` again.
* The declaration is **in force**: the factors the engine runs on are the ones
  the file declares, and each of them moves the impact category the file says it
  belongs to. A declaration nothing consumes would be documentation, not a
  specification.
* The coverage it claims is **the coverage there is**: a flow with no factor for
  a category is reported as such rather than counted as a zero burden.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.lca import run_lca
from algametrix.lciamethod import (
    completeness,
    factor_rows,
    load_method,
    method_statement,
)
from algametrix.library import load_library
from algametrix.models import LCIAFactors, Material, Utility
from algametrix.scenario import run_scenario
from algametrix.serialization import scenario_from_dict, scenario_to_dict
from algametrix.templates import build_template

QUALITY_FLAGS = {"sourced", "derived", "indicative"}


@pytest.fixture(scope="module")
def lib():
    return load_library()


@pytest.fixture(scope="module")
def method():
    m = load_method()
    assert m is not None, "data/lcia.yaml is missing"
    return m


# --------------------------------------------------------------------------- #
# Complete
# --------------------------------------------------------------------------- #
def test_every_factor_carries_provenance(method):
    for f in method.factors:
        assert f.unit, f"{f.name} has no unit"
        assert f.source, f"{f.name} has no source"
        assert f.geography, f"{f.name} has no geography"
        assert f.reference_period, f"{f.name} has no reference period"
        assert f.quality in QUALITY_FLAGS, f"{f.name} has quality {f.quality!r}"
        assert f.indicator in {i.key for i in method.indicators}
        assert f.input in {i.key for i in method.inputs}


def test_no_undeclared_factor_defaults(method):
    """Every LCIAFactors field is declared in the data file, not only in code."""
    declared = (set(method.factor_values())
                | set(method.conventions)
                | {"carbon_accounting", "count_biogenic_uptake"})
    fields = {f.name for f in dataclasses.fields(LCIAFactors)}
    assert fields - declared == set(), f"undeclared: {sorted(fields - declared)}"


def test_the_scope_statement_answers_what_iso_asks(method):
    scope = method.scope
    assert method.standard, "no standard named"
    for key in ("study_type", "functional_unit", "boundary"):
        assert scope.get(key), f"no {key} declared"
    assert scope["geography"]["default"]
    assert scope["reference_period"]["default"]
    assert scope["database"]["name"]
    assert method.cutoff.get("rule")
    assert method.allocation.get("hierarchy")
    assert method.included and method.excluded and method.limitations
    for indicator in method.indicators:
        assert indicator.method, f"{indicator.key} names no impact assessment method"
        assert indicator.kind in {"characterized", "inventory"}
    # The exclusions a cradle-to-gate algal LCA is most often asked about.
    outside = " ".join(str(x.get("item", "")).lower() for x in method.excluded)
    for item in ("infrastructure", "transport", "packaging"):
        assert item in outside, f"{item} is not declared as excluded"


def test_the_statement_renders_every_section(method):
    text = method_statement(method)
    for section in ("1  Goal and scope", "2  System boundary", "3  Allocation",
                    "4  Impact assessment", "5  Background factors", "6  Coverage",
                    "7  Declared limitations"):
        assert section in text
    assert "ISO 14044" in text
    # The coverage matrix has to show the gaps, not only the fills.
    assert "\n" in text and " - " in text


def test_factor_rows_export_carries_the_source(method):
    rows = factor_rows(method)
    assert len(rows) == len(method.factors) + len(method.inventory_assumptions)
    assert all(r["source"] for r in rows)
    assert {"factor", "input", "indicator", "value", "unit", "geography",
            "reference_period", "quality", "source"} == set(rows[0])


# --------------------------------------------------------------------------- #
# In force
# --------------------------------------------------------------------------- #
def test_the_library_runs_on_the_declared_factors(lib, method):
    assert lib.lcia_method is not None
    assert lib.lcia == method.lcia_factors()


def test_declared_values_are_the_values_the_engine_used_before():
    """A regression guard: moving the factors into data changed no number."""
    previous = {
        "elec_gwp": 0.35, "elec_ced": 9.5, "elec_water": 0.002,
        "heat_gwp": 0.066, "heat_ced": 1.15,
        "nitrogen_gwp": 8.0, "nitrogen_ced": 45.0,
        "phosphorus_gwp": 2.0, "phosphorus_ced": 25.0,
        "co2_supply_gwp": 0.10, "substrate_gwp": 0.75, "substrate_ced": 12.0,
        "bicarbonate_gwp": 0.87, "bicarbonate_ced": 11.0,
        "n_to_water_frac": 0.3, "p_to_water_frac": 0.5,
        "elec_acid": 0.0018, "heat_acid": 0.00007, "nitrogen_acid": 0.008,
        "phosphorus_acid": 0.006, "substrate_acid": 0.002, "solvent_acid": 0.004,
        "nitrogen_eutroph_n": 0.012, "phosphorus_eutroph_p": 0.03,
        "elec_eutroph_p": 0.00005,
    }
    factors = load_library().lcia
    for name, value in previous.items():
        assert getattr(factors, name) == pytest.approx(value), name


#: One scenario per carbon source and trophic mode, so that between them every
#: declared input is actually purchased by something.
_PERTURBATION_CASES = (
    "Algal-oil biorefinery (phototrophic)",   # CO2 feed, extraction solvent
    "C-phycocyanin (Spirulina)",              # bicarbonate feed
    "Omega-3 oil (heterotrophic fermentation)",  # organic substrate
)


def _impact(scenario, indicator_key, lib):
    inv_result = run_scenario(scenario)
    keys = {
        "gwp": inv_result.lca.gwp_gross_kg_co2eq_per_kg,
        "ced": inv_result.lca.ced_mj_per_kg,
        "water": inv_result.lca.water_m3_per_kg,
        "land": inv_result.lca.land_m2a_per_kg,
        "eutroph_n": inv_result.lca.impacts["Marine eutrophication (kg N-eq)"],
        "eutroph_p": inv_result.lca.impacts["Freshwater eutrophication (kg P-eq)"],
        "acid": inv_result.lca.impacts["Acidification (kg SO₂-eq)"],
    }
    return keys[indicator_key]


def test_every_declared_factor_moves_the_category_it_declares(lib, method):
    """The declaration is a specification of the code, not a description of it.

    Each factor is perturbed by +10% and the indicator it claims to belong to
    has to move in at least one of the four scenarios. A factor that moved
    nothing would be declared but unused; one that moved a different category
    would be declared in the wrong place.
    """
    scenarios = [build_template(name, lib) for name in _PERTURBATION_CASES]
    # The shipped templates all feed CO2 or sugar, so the bicarbonate factors
    # would be declared and never exercised. One Spirulina raceway covers them.
    bicarbonate = dataclasses.replace(
        scenarios[1], system=lib.systems["Open raceway pond (Spirulina, NaHCO3)"])
    scenarios.append(bicarbonate)
    unused = []
    for factor in method.factors:
        moved = False
        for scenario in scenarios:
            base = _impact(scenario, factor.indicator, lib)
            bumped = dataclasses.replace(
                scenario.lcia, **{factor.name: getattr(scenario.lcia, factor.name) * 1.1 + 1e-9})
            perturbed = dataclasses.replace(scenario, lcia=bumped)
            if _impact(perturbed, factor.indicator, lib) != base:
                moved = True
                break
        if not moved:
            unused.append(f"{factor.name} -> {factor.indicator}")
    assert not unused, f"declared but never used: {unused}"


# --------------------------------------------------------------------------- #
# Honest about coverage
# --------------------------------------------------------------------------- #
def test_a_material_without_a_factor_is_reported_not_zeroed(lib):
    scenario = build_template("Whole biomass — food (Chlorella, raceway)", lib)
    scenario.materials = [Material(name="Chelated iron", amount_per_kg=0.01,
                                   price=8.0, gwp=3.0, ced=40.0)]
    result = run_scenario(scenario)
    gaps = result.lca.not_characterized
    for category in ("water", "land", "acid", "eutroph_n", "eutroph_p"):
        assert gaps[category] == ["Chelated iron"]
    assert "gwp" not in gaps and "ced" not in gaps


def test_a_declared_factor_enters_its_category(lib):
    scenario = build_template("Whole biomass — food (Chlorella, raceway)", lib)
    plain = run_scenario(scenario).lca
    scenario.materials = [Material(name="Chelated iron", amount_per_kg=0.01, price=8.0,
                                   gwp=3.0, ced=40.0, acid=0.5, water=0.02, land=0.3,
                                   eutroph_n=0.001, eutroph_p=0.002)]
    loaded = run_scenario(scenario).lca
    assert loaded.impacts["Acidification (kg SO₂-eq)"] == pytest.approx(
        plain.impacts["Acidification (kg SO₂-eq)"] + 0.01 * 0.5)
    assert loaded.water_m3_per_kg == pytest.approx(plain.water_m3_per_kg + 0.01 * 0.02)
    assert loaded.land_m2a_per_kg == pytest.approx(plain.land_m2a_per_kg + 0.01 * 0.3)
    assert loaded.impacts["Marine eutrophication (kg N-eq)"] == pytest.approx(
        plain.impacts["Marine eutrophication (kg N-eq)"] + 0.01 * 0.001)
    assert loaded.impacts["Freshwater eutrophication (kg P-eq)"] == pytest.approx(
        plain.impacts["Freshwater eutrophication (kg P-eq)"] + 0.01 * 0.002)
    assert not loaded.not_characterized


def test_a_utility_reports_the_same_way(lib):
    scenario = build_template("Whole biomass — food (Chlorella, raceway)", lib)
    scenario.utilities = [Utility(name="Chilled water", amount_per_kg=2.0, unit="MJ",
                                  price=0.01, gwp=0.005, ced=0.05)]
    result = run_scenario(scenario)
    assert result.lca.not_characterized["acid"] == ["Chilled water"]


def test_an_undeclared_factor_survives_a_save(lib):
    scenario = build_template("Whole biomass — food (Chlorella, raceway)", lib)
    scenario.materials = [Material(name="Chelated iron", amount_per_kg=0.01, price=8.0,
                                   gwp=3.0, ced=40.0, acid=0.5)]
    back = scenario_from_dict(scenario_to_dict(scenario))
    material = back.materials[0]
    assert material.acid == pytest.approx(0.5)
    assert material.water is None and material.land is None
    assert completeness(back) == completeness(scenario)


def test_the_coverage_matrix_matches_what_the_engine_does(lib, method):
    """No cell claims a factor the engine has no field for, and none hides one."""
    fields = {f.name for f in dataclasses.fields(LCIAFactors)}
    for input_key, row in method.coverage().items():
        for indicator_key, mark in row.items():
            if mark is None or mark.startswith("("):
                continue
            assert mark in fields, f"{input_key}/{indicator_key} names {mark!r}"


def test_water_and_land_stay_as_narrow_as_they_are_declared(lib, method):
    """The two categories the declaration calls inventory-level, kept honest.

    If a future change gives the substrate or the fertilisers a water or land
    factor, this test fails and the declaration in data/lcia.yaml has to be
    updated with it — which is the point.
    """
    coverage = method.coverage()
    for input_key in ("nitrogen", "phosphorus", "substrate", "heat", "co2_supply"):
        assert coverage[input_key]["water"] is None
        assert coverage[input_key]["land"] is None
    assert coverage["electricity"]["water"] == "elec_water"
    assert coverage["electricity"]["land"] is None


def test_the_engine_still_runs_without_a_declaration(tmp_path, lib):
    """A data directory that predates lcia.yaml keeps working, factors and all."""
    import shutil

    from algametrix.library import DEFAULT_DATA_DIR

    shutil.copytree(DEFAULT_DATA_DIR, tmp_path / "data")
    (tmp_path / "data" / "lcia.yaml").unlink()
    params = tmp_path / "data" / "parameters.yaml"
    params.write_text(
        params.read_text(encoding="utf-8")
        + "\nlcia:\n  elec_gwp: 0.5\n  elec_ced: 9.5\n  elec_water: 0.002\n"
          "  heat_gwp: 0.066\n  heat_ced: 1.15\n  nitrogen_gwp: 8.0\n"
          "  nitrogen_ced: 45.0\n  phosphorus_gwp: 2.0\n  phosphorus_ced: 25.0\n"
          "  co2_supply_gwp: 0.10\n  substrate_gwp: 0.75\n  substrate_ced: 12.0\n",
        encoding="utf-8")
    fallback = load_library(tmp_path / "data")
    assert fallback.lcia_method is None
    assert fallback.lcia.elec_gwp == pytest.approx(0.5)
    assert fallback.lcia.elec_acid == pytest.approx(lib.lcia.elec_acid)


def test_a_data_directory_with_no_factors_at_all_says_so(tmp_path):
    import shutil

    from algametrix.library import DEFAULT_DATA_DIR

    shutil.copytree(DEFAULT_DATA_DIR, tmp_path / "data")
    (tmp_path / "data" / "lcia.yaml").unlink()
    with pytest.raises(FileNotFoundError, match="no life-cycle factors"):
        load_library(tmp_path / "data")


def test_run_lca_reports_gaps_on_the_result(lib):
    scenario = build_template("Omega-3 oil (heterotrophic fermentation)", lib)
    from algametrix.inventory import build_inventory

    result = run_lca(scenario, build_inventory(scenario))
    assert result.not_characterized, "the extraction solvent carries no water factor"
    assert "water" in result.not_characterized
