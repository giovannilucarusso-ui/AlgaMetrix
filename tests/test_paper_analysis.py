"""Tests for the analytical layer: statistics, GWP populations, carbon, Sobol, MC."""

from __future__ import annotations

import math

import numpy as np
import pytest

from algametrix.library import load_library
from algametrix.models import CarbonAccounting, CarbonSource, TrophicMode
from algametrix.paper import (
    archetypes,
    carbon,
    gwp,
    mcuncertainty,
    parameters,
    reconstructions,
    sobol,
    studies,
)
from algametrix.paper.evaluate import make_model, sobol_parameters
from algametrix.paper.stats import compute_spread, paired_changes
from algametrix.scenario import run_scenario

SEED = 20260801


@pytest.fixture(scope="module")
def dataset():
    return studies.default_dataset()


@pytest.fixture(scope="module")
def lib():
    return load_library()


# ----------------------------------------------------------------------
# Spread statistics: ratios across zero
# ----------------------------------------------------------------------

def test_ratio_is_not_computed_across_zero():
    sp = compute_spread("t", [("a", -0.5), ("b", 0.0), ("c", 10.0), ("d", 2.0)])
    assert sp.n_nonpositive == 2
    assert sp.max_min_ratio == pytest.approx(5.0)      # over the positive subset only
    assert "strictly positive" in sp.ratio_convention
    assert sp.absolute_range == pytest.approx(10.5)


def test_no_ratio_when_fewer_than_two_positive_values():
    sp = compute_spread("t", [("a", -1.0), ("b", 3.0)])
    assert sp.max_min_ratio is None
    assert sp.geometric_mean is None
    assert "undefined" in sp.ratio_convention


def test_extremes_are_attributed_to_a_study():
    sp = compute_spread("t", [("lo", 1.0), ("hi", 9.0), ("mid", 3.0)])
    assert sp.min_id == "lo" and sp.max_id == "hi"


def test_p90_p10_is_withheld_for_small_samples():
    sp = compute_spread("t", [(f"s{i}", float(i + 1)) for i in range(4)])
    assert sp.p90_p10_ratio is None
    assert any("P90/P10 not reported" in n for n in sp.notes)


def test_paired_changes_require_identical_study_sets():
    with pytest.raises(ValueError):
        paired_changes([("a", 1.0)], [("b", 2.0)])
    changes = paired_changes([("a", 2.0)], [("a", 3.0)])
    assert changes[0].relative == pytest.approx(0.5)


# ----------------------------------------------------------------------
# TASK 8 - carbon accounting
# ----------------------------------------------------------------------

def test_gross_and_net_are_always_distinguishable(lib):
    scn = reconstructions.build("scp_protein", lib)
    res = run_scenario(scn)
    assert res.lca.gwp_gross_kg_co2eq_per_kg != res.lca.gwp_kg_co2eq_per_kg
    assert res.lca.gwp_kg_co2eq_per_kg == pytest.approx(
        res.lca.gwp_gross_kg_co2eq_per_kg + res.lca.biogenic_adjustment_kg_co2eq_per_kg
    )
    assert res.lca.carbon_accounting_mode


def test_no_biogenic_credit_makes_gross_equal_net(lib):
    scn = reconstructions.build("scp_protein", lib)
    scn.lcia.carbon_accounting = CarbonAccounting.NO_BIOGENIC_CREDIT
    res = run_scenario(scn)
    assert res.lca.biogenic_adjustment_kg_co2eq_per_kg == 0.0
    assert res.lca.gwp_kg_co2eq_per_kg == pytest.approx(res.lca.gwp_gross_kg_co2eq_per_kg)


def test_legacy_master_switch_still_wins(lib):
    """count_biogenic_uptake=False must keep its historical meaning."""
    scn = reconstructions.build("scp_protein", lib)
    scn.lcia.count_biogenic_uptake = False
    scn.lcia.carbon_accounting = CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE
    res = run_scenario(scn)
    assert res.lca.carbon_accounting_mode == CarbonAccounting.NO_BIOGENIC_CREDIT.value
    assert res.lca.biogenic_adjustment_kg_co2eq_per_kg == 0.0


