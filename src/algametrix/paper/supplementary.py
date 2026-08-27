"""Assemble the Supplementary Information from what the pipeline already emits.

The SI is not written; it is *built*. Every table in it is a file that
``reproduce.py`` wrote in the same run, embedded verbatim and stamped with its
SHA-256, so a reader can recompute the hash of the shipped file and check that
the document was not edited after the fact. Nothing here re-derives a number: a
section that could not be filled from a generated artifact is a section this
module refuses to write.

What this module adds on top of the artifacts is threefold:

* the connective prose - what each section is, what it is *not* evidence of, and
  the exact command that regenerates it;
* three machine-readable exports that had no report of their own: the study
  dataset, the sampled parameter supports with their provenance, and a map of
  the software modules behind each claim;
* a manifest with a hash for every shipped and every embedded file.

Layout written under ``outdir``::

    SI.md                       the document (Markdown; Pandoc turns it into DOCX)
    data/studies.csv|.json      the study dataset, flat and machine-readable
    data/parameter_provenance.csv   sampled supports, per archetype, with sources
    data/module_map.csv         module -> what it does -> what it produces
    data/manifest.csv           SHA-256, size and line count of every file involved
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import platform
import re
import subprocess
from dataclasses import asdict
from datetime import date
from pathlib import Path

#: Every embedded report is an ASCII table whose meaning is in its column
#: alignment, so **nothing here is re-flowed**: a re-wrapped table row is a
#: broken table, and the widest rows in the pipeline (the parameter-support
#: metadata, at ~160 characters) are exactly the ones a naive wrapper destroys.
#: The page is made wide enough to hold them instead - see :func:`to_docx`.
#: This constant is only the width the document *claims* to print at, and
#: :func:`build` checks the claim against the files it actually embedded.
PRINT_WIDTH = 200

#: Marker that separates the flow-by-flow recovery (S2) from the controlled
#: counter-examples (S3) inside one generated report.
COUNTEREXAMPLE_MARKER = "CONTROLLED COUNTER-EXAMPLE"


# ======================================================================
# Small helpers
# ======================================================================

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:                                   # pragma: no cover
        pass
    return "unknown (not a git checkout, or git unavailable)"


def _versions(results_dir: Path | None = None) -> dict[str, str]:
    """Versions of everything a number in this SI could depend on.

    Brightway is a special case and has to be, or the table contradicts the
    document: the cross-check in S7 deliberately runs in its own environment,
    because bw2calc pulls in around thirty packages the engine does not need.
    When it is absent here, the version that produced the embedded result is
    read out of that result rather than reported as missing.
    """
    out = {"python": platform.python_version(), "platform": platform.platform()}
    for mod in ("numpy", "scipy", "matplotlib", "yaml", "SALib", "bw2calc"):
        try:
            m = __import__(mod)
            version = getattr(m, "__version__", None)
            if version is None:
                from importlib.metadata import version as _v
                version = _v(mod)
            out[mod] = str(version)
        except Exception:
            out[mod] = "not installed"

    if out["bw2calc"] == "not installed" and results_dir is not None:
        payload = results_dir / "brightway_crosscheck.json"
        if payload.exists():
            got = json.loads(payload.read_text(encoding="utf-8")).get("bw2calc_version")
            if got:
                out["bw2calc"] = f"{got} (separate environment; see S7.2)"
    return out


def _longest_line(text: str) -> int:
    return max((len(line) for line in text.splitlines()), default=0)


#: Two or more internal runs of 2+ spaces, i.e. at least three aligned columns.
#: A prose line with a padded label (``note    : ...``) has one such run and is
#: therefore not mistaken for a table row.
_TABLE_ROW = re.compile(r"\S {2,}\S.*?\S {2,}\S")


def _widest_table_row(text: str) -> int:
    """Width of the widest *aligned* row, ignoring prose.

    The distinction matters because the two fail differently when the page is
    too narrow: a prose line soft-wraps in the reader's word processor and loses
    nothing, while a table row soft-wraps and loses the alignment that carries
    its meaning. Only the second is a reason to widen the page.
    """
    return max((len(line) for line in text.splitlines()
                if _TABLE_ROW.search(line.strip())), default=0)


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist. The supplementary stage embeds what the "
            "other stages wrote; run `python reproduce.py` first."
        )
    return path.read_text(encoding="utf-8")


def _split_at(text: str, marker: str) -> tuple[str, str]:
    """Split a generated report at a section heading, keeping the heading."""
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"marker {marker!r} not found; the report format changed")
    # Back up over the rule line that precedes the heading, if there is one.
    head = text[:idx].rstrip("\n")
    if head.rsplit("\n", 1)[-1].strip("=") == "":
        head = head.rsplit("\n", 1)[0]
    return head.rstrip("\n"), text[idx:].rstrip("\n")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> Path:
    """Write rows to CSV, keeping the field order the rows were built in.

    Sorting the columns alphabetically would put ``absolute_bounds`` first and
    ``parameter`` in the middle. The order the rows carry is the order of the
    dataclass they came from - identity, then eligibility, then the economic
    number, then the environmental one - which is how a reader wants to read it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames) if fieldnames else list(
        dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=names, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in names})
    return path


