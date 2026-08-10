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
    """Seasonal cultivation heating — the only route into ``cultivation_heat_mj_per_kg``."""
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
              "exercises the bicarbonate branch of the carbon balance"),
    SuiteCase("var_batch", "Variant: batch scheduling", "variant", _batch,
              "annual output set by batches per year, not by area x productivity"),
    SuiteCase("var_electric_drying", "Variant: electrically dried", "variant", _electric_drying,
              "drying energy moved from the heat account to electricity"),
    SuiteCase("var_no_drying", "Variant: wet paste (no drying)", "variant", _no_drying),
    SuiteCase("var_heated_pond", "Variant: seasonally heated pond", "variant", _heated_pond,
              "the only configuration with cultivation thermal conditioning"),
    SuiteCase("var_carbon_no_credit", "Variant: no biogenic credit", "variant",
              _carbon_mode(CarbonAccounting.NO_BIOGENIC_CREDIT)),
    SuiteCase("var_carbon_at_gate", "Variant: at-gate storage credit", "variant",
              _carbon_mode(CarbonAccounting.TEMPORARY_STORAGE_CREDIT_AT_GATE)),
    SuiteCase("var_carbon_custom", "Variant: custom credit fraction", "variant",
              _carbon_mode(CarbonAccounting.CUSTOM)),
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
        "with extraction": 0, "multi-product allocation": 0,
        "with explicit media/utilities": 0,
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
        if scn.extraction.enabled:
            counts["with extraction"] += 1
        if len(scn.products) > 1:
            counts["multi-product allocation"] += 1
        if scn.materials or scn.utilities:
            counts["with explicit media/utilities"] += 1
    return counts
