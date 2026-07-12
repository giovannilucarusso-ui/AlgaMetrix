"""The canvas viewport: a ``QGraphicsView`` with wheel-zoom, pan and a grid."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsView

from .scene import FlowsheetScene

GRID = 20
MAJOR = 100
MIN_SCALE = 0.25
MAX_SCALE = 2.5


class FlowsheetView(QGraphicsView):
    def __init__(self, scene: FlowsheetScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scale = 1.0
        self._panning = False
        self._pan_start = None

    # -- zoom ------------------------------------------------------------ #
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = self._scale * factor
        if new_scale < MIN_SCALE or new_scale > MAX_SCALE:
            return
        self._scale = new_scale
        self.scale(factor, factor)

    def reset_zoom(self):
        self.resetTransform()
        self._scale = 1.0

    def fit_content(self):
        scene = self.scene()
        items_rect = scene.itemsBoundingRect() if scene.items() else QRectF(-200, -150, 400, 300)
        items_rect = items_rect.adjusted(-60, -60, 60, 60)
        self.fitInView(items_rect, Qt.KeepAspectRatio)
        # keep track of the resulting scale (approx) and clamp future zoom
        self._scale = self.transform().m11()

    # -- middle / space pan ---------------------------------------------- #
    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- background CAD grid (fine minor lines + heavier major lines) ---- #
    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        zoom = self.transform().m11()

        def draw_grid(step, pen):
            painter.setPen(pen)
            x = int(rect.left()) - (int(rect.left()) % step)
            lines = []
            while x < rect.right():
                lines.append(QLineF(x, rect.top(), x, rect.bottom()))
                x += step
            y = int(rect.top()) - (int(rect.top()) % step)
            while y < rect.bottom():
                lines.append(QLineF(rect.left(), y, rect.right(), y))
                y += step
            painter.drawLines(lines)

        if zoom >= 0.55:
            draw_grid(GRID, QPen(QColor("#eef2f6"), 0))
        draw_grid(MAJOR, QPen(QColor("#e0e7ec"), 0))
