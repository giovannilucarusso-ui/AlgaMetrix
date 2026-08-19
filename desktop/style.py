"""Blueprint stylesheet (QSS) for the desktop app.

A light, technical "engineering drafting" theme: cool paper ground, white cards,
thin blue-grey hairlines and a single drafting-blue accent. Layout metrics
(paddings, font sizes, group-title geometry) are kept identical to a known-good
light theme so the recolour introduces no clipping or text overlap.
"""

# Drafting blue accent (primary) and its darker shade (values, hovers, selection).
# This is the UI (QSS) accent only; the matplotlib charts keep their own colours.
ACCENT = "#1f5f9e"
ACCENT_DARK = "#12406e"

# Palette (named so the values read as chosen, not inherited).
_PAPER = "#e9eef3"       # cool paper ground (central background)
_CARD = "#ffffff"        # panels / cards / chart canvases
_HEADER = "#eef3f8"      # table headers / raised strips
_TAB_IDLE = "#dde5ee"    # unselected tab
_LINE = "#c6d3e0"        # hairline rules / borders
_LINE_SOFT = "#dbe3ec"   # table gridlines (softer)
_TEXT = "#1d2a38"        # primary ink
_DIM = "#5c7183"         # secondary ink / labels
_FAINT = "#8ea1b3"       # tertiary (units)

STYLESHEET = f"""
QMainWindow, QWidget#central {{ background: {_PAPER}; }}
QWidget {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 13px; color: {_TEXT}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QGroupBox {{
    font-weight: 600;
    border: 1px solid {_LINE};
    border-radius: 8px;
    margin-top: 16px;
    background: {_CARD};
    padding: 8px 10px 10px 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {ACCENT};
    font-weight: 700;
}}

/* Combo boxes and spin boxes are left with their NATIVE frame on purpose.
   Qt's stylesheet engine, once it styles the box, stops drawing the native
   drop-down / up-down arrows and expects arrow images — and Qt QSS does not accept
   data: URIs for those images, so a themed box would leave the arrows invisible (a
   spin box whose up-arrow can't be seen or clicked). Keeping these controls native
   guarantees visible, correctly-positioned, clickable arrows. The Blueprint identity
   is carried by the cards, tabs, tables, buttons and charts around them. */

/* Draggable divider between the input column and the results panel. */
QSplitter::handle:horizontal {{ width: 9px; background: {_PAPER}; border-left: 1px solid {_LINE}; }}
QSplitter::handle:horizontal:hover {{ background: #d6e2ee; }}
QSplitter::handle:vertical {{ height: 9px; background: {_PAPER}; border-top: 1px solid {_LINE}; }}
QSplitter::handle:vertical:hover {{ background: #d6e2ee; }}

QLabel#h1 {{ font-size: 18px; font-weight: 700; color: {ACCENT_DARK}; }}
QLabel#subtle {{ color: {_DIM}; }}

QFrame#kpiCard {{ background: {_CARD}; border: 1px solid {_LINE}; border-radius: 8px; }}
QLabel#kpiTitle {{ color: {_DIM}; font-size: 11px; font-weight: 600; }}
QLabel#kpiValue {{ color: {ACCENT_DARK}; font-size: 20px; font-weight: 800; }}
QLabel#kpiUnit  {{ color: {_FAINT}; font-size: 10px; }}

QTabWidget::pane {{ border: 1px solid {_LINE}; border-radius: 8px; background: {_CARD}; top: -1px; }}
QTabBar::tab {{
    padding: 8px 16px; margin-right: 2px;
    background: {_TAB_IDLE}; border-top-left-radius: 7px; border-top-right-radius: 7px;
    color: #3f5568;
}}
QTabBar::tab:selected {{ background: {_CARD}; color: {ACCENT_DARK}; font-weight: 700; }}

QTableWidget {{ border: none; gridline-color: {_LINE_SOFT}; background: {_CARD}; }}
QHeaderView::section {{ background: {_HEADER}; padding: 6px; border: none; font-weight: 600; color: #41576b; }}

QPushButton {{
    background: {ACCENT}; color: white; border: none; border-radius: 5px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {ACCENT_DARK}; }}
QPushButton:disabled {{ background: #aeb9c6; }}

QMenuBar {{ background: {_CARD}; border-bottom: 1px solid #cdd8e3; }}
QMenuBar::item:selected {{ background: #e3edf6; }}
QStatusBar {{ background: {_CARD}; border-top: 1px solid #cdd8e3; color: {_DIM}; }}
"""

# A refused scenario has to look refused. Red while it blocks the run, amber
# while it is only worth a second look.
STYLESHEET += """
QLabel#issueBanner {
    border-radius: 6px;
    padding: 8px 10px;
    background: #fff4e5;
    border: 1px solid #e0a458;
    color: #7a4b00;
}
QLabel#issueBanner[blocking="true"] {
    background: #fdecea;
    border: 1px solid #d9534f;
    color: #8b1a17;
}
"""
