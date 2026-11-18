"""Design tokens for the desktop app, and the Qt stylesheet built from them.

One place holds the colours, the type scale, the spacing steps and the radii
that every screen uses, so a card in the results panel, a page of the setup
wizard and a dialog on the validation page all come out of the same box of
parts. The module imports nothing from Qt: the PDF report (matplotlib) reads
the same tokens, and the Process Designer can adopt them once it lands.

Colour roles, not raw values, are what the rest of the code should name:
``INK`` for text, ``LINE`` for a hairline, ``ACCENT`` for the one interactive
colour, ``SUCCESS``/``WARNING``/``DANGER``/``INFO`` for a state. Every text
colour here clears a 4.5:1 contrast ratio on the white surface it sits on.
The chart palette is the validated categorical order of the data-viz
reference palette: assigned in fixed slot order, never cycled.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Colour
# --------------------------------------------------------------------------- #
# Surfaces: a cool near-white page, white cards and inputs.
CANVAS = "#f4f6f8"          # window / page background
SURFACE = "#ffffff"         # cards, inputs, tables, chart canvases
SURFACE_2 = "#f7f9fb"       # table headers, alternate rows, raised strips
SURFACE_3 = "#eef2f6"       # pressed / selected neutral background
LINE = "#d9dee4"            # borders and hairlines
LINE_SOFT = "#e8ecf0"       # table gridlines, dividers inside a card

# Ink. INK_3 is the lightest tone still at 4.5:1 on white.
INK = "#1a1f29"             # primary text
INK_2 = "#4b5565"           # secondary text, labels
INK_3 = "#667283"           # captions, units, axis text
INK_DISABLED = "#9aa3ae"    # disabled controls and their labels

# The one interactive colour, with its hover/pressed steps and tints. These are
# steps 550 / 600 / 650 / 100 / 150 of the data-viz blue ramp, so buttons and
# charts belong to the same family.
ACCENT = "#1c5cab"
ACCENT_HOVER = "#184f95"
ACCENT_PRESSED = "#104281"
ACCENT_SOFT = "#e6effb"     # selected row / hover tint
ACCENT_SOFT_2 = "#cde2fb"   # selection background
FOCUS = "#2a78d6"           # focus ring

# States. Each is a (text, background, border) triple that reads with an icon
# or a word next to it, never by colour alone.
SUCCESS = "#006300"
SUCCESS_BG = "#e6f4e6"
SUCCESS_LINE = "#8fcf8f"
WARNING = "#7a4b00"
WARNING_BG = "#fff4e5"
WARNING_LINE = "#e0a458"
DANGER = "#8b1a17"
DANGER_BG = "#fdecea"
DANGER_LINE = "#d9534f"
INFO = "#1c5cab"
INFO_BG = "#e8f0fb"
INFO_LINE = "#9ec5f4"

# Charts. SERIES is the validated categorical order (adjacent pairs pass the
# colour-vision checks on white); a single-series chart uses SERIES[0].
SERIES = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#6250d6",  # violet
    "#e34948",  # red
)
CHART_PRIMARY = SERIES[0]
CHART_EMPHASIS_GRAY = "#c5ccd3"
BURDEN = "#e34948"          # positive contribution to an impact
CREDIT = "#2a78d6"          # avoided burden / biogenic credit
CHART_GRID = "#e8ecf0"
CHART_AXIS = "#c5ccd3"
CHART_INK = INK
CHART_INK_2 = INK_2
CHART_MUTED = INK_3
CHART_SURFACE = SURFACE

# --------------------------------------------------------------------------- #
# Type scale (device-independent pixels), spacing and radii
# --------------------------------------------------------------------------- #
FONT_FAMILY = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'
FONT_MONO = '"Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace'

TEXT_XS = 11     # unit tags, captions in tight places
TEXT_SM = 12     # table captions, hints
TEXT_BASE = 13   # body and controls
TEXT_MD = 14     # section titles
TEXT_LG = 16     # page titles
TEXT_XL = 20     # window title strip
TEXT_KPI = 24    # the big number on a KPI tile

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

RADIUS_SM = 4
RADIUS = 6
RADIUS_LG = 10

#: Minimum height of a clickable control, so it can be hit with a finger or a
#: trackpad without aiming.
CONTROL_HEIGHT = 28

# Kept for callers that still import the old names.
ACCENT_DARK = ACCENT_PRESSED


# --------------------------------------------------------------------------- #
# Qt stylesheet
# --------------------------------------------------------------------------- #
def build_stylesheet() -> str:
    """The application stylesheet, rendered from the tokens above.

    Spin boxes, combo boxes and check boxes are given a frame and a focus ring
    but no replacement for their arrows and check marks, which the base style
    (Fusion) keeps drawing; a stylesheet that swaps them for images needs image
    files that a frozen build can lose.
    """
    return f"""
