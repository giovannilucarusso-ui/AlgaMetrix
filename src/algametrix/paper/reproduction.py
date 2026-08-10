"""Engine-versus-source comparison for every executable study.

Replaces the legacy ``results/validation.txt`` and ``results/lca_validation.txt``,
which listed reproductions whose scenario definitions are no longer in the
repository.

Three things are kept strictly apart here and were not before:

* the **economic endpoint** being compared. Comparing the engine's production
  cost against a source's minimum selling price is an endpoint mismatch, and the
  row says so instead of printing a percentage.
* **point predictions versus range checks.** A result that falls inside a
  published envelope is a plausibility check, not a prediction, and is reported
  with the envelope rather than as a deviation from its midpoint.
* the **price basis** - currency and price year - of each side. The previous
  version divided an engine number by a source number in a different currency,
  printed the quotient as a percentage deviation, and attached a note saying the
  currencies differed. A note does not make the quotient dimensionless. Every
  comparison here is now carried out in one declared basis, or it is refused.

How the basis is resolved
-------------------------
The engine returns a cost in the units of the price set it was fed, which
:mod:`algametrix.paper.basis` declares per builder. The comparison basis
is the **source's own** currency and price year - the published, citable unit -
and the engine value is moved into it with the year-specific ECB rate and, where
the price years differ, the per-class escalation of
:mod:`algametrix.paper.indices`. Where the source's basis is not fully
known, the row is marked ``not_comparable`` and carries no percentage.

Mixed price sets are bracketed rather than assumed away: the scenario is run a
second time with the shipped library defaults expressed in the declared currency,
and the deviation is reported as the interval spanned by the two readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..library import Library, load_library
from ..scenario import minimum_selling_price, run_scenario
from . import indices, reconstructions
from .basis import PriceBasis, basis_of_source
from .endpoints import PRIMARY_ENDPOINT
from .indices import BasisTransfer
from .schema import StudyRecord
from .studies import Dataset

#: Source endpoints the engine can produce a like-for-like value for.
_ENGINE_ENDPOINT = {
    "production_cost": "production cost",
    "minimum_selling_price": "MEPP (NPV = 0)",
    "minimum_biomass_selling_price": "MEPP (NPV = 0)",
    "minimum_product_selling_price": "MEPP (NPV = 0)",
}


@dataclass
class ReproductionRow:
    study_id: str
    metric: str                 # "cost" | "gwp"
    endpoint: str
    validation_mode: str
    comparison_kind: str        # "point" | "range" | "endpoint_mismatch" | "not_comparable"
    model: float | None
    reference: float | None
    ref_low: float | None = None
    ref_high: float | None = None
    unit: str = ""
    notes: list[str] = field(default_factory=list)

    # --- price basis (cost rows only; a GWP is basis-free) -----------------
    engine_basis: PriceBasis | None = None
    source_basis: PriceBasis | None = None
    #: The engine value as the engine produced it, before any basis transfer.
    model_native: float | None = None
    #: Second reading of the same scenario with the library defaults expressed in
    #: the engine's declared currency. Only set for a mixed price set.
    model_alt: float | None = None
    transfer: BasisTransfer | None = None

    # ------------------------------------------------------------------
    @property
    def model_low(self) -> float | None:
        if self.model is None:
            return None
        return min(self.model, self.model_alt) if self.model_alt is not None else self.model

    @property
    def model_high(self) -> float | None:
        if self.model is None:
            return None
        return max(self.model, self.model_alt) if self.model_alt is not None else self.model

    @property
    def ratio(self) -> float | None:
        """model / reference, only where a point comparison is defined.

        Both sides are in the comparison basis by construction: a row whose basis
        transfer was refused never reaches ``comparison_kind == "point"``.
        """
        if self.comparison_kind != "point" or not self.reference or self.model is None:
            return None
        return self.model / self.reference

    @property
    def ratio_bounds(self) -> tuple[float, float] | None:
        """Deviation interval over the two readings of a mixed price set."""
        if self.comparison_kind != "point" or not self.reference or self.model_alt is None:
            return None
        return (self.model_low / self.reference, self.model_high / self.reference)

    @property
    def in_range(self) -> bool | None:
        if self.comparison_kind != "range" or self.model is None:
            return None
        if self.ref_low is None or self.ref_high is None:
            return None
        return self.ref_low <= self.model <= self.ref_high

    @property
    def basis_label(self) -> str:
        """The unit both sides of the comparison are expressed in."""
        if self.metric == "gwp":
            return "kg CO2-eq/kg"
        return self.source_basis.label if self.source_basis else "unknown basis"

    @property
    def verdict(self) -> str:
        if self.comparison_kind == "endpoint_mismatch":
            return "endpoint mismatch - not compared"
        if self.comparison_kind == "not_comparable":
            return "NOT COMPARABLE"
        if self.comparison_kind == "range":
            inside = self.in_range
            return (f"in range {self.ref_low:g}-{self.ref_high:g}" if inside
                    else f"OUTSIDE range {self.ref_low:g}-{self.ref_high:g}")
        r = self.ratio
        if r is None:
            return "n/a"
        bounds = self.ratio_bounds
        if bounds is None:
            return f"{(r - 1) * 100:+.0f}%"
        lo, hi = bounds
        return f"{(lo - 1) * 100:+.0f}% to {(hi - 1) * 100:+.0f}%"


def _cost_of(scn) -> float:
    r = run_scenario(scn)
    if r.main_product is not None:
        return r.main_product.production_cost_eur_per_kg
    return r.tea.production_cost_eur_per_kg


def _engine_value(scn, endpoint: str) -> tuple[float, str]:
    if endpoint == PRIMARY_ENDPOINT:
        return _cost_of(scn), "production cost"
    return minimum_selling_price(scn), _ENGINE_ENDPOINT[endpoint]


def cost_row(
    rec: StudyRecord,
    lib: Library,
    registry: indices.Registry | None = None,
    shares: indices.ShareSet | None = None,
) -> ReproductionRow | None:
    if rec.reported_value is None:
        return None
    builder = rec.reconstruction_builder
    scn = reconstructions.build(builder, lib)
    endpoint = rec.economic_endpoint_type or "unknown"

    if endpoint not in _ENGINE_ENDPOINT:
        return ReproductionRow(
            rec.study_id, "cost", endpoint, rec.validation_mode or "none",
            "endpoint_mismatch", None, rec.reported_value,
            unit=rec.reported_unit or "",
            notes=["source endpoint is unknown; the engine has no like-for-like output"],
        )

    model_native, engine_endpoint = _engine_value(scn, endpoint)
    engine_basis = reconstructions.price_basis(builder)
    source_basis = basis_of_source(rec.reported_currency, rec.reported_price_year)

    row = ReproductionRow(
        study_id=rec.study_id, metric="cost",
        endpoint=f"{endpoint} vs engine {engine_endpoint}",
        validation_mode=rec.validation_mode or "none",
        comparison_kind="not_comparable", model=None, reference=rec.reported_value,
        ref_low=rec.reported_low, ref_high=rec.reported_high,
        unit=rec.reported_unit or "",
        engine_basis=engine_basis, source_basis=source_basis,
        model_native=model_native,
    )

    # --- move the engine value into the source's own basis -----------------
    tr = indices.transfer(model_native, engine_basis, source_basis, registry, shares)
    row.transfer = tr
    if not tr.ok:
        row.notes.append(
            f"engine output is denominated in {engine_basis.label}, the source in "
            f"{source_basis.label}: {tr.blocked_reason}. No deviation is reported; a "
            "ratio between two currencies is not a deviation"
        )
        return row

    row.model = tr.amount_out
    row.comparison_kind = ("range" if (rec.reported_low is not None
                                       and rec.reported_high is not None) else "point")

    if tr.is_identity:
        row.notes.append(
            f"like-for-like: the engine was run on a price set in {engine_basis.label}, "
            "the same basis the source reports in - no conversion applied"
        )
    else:
        row.notes.append(
            f"engine value {model_native:,.4g} {engine_basis.label} converted to "
            f"{tr.amount_out:,.4g} {source_basis.label} before the comparison "
            f"[{tr.quality}]"
        )

    # --- bracket a mixed price set -----------------------------------------
    if engine_basis.is_mixed:
        try:
            alt_scn, alt_tr = reconstructions.build_in_basis(builder, lib, registry, shares)
        except indices.MissingIndexError as exc:
            row.notes.append(
                f"the library-priced part of this scenario cannot be expressed in "
                f"{engine_basis.label} ({exc}), so the mixing error is not bounded"
            )
        else:
            alt_native, _ = _engine_value(alt_scn, endpoint)
            alt_tr2 = indices.transfer(alt_native, engine_basis, source_basis,
                                       registry, shares)
            priced = ", ".join(engine_basis.library_priced) or "none"
            if not alt_tr2.ok:
                row.notes.append(
                    f"MIXED price set ({priced} left at the shipped library default); the "
                    "second reading cannot be brought into the comparison basis, so the "
                    "mixing error is not bounded"
                )
            elif abs(alt_tr.amount_out - 1.0) < 1e-12:
                row.notes.append(
                    f"MIXED price set ({priced} left at the shipped library default). The "
                    f"library basis and {engine_basis.label} differ in no known respect, "
                    "so re-running changes nothing and the mixing is NOT bounded - the "
                    "price year of neither side is established"
                )
            else:
                row.model_alt = alt_tr2.amount_out
                row.notes.append(
                    f"MIXED price set: {len(engine_basis.library_priced)} price(s) left at "
                    f"the shipped library default ({priced}). Re-running with those "
                    f"defaults expressed in {engine_basis.label} (x{alt_tr.amount_out:.4f}) "
                    f"gives {row.model_alt:,.4g} instead of {row.model:,.4g}; the deviation "
                    "is reported as the interval this spans"
                )

    if rec.reported_price_year is None:
        row.notes.append(
            "source price year unknown: the two sides are in the same currency but "
            "have not been shown to be at the same price level"
        )
    return row


#: A net GWP comparison is only meaningful when both sides are on the same
#: biogenic-carbon convention. Below this, the engine's own adjustment is small
#: enough that the convention cannot materially move the number, so an
#: unrecorded source convention is not fatal.
IMMATERIAL_ADJUSTMENT = 0.01   # fraction of the gross result


def gwp_row(rec: StudyRecord, lib: Library) -> ReproductionRow | None:
    """Compare a published cradle-to-gate GWP, on a convention-free basis if possible.

    Three cases, in order of strength:

    1. the source publishes its **gross** figure (before any biogenic
       adjustment). Gross is convention-free, so the comparison is made on it
       and the net is reported alongside for information;
    2. the source's convention is recorded and matches the engine's, so the net
       comparison is like-for-like;
    3. the source's convention is unknown. Then the engine's own adjustment
       decides: if it is immaterial the comparison stands with a warning,
       otherwise the row is refused, exactly as a cross-currency quotient is
       refused. A percentage between two different carbon conventions is not a
       deviation.
    """
    if not rec.has_published_gwp:
        return None
    scn = reconstructions.build(rec.reconstruction_builder, lib)
    res = run_scenario(scn)
    gross = res.lca.gwp_gross_kg_co2eq_per_kg
    adj = res.lca.biogenic_adjustment_kg_co2eq_per_kg
    engine_mode = res.lca.carbon_accounting_mode

    kind = "range" if (rec.reported_gwp_low is not None
                       and rec.reported_gwp_high is not None
                       and rec.reported_gwp is None) else "point"

    # --- pick the basis both sides can stand on ---------------------------
    if rec.reported_gwp_gross is not None:
        basis = "gross (before any biogenic adjustment; convention-free)"
        model, reference = gross, rec.reported_gwp_gross
    else:
        basis = f"net, engine convention {engine_mode}"
        model, reference = res.lca.gwp_kg_co2eq_per_kg, rec.reported_gwp

    row = ReproductionRow(
        study_id=rec.study_id, metric="gwp",
        endpoint=f"{rec.environmental_endpoint_type or 'unknown'} [{basis}]",
        validation_mode=rec.validation_mode or "none",
        comparison_kind=kind,
        model=model, reference=reference,
        ref_low=rec.reported_gwp_low, ref_high=rec.reported_gwp_high,
        unit="kg CO2-eq/kg",
    )
    row.model_native = model
    row.notes.append(
        f"engine gross {gross:.3f}, biogenic adjustment {adj:+.3f}, net "
        f"{res.lca.gwp_kg_co2eq_per_kg:.3f} under {engine_mode}"
    )
    if rec.reported_gwp_gross is not None:
        row.notes.append(
            f"source gross {rec.reported_gwp_gross:.3f}"
            + (f", source biogenic adjustment {rec.reported_biogenic_adjustment:+.3f}"
               if rec.reported_biogenic_adjustment is not None else "")
            + f", source net {rec.reported_gwp:.3f}. The comparison is made on the GROSS "
              "figure, which carries no biogenic-carbon convention and is therefore "
              "comparable whatever either side chose"
        )
    if rec.gwp_basis_conversion:
        row.notes.append(f"basis: {rec.gwp_basis_conversion}")

    # --- convention gate ---------------------------------------------------
    if rec.biogenic_carbon_convention is None and rec.reported_gwp_gross is None:
        if abs(adj) > IMMATERIAL_ADJUSTMENT * max(abs(gross), 1e-12):
            row.comparison_kind = "not_comparable"
            row.model = None
            row.notes.append(
                f"NOT COMPARABLE: the source's biogenic-carbon convention is unrecorded "
                f"and the engine applies an adjustment of {adj:+.3f} on a gross of "
                f"{gross:.3f} ({abs(adj) / max(abs(gross), 1e-12):.0%}), so the two sides "
                "may be on different conventions and a percentage between them would not "
                "be a deviation. Record the source's convention, or its gross figure, to "
                "restore the comparison"
            )
        else:
            row.notes.append(
                "the source's biogenic-carbon convention is unrecorded, but the engine's "
                f"own adjustment is {adj:+.3f} on a gross of {gross:.3f}, i.e. immaterial, "
                "so the convention cannot materially move this comparison"
            )
    elif rec.biogenic_carbon_convention is not None:
        matched = rec.biogenic_carbon_convention == engine_mode
        on_gross = rec.reported_gwp_gross is not None
        if matched:
            tail = " - MATCHED"
        elif on_gross:
            tail = (" - not matched, but immaterial here: the comparison above is made on "
                    "the gross figures, which carry no convention")
        else:
            tail = (" - NOT MATCHED and no gross figure is recorded, so the deviation "
                    "above is between two different conventions and must not be read as "
                    "a model error")
        row.notes.append(
            f"source convention {rec.biogenic_carbon_convention}; engine convention "
            f"{engine_mode}{tail}"
        )
    return row


def build_rows(
    dataset: Dataset,
    lib: Library | None = None,
    registry: indices.Registry | None = None,
    shares: indices.ShareSet | None = None,
) -> list[ReproductionRow]:
    lib = lib or load_library()
    if shares is None:
        shares = indices.component_share_bounds(reconstructions.available())
    rows: list[ReproductionRow] = []
    for rec in sorted((r for r in dataset if r.is_executable), key=lambda r: r.study_id):
        for row in (cost_row(rec, lib, registry, shares), gwp_row(rec, lib)):
            if row is not None:
                rows.append(row)
    return rows


def blocked_rows(dataset: Dataset) -> dict[str, str]:
    """Declared Tier-B studies whose reproduction cannot be run at all.

    Excluded records are *not* listed here: their scenario builders exist and
    run perfectly well. What was found unsound is the published value, not the
    reconstruction, and conflating the two would misreport both.
    """
    return {
        r.study_id: reconstructions.MISSING_SCENARIOS.get(
            r.study_id, "no scenario builder registered")
        for r in dataset
        if r.reconstructability_tier == "B" and r.is_included and not r.is_executable
    }


def excluded_rows(dataset: Dataset) -> dict[str, str]:
    """Records withdrawn from every population, with the reason.

    Kept in the dataset rather than deleted so that an exclusion is countable
    and a reader can see what was taken out and why.
    """
    return {
        r.study_id: (r.exclusion_reason or "no reason recorded")
        for r in dataset if not r.is_included
    }
