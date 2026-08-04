"""Cost harmonization on constant cohorts.

The defect this replaces
------------------------
The previous analysis reported a single chain:

    reported 862x  ->  price-normalised 783x  ->  Tier-B harmonised 23.66x

The first two numbers describe 17 studies; the third describes 4. Most of the
"collapse" is therefore the removal of 13 studies, including the two that set the
extremes. A sequential decomposition whose population changes between steps
cannot attribute the change to the step.

What replaces it
----------------
Two analyses that never change their own membership:

**Analysis A - full literature cohort.** The same eligible studies at both
stages: reported value in the common currency, then price-year normalized.
Isolates the effect of currency and price-year conversion and nothing else.

**Analysis B - matched reconstructable cohort.** The same executable studies at
all three stages: source value in the common currency and price year, engine
reconstruction under each source's own accounting assumptions, engine
reconstruction under one declared common accounting profile. Isolates the effect
of imposing common accounting.

Cohort identity is enforced by :meth:`Cohort.require_same_as`, so a dataset edit
that changes membership mid-analysis raises instead of shifting a headline number.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..library import Library, load_library
from ..models import Scenario
from ..scenario import run_scenario
from . import endpoints, indices, reconstructions
from .basis import PriceBasis
from .indices import Normalization
from .schema import StudyRecord
from .stats import PairedChange, Spread, compute_spread, paired_changes
from .studies import Cohort, Dataset

#: The price year every monetary value is moved to.
COMMON_PRICE_YEAR = 2022


@dataclass(frozen=True)
class AccountingProfile:
    """A declared set of financial conventions, applied identically to every scenario.

    Only conventions that turn capital and overheads into an annual cost are
    included. Prices are deliberately *not* part of the profile: a price is a
    property of the technology's time and place, not an accounting choice, and
    overwriting prices would harmonize away real differences.
    """

    name: str
    installation_factor: float
    indirect_factor: float
    maintenance_frac: float
    insurance_frac: float
    overhead_frac: float
    depreciation_years: float
    working_capital_frac: float
    startup_frac: float
    plant_lifetime: float
    tax_rate: float
    source: str = ""

    def apply(self, scenario: Scenario) -> Scenario:
        eco = replace(
            scenario.economics,
            installation_factor=self.installation_factor,
            indirect_factor=self.indirect_factor,
            maintenance_frac=self.maintenance_frac,
            insurance_frac=self.insurance_frac,
            overhead_frac=self.overhead_frac,
            depreciation_years=self.depreciation_years,
            working_capital_frac=self.working_capital_frac,
            startup_frac=self.startup_frac,
            plant_lifetime=self.plant_lifetime,
            tax_rate=self.tax_rate,
        )
        return replace(scenario, economics=eco)

    def as_lines(self, indent: str = "    ") -> list[str]:
        return [
            f"{indent}installation factor    : {self.installation_factor:g}",
            f"{indent}indirect factor        : {self.indirect_factor:g}",
            f"{indent}maintenance fraction   : {self.maintenance_frac:g}/yr of DFC",
            f"{indent}insurance fraction     : {self.insurance_frac:g}/yr of DFC",
            f"{indent}overhead fraction      : {self.overhead_frac:g}",
            f"{indent}depreciation period    : {self.depreciation_years:g} yr, straight line",
            f"{indent}working capital        : {self.working_capital_frac:g} of DFC",
            f"{indent}start-up cost          : {self.startup_frac:g} of DFC",
            f"{indent}plant lifetime         : {self.plant_lifetime:g} yr",
            f"{indent}tax rate               : {self.tax_rate:g}",
            f"{indent}source                 : {self.source}",
        ]


def common_profile(lib: Library | None = None) -> AccountingProfile:
    """The repository's declared common accounting profile."""
    eco = (lib or load_library()).economics
    return AccountingProfile(
        name="AlgaMetrix common accounting profile",
        installation_factor=eco.installation_factor,
        indirect_factor=eco.indirect_factor,
        maintenance_frac=eco.maintenance_frac,
        insurance_frac=eco.insurance_frac,
        overhead_frac=eco.overhead_frac,
        depreciation_years=eco.depreciation_years,
        working_capital_frac=eco.working_capital_frac,
        startup_frac=eco.startup_frac,
        plant_lifetime=eco.plant_lifetime,
        tax_rate=eco.tax_rate,
        source="data/parameters.yaml -> economics (the shipped defaults)",
    )


