"""Economic-endpoint classification and eligibility for the primary cost spread.

The failure this module prevents
--------------------------------
A production cost, an operating cost, a minimum selling price and a minimum
biomass selling price are four different quantities. An MBSP embeds a required
return on capital by construction; a production cost as defined in AlgaMetrix
does not. Pooling them into one "spread of published costs" inflates the spread
by an amount that has nothing to do with the technology.

In this dataset that is not hypothetical: the study defining the *minimum* of the
legacy 17-study spread (``nrel_davis2016``, 0.74 USD/kg) reports an MBSP, not a
production cost. The headline max/min ratio therefore straddles two different
economic definitions.

The primary endpoint
--------------------
:data:`PRIMARY_ENDPOINT` is the AlgaMetrix production-cost definition already
implemented in :mod:`algametrix.tea`: annual operating cost divided by
annual production, **including** straight-line depreciation, **excluding** any
return on capital. It is declared here once and printed into every report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import StudyRecord
from .studies import Cohort

#: The one endpoint the primary cost comparison is run on.
PRIMARY_ENDPOINT = "production_cost"

PRIMARY_ENDPOINT_DEFINITION = (
    "production cost = annual operating cost / annual production, including "
    "straight-line depreciation, maintenance and insurance, and EXCLUDING any "
    "return on capital (that sits in NPV/IRR/MEPP). Functional unit: 1 kg dry biomass."
)

#: Functional unit the primary comparison is defined on. Studies reporting a cost
#: per kg of oil, pigment or protein isolate are a different quantity entirely.
PRIMARY_FUNCTIONAL_UNIT = "1 kg dry biomass"

#: What the cohort may be called. NOT "homogeneous".
#:
#: Screening on ``economic_endpoint_type`` and ``functional_unit`` makes the
#: cohort homogeneous in its *declared label*. It does not make the underlying
#: quantities the same: whether a source includes depreciation, whether it
#: embeds a return on capital, whether the cost is net of co-product credits,
#: which allocation rule produced it and where the system boundary sits are all
#: unknown for most of these records - and each of them moves a unit cost by more
#: than the differences the spread is used to argue about. Calling the result
#: homogeneous would assert something nobody has checked.
PRIMARY_COHORT_LABEL = "studies nominally classified as biomass production-cost estimates"

#: Attributes that decide whether two numbers both labelled "production cost"
#: are in fact the same quantity. Reported study by study, never aggregated away.
ENDPOINT_DEFINITION_FIELDS = (
    "includes_depreciation",
    "includes_return_on_capital",
    "includes_coproduct_credit",
    "coproduct_treatment",
    "allocation_method",
    "system_boundary",
)


class MixedEndpointError(ValueError):
    """Raised when values of different economic endpoints would be pooled."""


@dataclass
class EndpointAudit:
    """Per-study classification and eligibility decision."""

    study_id: str
    source_metric: str
    classification: str
    functional_unit: str
    eligible: bool
    exclusion_reason: str | None = None
    caveats: list[str] = field(default_factory=list)


def classify(record: StudyRecord) -> EndpointAudit:
    """Decide whether ``record`` may enter the primary production-cost spread."""
    source_metric = record.reported_unit or "unknown"
    classification = record.economic_endpoint_type or "unknown"
    fu = record.functional_unit or "unknown"
    caveats: list[str] = []

    if record.eligibility_status == "excluded":
        return EndpointAudit(
            record.study_id, source_metric, classification, fu, False,
            record.exclusion_reason or "excluded by the dataset's own eligibility decision",
        )

    if record.reported_value is None:
        return EndpointAudit(record.study_id, source_metric, classification, fu,
                             False, "no economic value reported")

    if classification == "unknown":
        return EndpointAudit(
            record.study_id, source_metric, classification, fu, False,
            "economic endpoint type unknown: cannot be pooled with a declared endpoint",
        )

    if classification != PRIMARY_ENDPOINT:
        return EndpointAudit(
            record.study_id, source_metric, classification, fu, False,
            f"endpoint is '{classification}', not '{PRIMARY_ENDPOINT}'; retained in the "
            "dataset but excluded from the primary production-cost spread because the "
            "underlying data are insufficient to recompute it to the primary endpoint",
        )

    if fu != PRIMARY_FUNCTIONAL_UNIT:
        return EndpointAudit(
            record.study_id, source_metric, classification, fu, False,
            f"functional unit is '{fu}', not '{PRIMARY_FUNCTIONAL_UNIT}'",
        )

    if not record.normalizable:
        missing = []
        if record.reported_currency is None:
            missing.append("currency")
        if record.reported_price_year is None:
            missing.append("price year")
        return EndpointAudit(
            record.study_id, source_metric, classification, fu, False,
            "not normalizable: " + " and ".join(missing) + " unknown",
        )

    # Eligible, but record what remains unverified about the endpoint definition.
    if record.includes_depreciation is None:
        caveats.append("includes_depreciation unknown")
    if record.includes_return_on_capital is None:
        caveats.append("includes_return_on_capital unknown")
    if record.includes_coproduct_credit is None:
        caveats.append("includes_coproduct_credit unknown")
    if record.coproduct_treatment in (None, "unknown"):
        caveats.append("coproduct treatment unknown")

    return EndpointAudit(record.study_id, source_metric, classification, fu, True,
                         None, caveats)


def audit_all(records: list[StudyRecord]) -> list[EndpointAudit]:
    return [classify(r) for r in sorted(records, key=lambda r: r.study_id)]


def primary_cost_cohort(records: list[StudyRecord]) -> Cohort:
    """Every study eligible for the primary production-cost comparison."""
    eligible = {a.study_id for a in audit_all(records) if a.eligible}
    return Cohort(sorted((r for r in records if r.study_id in eligible),
                         key=lambda r: r.study_id))


def assert_single_endpoint(records: list[StudyRecord], expected: str = PRIMARY_ENDPOINT) -> None:
    """Guard: raise unless every record carries ``expected`` as its endpoint.

    Called before any pooled statistic is computed, so that a dataset edit that
    lets an MSP into the cost cohort fails loudly instead of shifting a headline
    number.
    """
    offenders = {
        r.study_id: (r.economic_endpoint_type or "unknown")
        for r in records
        if r.economic_endpoint_type != expected
    }
    if offenders:
        raise MixedEndpointError(
            f"cohort mixes economic endpoints; expected all '{expected}', found: "
            + ", ".join(f"{k}={v}" for k, v in sorted(offenders.items()))
        )


def assert_single_functional_unit(
    records: list[StudyRecord], expected: str = PRIMARY_FUNCTIONAL_UNIT
) -> None:
    offenders = {
        r.study_id: (r.functional_unit or "unknown")
        for r in records
        if r.functional_unit != expected
    }
    if offenders:
        raise MixedEndpointError(
            f"cohort mixes functional units; expected all '{expected}', found: "
            + ", ".join(f"{k}={v}" for k, v in sorted(offenders.items()))
        )


@dataclass
class DefinitionAudit:
    """How far the cohort's endpoint homogeneity is verified rather than declared."""

    n: int
    #: field -> number of cohort members for which it is known
    known: dict[str, int] = field(default_factory=dict)
    #: study_id -> the fields still unknown for that study
    unknown_by_study: dict[str, list[str]] = field(default_factory=dict)

    @property
    def fully_specified(self) -> list[str]:
        return sorted(sid for sid, missing in self.unknown_by_study.items() if not missing)

    @property
    def verified(self) -> bool:
        """True only when every member has every definition attribute recorded."""
        return self.n > 0 and len(self.fully_specified) == self.n

    def statement(self) -> list[str]:
        """The sentence the manuscript is allowed to make about this cohort."""
        if self.n == 0:
            return ["The cohort is empty; no homogeneity statement applies."]
        if self.verified:
            return [
                f"All {self.n} members have every endpoint-definition attribute recorded "
                f"({', '.join(ENDPOINT_DEFINITION_FIELDS)}), so the cohort is homogeneous "
                "in the endpoint definition and not only in its label."
            ]
        worst = sorted(self.known.items(), key=lambda kv: kv[1])
        detail = "; ".join(f"{f}: known for {k}/{self.n}" for f, k in worst)
        return [
            f"This cohort is homogeneous in its DECLARED endpoint and functional unit "
            f"only. Of its {self.n} members, {len(self.fully_specified)} have every "
            f"endpoint-definition attribute recorded. {detail}.",
            "It must therefore be described as "
            f"'{PRIMARY_COHORT_LABEL}', not as a homogeneous production-cost cohort: "
            "depreciation treatment, return on capital, co-product credits, allocation "
            "and system boundary each move a unit cost by more than the differences this "
            "spread is used to discuss, and they are unverified here.",
        ]


def definition_audit(records: list[StudyRecord]) -> DefinitionAudit:
    """Per-study record of which endpoint-definition attributes are still unknown.

    The counterpart of :func:`classify`: eligibility asks whether a study may be
    pooled at all, this asks how much is actually known about what was pooled.
    """
    cohort = list(primary_cost_cohort(records))
    audit = DefinitionAudit(n=len(cohort), known={f: 0 for f in ENDPOINT_DEFINITION_FIELDS})
    for rec in cohort:
        missing: list[str] = []
        for f in ENDPOINT_DEFINITION_FIELDS:
            value = getattr(rec, f, None)
            if value is None or (isinstance(value, str) and value == "unknown"):
                missing.append(f)
            else:
                audit.known[f] += 1
        audit.unknown_by_study[rec.study_id] = missing
    return audit


def endpoint_breakdown(records: list[StudyRecord]) -> dict[str, list[str]]:
    """Study ids grouped by declared economic endpoint, for separate statistics."""
    out: dict[str, list[str]] = {}
    for r in sorted(records, key=lambda r: r.study_id):
        if r.reported_value is None:
            continue
        out.setdefault(r.economic_endpoint_type or "unknown", []).append(r.study_id)
    return out
