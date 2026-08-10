"""Writers for the two verification result files.

Kept apart from :mod:`algametrix.paper.report`, which writes the study-level
audits, because these two describe the *software* rather than the evidence base
and a reader should not have to disentangle them.
"""

from __future__ import annotations

from .report import RULE, THIN, header


# --------------------------------------------------------------------------
# Shared-inventory consistency
# --------------------------------------------------------------------------

def shared_inventory_consistency(reports, demos, coverage, duplicates, tol) -> str:
    """The verification that TEA and LCA meter the same physical flows."""
    from ..consistency import format_report as fmt_consistency

    n_flows = sum(len(r.active_flows) for r in reports)
    worst = max((r.max_discrepancy for r in reports), default=0.0)
    worst_inv = max((r.max_inventory_discrepancy for r in reports), default=0.0)
    ok = all(r.all_pass for r in reports)

    lines = header(
        "SHARED-INVENTORY CONSISTENCY",
        "the quantity of each physical flow that the TEA prices, recovered "
        "independently of the quantity the LCA characterizes",
    )
    lines += [
        "WHAT THIS IS",
        THIN,
        "  run_scenario builds ONE Inventory and hands the same object to run_tea and",
        "  run_lca. Agreement between them is therefore an ARCHITECTURAL INVARIANT, not",
        "  an empirical finding, and this file is a VERIFICATION that the invariant holds",
        "  - in the same sense that a unit test verifies an interface contract. It is not",
        "  an external validation and it says nothing about whether either analysis is",
        "  right. Accuracy is reported separately, in results/validation.txt.",
        "",
        "  Sharing an object does not by itself guarantee that both analyses read the",
        "  same FIELD of it: run_tea could price co2_supply_per_kg while run_lca",
        "  characterizes co2_fixed_per_kg. Both are on the inventory; they differ by the",
        "  carbon-utilization efficiency. The recovery below would catch that. It would",
        "  also catch a re-basing between the inventory and the reported number, because",
        "  the quantities are recovered from the RESULTS and not from the inventory.",
        "",
        "HOW A QUANTITY IS RECOVERED",
        THIN,
        "  Both analyses are exactly affine in their own coupling coefficient, so the",
        "  physical quantity is the derivative and a central difference recovers it:",
        "",
        "    q_TEA(k) = [ d(production cost) / d(unit price of k) ] / (1 + overhead_frac)",
        "    q_LCA(k) =   d(gross GWP)       / d(GWP factor of k)",
        "",
        "  Both are in physical units of k per kg of dry biomass, and are read off two",
        "  different result objects produced by two different code paths. The only",
        "  non-physical term is overhead_frac: overhead is DEFINED as a multiple of the",
        "  priced flows, so it is divided out and what remains is a physical quantity.",
        "  Water and land carry no characterization factor and are recovered directly;",
        "  those rows are marked.",
        "",
        "  The two recoveries each rebuild an inventory from the scenario rather than",
        "  sharing one object the way run_scenario does. That is deliberate and is the",
        "  stronger test: build_inventory is a pure function of the scenario, so the two",
        "  inventories are identical by construction, and what the comparison isolates is",
        "  whether run_tea and run_lca READ THE SAME FIELDS of it and report on the same",
        "  basis. The single-object path is exercised by the structural checks.",
        "",
        f"  agreement criterion : relative difference <= {tol:g}",
        "",
        "SCENARIO COVERAGE",
        THIN,
    ]
    for key, value in coverage.items():
        lines.append(f"  {key:34s} {value}")
    lines += [
        "",
        f"  The counts above are over the {coverage['total']} STRUCTURALLY DISTINCT",
        "  scenarios. Several suite members build an identical Scenario by a different",
        "  route - a template and the reconstruction that wraps it, an archetype and its",
        "  template - and are counted once, so the size of the evidence base is not",
        "  inflated. Collapsed:",
    ]
    if duplicates:
        for kept, absorbed in duplicates.items():
            lines.append(f"    {kept} == {', '.join(absorbed)}")
    else:
        lines.append("    none")

    lines += [
        "",
        RULE,
        "RESULT",
        RULE,
        f"  distinct scenarios checked        : {len(reports)}",
        f"  flow comparisons                  : {n_flows}",
        f"  maximum relative TEA-LCA gap      : {worst:.3e}",
        f"  maximum gap to the inventory field: {worst_inv:.3e}",
        f"  overall                           : {'PASS' if ok else 'FAIL'}",
        "",
        "  The residual is floating-point round-off in the two evaluations of the",
        "  central difference, not a modelling difference. There is no quantity here",
        "  that a better model would reduce; it is bounded by double precision.",
        "",
    ]
    for rep in reports:
        lines.append(fmt_consistency(rep))
        lines.append("")

    lines += [
        RULE,
        "CONTROLLED COUNTER-EXAMPLE: WHAT A DUPLICATED INVENTORY WOULD DO",
        RULE,
        "  A demonstration of a failure mode, run on this engine against itself. It is",
        "  NOT a claim about any other software: no other tool is inspected or implicated",
        "  here, and a duplicated inventory is a hazard, not an inevitability.",
        "",
        "  A duplicated-inventory implementation is emulated by giving the TEA and the",
        "  LCA their own copies of the scenario. ONE physical assumption - the harvesting",
        "  recovery - is then updated in the TEA copy only, exactly as a maintainer would",
        "  if the two inventories lived in two files and only one was edited. The",
        "  single-inventory path is run on the same edit for contrast.",
        "",
    ]
    for demo in demos:
        lines += [
            THIN,
            f"{demo.scenario_name}: {demo.assumption} "
            f"{demo.old_value:.4g} -> {demo.new_value:.4g}",
            THIN,
            f"  shared inventory     : max flow discrepancy "
            f"{demo.max_shared_discrepancy:.1e}",
            f"  duplicated inventory : max flow discrepancy "
            f"{demo.max_duplicated_discrepancy:.1%}",
            "",
            f"  {'flow':22s} {'TEA-implied':>14s} {'LCA-implied':>14s} {'gap':>10s}",
        ]
        for d in sorted(demo.duplicated, key=lambda x: -x.discrepancy):
            lines.append(f"  {d.flow:22s} {d.tea_quantity:14.8g} "
                         f"{d.lca_quantity:14.8g} {d.discrepancy:9.2%}")
        gwp_err = (abs(demo.gwp_duplicated - demo.gwp_shared)
                   / max(abs(demo.gwp_shared), 1e-30))
        lines += [
            "",
            f"  reported cost, shared inventory     : {demo.cost_shared:,.4f} /kg",
            f"  reported cost, duplicated inventory : {demo.cost_duplicated:,.4f} /kg",
            f"  reported gross GWP, shared          : {demo.gwp_shared:,.4f} kg CO2-eq/kg",
            f"  reported gross GWP, duplicated      : {demo.gwp_duplicated:,.4f} kg CO2-eq/kg",
            "",
            "  The cost is identical in the two columns because the TEA copy received the",
            "  edit in both. That is the whole difficulty: the error is entirely in the",
            f"  environmental result, which is understated by {gwp_err:.1%}, and the two",
            "  numbers are still published side by side as a matched economic-environmental",
            "  pair. Nothing in either number reveals that they now describe two different",
            "  plants, and no internal check on the LCA alone would find it - the stale",
            "  inventory is perfectly self-consistent, it is simply a different plant.",
            "",
            "  Note also that electricity moves by less than the other flows: drying and",
            "  extraction electricity are referred to the product, not to the gross",
            "  biomass, so the propagation is structural rather than a uniform rescaling.",
            "  A duplicated inventory has to reproduce that structure correctly too.",
            "",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Independent LCA implementation benchmark
# --------------------------------------------------------------------------

def lca_implementation_benchmark(reports, tol, brightway, bw_result) -> str:
    """Sequential engine versus the independent matrix implementation."""
    from .matrixlca import IMPACT_CATEGORIES, format_report as fmt_bench

    worst = max((r.max_rel_diff for r in reports), default=0.0)
    ok = all(r.passed(tol) for r in reports)

    lines = header(
        "INDEPENDENT LCA IMPLEMENTATION BENCHMARK",
        "algametrix.lca (sequential accumulation) versus "
        "algametrix.paper.matrixlca (matrix formalism: A s = f; g = B s; h = C g)",
    )
    lines += [
        "WHAT THIS IS",
        THIN,
        "  Two independent codings of ONE model specification, on identical foreground",
        "  data, an identical functional unit, identical system boundaries and identical",
        "  characterization factors. This is IMPLEMENTATION VERIFICATION: agreement means",
        "  the arithmetic is right. It is not an empirical validation of the model, and it",
        "  does not test the characterization factors themselves.",
        "",
        "  The matrix implementation shares no code with algametrix.lca and never reads",
        "  an Inventory. Both matrices are assembled from the primitive scenario",
        "  parameters - productivity, harvesting recovery, solids fractions, per-stage",
        "  energy, elemental composition - so agreement tests algametrix.inventory as",
        "  well as algametrix.lca. The harvesting recovery enters as an off-diagonal",
        "  transfer coefficient in A rather than as a pre-multiplied ratio.",
        "",
        "  Two honest caveats about the matrices themselves:",
        "    * C is close to the identity, because AlgaMetrix ships already-characterized",
        "      cradle-to-gate factors (kg CO2-eq per kWh, not kg CH4 per kWh). It is",
        "      assembled and applied as a real matrix anyway, because that is the code",
        "      path a user gets on replacing the background with uncharacterized flows,",
        "      and because freshwater eutrophication draws on three separate exchanges.",
        "    * A is block-triangular: the background is a cut-off unit-process system in",
        "      which each activity carries its cradle-to-gate burden as a direct exchange.",
        "      The foreground chain is a genuine multi-stage system and is solved with a",
        "      general LU factorisation.",
        "",
        f"  agreement criterion : relative difference <= {tol:g}",
        f"  indicators compared : {len(IMPACT_CATEGORIES) + 2} per scenario "
        f"({len(IMPACT_CATEGORIES)} impact categories, plus gross GWP and the biogenic",
        "                        adjustment)",
        "",
        RULE,
        "RESULT",
        RULE,
        f"  scenarios benchmarked        : {len(reports)}",
        f"  indicator comparisons        : {sum(len(r.rows) for r in reports)}",
        f"  maximum relative difference  : {worst:.3e}",
        f"  overall                      : {'PASS' if ok else 'FAIL'}",
        "",
        "  BRIGHTWAY CROSS-CHECK",
        THIN,
    ]
    if brightway and bw_result and bw_result[0]:
        bw, ours = bw_result
        lines += ["  bw2calc is installed; it was given the same A, B and C matrices.",
                  f"  {'category':36s} {'matrixlca':>16s} {'bw2calc':>16s} {'rel':>10s}"]
        for cat, value in bw.items():
            denom = max(abs(value), abs(ours[cat]), 1e-30)
            lines.append(f"  {cat:36s} {ours[cat]:16.9g} {value:16.9g} "
                         f"{abs(value - ours[cat]) / denom:10.1e}")
    else:
        lines += [
            "  bw2calc is NOT importable in the interpreter that produced this file, so",
            "  the third-party cross-check did not run HERE. It is not part of",
            "  reproduce.py because bw2calc pulls in around thirty packages the engine",
            "  does not otherwise need, and the repository should stay installable",
            "  without them. It is run separately, in its own environment:",
            "",
            "      python -m venv .bwenv",
            "      .bwenv/bin/pip install bw2calc numpy pyyaml pandas",
            "      .bwenv/bin/python scripts/brightway_crosscheck.py",
            "",
            "  and its output, including the bw2calc version that produced it, is in",
            "  results/brightway_crosscheck.txt.",
            "",
            "  Brightway is not the primary benchmark because its value lies in coupling",
            "  a model to a licensed background database (ecoinvent), which this",
            "  repository does not ship and cannot redistribute. Over a hand-built",
            "  foreground with the same aggregated factors it exercises the same linear",
            "  algebra as matrixlca, behind a much larger dependency surface.",
        ]
    lines.append("")
    for rep in reports:
        lines.append(fmt_bench(rep, tol))
        lines.append("")
    return "\n".join(lines)