# --------------------------------------------------------------------------
# Analysis A - full literature cohort
# --------------------------------------------------------------------------

@dataclass
class AnalysisA:
    """Currency and price-year normalization over one unchanging cohort."""

    cohort: Cohort
    target_price_year: int
    stage_common_currency: Spread
    stage_price_normalized: Spread
    normalizations: dict[str, Normalization] = field(default_factory=dict)
    shares: indices.ShareSet | None = None
    bounds_spreads: dict[str, Spread] = field(default_factory=dict)
    excluded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ratio_change(self) -> tuple[float | None, float | None]:
        return (self.stage_common_currency.max_min_ratio,
                self.stage_price_normalized.max_min_ratio)


def run_analysis_a(
    dataset: Dataset,
    target_price_year: int = COMMON_PRICE_YEAR,
    registry: indices.Registry | None = None,
) -> AnalysisA:
    """Two stages, identical cohort, currency and price-year effects only."""
    reg = registry or indices.default_registry()
    cohort = endpoints.primary_cost_cohort(dataset.records)
    endpoints.assert_single_endpoint(list(cohort))
    endpoints.assert_single_functional_unit(list(cohort))

    shares = indices.component_share_bounds(reconstructions.available())

    stage1: list[tuple[str, float]] = []
    stage2: list[tuple[str, float]] = []
    lower_pairs: list[tuple[str, float]] = []
    upper_pairs: list[tuple[str, float]] = []
    legacy_pairs: list[tuple[str, float]] = []
    norms: dict[str, Normalization] = {}

    for rec in cohort:
        conv = reg.conversion(rec.reported_currency, reg.common_currency,
                              year=rec.reported_price_year)
        stage1.append((rec.study_id, rec.source_value * conv.rate))
        n = indices.normalize(rec, target_price_year, reg, shares=shares)
        norms[rec.study_id] = n
        if not n.ok:
            raise ValueError(
                f"{rec.study_id} passed endpoint eligibility but failed normalization: "
                f"{n.method}"
            )
        stage2.append((rec.study_id, n.value))
        lower_pairs.append((rec.study_id, n.lower if n.lower is not None else n.value))
        upper_pairs.append((rec.study_id, n.upper if n.upper is not None else n.value))
        legacy_pairs.append((rec.study_id, n.legacy_whole_cost_value or n.value))

    a = AnalysisA(
        cohort=cohort,
        target_price_year=target_price_year,
        stage_common_currency=compute_spread(
            f"A1  reported value, common currency ({reg.common_currency}), native price year",
            stage1),
        stage_price_normalized=compute_spread(
            f"A2  price-year normalized to {target_price_year}", stage2),
        normalizations=norms,
        shares=shares,
        bounds_spreads={
            "lower": compute_spread(
                "A2-lo  lower bound over the engine-derived cost-share vectors",
                lower_pairs),
            "upper": compute_spread(
                "A2-hi  upper bound over the engine-derived cost-share vectors",
                upper_pairs),
            "legacy": compute_spread(
                "A2-legacy  previous method: one plant-cost index on 100% of the cost",
                legacy_pairs),
        },
        excluded=[
            (au.study_id, au.exclusion_reason or "")
            for au in endpoints.audit_all(dataset.records)
            if not au.eligible and au.exclusion_reason != "no economic value reported"
        ],
    )
    # The two stages must describe the same studies; this is the point of the rewrite.
    Cohort([r for r in cohort]).require_same_as(cohort, "A1", "A2")
    return a


