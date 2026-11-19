"""Reusable widgets: chart canvas, KPI tile, section card, banners, tables.

Everything here is built from the tokens in :mod:`desktop.theme`, so a screen
assembled from these parts needs no colour or size of its own.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable

# matplotlib must use the same Qt binding as the app (PySide6).
os.environ.setdefault("QT_API", "pyside6")
import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .charts import apply_defaults, style_axes
from .fmt import DASH

# Chart colours the rest of the app may still import by their old names.
ACCENT = theme.CHART_PRIMARY
NEG = theme.CREDIT    # credits / negative contributions
POS = theme.BURDEN    # burdens


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    """A QLabel with one of the text roles the stylesheet knows."""
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def chip(text: str, accent: bool = False, tooltip: str = "") -> QLabel:
    """A small rounded tag for a basis, a unit or a state."""
    lbl = QLabel(text)
    lbl.setObjectName("chipAccent" if accent else "chip")
    if tooltip:
        lbl.setToolTip(tooltip)
    return lbl


def button(text: str, kind: str = "primary", slot: Callable | None = None,
           tooltip: str = "", shortcut: str = "") -> QPushButton:
    """A push button of a given kind: primary, secondary, ghost or danger.

    ``shortcut`` is only named in the tooltip: the key binding itself belongs to
    the menu action for the same command, so that one key never has two owners.
    """
    btn = QPushButton(text)
    if kind != "primary":
        btn.setProperty("kind", kind)
    btn.setCursor(Qt.PointingHandCursor)
    if slot is not None:
        btn.clicked.connect(slot)
    tip = tooltip
    if shortcut:
        tip = f"{tip} ({shortcut})".strip() if tip else shortcut
    if tip:
        btn.setToolTip(tip)
    return btn


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("divider")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(1)


def form_row_of(widget: QWidget):
    """The form layout a field sits in and the item registered with it.

    A field wrapped with its unit label is registered with the form through the
    wrapper, so callers that want the row's label have to ask for the wrapper.
    Returns ``(None, None)`` when the widget is not in a form.
    """
    holder = widget
    parent = widget.parentWidget()
    for _ in range(2):
        if parent is None:
            return None, None
        layout = parent.layout()
        if isinstance(layout, QFormLayout):
            return layout, holder
        holder, parent = parent, parent.parentWidget()
    return None, None


# --------------------------------------------------------------------------- #
# Chart canvas
# --------------------------------------------------------------------------- #
class MplCanvas(FigureCanvasQTAgg):
    """A matplotlib figure embedded in Qt, styled once, with hover tooltips."""

    def __init__(self, width: float = 4.0, height: float = 3.0):
        apply_defaults()
        # Constrained layout fits the labels at draw time, so building the chart
        # costs nothing until the canvas is on screen.
        self.figure = Figure(figsize=(width, height), dpi=100, layout="constrained")
        self.figure.set_facecolor(theme.CHART_SURFACE)
        super().__init__(self.figure)
        self.ax = self.figure.add_subplot(111)
        style_axes(self.ax)
        self._hover: list = []
        self._pending = None
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mpl_connect("motion_notify_event", self._on_motion)

    def reset(self):
        """Clear the figure and return a fresh, styled axes."""
        self.figure.clear()
        self._hover = []
        self.ax = self.figure.add_subplot(111)
        style_axes(self.ax)
        return self.ax

    def refresh(self):
        self.draw_idle()

    def render_later(self, draw) -> None:
        """Run ``draw`` now if the canvas is on screen, otherwise when it next is.

        The results panel recomputes on every keystroke; a chart on a tab the
        user is not looking at is built when the tab is opened, not before.
        """
        self._pending = draw
        if self.isVisible():
            self._flush()

    def _flush(self) -> None:
        draw, self._pending = self._pending, None
        if draw is not None:
            draw()

    def showEvent(self, event):
        super().showEvent(event)
        if self._pending is not None:
            self._flush()

    def show_message(self, title: str, hint: str = ""):
        """An empty or error state drawn where the chart would be."""
        ax = self.reset()
        ax.set_axis_off()
        ax.text(0.5, 0.58 if hint else 0.5, title, ha="center", va="center", fontsize=10.5,
                fontweight="semibold", color=theme.CHART_INK_2, transform=ax.transAxes)
        if hint:
            ax.text(0.5, 0.42, hint, ha="center", va="center", fontsize=8.5,
                    color=theme.CHART_MUTED, transform=ax.transAxes, wrap=True)
        self.draw_idle()

    def set_hover(self, pairs: Iterable):
        """``(artist, text)`` pairs; ``text`` may be a callable of the hit details."""
        self._hover = list(pairs)

    def _on_motion(self, event):
        if event.inaxes is None or not self._hover:
            QToolTip.hideText()
            return
        for artist, text in self._hover:
            try:
                hit, details = artist.contains(event)
            except Exception:  # noqa: BLE001 - an artist removed under the cursor
                continue
            if hit:
                shown = text(details) if callable(text) else text
                if shown:
                    QToolTip.showText(QCursor.pos(), shown, self)
                    return
        QToolTip.hideText()


# --------------------------------------------------------------------------- #
# KPI tile
# --------------------------------------------------------------------------- #
class KpiCard(QFrame):
    """A tile with a title, a big value, its unit and the basis it is on."""

    def __init__(self, title: str, unit: str = "", basis: str = ""):
        super().__init__()
        self.setObjectName("kpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setObjectName("kpiTitle")
        self._title.setWordWrap(True)
        self._value = QLabel(DASH)
        self._value.setObjectName("kpiValue")
        self._unit = QLabel(unit)
        self._unit.setObjectName("kpiUnit")
        self._unit.setWordWrap(True)
        self._basis = QLabel(basis)
        self._basis.setObjectName("kpiBasis")
        self._basis.setWordWrap(True)
        self._basis.setVisible(bool(basis))

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._unit)
        layout.addWidget(self._basis)
        layout.addStretch(1)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setFocusPolicy(Qt.TabFocus)
        self.set_state("empty")

    def set_value(self, text: str, state: str = "ok"):
        self._value.setText(text)
        self.set_state("empty" if text == DASH else state)

    def set_state(self, state: str):
        for w in (self, self._value):
            if w.property("state") != state:
                w.setProperty("state", state)
                theme.repolish(w)

    def set_title(self, text: str):
        self._title.setText(text)

    def set_unit(self, text: str):
        """The unit belongs to the number, so it moves when the basis does."""
        self._unit.setText(text)

    def set_basis(self, text: str):
        self._basis.setText(text)
        self._basis.setVisible(bool(text))
        self.setAccessibleDescription(text)


# --------------------------------------------------------------------------- #
# Section card with a form
# --------------------------------------------------------------------------- #
class Section(QFrame):
    """A titled card holding a form, collapsible, numbered as a process step."""

    toggled = Signal(bool)

    def __init__(self, title: str, step: int | str | None = None, description: str = "",
                 collapsible: bool = True, expanded: bool = True):
        super().__init__()
        self.setObjectName("section")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(6)

        header = QFrame()
        header.setObjectName("sectionHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        if step is not None:
            badge = QLabel(str(step))
            badge.setObjectName("sectionStep")
            badge.setAlignment(Qt.AlignCenter)
            h.addWidget(badge)
        self._title = QLabel(title)
        self._title.setObjectName("sectionTitle")
        h.addWidget(self._title)
        h.addStretch(1)
        self._toggle = QToolButton()
        self._toggle.setObjectName("sectionToggle")
        self._toggle.setCursor(Qt.PointingHandCursor)
        self._toggle.setFocusPolicy(Qt.TabFocus)
        self._toggle.setToolTip("Collapse or expand this section")
        self._toggle.clicked.connect(lambda: self.set_expanded(not self._expanded))
        self._toggle.setVisible(collapsible)
        h.addWidget(self._toggle)
        outer.addWidget(header)

        self._desc = QLabel(description)
        self._desc.setObjectName("caption")
        self._desc.setWordWrap(True)
        self._desc.setVisible(bool(description))
        outer.addWidget(self._desc)

        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(0, 4, 0, 0)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        outer.addWidget(self.body)

        self._rows: list[tuple[QLabel | None, QWidget, str]] = []
        self._units: dict[int, QLabel] = {}
        self._expanded = True
        self.set_expanded(expanded)

    @property
    def title(self) -> str:
        return self._title.text()

    def add_row(self, text, field: QWidget, unit: str = "", hint: str = "") -> QLabel | None:
        """Add ``label | field [unit]``; returns the label widget (or ``None``)."""
        if unit:
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            hl.addWidget(field, 1)
            unit_lbl = QLabel(unit)
            unit_lbl.setObjectName("unit")
            unit_lbl.setToolTip(f"Unit: {unit}")
            hl.addWidget(unit_lbl)
            self._units[id(field)] = unit_lbl
        else:
            holder = field
        if isinstance(text, QLabel):
            lbl = text
        elif text:
            lbl = QLabel(text)
        else:
            lbl = None
        if lbl is None:
            self.form.addRow(holder)
        else:
            lbl.setBuddy(field)
            self.form.addRow(lbl, holder)
            if hint:
                lbl.setToolTip(hint)
        self._rows.append((lbl, holder, lbl.text() if lbl else ""))
        return lbl

    def add_widget(self, widget: QWidget, searchable: str = ""):
        self.form.addRow(widget)
        self._rows.append((None, widget, searchable))

    def set_unit(self, field: QWidget, text: str):
        """Change the unit tag of a row whose unit follows the sizing basis."""
        lbl = self._units.get(id(field))
        if lbl is not None:
            lbl.setText(text)
            lbl.setToolTip(f"Unit: {text}")

    def add_heading(self, text: str):
        """A small heading that groups the rows that follow."""
        lbl = QLabel(text)
        lbl.setObjectName("h3")
        lbl.setContentsMargins(0, 6, 0, 0)
        self.form.addRow(lbl)
        self._rows.append((None, lbl, text))

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, on: bool):
        self._expanded = bool(on)
        self.body.setVisible(self._expanded)
        self._desc.setVisible(self._expanded and bool(self._desc.text()))
        self._toggle.setText("Hide" if self._expanded else "Show")
        self._toggle.setAccessibleName(
            f"{'Collapse' if self._expanded else 'Expand'} {self._title.text()}")
        self.toggled.emit(self._expanded)

    def apply_filter(self, needle: str) -> int:
        """Show only the rows whose label matches; hide the card when none does."""
        needle = (needle or "").strip().lower()
        shown = 0
        title_hit = needle and needle in self._title.text().lower()
        for lbl, holder, text in self._rows:
            hit = (not needle or title_hit or needle in text.lower()
                   or (lbl is not None and needle in lbl.toolTip().lower()))
            self.form.setRowVisible(holder, bool(hit))
            shown += bool(hit)
        self.setVisible(shown > 0 or not needle)
        if needle and shown and not self._expanded:
            self.set_expanded(True)
        return shown


# --------------------------------------------------------------------------- #
# Banners and empty states
# --------------------------------------------------------------------------- #
_BANNER_GLYPH = {"info": "i", "success": "✓", "warning": "!", "danger": "!"}


class Banner(QFrame):
    """A one-paragraph message with a state: info, success, warning or danger."""

    def __init__(self, kind: str = "info", text: str = ""):
        super().__init__()
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        self._glyph = QLabel()
        font = self._glyph.font()
        font.setBold(True)
        self._glyph.setFont(font)
        self._glyph.setFixedWidth(14)
        self._glyph.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self._text = QLabel(text)
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._glyph)
        lay.addWidget(self._text, 1)
        self.set_kind(kind)

    def set_kind(self, kind: str):
        self.setProperty("kind", kind)
        self._glyph.setText(_BANNER_GLYPH.get(kind, "i"))
        theme.repolish(self)

    def set_text(self, text: str):
        self._text.setText(text)

    def text(self) -> str:
        return self._text.text()


class EmptyState(QFrame):
    """What a page shows before it has anything to show: a title, a hint, an action."""

    #: The widest the title and the hint may grow. Each sits in its own row
    #: between two stretches, so it fills the row up to this width and stays
    #: centred. Centring the whole layout instead drew each wrapped label at its
    #: size-hint width (about 270 px) with only the height it needs at the full
    #: width, which cut off the last lines of the hint.
    TEXT_WIDTH = 560

    def __init__(self, title: str, hint: str = "", action_text: str = "",
                 slot: Callable | None = None):
        super().__init__()
        self.setObjectName("emptyState")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 28, 24, 28)
        lay.setSpacing(6)
        self._title = self._text_label(title, "emptyTitle")
        self._hint = self._text_label(hint, "emptyHint")
        self._hint.setVisible(bool(hint))
        for lbl in (self._title, self._hint):
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(lbl, 100)
            row.addStretch(1)
            lay.addLayout(row)
        self.action = None
        if action_text:
            self.action = button(action_text, "secondary", slot)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(self.action)
            row.addStretch(1)
            lay.addSpacing(6)
            lay.addLayout(row)

    def _text_label(self, text: str, name: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName(name)
        lbl.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(self.TEXT_WIDTH)
        return lbl

    def set_text(self, title: str, hint: str = ""):
        self._title.setText(title)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))


# --------------------------------------------------------------------------- #
# Key / value grid for totals
# --------------------------------------------------------------------------- #
class KeyValueGrid(QWidget):
    """Short label / value / unit triples laid out in columns under a chart."""

    def __init__(self, columns: int = 3):
        super().__init__()
        self._columns = max(1, columns)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(18)
        self._grid.setVerticalSpacing(4)

    def set_rows(self, rows: Iterable[tuple]):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, row in enumerate(rows):
            key, value = row[0], row[1]
            unit = row[2] if len(row) > 2 else ""
            tip = row[3] if len(row) > 3 else ""
            cell = QWidget()
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            k = QLabel(key)
            k.setObjectName("caption")
            val = QLabel(f"{value} <span style='color:{theme.INK_3}; font-size:{theme.TEXT_SM}px'>{unit}</span>"
                         if unit else value)
            val.setTextFormat(Qt.RichText)
            font = val.font()
            font.setWeight(QFont.DemiBold)
            val.setFont(font)
            if tip:
                cell.setToolTip(tip)
            v.addWidget(k)
            v.addWidget(val)
            self._grid.addWidget(cell, i // self._columns, i % self._columns)
        self._grid.setColumnStretch(self._columns, 1)


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def make_table(headers: list[str], stretch_last: bool = True,
               stretch_first: bool = False) -> QTableWidget:
    """A read-only table with the app's header and row conventions."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setShowGrid(True)
    table.setFocusPolicy(Qt.StrongFocus)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(stretch_last)
    if stretch_first:
        header.setSectionResizeMode(0, QHeaderView.Stretch)
    header.setMinimumSectionSize(48)
    table.verticalHeader().setDefaultSectionSize(26)
    return table