# ======================================================================
# The three machine-readable exports
# ======================================================================

def module_map(root: Path) -> list[dict]:
    """Every module behind a claim, with its own first docstring line.

    The summary is read out of the source rather than maintained here, so it
    cannot drift from the code: a module whose purpose changes and whose
    docstring is updated updates this table on the next run, and one whose
    docstring is *not* updated is visibly stale in both places at once.
    """
    groups = [
        ("engine", sorted((root / "src" / "algametrix").glob("*.py"))),
        ("evidence pipeline", sorted((root / "src" / "algametrix" / "paper").glob("*.py"))),
        ("driver", [root / "reproduce.py"]),
        ("tooling", sorted(p for p in (root / "scripts").glob("*.py")
                           if p.name != "make_handoff.py")),
        ("tests behind the claims", sorted((root / "tests").glob("test_paper_*.py"))
                                    + [root / "tests" / "test_consistency.py",
                                       root / "tests" / "test_matrix_lca.py",
                                       root / "tests" / "test_verification.py"]),
    ]
    rows: list[dict] = []
    for role, paths in groups:
        for p in paths:
            if not p.exists() or p.name == "__init__.py":
                continue
            try:
                doc = ast.get_docstring(ast.parse(p.read_text(encoding="utf-8")))
            except SyntaxError:                          # pragma: no cover
                doc = None
            summary = (doc or "").strip().split("\n", 1)[0] or "(no module docstring)"
            rows.append({
                "role": role,
                "module": p.relative_to(root).as_posix(),
                "summary": summary,
                "lines": len(p.read_text(encoding="utf-8").splitlines()),
            })
    return rows


def parameter_provenance_rows(lib, archetypes_mod, parameters_mod) -> list[dict]:
    """The sampled support of every uncertain input, per archetype, with its source.

    ``uncertainty.txt`` prints the same information for a human. This is the
    machine-readable form, and it carries the field that matters most for
    reading the results honestly: ``evidence_quality``, which separates a range
    that is documented in the repository from one that is a bare scenario
    assumption with nothing behind it.
    """
    rows: list[dict] = []
    for arch in archetypes_mod.ARCHETYPES:
        scn = arch.build(lib)
        active = parameters_mod.active(parameters_mod.ALL_PARAMETERS, scn)
        active_names = {p.name for p in active}
        for p in parameters_mod.ALL_PARAMETERS:
            lo, mode, hi = p.bounds(scn)
            rows.append({
                "archetype": arch.key,
                "archetype_label": arch.label,
                "parameter": p.name,
                "group": p.group,
                "unit": p.unit,
                "distribution": p.distribution,
                "lower": lo,
                "mode": mode,
                "upper": hi,
                "relative_band": p.relative_band,
                "absolute_bounds": ("" if p.absolute_bounds is None
                                    else f"{p.absolute_bounds[0]}..{p.absolute_bounds[1]}"),
                "physical_min": p.physical_min,
                "physical_max": p.physical_max,
                "evidence_quality": p.evidence_quality,
                "source": p.source,
                "correlation_group": p.correlation_group or "none (assumed independent)",
                "sampled_in_this_archetype": p.name in active_names,
                "notes": p.notes,
            })
    return rows


def study_rows(dataset) -> list[dict]:
    """The study dataset, flattened one record per row."""
    rows = []
    for rec in dataset:
        d = asdict(rec)
        rows.append({k: ("" if v is None else
                         json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict))
                         else v)
                     for k, v in d.items()})
    return rows


# ======================================================================
# The document
# ======================================================================

