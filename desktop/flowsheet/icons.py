"""Hand-drawn vector icons for process equipment.

Every icon is a small function ``draw(painter, rect, color)`` that renders a
recognisable line-art silhouette of a unit operation inside ``rect`` using
``color`` for the stroke and a faint tint for fills. They are resolution
independent (pure ``QPainter`` geometry), so they look crisp on the canvas at
any zoom and can be rasterised to a ``QPixmap`` for the palette.

Add a new piece of equipment by writing a ``_draw_*`` function and registering
it in :data:`ICONS`; then point a :class:`~desktop.flowsheet.model.UnitSpec` at
its key via the ``icon`` field.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

Drawer = Callable[[QPainter, QRectF, QColor], None]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _pt(r: QRectF, nx: float, ny: float) -> QPointF:
    """A point at normalised (0..1) coordinates inside ``r``."""
    return QPointF(r.left() + nx * r.width(), r.top() + ny * r.height())


def _rect(r: QRectF, nx: float, ny: float, nw: float, nh: float) -> QRectF:
    return QRectF(r.left() + nx * r.width(), r.top() + ny * r.height(),
                  nw * r.width(), nh * r.height())


def _setup(painter: QPainter, color: QColor, weight: float = 0.075,
           fill: bool = True, base: float = 1.0) -> QPen:
    lw = max(1.4, weight * base)
    pen = QPen(color, lw)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    if fill:
        tint = QColor(color)
        tint.setAlpha(28)
        painter.setBrush(QBrush(tint))
    else:
        painter.setBrush(Qt.NoBrush)
    return pen


def _line(painter, r, x1, y1, x2, y2):
    painter.drawLine(_pt(r, x1, y1), _pt(r, x2, y2))


# --------------------------------------------------------------------------- #
# IO / storage
# --------------------------------------------------------------------------- #
def _draw_tank(p, r, c):
    _setup(p, c, base=r.width())
    body = _rect(r, 0.24, 0.16, 0.52, 0.72)
    path = QPainterPath()
    path.addRoundedRect(body, r.width() * 0.06, r.width() * 0.06)
    p.drawPath(path)
    # dome top
    p.drawArc(_rect(r, 0.24, 0.06, 0.52, 0.22), 0, 180 * 16)
    # liquid level line
    _line(p, r, 0.26, 0.55, 0.74, 0.55)
    # legs
    _line(p, r, 0.32, 0.88, 0.32, 0.96)
    _line(p, r, 0.68, 0.88, 0.68, 0.96)


def _draw_gas(p, r, c):
    _setup(p, c, base=r.width())
    body = _rect(r, 0.34, 0.24, 0.32, 0.64)
    path = QPainterPath()
    path.addRoundedRect(body, r.width() * 0.14, r.width() * 0.14)
    p.drawPath(path)
    # rounded shoulder
    p.drawArc(_rect(r, 0.34, 0.12, 0.32, 0.28), 0, 180 * 16)
    # valve
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.5, 0.08, 0.5, 0.16)
    p.drawRect(_rect(r, 0.44, 0.03, 0.12, 0.06))
    # label CO2 hint: three bubbles
    for i, x in enumerate((0.44, 0.5, 0.56)):
        p.drawEllipse(_pt(r, x, 0.5 + (i % 2) * 0.08), r.width() * 0.02, r.width() * 0.02)


def _draw_drum(p, r, c):
    _setup(p, c, base=r.width())
    body = _rect(r, 0.28, 0.16, 0.44, 0.68)
    p.drawRect(body)
    # elliptical top / bottom
    p.drawEllipse(_rect(r, 0.28, 0.08, 0.44, 0.16))
    _setup(p, c, base=r.width(), fill=False)
    p.drawArc(_rect(r, 0.28, 0.76, 0.44, 0.16), 180 * 16, 180 * 16)
    # hoops
    _line(p, r, 0.28, 0.38, 0.72, 0.38)
    _line(p, r, 0.28, 0.6, 0.72, 0.6)


def _draw_waste(p, r, c):
    _setup(p, c, base=r.width())
    # bin body (trapezoid)
    poly = QPolygonF([_pt(r, 0.3, 0.28), _pt(r, 0.7, 0.28),
                      _pt(r, 0.64, 0.9), _pt(r, 0.36, 0.9)])
    p.drawPolygon(poly)
    _setup(p, c, base=r.width(), fill=False)
    # lid
    _line(p, r, 0.24, 0.22, 0.76, 0.22)
    _line(p, r, 0.44, 0.14, 0.56, 0.14)
    _line(p, r, 0.44, 0.14, 0.44, 0.22)
    _line(p, r, 0.56, 0.14, 0.56, 0.22)
    # ribs
    _line(p, r, 0.44, 0.36, 0.42, 0.82)
    _line(p, r, 0.56, 0.36, 0.58, 0.82)


# --------------------------------------------------------------------------- #
# Cultivation / bioreactors
# --------------------------------------------------------------------------- #
def _draw_raceway(p, r, c):
    _setup(p, c, base=r.width(), fill=True)
    # stadium (racetrack) outline
    outer = _rect(r, 0.12, 0.34, 0.76, 0.4)
    path = QPainterPath()
    path.addRoundedRect(outer, outer.height() / 2, outer.height() / 2)
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False)
    # central divider
    _line(p, r, 0.32, 0.54, 0.68, 0.54)
    # paddlewheel
    cx, cy = 0.28, 0.54
    p.drawEllipse(_pt(r, cx, cy), r.width() * 0.06, r.width() * 0.06)
    for a in (0, 45, 90, 135):
        import math
        dx = 0.06 * math.cos(math.radians(a))
        dy = 0.06 * math.sin(math.radians(a))
        _line(p, r, cx - dx, cy - dy, cx + dx, cy + dy)


def _draw_tubular(p, r, c):
    _setup(p, c, base=r.width(), fill=False, weight=0.09)
    # serpentine of horizontal tubes
    ys = (0.3, 0.5, 0.7)
    for i, y in enumerate(ys):
        _line(p, r, 0.22, y, 0.78, y)
    # connect ends into a serpentine
    p.drawArc(_rect(r, 0.7, 0.3, 0.16, 0.2), 270 * 16, 180 * 16)
    p.drawArc(_rect(r, 0.14, 0.5, 0.16, 0.2), 90 * 16, 180 * 16)
    # vertical manifold hints
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.2, 0.24, 0.2, 0.76)


def _draw_flat_panel(p, r, c):
    _setup(p, c, base=r.width())
    for x in (0.28, 0.46, 0.64):
        p.drawRect(_rect(r, x, 0.2, 0.1, 0.62))
    _setup(p, c, base=r.width(), fill=False)
    # base frame
    _line(p, r, 0.2, 0.84, 0.82, 0.84)


def _draw_bubble_column(p, r, c):
    _setup(p, c, base=r.width())
    col = _rect(r, 0.36, 0.14, 0.28, 0.72)
    path = QPainterPath()
    path.addRoundedRect(col, r.width() * 0.05, r.width() * 0.05)
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    # rising bubbles
    for (x, y, s) in ((0.45, 0.66, 0.03), (0.55, 0.56, 0.025), (0.48, 0.44, 0.03),
                      (0.56, 0.32, 0.022), (0.45, 0.26, 0.02)):
        p.drawEllipse(_pt(r, x, y), r.width() * s, r.width() * s)
    # sparger
    _line(p, r, 0.4, 0.8, 0.6, 0.8)


def _draw_stirred_tank(p, r, c):
    _setup(p, c, base=r.width())
    # cylindrical body with dished bottom
    path = QPainterPath()
    path.moveTo(_pt(r, 0.28, 0.28))
    path.lineTo(_pt(r, 0.28, 0.72))
    path.quadTo(_pt(r, 0.5, 0.92), _pt(r, 0.72, 0.72))
    path.lineTo(_pt(r, 0.72, 0.28))
    path.closeSubpath()
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False)
    # motor on top
    p.drawRect(_rect(r, 0.44, 0.08, 0.12, 0.1))
    # shaft
    _line(p, r, 0.5, 0.18, 0.5, 0.62)
    # two impellers
    _line(p, r, 0.4, 0.5, 0.6, 0.5)
    _line(p, r, 0.42, 0.62, 0.58, 0.62)


# --------------------------------------------------------------------------- #
# Separation / dewatering
# --------------------------------------------------------------------------- #
def _draw_centrifuge(p, r, c):
    _setup(p, c, base=r.width())
    # conical bowl
    poly = QPolygonF([_pt(r, 0.3, 0.26), _pt(r, 0.7, 0.26),
                      _pt(r, 0.58, 0.76), _pt(r, 0.42, 0.76)])
    p.drawPolygon(poly)
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    # disc stack
    for y in (0.36, 0.46, 0.56):
        _line(p, r, 0.4, y, 0.6, y)
    # inlet + base
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.5, 0.12, 0.5, 0.26)
    _line(p, r, 0.4, 0.84, 0.6, 0.84)


def _draw_decanter(p, r, c):
    _setup(p, c, base=r.width())
    # horizontal cylinder, slightly tapered
    path = QPainterPath()
    body = _rect(r, 0.18, 0.36, 0.64, 0.3)
    path.addRoundedRect(body, r.height() * 0.15, r.height() * 0.15)
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    # internal screw (diagonal hatches)
    for x in (0.28, 0.4, 0.52, 0.64):
        _line(p, r, x, 0.4, x + 0.06, 0.62)
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.3, 0.78, 0.5, 0.78)


def _draw_membrane(p, r, c):
    _setup(p, c, base=r.width())
    p.drawRect(_rect(r, 0.24, 0.28, 0.52, 0.44))
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    # membrane sheets
    for x in (0.34, 0.44, 0.54, 0.64):
        _line(p, r, x, 0.3, x, 0.7)
    # feed/permeate arrows
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.12, 0.5, 0.24, 0.5)
    _line(p, r, 0.76, 0.5, 0.88, 0.5)


def _draw_filter_press(p, r, c):
    _setup(p, c, base=r.width(), fill=False, weight=0.08)
    # end frames
    p.drawRect(_rect(r, 0.18, 0.26, 0.06, 0.5))
    p.drawRect(_rect(r, 0.76, 0.26, 0.06, 0.5))
    # plate stack
    for x in (0.3, 0.4, 0.5, 0.6, 0.7):
        _line(p, r, x, 0.28, x, 0.74)
    # tie bar
    _line(p, r, 0.18, 0.5, 0.82, 0.5)


def _draw_settler(p, r, c):
    _setup(p, c, base=r.width())
    path = QPainterPath()
    path.moveTo(_pt(r, 0.24, 0.28))
    path.lineTo(_pt(r, 0.76, 0.28))
    path.lineTo(_pt(r, 0.76, 0.5))
    path.lineTo(_pt(r, 0.5, 0.86))
    path.lineTo(_pt(r, 0.24, 0.5))
    path.closeSubpath()
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False)
    # sludge line
    _line(p, r, 0.36, 0.62, 0.64, 0.62)


# --------------------------------------------------------------------------- #
# Thermal
# --------------------------------------------------------------------------- #
def _draw_spray_dryer(p, r, c):
    _setup(p, c, base=r.width())
    # chamber with conical bottom
    path = QPainterPath()
    path.moveTo(_pt(r, 0.2, 0.24))
    path.lineTo(_pt(r, 0.62, 0.24))
    path.lineTo(_pt(r, 0.62, 0.56))
    path.lineTo(_pt(r, 0.41, 0.82))
    path.lineTo(_pt(r, 0.2, 0.56))
    path.closeSubpath()
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False)
    # atomiser nozzle + spray
    _line(p, r, 0.41, 0.16, 0.41, 0.24)
    for dx in (-0.06, 0, 0.06):
        _line(p, r, 0.41, 0.3, 0.41 + dx, 0.44)
    # cyclone
    _setup(p, c, base=r.width())
    poly = QPolygonF([_pt(r, 0.72, 0.34), _pt(r, 0.86, 0.34),
                      _pt(r, 0.82, 0.6), _pt(r, 0.76, 0.6)])
    p.drawPolygon(poly)


def _draw_drum_dryer(p, r, c):
    _setup(p, c, base=r.width())
    p.drawEllipse(_pt(r, 0.48, 0.5), r.width() * 0.26, r.width() * 0.26)
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    p.drawEllipse(_pt(r, 0.48, 0.5), r.width() * 0.05, r.width() * 0.05)
    # scraper blade
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.76, 0.36, 0.9, 0.32)
    _line(p, r, 0.76, 0.36, 0.76, 0.44)


def _draw_freeze_dryer(p, r, c):
    _setup(p, c, base=r.width())
    p.drawRect(_rect(r, 0.24, 0.24, 0.52, 0.56))
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    # shelves
    for y in (0.38, 0.52, 0.66):
        _line(p, r, 0.3, y, 0.7, y)
    # snowflake
    _setup(p, c, base=r.width(), fill=False)
    import math
    cx, cy = 0.82, 0.3
    for a in range(0, 180, 60):
        dx = 0.05 * math.cos(math.radians(a))
        dy = 0.05 * math.sin(math.radians(a))
        _line(p, r, cx - dx, cy - dy, cx + dx, cy + dy)


def _draw_evaporator(p, r, c):
    _setup(p, c, base=r.width())
    col = _rect(r, 0.34, 0.16, 0.3, 0.66)
    path = QPainterPath()
    path.addRoundedRect(col, r.width() * 0.05, r.width() * 0.05)
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False)
    # heating coil at bottom
    for y in (0.62, 0.7):
        _line(p, r, 0.38, y, 0.6, y)
    # vapour arrow up
    _line(p, r, 0.49, 0.06, 0.49, 0.16)
    _line(p, r, 0.45, 0.1, 0.49, 0.06)
    _line(p, r, 0.53, 0.1, 0.49, 0.06)


# --------------------------------------------------------------------------- #
# Downstream
# --------------------------------------------------------------------------- #
def _draw_bead_mill(p, r, c):
    _setup(p, c, base=r.width())
    body = _rect(r, 0.2, 0.36, 0.6, 0.3)
    path = QPainterPath()
    path.addRoundedRect(body, r.height() * 0.14, r.height() * 0.14)
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False, weight=0.05)
    # beads
    import itertools
    for x, y in itertools.product((0.3, 0.4, 0.5, 0.6, 0.7), (0.45, 0.57)):
        p.drawEllipse(_pt(r, x, y), r.width() * 0.02, r.width() * 0.02)
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.1, 0.5, 0.2, 0.5)
    _line(p, r, 0.8, 0.5, 0.9, 0.5)


def _draw_homogenizer(p, r, c):
    _setup(p, c, base=r.width())
    p.drawRect(_rect(r, 0.24, 0.32, 0.4, 0.4))
    _setup(p, c, base=r.width(), fill=False)
    # piston
    _line(p, r, 0.24, 0.52, 0.12, 0.52)
    p.drawRect(_rect(r, 0.08, 0.46, 0.06, 0.12))
    # high-pressure valve nozzle
    poly = QPolygonF([_pt(r, 0.64, 0.44), _pt(r, 0.8, 0.5), _pt(r, 0.64, 0.56)])
    p.drawPolygon(poly)
    _line(p, r, 0.8, 0.5, 0.9, 0.5)


def _draw_extraction_column(p, r, c):
    _setup(p, c, base=r.width())
    col = _rect(r, 0.38, 0.12, 0.24, 0.76)
    path = QPainterPath()
    path.addRoundedRect(col, r.width() * 0.04, r.width() * 0.04)
    p.drawPath(path)
    _setup(p, c, base=r.width(), fill=False, weight=0.045)
    # packing (X hatches)
    for y in (0.26, 0.4, 0.54, 0.68):
        _line(p, r, 0.4, y, 0.6, y + 0.06)
        _line(p, r, 0.6, y, 0.4, y + 0.06)
    _setup(p, c, base=r.width(), fill=False)
    # side ports
    _line(p, r, 0.28, 0.22, 0.38, 0.22)
    _line(p, r, 0.62, 0.78, 0.72, 0.78)


# --------------------------------------------------------------------------- #
# Logic / auxiliary
# --------------------------------------------------------------------------- #
def _draw_mixer(p, r, c):
    _setup(p, c, base=r.width(), fill=True)
    p.drawEllipse(_pt(r, 0.5, 0.5), r.width() * 0.28, r.width() * 0.28)
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.28, 0.36, 0.5, 0.5)
    _line(p, r, 0.28, 0.64, 0.5, 0.5)
    _line(p, r, 0.5, 0.5, 0.74, 0.5)


def _draw_splitter(p, r, c):
    _setup(p, c, base=r.width(), fill=True)
    p.drawEllipse(_pt(r, 0.5, 0.5), r.width() * 0.28, r.width() * 0.28)
    _setup(p, c, base=r.width(), fill=False)
    _line(p, r, 0.26, 0.5, 0.5, 0.5)
    _line(p, r, 0.5, 0.5, 0.72, 0.36)
    _line(p, r, 0.5, 0.5, 0.72, 0.64)


def _draw_pump(p, r, c):
    _setup(p, c, base=r.width(), fill=True)
    p.drawEllipse(_pt(r, 0.5, 0.52), r.width() * 0.26, r.width() * 0.26)
    _setup(p, c, base=r.width(), fill=False)
    # impeller triangle
    poly = QPolygonF([_pt(r, 0.42, 0.4), _pt(r, 0.42, 0.64), _pt(r, 0.64, 0.52)])
    p.drawPolygon(poly)
    # suction + discharge ports
    _line(p, r, 0.16, 0.52, 0.24, 0.52)
    _line(p, r, 0.5, 0.26, 0.5, 0.16)


def _draw_hx(p, r, c):
    _setup(p, c, base=r.width(), fill=True)
    p.drawEllipse(_pt(r, 0.5, 0.5), r.width() * 0.3, r.width() * 0.3)
    _setup(p, c, base=r.width(), fill=False)
    # zig-zag through the shell
    path = QPainterPath(_pt(r, 0.24, 0.5))
    path.lineTo(_pt(r, 0.38, 0.34))
    path.lineTo(_pt(r, 0.5, 0.66))
    path.lineTo(_pt(r, 0.62, 0.34))
    path.lineTo(_pt(r, 0.76, 0.5))
    p.drawPath(path)


# --------------------------------------------------------------------------- #
# registry + public API
# --------------------------------------------------------------------------- #
ICONS: dict[str, Drawer] = {
    "tank": _draw_tank,
    "gas": _draw_gas,
    "drum": _draw_drum,
    "waste": _draw_waste,
    "raceway": _draw_raceway,
    "tubular": _draw_tubular,
    "flat_panel": _draw_flat_panel,
    "bubble_column": _draw_bubble_column,
    "stirred_tank": _draw_stirred_tank,
    "centrifuge": _draw_centrifuge,
    "decanter": _draw_decanter,
    "membrane": _draw_membrane,
    "filter_press": _draw_filter_press,
    "settler": _draw_settler,
    "spray_dryer": _draw_spray_dryer,
    "drum_dryer": _draw_drum_dryer,
    "freeze_dryer": _draw_freeze_dryer,
    "evaporator": _draw_evaporator,
    "bead_mill": _draw_bead_mill,
    "homogenizer": _draw_homogenizer,
    "extraction_column": _draw_extraction_column,
    "mixer": _draw_mixer,
    "splitter": _draw_splitter,
    "pump": _draw_pump,
    "hx": _draw_hx,
}


def paint_icon(painter: QPainter, key: str, rect: QRectF, color: QColor) -> None:
    """Draw the icon ``key`` inside ``rect`` (no-op if the key is unknown)."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    drawer = ICONS.get(key)
    if drawer is not None:
        drawer(painter, rect, color)
    painter.restore()


def icon_pixmap(key: str, size: int, color: QColor) -> QPixmap:
    """Rasterise an icon to a transparent ``QPixmap`` (for the palette list)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    paint_icon(painter, key, QRectF(1, 1, size - 2, size - 2), color)
    painter.end()
    return pm
