"""Study-evidence schema: controlled vocabularies and the study record.

Every published estimate that enters a figure or a headline number in the paper
is one :class:`StudyRecord`. The record carries not only the reported value but
also *what kind of number it is* (economic endpoint, what the endpoint includes,
which currency and price year) and *how well it is documented* (reconstructability
tier, completeness score, what had to be assumed).

Two rules govern this module:

1. **Missing information is visible.** Unknown fields are ``None`` and print as
   ``unknown``; they are never silently defaulted to a convenient value.
2. **Vocabularies are closed.** A typo in ``economic_endpoint_type`` raises at
   load time instead of quietly creating a new category that then fails to match
   anything downstream.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, fields
from typing import Any

# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------

#: What economic quantity the source actually reports. These are **not**
#: interchangeable and must never be pooled into one spread without first being
#: recomputed to a common endpoint through the engine.
ECONOMIC_ENDPOINT_TYPES = (
    "production_cost",              # annual operating cost / annual production
    "operating_cost",               # OPEX only, capital charges excluded
    "minimum_selling_price",        # price giving NPV = 0 (generic product)
    "minimum_biomass_selling_price",
    "minimum_product_selling_price",
    "market_price",                 # observed price, not a cost model
    "unknown",
)

#: How the source treats co-products.
COPRODUCT_TREATMENTS = ("none", "revenue_credit", "allocation", "unknown")

#: Allocation convention where more than one saleable stream leaves the gate.
ALLOCATION_METHODS = ("none", "economic", "mass", "energy", "system_expansion", "unknown")

#: Maturity of the modelled plant. Drives whether a cost is an observation or a
#: projection; mixing ``commercial`` and ``nth_plant`` values silently is one of
#: the ways literature spreads get inflated.
PLANT_MATURITIES = (
    "laboratory",
    "pilot",
    "demonstration",
    "first_of_a_kind",
    "nth_plant",
    "commercial",
    "projected",
    "unknown",
)

#: Whether the figure is expressed in money of the day (nominal) or deflated.
NOMINAL_OR_REAL = ("nominal", "real", "unknown")

#: Operational definition of the reconstructability tiers. See :func:`tier_rule`.
TIERS = ("A", "B")

#: Validation protocol actually used for a Tier-B case.
VALIDATION_MODES = ("blind", "calibrated", "range", "none")

#: Whether the engine can currently execute the study's foreground scenario.
RECONSTRUCTION_STATUSES = (
    "reproduced",                    # a scenario builder exists and runs
    "missing_scenario_definition",   # declared Tier B but no builder in the repo
    "not_applicable",                # Tier A: never intended to be rebuilt
)

#: How a GWP number relates to published evidence. The distinction between a
#: reproduction of a *published* GWP and a GWP the engine computes for a scenario
#: whose source only published a cost is the difference between validation and
#: model output.
GWP_ANALYSIS_CLASSES = (
    "published_gwp_untuned_reconstruction",
    "published_gwp_calibrated_reconstruction",
    "published_gwp_range_only",
    "model_derived_gwp_from_tea_scenario",
    "literature_point_only",
)

#: Quality of the price-year / currency transformation actually achievable,
#: strongest first.
NORMALIZATION_QUALITIES = (
    "component_resolved",      # per-component indices applied to a PUBLISHED breakdown
    "partial_component",       # some components resolved, remainder first-order
    "engine_share_weighted",   # per-component indices, shares taken from the engine's
                               # own reconstructions because the source publishes none
    "whole_cost_first_order",  # one index applied to the whole unit cost
    "not_normalizable",        # currency or price year unknown
)

ELIGIBILITY_STATUSES = ("included", "excluded")

TROPHIC_MODES = ("phototrophic", "heterotrophic", "mixotrophic", "unknown")

STUDY_TYPES = ("tea", "lca", "tea_lca", "review", "market_report", "unknown")

ENVIRONMENTAL_ENDPOINT_TYPES = ("gwp_cradle_to_gate", "gwp_other_boundary", "none", "unknown")


class VocabularyError(ValueError):
    """Raised when a study record uses a value outside a closed vocabulary."""


def _check(value: Any, allowed: tuple[str, ...], field_name: str, study_id: str) -> Any:
    if value is None:
        return None
    if value not in allowed:
        raise VocabularyError(
            f"{study_id}: {field_name}={value!r} is not in the controlled vocabulary "
            f"{allowed}"
        )
    return value


# --------------------------------------------------------------------------
# Naming a source to a reader
# --------------------------------------------------------------------------

def compose_label(short_citation: str | None, scenario_label: str | None,
                  fallback: str) -> str:
    """``"Russo et al., 2022 — Heterotrophic"``: the citation, then which scenario.

    One rule, used by every figure and table, so the same source is named the
    same way wherever it appears. Without a citation the caller's ``fallback``
    (the internal id) shows through, which is the module's general rule: a gap
    is displayed, never filled in with something that reads like an answer.
    """
    if not short_citation:
        return fallback
    if scenario_label:
        return f"{short_citation} — {scenario_label}"
    return short_citation


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------

#: Fields whose presence is required before a study may enter *any* main result.
#: A number that cannot be attached to an identified source is not evidence.
PROVENANCE_FIELDS = ("study_id", "full_citation")

#: Stronger traceability: the exact location of the value inside the source
#: (table, figure, page). Not required to enter a result - almost nothing in the
#: present dataset records it - but its absence is reported study by study so the
#: gap is visible rather than assumed away.
TRACEABILITY_FIELDS = ("doi", "data_location_in_source")

#: Fields scored by :meth:`StudyRecord.completeness`. Declared explicitly so the
#: score is a documented rule rather than "how many attributes happen to be set".
COMPLETENESS_FIELDS = (
    "doi",
    "publication_year",
    "functional_unit",
    "system_boundary",
    "geographical_context",
    "technology_scale",
    "plant_maturity",
    "reported_currency",
    "reported_price_year",
    "economic_endpoint_type",
    "includes_depreciation",
    "includes_return_on_capital",
    "published_inventory_available",
    "published_capex_available",
    "published_opex_available",
    "allocation_method",
    "biogenic_carbon_convention",
    "data_location_in_source",
)


@dataclass
class StudyRecord:
    """One published estimate, with everything needed to audit how it is used.

    ``None`` means *unknown* throughout. Booleans are three-valued for the same
    reason: ``False`` asserts the source excludes something, ``None`` says nobody
    has checked.
    """

    # --- identity and provenance -----------------------------------------
    study_id: str
    full_citation: str
    #: Reader-facing citation key, e.g. ``"Russo et al., 2022"``. ``study_id`` is
    #: an internal join key and must never be the only thing a reader of a figure
    #: is given: a row labelled ``vazquez2022b_nas_10ha`` cannot be looked up in
    #: a reference list. Every label is checked back against ``full_citation`` by
    #: :func:`citation_problems`, so it identifies the same source it names.
    short_citation: str | None = None
    #: What distinguishes this record from the other records of the same source
    #: (``"N. oceanica, 10 ha"``). One paper often contributes several scenarios,
    #: and they are different numbers, not repeats of one.
    scenario_label: str | None = None
    doi: str | None = None
    publication_year: int | None = None
    search_source: str | None = None
    date_identified: str | None = None
    data_location_in_source: str | None = None
    #: ``True`` when an author of AlgaMetrix is an author of the source. A cohort
    #: whose conclusion rests on the authors' own work is weaker than one of the
    #: same size that does not, and the difference must be countable rather than
    #: buried in a prose disclosure.
    author_overlap_with_algametrix: bool | None = None
    notes: str = ""

    # --- eligibility ------------------------------------------------------
    eligibility_status: str | None = None
    eligibility_reason: str | None = None
    exclusion_reason: str | None = None

    # --- what was studied -------------------------------------------------
    study_type: str | None = None
    organism: str | None = None
    cultivation_system: str | None = None
    trophic_mode: str | None = None
    technology_scale: str | None = None
    plant_maturity: str | None = None
    geographical_context: str | None = None
    functional_unit: str | None = None
    system_boundary: str | None = None

    # --- the economic number ---------------------------------------------
    economic_endpoint_type: str | None = None
    includes_depreciation: bool | None = None
    includes_return_on_capital: bool | None = None
    discount_rate_embedded: float | None = None
    includes_working_capital: bool | None = None
    includes_startup_cost: bool | None = None
    includes_coproduct_credit: bool | None = None
    coproduct_treatment: str | None = None
    allocation_method: str | None = None
    reported_value: float | None = None
    reported_unit: str | None = None
    source_value: float | None = None
    source_unit: str | None = None
    reported_currency: str | None = None
    reported_price_year: int | None = None
    currency_basis: str | None = None
    nominal_or_real: str | None = None

    # --- the environmental number ----------------------------------------
    environmental_endpoint_type: str | None = None
    reported_gwp: float | None = None
    reported_gwp_unit: str | None = None
    reported_gwp_low: float | None = None
    reported_gwp_high: float | None = None
    #: The source's GWP *before* any biogenic-carbon adjustment, where it
    #: publishes one. A net figure alone cannot be compared across conventions;
    #: a gross figure can, because it is convention-free. Recording it turns a
    #: convention-dependent comparison into a convention-free one.
    reported_gwp_gross: float | None = None
    #: The source's own biogenic-carbon adjustment (<= 0), where published.
    reported_biogenic_adjustment: float | None = None
    #: Free text stating exactly how the reported figures were placed on the
    #: engine's basis (1 kg DRY biomass) when the source uses another one.
    gwp_basis_conversion: str | None = None
    biogenic_carbon_convention: str | None = None
    published_gwp_available: bool | None = None
    gwp_reconstruction_status: str | None = None
    foreground_scenario_executable: bool | None = None
    gwp_analysis_class: str | None = None

    # --- reconstructability ----------------------------------------------
    reconstructability_tier: str | None = None
    validation_mode: str | None = None
    reconstruction_status: str | None = None
    reconstruction_builder: str | None = None
    published_inventory_available: bool | None = None
    published_capex_available: bool | None = None
    published_opex_available: bool | None = None
    assumptions_required: list[str] = field(default_factory=list)
    cost_breakdown: dict[str, float] = field(default_factory=dict)

    # --- range checks (studies reported as an envelope, not a point) ------
    reported_low: float | None = None
    reported_high: float | None = None

    # --- open items -------------------------------------------------------
    todos: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        sid = self.study_id
        _check(self.economic_endpoint_type, ECONOMIC_ENDPOINT_TYPES, "economic_endpoint_type", sid)
        _check(self.coproduct_treatment, COPRODUCT_TREATMENTS, "coproduct_treatment", sid)
        _check(self.allocation_method, ALLOCATION_METHODS, "allocation_method", sid)
        _check(self.plant_maturity, PLANT_MATURITIES, "plant_maturity", sid)
        _check(self.nominal_or_real, NOMINAL_OR_REAL, "nominal_or_real", sid)
        _check(self.reconstructability_tier, TIERS, "reconstructability_tier", sid)
        _check(self.validation_mode, VALIDATION_MODES, "validation_mode", sid)
        _check(self.reconstruction_status, RECONSTRUCTION_STATUSES, "reconstruction_status", sid)
        _check(self.gwp_reconstruction_status, RECONSTRUCTION_STATUSES,
               "gwp_reconstruction_status", sid)
        _check(self.gwp_analysis_class, GWP_ANALYSIS_CLASSES, "gwp_analysis_class", sid)
        _check(self.eligibility_status, ELIGIBILITY_STATUSES, "eligibility_status", sid)
        _check(self.trophic_mode, TROPHIC_MODES, "trophic_mode", sid)
        _check(self.study_type, STUDY_TYPES, "study_type", sid)
        _check(self.environmental_endpoint_type, ENVIRONMENTAL_ENDPOINT_TYPES,
               "environmental_endpoint_type", sid)

        # ``source_value``/``source_unit`` default to the reported pair: the paper's
        # own number in the paper's own unit, before anything is done to it.
        if self.source_value is None:
            self.source_value = self.reported_value
        if self.source_unit is None:
            self.source_unit = self.reported_unit

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def display_label(self) -> str:
        """How this record is named to a reader: citation, then which scenario."""
        return compose_label(self.short_citation, self.scenario_label, self.study_id)

    @property
    def has_cost(self) -> bool:
        return self.reported_value is not None

    @property
    def has_published_gwp(self) -> bool:
        """A GWP endpoint really was published (point or range)."""
        return self.reported_gwp is not None or self.reported_gwp_low is not None

    @property
    def is_included(self) -> bool:
        """False once a record has been excluded, whatever else it carries.

        An excluded record is kept in the dataset with its reason rather than
        deleted, so the exclusion is countable and auditable, but it must not
        reach any population, comparison or statistic.
        """
        return self.eligibility_status != "excluded"

    @property
    def is_tier_b(self) -> bool:
        return self.reconstructability_tier == "B"

    @property
    def is_executable(self) -> bool:
        """The engine can run this record, AND the record is still included.

        Excluded records keep their scenario builder — the scenario is a valid
        engine configuration and is still used for software verification — but
        they must produce no comparison against a published value, because the
        published value is what was found unsound.
        """
        return (self.is_included
                and bool(self.reconstruction_builder)
                and self.reconstruction_status == "reproduced")

    @property
    def has_cost_breakdown(self) -> bool:
        """A CAPEX/OPEX split is recorded, so component-wise escalation is possible."""
        return bool(self.cost_breakdown)

    @property
    def normalizable(self) -> bool:
        return self.reported_currency is not None and self.reported_price_year is not None

    def completeness(self) -> float:
        """Fraction of :data:`COMPLETENESS_FIELDS` that are known (0-1).

        A declared rule over a declared field list, so two studies with the same
        score are documented to the same degree. It is not a quality judgement of
        the underlying science.
        """
        known = 0
        for name in COMPLETENESS_FIELDS:
            value = getattr(self, name, None)
            if value is None:
                continue
            if isinstance(value, str) and value == "unknown":
                continue
            known += 1
        return known / len(COMPLETENESS_FIELDS)

    def missing_provenance(self) -> list[str]:
        """Fields that must be present for the record to enter any main result."""
        return [f for f in PROVENANCE_FIELDS if not getattr(self, f, None)]

    def missing_traceability(self) -> list[str]:
        """Fields needed to point a reader at the exact value inside the source."""
        return [f for f in TRACEABILITY_FIELDS if not getattr(self, f, None)]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            out[f.name] = getattr(self, f.name)
        return out


# --------------------------------------------------------------------------
# Operational tier rule
# --------------------------------------------------------------------------

def tier_rule(record: StudyRecord) -> str:
    """Tier that the *declared evidence* supports, independent of any label.

    Tier B requires the study's foreground to be rebuildable: a published
    inventory **and** enough economic documentation to reconstruct the cost
    structure (CAPEX or OPEX), **and** a scenario builder present in this
    repository. Everything else is Tier A - a literature point that can enter
    descriptive range statistics but not a mechanistic reconstruction.

    Returns ``"A"`` or ``"B"``. Compare against
    :attr:`StudyRecord.reconstructability_tier` to catch drift between the label
    and the evidence.
    """
    inventory = bool(record.published_inventory_available)
    economics = bool(record.published_capex_available) or bool(record.published_opex_available)
    builder = bool(record.reconstruction_builder)
    return "B" if (inventory and economics and builder) else "A"


def _fold(text: str) -> str:
    """Case- and accent-insensitive form of ``text``.

    The dataset types author names without accents ("Vazquez-Romero"), while the
    label a reader should see carries them. Folding both sides lets the check
    below compare what the two strings *say* rather than how they are typed.
    """
    bare = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    return bare.casefold()


#: Tokens of a short citation with nothing to check back against the source.
_CITATION_STOPWORDS = frozenset({"et", "al", "and", "the", "of", "in", "nd"})


def citation_problems(records: list[StudyRecord]) -> list[tuple[str, str]]:
    """``(study_id, problem)`` for every label a reader could not act on.

    Three failures, each of which has a reader-visible consequence:

    1. **no label at all** - the figure falls back to the internal id, which
       appears in no reference list;
    2. **a label that names two different records** - the reader cannot tell
       which row is which, and two scenarios of one paper are not one number;
    3. **a label that has drifted from its source** - every word and the year of
       ``short_citation`` must occur in ``full_citation``, so a label cannot
       quietly come to name a paper the record was not taken from.

    Returns an empty list when every record is citable. This is the guard that
    makes the labels evidence rather than decoration.
    """
    problems: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for r in records:
        if not r.short_citation:
            problems.append((r.study_id, "no short_citation: a figure would show the "
                                         "internal id, which is in no reference list"))
        else:
            folded_source = _fold(r.full_citation)
            for token in re.findall(r"[a-z0-9]+", _fold(r.short_citation)):
                if token in _CITATION_STOPWORDS or len(token) < 3:
                    continue
                year = re.fullmatch(r"(\d{4})[a-z]?", token)
                # A "2022b" suffix disambiguates two papers of one author-year:
                # it is a property of the reference list, not of the source.
                needle = year.group(1) if year else token
                if year and needle == str(r.publication_year):
                    continue        # the year is evidence in its own field
                if needle not in folded_source:
                    problems.append((
                        r.study_id,
                        f"short_citation {r.short_citation!r} says {needle!r}, which does "
                        f"not appear in full_citation {r.full_citation!r}"))
        label = r.display_label
        if label in seen:
            problems.append((r.study_id, f"label {label!r} already names {seen[label]}; "
                                         "add a scenario_label to tell them apart"))
        else:
            seen[label] = r.study_id
    return problems


def tier_disagreements(records: list[StudyRecord]) -> list[tuple[str, str, str]]:
    """``(study_id, declared_tier, rule_tier)`` for every record where they differ."""
    out = []
    for r in records:
        rule = tier_rule(r)
        if r.reconstructability_tier != rule:
            out.append((r.study_id, r.reconstructability_tier or "unknown", rule))
    return out


def fmt(value: Any) -> str:
    """Render a field for a text report: ``None`` is ``unknown``, never blank."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value) if value else "none"
    return str(value)
