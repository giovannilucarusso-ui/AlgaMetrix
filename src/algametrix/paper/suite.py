"""The scenario suite the verification and benchmarking sections are run over.

One heterogeneous set, defined once, so that the shared-inventory consistency
check, the mass-balance verification and the independent-implementation
benchmark all speak about the same population of scenarios and a reader can
count them.

The suite deliberately mixes provenance, and every member says which it is:

``reconstruction``
    a published case rebuilt from its source (see
    :mod:`algametrix.paper.reconstructions`);
``template``
    a shipped configuration from :mod:`algametrix.templates`;
``archetype``
    the sensitivity/uncertainty archetypes (:mod:`algametrix.paper.archetypes`);
``variant``
    a shipped configuration altered to exercise a code path the others do not
    reach — bicarbonate carbon feed, batch scheduling, electric drying, no
    drying at all, and each biogenic-carbon convention.

None of this is a claim that the suite is representative of the industry. It is
a claim that it exercises the engine broadly: both trophic modes, both carbon
sources, both cultivation bases, batch and continuous, with and without
downstream extraction and multi-product allocation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Callable

from ..library import Library, load_library
from ..models import CarbonAccounting, CarbonSource, Scenario, TrophicMode
from .. import templates
from . import archetypes, reconstructions


@dataclass
class SuiteCase:
    """One scenario in the suite, with its provenance."""

    key: str
    label: str
    kind: str                        # reconstruction | template | archetype | variant
    build: Callable[[Library], Scenario]
    note: str = ""

    def scenario(self, lib: Library | None = None) -> Scenario:
        return deepcopy(self.build(lib or load_library()))


# ---------------------------------------------------------------------
# Variants: configurations reached by no reconstruction or template
# ---------------------------------------------------------------------

#: Phototrophic base for the variants: the shipped open-raceway configuration.
_PHOTO_BASE = "Single-cell protein (Chlorella, raceway)"
#: Heterotrophic base for the variants.
_HETERO_BASE = "Heterotrophic microalgae powder"
#: Whole-biomass base, used where the variant must not carry a product split.
_WHOLE_BASE = templates.TEMPLATES[0].name


def _bicarbonate(lib: Library) -> Scenario:
    """NaHCO3 rather than CO2 gas — the alkaliphilic (Spirulina-type) carbon route."""
    scn = templates.build_template(_PHOTO_BASE, lib)
    scn.system = replace(scn.system, carbon_source=CarbonSource.BICARBONATE)
    return scn


def _batch(lib: Library) -> Scenario:
    """Batch scheduling rather than continuous throughput."""
    scn = templates.build_template(_HETERO_BASE, lib)
    scn.batch_mode = True
    scn.batch_size_kg = 1_200.0
    scn.batch_cycle_time_h = 120.0
    return scn


def _electric_drying(lib: Library) -> Scenario:
    """Drying heat routed to the electricity account instead of a gas boiler."""
    scn = templates.build_template(_PHOTO_BASE, lib)
    scn.drying = replace(scn.drying, fuel="electricity")
    return scn


def _no_drying(lib: Library) -> Scenario:
    """Wet paste: no thermal drying step at all."""
    scn = templates.build_template(_WHOLE_BASE, lib)
    scn.drying = replace(scn.drying, enabled=False)
    return scn


def _heated_pond(lib: Library) -> Scenario:
    """Seasonal pond heating from natural gas, on the shipped raceway."""
    scn = templates.build_template(_PHOTO_BASE, lib)
    scn.system = replace(scn.system, cultivation_heat_mj_per_kg=25.0,
                         cultivation_heat_fuel="natural_gas")
    return scn


def _carbon_mode(mode: CarbonAccounting) -> Callable[[Library], Scenario]:
    def build(lib: Library) -> Scenario:
        scn = templates.build_template(_PHOTO_BASE, lib)
        scn.lcia = replace(scn.lcia, count_biogenic_uptake=True, carbon_accounting=mode)
        return scn
    return build


VARIANTS: list[SuiteCase] = [
    SuiteCase("var_bicarbonate", "Variant: NaHCO3 carbon source", "variant", _bicarbonate,
              "the bicarbonate branch of the carbon balance"),
    SuiteCase("var_batch", "Variant: batch scheduling", "variant", _batch,
              "annual output set by batches per year, not by volume x productivity"),
    SuiteCase("var_electric_drying", "Variant: electrically dried", "variant", _electric_drying,
              "drying energy moved from the heat account to electricity"),
    SuiteCase("var_no_drying", "Variant: wet paste (no drying)", "variant", _no_drying,
              "no thermal drying step"),
    SuiteCase("var_heated_pond", "Variant: seasonally heated pond", "variant", _heated_pond,
              "cultivation heat from natural gas on an open pond"),
    SuiteCase("var_carbon_no_credit", "Variant: no biogenic credit", "variant",
              _carbon_mode(CarbonAccounting.NO_BIOGENIC_CREDIT),
              "biogenic carbon: no credit"),
    SuiteCase("var_carbon_at_gate", "Variant: at-gate storage credit", "variant",
              _carbon_mode(CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE),
              "biogenic carbon: credit for all carbon in the biomass at the gate"),
    SuiteCase("var_carbon_custom", "Variant: custom credit fraction", "variant",
              _carbon_mode(CarbonAccounting.CUSTOM),
              "biogenic carbon: credit for a declared fraction"),
]


# ---------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------

def _reconstruction_cases() -> list[SuiteCase]:
    return [
        SuiteCase(f"rec_{key}", f"Reconstruction: {key}", "reconstruction",
                  (lambda k: lambda lib: reconstructions.build(k, lib))(key))
        for key in sorted(reconstructions.available())
    ]


def _template_cases() -> list[SuiteCase]:
    return [
        SuiteCase(f"tpl_{name}", f"Template: {name}", "template",
                  (lambda n: lambda lib: templates.build_template(n, lib))(name))
        for name in templates.template_names()
    ]


def _archetype_cases() -> list[SuiteCase]:
    return [
        SuiteCase(f"arch_{a.key}", f"Archetype: {a.label}", "archetype",
                  (lambda k: lambda lib: archetypes.build(k, lib))(a.key))
        for a in archetypes.ARCHETYPES
    ]


def all_cases() -> list[SuiteCase]:
    """Every scenario in the suite, in a stable order."""
    return _reconstruction_cases() + _template_cases() + _archetype_cases() + list(VARIANTS)


def distinct_cases(lib: Library | None = None) -> tuple[list[SuiteCase], dict[str, list[str]]]:
    """The suite with structurally identical members collapsed.

    Several suite members build the *same* scenario by different routes: a
    template and the reconstruction that wraps it, or an archetype and its
    template. Counting those separately would inflate the size of the evidence
    base, so this returns the first member of each equality class together with
    a map from the kept key to the keys it absorbed.

    Equality is dataclass equality on the fully built :class:`Scenario`, i.e.
    every field of every component compares equal.
    """
    lib = lib or load_library()
    kept: list[SuiteCase] = []
    built: list[Scenario] = []
    duplicates: dict[str, list[str]] = {}
    for case in all_cases():
        scn = case.scenario(lib)
        for i, other in enumerate(built):
            if scn == other:
                duplicates.setdefault(kept[i].key, []).append(case.key)
                break
        else:
            kept.append(case)
            built.append(scn)
    return kept, duplicates


def carbon_convention(scn: Scenario) -> CarbonAccounting:
    """The biogenic-carbon convention in force; the master switch off means no credit."""
    if not scn.lcia.count_biogenic_uptake:
        return CarbonAccounting.NO_BIOGENIC_CREDIT
    return scn.lcia.carbon_accounting


#: Short names of the biogenic-carbon conventions, as the coverage table prints them.
CONVENTION_LABELS = {
    CarbonAccounting.SOURCE_SPECIFIC_CREDIT: "CO2-fed credit",
    CarbonAccounting.NO_BIOGENIC_CREDIT: "no credit",
    CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE: "at-gate credit",
    CarbonAccounting.CUSTOM: "declared fraction",
}


def coverage(lib: Library | None = None,
             cases: list[SuiteCase] | None = None) -> dict[str, int]:
    """How many suite members exercise each configuration axis.

    Reported alongside the verification results so "a heterogeneous set" is a
    counted statement rather than an adjective. Pass the output of
    :func:`distinct_cases` to count structurally distinct scenarios only, which
    is what the reports do; the default counts every member.
    """
    lib = lib or load_library()
    cases = cases if cases is not None else all_cases()
    counts = {
        "total": 0, "phototrophic": 0, "heterotrophic": 0,
        "carbon source: CO2": 0, "carbon source: NaHCO3": 0,
        "area basis": 0, "volume basis": 0,
        "batch": 0, "continuous": 0,
        "with drying": 0, "without drying": 0,
        "drying fuel: natural gas": 0, "drying fuel: electricity": 0,
        "heated cultivation": 0,
        "with extraction": 0, "multi-product allocation": 0,
        "with explicit media/utilities": 0,
        "waste-derived feed": 0,
        **{f"biogenic carbon: {label}": 0 for label in CONVENTION_LABELS.values()},
    }
    for case in cases:
        scn = case.scenario(lib)
        counts["total"] += 1
        photo = scn.system.mode == TrophicMode.PHOTOTROPHIC
        counts["phototrophic" if photo else "heterotrophic"] += 1
        if photo:
            key = ("carbon source: NaHCO3"
                   if scn.system.carbon_source == CarbonSource.BICARBONATE
                   else "carbon source: CO2")
            counts[key] += 1
        counts["area basis" if scn.system.basis.value == "area" else "volume basis"] += 1
        counts["batch" if scn.batch_mode else "continuous"] += 1
        counts["with drying" if scn.drying.enabled else "without drying"] += 1
        if scn.drying.enabled:
            counts["drying fuel: electricity" if scn.drying.fuel == "electricity"
                   else "drying fuel: natural gas"] += 1
        if scn.system.cultivation_heat_mj_per_kg > 0:
            counts["heated cultivation"] += 1
        if scn.extraction.enabled:
            counts["with extraction"] += 1
        if len(scn.products) > 1:
            counts["multi-product allocation"] += 1
        if scn.materials or scn.utilities:
            counts["with explicit media/utilities"] += 1
        if scn.waste_feed.enabled:
            counts["waste-derived feed"] += 1
        counts[f"biogenic carbon: {CONVENTION_LABELS[carbon_convention(scn)]}"] += 1
    return counts


# ---------------------------------------------------------------------
# One row per scenario (SI Table S-B)
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class SuiteRow:
    """What one distinct scenario is and which model options it exercises."""

    number: int
    key: str
    kind: str
    source: str                   # the study, template, archetype or variant purpose
    also: tuple[str, ...]         # other suite members that build the same scenario
    organism: str
    system: str
    carbon: str                   # CO2 | NaHCO3 | the organic substrate
    basis: str                    # area | volume
    operation: str                # continuous | batch
    drying: str
    downstream: str
    products: int                 # 1 for whole biomass
    options: tuple[str, ...]


def study_label(builder: str, dataset) -> str:
    """Short citation and scenario label of the study a builder reconstructs.

    Where two records share a builder, the one with an economic endpoint wins.
    Empty when no record names the builder.
    """
    records = sorted((r for r in dataset if r.reconstruction_builder == builder),
                     key=lambda r: (r.economic_endpoint_type is None, r.study_id))
    if not records:
        return ""
    return f"{records[0].short_citation}, {records[0].scenario_label}"


def options(scn: Scenario, lib: Library) -> tuple[str, ...]:
    """The model options a scenario exercises that :class:`SuiteRow` has no column for."""
    out = []
    if scn.system.cultivation_heat_mj_per_kg > 0:
        out.append("cultivation heat")
    if len(scn.products) > 1:
        out.append(f"{scn.extraction.allocation} allocation")
    if scn.materials:
        out.append("recipe materials")
    if scn.utilities:
        out.append("utility line items")
    if scn.waste_feed.enabled:
        out.append(f"waste-derived feed, {scn.waste_feed.convention.value.replace('_', '-')}")
    if scn.credits_per_year or scn.coproduct_revenue_per_year:
        out.append("revenue credits")
    if scn.other_opex_per_year:
        out.append("other operating cost")
    convention = carbon_convention(scn)
    if convention != CarbonAccounting.SOURCE_SPECIFIC_CREDIT:
        out.append(f"biogenic carbon: {CONVENTION_LABELS[convention]}")
    eco, ref = scn.economics, lib.economics
    if ((eco.discount_rate, eco.plant_lifetime, eco.depreciation_years, eco.tax_rate)
            != (ref.discount_rate, ref.plant_lifetime, ref.depreciation_years, ref.tax_rate)):
        out.append("source financial assumptions")
    return tuple(out)


def _source(case: SuiteCase, dataset) -> str:
    if case.kind == "reconstruction":
        return study_label(case.key.removeprefix("rec_"), dataset) or "no study record"
    if case.kind == "template":
        return "shipped template"
    if case.kind == "archetype":
        arch = archetypes.get(case.key.removeprefix("arch_"))
        return ("library-default archetype" if arch.kind == "library_default"
                else "archetype")
    return case.note


def describe(lib: Library | None = None, dataset=None) -> list[SuiteRow]:
    """The structurally distinct scenarios, numbered in suite order."""
    from . import studies

    lib = lib or load_library()
    dataset = dataset if dataset is not None else studies.default_dataset()
    cases, duplicates = distinct_cases(lib)
    rows = []
    for number, case in enumerate(cases, start=1):
        scn = case.scenario(lib)
        system = scn.system
        if system.mode == TrophicMode.HETEROTROPHIC:
            carbon = system.substrate_name
        elif system.carbon_source == CarbonSource.BICARBONATE:
            carbon = "NaHCO3"
        else:
            carbon = "CO2"
        if not scn.drying.enabled:
            drying = "none"
        elif scn.drying.fuel == "electricity":
            drying = f"{scn.drying.name}, electric"
        else:
            drying = scn.drying.name
        rows.append(SuiteRow(
            number=number,
            key=case.key,
            kind=case.kind,
            source=_source(case, dataset),
            also=tuple(duplicates.get(case.key, ())),
            organism=scn.organism.name,
            system=system.name,
            carbon=carbon,
            basis=system.basis.value,
            operation="batch" if scn.batch_mode else "continuous",
            drying=drying,
            downstream=scn.extraction.name if scn.extraction.enabled else "none",
            products=max(len(scn.products), 1),
            options=options(scn, lib),
        ))
    return rows