def fit_rows(table: QTableWidget, extra: int = 6) -> None:
    """Size the table to show every row, so the page scrolls instead of the table."""
    header = table.horizontalHeader()
    height = (header.sizeHint().height() if not header.isHidden() else 0) + 2 * table.frameWidth()
    height += sum(table.rowHeight(r) for r in range(table.rowCount())) + extra
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    table.setMinimumHeight(height)
    table.setMaximumHeight(height)


def fill_table(table: QTableWidget, rows: Iterable[Iterable], numeric_from: int = 1,
               bold_rows: Iterable[int] = (), tooltips: dict | None = None,
               colors: dict | None = None, max_width: int = 420, fit: bool = False):
    """Replace the table's content.

    Columns from ``numeric_from`` on are right-aligned. ``tooltips`` maps a
    ``(row, column)`` to a tooltip; ``colors`` maps one to a foreground colour.
    ``fit`` sizes the table to its rows so it never scrolls inside a page.
    """
    rows = [list(r) for r in rows]
    bold = set(bold_rows)
    tooltips = tooltips or {}
    colors = colors or {}
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            item = QTableWidgetItem("" if text is None else str(text))
            if c >= numeric_from:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if r in bold:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            tip = tooltips.get((r, c))
            if tip:
                item.setToolTip(tip)
            color = colors.get((r, c))
            if color:
                from PySide6.QtGui import QColor

                item.setForeground(QColor(color))
            table.setItem(r, c, item)
    table.resizeColumnsToContents()
    header = table.horizontalHeader()
    for c in range(table.columnCount()):
        if header.sectionSize(c) > max_width:
            header.resizeSection(c, max_width)
    if fit:
        fit_rows(table)
