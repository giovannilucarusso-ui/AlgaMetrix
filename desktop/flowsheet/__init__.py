"""Interactive process flowsheet ("Process Designer").

A SuperPro-style canvas where each unit operation is a draggable block that can
be wired to others with material streams. The heavy lifting lives in:

* :mod:`model`   - the serialisable data model, the unit-operation registry and a
  first-pass topological mass-balance solver.
* :mod:`builder` - turns a TEA/LCA :class:`~microalgae_tea_lca.models.Scenario`
  into a ready-made flowsheet (pure, no Qt).
* :mod:`scene`   - the interactive ``QGraphicsScene`` (nodes, ports, edges).
* :mod:`editor`  - the composite widget (palette + canvas + properties panel).

:class:`FlowsheetEditor` is imported lazily so that the pure model and builder
(and their tests) never pull in Qt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .builder import flowsheet_from_scenario

if TYPE_CHECKING:
    from .editor import FlowsheetEditor

__all__ = ["FlowsheetEditor", "flowsheet_from_scenario"]


def __getattr__(name: str):
    # Lazy import keeps `desktop.flowsheet` (and builder tests) Qt-free.
    if name == "FlowsheetEditor":
        from .editor import FlowsheetEditor

        return FlowsheetEditor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
