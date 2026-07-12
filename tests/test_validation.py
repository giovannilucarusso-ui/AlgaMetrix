"""Tests for the SuperPro / reference validation module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from microalgae_tea_lca.library import load_library
from microalgae_tea_lca.models import Scenario
from microalgae_tea_lca.scenario import run_scenario
from microalgae_tea_lca.validation import (
    compare,
    model_metrics,
    parse_reference_csv,
    parse_superpro_excel,
)


@pytest.fixture(scope="module")
def results():
    lib = load_library()
    scn = Scenario(
        organism=lib.organisms["Chlorella vulgaris"],
        system=lib.systems["Open raceway pond"],
        harvesting=lib.harvesting["Settling + centrifugation"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=100_000,
    )
    return run_scenario(scn)


def test_compare_pct_diff(results):
    model = model_metrics(results)
    # Reference set so the model is exactly 5% above it -> +5% deviation, "good".
    ref = {"production_cost_eur_per_kg": model["production_cost_eur_per_kg"] / 1.05}
    rows = {r.metric: r for r in compare(ref, results)}
    row = rows["production_cost_eur_per_kg"]
    assert row.pct_diff == pytest.approx(5.0, abs=0.1)
    assert row.status == "good"
    # Metrics absent from the reference report no deviation.
    assert rows["total_capex_eur"].pct_diff is None


def test_parse_reference_csv(tmp_path, results):
    csv_path = tmp_path / "ref.csv"
    csv_path.write_text(
        "# comment line\n"
        "total_capex_eur, 15,630,000\n"
        "production_cost_eur_per_kg, 6.14 EUR/kg\n"
        "unknown_key, 999\n",
        encoding="utf-8",
    )
    ref = parse_reference_csv(csv_path)
    assert ref["total_capex_eur"] == pytest.approx(15_630_000)
    assert ref["production_cost_eur_per_kg"] == pytest.approx(6.14)
    assert "unknown_key" not in ref


def test_parse_superpro_excel(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Total Capital Investment"
    ws["B1"] = 12_500_000
    ws["A2"] = "Annual Operating Cost"
    ws["B2"] = "$ 2,100,000"
    ws["A3"] = "Unit Production Cost"
    ws["B3"] = 6.5
    path = tmp_path / "superpro.xlsx"
    wb.save(path)

    found = parse_superpro_excel(path)
    assert found["total_capex_eur"] == pytest.approx(12_500_000)
    assert found["annual_opex_eur"] == pytest.approx(2_100_000)
    assert found["production_cost_eur_per_kg"] == pytest.approx(6.5)
