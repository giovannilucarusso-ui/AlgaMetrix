"""The production archetypes used by the sensitivity and uncertainty analyses.

Two of the three are *study reconstructions* already registered in
:mod:`algametrix.paper.reconstructions`. The third is a
**library-default archetype**: it is assembled from the shipped cultivation
library and is not a reproduction of any published plant. The distinction is
carried in :attr:`Archetype.provenance` and printed into every report, because a
sensitivity ranking computed on a library-default configuration says something
about the tool, not about a published system.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Callable

from ..library import Library, load_library
from ..models import Scenario
from . import reconstructions

#: Cultivation electricity of an LED-illuminated photobioreactor, kWh per kg dry
#: biomass. Taken from this repository's own documentation of the case
#: (paper_handoff/METHODS.md 1.3 and results/gwp_harmonization.txt), which cites
#: ~140 kWh/kg for the LED-lit systems. It is a documented order-of-magnitude
#: figure for an energy-intensive closed system, not a measurement from a
#: specific plant.
LED_PBR_ELECTRICITY_KWH_PER_KG = 140.0


@dataclass
class Archetype:
    """A named scenario plus what kind of object it is."""

    key: str
    label: str
    build: Callable[[Library], Scenario]
    provenance: str
    kind: str          # "study_reconstruction" | "library_default"
    study_id: str | None = None
    notes: str = ""


def _raceway(lib: Library) -> Scenario:
    return reconstructions.build("scp_protein", lib)


def _fermenter(lib: Library) -> Scenario:
    return reconstructions.build("heterotrophic_powder", lib)


def _led_pbr(lib: Library) -> Scenario:
    """Library-default LED-assisted tubular PBR.

    The shipped ``Tubular photobioreactor`` system with its cultivation
    electricity raised to :data:`LED_PBR_ELECTRICITY_KWH_PER_KG` to represent
    artificial illumination. Every other parameter is the library default.
    """
    system = replace(
        lib.systems["Tubular photobioreactor"],
        elec_kwh_per_kg=LED_PBR_ELECTRICITY_KWH_PER_KG,
        name="Tubular photobioreactor + LED",
    )
    return Scenario(
        organism=lib.organisms["Phaeodactylum tricornutum"],
        system=system,
        harvesting=lib.harvesting["Centrifugation only"],
        drying=lib.drying["Spray drying"],
        economics=lib.economics,
        lcia=lib.lcia,
        scale=10_000.0,
        product_price=100.0,
    )


ARCHETYPES: list[Archetype] = [
    Archetype(
        key="open_raceway_pond",
        label="Open raceway pond (Chlorella)",
        build=_raceway,
        provenance="reconstructions.scp_protein -> templates 'Single-cell protein (Chlorella, raceway)'",
        kind="library_default",
        study_id=None,
        notes=(
            "NOT a reproduction of a published plant. It was previously presented as a "
            "reconstruction of an open single-cell-protein cost envelope; that envelope has "
            "no primary source and its study record is now excluded from every population, "
            "so the archetype is what it always was - the shipped raceway template on "
            "library-default prices."
        ),
    ),
    Archetype(
        key="heterotrophic_fermenter",
        label="Heterotrophic fermenter (Schizochytrium)",
        build=_fermenter,
        provenance="reconstructions.heterotrophic_powder -> templates 'Heterotrophic microalgae powder'",
        kind="study_reconstruction",
        study_id="russo2022_aury",
        notes="Blind reproduction of Russo et al. (2022); authors' own study, disclosed.",
    ),
    Archetype(
        key="led_pbr",
        label="LED-assisted tubular PBR (P. tricornutum)",
        build=_led_pbr,
        provenance=(
            "library default: data/systems.yaml 'Tubular photobioreactor' with cultivation "
            f"electricity set to {LED_PBR_ELECTRICITY_KWH_PER_KG:g} kWh/kg "
            "(paper_handoff/METHODS.md 1.3)"
        ),
        kind="library_default",
        study_id=None,
        notes=(
            "NOT a reproduction of a published plant. The legacy analyses used the "
            "vazquez2022 reconstruction here; that reconstruction has since been recovered "
            "and is a cohort member in its own right, so this archetype remains a "
            "library-default configuration and its results must not be attributed to any "
            "source study."
        ),
    ),
]


def get(key: str) -> Archetype:
    for a in ARCHETYPES:
        if a.key == key:
            return a
    raise KeyError(key)


def build(key: str, lib: Library | None = None) -> Scenario:
    """Build an archetype scenario, isolated from the shared library objects.

    See :func:`algametrix.paper.reconstructions.build` for why the copy
    matters: a ``Library`` hands the same mutable ``LCIAFactors`` to every
    scenario, and these analyses mutate them.
    """
    return deepcopy(get(key).build(lib or load_library()))