/* ---- base ------------------------------------------------------------- */
QWidget {{
    font-family: {FONT_FAMILY};
    font-size: {TEXT_BASE}px;
    color: {INK};
}}
QMainWindow, QDialog, QWizard, QWidget#central, QWidget#page {{ background: {CANVAS}; }}
QToolTip {{
    background: {INK};
    color: {SURFACE};
    border: 1px solid {INK};
    border-radius: {RADIUS_SM}px;
    padding: 6px 8px;
    font-size: {TEXT_SM}px;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {LINE}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {INK_DISABLED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {LINE}; border-radius: 3px; min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: {INK_DISABLED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- menus and bars --------------------------------------------------- */
QMenuBar {{
    background: {SURFACE};
    border-bottom: 1px solid {LINE};
    padding: 2px 4px;
}}
QMenuBar::item {{ padding: 5px 10px; border-radius: {RADIUS_SM}px; }}
QMenuBar::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS}px;
    padding: 6px;
}}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: {RADIUS_SM}px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu::item:disabled {{ color: {INK_DISABLED}; }}
QMenu::separator {{ height: 1px; background: {LINE_SOFT}; margin: 6px 4px; }}
QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {LINE};
    color: {INK_2};
    font-size: {TEXT_SM}px;
}}
QStatusBar::item {{ border: none; }}

/* ---- header strip ----------------------------------------------------- */
QFrame#header {{
    background: {SURFACE};
    border-bottom: 1px solid {LINE};
}}
QLabel#brand {{ font-size: {TEXT_LG}px; font-weight: 700; color: {ACCENT_PRESSED}; }}
QLabel#caseTitle {{ font-size: {TEXT_MD}px; font-weight: 600; color: {INK}; }}

/* ---- text roles ------------------------------------------------------- */
QLabel#h1 {{ font-size: {TEXT_LG}px; font-weight: 700; color: {INK}; }}
QLabel#h2 {{ font-size: {TEXT_MD}px; font-weight: 600; color: {INK}; }}
QLabel#h3 {{ font-size: {TEXT_BASE}px; font-weight: 600; color: {INK_2}; }}
QLabel#subtle {{ color: {INK_2}; }}
QLabel#caption {{ color: {INK_3}; font-size: {TEXT_SM}px; }}
QLabel#unit {{ color: {INK_3}; font-size: {TEXT_SM}px; }}
QLabel#link {{ color: {ACCENT}; }}
QLabel#sectionTitle {{ font-size: {TEXT_MD}px; font-weight: 600; color: {INK}; }}
QLabel#sectionStep {{
    font-size: {TEXT_XS}px; font-weight: 700; color: {ACCENT};
    background: {ACCENT_SOFT}; border-radius: 9px; padding: 1px 6px;
}}
QLabel#chip {{
    font-size: {TEXT_XS}px; color: {INK_2};
    background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 9px;
    padding: 2px 8px;
}}
QLabel#chipAccent {{
    font-size: {TEXT_XS}px; color: {ACCENT};
    background: {ACCENT_SOFT}; border: 1px solid {ACCENT_SOFT_2}; border-radius: 9px;
    padding: 2px 8px;
}}

/* ---- cards and sections ----------------------------------------------- */
QFrame#card, QFrame#section {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_LG}px;
}}
QFrame#sectionHeader {{ background: transparent; border: none; }}
QToolButton#sectionToggle {{
    border: none; background: transparent; color: {INK_3};
    font-size: {TEXT_SM}px; padding: 2px 4px;
}}
QToolButton#sectionToggle:hover {{ color: {ACCENT}; background: {ACCENT_SOFT}; border-radius: {RADIUS_SM}px; }}
QFrame#divider {{ background: {LINE_SOFT}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#basisBox {{
    background: {SURFACE_2};
    border: 1px solid {LINE_SOFT};
    border-radius: {RADIUS}px;
}}
QGroupBox {{
    font-weight: 600;
    border: 1px solid {LINE};
    border-radius: {RADIUS_LG}px;
    margin-top: 16px;
    background: {SURFACE};
    padding: 8px 10px 10px 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {INK};
}}

