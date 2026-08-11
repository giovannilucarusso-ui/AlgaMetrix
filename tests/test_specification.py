"""The printed equations must be the equations the software runs.

This is a documentation-fidelity test and nothing more. It restates each
equation of the specification from the printed formula and compares it against
what the engine returns, over the whole scenario suite. It says nothing about
whether the model is right — that is validation, and it lives elsewhere.

The reason it exists: peer review asked for the governing equations because
source code does not define a model. Writing them by hand creates a second
artefact that can drift from the first, and a specification that has drifted is
worse than no specification, because it misleads a reader who trusts it. This
test is what stops the drift from being silent.
"""

from __future__ import annotations

import pytest

from algametrix.library import load_library
from algametrix.paper import specification, suite


def _cases():
    lib = load_library()
    cases, _ = suite.distinct_cases(lib)
    return lib, cases


def test_every_printed_equation_matches_the_engine_on_every_scenario():
    lib, cases = _cases()
    disagreements = []
    evaluated = 0
    for case in cases:
        for chk in specification.check_against_engine(case.scenario(lib), case.label):
            evaluated += 1
            if not chk.agrees:
                disagreements.append(
                    f"{chk.equation} on {chk.scenario}: stated {chk.stated!r} "
                    f"vs engine {chk.engine!r} (relative {chk.residual:.2e})")
    assert not disagreements, "\n".join(disagreements)
    assert evaluated > 200, f"only {evaluated} equation evaluations ran"


def test_every_checkable_equation_is_exercised_somewhere():
    """An equation whose check never runs is an equation nobody is holding.

    Equations that carry a ``stated``/``engine`` pair must be evaluated on at
    least one scenario; if a guard silently excludes one everywhere, the
    specification would claim coverage it does not have.
    """
    lib, cases = _cases()
    checkable = {eq.key for eq in specification.equations()
                 if eq.stated is not None and eq.engine is not None}
    seen = set()
    for case in cases:
        for chk in specification.check_against_engine(case.scenario(lib), case.label):
            seen.add(chk.equation)
    assert checkable - seen == set(), f"never evaluated: {sorted(checkable - seen)}"


def test_the_specification_covers_what_the_review_asked_for():
    """The reviewer named the areas by name; each must have at least one equation."""
    keys = {eq.key for eq in specification.equations()}
    for prefix in ("inv.", "tea.equipment", "tea.dfc", "tea.investment", "tea.materials",
                   "tea.utilities", "tea.facility", "tea.aoc", "tea.cost", "tea.profit",
                   "tea.cashflow", "tea.npv", "lca.", "alloc."):
        assert any(k.startswith(prefix) for k in keys), prefix


def test_every_equation_names_where_it_is_implemented():
    for eq in specification.equations():
        assert eq.implemented_in, eq.key
        assert eq.latex.strip(), eq.key
        assert eq.description.strip(), eq.key


def test_the_assumptions_that_are_not_neutral_are_stated():
    """The three the equations would otherwise smuggle past a reader."""
    titles = " | ".join(t for t, _ in specification.ASSUMPTIONS).lower()
    assert "linear in capacity" in titles
    assert "fixed annual cost" in titles
    assert "no return on capital" in titles


def test_the_main_text_subset_is_a_subset_and_is_checked():
    """What the manuscript prints must be under the same fidelity check.

    The reduced set exists so the main text is not merely descriptive. If a core
    equation had no numerical check it would be the one place where the paper
    could print an equation the software does not run.
    """
    eqs = specification.equations()
    core = [e for e in eqs if e.core]
    assert core, "no equation is marked for the main text"
    assert len(core) < len(eqs), "the reduced set is not reduced"
    for eq in core:
        assert eq.core_gloss.strip(), f"{eq.key} has no one-line gloss"
        assert eq.stated is not None and eq.engine is not None, \
            f"{eq.key} is printed in the main text but never checked"

    # Both trophic routes must be represented, or the paper describes half the
    # model in symbols and the other half in prose.
    keys = {e.key for e in core}
    assert "inv.carbon.photo" in keys and "inv.carbon.hetero" in keys
    # And the argument the paper rests on: one inventory, two contractions.
    assert "tea.cost" in keys and "lca.impact" in keys


def test_every_cross_reference_names_a_section_that_exists():
    """A pointer to a section the SI does not have is worse than no pointer."""
    sections = {f"S{n}" for n in range(9)}
    for where, cited, what in specification.CROSS_REFERENCES:
        for token in cited.replace(",", " ").split():
            assert token in sections, f"{where} cites {token!r}"
        assert where.strip() and what.strip()


def test_symbols_carry_a_unit_and_a_source():
    for sym in specification.SYMBOLS:
        assert sym.unit.strip(), sym.latex
        assert sym.source.strip(), sym.latex
        assert sym.description.strip(), sym.latex


@pytest.mark.parametrize("attr", ["carbon_accounting", "custom_biogenic_credit_fraction"])
def test_the_biogenic_equation_reads_the_fields_it_claims_to(attr):
    lib = load_library()
    assert hasattr(lib.lcia, attr), attr
