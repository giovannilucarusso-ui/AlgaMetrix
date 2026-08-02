"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from desktop.main_window import MainWindow


def main() -> int:
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