/* ---- KPI tiles -------------------------------------------------------- */
QFrame#kpiCard {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_LG}px;
}}
QFrame#kpiCard[state="empty"] {{ border: 1px dashed {LINE}; }}
QLabel#kpiTitle {{ color: {INK_2}; font-size: {TEXT_SM}px; font-weight: 600; }}
QLabel#kpiValue {{ color: {INK}; font-size: {TEXT_KPI}px; font-weight: 700; }}
QLabel#kpiValue[state="empty"] {{ color: {INK_DISABLED}; }}
QLabel#kpiUnit {{ color: {INK_2}; font-size: {TEXT_SM}px; }}
QLabel#kpiBasis {{ color: {INK_3}; font-size: {TEXT_XS}px; }}

/* ---- banners ---------------------------------------------------------- */
QLabel#issueBanner, QFrame#banner {{
    border-radius: {RADIUS}px;
    padding: 10px 12px;
    background: {WARNING_BG};
    border: 1px solid {WARNING_LINE};
    color: {WARNING};
}}
QLabel#issueBanner[blocking="true"] {{
    background: {DANGER_BG};
    border: 1px solid {DANGER_LINE};
    color: {DANGER};
}}
QFrame#banner QLabel {{ background: transparent; color: {WARNING}; }}
QFrame#banner[kind="info"] {{ background: {INFO_BG}; border-color: {INFO_LINE}; }}
QFrame#banner[kind="info"] QLabel {{ color: {INFO}; }}
QFrame#banner[kind="success"] {{ background: {SUCCESS_BG}; border-color: {SUCCESS_LINE}; }}
QFrame#banner[kind="success"] QLabel {{ color: {SUCCESS}; }}
QFrame#banner[kind="danger"] {{ background: {DANGER_BG}; border-color: {DANGER_LINE}; }}
QFrame#banner[kind="danger"] QLabel {{ color: {DANGER}; }}
QFrame#emptyState {{
    background: {SURFACE_2};
    border: 1px dashed {LINE};
    border-radius: {RADIUS_LG}px;
}}
QLabel#emptyTitle {{ color: {INK_2}; font-size: {TEXT_MD}px; font-weight: 600; }}
QLabel#emptyHint {{ color: {INK_3}; }}

/* ---- tabs ------------------------------------------------------------- */
QTabWidget::pane {{
    border: 1px solid {LINE};
    border-radius: {RADIUS_LG}px;
    background: {SURFACE};
    top: -1px;
}}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    padding: 8px 14px;
    margin-right: 2px;
    background: transparent;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    color: {INK_2};
}}
QTabBar::tab:hover {{ color: {ACCENT}; }}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:focus {{ border: 1px solid {FOCUS}; border-radius: {RADIUS_SM}px; }}
QTabBar QToolButton {{ border: none; background: {SURFACE_2}; }}

/* ---- tables ----------------------------------------------------------- */
QTableWidget, QTableView {{
    border: 1px solid {LINE_SOFT};
    border-radius: {RADIUS}px;
    gridline-color: {LINE_SOFT};
    background: {SURFACE};
    alternate-background-color: {SURFACE_2};
    selection-background-color: {ACCENT_SOFT_2};
    selection-color: {INK};
}}
QTableWidget::item, QTableView::item {{ padding: 4px 8px; }}
QHeaderView::section {{
    background: {SURFACE_2};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {LINE};
    border-right: 1px solid {LINE_SOFT};
    font-weight: 600;
    color: {INK_2};
    font-size: {TEXT_SM}px;
}}
QHeaderView::section:last {{ border-right: none; }}
QTableCornerButton::section {{ background: {SURFACE_2}; border: none; }}