def _embed(title: str, path: Path, root: Path, manifest: list[dict],
           text: str | None = None, note: str = "") -> list[str]:
    """One embedded artifact: provenance line, then the file verbatim."""
    body = _read(path) if text is None else text
    digest = _sha256(path)
    manifest.append({
        "file": path.relative_to(root).as_posix(),
        "role": "embedded in SI",
        "part": "whole file" if text is None else "extract",
        "sha256": digest,
        "bytes": path.stat().st_size,
        "lines": len(body.splitlines()),
        "longest_line": _longest_line(body),
        "widest_table_row": _widest_table_row(body),
    })
    # Two of the embedded files are themselves Markdown and contain fenced code
    # blocks, so the fence around them has to be longer than anything inside or
    # the block ends early and the rest of the file leaks into the document as
    # prose. Longest run of backticks in the body, plus one, never fewer than 3.
    ticks = "`" * max(3, max((len(m) for m in re.findall(r"`+", body)), default=0) + 1)

    out = [f"**{title}**", ""]
    if note:
        out += [note, ""]
    out += [
        f"*Source file:* `{path.relative_to(root).as_posix()}` · "
        f"{len(body.splitlines())} lines · SHA-256 `{digest[:16]}…`",
        "",
        f"{ticks}text",
        body,
        ticks,
        "",
    ]
    return out


def _markdown_table(rows: list[dict], columns: list[tuple[str, str]]) -> list[str]:
    """A real Markdown table (not a fenced dump), for the short generated tables."""
    head = [c[1] for c in columns]
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        cells = []
        for key, _label in columns:
            v = r.get(key, "")
            v = "" if v is None else str(v)
            cells.append(v.replace("|", "\\|"))
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return out


