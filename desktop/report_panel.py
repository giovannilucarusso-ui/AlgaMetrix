"""The report page: what the PDF will contain, the basis it states, the exports."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from algametrix import __version__

from .features import PROCESS_DESIGNER
from .i18n import tr
from .widgets import button, label

_PAGES = (
    ("cover", "Cover: key results with their units and basis"),
    ("tea", "Techno-economic charts: operating cost and capital by item"),
    ("cost_table", "Production cost breakdown table"),
    ("lca", "Life-cycle charts and impact categories"),
    ("method", "Life-cycle method, boundary and limitations for this scenario"),
    ("inventory_chart", "Electricity by stage"),
    ("inventory", "Inventory table per kg of dry biomass"),
)
_CONDITIONAL = (
    ("products", "Products and allocation", "a case with more than one product"),
    ("flowsheet", "Process flow diagram and stream table",
     "the Process Designer (not in this build)" if not PROCESS_DESIGNER
     else "a diagram built in the Process Designer"),
    ("sensitivity", "Sensitivity sweep", "a sweep run on the Sensitivity page"),
    ("uncertainty", "Monte Carlo uncertainty", "a run on the Uncertainty page"),
    ("compare", "Scenario comparison", "snapshots taken on the Compare page"),
)


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(8)
    lay.addWidget(label(title, "h2"))
    return card, lay


def build(win) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(10)
    lay.addWidget(label(
        tr("A multi-page A4 report of the current case, built from the same results as "
           "the screens. Every page states the functional unit and the basis of its numbers."),
        "subtle", wrap=True))

    pages, pl = _card(tr("What the PDF contains"))
    win.lbl_report_pages = QLabel("")
    win.lbl_report_pages.setTextFormat(Qt.RichText)
    win.lbl_report_pages.setWordWrap(True)
    win.lbl_report_pages.setTextInteractionFlags(Qt.TextSelectableByMouse)
    pl.addWidget(win.lbl_report_pages)
    lay.addWidget(pages)

    basis, bl = _card(tr("Basis stated in the report"))
    win.lbl_report_basis = QLabel("")
    win.lbl_report_basis.setTextFormat(Qt.RichText)
    win.lbl_report_basis.setWordWrap(True)
    win.lbl_report_basis.setTextInteractionFlags(Qt.TextSelectableByMouse)
    bl.addWidget(win.lbl_report_basis)
    lay.addWidget(basis)

    row = QHBoxLayout()
    row.setSpacing(8)
    win.btn_export_pdf = button(tr("Export PDF report…"), "primary", win.export_process_report,
                                "Write the report to a PDF file", "Ctrl+P")
    win.btn_export_json = button(tr("Export results (JSON)…"), "secondary", win.export_results,
                                 "Write the results, both bases and the scenario that made them",
                                 "Ctrl+E")
    win.btn_save_case = button(tr("Save scenario…"), "secondary", win.save_scenario,
                               "Write the whole case to a JSON file you can reopen", "Ctrl+S")
    row.addWidget(win.btn_export_pdf)
    row.addWidget(win.btn_export_json)
    row.addWidget(win.btn_save_case)
    row.addStretch(1)
    lay.addLayout(row)
    lay.addWidget(label(
        tr("Exports are refused while the case is not admissible: a number the model "
           "cannot have must not leave the application in a file."), "caption", wrap=True))
    lay.addStretch(1)
    refresh(win)
    return w


def refresh(win) -> None:
    r = win.results
    items = [f"<li>{tr(text)}</li>" for _key, text in _PAGES]
    has = {
        "products": bool(r is not None and r.products and len(r.products) > 1),
        "flowsheet": bool(PROCESS_DESIGNER and getattr(win, "flowsheet_editor", None) is not None),
        "sensitivity": bool(getattr(win, "_last_sensitivity", None)),
        "uncertainty": bool(getattr(win, "_last_uncertainty", None)),
        "compare": bool(getattr(win, "_snapshots", None)),
    }
    for key, text, needs in _CONDITIONAL:
        if has.get(key):
            items.append(f"<li>{tr(text)} <span style='color:#006300'>— included</span></li>")
        else:
            items.append(f"<li style='color:#667283'>{tr(text)} — needs {needs}</li>")
    win.lbl_report_pages.setText("<ul style='margin:0 0 0 16px; padding:0'>"
                                 + "".join(items) + "</ul>")
    ready = r is not None
    for btn in (win.btn_export_pdf, win.btn_export_json):
        btn.setEnabled(ready)
        btn.setToolTip("" if ready else tr("Not available: the case is not admissible."))
    basis_html = getattr(win, "_basis_html", "")
    version = f"<p style='margin:6px 0 0 0; color:#667283'>AlgaMetrix {__version__}</p>"
    win.lbl_report_basis.setText((basis_html or tr("Compute an admissible case to see its basis."))
                                 + version)