def test_co2_fed_scenario_carbon_report(lib):
    scn = reconstructions.build("scp_protein", lib)
    assert scn.system.carbon_source == CarbonSource.CO2
    r = carbon.carbon_report(scn, "co2_fed")
    assert r.carbon_feed == "co2"
    assert r.inorganic_co2_supplied > 0
    assert r.biogenic_co2_in_product > 0
    assert 0 < r.carbon_utilization <= 1
    assert r.net_by_mode[CarbonAccounting.NO_BIOGENIC_CREDIT.value] == pytest.approx(r.gross_gwp)
    assert (r.net_by_mode[CarbonAccounting.SOURCE_SPECIFIC_CREDIT.value]
            < r.net_by_mode[CarbonAccounting.NO_BIOGENIC_CREDIT.value])


def test_bicarbonate_fed_scenario_carbon_report(lib):
    scn = reconstructions.build("spirulina_padi", lib)
    assert scn.system.carbon_source == CarbonSource.BICARBONATE
    r = carbon.carbon_report(scn, "bicarbonate_fed")
    assert r.carbon_feed == "bicarbonate"
    # The historical convention credits nothing for a NaHCO3 feed ...
    assert r.adjustment_by_mode[CarbonAccounting.SOURCE_SPECIFIC_CREDIT.value] == 0.0
    # ... but the at-gate convention does, and both are reported.
    assert r.adjustment_by_mode[CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE.value] < 0
    assert r.carbon_supply_gwp > 0
    assert any("boundary convention" in n for n in r.notes)


def test_heterotrophic_scenario_carbon_report(lib):
    scn = reconstructions.build("heterotrophic_powder", lib)
    assert scn.system.mode == TrophicMode.HETEROTROPHIC
    r = carbon.carbon_report(scn, "heterotrophic")
    assert r.carbon_feed == "organic_substrate"
    assert r.substrate_co2_supplied > 0
    assert r.inorganic_co2_supplied == 0.0
    assert r.biogenic_co2_in_product > 0
    assert any("outside the cradle-to-gate boundary" in n for n in r.notes)


def test_a_user_can_reproduce_with_and_without_the_credit(lib):
    scn = reconstructions.build("algal_oil", lib)
    r = carbon.carbon_report(scn, "algal_oil")
    assert r.net_declared < 0 < r.gross_gwp          # net-negative under the default
    assert r.net_no_credit == pytest.approx(r.gross_gwp)
    assert any("produced by the convention" in n for n in r.notes)


def test_at_gate_credit_never_exceeds_the_carbon_leaving_the_gate(lib):
    for name in reconstructions.available():
        scn = reconstructions.build(name, lib)
        # A study whose own convention is "no credit" (spiralg2019, as published)
        # carries count_biogenic_uptake=False, and that master switch wins. Turn it
        # on explicitly so this test exercises the mode rather than the switch.
        scn.lcia.count_biogenic_uptake = True
        scn.lcia.carbon_accounting = CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE
        res = run_scenario(scn)
        inv = res.inventory
        assert res.lca.biogenic_adjustment_kg_co2eq_per_kg == pytest.approx(
            -inv.biogenic_co2_in_product_per_kg
        ), name


def test_a_source_declared_no_credit_convention_is_honoured(lib):
    """spiralg2019 publishes without a biogenic credit; the reconstruction must too."""
    scn = reconstructions.build("spiralg2019", lib)
    assert scn.lcia.count_biogenic_uptake is False
    res = run_scenario(scn)
    assert res.lca.carbon_accounting_mode == CarbonAccounting.NO_BIOGENIC_CREDIT.value
    assert res.lca.gwp_kg_co2eq_per_kg == pytest.approx(res.lca.gwp_gross_kg_co2eq_per_kg)


# ----------------------------------------------------------------------
# TASK 4 - GWP populations
# ----------------------------------------------------------------------

def test_published_and_model_derived_are_classified_apart(dataset):
    for r in dataset:
        cls = gwp.classify(r)
        if cls in gwp.COMPARISON_CLASSES:
            assert r.has_published_gwp, f"{r.study_id} labelled validation without a published GWP"
            assert r.is_executable
        if cls == gwp.CLASS_MODEL_DERIVED:
            assert not r.has_published_gwp
            assert r.is_executable


