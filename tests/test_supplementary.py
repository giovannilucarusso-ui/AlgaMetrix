"""The Supplementary Information bundle.

The SI is assembled, not written, so what these tests protect is the assembly:
that the machine-readable exports cover what they claim to cover, that the
hashes printed next to an embedded report actually match that report, and that
a generated table is never silently mangled to fit a page. The prose of the
document is not tested - it is prose - but every claim it makes about its own
contents is computed at build time and checked here.
"""

from __future__ import annotations

import csv
import hashlib
import types
from pathlib import Path

import pytest

from algametrix.library import load_library
from algametrix.paper import archetypes, parameters, studies, supplementary

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

#: The reports the SI embeds. They are tracked in the repository, so a fresh
#: checkout has them; a run that has not regenerated them still builds a valid
#: bundle, it just describes the committed state.
REQUIRED = [
    "verification.txt", "shared_inventory_consistency.txt", "validation.txt",
    "carbon_accounting.txt", "sobol_validation.txt", "sobol_convergence.txt",
    "sensitivity.txt", "uncertainty.txt", "lca_implementation_benchmark.txt",
    "brightway_crosscheck.txt",
]


def _bundle(tmp_path: Path):
    run = types.SimpleNamespace(
        lib=load_library(),
        dataset=studies.default_dataset(),
        stages_run=["verification", "consistency"],
    )
    return supplementary.build(run, tmp_path, RESULTS, ROOT, seed=20260801)


# --------------------------------------------------------------------------
# Telling a table apart from prose
# --------------------------------------------------------------------------

def test_table_rows_and_prose_are_told_apart():
    """The distinction the page layout rests on.

    A prose line that overflows soft-wraps and loses nothing. A table row that
    overflows loses the alignment that carries its meaning. Only the second may
    force the page wider, so a padded label must not be mistaken for a column.
    """
    prose = "  note    : source gross 15.050, the comparison is made on the GROSS figure"
    row = "  Productivity [open_raceway_pond] foreground   triangular   10   20   30"

    assert supplementary._widest_table_row(prose) == 0
    assert supplementary._widest_table_row(row) == len(row)
    # A long prose line must not raise the measured table width at all.
    assert supplementary._widest_table_row(prose + "\n" + row) == len(row)


def test_every_embedded_report_fits_the_page_it_is_printed_on():
    """The guard in :func:`build`, asserted on the real reports.

    If a report grows a wider table this fails here rather than shipping an SI
    whose tables wrap mid-column.
    """
    missing = [n for n in REQUIRED if not (RESULTS / n).exists()]
    if missing:
        pytest.skip(f"results not generated: {', '.join(missing)}")
    for name in REQUIRED:
        text = (RESULTS / name).read_text(encoding="utf-8")
        assert supplementary._widest_table_row(text) <= supplementary.PRINT_WIDTH, name


def test_split_at_refuses_a_missing_marker():
    """A silently empty S2 would be worse than a crash."""
    with pytest.raises(ValueError):
        supplementary._split_at("nothing to see here", "CONTROLLED COUNTER-EXAMPLE")


# --------------------------------------------------------------------------
# The machine-readable exports
# --------------------------------------------------------------------------

def test_module_map_reads_its_summaries_out_of_the_source():
    rows = supplementary.module_map(ROOT)
    by_module = {r["module"]: r for r in rows}

    assert "reproduce.py" in by_module
    assert "src/algametrix/paper/supplementary.py" in by_module
    assert "src/algametrix/consistency.py" in by_module
    # The summary is the module's own first docstring line, not a maintained
    # copy of it, so it must match the source rather than merely be non-empty.
    src = (ROOT / "src" / "algametrix" / "paper" / "sobol.py").read_text(encoding="utf-8")
    first = src.split('"""', 2)[1].strip().split("\n", 1)[0]
    assert by_module["src/algametrix/paper/sobol.py"]["summary"] == first
    assert all(r["summary"] != "(no module docstring)" for r in rows), \
        [r["module"] for r in rows if r["summary"] == "(no module docstring)"]


def test_parameter_provenance_covers_every_parameter_in_every_archetype():
    lib = load_library()
    rows = supplementary.parameter_provenance_rows(lib, archetypes, parameters)

    assert len(rows) == len(archetypes.ARCHETYPES) * len(parameters.ALL_PARAMETERS)
    for r in rows:
        assert r["lower"] <= r["mode"] <= r["upper"], r["parameter"]
        assert r["evidence_quality"] in parameters.EVIDENCE_QUALITIES, r["parameter"]
        assert r["group"] in parameters.GROUPS, r["parameter"]
    # At least one row must be sampled somewhere, and at least one must not:
    # the column exists precisely because the two differ per archetype.
    flags = {r["sampled_in_this_archetype"] for r in rows}
    assert flags == {True, False}


