"""The canvas viewport: wheel zoom, pan, a CAD grid and an overview map."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsView, QWidget

from .scene import FlowsheetScene

GRID = 20
MAJOR = 100
MIN_SCALE = 0.12
MAX_SCALE = 3.0


class Minimap(QWidget):
    """Thumbnail of the whole sheet with the visible area outlined; click to move."""

    W, H = 220, 136

    def __init__(self, view: "FlowsheetView"):
        super().__init__(view)
        self._view = view
        self._image: QImage | None = None
        self._source = QRectF()
        self._target = QRectF()
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Overview: click or drag to move around the drawing")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._render)

    def schedule(self):
        self._timer.start()

    def _render(self):
        scene = self._view.scene()
        if scene is None:
            return
        src = scene.export_rect() if isinstance(scene, FlowsheetScene) else scene.itemsBoundingRect()
        if src.isEmpty():
            self._image = None
            self.update()
            return
        box = QRectF(6, 6, self.W - 12, self.H - 12)
        k = min(box.width() / src.width(), box.height() / src.height())
        w, h = src.width() * k, src.height() * k
        self._target = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
        self._source = src
        dpr = self.devicePixelRatioF()
        img = QImage(int(self.W * dpr), int(self.H * dpr), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        canvas = QColor(scene.theme.canvas) if isinstance(scene, FlowsheetScene) else QColor("#ffffff")
        p.fillRect(self._target, canvas)
        card = getattr(scene, "card", None)
        hidden = card is not None and card.isVisible()
        if hidden:
            card.setVisible(False)
        scene.render(p, self._target, src, Qt.KeepAspectRatio)
        if hidden:
            card.setVisible(True)
        p.end()
        self._image = img
        self.update()

    def _to_scene(self, pt: QPointF) -> QPointF:
        if self._target.isEmpty():
            return QPointF()
        fx = (pt.x() - self._target.left()) / self._target.width()
        fy = (pt.y() - self._target.top()) / self._target.height()
        return QPointF(self._source.left() + fx * self._source.width(),
                       self._source.top() + fy * self._source.height())

    def _from_scene(self, rect: QRectF) -> QRectF:
        if self._source.isEmpty():
            return QRectF()
        kx = self._target.width() / self._source.width()
        ky = self._target.height() / self._source.height()
        return QRectF(self._target.left() + (rect.left() - self._source.left()) * kx,
                      self._target.top() + (rect.top() - self._source.top()) * ky,
                      rect.width() * kx, rect.height() * ky)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        scene = self._view.scene()
        dark = isinstance(scene, FlowsheetScene) and scene.theme.dark
        frame = QRectF(0.5, 0.5, self.W - 1, self.H - 1)
        p.setPen(QPen(QColor("#24486b" if dark else "#cbd5e1"), 1.0))
        p.setBrush(QColor(15, 34, 54, 235) if dark else QColor(255, 255, 255, 235))
        p.drawRoundedRect(frame, 7, 7)
        if self._image is not None:
            p.drawImage(QPointF(0, 0), self._image)
            vis = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
            r = self._from_scene(vis).intersected(self._target.adjusted(-1, -1, 1, 1))
            accent = QColor("#4ade80" if dark else "#15803d")
            fill = QColor(accent)
            fill.setAlpha(28)
            p.setBrush(fill)
            p.setPen(QPen(accent, 1.4))
            p.drawRect(r)
        p.end()

    def mousePressEvent(self, event):
        self._view.center_by_hand(self._to_scene(event.position()))
        self.update()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._view.center_by_hand(self._to_scene(event.position()))
            self.update()


class FlowsheetView(QGraphicsView):
    zoomChanged = Signal(float)

    def __init__(self, scene: FlowsheetScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheBackground)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QGraphicsView.NoFrame)
        self._scale = 1.0
        self._panning = False
        self._pan_start = None
        self.top_reserve = 0.0      # pixels kept free at the top for floating controls
        # After "Fit" the drawing stays fitted when the window or the sheet changes
        # size, until the user zooms or pans by hand.
        self._fitted = False
        self._fit_rect = QRectF()
        self._minimap_on = True
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(0)
        self._refit_timer.timeout.connect(self._refit)

        self.minimap = Minimap(self)
        self.minimap.hide()
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.valueChanged.connect(self._viewport_moved)
            bar.sliderMoved.connect(self._by_hand)
        scene.decorChanged.connect(self._decor_changed)

    def _content_rect(self) -> QRectF:
        scene = self.scene()
        if isinstance(scene, FlowsheetScene):
            return scene.export_rect()
        return scene.itemsBoundingRect() if scene is not None else QRectF()

    def _decor_changed(self):
        # the sheet behind the drawing grows and shrinks with it
        self.resetCachedContent()
        self.viewport().update()
        self.minimap.schedule()
        if self._fitted and self._content_rect() != self._fit_rect:
            self._refit_timer.start()
        else:
            self._sync_minimap()

    def _refit(self):
        if self._fitted:
            self.fit_content()

    def _by_hand(self, *_):
        self._fitted = False

    def _viewport_moved(self, *_):
        self.minimap.update()
        self._sync_minimap()

    # -- overlays -------------------------------------------------------- #
    def theme_changed(self):
        self.resetCachedContent()
        self.minimap.schedule()
        self.viewport().update()

    def set_minimap_visible(self, on: bool):
        self._minimap_on = on
        self._sync_minimap()

    def _sync_minimap(self):
        # The overview is only useful while part of the drawing is off screen;
        # at "Fit" it would sit on the title block for nothing.
        content = self._content_rect()
        seen = self.mapToScene(self.viewport().rect()).boundingRect()
        want = (self._minimap_on and not content.isEmpty()
                and not seen.adjusted(-2, -2, 2, 2).contains(content))
        if want != self.minimap.isVisible():
            self.minimap.setVisible(want)
            if want:
                self.minimap.schedule()
        self._place_overlays()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fitted:
            self._refit_timer.start()
        self._sync_minimap()

    def _place_overlays(self):
        vp = self.viewport().geometry()
        self.minimap.move(vp.right() - self.minimap.width() - 12,
                          vp.bottom() - self.minimap.height() - 12)
        self.minimap.raise_()

    def center_by_hand(self, point: QPointF):
        self._fitted = False
        self.centerOn(point)

    # -- zoom ------------------------------------------------------------ #
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = self._scale * factor
        if new_scale < MIN_SCALE or new_scale > MAX_SCALE:
            return
        self._fitted = False
        self._scale = new_scale
        self.scale(factor, factor)
        self._zoomed()

    def _zoomed(self):
        self.minimap.update()
        self._sync_minimap()
        self.zoomChanged.emit(self._scale)

    def zoom_by(self, factor: float):
        new_scale = self._scale * factor
        if MIN_SCALE <= new_scale <= MAX_SCALE:
            self._fitted = False
            self._scale = new_scale
            self.scale(factor, factor)
            self._zoomed()

    def reset_zoom(self):
        self._fitted = False
        self.resetTransform()
        self._scale = 1.0
        self._zoomed()

    def fit_content(self):
        scene = self.scene()
        if isinstance(scene, FlowsheetScene):
            scene.flush_decor()      # the sheet must match the drawing before it is measured
        rect = self._content_rect()
        if rect.isEmpty():
            rect = QRectF(-200, -150, 400, 300)
        self.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)
        if self.top_reserve:
            # second pass: now that the scale is known, leave the band at the top free
            k = self.transform().m11() or 1.0
            self.fitInView(rect.adjusted(-20, -20 - self.top_reserve / k, 20, 20), Qt.KeepAspectRatio)
        self._scale = self.transform().m11()
        self._fitted = True
        self._fit_rect = QRectF(rect)
        self._refit_timer.stop()
        self._zoomed()
        self.minimap.schedule()

    # -- middle-button pan ----------------------------------------------- #
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
            self._fitted = False
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        if event.buttons() & Qt.LeftButton:
            # dragging a block can grow the sheet; the view must not jump under it
            self._fitted = False
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- background: desk, sheet and CAD grid ---------------------------- #
    def drawBackground(self, painter, rect):
        scene = self.scene()
        theme = scene.theme
        canvas = QColor(theme.canvas)
        sheet = scene.sheet._rect if scene.show_sheet and scene.sheet.isVisible() else QRectF()
        if sheet.isNull():
            painter.fillRect(rect, canvas)
            area = rect
        else:
            painter.fillRect(rect, canvas.darker(125 if theme.dark else 106))
            shadow = QColor(0, 0, 0, 70 if theme.dark else 26)
            for i, a in enumerate((1.0, 0.6, 0.3)):
                c = QColor(shadow)
                c.setAlpha(int(shadow.alpha() * a))
                painter.fillRect(sheet.adjusted(-2 - 2 * i, 2 + 2 * i, 4 + 2 * i, 6 + 2 * i), c)
            painter.fillRect(sheet, canvas)
            area = rect.intersected(sheet)
            if area.isEmpty():
                return
        zoom = self.transform().m11()

        def draw_grid(step, pen):
            painter.setPen(pen)
            x = int(area.left()) - (int(area.left()) % step)
            lines = []
            while x < area.right():
                if x >= area.left():
                    lines.append(QLineF(x, area.top(), x, area.bottom()))
                x += step
            y = int(area.top()) - (int(area.top()) % step)
            while y < area.bottom():
                if y >= area.top():
                    lines.append(QLineF(area.left(), y, area.right(), y))
                y += step
            painter.drawLines(lines)

        if zoom >= 0.55:
            draw_grid(GRID, QPen(QColor(theme.grid_minor), 0))
        if zoom >= 0.2:
            draw_grid(MAJOR, QPen(QColor(theme.grid_major), 0))
