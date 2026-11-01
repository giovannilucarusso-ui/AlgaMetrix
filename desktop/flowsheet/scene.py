"""Interactive canvas: nodes, ports, streams — engineering (PFD) styling.

``FlowsheetScene`` renders a :class:`~desktop.flowsheet.model.Flowsheet` as
draggable :class:`NodeItem` equipment blocks whose :class:`PortItem` nozzles can
be wired together into :class:`EdgeItem` streams. On top of the plain diagram it
draws what the engine says about each part of it:

* streams coloured by what they carry and drawn wider the more they carry
  (log scale), with moving dashes for the flow direction;
* a read-out plate under every block, and a status lamp (linked and fine,
  warning, refused input, or drawn by hand);
* a halo behind each block coloured by the active layer (mass, energy, cost,
  GWP), and a dashed frame around each plant area;
* electricity and heat headers with a drop to every block that draws on them;
* a drawing sheet with zone marks, a legend and a title block.

The scene owns the interaction logic (drag-to-connect, delete, snap-to-grid) and
keeps the model in sync, emitting :attr:`graphChanged` on topology edits and
:attr:`nodeSelected` on selection changes.
"""

from __future__ import annotations

import math
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
)

from . import icons, model as M
from .theme import LAYER_LABELS, PAPER, STREAM_LABELS, Theme, category_color

# --- geometry ---------------------------------------------------------------- #
GRID = 20
SNAP = 10
NODE_W = 190.0
NODE_H = 150.0
LABEL_H = 16.0
SYM = 78.0                 # symbol size in the PFD (boxless) look
SYM_Y = 20.0
FACE_Y = 104.0             # read-out plate
FACE_LINE = 14.0
STUB = 12.0
PORT = 4.5                 # half-side of the square nozzle handle
CARD_SYM = 60.0            # symbol size in the boxed look

# Kept for callers that import the old names.
CANVAS_BG = PAPER.canvas

_UI = "Segoe UI"
_MONO = "Consolas"


def _font(size: float, weight=QFont.Normal, family: str = _UI) -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def _alpha(color: str | QColor, a: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, a)))
    return c


def _sym_rect() -> QRectF:
    return QRectF((NODE_W - SYM) / 2.0, SYM_Y, SYM, SYM)


def _port_band() -> tuple[float, float]:
    return SYM_Y + 10.0, SYM_Y + SYM - 10.0


# --------------------------------------------------------------------------- #
# Small vector glyphs (no emoji: they must print and follow the theme)
# --------------------------------------------------------------------------- #
def draw_glyph(painter, kind: str, center: QPointF, size: float, color: QColor) -> None:
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    x, y, s = center.x(), center.y(), size
    if kind == "power":       # lightning bolt
        poly = QPolygonF([QPointF(x + 0.10 * s, y - 0.50 * s), QPointF(x - 0.32 * s, y + 0.08 * s),
                          QPointF(x - 0.02 * s, y + 0.08 * s), QPointF(x - 0.12 * s, y + 0.50 * s),
                          QPointF(x + 0.32 * s, y - 0.10 * s), QPointF(x + 0.02 * s, y - 0.10 * s)])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPolygon(poly)
    elif kind == "heat":      # flame
        path = QPainterPath(QPointF(x, y - 0.52 * s))
        path.cubicTo(QPointF(x + 0.42 * s, y - 0.10 * s), QPointF(x + 0.40 * s, y + 0.46 * s),
                     QPointF(x, y + 0.50 * s))
        path.cubicTo(QPointF(x - 0.40 * s, y + 0.46 * s), QPointF(x - 0.36 * s, y - 0.02 * s),
                     QPointF(x - 0.10 * s, y - 0.18 * s))
        path.cubicTo(QPointF(x - 0.06 * s, y + 0.02 * s), QPointF(x + 0.04 * s, y - 0.20 * s),
                     QPointF(x, y - 0.52 * s))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)
    elif kind == "evap":      # rising vapour: three wavy strokes
        pen = QPen(color, max(1.0, s * 0.11), Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for dx in (-0.28, 0.0, 0.28):
            p = QPainterPath(QPointF(x + dx * s, y + 0.45 * s))
            p.cubicTo(QPointF(x + (dx - 0.16) * s, y + 0.15 * s),
                      QPointF(x + (dx + 0.16) * s, y - 0.10 * s),
                      QPointF(x + dx * s, y - 0.45 * s))
            painter.drawPath(p)
    painter.restore()


# --------------------------------------------------------------------------- #
# Ports (equipment nozzles)
# --------------------------------------------------------------------------- #
class PortItem(QGraphicsItem):
    """A square nozzle handle sitting at the tip of a short stub."""

    def __init__(self, node_item: "NodeItem", name: str, is_input: bool):
        super().__init__(node_item)
        self.node_item = node_item
        self.port_name = name
        self.is_input = is_input
        self.setZValue(3)
        self.setAcceptHoverEvents(True)
        self._hover = False
        self.setToolTip(f"{'inlet' if is_input else 'outlet'} · {name}")

    def boundingRect(self) -> QRectF:
        r = PORT + 4
        return QRectF(-r, -r, 2 * r, 2 * r)

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        color = QColor(self.node_item.accent)
        theme = self.node_item.theme
        # In the PFD (boxless) view the handle is a discreet dot; it grows into the
        # square grab-target on hover so wiring by hand stays easy.
        if getattr(NodeItem, "BOXLESS", False) and not self._hover:
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(0, 0), 2.3, 2.3)
            return
        s = PORT + (1.5 if self._hover else 0.0)
        rect = QRectF(-s, -s, 2 * s, 2 * s)
        painter.setBrush(QBrush(QColor(theme.face_bg) if self.is_input else color))
        painter.setPen(QPen(color, 1.6))
        painter.drawRect(rect)


