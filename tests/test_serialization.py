"""A saved scenario must come back as the scenario that was saved.

The desktop client's Save/Open used to write nine keys and drop everything else:
extraction, products, materials, the waste feed, the batch schedule. The case
came back looking plausible and computing something different, which is the
worst way for a tool like this to fail. These tests hold the round trip to
field-by-field equality over every shipped template, and pin the migration of
the old file so existing saves still open.
"""

from __future__ import annotations

import json
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algametrix.library import load_library  # noqa: E402
from algametrix.models import (  # noqa: E402
    Extraction,
    Material,
    Product,
    Scenario,
    Utility,
    WasteBurdenConvention,
    WasteFeed,
)
from algametrix.scenario import run_scenario  # noqa: E402
from algametrix.serialization import (  # noqa: E402
    FORMAT,
    VERSION,
    ScenarioFormatError,
    load_scenario,
    save_scenario,
    scenario_from_dict,
    scenario_to_dict,
)
from algametrix.templates import TEMPLATES  # noqa: E402


@pytest.fixture(scope="module")
def lib():
    return load_library()


def assert_same(a, b, path: str = "scenario"):
    """Recursive field-by-field equality, so a dropped field names itself."""
    if is_dataclass(a):
        assert is_dataclass(b), f"{path}: expected a dataclass, got {type(b).__name__}"
        for f in fields(a):
            assert_same(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}")
    elif isinstance(a, list):
        assert len(a) == len(b), f"{path}: {len(a)} item(s) saved, {len(b)} loaded"
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(x, y, f"{path}[{i}]")
    elif isinstance(a, float):
        assert a == pytest.approx(b), f"{path}: {a} != {b}"
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
def test_scenario_roundtrip_preserves_all_fields(template, lib):
    original = template.build(lib)
    restored = scenario_from_dict(json.loads(json.dumps(scenario_to_dict(original))))
    assert_same(original, restored)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
def test_roundtrip_reproduces_the_results(template, lib):
    """Equal fields are the mechanism; equal numbers are the promise."""
    original = template.build(lib)
    restored = scenario_from_dict(scenario_to_dict(original))
    a, b = run_scenario(original), run_scenario(restored)
    assert a.tea.production_cost_eur_per_kg == pytest.approx(b.tea.production_cost_eur_per_kg)
    assert a.tea.npv == pytest.approx(b.tea.npv)
    assert a.lca.gwp_kg_co2eq_per_kg == pytest.approx(b.lca.gwp_kg_co2eq_per_kg)
    assert a.inventory.annual_biomass_kg == pytest.approx(b.inventory.annual_biomass_kg)


def _loaded_case(lib) -> Scenario:
    """The QA case: a template plus every advanced setting the old file dropped."""
    scn = next(t for t in TEMPLATES if t.goal == "oil").build(lib)
    scn.materials = list(scn.materials) + [Material("Yeast extract", 0.04, 2.5, 1.8, 30.0)]
    scn.utilities = [Utility("Steam (sterilisation)", 1.2, "kg", 0.02, 0.08, 3.0)]
    scn.waste_feed = WasteFeed(
        enabled=True, name="Whey permeate", kind="food_byproduct", unit="kg",
        nitrogen_per_unit=0.002, substrate_per_unit=0.045, dosed_on="substrate",
        coverage=0.8, price_per_unit=-0.01,
        convention=WasteBurdenConvention.AVOIDED_TREATMENT,
        avoided_treatment_cost_per_unit=0.02,
    )
    scn.credits_per_year = 250_000.0
    scn.other_opex_per_year = 90_000.0
    return scn


def test_advanced_configuration_survives_the_file(tmp_path, lib):
    scn = _loaded_case(lib)
    path = tmp_path / "case.json"
    save_scenario(scn, path)
    back = load_scenario(path)

    assert back.extraction.enabled is True
    assert len(back.products) == len(scn.products) == 3
    assert len(back.materials) == len(scn.materials)
    assert len(back.utilities) == 1
    assert back.waste_feed.enabled is True
    assert back.waste_feed.convention is WasteBurdenConvention.AVOIDED_TREATMENT
    assert back.batch_mode is True
    assert back.credits_per_year == pytest.approx(250_000.0)
    assert back.other_opex_per_year == pytest.approx(90_000.0)
    assert_same(scn, back)


def test_file_declares_its_format_and_version(tmp_path, lib):
    save_scenario(_loaded_case(lib), tmp_path / "case.json")
    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert data["format"] == FORMAT
    assert data["version"] == VERSION


def test_enums_survive_as_their_values(lib):
    scn = _loaded_case(lib)
    data = scenario_to_dict(scn)
    assert data["system"]["mode"] == scn.system.mode.value
    assert data["waste_feed"]["convention"] == "avoided_treatment"
    assert data["lcia"]["carbon_accounting"] == scn.lcia.carbon_accounting.value


def test_version_1_file_still_opens(tmp_path, lib):
    """The nine-key file the previous desktop build wrote."""
    scn = TEMPLATES[0].build(lib)
    old = {
        k: scenario_to_dict(scn)[k]
        for k in ("organism", "system", "harvesting", "drying", "economics", "lcia", "scale")
    }
    old["product_price"] = 8.0
    old["coproduct_revenue"] = 120_000.0   # v1 spelling of coproduct_revenue_per_year
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old), encoding="utf-8")

    back = load_scenario(path)
    assert back.product_price == pytest.approx(8.0)
    assert back.coproduct_revenue_per_year == pytest.approx(120_000.0)
    assert back.organism.name == scn.organism.name
    assert back.extraction.enabled is False   # absent -> the default, not a crash


def test_unknown_keys_are_ignored(lib):
    data = scenario_to_dict(TEMPLATES[0].build(lib))
    data["a_field_from_the_future"] = {"nested": [1, 2, 3]}
    assert scenario_from_dict(data).organism.name == "Chlorella vulgaris"


def test_a_newer_format_is_refused_rather_than_half_loaded(lib):
    data = scenario_to_dict(TEMPLATES[0].build(lib))
    data["version"] = VERSION + 1
    with pytest.raises(ScenarioFormatError, match="newer version"):
        scenario_from_dict(data)


def test_a_foreign_file_is_refused():
    with pytest.raises(ScenarioFormatError, match="not an AlgaMetrix scenario"):
        scenario_from_dict({"format": "something.else", "scale": 1.0})


def test_products_keep_their_identity(lib):
    """Names, main flag and yield overrides are what a multiproduct case *is*."""
    scn = next(t for t in TEMPLATES if t.goal == "pigment").build(lib)
    scn.products.append(Product("Trial fraction", "custom", yield_override=0.012, price=42.0))
    back = scenario_from_dict(scenario_to_dict(scn))
    assert [p.name for p in back.products] == [p.name for p in scn.products]
    assert [p.is_main for p in back.products] == [p.is_main for p in scn.products]
    assert back.products[-1].yield_override == pytest.approx(0.012)


def test_extraction_defaults_survive_an_empty_object(lib):
    scn = TEMPLATES[0].build(lib)
    data = scenario_to_dict(scn)
    data["extraction"] = {}
    assert scenario_from_dict(data).extraction == Extraction()