def test_reproduction_count_matches_published_and_executable(dataset, lib):
    pops = gwp.build_populations(dataset, lib=lib)
    expected = sum(1 for r in dataset if r.has_published_gwp and r.is_executable)
    assert pops.n_reproduced == expected


def test_model_derived_scenarios_are_not_in_the_validation_set(dataset, lib):
    pops = gwp.build_populations(dataset, lib=lib)
    for case in pops.reproduced_cases:
        assert case.analysis_class in gwp.COMPARISON_CLASSES
        assert case.published_gwp is not None


def test_native_and_common_comparisons_keep_the_same_scenarios(dataset, lib):
    pops = gwp.build_populations(dataset, lib=lib)
    assert set(pops.executable_spread_native_gross.ids) == \
           set(pops.executable_spread_common_gross.ids)
    assert set(pops.executable_spread_native_net.ids) == \
           set(pops.executable_spread_common_net.ids)


def test_declared_gwp_classes_match_the_rule(dataset):
    assert gwp.class_disagreements(dataset) == []


# ----------------------------------------------------------------------
# TASK 5 - Sobol
# ----------------------------------------------------------------------

@pytest.mark.parametrize("factory", sobol.BENCHMARKS, ids=lambda f: f().name)
def test_sobol_reproduces_analytical_indices(factory):
    b = factory()
    out = sobol.run_benchmark(b, 2048, SEED, bootstrap=50)
    assert out.max_abs_error < 0.03, (
        f"{b.name}: S1 err {out.s1_abs_error}, ST err {out.st_abs_error}"
    )
    assert out.result.violations() == []


def test_sobol_matches_the_reference_library_when_available():
    """Cross-check against SALib.

    SALib draws its own Saltelli sample, so the two estimates come from different
    realisations of the same design. Agreement is therefore expected within
    Monte-Carlo error, not to machine precision; the tolerance below is the same
    one the benchmark report declares against the analytical values.
    """
    b = sobol.ishigami()
    out = sobol.run_benchmark(b, 2048, SEED, bootstrap=20)
    if out.reference is None:
        pytest.skip("SALib is not installed; the cross-check is documented in the report")
    if "error" in out.reference:
        pytest.skip(f"SALib present but unusable: {out.reference['error']}")
    for mine, theirs in zip(out.result.s1, out.reference["S1"]):
        assert mine.value == pytest.approx(theirs, abs=0.02)
    for mine, theirs in zip(out.result.st, out.reference["ST"]):
        assert mine.value == pytest.approx(theirs, abs=0.02)


def test_additive_first_order_indices_sum_to_one():
    b = sobol.additive_linear()
    out = sobol.run_benchmark(b, 2048, SEED, bootstrap=20)
    assert sum(e.value for e in out.result.s1) == pytest.approx(1.0, abs=0.02)


def test_interaction_only_has_zero_first_order():
    b = sobol.interaction_only()
    out = sobol.run_benchmark(b, 2048, SEED, bootstrap=20)
    for e in out.result.s1:
        assert abs(e.value) < 0.02
    for e in out.result.st:
        assert e.value == pytest.approx(1.0, abs=0.02)


def test_sobol_requires_a_power_of_two_base_sample():
    with pytest.raises(ValueError):
        sobol.saltelli_matrices(3, 1000, SEED)


def test_sobol_is_reproducible_with_a_fixed_seed():
    b = sobol.ishigami()
    a1 = sobol.analyze(b.parameters, b.model, 512, SEED, bootstrap=10)
    a2 = sobol.analyze(b.parameters, b.model, 512, SEED, bootstrap=10)
    assert [e.value for e in a1.st] == [e.value for e in a2.st]
    assert [e.ci_low for e in a1.s1] == [e.ci_low for e in a2.s1]


def test_non_finite_outputs_are_dropped_and_counted():
    b = sobol.ishigami()

    def flaky(X):
        y = b.model(X)
        y = np.array(y, dtype=float)
        y[::97] = np.nan
        return y

    res = sobol.analyze(b.parameters, flaky, 512, SEED, bootstrap=10)
    assert res.dropped_rows > 0
    assert all(math.isfinite(e.value) for e in res.st)


