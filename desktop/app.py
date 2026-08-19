"""Application entry point.

The ``algametrix`` console command lands here. The engine installs without Qt —
a script that only needs the TEA/LCA calculation should not download a 100 MB
GUI toolkit — so this module checks for the desktop dependencies and says what
to install instead of failing with an import traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

#: What ``pip install algametrix`` deliberately leaves out, and why each is needed.
DESKTOP_REQUIREMENTS = {
    "PySide6": "the Qt user interface",
    "matplotlib": "the charts in the results panel",
    "openpyxl": "reading SuperPro Excel reports and writing spreadsheet exports",
}


def missing_desktop_requirements() -> list[str]:
    """Which desktop dependencies are not importable here."""
    import importlib.util

    return [name for name in DESKTOP_REQUIREMENTS
            if importlib.util.find_spec(name) is None]


def _explain_missing(missing: list[str]) -> str:
    lines = [
        "AlgaMetrix's desktop application needs packages this environment does "
        "not have:",
        "",
    ]
    lines += [f"  · {name} — {DESKTOP_REQUIREMENTS[name]}" for name in missing]
    lines += [
        "",
        "Install them with:",
        "",
        '    pip install "algametrix[desktop]"',
        "",
        "The engine itself is already installed and usable from Python:",
        "",
        "    from algametrix.library import load_library",
        "    from algametrix.scenario import run_scenario",
    ]
    if sys.platform.startswith("linux"):
        lines += [
            "",
            "On a minimal Linux image Qt also needs its system libraries:",
            "",
            "    sudo apt-get install libegl1 libgl1 libxkbcommon-x11-0 "
            "libdbus-1-3 libxcb-cursor0",
        ]
    return "\n".join(lines)


def self_test(out_path: str | None = None) -> int:
    """Build the default scenario in a real window and report, then exit.

    This is what a smoke test of the shipped executable can actually do: start
    the application, construct the whole window, run the engine once and say
    what came out — without entering the event loop, and with a exit code CI can
    read. A build that imports but cannot compute fails here rather than in the
    hands of whoever downloaded it.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from algametrix import __version__

    from desktop.main_window import MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = MainWindow()
    r = window.results
    ok = (r is not None
          and r.tea.production_cost_eur_per_kg > 0
          and r.inventory.annual_biomass_kg > 0)
    lines = [
        f"AlgaMetrix {__version__} self-test: {'PASS' if ok else 'FAIL'}",
        f"  organism        : {window.organism.name}",
        f"  system          : {window.system.name}",
        f"  scale           : {window.scale:,.0f}",
    ]
    if r is not None:
        lines += [
            f"  production cost : {r.tea.production_cost_eur_per_kg:,.4f} EUR/kg",
            f"  GWP             : {r.lca.gwp_kg_co2eq_per_kg:,.4f} kg CO2-eq/kg",
            f"  annual output   : {r.inventory.annual_biomass_kg / 1000:,.1f} t/yr",
        ]
    else:
        lines.append("  the default scenario did not compute")
    report = "\n".join(lines)
    if out_path:
        # A windowed build has no console attached, so the report also goes to a
        # file the workflow can print.
        Path(out_path).write_text(report + "\n", encoding="utf-8")
    print(report)
    window.close()
    del app
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    missing = missing_desktop_requirements()
    if missing:
        print(_explain_missing(missing), file=sys.stderr)
        return 1

    if "--self-test" in argv:
        out = None
        if "--self-test-out" in argv:
            index = argv.index("--self-test-out") + 1
            out = argv[index] if index < len(argv) else None
        return self_test(out)

    from PySide6.QtWidgets import QApplication

    from desktop.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("AlgaMetrix")
    app.setOrganizationName("AlgaMetrix")

    # Language: use the saved choice, or ask once on first run (before building the UI).
    from desktop.i18n import LANGUAGES, load_saved_language, save_language, set_language

    lang = load_saved_language()
    if lang is None:
        from PySide6.QtWidgets import QInputDialog

        codes, names = list(LANGUAGES), list(LANGUAGES.values())
        name, ok = QInputDialog.getItem(
            None, "Language · Lingua · Idioma · Langue", "Select language:", names, 0, False
        )
        lang = codes[names.index(name)] if ok else "en"
        save_language(lang)
    set_language(lang)

    window = MainWindow()
    # Open filling the screen so the whole two-panel layout is visible immediately
    # (no need to maximise by hand on first launch).
    window.showMaximized()

    # Offer the guided setup wizard on launch; "Skip to full tool" goes straight in.
    from desktop.wizard import SetupWizard

    wizard = SetupWizard(window.lib, window)
    if wizard.exec():
        window.apply_scenario(wizard.scenario)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
