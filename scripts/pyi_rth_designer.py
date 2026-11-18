"""PyInstaller runtime hook for the Process Designer preview build.

AlgaMetrix.spec only adds it when the build is made with
ALGAMETRIX_BUILD_DESIGNER=1. It runs before desktop.features reads the flag, so
the designer is on at start-up; ALGAMETRIX_PROCESS_DESIGNER=0 still turns it off.
"""

import os

os.environ.setdefault("ALGAMETRIX_PROCESS_DESIGNER", "1")
