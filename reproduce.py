#!/usr/bin/env python
"""Regenerate every result file and figure behind the AlgaMetrix methods paper.

    python reproduce.py                 # everything
    python reproduce.py --only sobol    # one stage (repeatable: --only sobol --only gwp)
    python reproduce.py --quick         # smaller stochastic samples, for CI
    python reproduce.py --list          # show the stages

Every stochastic analysis is driven from a single documented master seed, so two
runs of this script on the same commit reproduce every reported quantity exactly,
down to the last printed digit. The only fields that differ between two runs are
the wall-clock timings in the Sobol' validation and convergence reports, which
are diagnostics and not results - the files are otherwise byte-identical.

Stage outputs
-------------
studies        results/study_selection_audit.txt
endpoints      results/economic_endpoint_audit.txt
verification   results/verification.txt
consistency    results/shared_inventory_consistency.txt
method         results/lcia_method_statement.txt
benchmark      results/lca_implementation_benchmark.txt
reproductions  results/validation.txt
harmonization  results/harmonization.txt
gwp            results/gwp_harmonization.txt
carbon         results/carbon_accounting.txt
sobol          results/sobol_validation.txt, sobol_convergence.txt, sensitivity.txt
uncertainty    results/uncertainty.txt
figures        figures/*.pdf and figures/*.png
figures_jie    figures/jie/*.pdf and figures/jie/*.png
supplementary  supplementary/SI.md (+ .docx) and supplementary/data/*
summary        results/revision_summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from algametrix import consistency as consistency_mod            # noqa: E402
from algametrix.library import load_library                      # noqa: E402
from algametrix.verification import format_report, verify        # noqa: E402
from algametrix.paper import (                                   # noqa: E402
    archetypes,
    carbon,
    endpoints,
    gwp,
    harmonization,
    indices,
    mcuncertainty,
    parameters,
    reconstructions,
    report,
    report_verification,
    reproduction,
    sobol,
    studies,
)
from algametrix.paper.evaluate import make_model, sobol_parameters  # noqa: E402
from algametrix.paper.schema import tier_disagreements           # noqa: E402
from algametrix.paper.stats import compute_spread                # noqa: E402

# =====================================================================
# Documented run configuration - the only place a seed or a sample size is set
# =====================================================================

#: Master seed for every stochastic analysis in this pipeline.
MASTER_SEED = 20260801

#: Sobol base sample sizes explored by the convergence study (powers of two, as
#: required by the Sobol' sequence).
SOBOL_CONVERGENCE_SIZES = (512, 1024, 2048, 4096, 8192)
SOBOL_QUICK_SIZES = (256, 512, 1024)

#: Declared Sobol convergence criteria.
SOBOL_MAX_CI_WIDTH = 0.15        # bootstrap 95% CI width on ST for the top drivers
SOBOL_MAX_SHIFT = 0.03           # |ST - ST(largest run)|
SOBOL_BENCHMARK_TOLERANCE = 0.02  # absolute error against analytical indices
SOBOL_BENCHMARK_N = 4096

#: Monte-Carlo sample sizes explored by the quantile convergence study.
MC_CONVERGENCE_SIZES = (250, 500, 1000, 2000, 4000, 8000)
MC_QUICK_SIZES = (250, 500, 1000)
MC_MAX_REL_SHIFT = 0.02          # |q(n) - q(n_max)| / |q(n_max)|
MC_MAX_CI_REL_WIDTH = 0.06       # 95% CI width on P90, relative to P90

#: Base sample for the GROUP-wise Sobol' variance decomposition. A power of two,
#: as the Sobol' sequence requires. With three groups this costs n*(3+2)
#: evaluations, far less than the per-parameter analysis, because the partition
#: is coarse.
GROUP_SOBOL_N = 4096

#: Outputs carried through the sensitivity and uncertainty analyses.
SENSITIVITY_OUTPUTS = ("Production cost (EUR/kg)", "NPV (EUR)", "GWP net (kg CO2-eq/kg)")
UNCERTAINTY_METRICS = ("Production cost (EUR/kg)", "GWP net (kg CO2-eq/kg)")

RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"

STAGES = ("studies", "endpoints", "verification", "consistency", "method", "benchmark",
          "reproductions", "harmonization", "gwp", "carbon", "sobol", "uncertainty",
          "figures", "figures_jie", "supplementary", "summary")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}  ({len(text.splitlines())} lines)")


class Run:
    """Carries state between stages and records what passed."""

    def __init__(self, quick: bool):
        self.quick = quick
        self.lib = load_library()
        self.dataset = studies.default_dataset()
        self.registry = indices.default_registry()
        self.status: dict[str, str] = {}
        self.todos: list[str] = []
        self.notes: list[str] = []
        self.sobol_validation_passed = False
        # Objects stashed by a stage for the figure stage to draw.
        self.artifacts: dict = {}
        # Stages that actually executed in this invocation, so a partial run can
        # never present itself as a full one.
        self.stages_run: list[str] = []

    def collect_todos(self) -> None:
        for r in self.dataset:
            for t in r.todos:
                self.todos.append(f"[{r.study_id}] {t}")
        for name, idx in sorted(self.registry.indices.items()):
            for t in idx.todos:
                self.todos.append(f"[index:{name}] {t}")
        for rate in self.registry.rates:
            for t in rate.get("todos") or []:
                self.todos.append(f"[currency:{rate['from_currency']}->"
                                  f"{rate['to_currency']}] {t}")


# =====================================================================
# Stages
# =====================================================================

def stage_studies(run: Run) -> None:
    print("[studies] study-selection and data-extraction audit")
    text = report.study_selection_audit(run.dataset, tier_disagreements(run.dataset.records))
    _write(RESULTS / "study_selection_audit.txt", text)
    n_missing = len(reconstructions.MISSING_SCENARIOS)
    run.status["task_7_study_audit"] = "pass"
    run.notes.append(
        f"{n_missing} declared Tier-B studies have no scenario builder in the repository."
    )


def stage_endpoints(run: Run) -> None:
    print("[endpoints] economic-endpoint classification")
    audits = endpoints.audit_all(run.dataset.records)
    definition = endpoints.definition_audit(run.dataset.records)
    text = report.economic_endpoint_audit(
        run.dataset, audits,
        endpoints.endpoint_breakdown(run.dataset.records),
        endpoints.PRIMARY_ENDPOINT_DEFINITION,
        definition=definition,
    )
    _write(RESULTS / "economic_endpoint_audit.txt", text)
    run.artifacts["definition_audit"] = definition
    run.status["task_2_endpoint_classification"] = "pass"
    # The cohort may only be called homogeneous if every member's endpoint
    # definition is recorded. It is not, so the status carries the qualifier
    # rather than the reports asserting uniformity they cannot support.
    run.notes.append(
        f"Primary cost cohort n={definition.n}: {endpoints.PRIMARY_COHORT_LABEL}. "
        f"{len(definition.fully_specified)}/{definition.n} have every endpoint-definition "
        "attribute recorded."
    )


def stage_verification(run: Run) -> None:
    """Internal verification, in two families that must not be conflated.

    The *construction identities* restate each inventory field as a closed form
    of the scenario and compare the two. They hold by construction and their
    residuals are round-off; what they detect is a change to ``inventory.py``
    that ``verification.py`` does not mirror. The *admissibility constraints*
    are inequalities a scenario can genuinely violate, and they are where the
    evidential weight sits.

    Verification asks whether the maths is self-consistent; validation asks
    whether it matches an external reference. They are reported separately and
    must not be conflated either.
    """
    print("[verification] construction identities and physical admissibility")
    from algametrix.paper import suite

    blocks, reports, ok = [], [], True
    # The same heterogeneous scenario set the consistency and benchmark stages
    # use, so the three verification results describe one population.
    cases, _ = suite.distinct_cases(run.lib)
    for case in cases:
        rep = verify(case.scenario(run.lib))
        ok = ok and rep.all_pass
        reports.append(rep)
        blocks.append(format_report(case.label, rep))
    checked = len(cases)
    n_identities = sum(len(r.balances) for r in reports)
    n_admissible = sum(len(r.invariants) for r in reports)

    header = report.header(
        "INTERNAL VERIFICATION",
        "construction identities of the inventory, and the physical admissibility "
        "constraints that can actually fail - self-consistency, NOT agreement with an "
        "external reference",
    )
    header += [
        f"scenarios checked        : {checked}",
        f"construction identities  : {n_identities}  (hold by construction; the residual "
        "measures round-off and code drift, not conservation)",
        f"admissibility constraints: {n_admissible}  (falsifiable: composition, fractions, "
        "heterotrophic carbon feasibility, product mass, scale invariance)",
        f"overall                  : {'PASS' if ok else 'FAIL'}",
        "",
    ]
    _write(RESULTS / "verification.txt",
           "\n".join(header) + "\n\n".join(blocks) + "\n")
    run.artifacts["verification_reports"] = reports
    run.status["verification"] = "pass" if ok else "fail"
    run.notes.append(
        f"Internal verification over {checked} scenarios: {'PASS' if ok else 'FAIL'}. "
        f"{n_identities} construction identities (which hold by construction) and "
        f"{n_admissible} physical admissibility constraints (which can fail)."
    )
    if not ok:
        raise SystemExit("verification FAILED - a conserved quantity does not close")


def stage_consistency(run: Run) -> None:
    """Shared-inventory consistency: do TEA and LCA meter the same physical flows?

    This is an architectural invariant, not an external validation: both analyses
    consume the same Inventory object by construction. What the stage adds is a
    number - each flow is recovered independently from the cost and from the
    impact, so a future edit that made one analysis read a different field, apply
    a different scaling or report on a different basis would show up here.
    """
    print("[consistency] TEA/LCA shared-inventory flow recovery")
    from algametrix.paper import suite

    cases, duplicates = suite.distinct_cases(run.lib)
    reports = [consistency_mod.check_scenario(c.scenario(run.lib), c.label) for c in cases]
    ok = all(r.all_pass for r in reports)
    worst = max((r.max_discrepancy for r in reports), default=0.0)
    worst_inv = max((r.max_inventory_discrepancy for r in reports), default=0.0)
    n_flows = sum(len(r.active_flows) for r in reports)

    # One controlled counter-example, on a phototrophic and a heterotrophic case.
    demo_keys = ("rec_spirulina_padi", "rec_heterotrophic_powder")
    demos = [consistency_mod.duplicated_inventory_drift(c.scenario(run.lib), c.label)
             for c in cases if c.key in demo_keys]

    _write(RESULTS / "shared_inventory_consistency.txt",
           report_verification.shared_inventory_consistency(
               reports, demos, suite.coverage(run.lib, cases), duplicates,
               consistency_mod.CONSISTENCY_TOL))
    run.artifacts["consistency"] = reports
    run.artifacts["consistency_demos"] = demos
    run.status["consistency"] = "pass" if ok else "fail"
    run.notes.append(
        f"Shared-inventory consistency over {len(reports)} distinct scenarios and "
        f"{n_flows} flow comparisons: {'PASS' if ok else 'FAIL'}; maximum relative "
        f"TEA-LCA discrepancy {worst:.1e}, maximum gap to the inventory field "
        f"{worst_inv:.1e}."
    )
    if not ok:
        raise SystemExit("shared-inventory consistency FAILED")


def stage_method(run: Run) -> None:
    """The LCA method declaration, and the coverage it does not have."""
    print("[method] life-cycle method statement and coverage")
    from algametrix.lciamethod import completeness, method_statement
    from algametrix.paper import suite

    method = run.lib.lcia_method
    if method is None:
        raise SystemExit("no data/lcia.yaml: there is no method declaration to report")

    cases, _ = suite.distinct_cases(run.lib)
    order = [ind.key for ind in method.indicators]
    gaps: dict[tuple[str, str], dict[str, set[str]]] = {}
    for case in cases:
        for gap in completeness(case.scenario(run.lib)):
            entry = gaps.setdefault((gap.item, gap.kind), {"cat": set(), "case": set()})
            entry["cat"].add(gap.indicator)
            entry["case"].add(case.key)

    lines = ["", "", "8  Completeness over the scenarios of this paper",
             "-" * 47, ""]
    if gaps:
        lines.append(
            f"  {len(cases)} scenarios. {len(gaps)} declared flows carry no factor in at "
            "least one category,")
        lines.append(
            "  so they contribute nothing to it - which understates that category by an "
            "unknown")
        lines.append("  amount rather than by zero.")
        lines.append("")
        rows = [("flow", "kind", "scenarios", "categories with no factor")]
        for (item, kind), entry in sorted(gaps.items()):
            rows.append((item, kind, str(len(entry["case"])),
                         ", ".join(k for k in order if k in entry["cat"])))
        widths = [max(len(r[i]) for r in rows) for i in range(4)]
        for n, row in enumerate(rows):
            lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
            if n == 0:
                lines.append("  " + "  ".join("-" * w for w in widths))
    else:
        lines.append(
            f"  None of the {len(cases)} scenarios declares a material, utility or "
            "solvent outside\n  what the factor table characterizes. The structural "
            "exclusions of section 2 still\n  apply to all of them.")

    indicative = method.indicative_factors()
    _write(RESULTS / "lcia_method_statement.txt", method_statement(method) + "\n".join(lines) + "\n")
    run.status["lcia_method_declared"] = "pass"
    run.notes.append(
        f"Life-cycle method declared in data/lcia.yaml: {len(method.factors)} background "
        f"factors, each with unit, geography, reference period, source and quality flag "
        f"({len(indicative)} flagged indicative); {len(method.excluded)} declared "
        f"exclusions from the boundary; {len(method.limitations)} declared limitations."
    )


def stage_benchmark(run: Run) -> None:
    """Independent implementation benchmark for the LCA."""
    print("[benchmark] independent matrix LCA")
    from algametrix.paper import matrixlca, suite

    cases, _ = suite.distinct_cases(run.lib)
    reports = [matrixlca.benchmark(c.scenario(run.lib), c.label) for c in cases]
    ok = all(r.passed(matrixlca.BENCHMARK_TOL) for r in reports)
    worst = max((r.max_rel_diff for r in reports), default=0.0)

    bw = None
    if matrixlca.brightway_available():
        scn = next(c for c in cases if c.key == "rec_scp_protein").scenario(run.lib)
        bw = (matrixlca.compare_with_brightway(scn),
              matrixlca.run_matrix_lca(scn).impacts)

    _write(RESULTS / "lca_implementation_benchmark.txt",
           report_verification.lca_implementation_benchmark(
               reports, matrixlca.BENCHMARK_TOL, matrixlca.brightway_available(), bw))
    run.artifacts["benchmark"] = reports
    run.status["lca_implementation_benchmark"] = "pass" if ok else "fail"
    run.notes.append(
        f"Independent matrix LCA benchmark over {len(reports)} scenarios and "
        f"{sum(len(r.rows) for r in reports)} indicator comparisons "
        f"({len(matrixlca.IMPACT_CATEGORIES)} impact categories plus gross GWP and the "
        f"biogenic adjustment): {'PASS' if ok else 'FAIL'}; maximum relative difference "
        f"{worst:.1e}."
        + ("" if matrixlca.brightway_available() else
           " Brightway (bw2calc) is not importable in this interpreter, so the optional "
           "third-party cross-check did not run here"
           + (f"; a previous run is recorded in results/brightway_crosscheck.txt."
              if (RESULTS / "brightway_crosscheck.txt").exists() else
              ". Run scripts/brightway_crosscheck.py in an environment that has it."))
    )
    if not ok:
        raise SystemExit("LCA implementation benchmark FAILED")


def stage_reproductions(run: Run) -> None:
    print("[reproductions] engine versus source values")
    rows = reproduction.build_rows(run.dataset, run.lib, registry=run.registry)
    blocked = reproduction.blocked_rows(run.dataset)
    excluded = reproduction.excluded_rows(run.dataset)
    _write(RESULTS / "validation.txt", report.reproductions(rows, blocked, excluded))
    run.artifacts["reproduction_rows"] = rows
    run.artifacts["reproduction_blocked"] = blocked
    run.artifacts["reproduction_excluded"] = excluded
    summary = reproduction.evidence_summary(rows)
    run.artifacts["evidence_summary"] = summary
    by_class = ", ".join(f"{n} {cls.replace('_', ' ')}"
                         for cls, n in summary.by_class.items())
    run.notes.append(
        f"{summary.n_point} point comparison(s): {by_class}. Retrospective untuned "
        f"production cost, {summary.untuned_cost.describe()}; retrospective untuned "
        f"GWP, {summary.untuned_gwp.describe()}. {len(blocked)} blocked Tier-B "
        f"studies; {len(excluded)} record(s) excluded for unsound provenance "
        f"({', '.join(sorted(excluded)) or 'none'})."
    )


def stage_harmonization(run: Run) -> None:
    print("[harmonization] constant-cohort cost harmonization")
    a = harmonization.run_analysis_a(run.dataset, registry=run.registry)
    b = harmonization.run_analysis_b(run.dataset, registry=run.registry, lib=run.lib)
    # Recomputed rather than fetched with a default. The definition audit carries
    # the statement that this cohort is homogeneous in its LABEL only, which is
    # the most important qualification in the file; reaching for it with .get()
    # meant that running this stage without `endpoints` first - which is what
    # `--only figures` does through its prerequisite map - rewrote the file with
    # that paragraph silently missing. A caveat that can disappear because of the
    # order stages ran in is not a caveat.
    definition = (run.artifacts.get("definition_audit")
                  or endpoints.definition_audit(run.dataset.records))
    text = report.harmonization(a, b, harmonization.conclusion(a, b), run.registry,
                                definition=definition)
    _write(RESULTS / "harmonization.txt", text)
    run.artifacts["analysis_a"] = a
    run.artifacts["analysis_b"] = b
    run.status["task_1_cost_harmonization"] = "pass" if b.n >= 3 else "partial"
    run.notes.append(
        f"Analysis A cohort n={len(a.cohort)}; Analysis B cohort n={b.n} "
        f"({len(b.blocked)} Tier-B studies blocked by missing scenario definitions)."
    )

    # Task 3 status is derived from the data, not asserted. It reaches "pass" only
    # when every index has provider provenance AND at least one study carries its
    # own published cost breakdown; until then the split is engine-derived.
    qualities = {n.quality for n in a.normalizations.values()}
    run.notes.append(f"Normalization quality flags in use: {sorted(qualities)}.")
    unsourced = [name for name, idx in run.registry.indices.items()
                 if idx.provenance != "fetched_from_provider_api"]
    n_published_split = sum(1 for r in run.dataset if r.has_cost_breakdown)
    if not unsourced and n_published_split:
        run.status["task_3_price_normalization"] = "pass"
    else:
        run.status["task_3_price_normalization"] = "partial"
        if unsourced:
            run.notes.append(
                "Task 3 partial: index(es) without provider provenance: "
                + ", ".join(sorted(unsourced)) + "."
            )
        if not n_published_split:
            run.notes.append(
                "Task 3 partial: no study in the dataset publishes a CAPEX/OPEX "
                "breakdown, so component shares are engine-derived and every "
                "normalized value is reported as an interval."
            )


def stage_gwp(run: Run) -> None:
    print("[gwp] GWP analysis populations")
    pops = gwp.build_populations(run.dataset, lib=run.lib)
    text = report.gwp_harmonization(
        pops, gwp.conclusion(pops), gwp.class_disagreements(run.dataset)
    )
    _write(RESULTS / "gwp_harmonization.txt", text)
    run.artifacts["gwp"] = pops
    run.status["task_4_gwp_populations"] = "pass" if pops.n_reproduced >= 3 else "partial"
    run.notes.append(
        f"{pops.n_published} published GWP points; {pops.n_reproduced} engine "
        f"reproductions of a published endpoint; {len(pops.blocked)} blocked."
    )


def stage_carbon(run: Run) -> None:
    print("[carbon] biogenic-carbon accounting")
    reports = []
    for rec in sorted((r for r in run.dataset if r.is_executable), key=lambda r: r.study_id):
        scn = reconstructions.build(rec.reconstruction_builder, run.lib)
        reports.append(carbon.carbon_report(scn, rec.study_id))
    for a in archetypes.ARCHETYPES:
        if a.kind == "library_default":
            reports.append(carbon.carbon_report(a.build(run.lib), f"archetype:{a.key}"))

    gross_pairs = [(r.label, r.gross_gwp) for r in reports]
    net_pairs = [(r.label, r.net_declared) for r in reports]
    nocredit_pairs = [(r.label, r.net_no_credit) for r in reports]
    spreads = [
        compute_spread("GROSS cradle-to-gate GWP (before any biogenic adjustment)",
                       gross_pairs),
        compute_spread("NET GWP under the declared convention", net_pairs),
        compute_spread("NET GWP with no biogenic-carbon credit", nocredit_pairs),
    ]
    _write(RESULTS / "carbon_accounting.txt", report.carbon_accounting(reports, spreads))
    run.artifacts["carbon"] = reports
    run.status["task_8_biogenic_carbon"] = "pass"
    neg = [r.label for r in reports if r.net_declared < 0]
    if neg:
        run.notes.append(
            f"Net-negative GWP under the declared convention for: {', '.join(neg)} "
            "- always reported with its gross value."
        )


def stage_sobol(run: Run) -> None:
    print("[sobol] implementation validation")
    n_bench = 1024 if run.quick else SOBOL_BENCHMARK_N
    outcomes = [
        sobol.run_benchmark(factory(), n_bench, MASTER_SEED)
        for factory in sobol.BENCHMARKS
    ]
    # The group estimator is validated on its own analytical cases: the figure
    # reports a between-group interaction remainder, and no per-parameter
    # benchmark can tell whether that number is right.
    group_outcomes = [
        sobol.run_group_benchmark(factory(), n_bench, MASTER_SEED)
        for factory in sobol.GROUP_BENCHMARKS
    ]
    passed = all(o.max_abs_error <= SOBOL_BENCHMARK_TOLERANCE
                 and not o.result.violations()
                 for o in (*outcomes, *group_outcomes))
    run.sobol_validation_passed = passed
    run.artifacts["sobol_benchmarks"] = outcomes
    run.artifacts["sobol_group_benchmarks"] = group_outcomes
    _write(RESULTS / "sobol_validation.txt",
           report.sobol_validation(outcomes, sobol.salib_available(),
                                   SOBOL_BENCHMARK_TOLERANCE,
                                   group_outcomes=group_outcomes))
    if not passed:
        run.status["task_5_sobol_validation"] = "fail"
        print("  !! benchmark validation failed; sensitivity results not generated")
        return

    print("[sobol] convergence")
    sizes = SOBOL_QUICK_SIZES if run.quick else SOBOL_CONVERGENCE_SIZES
    conv_blocks = []
    chosen_by_key: dict[str, int] = {}
    for arch in archetypes.ARCHETYPES:
        scn = arch.build(run.lib)
        params = parameters.mode_parameters(parameters.MODE_A_SHARED_FOREGROUND, scn)
        output = "Production cost (EUR/kg)"
        rows = sobol.convergence_study(
            sobol_parameters(scn, params), make_model(scn, params, output),
            sizes, MASTER_SEED, output, bootstrap=200,
        )
        chosen = sobol.smallest_converged(rows, SOBOL_MAX_CI_WIDTH, SOBOL_MAX_SHIFT)
        chosen_by_key[arch.key] = chosen.n_base if chosen else max(sizes)
        conv_blocks.append(
            (f"{arch.label} - Mode A - {output}", rows, chosen)
        )
    criteria = {
        "no impossible point estimate (S1/ST outside [0,1], S1 > ST)": f"tol {sobol.INDEX_TOLERANCE}",
        "no materially negative lower bootstrap bound on S1": f"tol {sobol.INDEX_TOLERANCE}",
        "bootstrap 95% CI width on ST for the top-2 drivers": f"< {SOBOL_MAX_CI_WIDTH}",
        "|ST - ST(largest run)|": f"< {SOBOL_MAX_SHIFT}",
        "ranking of drivers identical to the largest run": "required",
        "absolute error on analytical benchmark indices": f"< {SOBOL_BENCHMARK_TOLERANCE}",
    }
    _write(RESULTS / "sobol_convergence.txt", report.sobol_convergence(conv_blocks, criteria))

    print("[sobol] sensitivity on the archetypes")
    blocks = []
    for arch in archetypes.ARCHETYPES:
        scn = arch.build(run.lib)
        n_base = chosen_by_key[arch.key]
        modes: dict[str, list] = {}
        for mode in (parameters.MODE_A_SHARED_FOREGROUND, parameters.MODE_B_FULL_DECISION):
            params = parameters.mode_parameters(mode, scn)
            results = []
            for output in SENSITIVITY_OUTPUTS:
                results.append(sobol.analyze(
                    sobol_parameters(scn, params), make_model(scn, params, output),
                    n_base, MASTER_SEED, output, bootstrap=200,
                ))
            modes[mode] = results
        blocks.append({
            "archetype_label": arch.label,
            "archetype_kind": arch.kind,
            "provenance": arch.provenance,
            "archetype_notes": arch.notes,
            "modes": modes,
        })
    _write(RESULTS / "sensitivity.txt",
           report.sensitivity(blocks, parameters.MODE_DESCRIPTIONS, passed, MASTER_SEED))
    run.artifacts["sobol_blocks"] = blocks
    run.artifacts["sobol_convergence"] = conv_blocks

    # Only claim a driver flip if Mode A gives a stable, different top driver per output.
    flips = _driver_flip(blocks)
    run.status["task_5_sobol_validation"] = "pass"
    run.notes.append(
        "Mode-A dominant driver by output and archetype: " + "; ".join(flips)
    )


def _driver_flip(blocks) -> list[str]:
    out = []
    for b in blocks:
        tops = {r.output: r.ranking()[0] for r in b["modes"][parameters.MODE_A_SHARED_FOREGROUND]}
        same = len(set(tops.values())) == 1
        out.append(
            f"{b['archetype_label']}: "
            + ", ".join(f"{k} -> {v}" for k, v in tops.items())
            + (" (same driver for every output)" if same else " (driver differs by output)")
        )
    return out


def stage_uncertainty(run: Run) -> None:
    print("[uncertainty] Monte-Carlo decomposition")
    sizes = MC_QUICK_SIZES if run.quick else MC_CONVERGENCE_SIZES

    conv_blocks = []
    per_archetype_n: list[int] = []
    for arch in archetypes.ARCHETYPES:
        scn = arch.build(run.lib)
        rows = mcuncertainty.quantile_convergence(
            scn, arch.key, "Production cost (EUR/kg)", mcuncertainty.MODE_JOINT,
            sizes, MASTER_SEED, bootstrap=200,
        )
        chosen = mcuncertainty.smallest_converged_n(rows, MC_MAX_REL_SHIFT, MC_MAX_CI_REL_WIDTH)
        conv_blocks.append(
            (f"{arch.label} - joint - Production cost (EUR/kg)", rows, chosen)
        )
        per_archetype_n.append(chosen.n if chosen is not None else max(sizes))
    # One sample size for every archetype: the largest of the per-archetype
    # smallest-converged sizes, so no archetype is reported below its own
    # convergence threshold.
    chosen_n = max(per_archetype_n)

    # The variance DECOMPOSITION is a group-wise Sobol' analysis, not a ratio of
    # conditional variances: pinning the other groups at nominal does not
    # decompose the variance of a non-additive model. Sample sizes are powers of
    # two, as the Sobol' sequence requires, and are reused from the sensitivity
    # convergence study.
    group_sobol: dict[tuple[str, str], object] = {}
    n_group = 256 if run.quick else GROUP_SOBOL_N

    blocks = []
    metadata: list[dict] = []
    seen_meta: set[str] = set()
    for arch in archetypes.ARCHETYPES:
        scn = arch.build(run.lib)
        params = parameters.mode_parameters(parameters.MODE_B_FULL_DECISION, scn)
        for metric in UNCERTAINTY_METRICS:
            group_sobol[(arch.label, metric)] = sobol.analyze_groups(
                sobol_parameters(scn, params), make_model(scn, params, metric),
                n_group, MASTER_SEED, metric, bootstrap=200,
                group_order=list(parameters.GROUPS),
            )
        metrics = {
            metric: mcuncertainty.decompose(
                scn, arch.key, metric, chosen_n, MASTER_SEED, bootstrap=300)
            for metric in UNCERTAINTY_METRICS
        }
        blocks.append({
            "archetype_label": arch.label,
            "archetype_kind": arch.kind,
            "provenance": arch.provenance,
            "archetype_notes": arch.notes,
            "metrics": metrics,
        })
        for p in parameters.active(parameters.ALL_PARAMETERS, scn):
            key = f"{arch.key}:{p.name}"
            if key in seen_meta:
                continue
            seen_meta.add(key)
            md = p.metadata(scn)
            md["name"] = f"{p.name} [{arch.key}]"
            metadata.append(md)

    _write(RESULTS / "uncertainty.txt",
           report.uncertainty(blocks, conv_blocks, metadata, MASTER_SEED, chosen_n,
                              groups=group_sobol))
    bad = {k: g.violations() for k, g in group_sobol.items() if g.violations()}
    run.status["task_6_uncertainty_decomposition"] = "pass" if not bad else "partial"
    run.artifacts["mc_blocks"] = blocks
    run.artifacts["mc_convergence"] = conv_blocks
    run.artifacts["group_sobol"] = group_sobol
    run.notes.append(f"Monte-Carlo sample size chosen by convergence: n={chosen_n}.")
    run.notes.append(
        f"Group Sobol' decomposition (n_base={n_group}) over "
        f"{len(parameters.GROUPS)} parameter groups: "
        + "; ".join(
            f"{label} / {metric}: "
            + ", ".join(f"{g} S={s.value:.2f}" for g, (s, _st) in gr.by_group().items())
            + f", between-group interactions {gr.interactions:.2f}"
            for (label, metric), gr in group_sobol.items()
        )
    )
    if bad:
        run.notes.append(
            "Group Sobol' index violations: "
            + "; ".join(f"{k}: {', '.join(v)}" for k, v in bad.items()))


def stage_figures(run: Run) -> None:
    print("[figures] regenerating")
    from algametrix.paper import figures as figmod

    # A figure is never drawn from stale state: any prerequisite stage that has
    # not run in this process is run now, with the same seeds and sample sizes.
    prereq = {
        # `endpoints` first: `harmonization` reads its definition audit, and a
        # prerequisite map one level deep would run harmonization without it.
        "definition_audit": ("endpoints", stage_endpoints),
        "analysis_a": ("harmonization", stage_harmonization),
        "gwp": ("gwp", stage_gwp),
        "carbon": ("carbon", stage_carbon),
        "sobol_blocks": ("sobol", stage_sobol),
        "mc_blocks": ("uncertainty", stage_uncertainty),
    }
    for key, (stage_name, fn) in prereq.items():
        if key not in run.artifacts:
            fn(run)
            if stage_name not in run.stages_run:
                run.stages_run.append(stage_name)

    made = figmod.build_all(run, FIGURES)
    for p in made:
        print(f"  wrote {p.relative_to(ROOT)}")


def stage_figures_jie(run: Run) -> None:
    """The four figures of the Journal of Industrial Ecology manuscript."""
    print("[figures_jie] regenerating")
    from algametrix.paper import figures_jie

    prereq = {
        "verification_reports": ("verification", stage_verification),
        "consistency": ("consistency", stage_consistency),
        "benchmark": ("benchmark", stage_benchmark),
        "reproduction_rows": ("reproductions", stage_reproductions),
        "sobol_blocks": ("sobol", stage_sobol),
        "mc_blocks": ("uncertainty", stage_uncertainty),
    }
    for key, (stage_name, fn) in prereq.items():
        if key not in run.artifacts:
            fn(run)
            if stage_name not in run.stages_run:
                run.stages_run.append(stage_name)

    made = figures_jie.build_all(run, FIGURES / "jie", RESULTS)
    for p in made:
        print(f"  wrote {p.relative_to(ROOT)}")


def stage_supplementary(run: Run) -> None:
    """Assemble the Supplementary Information from what the other stages wrote.

    This stage embeds files rather than recomputing numbers, so it must run
    after the stages that produce them. It states which stages ran in this
    invocation, so an SI built from a partial run says so on its own front page.
    """
    print("[supplementary] assembling the SI bundle")
    from algametrix.paper import supplementary

    required = {
        "verification.txt": "verification",
        "shared_inventory_consistency.txt": "consistency",
        "lcia_method_statement.txt": "method",
        "lca_implementation_benchmark.txt": "benchmark",
        "validation.txt": "reproductions",
        "carbon_accounting.txt": "carbon",
        "sobol_validation.txt": "sobol",
        "sensitivity.txt": "sobol",
        "uncertainty.txt": "uncertainty",
    }
    stale = sorted({stage for name, stage in required.items()
                    if stage not in run.stages_run and (RESULTS / name).exists()})
    if stale:
        print(f"  note: embedding existing output for stages not run here: "
              f"{', '.join(stale)}")

    made = supplementary.build(run, ROOT / "supplementary", RESULTS, ROOT,
                               seed=MASTER_SEED, stale_stages=stale)
    for p in made:
        print(f"  wrote {p.relative_to(ROOT)}")
    docx = supplementary.to_docx(ROOT / "supplementary" / "SI.md")
    if docx:
        print(f"  wrote {docx.relative_to(ROOT)}")
    else:
        print("  note: pandoc not found; SI.md written, DOCX not generated. "
              "Install pandoc and re-run, or convert manually.")


def stage_summary(run: Run) -> None:
    print("[summary] machine-readable status")
    run.collect_todos()
    tests_passed, tests_failed = _run_tests()
    task_stages = ("studies", "endpoints", "verification", "consistency", "method",
                   "benchmark",
                   "reproductions", "harmonization", "gwp", "carbon", "sobol",
                   "uncertainty")
    missing = [st for st in task_stages if st not in run.stages_run]
    if missing:
        print(f"  !! PARTIAL RUN: {', '.join(missing)} did not execute in this "
              "invocation, so their tasks are reported as 'not_run'.")
        print("     Run `python reproduce.py` with no --only to produce a complete summary.")

    summary = {
        "generated_by": "reproduce.py",
        "master_seed": MASTER_SEED,
        "complete_run": not missing,
        "stages_run": list(run.stages_run),
        **{k: run.status.get(k, "not_run") for k in (
            "consistency",
            "lcia_method_declared",
            "lca_implementation_benchmark",
            "task_1_cost_harmonization",
            "task_2_endpoint_classification",
            "task_3_price_normalization",
            "task_4_gwp_populations",
            "task_5_sobol_validation",
            "task_6_uncertainty_decomposition",
            "task_7_study_audit",
            "task_8_biogenic_carbon",
        )},
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "notes": run.notes,
        "remaining_todos": sorted(set(run.todos)),
    }
    _write(RESULTS / "revision_summary.json", json.dumps(summary, indent=2) + "\n")


def _run_tests() -> tuple[int, int]:
    """Run pytest and return (passed, failed). Reported honestly, including 0/0."""
    import subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "--tb=no"],
            cwd=ROOT, capture_output=True, text=True, timeout=1800,
        )
    except Exception as exc:  # pragma: no cover
        print(f"  could not run tests: {exc}")
        return 0, 0
    import re
    passed = failed = 0
    for line in proc.stdout.splitlines()[::-1]:
        m_pass = re.search(r"(\d+) passed", line)
        m_fail = re.search(r"(\d+) failed", line)
        if m_pass or m_fail:
            passed = int(m_pass.group(1)) if m_pass else 0
            failed = int(m_fail.group(1)) if m_fail else 0
            break
    print(f"  tests: {passed} passed, {failed} failed")
    return passed, failed


STAGE_FUNCS = {
    "studies": stage_studies,
    "endpoints": stage_endpoints,
    "verification": stage_verification,
    "consistency": stage_consistency,
    "method": stage_method,
    "benchmark": stage_benchmark,
    "reproductions": stage_reproductions,
    "harmonization": stage_harmonization,
    "gwp": stage_gwp,
    "carbon": stage_carbon,
    "sobol": stage_sobol,
    "uncertainty": stage_uncertainty,  # includes the group-wise Sobol' decomposition
    "figures": stage_figures,
    "figures_jie": stage_figures_jie,
    "supplementary": stage_supplementary,
    "summary": stage_summary,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", choices=STAGES,
                    help="run only this stage (repeatable)")
    ap.add_argument("--quick", action="store_true",
                    help="smaller stochastic samples; results are NOT publication grade")
    ap.add_argument("--list", action="store_true", help="list the stages and exit")
    args = ap.parse_args()

    if args.list:
        for s in STAGES:
            print(s)
        return 0

    wanted = args.only or list(STAGES)
    run = Run(quick=args.quick)
    if args.quick:
        print("!! --quick: reduced sample sizes, for CI only\n")

    t0 = time.perf_counter()
    for stage in STAGES:
        if stage not in wanted:
            continue
        STAGE_FUNCS[stage](run)
        if stage not in run.stages_run:
            run.stages_run.append(stage)
    print(f"\ndone in {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
