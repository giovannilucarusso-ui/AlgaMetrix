"""Reusable widgets: an embedded matplotlib canvas and a KPI card."""

from __future__ import annotations

import os

# matplotlib must use the same Qt binding as the app (PySide6).
os.environ.setdefault("QT_API", "pyside6")
import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

ACCENT = "#2e7d32"
NEG = "#2e7d32"   # green for credits / negative contributions
POS = "#c0392b"   # red for burdens


class MplCanvas(FigureCanvasQTAgg):
    """A matplotlib figure embedded in Qt, with a convenient reset helper."""

    def __init__(self, width: float = 4.0, height: float = 3.0):
        self.figure = Figure(figsize=(width, height), dpi=100)
        self.figure.set_facecolor("#ffffff")
        super().__init__(self.figure)
        self.ax = self.figure.add_subplot(111)

    def reset(self):
        """Clear the figure and return a fresh axes."""
        self.figure.clear()
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor("#ffffff")
        return self.ax

    def refresh(self):
        self.figure.tight_layout()
        self.draw_idle()


class KpiCard(QFrame):
    """A small card showing a title, a big value and a unit."""

    def __init__(self, title: str, unit: str = ""):
        super().__init__()
        self.setObjectName("kpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setObjectName("kpiTitle")
        self._value = QLabel("-")
        self._value.setObjectName("kpiValue")
        self._unit = QLabel(unit)
        self._unit.setObjectName("kpiUnit")

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._unit)
        layout.addStretch(1)

    def set_value(self, text: str):
        self._value.setText(text)

    def set_title(self, text: str):
        self._title.setText(text)

    def set_unit(self, text: str):
        """The unit belongs to the number, so it moves when the basis does."""
        self._unit.setText(text)