# --------------------------------------------------------------------------
# Analysis B - matched reconstructable cohort
# --------------------------------------------------------------------------

@dataclass
class StageValue:
    study_id: str
    value: float
    detail: str = ""


@dataclass
class AnalysisB:
    """Accounting harmonization over one unchanging, executable cohort."""

    cohort: Cohort
    profile: AccountingProfile
    target_price_year: int
    stage_source_value: Spread
    stage_source_accounting: Spread
    stage_common_accounting: Spread
    paired: list[PairedChange]
    per_study: dict[str, dict[str, float]] = field(default_factory=dict)
    blocked: dict[str, str] = field(default_factory=dict)
    #: study_id -> the transfer that moved the engine output into the common basis
    engine_transfers: dict[str, indices.BasisTransfer] = field(default_factory=dict)
    #: study_id -> reason the engine output could not be brought to the common basis
    basis_blocked: dict[str, str] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.cohort)


@dataclass
class IndependenceAudit:
    """How many independent sources a cohort's conclusion actually rests on.

    ``n`` counts records. A cohort of five records drawn from three publications
    by two author groups, one of which is the authors' own, is not five pieces of
    evidence, and the difference has to be visible in the output rather than left
    to a reader to reconstruct from the citation list.
    """

    n: int
    publications: dict[str, list[str]] = field(default_factory=dict)  # doi -> study ids
    self_cited: list[str] = field(default_factory=list)
    overlap_unknown: list[str] = field(default_factory=list)

    @property
    def n_publications(self) -> int:
        return len(self.publications)

    @property
    def n_external(self) -> int:
        return self.n - len(self.self_cited)

    def statement(self) -> list[str]:
        if not self.n:
            return []
        multi = [f"{doi} ({len(ids)} records)"
                 for doi, ids in sorted(self.publications.items()) if len(ids) > 1]
        out = [
            f"The {self.n} members come from {self.n_publications} publication(s). "
            f"{self.n_external} are external to the AlgaMetrix authors"
            + (f"; {len(self.self_cited)} are the authors' own "
               f"({', '.join(self.self_cited)})" if self.self_cited else "")
            + (f"; author overlap is unrecorded for {len(self.overlap_unknown)} "
               f"({', '.join(self.overlap_unknown)})" if self.overlap_unknown else "")
            + "."
        ]
        if multi:
            out.append(
                "Records sharing one publication - and therefore one facility, one cost "
                "model and one author group - are not independent evidence: "
                + "; ".join(multi) + "."
            )
        return out


def independence_audit(cohort: Cohort) -> IndependenceAudit:
    audit = IndependenceAudit(n=len(cohort))
    for rec in cohort:
        key = rec.doi or rec.full_citation or rec.study_id
        audit.publications.setdefault(key, []).append(rec.study_id)
        if rec.author_overlap_with_algametrix is True:
            audit.self_cited.append(rec.study_id)
        elif rec.author_overlap_with_algametrix is None:
            audit.overlap_unknown.append(rec.study_id)
    return audit


def reconstructable_cost_cohort(dataset: Dataset) -> tuple[Cohort, dict[str, str]]:
    """Executable studies eligible for the primary production-cost comparison.

    Returns the cohort and, separately, the studies that *claim* Tier B and would
    belong here but cannot be executed, with the reason. They are named rather
    than dropped silently, because their absence is the main limitation of this
    analysis.
    """
    eligible = endpoints.primary_cost_cohort(dataset.records)
    members = [r for r in eligible if r.is_executable]
    blocked: dict[str, str] = {}
    for r in eligible:
        if r.is_executable:
            continue
        if r.reconstructability_tier == "B":
            blocked[r.study_id] = (
                f"declared Tier B but {r.reconstruction_status}: "
                + reconstructions.MISSING_SCENARIOS.get(r.study_id, "no builder registered")
            )
    return Cohort(members), blocked