def test_violations_catch_an_impossible_index():
    """The guard that would have caught the legacy S1 = 1.13 and S1 = 1.81."""
    res = sobol.SobolResult(
        output="x", parameters=["p"], n_base=8, n_evaluations=24, seed=1,
        s1=[sobol.IndexEstimate("p", 1.13, 1.0, 1.2)],
        st=[sobol.IndexEstimate("p", 0.91, 0.9, 0.95)],
    )
    v = res.violations()
    assert any("> 1" in m for m in v)
    assert any("S1[p]" in m and "ST[p]" in m for m in v)
    assert not res.converged


def test_convergence_utilities_select_a_size():
    b = sobol.additive_linear()
    rows = sobol.convergence_study(b.parameters, b.model, (128, 256, 512), SEED,
                                   bootstrap=20)
    assert [r.n_base for r in rows] == [128, 256, 512]
    assert rows[-1].max_abs_shift_vs_largest == pytest.approx(0.0)
    chosen = sobol.smallest_converged(rows, max_ci_width=0.5, max_shift=0.05)
    assert chosen is not None and chosen.n_base <= 512


def test_engine_sobol_indices_are_in_range(lib):
    """A real archetype, not a synthetic function: indices must still be bounded."""
    scn = archetypes.build("open_raceway_pond", lib)
    params = parameters.mode_parameters(parameters.MODE_A_SHARED_FOREGROUND, scn)
    res = sobol.analyze(sobol_parameters(scn, params),
                        make_model(scn, params, "Production cost (EUR/kg)"),
                        256, SEED, bootstrap=20)
    assert res.violations() == []


# ----------------------------------------------------------------------
# TASK 6 - uncertainty modes
# ----------------------------------------------------------------------