# --------------------------------------------------------------------------- #
# Nodes (equipment blocks)
# --------------------------------------------------------------------------- #
class NodeItem(QGraphicsObject):
    """A draggable equipment block bound to a :class:`model.UnitNode`."""

    # Rendering mode (class-wide toggle, flipped from the editor toolbar):
    # True  -> PFD look: the symbol floats on the sheet (no card / box).
    # False -> card look: a boxed block with port labels (better for wiring).
    BOXLESS = True

    STATUS_TEXT = {"ok": "Linked to the case study", "warning": "Linked; input warning",
                   "error": "Linked; input refused by the engine", "idle": "Drawn by hand"}

    def __init__(self, node: M.UnitNode, theme: Theme = PAPER):
        super().__init__()
        self.node = node
        self.sp = node.spec
        self.theme = theme
        self.accent = category_color(self.sp.category, theme)
        self._lines: list = []          # read-out plate: list of [(glyph, text)]
        self._status = "ok" if node.role else "idle"
        self._status_note = ""
        self._halo = 0.0                # 0..1 intensity of the layer halo
        self._halo_color = QColor(theme.layer["mass"])
        self._badge = ""                # layer value pill
        self._parallel = 0
        self._hover = False

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.setPos(node.x, node.y)

        self.ports: dict[tuple[bool, str], PortItem] = {}
        self._make_ports()
        self._refresh_tooltip()

    # -- ports ----------------------------------------------------------- #
    def _make_ports(self):
        for i, name in enumerate(self.sp.inputs):
            p = PortItem(self, name, True)
            p.setPos(-STUB, self._port_y(i, len(self.sp.inputs)))
            self.ports[(True, name)] = p
        for i, name in enumerate(self.sp.outputs):
            p = PortItem(self, name, False)
            p.setPos(NODE_W + STUB, self._port_y(i, len(self.sp.outputs)))
            self.ports[(False, name)] = p

    def _port_y(self, index: int, count: int) -> float:
        top, bot = _port_band()
        if count <= 1:
            return (top + bot) / 2.0
        return top + (bot - top) * index / (count - 1)

    def port(self, name: str, is_input: bool) -> PortItem | None:
        return self.ports.get((is_input, name))

    # -- state pushed by the editor -------------------------------------- #
    def set_theme(self, theme: Theme):
        self.theme = theme
        self.accent = category_color(self.sp.category, theme)
        self.update()
        for p in self.ports.values():
            p.update()

    def set_readout(self, lines):
        """``lines``: list of lines, each a list of (glyph, text) segments, or a string."""
        if isinstance(lines, str):
            lines = [[("", lines)]] if lines else []
        lines = [ln for ln in lines if ln]
        if lines != self._lines:
            self._lines = lines
            self.update()

    def set_status(self, status: str, note: str = ""):
        if (status, note) != (self._status, self._status_note):
            self._status, self._status_note = status, note
            self._refresh_tooltip()
            self.update()

    def set_overlay(self, intensity: float, color: QColor | str | None = None, badge: str = ""):
        self._halo = max(0.0, min(1.0, intensity))
        if color is not None:
            self._halo_color = QColor(color)
        self._badge = badge
        self.update()

    def set_parallel(self, n: int):
        if n != self._parallel:
            self._parallel = n
            self.update()

    def _refresh_tooltip(self):
        n = self.node
        text = f"<b>{n.tag}</b> {n.name}<br><span style='color:#64748b'>{self.sp.label}</span>"
        text += f"<br>{self.STATUS_TEXT.get(self._status, '')}"
        if self._status_note:
            text += f"<br><span style='color:#b45309'>{self._status_note}</span>"
        self.setToolTip(text)

    # -- painting -------------------------------------------------------- #
    def boundingRect(self) -> QRectF:
        return QRectF(-STUB - 8, -8, NODE_W + 2 * STUB + 16, NODE_H + 14)

    def core_rect(self) -> QRectF:
        """The block without its nozzle stubs, in scene coordinates."""
        return QRectF(self.pos().x(), self.pos().y(), NODE_W, NODE_H)

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setRenderHint(painter.RenderHint.TextAntialiasing, True)
        if getattr(NodeItem, "BOXLESS", False):
            self._paint_boxless(painter)
        else:
            self._paint_card(painter)

    def _paint_status(self, painter, center: QPointF):
        t = self.theme
        color = QColor({"ok": t.ok, "warning": t.warn, "error": t.error}.get(self._status, t.idle))
        glow = QRadialGradient(center, 6.5)
        glow.setColorAt(0.0, _alpha(color, 150))
        glow.setColorAt(1.0, _alpha(color, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, 6.5, 6.5)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(color.darker(130), 0.8))
        painter.drawEllipse(center, 3.0, 3.0)

    def _paint_label_row(self, painter, y: float):
        t = self.theme
        tag = self.node.tag or ""
        f_tag = _font(8, QFont.Bold, _MONO)
        f_name = _font(8)
        fm_tag = QFontMetricsF(f_tag)
        fm_name = QFontMetricsF(f_name)
        tag_w = fm_tag.horizontalAdvance(tag)
        name = fm_name.elidedText(self.node.name, Qt.ElideRight, NODE_W - tag_w - 34)
        name_w = fm_name.horizontalAdvance(name) if name else 0.0
        gap = 6.0 if name else 0.0
        lamp = 10.0
        x0 = (NODE_W - (lamp + tag_w + gap + name_w)) / 2.0
        self._paint_status(painter, QPointF(x0 + 3.0, y + LABEL_H / 2.0))
        painter.setFont(f_tag)
        painter.setPen(QPen(QColor(t.ink)))
        painter.drawText(QRectF(x0 + lamp, y, tag_w + 2, LABEL_H), Qt.AlignVCenter | Qt.AlignLeft, tag)
        if name:
            painter.setFont(f_name)
            painter.setPen(QPen(QColor(t.ink_dim)))
            painter.drawText(QRectF(x0 + lamp + tag_w + gap, y, name_w + 2, LABEL_H),
                             Qt.AlignVCenter | Qt.AlignLeft, name)

    def _paint_halo(self, painter, sym: QRectF):
        if self._halo <= 0.0:
            return
        c = sym.center()
        r = SYM * 0.78
        g = QRadialGradient(c, r)
        g.setColorAt(0.0, _alpha(self._halo_color, int(40 + 150 * self._halo)))
        g.setColorAt(0.55, _alpha(self._halo_color, int(20 + 80 * self._halo)))
        g.setColorAt(1.0, _alpha(self._halo_color, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(g))
        painter.drawEllipse(c, r, r)

    def _paint_badge(self, painter, sym: QRectF):
        if not self._badge:
            return
        f = _font(7, QFont.Bold)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(self._badge) + 10
        box = QRectF(sym.right() - w * 0.35, sym.top() - 2, w, 14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._halo_color))
        painter.drawRoundedRect(box, 7, 7)
        painter.setFont(f)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(box, Qt.AlignCenter, self._badge)

    def _paint_symbol(self, painter, sym: QRectF, accent: QColor):
        if self._parallel > 1:
            # Identical units in parallel: two ghost copies behind the symbol.
            for k in (2, 1):
                ghost = sym.translated(5.0 * k, -5.0 * k)
                painter.save()
                painter.setOpacity(0.22 if k == 2 else 0.38)
                icons.paint_icon(painter, self.sp.icon, ghost, accent, self.theme.paper)
                painter.restore()
        icons.paint_icon(painter, self.sp.icon, sym, accent, self.theme.paper)
        if self._parallel > 1:
            f = _font(7, QFont.Bold)
            text = f"×{self._parallel}"
            w = QFontMetricsF(f).horizontalAdvance(text) + 8
            box = QRectF(sym.right() - w + 6, sym.bottom() - 12, w, 13)
            painter.setPen(QPen(accent, 1.0))
            painter.setBrush(QBrush(QColor(self.theme.face_bg)))
            painter.drawRoundedRect(box, 3, 3)
            painter.setFont(f)
            painter.setPen(QPen(accent))
            painter.drawText(box, Qt.AlignCenter, text)

    def _paint_plate(self, painter, top: float, width_max: float):
        if not self._lines:
            return
        t = self.theme
        f = _font(7.5, QFont.DemiBold)
        fm = QFontMetricsF(f)
        glyph_w = 11.0

        def seg_w(seg):
            g, text = seg
            return (glyph_w if g else 0.0) + fm.horizontalAdvance(text)

        widths = [sum(seg_w(s) for s in ln) + 10.0 * (len(ln) - 1) for ln in self._lines]
        w = min(max(max(widths) + 16.0, 92.0), width_max)
        h = FACE_LINE * len(self._lines) + 6.0
        box = QRectF((NODE_W - w) / 2.0, top, w, h)
        painter.setBrush(QBrush(QColor(t.face_bg)))
        painter.setPen(QPen(QColor(t.face_border), 1.0))
        painter.drawRoundedRect(box, 4, 4)
        # a thin accent tick on the left edge ties the plate to its block
        painter.setPen(QPen(QColor(self.accent), 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(box.left() + 1.5, box.top() + 4), QPointF(box.left() + 1.5, box.bottom() - 4))
        painter.setFont(f)
        for i, (ln, lw) in enumerate(zip(self._lines, widths)):
            x = (NODE_W - lw) / 2.0
            y = top + 3.0 + i * FACE_LINE
            for g, text in ln:
                if g:
                    color = QColor({"power": t.elec, "heat": t.heat}.get(g, t.layer["mass"]))
                    draw_glyph(painter, g, QPointF(x + 4.5, y + FACE_LINE / 2.0), 9.0, color)
                    x += glyph_w
                painter.setPen(QPen(QColor(t.face_ink)))
                tw = fm.horizontalAdvance(text)
                painter.drawText(QRectF(x, y, tw + 2, FACE_LINE), Qt.AlignVCenter | Qt.AlignLeft, text)
                x += tw + 10.0

    def _paint_selection(self, painter, rect: QRectF):
        t = self.theme
        if self.isSelected():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(_alpha(t.selection, 18)))
            painter.drawRoundedRect(rect, 8, 8)
            pen = QPen(QColor(t.selection), 2.0, Qt.SolidLine, Qt.SquareCap)
            painter.setPen(pen)
            k = 12.0
            for (x, y, dx, dy) in ((rect.left(), rect.top(), 1, 1), (rect.right(), rect.top(), -1, 1),
                                   (rect.left(), rect.bottom(), 1, -1),
                                   (rect.right(), rect.bottom(), -1, -1)):
                painter.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
                painter.drawLine(QPointF(x, y), QPointF(x, y + dy * k))
        elif self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(_alpha(t.hover, 200)))
            painter.drawRoundedRect(rect, 8, 8)

    def _paint_boxless(self, painter):
        """PFD look: the symbol floats on the sheet. Tag and name sit above, the
        read-out plate below, and thin accent leaders run from the symbol edge out
        to the connection points."""
        accent = QColor(self.accent)
        self._paint_selection(painter, QRectF(-4, -5, NODE_W + 8, NODE_H + 8))
        sym = _sym_rect()
        self._paint_halo(painter, sym)
        self._paint_label_row(painter, 0.0)

        scene = self.scene()
        wired = scene.wired if isinstance(scene, FlowsheetScene) else set()
        open_pen = QPen(_alpha(accent, 70), 1.2, Qt.DotLine)
        for (is_input, name), port in self.ports.items():
            y = port.pos().y()
            connected = (self.node.id, name, is_input) in wired
            painter.setPen(QPen(accent, 1.6) if connected else open_pen)
            if is_input:
                painter.drawLine(QPointF(sym.left() + 4, y), QPointF(-STUB, y))
            else:
                painter.drawLine(QPointF(sym.right() - 4, y), QPointF(NODE_W + STUB, y))
        self._paint_symbol(painter, sym, accent)
        self._paint_badge(painter, sym)
        self._paint_plate(painter, FACE_Y, NODE_W - 4)

    def _paint_card(self, painter):
        """Boxed look: a card with an accent bar, port labels and the plate inside."""
        t = self.theme
        accent = QColor(self.accent)
        selected = self.isSelected()
        body = QRectF(0, 0, NODE_W, NODE_H)
        path = QPainterPath()
        path.addRoundedRect(body, 6, 6)
        painter.setBrush(QBrush(QColor(t.face_bg)))
        painter.setPen(QPen(QColor(t.selection) if selected else QColor(t.face_border),
                            2.0 if selected else 1.1))
        painter.drawPath(path)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(0, 0, NODE_W, 4), accent)
        painter.restore()
        self._paint_label_row(painter, 6.0)
        sym = QRectF((NODE_W - CARD_SYM) / 2.0, SYM_Y + 9.0, CARD_SYM, CARD_SYM)
        self._paint_halo(painter, sym)
        self._paint_symbol(painter, sym, accent)
        self._paint_badge(painter, sym)
        painter.setFont(_font(6, QFont.DemiBold))
        pen_stub = QPen(QColor(t.face_border), 1.4)
        lbl_w = NODE_W * 0.34
        for (is_input, name), p in self.ports.items():
            y = p.pos().y()
            painter.setPen(pen_stub)
            if is_input:
                painter.drawLine(QPointF(0, y), QPointF(-STUB, y))
            else:
                painter.drawLine(QPointF(NODE_W, y), QPointF(NODE_W + STUB, y))
            painter.setPen(QPen(QColor(t.ink_faint)))
            if is_input:
                painter.drawText(QRectF(4, y - 8, lbl_w, 16), Qt.AlignVCenter | Qt.AlignLeft, name)
            else:
                painter.drawText(QRectF(NODE_W - 4 - lbl_w, y - 8, lbl_w, 16),
                                 Qt.AlignVCenter | Qt.AlignRight, name)
        self._paint_plate(painter, FACE_Y + 2.0, NODE_W - 10)

    # -- movement: snap to grid, keep model + edges in sync -------------- #
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and isinstance(value, QPointF):
            return QPointF(round(value.x() / SNAP) * SNAP, round(value.y() / SNAP) * SNAP)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            scene = self.scene()
            if isinstance(scene, FlowsheetScene):
                scene.update_edges_for(self.node.id)
                scene.schedule_decor()
        return super().itemChange(change, value)


