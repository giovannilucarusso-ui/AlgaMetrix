"""Render every screen of the desktop app off-screen, for a review or the docs.

    python scripts/ui_screenshots.py OUT_DIR

Uses Qt's offscreen platform, so it runs on a machine without a display. On
Windows the offscreen platform finds no fonts unless QT_QPA_FONTDIR points at
the system font folder; the script sets it when the folder exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform.startswith("win") and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from algametrix.templates import build_template  # noqa: E402
from desktop import theme  # noqa: E402
from desktop.main_window import MainWindow  # noqa: E402
from desktop.results_panel import TAB_TITLES  # noqa: E402
from desktop.wizard import SetupWizard  # noqa: E402

OMEGA3 = "Omega-3 oil (heterotrophic fermentation)"


def main(out_dir: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme.apply_to(app)

    def snap(widget, name):
        app.processEvents()
        app.processEvents()
        pm = widget.grab()
        pm.save(str(out / f"{name}.png"))
        print(f"{name}: {pm.width()}x{pm.height()}")

    w = MainWindow()
    w.resize(1440, 900)
    w.show()
    snap(w, "01_overview_default")
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        snap(w, f"02_tab_{i}_{TAB_TITLES[i].lower().replace(' ', '_')}")

    w.tabs.setCurrentIndex(0)
    w._spins[("system", "productivity")].setValue(0.0)
    snap(w, "13_inadmissible")
    w._spins[("system", "productivity")].setValue(20.0)
    w.input_search.setText("price")
    snap(w, "14_filter_price")
    w.input_search.setText("")

    w.apply_scenario(build_template(OMEGA3, w.lib))
    w.tabs.setCurrentIndex(0)
    snap(w, "03_overview_omega3")
    w.tabs.setCurrentIndex(1)
    snap(w, "03_costs_omega3")
    w.tabs.setCurrentIndex(2)
    snap(w, "03_lifecycle_omega3")
    w.tabs.setCurrentIndex(4)
    snap(w, "03_products_omega3")

    w.run_sensitivity()
    w.tabs.setCurrentIndex(5)
    snap(w, "04_sensitivity")
    w.spn_unc_n.setValue(300)
    w.run_uncertainty()
    w.tabs.setCurrentIndex(6)
    snap(w, "05_uncertainty")
    w.snapshot_scenario()
    w.spn_price.setValue(w.spn_price.value() * 1.2)
    w.snapshot_scenario()
    snap(w, "06_compare")

    w.load_bundled_reference("reference_superpro_omega3.csv")
    snap(w, "08_validation_reference")
    w.show_benchmarks()
    snap(w, "09_validation_benchmarks")
    w.show_validation_references()
    snap(w, "10_validation_library")
    w.show_market_prices()
    snap(w, "11_validation_market")
    w.tabs.setCurrentIndex(9)
    snap(w, "12_report")

    w.tabs.setCurrentIndex(0)
    w.resize(1180, 760)
    snap(w, "15_overview_1180")
    w.resize(1440, 900)

    wiz = SetupWizard(w.lib, w)
    wiz.show()
    app.processEvents()
    for i in range(7):
        snap(wiz, f"16_wizard_{i}")
        if i < 6:
            wiz.next()
            app.processEvents()
    wiz.close()
    w.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "screenshots"))
