"""Interactive process flowsheet ("Process Designer").

A SuperPro-style canvas where each unit operation is a draggable block that can
be wired to others with material streams. The heavy lifting lives in three
modules:

* :mod:`model`  - the serialisable data model, the unit-operation registry and a
  first-pass topological mass-balance solver.
* :mod:`scene`  - the interactive ``QGraphicsScene`` (nodes, ports, edges).
* :mod:`editor` - the composite widget (palette + canvas + properties panel).
"""

from __future__ import annotations

from .editor import FlowsheetEditor

__all__ = ["FlowsheetEditor"]
