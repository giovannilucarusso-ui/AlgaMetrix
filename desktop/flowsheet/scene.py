"""Interactive canvas: nodes, ports, streams — engineering (PFD) styling.

``FlowsheetScene`` renders a :class:`~desktop.flowsheet.model.Flowsheet` as
draggable :class:`NodeItem` equipment blocks whose :class:`PortItem` nozzles can
be wired together into :class:`EdgeItem` streams. Blocks are drawn as flat,
technical cards (equipment tag + name + schematic symbol + a mass-balance
read-out); streams are orthogonal (right-angle) connectors with an arrowhead and
a numbered stream tag, in the style of a process flow diagram.

The scene owns the interaction logic (drag-to-connect, delete, snap-to-grid) and
keeps the model in sync, emitting :attr:`graphChanged` on topology edits and
:attr:`nodeSelected` on selection changes.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
)

from . import icons, model as M

# --- geometry (uniform technical blocks) ------------------------------------ #
GRID = 20
SNAP = 10
NODE_W = 182.0
NODE_H = 122.0
ACCENT_H = 4.0
LABEL_Y0 = 8.0
LABEL_H = 15.0
SYM_Y0 = 26.0
SYM_H = 60.0
DIV_Y = 94.0
READ_Y0 = 97.0
READ_H = 18.0
STUB = 12.0
PORT = 4.5           # half-side of the square nozzle handle

# --- professional palette --------------------------------------------------- #
COL_BG = "#ffffff"
COL_BORDER = "#9aa7b2"
COL_BORDER_SEL = "#15803d"
COL_TAG = "#0f172a"
COL_NAME = "#64748b"
COL_DIVIDER = "#e5eaef"
COL_PORTLBL = "#8a97a1"
COL_READOUT = "#33414d"
COL_STREAM = "#5f6f7c"
COL_STREAM_SEL = "#15803d"
CANVAS_BG = "#fbfcfd"


def _port_band() -> tuple[float, float]:
    return SYM_Y0 + 6.0, SYM_Y0 + SYM_H - 6.0


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
        s = PORT + (1.5 if self._hover else 0.0)
        rect = QRectF(-s, -s, 2 * s, 2 * s)
        if self.is_input:
            painter.setBrush(QBrush(QColor("#ffffff")))
        else:
            painter.setBrush(QBrush(color))
        painter.setPen(QPen(color, 1.6))
        painter.drawRect(rect)


# --------------------------------------------------------------------------- #
# Nodes (equipment blocks)
# --------------------------------------------------------------------------- #
class NodeItem(QGraphicsObject):
    """A draggable equipment block bound to a :class:`model.UnitNode`."""

    def __init__(self, node: M.UnitNode):
        super().__init__()
        self.node = node
        self.sp = node.spec
        self.accent = M.CATEGORY_COLORS.get(self.sp.category, "#455a64")
        self._readout = ""

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        self.setPos(node.x, node.y)

        self.ports: dict[tuple[bool, str], PortItem] = {}
        self._make_ports()

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

    # -- painting -------------------------------------------------------- #
    def boundingRect(self) -> QRectF:
        return QRectF(-STUB - 6, -3, NODE_W + 2 * STUB + 12, NODE_H + 6)

    def set_readout(self, text: str):
        if text != self._readout:
            self._readout = text
            self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        accent = QColor(self.accent)
        selected = self.isSelected()

        body = QRectF(0, 0, NODE_W, NODE_H)
        body_path = QPainterPath()
        body_path.addRoundedRect(body, 6, 6)

        # card
        painter.setBrush(QBrush(QColor(COL_BG)))
        painter.setPen(QPen(QColor(COL_BORDER_SEL) if selected else QColor(COL_BORDER),
                            2.0 if selected else 1.1))
        painter.drawPath(body_path)

        # top accent bar (category colour), clipped to the rounded card
        painter.save()
        painter.setClipPath(body_path)
        painter.fillRect(QRectF(0, 0, NODE_W, ACCENT_H), accent)
        painter.restore()

        # label row: TAG (bold) + name (regular, subtle), elided
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        fm = painter.fontMetrics()
        tag = self.node.tag or ""
        tag_w = fm.horizontalAdvance(tag)
        painter.setPen(QPen(QColor(COL_TAG)))
        painter.drawText(QRectF(9, LABEL_Y0, tag_w + 2, LABEL_H),
                         Qt.AlignVCenter | Qt.AlignLeft, tag)
        painter.setFont(QFont("Segoe UI", 8))
        fm2 = painter.fontMetrics()
        name_x = 9 + tag_w + 6
        name_w = NODE_W - name_x - 8
        painter.setPen(QPen(QColor(COL_NAME)))
        painter.drawText(QRectF(name_x, LABEL_Y0, name_w, LABEL_H),
                         Qt.AlignVCenter | Qt.AlignLeft,
                         fm2.elidedText(self.node.name, Qt.ElideRight, int(name_w)))

        # schematic symbol
        sym = QRectF((NODE_W - SYM_H) / 2.0, SYM_Y0, SYM_H, SYM_H)
        icons.paint_icon(painter, self.sp.icon, sym, accent)

        # nozzle stubs + port labels
        painter.setFont(QFont("Segoe UI", 6, QFont.DemiBold))
        pen_stub = QPen(QColor(COL_BORDER), 1.4)
        lbl_w = NODE_W * 0.34
        for (is_input, name), p in self.ports.items():
            y = p.pos().y()
            painter.setPen(pen_stub)
            if is_input:
                painter.drawLine(QPointF(0, y), QPointF(-STUB, y))
            else:
                painter.drawLine(QPointF(NODE_W, y), QPointF(NODE_W + STUB, y))
            painter.setPen(QPen(QColor(COL_PORTLBL)))
            if is_input:
                painter.drawText(QRectF(4, y - 8, lbl_w, 16),
                                 Qt.AlignVCenter | Qt.AlignLeft, name)
            else:
                painter.drawText(QRectF(NODE_W - 4 - lbl_w, y - 8, lbl_w, 16),
                                 Qt.AlignVCenter | Qt.AlignRight, name)

        # divider + read-out
        painter.setPen(QPen(QColor(COL_DIVIDER), 1.0))
        painter.drawLine(QPointF(8, DIV_Y), QPointF(NODE_W - 8, DIV_Y))
        if self._readout:
            painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
            painter.setPen(QPen(QColor(COL_READOUT)))
            painter.drawText(QRectF(9, READ_Y0, NODE_W - 18, READ_H),
                             Qt.AlignVCenter | Qt.AlignHCenter, self._readout)

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
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    p1 = QPointF(tip.x() + size * math.cos(a1), tip.y() + size * math.sin(a1))
    p2 = QPointF(tip.x() + size * math.cos(a2), tip.y() + size * math.sin(a2))
    return QPolygonF([tip, p1, p2])


# --------------------------------------------------------------------------- #
# Edges (streams)
# --------------------------------------------------------------------------- #
class EdgeItem(QGraphicsPathItem):
    """An orthogonal stream connector with an arrowhead and a numbered tag."""

    def __init__(self, link: M.StreamLink, scene: "FlowsheetScene"):
        super().__init__()
        self.link = link
        self._scene = scene
        self.setZValue(0)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self._points: list[QPointF] = []
        self._arrow = QPolygonF()
        self._num = 0
        self._flow = ""
        self.update_path()

    def set_stream(self, number: int, flow: str):
        self._num = number
        self._flow = flow
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
        self.setPath(_rounded_polyline(self._points, 9.0))
        self._arrow = _arrow_head(self._points[-2], self._points[-1], 9.0)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        selected = self.isSelected()
        color = QColor(COL_STREAM_SEL if selected else COL_STREAM)
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(color, 2.6 if selected else 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())
        if not self._arrow.isEmpty():
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color, 1.0))
            painter.drawPolygon(self._arrow)

        if not self._points:
            return
        mid = self.path().pointAtPercent(0.5)
        # flow rate chip, above the line
        if self._flow:
            painter.setFont(QFont("Segoe UI", 7, QFont.DemiBold))
            fm = painter.fontMetrics()
            w = fm.horizontalAdvance(self._flow) + 8
            box = QRectF(mid.x() - w / 2, mid.y() - 22, w, 14)
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(QPen(QColor("#d5dde3"), 1.0))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QPen(QColor(COL_READOUT)))
            painter.drawText(box, Qt.AlignCenter, self._flow)
        # stream-number tag on the line (PFD convention)
        if self._num:
            r = 8.0
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(QPen(color, 1.4))
            painter.drawEllipse(mid, r, r)
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.setPen(QPen(color))
            painter.drawText(QRectF(mid.x() - r, mid.y() - r, 2 * r, 2 * r),
                             Qt.AlignCenter, str(self._num))


# --------------------------------------------------------------------------- #
# Scene
# --------------------------------------------------------------------------- #
class FlowsheetScene(QGraphicsScene):
    graphChanged = Signal()
    nodeSelected = Signal(object)   # node_id: str | None

    def __init__(self, flowsheet: M.Flowsheet | None = None, parent=None):
        super().__init__(parent)
        self.setSceneRect(-4000, -3000, 8000, 6000)
        self.setBackgroundBrush(QBrush(QColor(CANVAS_BG)))
        self.flowsheet = flowsheet or M.Flowsheet()
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: dict[str, EdgeItem] = {}

        self._pending_from: PortItem | None = None
        self._temp_edge: QGraphicsPathItem | None = None

        self.selectionChanged.connect(self._on_selection)
        self.rebuild()

    # -- (re)build from model ------------------------------------------- #
    def set_flowsheet(self, fs: M.Flowsheet):
        self.flowsheet = fs
        self.rebuild()
        self.graphChanged.emit()

    def rebuild(self):
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        for node in self.flowsheet.nodes.values():
            self._add_node_item(node)
        for link in self.flowsheet.links.values():
            self._add_edge_item(link)

    def _add_node_item(self, node: M.UnitNode) -> NodeItem:
        item = NodeItem(node)
        self.addItem(item)
        self.node_items[node.id] = item
        return item

    def _add_edge_item(self, link: M.StreamLink) -> EdgeItem:
        edge = EdgeItem(link, self)
        self.addItem(edge)
        self.edge_items[link.id] = edge
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

    # -- public helpers used by the editor ------------------------------ #
    def add_node(self, kind: str, scene_pos: QPointF) -> NodeItem:
        x = round(scene_pos.x() / SNAP) * SNAP
        y = round(scene_pos.y() / SNAP) * SNAP
        node = self.flowsheet.add_node(kind, x, y)
        item = self._add_node_item(node)
        self.clearSelection()
        item.setSelected(True)
        self.graphChanged.emit()
        return item

    def update_edges_for(self, node_id: str):
        for edge in self.edge_items.values():
            if edge.link.src_node == node_id or edge.link.dst_node == node_id:
                edge.update_path()

    def delete_selected(self):
        removed = False
        for item in list(self.selectedItems()):
            if isinstance(item, NodeItem):
                self.flowsheet.remove_node(item.node.id)
                removed = True
            elif isinstance(item, EdgeItem):
                self.flowsheet.remove_link(item.link.id)
                removed = True
        if removed:
            for nid in list(self.node_items):
                if nid not in self.flowsheet.nodes:
                    self.removeItem(self.node_items.pop(nid))
            self._sync_edges()
            self.graphChanged.emit()

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
                self._temp_edge.setPen(QPen(QColor(COL_STREAM_SEL), 1.8, Qt.DashLine))
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
        nodes = [it for it in self.selectedItems() if isinstance(it, NodeItem)]
        self.nodeSelected.emit(nodes[0].node.id if len(nodes) == 1 else None)

    def node_item(self, node_id: str) -> NodeItem | None:
        return self.node_items.get(node_id)