def run_analysis_b(
    dataset: Dataset,
    profile: AccountingProfile | None = None,
    target_price_year: int = COMMON_PRICE_YEAR,
    registry: indices.Registry | None = None,
    lib: Library | None = None,
) -> AnalysisB:
    """Three stages, identical cohort, accounting effect only."""
    reg = registry or indices.default_registry()
    lib = lib or load_library()
    prof = profile or common_profile(lib)
    cohort, blocked = reconstructable_cost_cohort(dataset)

    shares = indices.component_share_bounds(reconstructions.available())
    common_basis = PriceBasis(
        currency=reg.common_currency, price_year=target_price_year,
        kind="library_default_price_set",
        provenance=f"the analysis's own common basis: {reg.common_currency} "
                   f"{target_price_year}",
    )

    s1: list[tuple[str, float]] = []
    s2: list[tuple[str, float]] = []
    s3: list[tuple[str, float]] = []
    per_study: dict[str, dict[str, float]] = {}
    transfers: dict[str, indices.BasisTransfer] = {}
    basis_blocked: dict[str, str] = {}
    members = []

    for rec in cohort:
        norm = indices.normalize(rec, target_price_year, reg, shares=shares)
        if not norm.ok:
            raise ValueError(f"{rec.study_id}: source value not normalizable")
        source_scn = reconstructions.build(rec.reconstruction_builder, lib)
        source_cost = _unit_cost(source_scn)
        common_cost = _unit_cost(prof.apply(source_scn))

        # The engine returns a cost in the units of the price set it was fed, so
        # B2 and B3 are NOT automatically in the common basis. Pooling them
        # without this step mixes EUR 2016, EUR 2021 and USD 2022 into one
        # max/min ratio - the same defect as comparing a EUR model output with a
        # USD source value. A study whose engine output cannot be brought to the
        # common basis leaves the cohort rather than being silently mis-stated.
        engine_basis = reconstructions.price_basis(rec.reconstruction_builder)
        tr = indices.transfer(source_cost, engine_basis, common_basis, reg, shares)
        if not tr.ok:
            basis_blocked[rec.study_id] = tr.blocked_reason or "basis transfer refused"
            continue
        tr_common = indices.transfer(common_cost, engine_basis, common_basis, reg, shares)
        transfers[rec.study_id] = tr

        members.append(rec)
        s1.append((rec.study_id, norm.value))
        s2.append((rec.study_id, tr.amount_out))
        s3.append((rec.study_id, tr_common.amount_out))
        per_study[rec.study_id] = {
            "source_value_normalized": norm.value,
            "engine_source_accounting": tr.amount_out,
            "engine_common_accounting": tr_common.amount_out,
            "engine_source_accounting_native": source_cost,
            "engine_common_accounting_native": common_cost,
        }

    cohort = Cohort(members)

    stage1 = compute_spread(
        f"B1  source value, common currency and {target_price_year} price year", s1)
    stage2 = compute_spread(
        f"B2  engine reconstruction, each source's own accounting, in "
        f"{reg.common_currency} {target_price_year}", s2)
    stage3 = compute_spread(
        f"B3  engine reconstruction, {prof.name}, in "
        f"{reg.common_currency} {target_price_year}", s3)

    # Constant-cohort guard across all three stages.
    c1 = Cohort([dataset.by_id(i) for i in stage1.ids])
    c2 = Cohort([dataset.by_id(i) for i in stage2.ids])
    c3 = Cohort([dataset.by_id(i) for i in stage3.ids])
    c1.require_same_as(c2, "B1", "B2")
    c2.require_same_as(c3, "B2", "B3")

    return AnalysisB(
        cohort=cohort,
        profile=prof,
        target_price_year=target_price_year,
        stage_source_value=stage1,
        stage_source_accounting=stage2,
        stage_common_accounting=stage3,
        paired=paired_changes(s2, s3),
        per_study=per_study,
        blocked=blocked,
        engine_transfers=transfers,
        basis_blocked=basis_blocked,
    )