# --------------------------------------------------------------------------- #
# Orthogonal routing helpers
# --------------------------------------------------------------------------- #
def _ortho_points(p1: QPointF, p2: QPointF) -> list[QPointF]:
    """Right-angle route from an outlet (p1) to an inlet (p2)."""
    s = 16.0
    x1, y1 = p1.x(), p1.y()
    x2, y2 = p2.x(), p2.y()
    if x2 - x1 >= 2 * s:
        mx = (x1 + x2) / 2.0
        return [p1, QPointF(mx, y1), QPointF(mx, y2), p2]
    ax, bx = x1 + s, x2 - s
    my = (y1 + y2) / 2.0
    return [p1, QPointF(ax, y1), QPointF(ax, my), QPointF(bx, my), QPointF(bx, y2), p2]


def _rounded_polyline(points: list[QPointF], radius: float) -> QPainterPath:
    """A polyline through ``points`` with rounded corners."""
    path = QPainterPath(points[0])
    for i in range(1, len(points) - 1):
        prev, cur, nxt = points[i - 1], points[i], points[i + 1]
        v1 = QPointF(cur.x() - prev.x(), cur.y() - prev.y())
        v2 = QPointF(nxt.x() - cur.x(), nxt.y() - cur.y())
        l1 = math.hypot(v1.x(), v1.y()) or 1.0
        l2 = math.hypot(v2.x(), v2.y()) or 1.0
        d = min(radius, l1 / 2.0, l2 / 2.0)
        p_in = QPointF(cur.x() - v1.x() / l1 * d, cur.y() - v1.y() / l1 * d)
        p_out = QPointF(cur.x() + v2.x() / l2 * d, cur.y() + v2.y() / l2 * d)
        path.lineTo(p_in)
        path.quadTo(cur, p_out)
    path.lineTo(points[-1])
    return path


def _arrow_head(from_pt: QPointF, tip: QPointF, size: float) -> QPolygonF:
    ang = math.atan2(tip.y() - from_pt.y(), tip.x() - from_pt.x())
    a1 = ang + math.radians(152)
    a2 = ang - math.radians(152)
    p1 = QPointF(tip.x() + size * math.cos(a1), tip.y() + size * math.sin(a1))
    p2 = QPointF(tip.x() + size * math.cos(a2), tip.y() + size * math.sin(a2))
    return QPolygonF([tip, p1, p2])


def _label_anchor(points: list[QPointF]) -> QPointF:
    """Middle of the longest horizontal run (falls back to the longest segment)."""
    best, best_len, horiz = None, -1.0, False
    for a, b in zip(points, points[1:]):
        length = math.hypot(b.x() - a.x(), b.y() - a.y())
        is_h = abs(b.y() - a.y()) < 0.5
        if (is_h and not horiz) or ((is_h == horiz) and length > best_len):
            best, best_len, horiz = (a, b), length, is_h
    a, b = best
    return QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0)


