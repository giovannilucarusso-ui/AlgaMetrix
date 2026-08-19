"""Launch the AlgaMetrix desktop app.

    python run_desktop.py
    python run_desktop.py --self-test    # build the default case and exit
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
