# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the desktop application, on Windows and on macOS.

One spec for both, because there is one application: the analysis, the data
library and the entry point are identical and only the container differs. What
the platform decides is written out below rather than kept in two files that
would drift.
"""
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

MACOS = sys.platform == "darwin"

hiddenimports = ['openpyxl']
hiddenimports += collect_submodules('algametrix')
hiddenimports += collect_submodules('desktop')

# The Process Designer is not in released builds (see desktop/features.py). Its
# pure model and builder stay: the PDF report imports desktop.flowsheet.model.
# What is left out is the interactive Qt canvas, so the feature cannot be
# reached in a shipped build at all - not by a flag, not by accident.
PROCESS_DESIGNER_MODULES = [
    'desktop.flowsheet.editor',
    'desktop.flowsheet.scene',
    'desktop.flowsheet.view',
    'desktop.flowsheet.icons',
]
hiddenimports = [m for m in hiddenimports if m not in PROCESS_DESIGNER_MODULES]

# The icon, in the container each platform reads. Both are generated from the
# same artwork; scripts/make_icns.py writes the .icns from the .ico so the two
# cannot come to show different marks.
ICON = 'desktop/assets/algametrix.icns' if MACOS else 'desktop/assets/algametrix.ico'

# UPX is left off on macOS. It rewrites the Mach-O headers of every bundled
# dylib, which breaks the signature the bundle needs in order to launch at all
# on Apple Silicon. On Windows it only makes the download smaller.
USE_UPX = not MACOS

# The version the bundle reports to macOS, read from the one place that defines
# it. Parsed rather than imported: this file runs before the package is
# importable, and a build must not depend on the interpreter finding src/.
VERSION = re.search(
    r'^__version__ = "([^"]+)"',
    Path('src/algametrix/__init__.py').read_text(encoding='utf-8'),
    re.M,
).group(1)


a = Analysis(
    ['run_desktop.py'],
    pathex=['src', '.'],
    binaries=[],
    datas=[('data', 'data'), ('desktop/assets', 'desktop/assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['streamlit', 'plotly', 'tkinter', 'pytest'] + PROCESS_DESIGNER_MODULES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AlgaMetrix',
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=USE_UPX,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=USE_UPX,
    upx_exclude=[],
    name='AlgaMetrix',
)

if MACOS:
    # macOS runs applications out of a bundle, not a folder of loose files: an
    # .app is what a Mac user can double-click, drag into /Applications and see
    # named and iconed the way every other application is.
    app = BUNDLE(
        coll,
        name='AlgaMetrix.app',
        icon=ICON,
        bundle_identifier='io.github.giovannilucarusso-ui.algametrix',
        version=VERSION,
        info_plist={
            'CFBundleName': 'AlgaMetrix',
            'CFBundleDisplayName': 'AlgaMetrix',
            'CFBundleShortVersionString': VERSION,
            'CFBundleVersion': VERSION,
            # Without this the window is drawn at 1x and upscaled, which on a
            # Retina display makes every label and axis look soft.
            'NSHighResolutionCapable': True,
            # The app is a single-window tool, not a document editor.
            'LSApplicationCategoryType': 'public.app-category.productivity',
            'LSMinimumSystemVersion': '11.0',
            'NSHumanReadableCopyright': 'MIT licence. Giovanni Luca Russo.',
        },
    )