# --------------------------------------------------------------------------- #
# Edges (streams)
# --------------------------------------------------------------------------- #
class EdgeItem(QGraphicsPathItem):
    """An orthogonal stream: coloured by kind, sized by flow, with moving dashes."""

    def __init__(self, link: M.StreamLink, scene: "FlowsheetScene"):
        super().__init__()
        self.link = link
        self._scene = scene
        self.setZValue(0)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._points: list[QPointF] = []
        self._arrow = QPolygonF()
        self._num = 0
        self._flow_text = ""
        self.flow: dict = {}
        self.kind = "empty"
        self.width = 1.8
        self._hover = False
        self.update_path()

    def set_stream(self, number: int, flow_text: str, flow: dict | None = None,
                   kind: str | None = None, width: float | None = None):
        self._num = number
        self._flow_text = flow_text
        if flow is not None:
            self.flow = flow
        if kind is not None:
            self.kind = kind
        if width is not None:
            self.width = width
        self.prepareGeometryChange()
        self.update()

    def _endpoints(self) -> tuple[QPointF, QPointF] | None:
        src = self._scene.node_items.get(self.link.src_node)
        dst = self._scene.node_items.get(self.link.dst_node)
        if not src or not dst:
            return None
        sp = src.port(self.link.src_port, False)
        dp = dst.port(self.link.dst_port, True)
        if not sp or not dp:
            return None
        return sp.scenePos(), dp.scenePos()

    def update_path(self):
        ends = self._endpoints()
        if ends is None:
            self._points = []
            self.setPath(QPainterPath())
            return
        self._points = _ortho_points(*ends)
        self.setPath(_rounded_polyline(self._points, 10.0))
        self._arrow = _arrow_head(self._points[-2], self._points[-1], 9.0 + self.width * 0.6)

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-60, -36, 60, 22)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(max(12.0, self.width + 8.0))
        return stroker.createStroke(self.path())

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        self._scene.show_stream_card(self, event.scenePos())

    def hoverMoveEvent(self, event):
        self._scene.show_stream_card(self, event.scenePos())

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()
        self._scene.hide_stream_card(self)

    def color(self) -> QColor:
        t = self._scene.theme
        return QColor(t.stream.get(self.kind, t.stream["empty"]))

    def paint(self, painter, option, widget=None):
        if not self._points:
            return
        t = self._scene.theme
        selected = self.isSelected()
        color = QColor(t.selection) if selected else self.color()
        w = self.width + (1.2 if (selected or self._hover) else 0.0)
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        path = self.path()

        # casing in the sheet colour: where two streams cross, the lower one shows a gap
        painter.setPen(QPen(QColor(t.canvas), w + 5.0, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        if self._hover or selected:
            painter.setPen(QPen(_alpha(color, 60), w + 7.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)

        style = Qt.DashLine if self.kind == "vapour" else Qt.SolidLine
        pen = QPen(color, w, style, Qt.RoundCap, Qt.RoundJoin)
        if style == Qt.DashLine:
            pen.setDashPattern([4.0 / max(w, 1.0) * 1.6, 3.0 / max(w, 1.0) * 1.6])
        painter.setPen(pen)
        painter.drawPath(path)

        # moving dashes show the direction of flow
        if self._scene.animate and self.kind not in ("empty",) and w >= 1.4:
            dw = max(1.0, w * 0.42)
            anim = QPen(_alpha(t.flow_tint, 150 if not t.dark else 110), dw, Qt.CustomDashLine,
                        Qt.RoundCap, Qt.RoundJoin)
            dash, gap = 5.0, 15.0
            anim.setDashPattern([dash / dw, gap / dw])
            anim.setDashOffset(-self._scene.phase / dw)
            painter.setPen(anim)
            painter.drawPath(path)

        if not self._arrow.isEmpty():
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color, 1.0))
            painter.drawPolygon(self._arrow)

        if not self._scene.show_labels:
            return
        mid = _label_anchor(self._points)
        # flow-rate chip, above the line
        if self._flow_text:
            f = _font(7, QFont.DemiBold)
            painter.setFont(f)
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(self._flow_text) + 10
            box = QRectF(mid.x() - tw / 2, mid.y() - 13 - w / 2 - 12, tw, 14)
            painter.setBrush(QBrush(QColor(t.chip_bg)))
            painter.setPen(QPen(QColor(t.chip_border), 1.0))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(box.left() + 5, box.center().y()), 2.0, 2.0)
            painter.setPen(QPen(QColor(t.face_ink)))
            painter.drawText(box.adjusted(5, 0, 0, 0), Qt.AlignCenter, self._flow_text)
        # stream number in a diamond, on the line (PFD convention)
        if self._num:
            r = 8.5
            diamond = QPolygonF([QPointF(mid.x(), mid.y() - r), QPointF(mid.x() + r, mid.y()),
                                 QPointF(mid.x(), mid.y() + r), QPointF(mid.x() - r, mid.y())])
            painter.setBrush(QBrush(QColor(t.face_bg)))
            painter.setPen(QPen(color, 1.4))
            painter.drawPolygon(diamond)
            painter.setFont(_font(6.5, QFont.Bold))
            painter.setPen(QPen(QColor(t.ink)))
            painter.drawText(QRectF(mid.x() - r, mid.y() - r, 2 * r, 2 * r), Qt.AlignCenter,
                             str(self._num))


