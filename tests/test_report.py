"""Qt-free tests for the process-report PDF builder (desktop.report)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from desktop import report  # noqa: E402
from desktop.flowsheet import builder  # noqa: E402
from algametrix.library import load_library  # noqa: E402
from algametrix.scenario import run_scenario  # noqa: E402
from algametrix.templates import TEMPLATES  # noqa: E402


@pytest.fixture(scope="module")
def lib():
    return load_library()


def test_build_process_report_writes_a_pdf(lib, tmp_path):
    """A report (summary + stream table, no image) builds head-less."""
    scn = TEMPLATES[0].build(lib)
    results = run_scenario(scn)
    fs = builder.flowsheet_from_scenario(scn, results)

    out = tmp_path / "report.pdf"
    report.build_process_report(out, results, scn, flowsheet=fs, pfd_png=None,
                                title="Test report")
    assert out.exists()
    assert out.stat().st_size > 1500  # a real multi-page PDF, not an empty stub


def test_report_includes_available_analyses(lib, tmp_path):
    """Products + sensitivity/uncertainty/compare extras add pages to the report."""
    from algametrix.comparison import KPI_ORDER, scenario_kpis
    from algametrix.sensitivity import OUTPUTS, PARAMETERS, run_sweep
    from algametrix.uncertainty import run_montecarlo

    scn = next(t for t in TEMPLATES if "oil" in t.name.lower()).build(lib)  # multi-product
    results = run_scenario(scn)
    assert len(results.products) > 1

    out_name, getter = next(iter(OUTPUTS.items()))
    param = PARAMETERS[0]
    pts = run_sweep(scn, param, param.default_range(scn))
    sens = {"param": param.name, "unit": param.unit, "output": out_name,
            "xs": [p.value for p in pts], "ys": [getter(p.results) for p in pts]}
    mc = run_montecarlo(scn, [(param, 0.2)], outputs={out_name: getter}, n=120)
    unc = {"output": out_name, "n": mc.n, "vals": list(mc.series[out_name]),
           "stats": dict(mc.stats(out_name))}
    extras = {"sensitivity": sens, "uncertainty": unc,
              "compare": {"order": KPI_ORDER, "snapshots": [("A", scenario_kpis(results))]}}

    base = tmp_path / "base.pdf"
    full = tmp_path / "full.pdf"
    report.build_process_report(base, results, scn)
    report.build_process_report(full, results, scn, extras=extras)
    assert full.stat().st_size > base.stat().st_size  # extra pages were added


def test_stream_rows_cover_every_link(lib):
    scn = TEMPLATES[2].build(lib)          # omega-3: feeds + extraction
    fs = builder.flowsheet_from_scenario(scn, run_scenario(scn))
    rows = report._stream_rows(fs)
    assert len(rows) == len(fs.links)
    assert all(" → " in route for _s, route, _rate, _comp in rows)
