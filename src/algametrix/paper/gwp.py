"""GWP analysis populations: published evidence versus model output.

The defect this replaces
------------------------
The previous ``gwp_harmonization.txt`` described "8 reproducible cases" and ran a
native-background / common-background comparison over all of them. Four of those
eight came from studies that never published a GWP at all: they are TEA scenarios
for which the engine *computes* a GWP. Calling that group "reproductions" turns
model output into apparent validation.

Three populations, kept apart
-----------------------------
``PUBLISHED GWP LITERATURE SET``
    every study with an actual published GWP endpoint. Descriptive only.
``GWP-REPRODUCED MATCHED SET``
    the subset of those the engine can execute. This, and only this, is
    validation. Calibrated and untuned cases are reported separately.
``FULL EXECUTABLE FOREGROUND SET``
    every scenario the engine can run, with each case labelled by its
    ``gwp_analysis_class``. Model-derived cases are extensions of the model, not
    evidence about it, and are labelled that way.

Every case reports gross GWP, the biogenic-carbon adjustment and net GWP, so a
net-negative result never appears without the gross value that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..library import Library, load_library
from ..models import Scenario
from ..scenario import run_scenario
from . import reconstructions
from .schema import StudyRecord
from .stats import Spread, compute_spread
from .studies import Cohort, Dataset

CLASS_UNTUNED = "published_gwp_untuned_reconstruction"
CLASS_COMPONENT_INFORMED = "published_gwp_component_informed_reconstruction"
CLASS_CALIBRATED = "published_gwp_calibrated_reconstruction"
CLASS_RANGE_ONLY = "published_gwp_range_only"
CLASS_MODEL_DERIVED = "model_derived_gwp_from_tea_scenario"
CLASS_LITERATURE_ONLY = "literature_point_only"

#: Classes that compare an engine GWP against a published one. They are NOT
#: equally strong: only :data:`CLASS_UNTUNED` is a reconstruction the source's
#: own reported endpoint did not feed, and the three are never pooled into one
#: reported range.
COMPARISON_CLASSES = (CLASS_UNTUNED, CLASS_COMPONENT_INFORMED, CLASS_CALIBRATED)


@dataclass(frozen=True)
class BackgroundProfile:
    """A declared LCIA background, applied identically to every scenario."""

    name: str
    elec_gwp: float
    heat_gwp: float
    source: str = ""

    def apply(self, scenario: Scenario) -> Scenario:
        lcia = replace(scenario.lcia, elec_gwp=self.elec_gwp, heat_gwp=self.heat_gwp)
        return replace(scenario, lcia=lcia)


def common_background(lib: Library | None = None) -> BackgroundProfile:
    lcia = (lib or load_library()).lcia
    return BackgroundProfile(
        name="AlgaMetrix common background",
        elec_gwp=lcia.elec_gwp,
        heat_gwp=lcia.heat_gwp,
        source="data/parameters.yaml -> lcia (the shipped defaults)",
    )


def classify(record: StudyRecord) -> str:
    """The GWP analysis class the *evidence* supports, independent of any label."""
    executable = record.is_executable
    if record.has_published_gwp:
        if not executable:
            return CLASS_LITERATURE_ONLY
        if record.evidence_class == "calibrated":
            return CLASS_CALIBRATED
        if record.evidence_class == "component_informed":
            return CLASS_COMPONENT_INFORMED
        if record.evidence_class == "range":
            return CLASS_RANGE_ONLY
        return CLASS_UNTUNED
    return CLASS_MODEL_DERIVED if executable else CLASS_LITERATURE_ONLY


def class_disagreements(dataset: Dataset) -> list[tuple[str, str, str]]:
    """``(study_id, declared_class, rule_class)`` wherever the label and rule differ."""
    out = []
    for r in dataset:
        rule = classify(r)
        declared = r.gwp_analysis_class
        if declared is not None and declared != rule:
            out.append((r.study_id, declared, rule))
    return out


@dataclass
class GwpCase:
    """One executable scenario evaluated under its native and the common background."""

    study_id: str
    label: str
    analysis_class: str
    published_gwp: float | None
    elec_kwh_per_kg: float
    native_elec_gwp: float
    common_elec_gwp: float
    native_gross: float
    native_adjustment: float
    native_net: float
    common_gross: float
    common_adjustment: float
    common_net: float
    carbon_mode: str
    notes: list[str] = field(default_factory=list)

    @property
    def background_is_identical(self) -> bool:
        return abs(self.native_elec_gwp - self.common_elec_gwp) < 1e-12

    @property
    def deviation_vs_published(self) -> float | None:
        if self.published_gwp in (None, 0):
            return None
        return self.native_net / self.published_gwp - 1.0


def evaluate_case(
    record: StudyRecord, background: BackgroundProfile, lib: Library | None = None
) -> GwpCase:
    lib = lib or load_library()
    scn = reconstructions.build(record.reconstruction_builder, lib)
    native = run_scenario(scn)
    common = run_scenario(background.apply(scn))

    case = GwpCase(
        study_id=record.study_id,
        label=record.cultivation_system or record.study_id,
        analysis_class=classify(record),
        published_gwp=record.reported_gwp,
        elec_kwh_per_kg=native.inventory.elec_kwh_per_kg,
        native_elec_gwp=scn.lcia.elec_gwp,
        common_elec_gwp=background.elec_gwp,
        native_gross=native.lca.gwp_gross_kg_co2eq_per_kg,
        native_adjustment=native.lca.biogenic_adjustment_kg_co2eq_per_kg,
        native_net=native.lca.gwp_kg_co2eq_per_kg,
        common_gross=common.lca.gwp_gross_kg_co2eq_per_kg,
        common_adjustment=common.lca.biogenic_adjustment_kg_co2eq_per_kg,
        common_net=common.lca.gwp_kg_co2eq_per_kg,
        carbon_mode=native.lca.carbon_accounting_mode,
    )
    if case.background_is_identical:
        case.notes.append(
            "native background == common background: this scenario carries no "
            "study-specific grid factor, so the native-to-common step is a no-op for it"
        )
    return case


@dataclass
class GwpPopulations:
    """The three populations plus their spreads."""

    published_literature: Cohort
    published_spread_net: Spread
    published_by_class: dict[str, list[str]]
    reproduced_cases: list[GwpCase]
    executable_cases: list[GwpCase]
    background: BackgroundProfile
    reproduced_spread_native_gross: Spread | None = None
    reproduced_spread_common_gross: Spread | None = None
    executable_spread_native_gross: Spread = None  # type: ignore[assignment]
    executable_spread_common_gross: Spread = None  # type: ignore[assignment]
    executable_spread_native_net: Spread = None    # type: ignore[assignment]
    executable_spread_common_net: Spread = None    # type: ignore[assignment]
    blocked: dict[str, str] = field(default_factory=dict)

    @property
    def n_published(self) -> int:
        return len(self.published_literature)

    @property
    def n_reproduced(self) -> int:
        return len(self.reproduced_cases)


def build_populations(
    dataset: Dataset,
    background: BackgroundProfile | None = None,
    lib: Library | None = None,
) -> GwpPopulations:
    lib = lib or load_library()
    bg = background or common_background(lib)

    published = Cohort(sorted((r for r in dataset if r.has_published_gwp),
                              key=lambda r: r.study_id))
    published_pairs = [
        (r.study_id, r.reported_gwp) for r in published if r.reported_gwp is not None
    ]
    by_class: dict[str, list[str]] = {}
    for r in published:
        by_class.setdefault(classify(r), []).append(r.study_id)

    executable_records = [r for r in dataset if r.is_executable]
    cases = [evaluate_case(r, bg, lib) for r in executable_records]
    reproduced = [c for c in cases if c.analysis_class in COMPARISON_CLASSES]

    blocked = {
        r.study_id: (
            f"published GWP {r.reported_gwp} but {r.gwp_reconstruction_status}: "
            + reconstructions.MISSING_SCENARIOS.get(r.study_id, "no builder registered")
        )
        for r in dataset
        if r.has_published_gwp and r.reconstructability_tier == "B" and not r.is_executable
    }

    pops = GwpPopulations(
        published_literature=published,
        published_spread_net=compute_spread(
            "published cradle-to-gate GWP as reported (each source's own convention)",
            published_pairs),
        published_by_class=by_class,
        reproduced_cases=reproduced,
        executable_cases=cases,
        background=bg,
        blocked=blocked,
    )

    if reproduced:
        pops.reproduced_spread_native_gross = compute_spread(
            "GWP-reproduced subset, native background, GROSS",
            [(c.study_id, c.native_gross) for c in reproduced])
        pops.reproduced_spread_common_gross = compute_spread(
            "GWP-reproduced subset, common background, GROSS",
            [(c.study_id, c.common_gross) for c in reproduced])

    pops.executable_spread_native_gross = compute_spread(
        "full executable foreground set, native background, GROSS",
        [(c.study_id, c.native_gross) for c in cases])
    pops.executable_spread_common_gross = compute_spread(
        "full executable foreground set, common background, GROSS",
        [(c.study_id, c.common_gross) for c in cases])
    pops.executable_spread_native_net = compute_spread(
        "full executable foreground set, native background, NET (declared convention)",
        [(c.study_id, c.native_net) for c in cases])
    pops.executable_spread_common_net = compute_spread(
        "full executable foreground set, common background, NET (declared convention)",
        [(c.study_id, c.common_net) for c in cases])
    return pops


def conclusion(p: GwpPopulations) -> list[str]:
    """Conditional statements only; nothing that model output cannot support."""
    lines: list[str] = []
    sp = p.published_spread_net
    lines.append(
        f"Published GWP evidence: {p.n_published} points, absolute range "
        f"{sp.minimum:,.4g} to {sp.maximum:,.4g} kg CO2-eq/kg "
        f"({sp.min_id} to {sp.max_id}). "
        + (f"Over the {sp.n - sp.n_nonpositive} strictly positive points the ratio is "
           f"{sp.max_min_ratio:,.4g}x." if sp.max_min_ratio else
           "No ratio is reported: the set contains a non-positive value.")
    )
    if sp.n_nonpositive:
        lines.append(
            f"{sp.n_nonpositive} published point(s) are <= 0. Each source's own "
            "biogenic-carbon convention is not recorded in this dataset, so those "
            "values are not comparable with the positive ones without it."
        )
    lines.append(
        f"Engine reproductions of a PUBLISHED GWP endpoint: {p.n_reproduced}. "
        + (f"Blocked by missing scenario definitions: {len(p.blocked)} "
           f"({', '.join(sorted(p.blocked))})." if p.blocked else "")
    )
    n_model = sum(1 for c in p.executable_cases if c.analysis_class == CLASS_MODEL_DERIVED)
    lines.append(
        f"The full executable foreground set has {len(p.executable_cases)} scenarios, of "
        f"which {n_model} are model-derived GWP from TEA studies with no published GWP "
        "endpoint. Those are model output, NOT validation."
    )
    identical = [c.study_id for c in p.executable_cases if c.background_is_identical]
    if len(identical) == len(p.executable_cases):
        lines.append(
            "Every executable scenario currently uses the common background, so the "
            "native-to-common comparison is a no-op and NO statement about the effect of "
            "harmonizing the electricity background can be made. The scenarios that "
            "carried study-specific grid factors are exactly the ones whose definitions "
            "are missing from the repository."
        )
    return lines
