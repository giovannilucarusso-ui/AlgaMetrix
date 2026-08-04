"""Load the machine-readable study dataset and select cohorts from it.

The dataset itself lives in ``data/studies/studies.yaml``. This module turns it
into :class:`~algametrix.paper.schema.StudyRecord` objects and provides
the *only* sanctioned way to build a cohort, so that a cohort used at one stage
of an analysis can be compared, by identity, with the cohort used at the next.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

import yaml

from .schema import StudyRecord

if getattr(sys, "frozen", False):
    _ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DEFAULT_STUDY_DIR = _ROOT / "data" / "studies"
else:
    DEFAULT_STUDY_DIR = Path(__file__).resolve().parents[3] / "data" / "studies"


@dataclass
class Dataset:
    """The full evidence set plus the metadata describing how it was assembled."""

    records: list[StudyRecord]
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def by_id(self, study_id: str) -> StudyRecord:
        for r in self.records:
            if r.study_id == study_id:
                return r
        raise KeyError(study_id)

    @property
    def ids(self) -> list[str]:
        return [r.study_id for r in self.records]

    def select(self, predicate: Callable[[StudyRecord], bool]) -> "Cohort":
        return Cohort(sorted((r for r in self.records if predicate(r)),
                             key=lambda r: r.study_id))


class CohortMismatch(AssertionError):
    """Raised when two stages of a sequential analysis do not share a cohort.

    This is the guard that makes a "harmonization collapsed the spread" claim
    checkable: if the membership changed between stages, part of the collapse is
    study exclusion, not harmonization.
    """


@dataclass(frozen=True)
class Cohort:
    """An immutable, ordered set of study records with an auditable identity."""

    records: tuple[StudyRecord, ...]

    def __init__(self, records: Iterable[StudyRecord]):
        object.__setattr__(self, "records", tuple(records))

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(r.study_id for r in self.records)

    def filter(self, predicate: Callable[[StudyRecord], bool]) -> "Cohort":
        return Cohort(r for r in self.records if predicate(r))

    def require_same_as(self, other: "Cohort", stage_a: str, stage_b: str) -> None:
        """Raise unless ``self`` and ``other`` contain exactly the same studies."""
        if set(self.ids) != set(other.ids):
            only_a = sorted(set(self.ids) - set(other.ids))
            only_b = sorted(set(other.ids) - set(self.ids))
            raise CohortMismatch(
                f"cohort changed between '{stage_a}' (n={len(self)}) and "
                f"'{stage_b}' (n={len(other)}); "
                f"only in {stage_a}: {only_a or 'none'}; "
                f"only in {stage_b}: {only_b or 'none'}"
            )


def _to_record(d: dict) -> StudyRecord:
    known = {f for f in StudyRecord.__dataclass_fields__}
    unknown = set(d) - known
    if unknown:
        raise ValueError(
            f"{d.get('study_id', '<no id>')}: unknown field(s) {sorted(unknown)}. "
            "Add them to StudyRecord or fix the YAML."
        )
    return StudyRecord(**d)


def load_dataset(path: Path | str | None = None) -> Dataset:
    """Read ``studies.yaml``. Vocabulary violations raise at load time."""
    base = Path(path) if path is not None else DEFAULT_STUDY_DIR / "studies.yaml"
    with base.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    records = [_to_record(d) for d in raw.get("studies", [])]
    seen: set[str] = set()
    for r in records:
        if r.study_id in seen:
            raise ValueError(f"duplicate study_id {r.study_id!r}")
        seen.add(r.study_id)
    return Dataset(records=records, meta=raw.get("meta", {}) or {})


@lru_cache(maxsize=1)
def default_dataset() -> Dataset:
    """The repository dataset, loaded once."""
    return load_dataset()