# --------------------------------------------------------------------------- #
# Decorations: plant areas, utility headers, stream card, drawing sheet
# --------------------------------------------------------------------------- #
class SectionItem(QGraphicsItem):
    """Dashed frame around the blocks of one plant area, with its header tab."""

    PAD = 16.0

    def __init__(self, code: str, label: str, color: str, scene: "FlowsheetScene"):
        super().__init__()
        self.code, self.label, self.base_color = code, label, color
        self._scene = scene
        self._rect = QRectF()
        self._metric = ""
        self._intensity = 0.0
        self.setZValue(-2)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_members(self, rects: list[QRectF]):
        if not rects:
            r = QRectF()
        else:
            r = rects[0]
            for x in rects[1:]:
                r = r.united(x)
            r = r.adjusted(-self.PAD, -self.PAD - 18, self.PAD, self.PAD)
        if r != self._rect:
            self.prepareGeometryChange()
            self._rect = r
        self.setVisible(bool(rects))

    def set_metric(self, text: str, intensity: float = 0.0):
        self._metric, self._intensity = text, intensity
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-2, -2, 2, 2)

    def paint(self, painter, option, widget=None):
        if self._rect.isNull():
            return
        t = self._scene.theme
        color = QColor(category_color_for_section(self.code, t, self.base_color))
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        fill = _alpha(color, 10 + int(26 * self._intensity))
        painter.setBrush(QBrush(fill))
        pen = QPen(_alpha(color, 150), 1.1, Qt.CustomDashLine)
        pen.setDashPattern([6, 4])
        painter.setPen(pen)
        painter.drawRoundedRect(self._rect, 10, 10)
        # header tab
        f = _font(7, QFont.Bold)
        fm = QFontMetricsF(f)
        title = f"AREA {self.code}  ·  {self.label.upper()}"
        tw = fm.horizontalAdvance(title) + 16
        tab = QRectF(self._rect.left() + 12, self._rect.top() - 8, tw, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(tab, 8, 8)
        painter.setFont(f)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(tab, Qt.AlignCenter, title)
        if self._metric:
            f2 = _font(7, QFont.DemiBold)
            fm2 = QFontMetricsF(f2)
            mw = fm2.horizontalAdvance(self._metric) + 14
            y = self._rect.top() - 8
            if tab.right() + 8 > self._rect.right() - mw - 12:
                y = self._rect.bottom() - 8
            mtab = QRectF(self._rect.right() - mw - 12, y, mw, 16)
            painter.setBrush(QBrush(QColor(t.face_bg)))
            painter.setPen(QPen(color, 1.0))
            painter.drawRoundedRect(mtab, 8, 8)
            painter.setFont(f2)
            painter.setPen(QPen(color.darker(115) if not t.dark else color.lighter(120)))
            painter.drawText(mtab, Qt.AlignCenter, self._metric)


_SECTION_DARK = {"100": "#8fb0cc", "200": "#4ade80", "300": "#60a5fa", "400": "#fb923c",
                 "500": "#c084fc"}


def category_color_for_section(code: str, theme: Theme, paper_color: str) -> str:
    return _SECTION_DARK.get(code, paper_color) if theme.dark else paper_color


class UtilityItem(QGraphicsItem):
    """Electricity and heat headers above the plant, with a drop to each user."""

    def __init__(self, scene: "FlowsheetScene"):
        super().__init__()
        self._scene = scene
        self._drops: list = []     # (kind, x, y_top_of_block, label)
        self._totals = {"power": "", "heat": ""}
        self._y = {"power": 0.0, "heat": 0.0}
        self._x0 = self._x1 = 0.0
        self._rect = QRectF()
        # under the area frames, so the area tabs and totals mask the drops
        self.setZValue(-3)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_drops(self, drops, totals: dict, top: float, x0: float, x1: float):
        self.prepareGeometryChange()
        self._drops = drops
        self._totals = totals
        self._y = {"power": top - 74.0, "heat": top - 50.0}
        self._x0, self._x1 = x0 - 40.0, x1 + 40.0
        ys = [y for _k, _x, y, _l in drops] or [top]
        self._rect = QRectF(self._x0 - 10, top - 100, self._x1 - self._x0 + 20,
                            max(ys) - (top - 100) + 30)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None):
        if not self._drops:
            return
        t = self._scene.theme
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        f = _font(7, QFont.Bold)
        f_small = _font(6.5, QFont.DemiBold)
        for kind in ("power", "heat"):
            if not any(k == kind for k, *_ in self._drops):
                continue
            color = QColor(t.elec if kind == "power" else t.heat)
            y = self._y[kind]
            header = QPen(color, 2.4, Qt.SolidLine, Qt.FlatCap)
            painter.setPen(header)
            painter.drawLine(QPointF(self._x0, y), QPointF(self._x1, y))
            # header label at the left end
            label = ("ELECTRICITY" if kind == "power" else "HEAT / STEAM") + f"  Σ {self._totals[kind]}"
            fm = QFontMetricsF(f)
            lw = fm.horizontalAdvance(label) + 30
            box = QRectF(self._x0 - lw - 6, y - 9, lw, 18)
            painter.setBrush(QBrush(QColor(t.face_bg)))
            painter.setPen(QPen(color, 1.2))
            painter.drawRoundedRect(box, 9, 9)
            draw_glyph(painter, kind, QPointF(box.left() + 12, y), 11.0, color)
            painter.setFont(f)
            painter.setPen(QPen(QColor(t.ink)))
            painter.drawText(box.adjusted(22, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        for kind, x, y_block, text in self._drops:
            color = QColor(t.elec if kind == "power" else t.heat)
            y0 = self._y[kind]
            pen = QPen(color, 1.4, Qt.CustomDashLine, Qt.FlatCap)
            pen.setDashPattern([3, 2.5])
            painter.setPen(pen)
            painter.drawLine(QPointF(x, y0), QPointF(x, y_block))
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(x, y0), 2.6, 2.6)
            painter.drawPolygon(QPolygonF([QPointF(x - 3.5, y_block - 6), QPointF(x + 3.5, y_block - 6),
                                           QPointF(x, y_block)]))
            painter.setFont(f_small)
            fm = QFontMetricsF(f_small)
            tw = fm.horizontalAdvance(text) + 8
            lbl = QRectF(x + 4, (y0 + y_block) / 2.0 - 7 + (8 if kind == "heat" else -8), tw, 13)
            painter.setBrush(QBrush(QColor(t.face_bg)))
            painter.setPen(QPen(_alpha(color, 160), 0.8))
            painter.drawRoundedRect(lbl, 3, 3)
            painter.setPen(QPen(QColor(t.face_ink)))
            painter.drawText(lbl, Qt.AlignCenter, text)


class StreamCard(QGraphicsItem):
    """Floating card describing the stream under the cursor."""

    W = 236.0

    def __init__(self, scene: "FlowsheetScene"):
        super().__init__()
        self._scene = scene
        self._edge: EdgeItem | None = None
        self._lines: list = []
        self._h = 100.0
        self.setZValue(60)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setVisible(False)

    def show_for(self, edge: EdgeItem, pos: QPointF, title: str, rows: list):
        self._edge = edge
        self._title = title
        self._rows = rows
        self._h = 46.0 + 15.0 * len(rows) + 30.0
        self.prepareGeometryChange()
        self.setPos(pos + QPointF(16, 14))
        self.setVisible(True)
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -6, self.W + 12, self._h + 12)

    def paint(self, painter, option, widget=None):
        if self._edge is None:
            return
        t = self._scene.theme
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.W, self._h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_alpha("#000000", 34 if not t.dark else 90)))
        painter.drawRoundedRect(rect.translated(0, 3), 8, 8)
        painter.setBrush(QBrush(QColor(t.face_bg)))
        painter.setPen(QPen(QColor(t.face_border), 1.0))
        painter.drawRoundedRect(rect, 8, 8)
        color = self._edge.color()
        painter.fillRect(QRectF(0, 8, 3, self._h - 16), color)
        painter.setFont(_font(8.5, QFont.Bold))
        painter.setPen(QPen(QColor(t.ink)))
        painter.drawText(QRectF(12, 6, self.W - 20, 18), Qt.AlignVCenter | Qt.AlignLeft, self._title)
        painter.setFont(_font(7, QFont.DemiBold))
        painter.setPen(QPen(color))
        painter.drawText(QRectF(12, 22, self.W - 20, 14), Qt.AlignVCenter | Qt.AlignLeft,
                         STREAM_LABELS.get(self._edge.kind, "Stream").upper())
        y = 40.0
        f = _font(7.5)
        fb = _font(7.5, QFont.DemiBold)
        for k, v in self._rows:
            painter.setFont(f)
            painter.setPen(QPen(QColor(t.ink_dim)))
            painter.drawText(QRectF(12, y, 110, 14), Qt.AlignVCenter | Qt.AlignLeft, k)
            painter.setFont(fb)
            painter.setPen(QPen(QColor(t.face_ink)))
            painter.drawText(QRectF(110, y, self.W - 122, 14), Qt.AlignVCenter | Qt.AlignRight, v)
            y += 15.0
        # composition bar
        flow = self._edge.flow
        total = sum(flow.values()) or 1.0
        bar = QRectF(12, y + 8, self.W - 24, 9)
        x = bar.left()
        comp_colors = {"biomass": "#2e7d32", "water": "#2b7bd6", "solvent": "#7c3aed",
                       "product": "#d97706", "substrate": "#a0522d", "co2": "#4f86a6",
                       "other": "#e8590c"}
        painter.setPen(Qt.NoPen)
        for comp, val in flow.items():
            if val <= 0:
                continue
            w = bar.width() * val / total
            painter.setBrush(QBrush(QColor(comp_colors.get(comp, "#94a3b8"))))
            painter.drawRect(QRectF(x, bar.top(), max(w, 0.8), bar.height()))
            x += w
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(t.face_border), 0.8))
        painter.drawRoundedRect(bar, 2, 2)


