"""Cross-study evidence layer behind the AlgaMetrix methods paper.

This package holds everything that is *about* the published literature rather
than about a single scenario:

* :mod:`schema`          - controlled vocabularies and the study record
* :mod:`studies`         - the machine-readable study dataset loader
* :mod:`reconstructions` - study_id -> engine scenario builders (Tier B)
* :mod:`indices`         - price indices with provenance + normalization
* :mod:`endpoints`       - economic-endpoint classification and eligibility
* :mod:`stats`           - spread statistics with explicit ratio conventions
* :mod:`harmonization`   - constant-cohort cost harmonization (Analyses A and B)
* :mod:`carbon`          - biogenic-carbon accounting modes, gross vs net GWP
* :mod:`gwp`             - GWP analysis populations
* :mod:`archetypes`      - the archetypes used by the global-sensitivity work
* :mod:`sobol`           - Saltelli/Jansen Sobol estimators + benchmarks
* :mod:`mcuncertainty`   - Monte-Carlo uncertainty by source group
* :mod:`report`          - the ``results/*.txt`` writers

The engine itself (``algametrix.inventory`` / ``tea`` / ``lca``) does not
import anything from here: the evidence layer sits *on top of* the single shared
mass-and-energy balance, never inside it.
"""

from __future__ import annotations

__all__ = [
    "schema",
    "studies",
    "reconstructions",
    "indices",
    "endpoints",
    "stats",
    "harmonization",
    "carbon",
    "gwp",
    "archetypes",
    "sobol",
    "mcuncertainty",
    "report",
]