def test_study_export_carries_the_exclusion_reasons():
    """An exclusion that is not in the machine-readable export is not countable."""
    rows = supplementary.study_rows(studies.default_dataset())
    assert rows, "no study records exported"
    ids = {r["study_id"] for r in rows}
    assert len(ids) == len(rows), "study_id is not unique in the export"
    excluded = [r for r in rows if str(r.get("exclusion_reason", "")).strip()]
    assert excluded, "no exclusion reason survived the export"


# --------------------------------------------------------------------------
# The bundle
# --------------------------------------------------------------------------

def test_build_writes_the_bundle_and_every_hash_matches(tmp_path):
    missing = [n for n in REQUIRED if not (RESULTS / n).exists()]
    if missing:
        pytest.skip(f"results not generated: {', '.join(missing)}")

    made = _bundle(tmp_path)
    names = {p.name for p in made}
    assert {"SI.md", "studies.csv", "studies.json", "parameter_provenance.csv",
            "module_map.csv", "manifest.csv"} <= names

    si = (tmp_path / "SI.md").read_text(encoding="utf-8")
    for section in ("## S1 ", "## S2 ", "## S3 ", "## S4 ", "## S5 ", "## S6 ", "## S7 "):
        assert section in si, section

    with (tmp_path / "data" / "manifest.csv").open(encoding="utf-8") as fh:
        manifest = list(csv.DictReader(fh))
    assert manifest

    for row in manifest:
        base = ROOT if row["role"] == "embedded in SI" else tmp_path
        path = base / row["file"]
        assert path.exists(), row["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == row["sha256"], row["file"]
        # The hash in the document is the one a reader will recompute, so the
        # abbreviation printed above each block has to be a prefix of it.
        if row["role"] == "embedded in SI":
            assert digest[:16] in si, row["file"]


def test_embedded_markdown_does_not_break_out_of_its_fence(tmp_path):
    """Two embedded files are Markdown and contain ``` blocks of their own.

    A three-backtick fence around them ends at the first inner fence and the
    rest of the file leaks into the document as prose - which renders, so
    nothing crashes and the damage is silent. Hence a test rather than a guard.
    """
    missing = [n for n in REQUIRED if not (RESULTS / n).exists()]
    if missing:
        pytest.skip(f"results not generated: {', '.join(missing)}")

    _bundle(tmp_path)
    lines = (tmp_path / "SI.md").read_text(encoding="utf-8").splitlines()

    # Walk the document the way a Markdown parser does, and record which lines
    # end up inside a fenced block. Fence balance alone proves nothing here: an
    # inner ``` closes the outer fence and a later one re-opens it, so the count
    # can come out even while half the file has leaked into the prose.
    inside: list[bool] = []
    fence = None
    for line in lines:
        s = line.rstrip()
        if fence is None:
            opening = s.startswith("```")
            inside.append(opening)
            if opening:
                fence = s[:len(s) - len(s.lstrip("`"))]
        else:
            inside.append(True)
            if s == fence:
                fence = None
    assert fence is None, "a fenced block in SI.md is never closed"

    # Every line of the embedded methodology notes must be inside a block. The
    # last one is the strictest single check: it is past every inner fence.
    for doc in ("VALIDATION.md", "CARBON_ACCOUNTING.md"):
        body = (ROOT / "docs" / doc).read_text(encoding="utf-8")
        tail = [ln for ln in body.splitlines() if ln.strip()][-1]
        hits = [i for i, ln in enumerate(lines) if ln.rstrip() == tail.rstrip()]
        assert hits, f"{doc} was not embedded at all"
        assert any(inside[i] for i in hits), \
            f"{doc} leaked out of its fence: its last line is loose in the document"


def test_the_counterexamples_are_reproduced_whole_and_only_in_s2(tmp_path):
    """S1.2 must not carry the counter-example, and S2 must carry all of it."""
    if not (RESULTS / "shared_inventory_consistency.txt").exists():
        pytest.skip("consistency report not generated")

    text = (RESULTS / "shared_inventory_consistency.txt").read_text(encoding="utf-8")
    recovery, counterexample = supplementary._split_at(
        text, supplementary.COUNTEREXAMPLE_MARKER)

    assert supplementary.COUNTEREXAMPLE_MARKER not in recovery
    assert counterexample.startswith(supplementary.COUNTEREXAMPLE_MARKER)
    # Both demonstrations, not just the first one.
    assert counterexample.count("harvesting recovery 0.9 -> 0.765") == 2
    # Nothing dropped between the two halves.
    assert len(recovery.splitlines()) + len(counterexample.splitlines()) \
        >= len(text.splitlines()) - 2