class SheetItem(QGraphicsItem):
    """Drawing sheet: border with zone marks, a legend and a title block."""

    MARGIN = 70.0
    STRIP = 128.0      # height of the legend / title-block strip under the drawing

    def __init__(self, scene: "FlowsheetScene"):
        super().__init__()
        self._scene = scene
        self._content = QRectF()
        self._rect = QRectF()
        self.info: dict = {}
        self.kinds: list[str] = []
        self.layer_scale: tuple | None = None   # (label, lo_text, hi_text, color)
        self.setZValue(-10)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_content(self, rect: QRectF):
        m = self.MARGIN
        r = rect.adjusted(-m, -m, m, m + self.STRIP)
        min_w = 1180.0
        if r.width() < min_w:
            r.adjust(-(min_w - r.width()) / 2, 0, (min_w - r.width()) / 2, 0)
        if r != self._rect:
            self.prepareGeometryChange()
            self._rect = r
            self._content = rect

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-30, -30, 30, 30)

    def paint(self, painter, option, widget=None):
        if self._rect.isNull():
            return
        t = self._scene.theme
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        r = self._rect
        ink = QColor(t.frame)
        # double border
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(ink, 2.0))
        painter.drawRect(r)
        inner = r.adjusted(14, 14, -14, -14)
        painter.setPen(QPen(ink, 0.8))
        painter.drawRect(inner)
        # zone marks: numbers across, letters down
        f = _font(6.5, QFont.DemiBold)
        painter.setFont(f)
        cols = max(4, int(r.width() // 260))
        rows = max(3, int(r.height() // 220))
        for i in range(cols + 1):
            x = r.left() + r.width() * i / cols
            if 0 < i < cols:
                painter.drawLine(QPointF(x, r.top()), QPointF(x, inner.top()))
                painter.drawLine(QPointF(x, r.bottom()), QPointF(x, inner.bottom()))
            if i < cols:
                cx = r.left() + r.width() * (i + 0.5) / cols
                for y in (r.top(), inner.bottom()):
                    painter.drawText(QRectF(cx - 10, y, 20, 14), Qt.AlignCenter, str(i + 1))
        for j in range(rows + 1):
            y = r.top() + r.height() * j / rows
            if 0 < j < rows:
                painter.drawLine(QPointF(r.left(), y), QPointF(inner.left(), y))
                painter.drawLine(QPointF(r.right(), y), QPointF(inner.right(), y))
            if j < rows:
                cy = r.top() + r.height() * (j + 0.5) / rows
                letter = chr(ord("A") + j)
                for x in (r.left(), inner.right()):
                    painter.drawText(QRectF(x, cy - 7, 14, 14), Qt.AlignCenter, letter)
        self._paint_title_block(painter, inner, ink)
        self._paint_legend(painter, inner, ink)

    def _paint_title_block(self, painter, inner: QRectF, ink: QColor):
        t = self._scene.theme
        info = self.info
        w, h = 470.0, 96.0
        box = QRectF(inner.right() - w, inner.bottom() - h, w, h)
        painter.setBrush(QBrush(QColor(t.face_bg)))
        painter.setPen(QPen(ink, 1.4))
        painter.drawRect(box)
        split = box.left() + 120
        row1 = box.top() + 56
        painter.setPen(QPen(ink, 0.8))
        painter.drawLine(QPointF(split, box.top()), QPointF(split, row1))
        painter.drawLine(QPointF(box.left(), row1), QPointF(box.right(), row1))
        cells = [("DRAWING", info.get("drawing", "PFD-001")), ("REV", info.get("rev", "A")),
                 ("DATE", info.get("date", date.today().isoformat())),
                 ("BASIS", info.get("basis", "kg/h, steady state"))]
        widths = [110.0, 50.0, 100.0, w - 260.0]
        x = box.left()
        for (k, v), cw in zip(cells, widths):
            if x > box.left():
                painter.drawLine(QPointF(x, row1), QPointF(x, box.bottom()))
            painter.setFont(_font(5.5, QFont.Bold))
            painter.setPen(QPen(QColor(t.ink_faint)))
            painter.drawText(QRectF(x + 6, row1 + 3, cw - 8, 10), Qt.AlignLeft | Qt.AlignVCenter, k)
            painter.setFont(_font(7.5, QFont.DemiBold))
            painter.setPen(QPen(QColor(t.ink)))
            painter.drawText(QRectF(x + 6, row1 + 14, cw - 10, 22), Qt.AlignLeft | Qt.AlignVCenter,
                             QFontMetricsF(_font(7.5, QFont.DemiBold)).elidedText(v, Qt.ElideRight, cw - 12))
            painter.setPen(QPen(ink, 0.8))
            x += cw
        # left cell: logo or product name
        logo = self._scene.logo
        cell = QRectF(box.left() + 8, box.top() + 8, 104, row1 - box.top() - 16)
        if logo is not None and not logo.isNull():
            s = min(cell.width() / logo.width(), cell.height() / logo.height())
            lw, lh = logo.width() * s, logo.height() * s
            painter.drawPixmap(QRectF(cell.center().x() - lw / 2, cell.center().y() - lh / 2, lw, lh),
                               logo, QRectF(logo.rect()))
        else:
            painter.setFont(_font(10, QFont.Bold))
            painter.setPen(QPen(QColor(t.ink)))
            painter.drawText(cell, Qt.AlignCenter, "AlgaMetrix")
        painter.setFont(_font(10.5, QFont.Bold))
        painter.setPen(QPen(QColor(t.ink)))
        painter.drawText(QRectF(split + 10, box.top() + 6, box.right() - split - 16, 20),
                         Qt.AlignLeft | Qt.AlignVCenter, "PROCESS FLOW DIAGRAM")
        painter.setFont(_font(7.5))
        painter.setPen(QPen(QColor(t.ink_dim)))
        title = info.get("title", "")
        sub = info.get("subtitle", "")
        fm = QFontMetricsF(_font(7.5))
        painter.drawText(QRectF(split + 10, box.top() + 25, box.right() - split - 16, 13),
                         Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(title, Qt.ElideRight, w - 140))
        painter.drawText(QRectF(split + 10, box.top() + 38, box.right() - split - 16, 13),
                         Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(sub, Qt.ElideRight, w - 140))

    def _paint_legend(self, painter, inner: QRectF, ink: QColor):
        t = self._scene.theme
        kinds = [k for k in STREAM_LABELS if k in self.kinds]
        if not kinds:
            return
        per_col = 4
        ncols = (len(kinds) + per_col - 1) // per_col
        col_w = 150.0
        scale_w = 190.0 if self.layer_scale else 0.0
        w = 16 + ncols * col_w + scale_w
        h = 96.0
        box = QRectF(inner.left(), inner.bottom() - h, w, h)
        painter.setBrush(QBrush(QColor(t.face_bg)))
        painter.setPen(QPen(ink, 1.2))
        painter.drawRect(box)
        painter.setFont(_font(6, QFont.Bold))
        painter.setPen(QPen(QColor(t.ink_faint)))
        painter.drawText(QRectF(box.left() + 8, box.top() + 4, 200, 12), Qt.AlignLeft | Qt.AlignVCenter,
                         "STREAMS  ·  line width ∝ log(mass flow)")
        f = _font(7)
        for i, k in enumerate(kinds):
            c, rrow = divmod(i, per_col)
            x = box.left() + 10 + c * col_w
            y = box.top() + 24 + rrow * 17
            color = QColor(t.stream[k])
            pen = QPen(color, 3.0, Qt.DashLine if k == "vapour" else Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, y + 6), QPointF(x + 26, y + 6))
            painter.setFont(f)
            painter.setPen(QPen(QColor(t.face_ink)))
            painter.drawText(QRectF(x + 33, y, col_w - 36, 13), Qt.AlignLeft | Qt.AlignVCenter,
                             STREAM_LABELS[k])
        if self.layer_scale:
            label, lo, hi, color = self.layer_scale
            x0 = box.left() + 16 + ncols * col_w
            painter.setPen(QPen(ink, 0.6))
            painter.drawLine(QPointF(x0 - 8, box.top() + 8), QPointF(x0 - 8, box.bottom() - 8))
            painter.setFont(_font(6, QFont.Bold))
            painter.setPen(QPen(QColor(t.ink_faint)))
            painter.drawText(QRectF(x0, box.top() + 4, scale_w - 10, 12), Qt.AlignLeft | Qt.AlignVCenter,
                             f"HALO  ·  {label.upper()}")
            bar = QRectF(x0, box.top() + 30, scale_w - 22, 10)
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            g.setColorAt(0.0, _alpha(color, 25))
            g.setColorAt(1.0, _alpha(color, 220))
            painter.setBrush(QBrush(g))
            painter.setPen(QPen(_alpha(color, 160), 0.8))
            painter.drawRoundedRect(bar, 3, 3)
            painter.setFont(_font(6.5))
            painter.setPen(QPen(QColor(t.face_ink)))
            painter.drawText(QRectF(bar.left(), bar.bottom() + 3, 80, 12), Qt.AlignLeft, lo)
            painter.drawText(QRectF(bar.right() - 80, bar.bottom() + 3, 80, 12), Qt.AlignRight, hi)
            draw_glyph(painter, "power", QPointF(x0 + 6, box.top() + 68), 10.0, QColor(t.elec))
            draw_glyph(painter, "heat", QPointF(x0 + 6, box.top() + 84), 10.0, QColor(t.heat))
            painter.drawText(QRectF(x0 + 16, box.top() + 61, 160, 13), Qt.AlignLeft | Qt.AlignVCenter,
                             "electric load")
            painter.drawText(QRectF(x0 + 16, box.top() + 77, 160, 13), Qt.AlignLeft | Qt.AlignVCenter,
                             "heat duty")


# --------------------------------------------------------------------------- #
# Scene
# --------------------------------------------------------------------------- #
class FlowsheetScene(QGraphicsScene):
    graphChanged = Signal()
    nodeSelected = Signal(object)   # node_id: str | None
    edgeSelected = Signal(object)   # link_id: str | None
    message = Signal(str)
    decorChanged = Signal()         # frames, headers or sheet moved or changed

    def __init__(self, flowsheet: M.Flowsheet | None = None, parent=None):
        super().__init__(parent)
        self.setSceneRect(-6000, -4000, 14000, 9000)
        self.theme: Theme = PAPER
        self.setBackgroundBrush(QBrush(QColor(self.theme.canvas)))
        self.flowsheet = flowsheet or M.Flowsheet()
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: dict[str, EdgeItem] = {}
        self.wired: set[tuple[str, str, bool]] = set()   # (node id, port, is_input)
        self.section_items: list[SectionItem] = []
        self.sections: list = []        # [(code, label, roles, color)] set by the editor
        self.logo = None

        self.animate = True
        self.show_labels = True
        self.show_sheet = True
        self.show_sections = True
        self.show_utilities = False
        self.phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self._utility_data = ([], {"power": "", "heat": ""})
        self._decor_timer = QTimer(self)
        self._decor_timer.setSingleShot(True)
        self._decor_timer.setInterval(30)
        self._decor_timer.timeout.connect(self.refresh_decor)

        self._pending_from: PortItem | None = None
        self._temp_edge: QGraphicsPathItem | None = None
        self.stream_info = None         # callable(edge) -> (title, rows), set by the editor

        self.selectionChanged.connect(self._on_selection)
        self.rebuild()

    # -- theme / modes --------------------------------------------------- #
    def set_theme(self, theme: Theme):
        self.theme = theme
        self.setBackgroundBrush(QBrush(QColor(theme.canvas)))
        for item in self.node_items.values():
            item.set_theme(theme)
        self.update()

    def set_animation(self, on: bool):
        self.animate = on
        if on and self.edge_items:
            self._timer.start()
        else:
            self._timer.stop()
        for e in self.edge_items.values():
            e.update()

    def pause_animation(self, paused: bool):
        """Stop the clock while the canvas is hidden; keep the setting."""
        if paused:
            self._timer.stop()
        elif self.animate and self.edge_items:
            self._timer.start()

    def _tick(self):
        self.phase = (self.phase + 1.4) % 4000.0
        for e in self.edge_items.values():
            if e.width >= 1.4:
                e.update()

    # -- (re)build from model ------------------------------------------- #
    def set_flowsheet(self, fs: M.Flowsheet):
        self.flowsheet = fs
        self.rebuild()
        self.graphChanged.emit()

    def rebuild(self):
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.wired = set()
        self.section_items = []
        self.sheet = SheetItem(self)
        self.addItem(self.sheet)
        self.utilities = UtilityItem(self)
        self.addItem(self.utilities)
        self.card = StreamCard(self)
        self.addItem(self.card)
        for code, label, _roles, color in self.sections:
            sec = SectionItem(code, label, color, self)
            self.addItem(sec)
            self.section_items.append(sec)
        for node in self.flowsheet.nodes.values():
            self._add_node_item(node)
        for link in self.flowsheet.links.values():
            self._add_edge_item(link)
        self.refresh_decor()

    def set_sections(self, sections):
        """``[(code, label, roles, color)]``: the plant areas to frame."""
        self.sections = list(sections)
        for sec in self.section_items:
            self.removeItem(sec)
        self.section_items = []
        for code, label, _roles, color in self.sections:
            sec = SectionItem(code, label, color, self)
            self.addItem(sec)
            self.section_items.append(sec)
        self.refresh_decor()

    def _add_node_item(self, node: M.UnitNode) -> NodeItem:
        item = NodeItem(node, self.theme)
        self.addItem(item)
        self.node_items[node.id] = item
        return item

    def _add_edge_item(self, link: M.StreamLink) -> EdgeItem:
        edge = EdgeItem(link, self)
        self.addItem(edge)
        self.edge_items[link.id] = edge
        self.wired.add((link.src_node, link.src_port, False))
        self.wired.add((link.dst_node, link.dst_port, True))
        if self.animate and not self._timer.isActive():
            self._timer.start()
        return edge

    def _sync_edges(self):
        """Reconcile edge items with the model (after add/remove)."""
        for lid in list(self.edge_items):
            if lid not in self.flowsheet.links:
                self.removeItem(self.edge_items.pop(lid))
        for lid, link in self.flowsheet.links.items():
            if lid not in self.edge_items:
                self._add_edge_item(link)
            else:
                self.edge_items[lid].update_path()
        self.wired = {(lk.src_node, lk.src_port, False) for lk in self.flowsheet.links.values()}
        self.wired |= {(lk.dst_node, lk.dst_port, True) for lk in self.flowsheet.links.values()}
        for item in self.node_items.values():
            item.update()

    # -- decorations ----------------------------------------------------- #
    def schedule_decor(self):
        self._decor_timer.start()

    def flush_decor(self):
        """Apply a pending decoration refresh now (before the sheet is measured)."""
        if self._decor_timer.isActive():
            self._decor_timer.stop()
            self.refresh_decor()

    def content_rect(self) -> QRectF:
        rect = QRectF()
        for item in self.node_items.values():
            r = item.core_rect().adjusted(-STUB - 4, -4, STUB + 4, 4)
            rect = r if rect.isNull() else rect.united(r)
        for sec in self.section_items:
            if sec.isVisible() and not sec.boundingRect().isNull():
                rect = rect.united(sec.boundingRect())
        if self.show_utilities and self.utilities._drops:
            rect = rect.united(self.utilities.boundingRect().adjusted(-230, 0, 0, 0))
        return rect

    def refresh_decor(self):
        by_role: dict[str, list[NodeItem]] = {}
        for item in self.node_items.values():
            base = item.node.role.split(":")[0] if item.node.role else ""
            if base:
                by_role.setdefault(base, []).append(item)
        for sec, (_code, _label, roles, _color) in zip(self.section_items, self.sections):
            rects = [it.core_rect() for r in roles for it in by_role.get(r, [])]
            sec.set_members(rects)
            sec.setVisible(self.show_sections and bool(rects))
        self._place_utilities()
        content = self.content_rect()
        self.sheet.set_content(content if not content.isNull() else QRectF(-300, -200, 600, 400))
        self.sheet.setVisible(self.show_sheet and bool(self.node_items))
        self.update()
        self.decorChanged.emit()

    def set_utility_loads(self, loads: dict, totals: dict):
        """``loads``: node_id -> {"power": text, "heat": text}; totals: kind -> text."""
        self._utility_data = (loads, totals)
        self._place_utilities()

    def _place_utilities(self):
        loads, totals = self._utility_data
        drops = []
        xs = []
        if self.show_utilities and loads:
            top = min((it.pos().y() for it in self.node_items.values()), default=0.0)
            for nid, kinds in loads.items():
                item = self.node_items.get(nid)
                if item is None:
                    continue
                cx = item.pos().x() + NODE_W / 2.0
                y_block = item.pos().y() - 3.0       # stop above the tag line
                if "power" in kinds:
                    drops.append(("power", cx + SYM / 2.0 + 10.0, y_block, kinds["power"]))
                    xs.append(cx)
                if "heat" in kinds:
                    drops.append(("heat", cx + SYM / 2.0 + 22.0, y_block, kinds["heat"]))
                    xs.append(cx)
            if drops:
                x0 = min(it.pos().x() for it in self.node_items.values())
                x1 = max(it.pos().x() + NODE_W for it in self.node_items.values())
                self.utilities.set_drops(drops, totals, top - 30.0, x0, x1)
        if not drops:
            self.utilities.set_drops([], totals, 0.0, 0.0, 0.0)
        self.utilities.setVisible(bool(drops))

    def set_section_metrics(self, metrics: dict):
        """``metrics``: area code -> (text, intensity 0..1)."""
        for sec in self.section_items:
            text, k = metrics.get(sec.code, ("", 0.0))
            sec.set_metric(text, k)

    def set_sheet_info(self, info: dict, kinds: list[str], layer_scale=None):
        self.sheet.info = info
        self.sheet.kinds = kinds
        self.sheet.layer_scale = layer_scale
        self.sheet.update()

    def set_show_sheet(self, on: bool):
        self.show_sheet = on
        self.refresh_decor()

    def set_show_sections(self, on: bool):
        self.show_sections = on
        self.refresh_decor()

    def set_show_utilities(self, on: bool):
        self.show_utilities = on
        self.refresh_decor()

    def set_show_labels(self, on: bool):
        self.show_labels = on
        for e in self.edge_items.values():
            e.update()

    # -- stream card ----------------------------------------------------- #
    def show_stream_card(self, edge: EdgeItem, pos: QPointF):
        if self.stream_info is None:
            return
        title, rows = self.stream_info(edge)
        self.card.show_for(edge, pos, title, rows)

    def hide_stream_card(self, edge: EdgeItem):
        if self.card._edge is edge:
            self.card.setVisible(False)

    # -- public helpers used by the editor ------------------------------ #
    def add_node(self, kind: str, scene_pos: QPointF) -> NodeItem:
        x = round(scene_pos.x() / SNAP) * SNAP
        y = round(scene_pos.y() / SNAP) * SNAP
        node = self.flowsheet.add_node(kind, x, y)
        item = self._add_node_item(node)
        self.clearSelection()
        item.setSelected(True)
        self.refresh_decor()
        self.graphChanged.emit()
        return item

    def update_edges_for(self, node_id: str):
        for edge in self.edge_items.values():
            if edge.link.src_node == node_id or edge.link.dst_node == node_id:
                edge.update_path()

    def delete_selected(self):
        removed = False
        kept = []
        for item in list(self.selectedItems()):
            if isinstance(item, NodeItem):
                if item.node.role:
                    kept.append(item.node.tag)
                    continue
                self.flowsheet.remove_node(item.node.id)
                removed = True
            elif isinstance(item, EdgeItem):
                src = self.flowsheet.nodes.get(item.link.src_node)
                dst = self.flowsheet.nodes.get(item.link.dst_node)
                if src is not None and dst is not None and src.role and dst.role:
                    kept.append(f"stream {item._num}")
                    continue
                self.flowsheet.remove_link(item.link.id)
                removed = True
        if kept:
            self.message.emit(
                f"{', '.join(kept)} belong{'s' if len(kept) == 1 else ''} to the case study and "
                f"stay{'s' if len(kept) == 1 else ''}: change the technology in the inspector, "
                f"or switch a step off on the Scenario tab.")
        if removed:
            for nid in list(self.node_items):
                if nid not in self.flowsheet.nodes:
                    self.removeItem(self.node_items.pop(nid))
            self._sync_edges()
            self.refresh_decor()
            self.graphChanged.emit()

    def select_node(self, node_id: str | None):
        self.clearSelection()
        item = self.node_items.get(node_id) if node_id else None
        if item is not None:
            item.setSelected(True)

    # -- connection interaction ----------------------------------------- #
    def _port_at(self, scene_pos: QPointF) -> PortItem | None:
        for item in self.items(scene_pos):
            if isinstance(item, PortItem):
                return item
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            port = self._port_at(event.scenePos())
            if port is not None and not port.is_input:
                self._pending_from = port
                self._temp_edge = QGraphicsPathItem()
                self._temp_edge.setZValue(5)
                self._temp_edge.setPen(QPen(QColor(self.theme.selection), 1.8, Qt.DashLine))
                self.addItem(self._temp_edge)
                self._drag_temp(event.scenePos())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pending_from is not None:
            self._drag_temp(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pending_from is not None:
            target = self._port_at(event.scenePos())
            src = self._pending_from
            self._pending_from = None
            if self._temp_edge is not None:
                self.removeItem(self._temp_edge)
                self._temp_edge = None
            if target is not None and target.is_input and target.node_item is not src.node_item:
                link = self.flowsheet.add_link(
                    src.node_item.node.id, src.port_name,
                    target.node_item.node.id, target.port_name,
                )
                if link is not None:
                    self._sync_edges()
                    self.graphChanged.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _drag_temp(self, scene_pos: QPointF):
        if self._temp_edge is None or self._pending_from is None:
            return
        pts = _ortho_points(self._pending_from.scenePos(), scene_pos)
        self._temp_edge.setPath(_rounded_polyline(pts, 9.0))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- selection ------------------------------------------------------- #
    def _on_selection(self):
        items = self.selectedItems()
        nodes = [it for it in items if isinstance(it, NodeItem)]
        edges = [it for it in items if isinstance(it, EdgeItem)]
        self.nodeSelected.emit(nodes[0].node.id if len(nodes) == 1 else None)
        self.edgeSelected.emit(edges[0].link.id if len(edges) == 1 and not nodes else None)

    def select_edge(self, link_id: str | None):
        self.clearSelection()
        edge = self.edge_items.get(link_id) if link_id else None
        if edge is not None:
            edge.setSelected(True)

    def node_item(self, node_id: str) -> NodeItem | None:
        return self.node_items.get(node_id)

    # -- export ---------------------------------------------------------- #
    def export_rect(self) -> QRectF:
        if self.show_sheet and self.sheet.isVisible():
            return self.sheet._rect.adjusted(-8, -8, 8, 8)
        return self.content_rect().adjusted(-40, -40, 40, 40)


__all__ = ["FlowsheetScene", "NodeItem", "EdgeItem", "PortItem", "CANVAS_BG", "LAYER_LABELS",
           "draw_glyph"]
