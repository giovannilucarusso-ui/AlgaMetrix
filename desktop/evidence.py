"""Evidence classes for the validation page.

``data/validation_references.yaml`` is the short list the desktop app shows:
one row per (paper, metric) with the paper's value next to the model's. What a
row *depends on* is recorded elsewhere, per study, in
``data/studies/studies.yaml`` as ``evidence_class``. This module joins the two
by DOI, or by first author and year when the reference carries no DOI, so the
page can print the class next to every row and never present a calibrated
reproduction as an independent test. Qt-free; reads the YAML directly so the
desktop app does not import the paper package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from algametrix.library import DEFAULT_DATA_DIR

#: One line per class, in the words of docs/VALIDATION.md.
CLASS_MEANING = {
    "retrospective_untuned": (
        "The source's own assumptions were entered without adjusting anything to its "
        "reported endpoint. Untuned, but not blind: the endpoint was available."),
    "component_informed": (
        "A published aggregate outcome of the source was used to build one or more "
        "model inputs, so part of the target appears on both sides. Not an "
        "independent endpoint test."),
    "calibrated": (
        "The scenario was deliberately configured to reproduce a reference simulator "
        "or case study, to show the engine agrees with it under matched assumptions."),
    "range": (
        "A plausibility check against a published envelope. Never turned into a "
        "percentage deviation from an envelope midpoint."),
    "excluded": (
        "The reported figures could not be traced to the cited source. The record "
        "stays in the dataset with its reason, and enters no population."),
    "none": "A literature point that enters descriptive statistics only; not a reconstruction.",
}

CLASS_LABEL = {
    "retrospective_untuned": "retrospective, untuned",
    "component_informed": "component-informed",
    "calibrated": "calibrated",
    "range": "range check",
    "excluded": "excluded",
    "none": "descriptive only",
}

#: Said on the page itself, above the table. From docs/VALIDATION.md.
CAVEATS = (
    "None of these is a prospective validation: every source was already published "
    "when the scenario was built, and no prediction was registered before the target "
    "was read. The class says what each comparison depends on, not how well it did. "
    "Classes are never pooled, and only retrospective-untuned rows carry a reported "
    "range. Several rows of one paper are several comparisons and one independent source."
)


@dataclass(frozen=True)
class EvidenceRecord:
    study_id: str
    short_citation: str
    scenario_label: str
    study_type: str
    evidence_class: str
    independence_group: str
    doi: str
    author_overlap: bool

    @property
    def class_label(self) -> str:
        return CLASS_LABEL.get(self.evidence_class, self.evidence_class or "unknown")

    @property
    def class_meaning(self) -> str:
        return CLASS_MEANING.get(self.evidence_class, "")


def _text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def load_records(data_dir: Path | str | None = None) -> list[EvidenceRecord]:
    """Every study record that carries an evidence class. Empty when the file is absent."""
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    return list(_records_at(str(base)))


@lru_cache(maxsize=4)
def _records_at(base: str) -> tuple[EvidenceRecord, ...]:
    # The study file is a thousand lines of YAML; one parse per process is enough
    # for a window that only reads it, and every main window would otherwise pay it.
    path = Path(base) / "studies" / "studies.yaml"
    if not path.is_file():
        return ()
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    out = []
    for d in doc.get("studies") or []:
        if not isinstance(d, dict):
            continue
        out.append(EvidenceRecord(
            study_id=_text(d.get("study_id")),
            short_citation=_text(d.get("short_citation")),
            scenario_label=_text(d.get("scenario_label")),
            study_type=_text(d.get("study_type")),
            evidence_class=_text(d.get("evidence_class")),
            independence_group=_text(d.get("independence_group")),
            doi=_text(d.get("doi")).lower(),
            author_overlap=bool(d.get("author_overlap_with_algametrix", False)),
        ))
    return tuple(out)


_YEAR = re.compile(r"(19|20)\d{2}")
_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)


def _surname(text: str) -> str:
    """First author's surname, lower-case, from a citation string."""
    head = re.split(r"[,;(]| et al| and ", text, maxsplit=1)[0]
    words = [w for w in re.split(r"\s+", head.strip()) if w]
    return words[0].lower().strip(".") if words else ""


def match(paper: str, url: str, records: list[EvidenceRecord]) -> EvidenceRecord | None:
    """The study record a validation reference belongs to, or ``None``.

    DOI first: a DOI in the reference's URL that equals a record's DOI is an
    exact join. Otherwise the first author's surname and the year have to agree,
    which is enough for the short list the app ships.
    """
    doi = _DOI.search(url or "")
    if doi:
        wanted = doi.group(0).rstrip(".").lower()
        for r in records:
            if r.doi and (r.doi == wanted or wanted.startswith(r.doi) or r.doi.startswith(wanted)):
                return r
    surname = _surname(paper or "")
    year = _YEAR.search(paper or "")
    if not surname or not year:
        return None
    y = year.group(0)
    for r in records:
        if r.short_citation.lower().startswith(surname) and y in r.short_citation:
            return r
    return None


def classify(references, records: list[EvidenceRecord] | None = None) -> list:
    """``[(reference, record or None), ...]`` for a list of validation references."""
    records = load_records() if records is None else records
    return [(ref, match(ref.paper, ref.url, records)) for ref in references]
