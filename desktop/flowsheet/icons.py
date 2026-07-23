"""Engineering (P&ID / PFD-standard) vector symbols for process equipment.

Every icon is a small function ``draw(painter, rect, color)`` that renders a
technically correct symbol of a unit operation inside ``rect`` using ``color``.
The style is *detailed engineering*: a crisp stroke over a soft vertical
gradient body fill (depth), with real equipment internals — dished vessel heads,
jackets, agitator turbines, disc stacks, trays with downcomers, shell-and-tube
bundles with baffles, rotary atomisers, level gauges — and flanged nozzles.
Symbols are resolution independent (pure ``QPainter`` geometry) so they stay
crisp at any zoom and can be rasterised to a ``QPixmap`` for the palette.

Add a new piece of equipment by writing a ``_draw_*`` function and registering
it in :data:`ICONS`; then point a :class:`~desktop.flowsheet.model.UnitSpec` at
its key via the ``icon`` field. The node draws the symbol in its category colour,
so keep the geometry colour-agnostic (stroke/fill with the passed ``color``).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
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


def _pen(painter: QPainter, color: QColor, r: QRectF, w: float = 0.028,
         fill: QColor | None = None) -> None:
    """Thin, uniform engineering stroke (round caps/joins); optional solid fill."""
    lw = max(1.2, w * r.width())
    pen = QPen(QColor(color), lw)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(fill)) if fill is not None else Qt.NoBrush)


def _grad(color: QColor, r: QRectF, y0: float, y1: float) -> QBrush:
    """Soft vertical gradient tint of ``color`` from y0 (top) to y1 (bottom)."""
    g = QLinearGradient(_pt(r, 0.0, y0), _pt(r, 0.0, y1))
    top, bot = QColor(color), QColor(color)
    top.setAlpha(52)
    bot.setAlpha(14)
    g.setColorAt(0.0, top)
    g.setColorAt(1.0, bot)
    return QBrush(g)


def _fillpath(painter, color, r, path: QPainterPath, y0: float, y1: float,
              w: float = 0.028) -> None:
    """Stroke ``path`` with a gradient body fill, then reset to a no-fill pen."""
    _pen(painter, color, r, w)
    painter.setBrush(_grad(color, r, y0, y1))
    painter.drawPath(path)
    _pen(painter, color, r, w)


def _line(painter, r, x1, y1, x2, y2):
    painter.drawLine(_pt(r, x1, y1), _pt(r, x2, y2))


def _poly(painter, r, pts, close=False):
    poly = QPolygonF([_pt(r, x, y) for x, y in pts])
    if close:
        painter.drawPolygon(poly)
    else:
        painter.drawPolyline(poly)


def _flange(painter, r, x, y, vertical_pipe: bool, s: float = 0.045):
    """A flange bar across a nozzle tip (perpendicular to the pipe)."""
    if vertical_pipe:
        _line(painter, r, x - s, y, x + s, y)
    else:
        _line(painter, r, x, y - s, x, y + s)


# --------------------------------------------------------------------------- #
# IO / storage
# --------------------------------------------------------------------------- #
def _draw_tank(p, r, c):
    """Vertical storage vessel: dished heads, level gauge, manway, flanged nozzles."""
    path = QPainterPath(_pt(r, 0.32, 0.24))
    path.lineTo(_pt(r, 0.32, 0.78))
    path.quadTo(_pt(r, 0.50, 0.90), _pt(r, 0.68, 0.78))
    path.lineTo(_pt(r, 0.68, 0.24))
    path.quadTo(_pt(r, 0.50, 0.12), _pt(r, 0.32, 0.24))
    _fillpath(p, c, r, path, 0.12, 0.90)
    _line(p, r, 0.50, 0.16, 0.50, 0.06); _flange(p, r, 0.50, 0.06, True)
    _line(p, r, 0.50, 0.86, 0.50, 0.94); _flange(p, r, 0.50, 0.94, True, 0.04)
    _pen(p, c, r, 0.02)
    lg = _rect(r, 0.71, 0.34, 0.06, 0.34)                  # external level gauge
    p.drawRoundedRect(lg, lg.width() * 0.3, lg.width() * 0.3)
    _line(p, r, 0.68, 0.38, 0.71, 0.38); _line(p, r, 0.68, 0.64, 0.71, 0.64)
    p.drawEllipse(_pt(r, 0.42, 0.42), r.width() * 0.045, r.width() * 0.045)  # manway


def _draw_gas(p, r, c):
    """Compressed-gas cylinder: domed shoulder, valve, regulator gauge, flanged outlet."""
    path = QPainterPath(_pt(r, 0.38, 0.30))
    path.lineTo(_pt(r, 0.38, 0.82))
    path.quadTo(_pt(r, 0.50, 0.90), _pt(r, 0.62, 0.82))
    path.lineTo(_pt(r, 0.62, 0.30))
    path.quadTo(_pt(r, 0.50, 0.18), _pt(r, 0.38, 0.30))
    _fillpath(p, c, r, path, 0.18, 0.90)
    p.drawRect(_rect(r, 0.45, 0.10, 0.10, 0.08))           # valve body
    _line(p, r, 0.50, 0.18, 0.50, 0.24)
    _pen(p, c, r, 0.02)
    p.drawEllipse(_pt(r, 0.50, 0.06), r.width() * 0.035, r.width() * 0.035)  # gauge
    _pen(p, c, r)
    _line(p, r, 0.55, 0.14, 0.63, 0.14); _flange(p, r, 0.63, 0.14, False, 0.03)


def _draw_drum(p, r, c):
    """Closed product drum: elliptical chimes, hoops, bung."""
    body = QPainterPath(_pt(r, 0.30, 0.20))
    body.lineTo(_pt(r, 0.30, 0.80))
    body.quadTo(_pt(r, 0.50, 0.90), _pt(r, 0.70, 0.80))
    body.lineTo(_pt(r, 0.70, 0.20))
    _fillpath(p, c, r, body, 0.16, 0.90)
    p.drawEllipse(_rect(r, 0.30, 0.14, 0.40, 0.12))        # top rim
    _pen(p, c, r, 0.018)
    _line(p, r, 0.30, 0.42, 0.70, 0.42)                    # hoops
    _line(p, r, 0.30, 0.62, 0.70, 0.62)
    p.drawEllipse(_pt(r, 0.44, 0.20), r.width() * 0.03, r.width() * 0.02)   # bung


def _draw_waste(p, r, c):
    """Effluent / waste sump: liquid fill, surface line, flanged drain to sewer."""
    tank = QPainterPath(_pt(r, 0.30, 0.30))
    tank.lineTo(_pt(r, 0.34, 0.80)); tank.lineTo(_pt(r, 0.66, 0.80)); tank.lineTo(_pt(r, 0.70, 0.30))
    _fillpath(p, c, r, tank, 0.42, 0.80)
    _pen(p, c, r, 0.018)
    _line(p, r, 0.33, 0.42, 0.67, 0.42)                    # liquid surface
    _pen(p, c, r)
    _line(p, r, 0.50, 0.80, 0.50, 0.90); _flange(p, r, 0.50, 0.86, True, 0.04)
    _poly(p, r, [(0.45, 0.88), (0.50, 0.94), (0.55, 0.88)], close=True)


# --------------------------------------------------------------------------- #
# Cultivation / bioreactors
# --------------------------------------------------------------------------- #
def _draw_raceway(p, r, c):
    """Open raceway pond (plan view): channel water, island, paddlewheel, flow arrows."""
    outer = _rect(r, 0.12, 0.34, 0.76, 0.40)
    path = QPainterPath()
    path.addRoundedRect(outer, outer.height() / 2, outer.height() / 2)
    _fillpath(p, c, r, path, 0.34, 0.74)
    inner = _rect(r, 0.26, 0.45, 0.48, 0.18)
    path2 = QPainterPath()
    path2.addRoundedRect(inner, inner.height() / 2, inner.height() / 2)
    p.setBrush(QBrush(QColor("#ffffff"))); p.drawPath(path2)   # island (carves channel)
    _pen(p, c, r)
    p.drawPath(path2)
    cx, cy, rad = 0.30, 0.54, 0.055                        # paddlewheel
    p.drawEllipse(_pt(r, cx, cy), rad * r.width(), rad * r.width())
    for a in range(0, 180, 45):
        dx = rad * math.cos(math.radians(a)); dy = rad * math.sin(math.radians(a))
        _line(p, r, cx - dx, cy - dy, cx + dx, cy + dy)
    _pen(p, c, r, 0.02)                                    # flow arrow
    _line(p, r, 0.55, 0.40, 0.62, 0.40)
    _poly(p, r, [(0.60, 0.375), (0.65, 0.40), (0.60, 0.425)], close=True)


def _draw_tubular(p, r, c):
    """Tubular PBR: manifold headers + serpentine tube bank with return bends."""
    lh = _rect(r, 0.16, 0.26, 0.06, 0.5)                   # headers
    rh = _rect(r, 0.80, 0.26, 0.06, 0.5)
    ph = QPainterPath(); ph.addRoundedRect(lh, lh.width() * 0.4, lh.width() * 0.4)
    _fillpath(p, c, r, ph, 0.26, 0.76)
    ph2 = QPainterPath(); ph2.addRoundedRect(rh, rh.width() * 0.4, rh.width() * 0.4)
    _fillpath(p, c, r, ph2, 0.26, 0.76)
    for y in (0.32, 0.44, 0.56, 0.68):                     # tubes
        _line(p, r, 0.22, y, 0.80, y)
    _line(p, r, 0.16, 0.32, 0.10, 0.32); _flange(p, r, 0.10, 0.32, True, 0.03)
    _line(p, r, 0.86, 0.68, 0.92, 0.68); _flange(p, r, 0.92, 0.68, True, 0.03)


def _draw_flat_panel(p, r, c):
    """Flat-panel PBR: gradient panels on a base frame with a gas manifold."""
    for x in (0.28, 0.46, 0.64):
        panel = QPainterPath(); panel.addRect(_rect(r, x, 0.22, 0.09, 0.56))
        _fillpath(p, c, r, panel, 0.22, 0.78)
    _line(p, r, 0.22, 0.82, 0.80, 0.82)                    # gas manifold
    for x in (0.325, 0.505, 0.685):
        _line(p, r, x, 0.78, x, 0.82)
    _line(p, r, 0.30, 0.82, 0.30, 0.88); _line(p, r, 0.70, 0.82, 0.70, 0.88)  # legs


def _draw_bubble_column(p, r, c):
    """Bubble-column / airlift PBR: liquid column, sparger, rising bubbles, gas in."""
    col = _rect(r, 0.38, 0.16, 0.24, 0.68)
    path = QPainterPath(); path.addRoundedRect(col, col.width() * 0.2, col.width() * 0.2)
    _fillpath(p, c, r, path, 0.16, 0.84)
    _pen(p, c, r, 0.02)
    _line(p, r, 0.43, 0.76, 0.57, 0.76)                    # sparger
    for (x, y, s) in ((0.46, 0.66, 0.022), (0.54, 0.56, 0.02),
                      (0.47, 0.46, 0.022), (0.55, 0.36, 0.018), (0.48, 0.28, 0.017)):
        p.drawEllipse(_pt(r, x, y), s * r.width(), s * r.width())
    _pen(p, c, r)
    _line(p, r, 0.50, 0.84, 0.50, 0.90); _flange(p, r, 0.50, 0.90, True, 0.035)
    _line(p, r, 0.50, 0.16, 0.50, 0.10)                    # top gas-off


def _draw_stirred_tank(p, r, c):
    """Jacketed CSTR: motor+gearbox, shaft, 2 Rushton turbines, baffles, jacket nozzles."""
    jak = QPainterPath(_pt(r, 0.26, 0.34))
    jak.lineTo(_pt(r, 0.26, 0.72)); jak.quadTo(_pt(r, 0.50, 0.92), _pt(r, 0.74, 0.72))
    jak.lineTo(_pt(r, 0.74, 0.34))
    _pen(p, c, r, 0.02); p.drawPath(jak)                   # jacket
    body = QPainterPath(_pt(r, 0.30, 0.30))
    body.lineTo(_pt(r, 0.30, 0.72)); body.quadTo(_pt(r, 0.50, 0.86), _pt(r, 0.70, 0.72))
    body.lineTo(_pt(r, 0.70, 0.30)); body.lineTo(_pt(r, 0.30, 0.30))
    _fillpath(p, c, r, body, 0.30, 0.86)
    p.drawRect(_rect(r, 0.45, 0.05, 0.10, 0.06))           # gearbox
    p.drawRect(_rect(r, 0.435, 0.11, 0.13, 0.07))          # motor
    _line(p, r, 0.50, 0.18, 0.50, 0.66)
    for y in (0.52, 0.64):
        _line(p, r, 0.41, y, 0.59, y)
        for xx in (0.41, 0.59):
            _line(p, r, xx, y - 0.035, xx, y + 0.035)
    _pen(p, c, r, 0.018)
    _line(p, r, 0.335, 0.36, 0.335, 0.66); _line(p, r, 0.665, 0.36, 0.665, 0.66)
    _pen(p, c, r, 0.02)
    _line(p, r, 0.26, 0.40, 0.20, 0.40); _line(p, r, 0.74, 0.66, 0.80, 0.66)


# --------------------------------------------------------------------------- #
# Separation / dewatering
# --------------------------------------------------------------------------- #
def _draw_centrifuge(p, r, c):
    """Disk-stack centrifuge: bowl, chevron disc stack, feed, phase outlets, drive."""
    body = QPainterPath(_pt(r, 0.34, 0.34))
    body.quadTo(_pt(r, 0.50, 0.20), _pt(r, 0.66, 0.34))
    body.lineTo(_pt(r, 0.66, 0.60)); body.quadTo(_pt(r, 0.50, 0.72), _pt(r, 0.34, 0.60))
    body.lineTo(_pt(r, 0.34, 0.34))
    _fillpath(p, c, r, body, 0.20, 0.72)
    _pen(p, c, r, 0.016)
    for y in (0.38, 0.44, 0.50):
        _poly(p, r, [(0.41, y), (0.50, y + 0.05), (0.59, y)])
    _pen(p, c, r)
    _line(p, r, 0.50, 0.20, 0.50, 0.10); _flange(p, r, 0.50, 0.10, True, 0.04)  # feed
    _line(p, r, 0.66, 0.30, 0.76, 0.30)                    # centrate
    _line(p, r, 0.50, 0.72, 0.50, 0.80)                    # solids
    p.drawRect(_rect(r, 0.42, 0.80, 0.16, 0.08))           # drive
    _line(p, r, 0.46, 0.88, 0.46, 0.92); _line(p, r, 0.54, 0.88, 0.54, 0.92)


def _draw_decanter(p, r, c):
    """Horizontal decanter centrifuge: tapered bowl, scroll, drive, supports, nozzles."""
    path = QPainterPath(_pt(r, 0.22, 0.40))
    path.lineTo(_pt(r, 0.66, 0.40)); path.lineTo(_pt(r, 0.80, 0.46))
    path.lineTo(_pt(r, 0.80, 0.56)); path.lineTo(_pt(r, 0.66, 0.62)); path.lineTo(_pt(r, 0.22, 0.62))
    path.quadTo(_pt(r, 0.16, 0.51), _pt(r, 0.22, 0.40))
    _fillpath(p, c, r, path, 0.40, 0.62)
    _pen(p, c, r, 0.018)
    for x in (0.30, 0.42, 0.54):                           # scroll flights
        _line(p, r, x, 0.42, x + 0.05, 0.60)
    _pen(p, c, r)
    p.drawRect(_rect(r, 0.10, 0.44, 0.06, 0.14))           # drive
    _line(p, r, 0.34, 0.62, 0.34, 0.72); _line(p, r, 0.60, 0.62, 0.60, 0.72)   # supports
    _line(p, r, 0.30, 0.40, 0.30, 0.32); _flange(p, r, 0.30, 0.32, True, 0.03)
    _line(p, r, 0.80, 0.51, 0.88, 0.51)                    # centrate


def _draw_membrane(p, r, c):
    """Membrane module (3-port): housing, angled sheets, flanged feed/retentate/permeate."""
    housing = QPainterPath(); housing.addRect(_rect(r, 0.28, 0.30, 0.44, 0.40))
    _fillpath(p, c, r, housing, 0.30, 0.70)
    p.drawRect(_rect(r, 0.26, 0.32, 0.03, 0.36))           # end caps
    p.drawRect(_rect(r, 0.71, 0.32, 0.03, 0.36))
    _pen(p, c, r, 0.018)
    for x in (0.36, 0.46, 0.56, 0.64):
        _line(p, r, x, 0.32, x, 0.68)
    _pen(p, c, r)
    _line(p, r, 0.26, 0.50, 0.16, 0.50); _flange(p, r, 0.16, 0.50, False, 0.035)  # feed
    _line(p, r, 0.74, 0.40, 0.84, 0.40); _flange(p, r, 0.84, 0.40, False, 0.03)   # retentate
    _line(p, r, 0.74, 0.60, 0.84, 0.60); _flange(p, r, 0.84, 0.60, False, 0.03)   # permeate


def _draw_filter_press(p, r, c):
    """Plate-and-frame press: platens, plate stack, hydraulic ram, tie bars, filtrate."""
    fp = QPainterPath(); fp.addRect(_rect(r, 0.18, 0.28, 0.06, 0.44))
    _fillpath(p, c, r, fp, 0.28, 0.72)
    mp = QPainterPath(); mp.addRect(_rect(r, 0.72, 0.28, 0.06, 0.44))
    _fillpath(p, c, r, mp, 0.28, 0.72)
    _pen(p, c, r, 0.02)
    for x in (0.30, 0.39, 0.48, 0.57, 0.66):               # plates
        _line(p, r, x, 0.30, x, 0.70)
    _pen(p, c, r)
    p.drawRect(_rect(r, 0.80, 0.42, 0.08, 0.16))           # hydraulic ram
    _line(p, r, 0.18, 0.24, 0.84, 0.24)                    # tie bars
    _line(p, r, 0.18, 0.76, 0.78, 0.76)
    _line(p, r, 0.40, 0.72, 0.40, 0.80); _line(p, r, 0.56, 0.72, 0.56, 0.80)   # filtrate


def _draw_settler(p, r, c):
    """Gravity settler / thickener: liquid cone, overflow launder, rake drive, underflow."""
    cone = QPainterPath(_pt(r, 0.22, 0.32))
    cone.lineTo(_pt(r, 0.78, 0.32)); cone.lineTo(_pt(r, 0.50, 0.80))
    _fillpath(p, c, r, cone, 0.32, 0.80)
    _line(p, r, 0.20, 0.32, 0.80, 0.32)                    # launder rim
    _pen(p, c, r, 0.02)
    _line(p, r, 0.50, 0.30, 0.50, 0.56)                    # rake shaft
    _line(p, r, 0.42, 0.56, 0.58, 0.56)                    # rake arm
    _line(p, r, 0.44, 0.56, 0.44, 0.60); _line(p, r, 0.56, 0.56, 0.56, 0.60)
    _pen(p, c, r)
    _line(p, r, 0.50, 0.80, 0.50, 0.88); _flange(p, r, 0.50, 0.84, True, 0.035)  # underflow
    _line(p, r, 0.78, 0.32, 0.86, 0.36)                    # overflow


# --------------------------------------------------------------------------- #
# Thermal
# --------------------------------------------------------------------------- #
def _draw_spray_dryer(p, r, c):
    """Spray dryer: chamber, rotary atomiser, hot-air inlet, cyclone with product out."""
    body = QPainterPath(_pt(r, 0.16, 0.32))
    body.quadTo(_pt(r, 0.16, 0.26), _pt(r, 0.22, 0.26))
    body.lineTo(_pt(r, 0.50, 0.26)); body.quadTo(_pt(r, 0.56, 0.26), _pt(r, 0.56, 0.32))
    body.lineTo(_pt(r, 0.56, 0.52)); body.lineTo(_pt(r, 0.36, 0.80)); body.lineTo(_pt(r, 0.16, 0.52))
    body.lineTo(_pt(r, 0.16, 0.32))
    _fillpath(p, c, r, body, 0.26, 0.80)
    p.drawRect(_rect(r, 0.31, 0.12, 0.10, 0.06))           # atomiser motor
    _line(p, r, 0.36, 0.18, 0.36, 0.24)
    _line(p, r, 0.30, 0.26, 0.42, 0.26)                    # atomiser disk
    _pen(p, c, r, 0.018)
    for dx in (-0.08, -0.03, 0.03, 0.08):
        _line(p, r, 0.36, 0.27, 0.36 + dx, 0.40)           # spray
    _pen(p, c, r)
    _line(p, r, 0.10, 0.30, 0.16, 0.30)                    # hot-air inlet
    p.drawPolygon(QPolygonF([_pt(r, 0.16, 0.27), _pt(r, 0.21, 0.30), _pt(r, 0.16, 0.33)]))
    cyc = QPainterPath(_pt(r, 0.70, 0.36))
    cyc.lineTo(_pt(r, 0.88, 0.36)); cyc.lineTo(_pt(r, 0.88, 0.48))
    cyc.lineTo(_pt(r, 0.79, 0.66)); cyc.lineTo(_pt(r, 0.70, 0.48)); cyc.lineTo(_pt(r, 0.70, 0.36))
    _fillpath(p, c, r, cyc, 0.36, 0.66)
    _line(p, r, 0.79, 0.30, 0.79, 0.36)                    # exhaust
    _line(p, r, 0.79, 0.66, 0.79, 0.74)                    # product out
    _line(p, r, 0.56, 0.34, 0.70, 0.40)                    # duct


def _draw_drum_dryer(p, r, c):
    """Rotary drum dryer: heated drum, hub & spokes, doctor blade, feed pan."""
    drum = QPainterPath()
    drum.addEllipse(_pt(r, 0.44, 0.50), r.width() * 0.24, r.width() * 0.24)
    _fillpath(p, c, r, drum, 0.26, 0.74)
    _pen(p, c, r, 0.02)
    p.drawEllipse(_pt(r, 0.44, 0.50), r.width() * 0.045, r.width() * 0.045)   # hub
    for a in range(0, 360, 90):                            # spokes
        dx = 0.20 * math.cos(math.radians(a)); dy = 0.20 * math.sin(math.radians(a))
        _line(p, r, 0.44, 0.50, 0.44 + dx, 0.50 + dy)
    _pen(p, c, r)
    _line(p, r, 0.68, 0.38, 0.84, 0.33); _line(p, r, 0.68, 0.38, 0.68, 0.46)   # doctor blade
    p.drawArc(_rect(r, 0.28, 0.74, 0.32, 0.14), 0, 180 * 16)  # feed pan


def _draw_freeze_dryer(p, r, c):
    """Lyophiliser: shelved chamber, condenser with coil, isolation valve, frost mark."""
    ch = QPainterPath(); ch.addRect(_rect(r, 0.20, 0.26, 0.40, 0.50))
    _fillpath(p, c, r, ch, 0.26, 0.76)
    _pen(p, c, r, 0.018)
    for y in (0.38, 0.50, 0.62):                           # shelves
        _line(p, r, 0.25, y, 0.55, y)
    _pen(p, c, r)
    cond = QPainterPath(); cond.addRoundedRect(_rect(r, 0.70, 0.40, 0.16, 0.30), 3, 3)
    _fillpath(p, c, r, cond, 0.40, 0.70)
    _pen(p, c, r, 0.018)
    _poly(p, r, [(0.74, 0.46), (0.82, 0.50), (0.74, 0.54), (0.82, 0.58)])       # coil
    _pen(p, c, r)
    _poly(p, r, [(0.60, 0.47), (0.66, 0.53), (0.60, 0.53), (0.66, 0.47)], close=True)  # valve
    _pen(p, c, r, 0.02)
    cx, cy = 0.78, 0.30                                    # frost asterisk
    for a in range(0, 180, 60):
        dx = 0.045 * math.cos(math.radians(a)); dy = 0.045 * math.sin(math.radians(a))
        _line(p, r, cx - dx, cy - dy, cx + dx, cy + dy)


def _draw_evaporator(p, r, c):
    """Evaporator: body, calandria tube bundle, vapour dome, demister, nozzles."""
    body = _rect(r, 0.34, 0.20, 0.32, 0.62)
    path = QPainterPath(); path.addRoundedRect(body, body.width() * 0.14, body.width() * 0.14)
    _fillpath(p, c, r, path, 0.20, 0.82)
    p.drawRect(_rect(r, 0.39, 0.56, 0.22, 0.16))           # calandria shell
    _pen(p, c, r, 0.018)
    for x in (0.43, 0.49, 0.55):                           # tubes
        _line(p, r, x, 0.56, x, 0.72)
    _line(p, r, 0.40, 0.30, 0.60, 0.30)                    # demister
    _pen(p, c, r)
    _line(p, r, 0.50, 0.20, 0.50, 0.08); _flange(p, r, 0.50, 0.08, True, 0.04)  # vapour
    _line(p, r, 0.66, 0.60, 0.74, 0.60)                    # steam in
    _line(p, r, 0.34, 0.68, 0.26, 0.68)                    # condensate
    _line(p, r, 0.50, 0.82, 0.50, 0.90)                    # concentrate


# --------------------------------------------------------------------------- #
# Downstream
# --------------------------------------------------------------------------- #
def _draw_bead_mill(p, r, c):
    """Jacketed bead mill: chamber, agitator discs, grinding beads, drive, nozzles."""
    body = _rect(r, 0.18, 0.38, 0.60, 0.26)
    path = QPainterPath(); path.addRoundedRect(body, body.height() * 0.4, body.height() * 0.4)
    _fillpath(p, c, r, path, 0.38, 0.64)
    _pen(p, c, r, 0.018)                                   # jacket
    jbody = _rect(r, 0.20, 0.41, 0.56, 0.20)
    jp = QPainterPath(); jp.addRoundedRect(jbody, jbody.height() * 0.4, jbody.height() * 0.4)
    p.drawPath(jp)
    _pen(p, c, r)
    _line(p, r, 0.22, 0.51, 0.72, 0.51)                    # shaft
    for x in (0.30, 0.42, 0.54, 0.64):                     # agitator discs
        _line(p, r, x, 0.45, x, 0.57)
    _pen(p, c, r, 0.016)
    for (x, y) in ((0.34, 0.46), (0.46, 0.56), (0.58, 0.45)):
        p.drawEllipse(_pt(r, x, y), r.width() * 0.018, r.width() * 0.018)
    _pen(p, c, r)
    p.drawRect(_rect(r, 0.78, 0.44, 0.06, 0.14))           # drive
    _line(p, r, 0.10, 0.51, 0.18, 0.51); _flange(p, r, 0.10, 0.51, False, 0.03)  # feed
    _line(p, r, 0.30, 0.38, 0.30, 0.31)                    # discharge


def _draw_homogenizer(p, r, c):
    """High-pressure homogeniser: crankcase, pump head, plunger, HP valve, gauge."""
    crank = QPainterPath(); crank.addRect(_rect(r, 0.18, 0.32, 0.20, 0.36))
    _fillpath(p, c, r, crank, 0.32, 0.68)
    head = QPainterPath(); head.addRect(_rect(r, 0.38, 0.38, 0.22, 0.24))
    _fillpath(p, c, r, head, 0.38, 0.62)
    _line(p, r, 0.14, 0.50, 0.18, 0.50)                    # plunger rod
    _poly(p, r, [(0.60, 0.42), (0.76, 0.50), (0.60, 0.58)], close=True)         # HP valve
    _line(p, r, 0.76, 0.50, 0.88, 0.50); _flange(p, r, 0.88, 0.50, False, 0.03)
    _pen(p, c, r, 0.02)
    p.drawEllipse(_pt(r, 0.49, 0.32), r.width() * 0.035, r.width() * 0.035)     # gauge
    _line(p, r, 0.49, 0.355, 0.49, 0.38)


def _draw_extraction_column(p, r, c):
    """Trayed extraction / distillation column: heads, trays with downcomers, nozzles."""
    x0, x1, yt, yb = 0.40, 0.60, 0.14, 0.86
    col = QPainterPath(_pt(r, x0, yt + 0.05))
    col.quadTo(_pt(r, x0, yt), _pt(r, 0.50, yt)); col.quadTo(_pt(r, x1, yt), _pt(r, x1, yt + 0.05))
    col.lineTo(_pt(r, x1, yb - 0.05)); col.quadTo(_pt(r, x1, yb), _pt(r, 0.50, yb))
    col.quadTo(_pt(r, x0, yb), _pt(r, x0, yb - 0.05)); col.lineTo(_pt(r, x0, yt + 0.05))
    _fillpath(p, c, r, col, yt, yb)
    _pen(p, c, r, 0.016)
    for i, y in enumerate((0.28, 0.38, 0.48, 0.58, 0.68)):     # trays + downcomers
        _line(p, r, x0, y, x1, y)
        dx = x0 + 0.02 if i % 2 == 0 else x1 - 0.02
        _line(p, r, dx, y, dx, y + 0.06)
    _pen(p, c, r)
    _line(p, r, 0.30, 0.22, x0, 0.22); _flange(p, r, 0.30, 0.22, True, 0.03)    # feed
    _line(p, r, 0.50, 0.14, 0.50, 0.06); _flange(p, r, 0.50, 0.06, True, 0.035) # vapour
    _line(p, r, x1, 0.80, 0.70, 0.80); _flange(p, r, 0.70, 0.80, True, 0.03)    # bottoms
    _line(p, r, 0.30, 0.74, x0, 0.74)                                           # reboiler return


# --------------------------------------------------------------------------- #
# Logic / auxiliary
# --------------------------------------------------------------------------- #
def _draw_mixer(p, r, c):
    """Stream mixing junction: two inlets converge to a single outlet."""
    p.setBrush(_grad(c, r, 0.38, 0.62))
    _pen(p, c, r)
    p.setBrush(_grad(c, r, 0.38, 0.62))
    p.drawEllipse(_pt(r, 0.50, 0.50), r.width() * 0.12, r.width() * 0.12)
    _pen(p, c, r)
    _line(p, r, 0.20, 0.36, 0.40, 0.47)                    # inlet a
    _line(p, r, 0.20, 0.64, 0.40, 0.53)                    # inlet b
    _line(p, r, 0.62, 0.50, 0.80, 0.50)                    # outlet
    _poly(p, r, [(0.74, 0.46), (0.80, 0.50), (0.74, 0.54)], close=True)


def _draw_splitter(p, r, c):
    """Stream splitting junction: one inlet, two outlets."""
    _pen(p, c, r)
    p.setBrush(_grad(c, r, 0.38, 0.62))
    p.drawEllipse(_pt(r, 0.50, 0.50), r.width() * 0.12, r.width() * 0.12)
    _pen(p, c, r)
    _line(p, r, 0.20, 0.50, 0.38, 0.50)                    # inlet
    _line(p, r, 0.60, 0.47, 0.80, 0.36)                    # outlet a
    _line(p, r, 0.60, 0.53, 0.80, 0.64)                    # outlet b
    _poly(p, r, [(0.75, 0.33), (0.81, 0.35), (0.77, 0.40)], close=True)
    _poly(p, r, [(0.77, 0.60), (0.81, 0.65), (0.75, 0.67)], close=True)


def _draw_pump(p, r, c):
    """Centrifugal pump: volute casing, impeller, motor & baseplate, flanged nozzles."""
    casing = QPainterPath()
    casing.addEllipse(_pt(r, 0.42, 0.50), r.width() * 0.22, r.width() * 0.22)
    _fillpath(p, c, r, casing, 0.28, 0.72)
    _pen(p, c, r, 0.024, fill=c)
    _poly(p, r, [(0.34, 0.40), (0.34, 0.60), (0.56, 0.50)], close=True)         # impeller
    _pen(p, c, r)
    _line(p, r, 0.20, 0.50, 0.12, 0.50); _flange(p, r, 0.12, 0.50, False, 0.035)  # suction
    _line(p, r, 0.42, 0.28, 0.42, 0.16); _flange(p, r, 0.42, 0.16, True, 0.035)   # discharge
    p.drawRect(_rect(r, 0.64, 0.42, 0.16, 0.16))           # motor
    _line(p, r, 0.60, 0.50, 0.64, 0.50)                    # coupling
    _line(p, r, 0.24, 0.74, 0.82, 0.74)                    # baseplate


def _draw_hx(p, r, c):
    """Shell-and-tube heat exchanger: shell, tube bundle, baffles, head bolts, nozzles."""
    shell = _rect(r, 0.16, 0.36, 0.68, 0.28)
    path = QPainterPath(); path.addRoundedRect(shell, shell.height() * 0.35, shell.height() * 0.35)
    _fillpath(p, c, r, path, 0.36, 0.64)
    _line(p, r, 0.27, 0.36, 0.27, 0.64); _line(p, r, 0.73, 0.36, 0.73, 0.64)   # channel heads
    _pen(p, c, r, 0.014)
    for y in (0.43, 0.48, 0.53, 0.58):                     # tubes
        _line(p, r, 0.27, y, 0.73, y)
    for i, x in enumerate((0.36, 0.46, 0.56, 0.66)):       # segmental baffles
        if i % 2 == 0:
            _line(p, r, x, 0.37, x, 0.55)
        else:
            _line(p, r, x, 0.45, x, 0.63)
    for by in (0.42, 0.50, 0.58):                          # head bolts
        p.drawEllipse(_pt(r, 0.225, by), r.width() * 0.008, r.width() * 0.008)
        p.drawEllipse(_pt(r, 0.775, by), r.width() * 0.008, r.width() * 0.008)
    _pen(p, c, r)
    _line(p, r, 0.34, 0.36, 0.34, 0.28); _flange(p, r, 0.34, 0.28, True, 0.03)  # nozzles
    _line(p, r, 0.66, 0.64, 0.66, 0.72); _flange(p, r, 0.66, 0.72, True, 0.03)
    _line(p, r, 0.16, 0.50, 0.08, 0.50); _line(p, r, 0.84, 0.50, 0.92, 0.50)


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