def build(run, outdir: Path, results_dir: Path, root: Path,
          seed: int, docs_dir: Path | None = None,
          stale_stages: list[str] | None = None) -> list[Path]:
    """Write the SI document and its machine-readable companions.

    ``stale_stages`` names stages whose output is embedded but was produced by
    an earlier invocation. It is printed on the front page rather than only to
    the console: an SI assembled from a partial run has to say so where a reader
    will see it.
    """
    from ..lciamethod import factor_rows
    from . import archetypes, parameters, specification, suite

    spec_cases, _ = suite.distinct_cases(run.lib)
    docs = docs_dir or (root / "docs")
    data_dir = outdir / "data"
    outdir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    # ---------------------------------------------------------------- data
    studies = study_rows(run.dataset)
    params = parameter_provenance_rows(run.lib, archetypes, parameters)
    modules = module_map(root)

    lcia_factors = factor_rows(run.lib.lcia_method) if run.lib.lcia_method else []

    written = [
        _write_csv(data_dir / "studies.csv", studies),
        _write_csv(data_dir / "parameter_provenance.csv", params),
        _write_csv(data_dir / "module_map.csv", modules,
                   fieldnames=["role", "module", "summary", "lines"]),
    ]
    if lcia_factors:
        written.append(_write_csv(
            data_dir / "lcia_factors.csv", lcia_factors,
            fieldnames=["factor", "input", "indicator", "value", "unit", "geography",
                        "reference_period", "quality", "source"]))
    (data_dir / "studies.json").write_text(
        json.dumps(studies, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(data_dir / "studies.json")

    # The reduced equation set for the manuscript. Written beside the SI rather
    # than inside it: it is authoring material, not part of the deliverable.
    main_text = outdir / "main_text_equations.md"
    main_text.write_text(
        "\n".join(specification.render_main_text_block(run.lib, spec_cases)) + "\n",
        encoding="utf-8")
    written.append(main_text)

    # ---------------------------------------------------------------- doc
    commit = _git_commit(root)
    versions = _versions(results_dir)
    consistency_text = _read(results_dir / "shared_inventory_consistency.txt")
    recovery_text, counterexample_text = _split_at(consistency_text, COUNTEREXAMPLE_MARKER)

    L: list[str] = []
    L += [
        "# Supplementary Information",
        "",
        "**AlgaMetrix: a single-inventory framework for consistent techno-economic "
        "and life-cycle assessment of microalgal and protist biomass**",
        "",
        "---",
        "",
        "## S0 What this document is, and how to regenerate it",
        "",
        "Every table below is a file produced by `reproduce.py`, embedded verbatim and "
        "stamped with its SHA-256. Nothing was transcribed, reformatted or rounded by "
        "hand: the only text written for this document is the prose that introduces "
        "each section. Recomputing the hash of any shipped file and comparing it with "
        "the value printed above the corresponding block is sufficient to show that the "
        "document reports what the software produced.",
        "",
        "The whole of it, including this file, is regenerated by",
        "",
        "```bash",
        "python reproduce.py",
        "```",
        "",
        "from a single documented master seed. Two runs of that command on the same "
        "commit reproduce every reported quantity exactly, down to the last printed "
        "digit, so any number in the manuscript can be traced to a line in a file "
        "listed here. The claim is deliberately not stated as byte-identity: the "
        "Sobol' validation and convergence reports print wall-clock timings, which "
        "differ between runs and are diagnostics rather than results. Every other file "
        "listed in S8.5 is byte-identical across runs.",
        "",
        "### Provenance of this build",
        "",
    ]
    L += _markdown_table(
        [{"k": "generated", "v": date.today().isoformat()},
         {"k": "git commit", "v": f"`{commit}`"},
         {"k": "master seed", "v": str(seed)},
         {"k": "stages run before this one, in the same invocation",
          "v": ", ".join(run.stages_run) or "none"}]
        + [{"k": k, "v": v} for k, v in versions.items()],
        [("k", "item"), ("v", "value")])
    if stale_stages:
        L += [
            f"> **This bundle was assembled from a partial run.** The stages "
            f"*{', '.join(stale_stages)}* did not execute in the invocation that "
            "built this document; their output is embedded as it stood in the "
            "repository, and the SHA-256 above each block identifies exactly "
            "which version that is. `python reproduce.py` with no `--only` "
            "rebuilds every stage and this document together.",
            "",
        ]
    L += [
        "### A distinction this document keeps throughout",
        "",
        "**Verification** asks whether the software is self-consistent and whether "
        "independent implementations of it agree. **Validation** asks whether it "
        "reproduces something published. Sections S2, S3, S5 and S7 are verification; "
        "only S4 is validation, and it is much weaker evidence. The two are never "
        "pooled, and no verification result in this document is offered as evidence "
        "that the model is right.",
        "",
        "### Contents",
        "",
        "| Section | Content |",
        "|---|---|",
        "| S1 | Model specification: symbols, governing equations, assumptions |",
        "| S2 | Verification suite and flow-by-flow TEA/LCA recovery, 27 scenarios |",
        "| S3 | Controlled duplicated-foreground counter-examples, both archetypes |",
        "| S4 | External validation: protocol, price basis, carbon accounting, "
        "exclusions, failed range check |",
        "| S5 | Global sensitivity: estimator and group-estimator validation, "
        "convergence, full Sobol' tables |",
        "| S6 | Monte-Carlo uncertainty: input distributions and full P10/P50/P90 |",
        "| S7 | LCA implementation cross-checks: sequential vs matrix vs Brightway |",
        "| S8 | Machine-readable dataset, parameter provenance, software map, manifest |",
        "",
        "---",
        "",
    ]

    # ---- S1 ----------------------------------------------------------
    # The specification comes before the evidence: a reader cannot judge whether
    # a residual matters without knowing what equation produced it.
    L += ["## S1 Model specification", ""]
    L += specification.render_markdown(run.lib, spec_cases)
    L += [
        "### Life-cycle method declaration",
        "",
        "The equations above say how an impact is computed from the inventory. They do "
        "not say what the factors in them mean, where they came from, what the boundary "
        "around them is or what it leaves out - and an impact result is not "
        "interpretable without that. The declaration below is the scope statement ISO "
        "14044 clause 4.2.3 asks a study to make. It is generated from "
        "`data/lcia.yaml`, the same file the engine loads its factors from, so the "
        "statement and the numbers cannot drift apart.",
        "",
        "Three things in it are worth reading before any environmental result in this "
        "manuscript. **Section 2** lists what the boundary excludes - infrastructure, "
        "transport, packaging, spent-medium treatment and every direct emission other "
        "than N and P to water. **Section 6** is the coverage matrix: GWP and cumulative "
        "energy demand are the only categories most inputs reach, and water, land, "
        "acidification and the two eutrophication categories are correspondingly "
        "narrower. **Section 7** records that 22 of the 23 shipped factors are "
        "order-of-magnitude values with no traceable dataset behind them, which is why "
        "the external validation in S4 compares GWP and production cost and nothing "
        "else.",
        "",
    ]
    L += _embed("Method statement: scope, coverage matrix and factor provenance",
                results_dir / "lcia_method_statement.txt", root, manifest)
    L += ["---", ""]

    # ---- S2 ----------------------------------------------------------
    L += [
        "## S2 Verification suite and flow-by-flow recovery",
        "",
        "```bash",
        "python reproduce.py --only verification --only consistency",
        "```",
        "",
        "Both checks run over one scenario set (`algametrix.paper.suite`), so the "
        "results describe the same population: 35 members, **27 structurally "
        "distinct**, because several members build an identical `Scenario` by "
        "different routes and are counted once rather than inflating the evidence "
        "base. The coverage table at the head of S2.2 states what those 27 span.",
        "",
        "S2.1 reports two families of check that are not equally strong evidence. The "
        "**construction identities** restate each inventory field as a closed form of "
        "the scenario, written independently of `inventory.py`, and compare the two. "
        "They hold *by construction*: `build_inventory` derives the nitrogen supply as "
        "`org.nitrogen × gpp / uptake`, so `supply × uptake = org.nitrogen × gpp` "
        "cannot fail for any parameter values. Their machine-precision residuals are "
        "therefore evidence that the implementation matches its specification, and "
        "specifically **not** evidence that a conservation law holds. The **physical "
        "admissibility constraints** are the ones a scenario can genuinely violate: "
        "elemental composition within the dry mass it is a fraction of, recovery and "
        "uptake and utilization inside (0, 1], and — for a heterotroph — biomass carbon "
        "not exceeding the carbon its substrate supplied. That last constraint is the "
        "elemental carbon test, and it is separate from the identities precisely "
        "because none of them mentions carbon at all. The carbon not incorporated is "
        "respired; it is reported per scenario and is not summed into the GWP, under "
        "the same biogenic 0/0 convention the substrate carbon already receives.",
        "",
        "S2.2 asks a different question again: `run_scenario` builds one `Inventory` "
        "and hands the *same "
        "object* to `run_tea` and `run_lca`, so agreement between them is an "
        "architectural invariant rather than an empirical finding — but sharing an "
        "object does not by itself guarantee that both analyses read the same *field* "
        "of it, on the same basis. Each flow is therefore recovered independently from "
        "the two reported results, as the derivative of production cost with respect "
        "to that flow's unit price (net of overhead) and as the derivative of gross "
        "GWP with respect to its characterization factor. Both are in physical units "
        "per kilogram of dry biomass, and both are read off the *results*, not off the "
        "inventory, so a re-basing between the two would also appear.",
        "",
    ]
    L += _embed("S2.1 Construction identities and physical admissibility, per scenario",
                results_dir / "verification.txt", root, manifest)
    L += _embed("S2.2 Flow-by-flow TEA/LCA recovery, per scenario",
                results_dir / "shared_inventory_consistency.txt", root, manifest,
                text=recovery_text,
                note="*The controlled counter-examples that close this report are "
                     "reproduced separately in S2.*")

    # ---- S3 ----------------------------------------------------------
    L += [
        "---",
        "",
        "## S3 Controlled duplicated-foreground counter-examples",
        "",
        "A verification that always passes proves nothing unless the check can fail. "
        "The two cases below are that demonstration, run **on this engine against "
        "itself**: they are not a claim about any other software, and no other tool is "
        "inspected or implicated. A duplicated-inventory implementation is emulated by "
        "giving the TEA and the LCA their own copies of the scenario; one physical "
        "assumption — the harvesting recovery — is then updated in the TEA copy only, "
        "exactly as a maintainer would if the two inventories lived in two files and "
        "only one were edited. The single-inventory path is run on the same edit for "
        "contrast.",
        "",
        "What the two cases show is why the failure is hard to catch from the outside: "
        "the reported production cost is unchanged, the entire error lands in the "
        "environmental result, and the two numbers are still published side by side as "
        "a matched economic–environmental pair. No internal check on the LCA alone "
        "would find it — the stale inventory is perfectly self-consistent; it is simply "
        "a different plant.",
        "",
    ]
    L += _embed("S3 Duplicated-inventory drift, phototrophic and heterotrophic",
                results_dir / "shared_inventory_consistency.txt", root, manifest,
                text=counterexample_text,
                note="*Extracted from the same generated report as S2.2; the hash below "
                     "is that of the whole file.*")

    # ---- S4 ----------------------------------------------------------
    L += [
        "---",
        "",
        "## S4 External validation",
        "",
        "```bash",
        "python reproduce.py --only reproductions --only carbon",
        "```",
        "",
        "This is the only section of this document that is validation. Reproductions "
        "are kept apart by how the scenario was built, because they are not equally "
        "strong evidence: a **blind** case traces every input to a value published by "
        "the source or to an itemised library default and never uses the reported "
        "endpoint as an input; a **calibrated** case deliberately imposes the "
        "reference's design assumptions. No blind case was tuned, and the two classes "
        "are never pooled. A **range** check is a plausibility check against a "
        "published envelope and is never converted into a percentage deviation from an "
        "envelope midpoint. An **excluded** record is one whose published figures could "
        "not be traced to the cited source; it stays in the dataset with its reason so "
        "the exclusion is countable, and it enters no population.",
        "",
        "Two bases have to be fixed before any deviation means anything, and each has "
        "its own note below: the **price basis**, because a cost is only comparable "
        "within a stated currency and price year, and the **biogenic-carbon "
        "convention**, because a GWP compared across an unstated convention is not a "
        "comparison at all. Every GWP row is placed on a basis that does not depend on "
        "an unstated convention.",
        "",
    ]
    for title, path in (
        ("S4.1 Validation protocol and classification", docs / "VALIDATION.md"),
        ("S4.2 Price-basis notes", docs / "PRICE_BASIS.md"),
        ("S4.3 Carbon-accounting notes", docs / "CARBON_ACCOUNTING.md"),
    ):
        L += _embed(title, path, root, manifest)
    L += _embed("S4.4 Carbon accounting under each convention, per scenario",
                results_dir / "carbon_accounting.txt", root, manifest)
    L += _embed("S4.5 Full comparison table, exclusions and the failed range check",
                results_dir / "validation.txt", root, manifest,
                note="*The range check is reported here and nowhere else in the "
                     "manuscript as a point prediction: it is a plausibility check, it "
                     "fell outside its published envelope, and it was retained rather "
                     "than removed.*")

    # ---- S5 ----------------------------------------------------------
    L += [
        "---",
        "",
        "## S5 Global sensitivity",
        "",
        "```bash",
        "python reproduce.py --only sobol",
        "```",
        "",
        "Sobol' indices are only worth reporting if the estimator that produced them "
        "has been shown to recover indices that are known in closed form, and if the "
        "sample size has been shown to be large enough that the ranking is not an "
        "artefact of it. S5.1 and S5.2 are those two demonstrations; S5.3 is the "
        "result. The pipeline refuses to draw the sensitivity figure at all if S5.1 "
        "does not pass.",
        "",
        "S5.1 covers **two different estimators**. The per-parameter estimator is "
        "checked against three analytical functions, and additionally against SALib "
        "where it is installed. The **group** estimator is checked separately, because "
        "its headline quantity — the share of variance carried by interactions "
        "*between* groups, the grey remainder of the group decomposition — has no "
        "per-parameter analogue and cannot be checked by those three functions. Its "
        "two cases are constructed so that the remainder is exactly 0 in one and "
        "exactly 1/19 in the other.",
        "",
    ]
    L += _embed("S5.1 Estimator validation: analytical benchmarks, SALib cross-check, "
                "and group-estimator validation",
                results_dir / "sobol_validation.txt", root, manifest)
    L += _embed("S5.2 Convergence diagnostics and the declared acceptance criteria",
                results_dir / "sobol_convergence.txt", root, manifest)
    L += _embed("S5.3 Full first- and total-order tables with bootstrap 95% CIs",
                results_dir / "sensitivity.txt", root, manifest,
                note="*Two parameter modes are reported. Mode A restricts every output "
                     "to the same shared physical parameter set, so the TEA and LCA "
                     "rankings are directly comparable; Mode B adds output-specific "
                     "economic and LCIA parameters, and its rankings are conditional on "
                     "that assignment and are not evidence that one physical driver "
                     "matters more than another.*")

    # ---- S6 ----------------------------------------------------------
    L += [
        "---",
        "",
        "## S6 Monte-Carlo uncertainty",
        "",
        "```bash",
        "python reproduce.py --only uncertainty",
        "```",
        "",
        "One definition serves both the sensitivity analysis and the uncertainty "
        "propagation (`algametrix.paper.parameters`), so the two can never disagree "
        "about what a parameter means or how wide its range is. What they do not share "
        "is the density: Sobol' indices are taken over **uniform** supports, the "
        "Monte-Carlo bands use **triangular** densities with the mode at nominal on the "
        "same supports. The two therefore share supports, not distributions, and their "
        "numbers are not interchangeable.",
        "",
        "No range in S6.1 is presented as an empirical distribution, because none of "
        "them is. The `evidence_quality` column is the one to read first: "
        "`derived_from_repository` marks a range already declared in the tool and cited "
        "as such, `scenario_assumption` marks a first-order band with no evidence "
        "behind it — a *choice*, and results that depend on it are conditional on it. "
        "Parameters are sampled independently; grouped dependence is implemented but "
        "switched off, because no correlation data exist for these systems. That too is "
        "an assumption, not a finding.",
        "",
        f"The machine-readable form of S6.1 is `data/parameter_provenance.csv` "
        f"({len(params)} rows: every parameter against every archetype, with the "
        "support actually sampled after physical clipping).",
        "",
    ]
    L += _embed("S6.1–S6.2 Input distributions with provenance, and complete "
                "P10/P50/P90 outputs by source of uncertainty",
                results_dir / "uncertainty.txt", root, manifest,
                note="*The report carries both the quantile bands and the group Sobol' "
                     "decomposition for each archetype and metric, followed by the "
                     "parameter distribution metadata. The conditional-variance ratios "
                     "printed alongside are screening statistics, not a variance "
                     "decomposition, and are labelled as such in the report itself.*")

    # ---- S7 ----------------------------------------------------------
    L += [
        "---",
        "",
        "## S7 LCA implementation cross-checks",
        "",
        "```bash",
        "python reproduce.py --only benchmark",
        "python scripts/brightway_crosscheck.py      # requires bw2calc",
        "```",
        "",
        "The engine computes life-cycle impacts sequentially. That is an "
        "implementation choice, and an implementation choice needs an independent "
        "check. Two are reported: the same inventories solved as a Leontief system "
        "(**A**·s = **f**, impacts = **C**·**B**·s) by a matrix implementation written "
        "for this purpose, and that matrix implementation solved again by **bw2calc**, "
        "the Brightway 2 LCA solver. The condition number of **A** is reported per "
        "scenario, so a small residual cannot be mistaken for a well-conditioned "
        "problem when it is not.",
        "",
    ]
    L += _embed("S7.1 Sequential engine against an independent matrix implementation",
                results_dir / "lca_implementation_benchmark.txt", root, manifest)
    L += _embed("S7.2 Matrix implementation against bw2calc",
                results_dir / "brightway_crosscheck.txt", root, manifest,
                note="*The machine-readable result, including every per-scenario "
                     "relative difference plotted in Figure 2b, is "
                     "`results/brightway_crosscheck.json`.*")

    # ---- S8 ----------------------------------------------------------
    L += [
        "---",
        "",
        "## S8 Machine-readable data, parameter provenance and software map",
        "",
        "### S8.1 Study dataset",
        "",
        f"`data/studies.csv` and `data/studies.json` carry all {len(studies)} records "
        "of the study dataset, one row each, with every field: identity and "
        "provenance, eligibility, what was studied, the economic number and its price "
        "basis, the environmental number and its convention, and — where a record was "
        "excluded — the reason it was excluded. Records are kept in the dataset rather "
        "than deleted so that an exclusion is countable and a reader can see what was "
        "taken out and why. The authoritative source is "
        "`data/studies/studies.yaml` in the software repository; these two files are "
        "flattened exports of it.",
        "",
        "### S8.2 Sampled parameter supports and their provenance",
        "",
        f"`data/parameter_provenance.csv`, {len(params)} rows. See S6 for how to read "
        "the `evidence_quality` column.",
        "",
        "### S8.3 Software module map",
        "",
        "Every module behind a claim in this manuscript, with its own first docstring "
        "line as its summary — read out of the source at build time, so it cannot "
        "drift from the code. The desktop application is deliberately out of scope: "
        "nothing in this manuscript depends on it.",
        "",
    ]
    L += _markdown_table(modules, [("role", "Role"), ("module", "Module"),
                                   ("summary", "What it does"), ("lines", "Lines")])

    L += [
        "### S8.4 Life-cycle background factors",
        "",
        f"`data/lcia_factors.csv`, {len(lcia_factors)} rows: every characterization "
        "factor the engine uses and every foreground partitioning fraction, each with "
        "its input, impact category, value, unit, geography, reference period, quality "
        "flag and source. The authoritative file is `data/lcia.yaml` in the software "
        "repository, which additionally carries the boundary, cut-off, allocation and "
        "impact-assessment statement rendered in S1. A `quality` of `indicative` "
        "means a literature-typical value with no traceable dataset behind it.",
        "",
        "",
    ]

    # The manifest has to come last: it hashes everything written above it.
    si_path = outdir / "SI.md"
    for p in written:
        body = p.read_text(encoding="utf-8")
        manifest.append({
            "file": p.relative_to(outdir).as_posix(),
            "role": "shipped with this SI",
            "part": "whole file",
            "sha256": _sha256(p),
            "bytes": p.stat().st_size,
            "lines": len(body.splitlines()),
            "longest_line": _longest_line(body),
            "widest_table_row": _widest_table_row(body),
        })
    manifest_path = _write_csv(
        data_dir / "manifest.csv", manifest,
        fieldnames=["file", "role", "part", "sha256", "bytes", "lines",
                    "longest_line", "widest_table_row"])
    written.append(manifest_path)

    embedded = [m for m in manifest if m["role"] == "embedded in SI"]
    widest_row = max((int(m["widest_table_row"]) for m in embedded), default=0)
    long_prose = sum(1 for m in embedded if int(m["longest_line"]) > PRINT_WIDTH)
    if widest_row > PRINT_WIDTH:
        raise ValueError(
            f"an embedded table row is {widest_row} characters wide, past the "
            f"{PRINT_WIDTH} the page is set up for. Widen the page in to_docx() or "
            "narrow the report - do not re-wrap it, a re-wrapped table is a broken "
            "table."
        )
    L += [
        "### S8.5 Manifest",
        "",
        "`data/manifest.csv` lists every file embedded in this document and every file "
        "shipped alongside it, with its SHA-256, byte count, line count, longest line "
        "and widest aligned table row. Each embedded block is **byte-identical to the "
        "file it names**: nothing was re-flowed, re-wrapped, re-aligned or rounded, so "
        "the hash printed above a block can be recomputed directly against the "
        "corresponding file in the software repository.",
        "",
        "The reports are fixed-width tables whose meaning is partly in their "
        f"alignment. The widest aligned row across all of them is {widest_row} "
        f"characters, so the page is set landscape with a 6.5 pt monospace face — "
        "about 200 characters — rather than the tables being made to fit. "
        + (f"{long_prose} of the embedded reports additionally contain prose lines "
           "longer than that, in `note:` and `provenance:` annotations; those soft-wrap "
           "in the rendered document, which costs nothing, and are unbroken in the "
           "Markdown source."
           if long_prose else "No embedded line exceeds that width."),
        "",
    ]
    L += _markdown_table(manifest, [("file", "File"), ("part", "Part"),
                                    ("sha256", "SHA-256"), ("lines", "Lines"),
                                    ("widest_table_row", "Widest row")])

    si_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return [si_path, *written]


#: A4 landscape and 2 cm margins, in twips, and 6.5 pt (``w:sz`` is half-points).
_PAGE = ('<w:pgSz w:w="16838" w:h="11906" w:orient="landscape" />'
         '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
         'w:header="708" w:footer="708" w:gutter="0" />')
_CODE_STYLE = (
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="SourceCode">'
    '<w:name w:val="Source Code" /><w:basedOn w:val="Normal" />'
    '<w:pPr><w:spacing w:before="0" w:after="0" w:line="200" w:lineRule="exact" />'
    '<w:contextualSpacing /></w:pPr>'
    '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas" />'
    '<w:sz w:val="13" /><w:szCs w:val="13" /></w:rPr></w:style>')


def reference_docx(dest: Path) -> Path | None:
    """Pandoc reference document: A4 landscape, 6.5 pt monospace code blocks.

    Built by patching Pandoc's own default reference document rather than
    writing one, so every style Pandoc expects is present and only the two
    things that matter here are changed. At this page width and face a fenced
    block holds about 200 characters, which is what the widest generated table
    needs; the alternative - re-wrapping the tables - would destroy the column
    alignment that carries their meaning.
    """
    import io
    import zipfile

    try:
        got = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                             capture_output=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if got.returncode != 0 or not got.stdout:            # pragma: no cover
        return None

    src = zipfile.ZipFile(io.BytesIO(got.stdout))
    doc = src.read("word/document.xml").decode("utf-8")
    styles = src.read("word/styles.xml").decode("utf-8")
    if "<w:sectPr>" not in doc or "</w:styles>" not in styles:   # pragma: no cover
        return None                                     # Pandoc changed its template
    doc = doc.replace("<w:sectPr>", "<w:sectPr>" + _PAGE, 1)
    styles = re.sub(r'(w:styleId="VerbatimChar".*?<w:sz w:val=")\d+(")',
                    r"\g<1>13\g<2>", styles, count=1, flags=re.S)
    styles = styles.replace("</w:styles>", _CODE_STYLE + "</w:styles>", 1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = doc.encode("utf-8")
            elif item.filename == "word/styles.xml":
                data = styles.encode("utf-8")
            out.writestr(item, data)
    dest.write_bytes(buf.getvalue())
    return dest


def to_docx(si_path: Path) -> Path | None:
    """Convert the SI to DOCX with Pandoc, if Pandoc is on PATH.

    Returns the written path, or ``None`` when Pandoc is unavailable - the
    Markdown is the deliverable and the conversion is a convenience, so a
    missing Pandoc must not fail the run.
    """
    import tempfile

    out = si_path.with_suffix(".docx")
    # The reference document is scaffolding, not a deliverable: it is built in a
    # temporary directory so it never lands in the bundle a reader receives.
    with tempfile.TemporaryDirectory() as tmp:
        ref = reference_docx(Path(tmp) / "si_reference.docx")
        cmd = ["pandoc", str(si_path), "-o", str(out), "--standalone",
               "--toc", "--toc-depth=2", "--from", "gfm", "--to", "docx"]
        if ref is not None:
            cmd += ["--reference-doc", str(ref)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
    if res.returncode != 0:                              # pragma: no cover
        raise RuntimeError(f"pandoc failed: {res.stderr.strip()[:500]}")
    return out