def test_uncertainty_modes_are_separated(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    fg = mcuncertainty.mode_parameters(mcuncertainty.MODE_FOREGROUND, scn)
    ec = mcuncertainty.mode_parameters(mcuncertainty.MODE_ECONOMIC, scn)
    bg = mcuncertainty.mode_parameters(mcuncertainty.MODE_BACKGROUND, scn)
    joint = mcuncertainty.mode_parameters(mcuncertainty.MODE_JOINT, scn)
    names = lambda ps: {p.name for p in ps}          # noqa: E731
    assert not names(fg) & names(ec)
    assert not names(fg) & names(bg)
    assert not names(ec) & names(bg)
    assert names(joint) == names(fg) | names(ec) | names(bg)


def test_lcia_factors_cannot_move_a_cost(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    res = mcuncertainty.run_mode(scn, "pond", "Production cost (EUR/kg)",
                                 mcuncertainty.MODE_BACKGROUND, 60, SEED, bootstrap=20)
    assert res.p10.value == pytest.approx(res.p90.value)
    assert res.variance == pytest.approx(0.0, abs=1e-18)


def test_prices_cannot_move_a_gwp(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    res = mcuncertainty.run_mode(scn, "pond", "GWP net (kg CO2-eq/kg)",
                                 mcuncertainty.MODE_ECONOMIC, 60, SEED, bootstrap=20)
    assert res.p10.value == pytest.approx(res.p90.value)


def test_quantiles_are_reproducible_with_a_fixed_seed(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    kw = dict(archetype="pond", metric="Production cost (EUR/kg)",
              mode=mcuncertainty.MODE_JOINT, n=80, seed=SEED, bootstrap=20)
    a = mcuncertainty.run_mode(scn, **kw)
    b = mcuncertainty.run_mode(scn, **kw)
    assert (a.p10.value, a.p50.value, a.p90.value) == (b.p10.value, b.p50.value, b.p90.value)
    assert (a.p90.ci_low, a.p90.ci_high) == (b.p90.ci_low, b.p90.ci_high)


def test_a_different_seed_changes_the_sample(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    kw = dict(archetype="pond", metric="Production cost (EUR/kg)",
              mode=mcuncertainty.MODE_JOINT, n=80, bootstrap=20)
    a = mcuncertainty.run_mode(scn, seed=SEED, **kw)
    b = mcuncertainty.run_mode(scn, seed=SEED + 1, **kw)
    assert a.p50.value != b.p50.value


def test_quantiles_carry_confidence_intervals(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    res = mcuncertainty.run_mode(scn, "pond", "Production cost (EUR/kg)",
                                 mcuncertainty.MODE_FOREGROUND, 200, SEED, bootstrap=50)
    for q in (res.p10, res.p50, res.p90):
        assert q.ci_low <= q.value <= q.ci_high


def test_conditional_variance_ratios_are_labelled_as_screening(lib):
    """The screening diagnostic still runs, and still cannot move the wrong output.

    It is deliberately NOT called a variance share: see
    ``Decomposition.conditional_variance_ratios`` and
    ``sobol.analyze_groups`` for the decomposition actually used.
    """
    scn = archetypes.build("open_raceway_pond", lib)
    dec = mcuncertainty.decompose(scn, "pond", "GWP net (kg CO2-eq/kg)", 150, SEED,
                                  bootstrap=20)
    ratios = dec.conditional_variance_ratios()
    assert set(ratios) == {mcuncertainty.MODE_FOREGROUND, mcuncertainty.MODE_ECONOMIC,
                           mcuncertainty.MODE_BACKGROUND, "unexplained_remainder"}
    # Prices cannot move a GWP, whatever the estimator.
    assert ratios[mcuncertainty.MODE_ECONOMIC] == pytest.approx(0.0, abs=1e-9)
    assert not hasattr(dec, "variance_shares"), (
        "the misleading name must not come back")


def test_p90_p10_is_none_when_p10_is_not_positive():
    q = mcuncertainty.QuantileEstimate
    res = mcuncertainty.ModeResult(
        archetype="a", metric="m", mode="joint", n=1, seed=1, correlated=False,
        parameters=[], nominal=0.0,
        p10=q(10, -1.0, -1.1, -0.9), p50=q(50, 0.0, 0.0, 0.0), p90=q(90, 1.0, 0.9, 1.1),
        variance=1.0, mean=0.0,
    )
    assert res.p90_p10 is None
    assert res.absolute_band == pytest.approx(2.0)


def test_independence_is_reported_as_an_assumption(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    res = mcuncertainty.run_mode(scn, "pond", "Production cost (EUR/kg)",
                                 mcuncertainty.MODE_FOREGROUND, 60, SEED, bootstrap=10)
    assert any("INDEPENDENT" in n for n in res.notes)


def test_grouped_dependence_changes_the_sample(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    params = mcuncertainty.mode_parameters(mcuncertainty.MODE_FOREGROUND, scn)
    indep = mcuncertainty.sample(params, scn, 200, SEED, correlated=False)
    corr = mcuncertainty.sample(params, scn, 200, SEED, correlated=True)
    assert not np.allclose(indep, corr)


def test_every_uncertain_parameter_carries_full_metadata(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    for p in parameters.active(parameters.ALL_PARAMETERS, scn):
        md = p.metadata(scn)
        for key in ("distribution", "lower", "mode_or_mean", "upper_or_sd",
                    "source", "evidence_quality", "correlation_group", "notes"):
            assert key in md
        assert md["source"], f"{p.name} has no declared source"
        assert md["evidence_quality"] in parameters.EVIDENCE_QUALITIES
        assert md["lower"] <= md["mode_or_mean"] <= md["upper_or_sd"]


def test_characterization_factor_bands_are_labelled_as_assumptions():
    for p in parameters.BACKGROUND:
        assert p.evidence_quality == "scenario_assumption"
        assert "SCENARIO ASSUMPTION" in p.source


def test_physical_caps_are_respected(lib):
    scn = archetypes.build("open_raceway_pond", lib)
    for name in ("Harvesting recovery", "Nutrient uptake", "Carbon utilization"):
        p = next(x for x in parameters.ALL_PARAMETERS if x.name == name)
        lo, mode, hi = p.bounds(scn)
        assert hi <= 1.0 and lo >= 0.0 and lo <= mode <= hi


# ----------------------------------------------------------------------
# Archetypes
# ----------------------------------------------------------------------

def test_library_default_archetype_is_flagged_as_such():
    a = archetypes.get("led_pbr")
    assert a.kind == "library_default"
    assert a.study_id is None
    assert "NOT a reproduction" in a.notes


def test_study_archetypes_point_at_a_real_record(dataset):
    for a in archetypes.ARCHETYPES:
        if a.kind == "study_reconstruction":
            rec = dataset.by_id(a.study_id)
            assert rec.is_executable
