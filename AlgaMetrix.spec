# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

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
    icon='desktop/assets/algametrix.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='AlgaMetrix',
)
