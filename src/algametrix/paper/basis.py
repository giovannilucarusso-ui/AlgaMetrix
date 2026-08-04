"""The currency and price year a monetary number is actually denominated in.

The labelling error this module removes
---------------------------------------
AlgaMetrix has no currency. :mod:`algametrix.tea` does arithmetic on the
numbers held in :class:`~algametrix.models.Economics`; the unit of its
output is whatever unit those numbers were in. A reconstruction fed a source's
published **USD 2015** price set therefore returns a production cost in USD 2015.
Calling it EUR - which the field name ``production_cost_eur_per_kg`` does, and
which ``data/reference_superpro_*.csv`` does in column names whose own comment
line says "Values in USD" - is a labelling error, not a conversion.

That error propagated into two places:

* the validation table, which divided an engine number by a source number in a
  different currency and printed the result as a percentage deviation. A ratio
  between EUR and USD is not dimensionless and is not a deviation;
* Analysis B of the harmonization, which pooled engine outputs denominated in
  EUR 2016, EUR 2021, EUR 2022 and USD 2022 into a single max/min spread.

Both are fixed by carrying the basis explicitly: every reconstruction declares
the currency and price year of the price set it is run with, every comparison
states the basis both sides are expressed in, and every transformation between
bases is audited in :mod:`algametrix.paper.indices`.

Mixed price sets
----------------
Several reconstructions take *some* prices from the source and leave the rest at
the shipped library defaults. Their output is not cleanly in one currency. Such a
basis is declared ``mixed_price_set``; :func:`reconstructions.build_in_basis`
re-runs it with the library defaults converted into the declared basis, and the
difference between the two runs bounds the error the mixing introduces. The
deviation is then reported as an interval instead of a point.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How a reconstruction's price set was assembled.
#:
#: ``source_price_set``
#:     every price fed to the engine comes from the source study.
#: ``mixed_price_set``
#:     the prices the source publishes are used; the remainder are the shipped
#:     library defaults, which are in the library's own currency and price year.
#: ``library_default_price_set``
#:     the scenario runs entirely on ``data/parameters.yaml``. Its output is in
#:     the library basis, whatever the source is denominated in.
BASIS_KINDS = ("source_price_set", "mixed_price_set", "library_default_price_set")


@dataclass(frozen=True)
class PriceBasis:
    """Currency and price year in which a monetary quantity is denominated."""

    currency: str
    price_year: int | None
    kind: str
    provenance: str
    #: Economics fields left at the shipped default on a ``mixed_price_set``.
    library_priced: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if self.kind not in BASIS_KINDS:
            raise ValueError(f"price basis kind {self.kind!r} not in {BASIS_KINDS}")

    @property
    def resolved(self) -> bool:
        """The price year is known, so a year-specific transformation is possible."""
        return self.price_year is not None

    @property
    def is_mixed(self) -> bool:
        return self.kind == "mixed_price_set"

    @property
    def label(self) -> str:
        return f"{self.currency} {self.price_year if self.price_year is not None else '(year unknown)'}"

    def same_as(self, other: "PriceBasis") -> bool:
        """True only when both bases are fully resolved and identical.

        Two bases with the same currency and an unknown price year are *not*
        the same basis: nobody has checked that they are.
        """
        return (
            self.currency == other.currency
            and self.price_year is not None
            and self.price_year == other.price_year
        )

    def as_lines(self, indent: str = "      ") -> list[str]:
        out = [f"{indent}basis   : {self.label}  [{self.kind}]",
               f"{indent}priced  : {self.provenance}"]
        if self.library_priced:
            out.append(f"{indent}library : {', '.join(self.library_priced)} left at the "
                       "shipped default")
        if self.notes:
            out.append(f"{indent}note    : {self.notes}")
        return out


#: The basis of the shipped price set in ``data/parameters.yaml``.
#:
#: DECLARED, NOT SOURCED. The shipped prices carry no dated provenance: 0.15
#: EUR/kWh sits between the Eurostat EU27 industrial band-IC price for 2021
#: (0.095) and 2022 (0.179), and 250 000 EUR/yr of labour is not tied to a
#: published wage table. 2022 is declared as the reference year because it is the
#: year the harmonization normalises to and the year the legacy outputs were
#: produced against. Every result that depends on it says so.
LIBRARY_PRICE_BASIS = PriceBasis(
    currency="EUR",
    price_year=2022,
    kind="library_default_price_set",
    provenance="data/parameters.yaml -> economics (shipped defaults)",
    notes=(
        "declared, not sourced: the shipped price set is not tied to a dated price "
        "table. Any comparison that depends on this year inherits that assumption"
    ),
)

#: Economics fields that carry money and are therefore basis-dependent. Used by
#: :func:`algametrix.paper.indices.convert_economics` to move a library
#: default price set into another basis. Fractions, factors, rates and lifetimes
#: are dimensionless and are deliberately absent.
MONETARY_ECONOMICS_FIELDS = (
    "electricity_price",
    "heat_price",
    "co2_price",
    "bicarbonate_price",
    "nitrogen_price",
    "phosphorus_price",
    "water_price",
    "substrate_price",
    "land_price",
    "harvest_capex_per_kgyr",
    "drying_capex_per_kgyr",
    "labor_cost_per_year",
)


def basis_of_source(
    currency: str | None, price_year: int | None, provenance: str = "as reported by the source"
) -> PriceBasis:
    """The basis a published value is reported in.

    An unknown currency is carried as ``"unknown"`` rather than defaulted, so a
    comparison against it is blocked instead of silently assuming EUR.
    """
    return PriceBasis(
        currency=currency or "unknown",
        price_year=price_year,
        kind="source_price_set",
        provenance=provenance,
    )