def _unit_cost(scenario: Scenario) -> float:
    r = run_scenario(scenario)
    if r.main_product is not None:
        return r.main_product.production_cost_eur_per_kg
    return r.tea.production_cost_eur_per_kg


# --------------------------------------------------------------------------
# Conditional conclusion
# --------------------------------------------------------------------------

def conclusion(a: AnalysisA, b: AnalysisB) -> list[str]:
    """A conclusion that states its own conditions instead of asserting a cause.

    Deliberately does not generate "cost divergence is mostly real": that claim
    requires the accounting step to be measured on a cohort large enough to
    support it, which the present dataset does not provide.
    """
    lines: list[str] = []
    r1, r2 = a.ratio_change
    if r1 and r2:
        direction = "widened" if r2 > r1 else "narrowed"
        lines.append(
            f"Over the SAME {len(a.cohort)} {endpoints.PRIMARY_COHORT_LABEL}, moving from "
            f"the reported value in a common currency to a {a.target_price_year} price "
            f"year {direction} the max/min spread from {r1:,.4g}x to {r2:,.4g}x "
            f"({abs(r2 / r1 - 1):.0%} change). Price-year normalization is therefore not "
            "the main source of the literature spread."
        )
    lo = a.bounds_spreads["lower"].max_min_ratio
    hi = a.bounds_spreads["upper"].max_min_ratio
    legacy = a.bounds_spreads["legacy"].max_min_ratio
    if lo and hi:
        lines.append(
            f"That conclusion is robust to the cost split: across the engine-derived "
            f"share vectors the normalized spread stays between {min(lo, hi):,.4g}x and "
            f"{max(lo, hi):,.4g}x."
            + (f" The previous method - one plant-cost index on the whole cost - gives "
               f"{legacy:,.4g}x." if legacy else "")
        )

    if b.n and all(abs(p.absolute) < 1e-9 for p in b.paired):
        lines.append(
            "Within the matched cohort the common accounting profile changed no study's "
            "unit cost: every executable reconstruction already carries the shipped "
            "accounting defaults, so stage B3 is identical to B2 by construction. The "
            "accounting-harmonization step is currently VACUOUS and measures nothing. "
            "It becomes informative only when reconstructions that carry a source's own "
            "financial conventions enter the cohort."
        )

    ind = independence_audit(b.cohort)
    lines.extend(ind.statement())

    if b.n < 3:
        lines.append(
            f"The matched reconstructable cohort contains only {b.n} stud"
            f"{'y' if b.n == 1 else 'ies'}"
            + (f" ({', '.join(b.cohort.ids)})" if b.n else "")
            + ". NO quantitative statement about the effect of imposing a common "
            "accounting profile can be supported at this n. "
            + (f"{len(b.blocked)} further Tier-B stud"
               f"{'y is' if len(b.blocked) == 1 else 'ies are'} blocked: "
               f"{', '.join(sorted(b.blocked))}." if b.blocked else "")
        )
        return lines

    r_src = b.stage_source_accounting.max_min_ratio
    r_com = b.stage_common_accounting.max_min_ratio
    if r_src and r_com:
        lines.append(
            f"Within the matched reconstructable cohort (n={b.n}, identical at every "
            f"stage, all values in EUR {b.target_price_year}), "
            f"imposing the common accounting profile moved the spread from "
            f"{r_src:,.4g}x to {r_com:,.4g}x; a divergence of {r_com:,.4g}x remains "
            "after accounting is held constant."
        )
        if ind.n_publications < 4 or ind.self_cited:
            lines.append(
                f"That figure rests on {ind.n_publications} publication(s) and must be "
                "quoted with that qualifier. It is a demonstration that the instrument "
                "can hold accounting constant across reconstructable studies, not an "
                "estimate of the divergence in the literature at large."
            )
    return lines
