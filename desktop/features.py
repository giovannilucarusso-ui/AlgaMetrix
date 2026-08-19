"""Which parts of the client this build exposes.

A feature can be finished enough to develop against and not finished enough to
hand to a researcher who will publish from it. This module is where that
distinction is written down, so it is one line to change rather than a branch to
maintain.

``PROCESS_DESIGNER``
    The SuperPro-style visual flowsheet editor (``desktop.flowsheet.editor``).
    Off in released builds: the pure model and builder underneath it are used by
    the PDF report and are well covered, but the interactive canvas is not ready
    to be relied on. Set ``ALGAMETRIX_PROCESS_DESIGNER=1`` to work on it.

    The released Windows build goes further and leaves the canvas modules out of
    the bundle entirely (see ``AlgaMetrix.spec``), so this flag cannot resurrect
    a half-finished feature in somebody else's hands.
"""

from __future__ import annotations

import os


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


#: The visual process flowsheet editor. Off by default; see the module docstring.
PROCESS_DESIGNER = _enabled("ALGAMETRIX_PROCESS_DESIGNER", default=False)
