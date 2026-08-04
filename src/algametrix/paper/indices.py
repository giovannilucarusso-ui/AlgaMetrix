"""Currency and price-year normalization, component by component where possible.

Why this module exists
----------------------
The previous method escalated the *whole* unit production cost with CEPCI. CEPCI
is a plant and equipment cost index. Labour, electricity, heat, nutrients and
general overheads do not move with it - over 2020-2022 energy in particular moved
several times further. Applying one plant-cost index to every expenditure
category is therefore a modelling choice, not a neutral correction, and it must
be labelled as one.

What it does
------------
* Splits a study's cost into normalization *components* when the source publishes
  a breakdown, and escalates each with its own index class.
* Falls back to a first-order whole-cost escalation when no breakdown exists -
  but reports it under a distinct quality flag and brackets it with an explicit
  interval instead of hiding a single assumption inside a point estimate.
* Emits a full audit trail: which index, which base and target year, which index
  values, and the resulting factor, for every transformation.

Nothing here hard-codes an index value; all of them come from
``data/studies/indices.yaml`` together with their provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .basis import MONETARY_ECONOMICS_FIELDS, PriceBasis
from .schema import StudyRecord
from .studies import DEFAULT_STUDY_DIR

#: Expenditure components a cost can be split into for escalation. The names are
#: the keys expected in ``StudyRecord.cost_breakdown`` (shares of the unit cost,
#: which must sum to 1).
COMPONENTS = (
    "capital_annualised",
    "labour",
    "electricity",
    "heat_fuel",
    "nutrients",
    "maintenance",
    "overhead",
    "other_opex",
)

#: Which index class each component is escalated with.
COMPONENT_CLASS: dict[str, str] = {
    "capital_annualised": "capital",
    "maintenance": "capital",
    "labour": "labour",
    "electricity": "energy",
    "heat_fuel": "energy",
    "nutrients": "general_opex",
    "overhead": "general_opex",
    "other_opex": "general_opex",
}


class MissingIndexError(KeyError):
    """Raised when a transformation needs an index value that is not available."""


@dataclass
class PriceIndex:
    """One index series plus everything needed to audit its use."""

    index_name: str
    normalization_class: str
    source: str | None
    retrieval_date: str | None
    provenance: str
    values_by_year: dict[int, float] = field(default_factory=dict)
    description: str = ""
    notes: str = ""
    todos: list[str] = field(default_factory=list)
    #: Span beyond which the index's own documentation says it should not be used.
    #: CEPCI carries 5 years; exceeding it is flagged, not silently allowed.
    max_recommended_span_years: int | None = None

    @property
    def available(self) -> bool:
        return bool(self.values_by_year)

    def factor(self, base_year: int, target_year: int) -> "IndexApplication":
        if base_year not in self.values_by_year or target_year not in self.values_by_year:
            missing = [y for y in (base_year, target_year) if y not in self.values_by_year]
            raise MissingIndexError(
                f"{self.index_name}: no value for year(s) {missing} "
                f"(have {sorted(self.values_by_year)})"
            )
        vb = self.values_by_year[base_year]
        vt = self.values_by_year[target_year]
        span = abs(target_year - base_year)
        over = (self.max_recommended_span_years is not None
                and span > self.max_recommended_span_years)
        return IndexApplication(
            index_name=self.index_name,
            normalization_class=self.normalization_class,
            base_year=base_year,
            target_year=target_year,
            value_base=vb,
            value_target=vt,
            factor=vt / vb,
            source=self.source,
            retrieval_date=self.retrieval_date,
            provenance=self.provenance,
            exceeds_recommended_span=over,
            recommended_span_years=self.max_recommended_span_years,
        )


@dataclass
class IndexApplication:
    """A single, auditable index transformation."""

    index_name: str
    normalization_class: str
    base_year: int
    target_year: int
    value_base: float
    value_target: float
    factor: float
    source: str | None
    retrieval_date: str | None
    provenance: str
    exceeds_recommended_span: bool = False
    recommended_span_years: int | None = None

    def __str__(self) -> str:  # pragma: no cover - formatting only
        warn = ""
        if self.exceeds_recommended_span:
            warn = (f"  !! span {abs(self.target_year - self.base_year)} yr exceeds the "
                    f"{self.recommended_span_years}-yr window this index is documented for")
        return (
            f"{self.index_name} {self.base_year}->{self.target_year}: "
            f"{self.value_base:g} -> {self.value_target:g} (x{self.factor:.4f}; "
            f"provenance={self.provenance}){warn}"
        )


@dataclass
class CurrencyConversion:
    """A single, auditable currency transformation."""

    from_currency: str
    to_currency: str
    rate: float
    year_specific: bool
    source: str | None
    retrieval_date: str | None
    provenance: str
    year: int | None = None

    def __str__(self) -> str:  # pragma: no cover - formatting only
        y = (f"year-specific, {self.year}" if self.year_specific
             else "FLAT (year-independent)")
        return (
            f"{self.from_currency}->{self.to_currency} x{self.rate:g} [{y}; "
            f"provenance={self.provenance}]"
        )


@dataclass
class Registry:
    """All indices and currency rates, loaded from ``indices.yaml``."""

    indices: dict[str, PriceIndex]
    rates: list[dict]
    common_currency: str
    bounding: dict

    def by_class(self, normalization_class: str) -> PriceIndex | None:
        for idx in self.indices.values():
            if idx.normalization_class == normalization_class:
                return idx
        return None

    def conversion(
        self, from_currency: str, to_currency: str, year: int | None = None,
        legacy_flat: bool = False,
    ) -> CurrencyConversion:
        """Rate for ``year``. Falls back to the flat legacy rate only on request.

        A pair declared in one direction is usable in both: the reverse is the
        reciprocal of the same published rate, so inverting it introduces no new
        assumption and avoids having to maintain two copies of one ECB series
        that could drift apart.
        """
        if from_currency == to_currency:
            return CurrencyConversion(from_currency, to_currency, 1.0, True,
                                      "identity", None, "identity", year)
        direct = self._direct(from_currency, to_currency, year, legacy_flat)
        if direct is not None:
            return direct
        reverse = self._direct(to_currency, from_currency, year, legacy_flat)
        if reverse is not None:
            return CurrencyConversion(
                from_currency, to_currency, 1.0 / reverse.rate, reverse.year_specific,
                reverse.source, reverse.retrieval_date,
                f"{reverse.provenance} (inverted)", year,
            )
        raise MissingIndexError(f"no conversion {from_currency}->{to_currency}")

    def _direct(
        self, from_currency: str, to_currency: str, year: int | None, legacy_flat: bool
    ) -> CurrencyConversion | None:
        for r in self.rates:
            if r["from_currency"] != from_currency or r["to_currency"] != to_currency:
                continue
            if legacy_flat and r.get("legacy_flat_rate") is not None:
                return CurrencyConversion(
                    from_currency, to_currency, float(r["legacy_flat_rate"]), False,
                    r.get("legacy_flat_rate_source"), None,
                    "back_calculated_from_legacy_results", year,
                )
            by_year = {int(k): float(v) for k, v in (r.get("rates_by_year") or {}).items()}
            if by_year:
                if year is None:
                    raise MissingIndexError(
                        f"{from_currency}->{to_currency} is year-specific but no price "
                        "year was supplied"
                    )
                if year not in by_year:
                    raise MissingIndexError(
                        f"{from_currency}->{to_currency}: no rate for {year} "
                        f"(have {sorted(by_year)})"
                    )
                return CurrencyConversion(
                    from_currency, to_currency, by_year[year], True,
                    r.get("source"), r.get("retrieval_date"),
                    r.get("provenance", "unknown"), year,
                )
            if r.get("rate") is not None:
                return CurrencyConversion(
                    from_currency, to_currency, float(r["rate"]),
                    bool(r.get("year_specific", False)), r.get("source"),
                    r.get("retrieval_date"), r.get("provenance", "unknown"), year,
                )
        return None


def load_registry(path: Path | str | None = None) -> Registry:
    base = Path(path) if path is not None else DEFAULT_STUDY_DIR / "indices.yaml"
    with base.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    indices = {}
    for d in raw.get("indices", []):
        idx = PriceIndex(
            index_name=d["index_name"],
            normalization_class=d["normalization_class"],
            source=d.get("source"),
            retrieval_date=d.get("retrieval_date"),
            provenance=d.get("provenance", "unknown"),
            values_by_year={int(k): float(v) for k, v in (d.get("values_by_year") or {}).items()},
            description=d.get("description", ""),
            notes=d.get("notes", ""),
            todos=list(d.get("todos") or []),
            max_recommended_span_years=d.get("max_recommended_span_years"),
        )
        indices[idx.index_name] = idx
    cur = raw.get("currency", {}) or {}
    return Registry(
        indices=indices,
        rates=list(cur.get("rates") or []),
        common_currency=cur.get("common_currency", "EUR"),
        bounding=raw.get("bounding", {}) or {},
    )


@lru_cache(maxsize=1)
def default_registry() -> Registry:
    return load_registry()


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

@dataclass
class Normalization:
    """The result of moving one reported value to the common currency and year."""

    study_id: str
    source_value: float | None
    source_currency: str | None
    source_price_year: int | None
    target_currency: str
    target_price_year: int
    method: str                     # human description of the route taken
    quality: str                    # see schema.NORMALIZATION_QUALITIES
    value: float | None = None      # point estimate in target currency/year
    lower: float | None = None      # bounding interval, when the point is assumption-driven
    upper: float | None = None
    currency_step: CurrencyConversion | None = None
    index_steps: list[IndexApplication] = field(default_factory=list)
    component_shares: dict[str, float] = field(default_factory=dict)
    #: What the previous method (one plant-cost index on the whole cost) would give,
    #: kept for comparison so the change of method is visible rather than silent.
    legacy_whole_cost_value: float | None = None
    notes: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None

    def audit_lines(self, indent: str = "      ") -> list[str]:
        out = [f"{indent}method  : {self.method}",
               f"{indent}quality : {self.quality}"]
        if self.currency_step is not None:
            out.append(f"{indent}currency: {self.currency_step}")
        for step in self.index_steps:
            out.append(f"{indent}index   : {step}")
        if self.component_shares:
            shares = ", ".join(f"{k}={v:.3f}" for k, v in sorted(self.component_shares.items()))
            out.append(f"{indent}shares  : {shares}")
        if self.lower is not None and self.upper is not None:
            out.append(f"{indent}bounds  : {self.lower:,.4g} - {self.upper:,.4g} "
                       f"(point {self.value:,.4g})")
        for n in self.notes:
            out.append(f"{indent}note    : {n}")
        for t in self.todos:
            out.append(f"{indent}TODO    : {t}")
        return out


@dataclass
class ShareSet:
    """Cost-category shares observed across the engine's own reconstructions.

    Used when a source publishes no CAPEX/OPEX breakdown: rather than assume one
    split, the analysis is run over the whole observed set and reported as an
    interval. ``per_builder`` maps a builder name to a share vector over the
    normalization classes; ``median`` is the element-wise median, renormalised.
    """

    per_builder: dict[str, dict[str, float]] = field(default_factory=dict)
    median: dict[str, float] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.per_builder)

    def as_lines(self, indent: str = "    ") -> list[str]:
        out = [f"{indent}median share vector: "
               + ", ".join(f"{k}={v:.3f}" for k, v in sorted(self.median.items()))]
        for name, vec in sorted(self.per_builder.items()):
            out.append(f"{indent}  {name:24s} "
                       + ", ".join(f"{k}={v:.3f}" for k, v in sorted(vec.items())))
        return out


def normalize(
    record: StudyRecord,
    target_price_year: int,
    registry: Registry | None = None,
    shares: "ShareSet | None" = None,
) -> Normalization:
    """Move ``record``'s reported value to the common currency and ``target_price_year``.

    Route selection:

    ``not_normalizable``
        currency or price year unknown -> no value is produced.
    ``component_resolved`` / ``partial_component``
        the record carries a ``cost_breakdown``; each component is escalated with
        its own index class. Components whose index is unavailable fall back to
        the capital index and the result is downgraded to ``partial_component``.
    ``engine_share_weighted``
        no published breakdown, but the engine's own reconstructions have one.
        Each normalization class is escalated with its own index and weighted by
        the median share observed across those reconstructions; the interval over
        the individual share vectors is reported, and so is the legacy
        CEPCI-on-everything value for comparison.
    ``whole_cost_first_order``
        no breakdown and no share set: one index on the entire cost. The fallback
        of last resort.
    """
    reg = registry or default_registry()
    n = Normalization(
        study_id=record.study_id,
        source_value=record.source_value,
        source_currency=record.reported_currency,
        source_price_year=record.reported_price_year,
        target_currency=reg.common_currency,
        target_price_year=target_price_year,
        method="",
        quality="not_normalizable",
    )

    if record.source_value is None:
        n.method = "no reported value"
        n.notes.append("record carries no economic value")
        return n
    if record.reported_currency is None or record.reported_price_year is None:
        n.method = "blocked: currency and/or price year unknown"
        missing = []
        if record.reported_currency is None:
            missing.append("reported_currency")
        if record.reported_price_year is None:
            missing.append("reported_price_year")
        n.notes.append("missing " + ", ".join(missing))
        n.todos.append(f"extract {', '.join(missing)} from the source")
        return n

    # --- currency first, at the source price year -------------------------
    conv = reg.conversion(record.reported_currency, reg.common_currency,
                          year=record.reported_price_year)
    n.currency_step = conv
    if not conv.year_specific and conv.rate != 1.0:
        n.notes.append(
            "flat exchange rate applied irrespective of price year: part of the "
            "reported price-year effect is an unseparated exchange-rate effect"
        )
    in_common_currency = record.source_value * conv.rate

    capital = reg.by_class("capital")
    if capital is None or not capital.available:
        n.method = "blocked: no capital index available"
        n.todos.append("supply a plant-cost index series in data/studies/indices.yaml")
        return n

    # --- component-wise route --------------------------------------------
    if record.has_cost_breakdown:
        shares = dict(record.cost_breakdown)
        total = sum(shares.values())
        if abs(total - 1.0) > 1e-6:
            n.notes.append(f"cost_breakdown shares sum to {total:g}; renormalised to 1")
            shares = {k: v / total for k, v in shares.items()}
        n.component_shares = shares

        resolved = 0.0
        factor_sum = 0.0
        fell_back = []
        for comp, share in shares.items():
            cls = COMPONENT_CLASS.get(comp, "general_opex")
            idx = reg.by_class(cls)
            if idx is not None and idx.available:
                app = idx.factor(record.reported_price_year, target_price_year)
                resolved += share
            else:
                app = capital.factor(record.reported_price_year, target_price_year)
                fell_back.append(comp)
            n.index_steps.append(app)
            factor_sum += share * app.factor

        n.value = in_common_currency * factor_sum
        if fell_back:
            n.quality = "partial_component"
            n.method = (
                f"component-wise escalation; {len(fell_back)} component(s) "
                f"({', '.join(sorted(fell_back))}) fell back to the capital index "
                "because no index of their own class is available"
            )
            n.todos.append(
                "supply indices for " + ", ".join(sorted({COMPONENT_CLASS[c] for c in fell_back}))
            )
        else:
            n.quality = "component_resolved"
            n.method = "component-wise escalation with one index class per component"
        n.notes.append(f"share of cost escalated with its own index class: {resolved:.0%}")
        return n

    # --- no published breakdown ------------------------------------------
    legacy = capital.factor(record.reported_price_year, target_price_year)
    n.legacy_whole_cost_value = in_common_currency * legacy.factor
    if legacy.exceeds_recommended_span:
        n.notes.append(
            f"{legacy.index_name} is applied over {abs(target_price_year - record.reported_price_year)} "
            f"years, beyond the ~{legacy.recommended_span_years}-year window it is "
            "documented for"
        )

    if shares is not None and shares.available:
        # Escalate each normalization class with its own index, weight by the
        # shares the engine's reconstructions actually exhibit.
        class_factors: dict[str, float] = {}
        for cls in sorted({c for vec in shares.per_builder.values() for c in vec}):
            idx = reg.by_class(cls)
            if idx is None or not idx.available:
                idx = capital
            app = idx.factor(record.reported_price_year, target_price_year)
            n.index_steps.append(app)
            class_factors[cls] = app.factor

        def weighted(vec: dict[str, float]) -> float:
            return sum(share * class_factors.get(cls, legacy.factor)
                       for cls, share in vec.items())

        point_factor = weighted(shares.median)
        realised = [weighted(v) for v in shares.per_builder.values()]
        n.quality = "engine_share_weighted"
        n.method = (
            "per-class escalation (capital -> plant-cost index, labour -> labour cost "
            "index, energy -> industrial electricity price, remainder -> CPI) weighted "
            "by the median cost-category shares of the engine's own reconstructions; "
            "the source publishes no breakdown"
        )
        n.value = in_common_currency * point_factor
        n.component_shares = dict(shares.median)
        n.lower = in_common_currency * min(realised)
        n.upper = in_common_currency * max(realised)
        n.notes.append(
            "the interval spans the share vectors of the individual reconstructions; "
            "it describes how much the result depends on the cost split, not on the indices"
        )
        n.notes.append(
            f"legacy method (one plant-cost index on 100% of the cost) would give "
            f"{n.legacy_whole_cost_value:,.4g}, a factor of "
            f"{n.legacy_whole_cost_value / n.value:.3f} on this point estimate"
        )
        n.todos.append(
            "extract the source's own CAPEX/OPEX breakdown to replace the engine-derived "
            "shares and reach component_resolved"
        )
        return n

    n.index_steps.append(legacy)
    n.quality = "whole_cost_first_order"
    n.method = (
        f"first-order: the single index {legacy.index_name} applied to the entire unit "
        "cost (no published breakdown and no share set supplied)"
    )
    n.value = n.legacy_whole_cost_value
    n.todos.append(
        "extract the source's cost breakdown to upgrade this study to component_resolved"
    )
    return n


# --------------------------------------------------------------------------
# Moving a value between two price bases
# --------------------------------------------------------------------------
# :func:`normalize` moves a *study record* to the common currency and year. The
# machinery below moves an *arbitrary amount* - typically an engine output, which
# is denominated in the basis of the price set it was run with - between any two
# bases. Both share the same registry, the same year-specific exchange rates and
# the same per-class escalation, so a value normalized by either route is
# comparable with a value normalized by the other.

#: Quality of a basis transformation, strongest first.
TRANSFER_QUALITIES = (
    "identity",                       # the two bases are the same resolved basis
    "currency_only",                  # same price year, currencies differ
    "price_year_only",                # same currency, price years differ
    "currency_and_price_year",        # both differ
    "currency_aligned_year_unknown",  # currencies match, at least one year unknown
    "blocked",                        # no defensible transformation exists
)


@dataclass
class BasisTransfer:
    """One amount moved from one price basis to another, with its audit trail."""

    amount_in: float
    from_basis: PriceBasis
    to_basis: PriceBasis
    quality: str
    amount_out: float | None = None
    currency_step: CurrencyConversion | None = None
    index_steps: list[IndexApplication] = field(default_factory=list)
    escalation_factor: float | None = None
    blocked_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.amount_out is not None

    @property
    def is_identity(self) -> bool:
        return self.quality == "identity"

    def audit_lines(self, indent: str = "      ") -> list[str]:
        out = [f"{indent}transfer: {self.from_basis.label} -> {self.to_basis.label} "
               f"[{self.quality}]"]
        if self.blocked_reason:
            out.append(f"{indent}blocked : {self.blocked_reason}")
        if self.currency_step is not None:
            out.append(f"{indent}currency: {self.currency_step}")
        for step in self.index_steps:
            out.append(f"{indent}index   : {step}")
        if self.escalation_factor is not None and abs(self.escalation_factor - 1.0) > 1e-12:
            out.append(f"{indent}escal.  : x{self.escalation_factor:.4f} "
                       "(share-weighted over the normalization classes)")
        for n in self.notes:
            out.append(f"{indent}note    : {n}")
        return out


def escalation(
    base_year: int,
    target_year: int,
    registry: Registry,
    shares: "ShareSet | None" = None,
) -> tuple[float, list[IndexApplication], str]:
    """Price-year escalation factor between two years.

    With a :class:`ShareSet`, each normalization class is escalated with its own
    index and the factors are weighted by the median observed share - the same
    per-class treatment :func:`normalize` applies, and for the same reason: a
    plant-cost index does not describe labour, energy or consumables. Without one,
    the capital index is applied to the whole amount and the method string says so.
    """
    if base_year == target_year:
        return 1.0, [], "identity (same price year)"

    capital = registry.by_class("capital")
    if capital is None or not capital.available:
        raise MissingIndexError("no capital index available for escalation")

    if shares is not None and shares.available:
        steps: list[IndexApplication] = []
        factor = 0.0
        for cls, share in sorted(shares.median.items()):
            idx = registry.by_class(cls)
            if idx is None or not idx.available:
                idx = capital
            app = idx.factor(base_year, target_year)
            steps.append(app)
            factor += share * app.factor
        return factor, steps, ("per-class escalation weighted by the median cost-category "
                               "shares of the engine's reconstructions")

    app = capital.factor(base_year, target_year)
    return app.factor, [app], f"first-order: {app.index_name} on the whole amount"


def transfer(
    amount: float,
    from_basis: PriceBasis,
    to_basis: PriceBasis,
    registry: Registry | None = None,
    shares: "ShareSet | None" = None,
) -> BasisTransfer:
    """Move ``amount`` from ``from_basis`` to ``to_basis``.

    The currency step is taken **at the price year the money is denominated in**,
    then the result is escalated inside the target currency. Doing it the other
    way round would apply an exchange rate to money of a year it never existed in.

    A transformation that cannot be defended is refused, not approximated:

    * an unknown currency on either side blocks everything;
    * differing currencies with an unknown denomination year block, because no
      year-specific rate can be chosen and a flat rate folds an exchange-rate
      movement into what is reported as a deviation;
    * differing price years with either year unknown block the escalation.

    Matching currencies with an unknown year are *not* blocked - the amount is
    already currency-comparable - but the result is flagged
    ``currency_aligned_year_unknown`` so no reader mistakes it for an aligned one.
    """
    reg = registry or default_registry()
    t = BasisTransfer(amount_in=amount, from_basis=from_basis, to_basis=to_basis,
                      quality="blocked")

    if "unknown" in (from_basis.currency, to_basis.currency):
        t.blocked_reason = (
            f"currency unknown on one side ({from_basis.label} -> {to_basis.label}); "
            "no conversion is defined"
        )
        return t

    same_currency = from_basis.currency == to_basis.currency
    years_known = from_basis.resolved and to_basis.resolved

    if not years_known:
        if not same_currency:
            missing = "source" if not from_basis.resolved else "target"
            t.blocked_reason = (
                f"{from_basis.currency} -> {to_basis.currency} needs the exchange rate of "
                f"the year the money is denominated in, and the {missing} price year is "
                "unknown. A flat rate would fold a currency movement into the deviation"
            )
            return t
        t.quality = "currency_aligned_year_unknown"
        t.amount_out = amount
        t.notes.append(
            "both sides are in "
            f"{from_basis.currency}, so the comparison is dimensionless, but at least one "
            "price year is unknown: the two are not aligned to a common price level"
        )
        return t

    if from_basis.same_as(to_basis):
        t.quality = "identity"
        t.amount_out = amount
        return t

    value = amount
    if not same_currency:
        conv = reg.conversion(from_basis.currency, to_basis.currency,
                              year=from_basis.price_year)
        t.currency_step = conv
        value *= conv.rate

    factor, steps, method = escalation(from_basis.price_year, to_basis.price_year,
                                       reg, shares)
    t.index_steps = steps
    t.escalation_factor = factor
    value *= factor

    t.amount_out = value
    if same_currency:
        t.quality = "price_year_only"
    elif from_basis.price_year == to_basis.price_year:
        t.quality = "currency_only"
    else:
        t.quality = "currency_and_price_year"
    if steps:
        t.notes.append(method)
    return t


def convert_economics(economics, from_basis: PriceBasis, to_basis: PriceBasis,
                      registry: Registry | None = None,
                      shares: "ShareSet | None" = None):
    """Return ``economics`` with every monetary field moved to ``to_basis``.

    Used to answer one question and no other: *how much of a reconstruction's
    deviation comes from having left part of its price set in the library's
    currency?* Running the same scenario with the library defaults expressed in
    the source's own currency and price year, and comparing, bounds that error
    exactly instead of asserting it is small.

    Only :data:`~algametrix.paper.basis.MONETARY_ECONOMICS_FIELDS` move.
    Fractions, factors and lifetimes are dimensionless; prices the *source*
    published are already in the target basis and must not be touched, which is
    why the caller applies its source overrides after this conversion, not before.
    """
    from dataclasses import replace as _replace

    t = transfer(1.0, from_basis, to_basis, registry, shares)
    if not t.ok:
        raise MissingIndexError(
            f"cannot express the library price set in {to_basis.label}: {t.blocked_reason}"
        )
    factor = t.amount_out
    updates = {f: getattr(economics, f) * factor for f in MONETARY_ECONOMICS_FIELDS
               if hasattr(economics, f)}
    return _replace(economics, **updates), t


# --------------------------------------------------------------------------
# Engine-derived capital share
# --------------------------------------------------------------------------

#: Engine cost category -> normalization class. The engine's own OPEX categories
#: are the only cost breakdown this repository can produce for a scenario, so they
#: are what the bounding analysis is built on.
_CATEGORY_TO_CLASS: dict[str, str] = {
    "Facility-dependent": "capital",   # depreciation + maintenance + insurance
    "Utilities": "energy",             # electricity + process heat
    "Labour": "labour",
    "Raw materials": "general_opex",
    "Overhead": "general_opex",
    "Other operating": "general_opex",
}


def component_share_bounds(builder_names: list[str]) -> ShareSet:
    """Cost-category shares of annual operating cost, per reconstruction.

    Runs each registered reconstruction, reads ``TEAResult.opex_categories`` and
    maps it onto the normalization classes. The result is the empirical spread of
    cost splits this engine produces - anchored to numbers the repository can
    regenerate, not to a literature figure nobody can check.

    It is **not** a claim about the unreconstructed studies' cost structure, which
    is exactly why every value derived from it is reported as an interval.
    """
    import statistics

    from ..library import load_library
    from ..scenario import run_scenario
    from . import reconstructions

    lib = load_library()
    per_builder: dict[str, dict[str, float]] = {}
    for name in builder_names:
        if not reconstructions.has_builder(name):
            continue
        res = run_scenario(reconstructions.build(name, lib))
        total = res.tea.annual_opex
        if total <= 0:
            continue
        vec: dict[str, float] = {}
        for category, value in res.tea.opex_categories.items():
            cls = _CATEGORY_TO_CLASS.get(category)
            if cls is None:
                continue
            vec[cls] = vec.get(cls, 0.0) + value / total
        covered = sum(vec.values())
        if covered <= 0:
            continue
        # Any category the map does not cover is folded into general OPEX rather
        # than dropped, so every share vector sums to exactly 1.
        if covered < 1.0 - 1e-9:
            vec["general_opex"] = vec.get("general_opex", 0.0) + (1.0 - covered)
        per_builder[name] = vec

    if not per_builder:
        raise ValueError("no executable reconstruction available to derive cost shares")

    classes = sorted({c for vec in per_builder.values() for c in vec})
    raw = {c: statistics.median([vec.get(c, 0.0) for vec in per_builder.values()])
           for c in classes}
    total = sum(raw.values())
    median = {c: v / total for c, v in raw.items()}   # element-wise medians need renormalising
    return ShareSet(per_builder=per_builder, median=median)