/* ---- buttons ---------------------------------------------------------- */
QPushButton {{
    background: {ACCENT};
    color: {SURFACE};
    border: 1px solid {ACCENT};
    border-radius: {RADIUS}px;
    padding: 6px 14px;
    min-height: {CONTROL_HEIGHT - 14}px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton:focus {{ border: 2px solid {FOCUS}; padding: 5px 13px; }}
QPushButton:disabled {{ background: {SURFACE_3}; border-color: {LINE}; color: {INK_DISABLED}; }}
QPushButton[kind="secondary"] {{
    background: {SURFACE};
    color: {ACCENT};
    border: 1px solid {LINE};
}}
QPushButton[kind="secondary"]:hover {{ background: {ACCENT_SOFT}; border-color: {ACCENT_SOFT_2}; }}
QPushButton[kind="secondary"]:pressed {{ background: {ACCENT_SOFT_2}; }}
QPushButton[kind="secondary"]:disabled {{ color: {INK_DISABLED}; background: {SURFACE_2}; }}
QPushButton[kind="ghost"] {{
    background: transparent;
    color: {ACCENT};
    border: 1px solid transparent;
    font-weight: 600;
}}
QPushButton[kind="ghost"]:hover {{ background: {ACCENT_SOFT}; }}
QPushButton[kind="danger"] {{ background: {DANGER_LINE}; border-color: {DANGER_LINE}; }}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: 4px 6px;
    color: {INK_2};
}}
QToolButton:hover {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QToolButton:focus {{ border: 1px solid {FOCUS}; }}

/* ---- inputs ----------------------------------------------------------- */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS}px;
    padding: 3px 6px;
    min-height: {CONTROL_HEIGHT - 8}px;
    selection-background-color: {ACCENT_SOFT_2};
    selection-color: {INK};
}}
QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {INK_DISABLED}; }}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {FOCUS};
    padding: 2px 5px;
}}
QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background: {SURFACE_2};
    color: {INK_DISABLED};
    border-color: {LINE_SOFT};
}}
QDoubleSpinBox[issue="warning"], QSpinBox[issue="warning"] {{
    border: 2px solid {WARNING_LINE}; background: {WARNING_BG}; padding: 2px 5px;
}}
QDoubleSpinBox[issue="error"], QSpinBox[issue="error"] {{
    border: 2px solid {DANGER_LINE}; background: {DANGER_BG}; padding: 2px 5px;
}}
QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    width: 16px; border: none; background: transparent;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS}px;
    padding: 4px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
    outline: none;
}}
QCheckBox, QRadioButton {{ spacing: 8px; min-height: 22px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {INK_DISABLED}; }}
QLabel:disabled {{ color: {INK_DISABLED}; }}
QLineEdit#search {{ padding-left: 8px; }}

/* ---- splitter, progress ----------------------------------------------- */
QSplitter::handle:horizontal {{ width: 8px; background: {CANVAS}; }}
QSplitter::handle:horizontal:hover {{ background: {ACCENT_SOFT_2}; }}
QSplitter::handle:vertical {{ height: 8px; background: {CANVAS}; }}
QSplitter::handle:vertical:hover {{ background: {ACCENT_SOFT_2}; }}
QProgressBar {{
    border: 1px solid {LINE}; border-radius: {RADIUS_SM}px; background: {SURFACE_2};
    text-align: center; height: 10px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: {RADIUS_SM}px; }}

/* ---- wizard ----------------------------------------------------------- */
QWizard QFrame#wizardSide {{
    background: {SURFACE};
    border-right: 1px solid {LINE};
}}
QLabel#wizardStep {{ color: {INK_3}; padding: 4px 0; }}
QLabel#wizardStepCurrent {{ color: {ACCENT}; font-weight: 700; padding: 4px 0; }}
QLabel#wizardStepDone {{ color: {INK_2}; padding: 4px 0; }}
QWizardPage {{ background: {CANVAS}; }}
QMessageBox {{ background: {SURFACE}; }}
"""


#: Built once at import time; the name the rest of the app imports.
STYLESHEET = build_stylesheet()


def apply_to(app) -> None:
    """Install the theme on a running ``QApplication``: style, palette, stylesheet.

    Idempotent, so the main window can call it on construction and a second
    window or a test finds it already in place. Imported lazily so this module
    stays importable without Qt.
    """
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication, QStyleFactory

    if app is None or app.property("algametrix_theme_applied"):
        return
    if "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(CANVAS))
    palette.setColor(QPalette.WindowText, QColor(INK))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(SURFACE_2))
    palette.setColor(QPalette.Text, QColor(INK))
    palette.setColor(QPalette.Button, QColor(SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(INK))
    palette.setColor(QPalette.ToolTipBase, QColor(INK))
    palette.setColor(QPalette.ToolTipText, QColor(SURFACE))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor(SURFACE))
    palette.setColor(QPalette.Link, QColor(ACCENT))
    palette.setColor(QPalette.PlaceholderText, QColor(INK_DISABLED))
    palette.setColor(QPalette.Mid, QColor(LINE))
    palette.setColor(QPalette.Dark, QColor(INK_3))
    palette.setColor(QPalette.Light, QColor(SURFACE))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(INK_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(INK_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(INK_DISABLED))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
    app.setProperty("algametrix_theme_applied", True)
    if isinstance(app, QApplication):
        font = app.font()
        font.setFamily("Segoe UI")
        font.setPixelSize(TEXT_BASE)
        app.setFont(font)


def repolish(widget) -> None:
    """Re-apply the stylesheet after a dynamic property (``state``, ``kind``,
    ``issue``) changed, which Qt does not do on its own."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
