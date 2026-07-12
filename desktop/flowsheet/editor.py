"""The Process Designer widget: palette + canvas + properties + KPI bar.

This is the single public entry point of the package (re-exported as
``FlowsheetEditor``). It owns a :class:`~desktop.flowsheet.scene.FlowsheetScene`,
lets the user drop unit operations from the palette, edit the selected block's
parameters, and re-runs the first-pass mass balance to annotate every stream.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import icons, model as M
from .scene import FlowsheetScene
from .view import FlowsheetView

# Palette order (category -> heading label).
_CATEGORY_LABELS = {
    "io": "Feeds & products",
    "cultivation": "Cultivation",
    "separation": "Separation",
    "thermal": "Thermal",
    "downstream": "Downstream",
    "logic": "Logic",
}


def _fmt_flow(kg_h: float) -> str:
    if kg_h >= 1000.0:
        return f"{kg_h / 1000.0:,.2f} t/h"
    if kg_h >= 1.0:
        return f"{kg_h:,.0f} kg/h"
    if kg_h > 0.0:
        return f"{kg_h:,.2f} kg/h"
    return "0"


class FlowsheetEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = FlowsheetScene(M.starter_flowsheet())
        self.view = FlowsheetView(self.scene)
        self._add_offset = 0
        self._prop_spins: dict[str, QDoubleSpinBox | QComboBox] = {}
        self._current_node: str | None = None
        self._stream_no: dict[str, int] = {}

        self._build_ui()

        self.scene.graphChanged.connect(self.solve_and_annotate)
        self.scene.nodeSelected.connect(self._on_node_selected)

        self.solve_and_annotate()
        self.view.fit_content()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        root.addLayout(self._build_toolbar())

        middle = QHBoxLayout()
        middle.setSpacing(6)
        middle.addWidget(self._build_palette(), 0)
        middle.addWidget(self.view, 1)
        middle.addWidget(self._build_properties_panel(), 0)
        root.addLayout(middle, 1)

        self.kpi = QLabel("")
        self.kpi.setObjectName("subtle")
        self.kpi.setWordWrap(True)
        self.kpi.setTextFormat(Qt.RichText)
        root.addWidget(self.kpi)

    _SECONDARY_BTN = (
        "QPushButton{background:#ffffff; color:#334155; border:1px solid #cbd5e1; "
        "border-radius:5px; padding:6px 11px; font-weight:600;} "
        "QPushButton:hover{background:#f1f5f9; border-color:#94a3b8;}")

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(5)

        def btn(text, slot, style=None):
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setStyleSheet(style or self._SECONDARY_BTN)
            bar.addWidget(b)
            return b

        title = QLabel("Process Flow Diagram")
        title.setStyleSheet("font-weight:700; color:#0f172a; font-size:14px; letter-spacing:0.3px;")
        bar.addWidget(title)
        bar.addSpacing(14)

        btn("↻ Update balance", self.solve_and_annotate,
            "QPushButton{background:#15803d; color:white; border:none; border-radius:5px; "
            "padding:6px 12px; font-weight:700;} QPushButton:hover{background:#116330;}")
        btn("⤢ Fit", self.view.fit_content)
        btn("1:1", self.view.reset_zoom)
        bar.addSpacing(10)
        btn("Save…", self.save_flowsheet)
        btn("Load…", self.load_flowsheet)
        btn("Example", self.load_example)
        btn("Clear", self.clear_flowsheet,
            "QPushButton{background:#ffffff; color:#b0392f; border:1px solid #e3b7b3; "
            "border-radius:5px; padding:6px 11px; font-weight:600;} "
            "QPushButton:hover{background:#fbeceb;}")
        bar.addStretch(1)

        hint = QLabel("Double-click to add · drag outlet → inlet to connect · Del to remove")
        hint.setObjectName("subtle")
        bar.addWidget(hint)
        return bar

    def _build_palette(self) -> QWidget:
        box = QFrame()
        box.setObjectName("kpiCard")
        box.setFixedWidth(206)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        head = QLabel("Unit operations")
        head.setStyleSheet("font-weight:700; color:#334155;")
        lay.addWidget(head)

        self.palette = QListWidget()
        self.palette.setFrameShape(QFrame.NoFrame)
        self.palette.setIconSize(QSize(22, 22))
        self.palette.setStyleSheet("QListWidget{background:transparent;} "
                                   "QListWidget::item{padding:4px 4px; border-radius:6px;} "
                                   "QListWidget::item:hover{background:#eef5ee;}")
        self.palette.itemDoubleClicked.connect(self._palette_add)

        for cat, label in _CATEGORY_LABELS.items():
            header = QListWidgetItem(label.upper())
            header.setFlags(Qt.NoItemFlags)
            f = QFont("Segoe UI", 7, QFont.Bold)
            header.setFont(f)
            header.setForeground(QColor("#90a0ab"))
            self.palette.addItem(header)
            color = QColor(M.CATEGORY_COLORS.get(cat, "#455a64"))
            for key, sp in M.UNIT_TYPES.items():
                if sp.category != cat:
                    continue
                item = QListWidgetItem(f"  {sp.label}")
                item.setIcon(QIcon(icons.icon_pixmap(sp.icon, 22, color)))
                item.setData(Qt.UserRole, key)
                item.setToolTip(sp.hint)
                self.palette.addItem(item)

        lay.addWidget(self.palette, 1)
        tip = QLabel("Double-click to drop on canvas")
        tip.setObjectName("subtle")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return box

    def _build_properties_panel(self) -> QWidget:
        box = QFrame()
        box.setObjectName("kpiCard")
        box.setFixedWidth(288)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(8, 8, 8, 8)

        head = QLabel("Equipment details")
        head.setStyleSheet("font-weight:700; color:#334155;")
        outer.addWidget(head)

        self.prop_scroll = QScrollArea()
        self.prop_scroll.setWidgetResizable(True)
        self.prop_scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.prop_scroll, 1)

        self._show_placeholder()
        return box

    def _show_placeholder(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        msg = QLabel("Select a block on the canvas to edit its parameters.")
        msg.setObjectName("subtle")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        lay.addStretch(1)
        self.prop_scroll.setWidget(w)

    # ------------------------------------------------------------------ #
    # Palette / adding nodes
    # ------------------------------------------------------------------ #
    def _palette_add(self, item: QListWidgetItem):
        kind = item.data(Qt.UserRole)
        if not kind:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self._add_offset = (self._add_offset + 1) % 6
        pos = QPointF(center.x() - 84 + self._add_offset * 18,
                      center.y() - 40 + self._add_offset * 18)
        self.scene.add_node(kind, pos)

    # ------------------------------------------------------------------ #
    # Selection -> properties form
    # ------------------------------------------------------------------ #
    def _on_node_selected(self, node_id):
        self._current_node = node_id
        if node_id is None or node_id not in self.scene.flowsheet.nodes:
            self._show_placeholder()
            return
        self._build_form(node_id)

    def _build_form(self, node_id: str):
        node = self.scene.flowsheet.nodes[node_id]
        sp = node.spec
        self._prop_spins = {}

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        accent = M.CATEGORY_COLORS.get(sp.category, "#455a64")
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.icon_pixmap(sp.icon, 34, QColor(accent)))
        icon_lbl.setFixedSize(34, 34)
        header_row.addWidget(icon_lbl)
        titlebox = QVBoxLayout()
        titlebox.setSpacing(0)
        tag_lbl = QLabel(node.tag)
        tag_lbl.setStyleSheet(
            "font-family:Consolas,'Courier New'; font-weight:800; font-size:15px; color:#0f172a;")
        class_lbl = QLabel(sp.label)
        class_lbl.setStyleSheet(f"color:{accent}; font-weight:600; font-size:11px;")
        titlebox.addWidget(tag_lbl)
        titlebox.addWidget(class_lbl)
        header_row.addLayout(titlebox, 1)
        lay.addLayout(header_row)

        if sp.hint:
            h = QLabel(sp.hint)
            h.setObjectName("subtle")
            h.setWordWrap(True)
            lay.addWidget(h)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        name_edit = QLineEdit(node.name)
        name_edit.textChanged.connect(lambda t, nid=node_id: self._rename(nid, t))
        form.addRow("Name", name_edit)

        for p in sp.params:
            if p.key == "component":
                combo = QComboBox()
                for idx in sorted(M._FEED_COMPONENT):
                    combo.addItem(M._FEED_COMPONENT[idx].capitalize(), idx)
                combo.setCurrentIndex(int(node.params.get("component", p.default)))
                combo.currentIndexChanged.connect(
                    lambda i, nid=node_id, cb=combo: self._set_param(nid, "component", float(cb.currentData())))
                form.addRow(p.label, combo)
                self._prop_spins["component"] = combo
            else:
                sb = QDoubleSpinBox()
                sb.setRange(p.lo, p.hi)
                sb.setDecimals(p.decimals)
                sb.setValue(float(node.params.get(p.key, p.default)))
                step = 10 ** (-p.decimals) * 10 if p.decimals else 1.0
                sb.setSingleStep(step)
                if p.unit:
                    sb.setSuffix(f"  {p.unit}")
                sb.valueChanged.connect(
                    lambda v, nid=node_id, key=p.key: self._set_param(nid, key, v))
                form.addRow(p.label, sb)
                self._prop_spins[p.key] = sb

        lay.addLayout(form)

        # --- stream table (engineering detail) ----------------------------- #
        st_head = QLabel("Streams")
        st_head.setStyleSheet("font-weight:700; color:#334155; margin-top:6px;")
        lay.addWidget(st_head)

        self.stream_table = QTableWidget(0, 4)
        self.stream_table.setHorizontalHeaderLabels(["S#", "Port", "kg/h", "Composition"])
        self.stream_table.verticalHeader().setVisible(False)
        self.stream_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stream_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.stream_table.setAlternatingRowColors(True)
        self.stream_table.setStyleSheet(
            "QTableWidget{border:1px solid #e2e8f0; font-size:11px;} "
            "QHeaderView::section{font-size:10px;}")
        hh = self.stream_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.stream_table.setMinimumHeight(120)
        lay.addWidget(self.stream_table)

        # --- performance summary ------------------------------------------ #
        self.perf_label = QLabel("")
        self.perf_label.setTextFormat(Qt.RichText)
        self.perf_label.setWordWrap(True)
        self.perf_label.setStyleSheet(
            "background:#f1f5f9; border:1px solid #e2e8f0; border-radius:4px; "
            "padding:6px; font-size:11px; color:#33414d;")
        lay.addWidget(self.perf_label)

        lay.addStretch(1)
        del_btn = QPushButton("Delete block")
        del_btn.setStyleSheet("background:#b0392f;")
        del_btn.clicked.connect(lambda _=False, nid=node_id: self._delete_node(nid))
        lay.addWidget(del_btn)

        self.prop_scroll.setWidget(w)
        self._update_details(node_id)

    def _rename(self, node_id: str, text: str):
        node = self.scene.flowsheet.nodes.get(node_id)
        if node is None:
            return
        node.name = text
        item = self.scene.node_item(node_id)
        if item is not None:
            item.update()

    def _set_param(self, node_id: str, key: str, value: float):
        node = self.scene.flowsheet.nodes.get(node_id)
        if node is None:
            return
        node.params[key] = float(value)
        self.solve_and_annotate()

    def _delete_node(self, node_id: str):
        item = self.scene.node_item(node_id)
        if item is not None:
            self.scene.clearSelection()
            item.setSelected(True)
            self.scene.delete_selected()
        self._show_placeholder()

    # ------------------------------------------------------------------ #
    # Solve + annotate
    # ------------------------------------------------------------------ #
    def solve_and_annotate(self):
        fs = self.scene.flowsheet
        result = M.solve(fs)

        # Number streams 1..N in a stable order (used on the canvas and the table).
        self._stream_no = {lid: i + 1 for i, lid in enumerate(fs.links)}

        for lid, edge in self.scene.edge_items.items():
            flow = result.stream_flows.get(lid, M.empty_flow())
            edge.set_stream(self._stream_no.get(lid, 0), _fmt_flow(M.flow_total(flow)))

        for nid, item in self.scene.node_items.items():
            item.set_readout(self._node_readout(nid, result))

        self._update_kpi(fs, result)
        if self._current_node:
            self._update_details(self._current_node)

    def _node_readout(self, node_id: str, result: M.SolveResult) -> str:
        node = self.scene.flowsheet.nodes[node_id]
        if not node.spec.outputs:  # sink: show inbound
            agg = M.empty_flow()
            for lk in self.scene.flowsheet.links.values():
                if lk.dst_node == node_id:
                    agg = M.flow_add(agg, result.stream_flows.get(lk.id, M.empty_flow()))
            return "← " + _fmt_flow(M.flow_total(agg))
        outs = result.node_outputs.get(node_id, {})
        total = sum(M.flow_total(f) for f in outs.values())
        return "Σ " + _fmt_flow(total)

    @staticmethod
    def _composition(flow) -> str:
        parts = [f"{c} {v:,.1f}" for c, v in flow.items() if v > 0.01]
        return ", ".join(parts) if parts else "—"

    def _update_details(self, node_id: str):
        """Fill the stream table and performance summary for the selected block."""
        if node_id not in self.scene.flowsheet.nodes or not hasattr(self, "stream_table"):
            return
        fs = self.scene.flowsheet
        result = M.solve(fs)
        node = fs.nodes[node_id]
        sp = node.spec
        outs = result.node_outputs.get(node_id, {})

        rows: list[tuple] = []          # (s#, dir, port, other_tag, flow)
        in_agg = M.empty_flow()
        out_agg = M.empty_flow()

        for port in sp.inputs:
            lk = next((l for l in fs.links.values()
                       if l.dst_node == node_id and l.dst_port == port), None)
            if lk is not None:
                flow = result.stream_flows.get(lk.id, M.empty_flow())
                other = fs.nodes[lk.src_node].tag if lk.src_node in fs.nodes else "?"
                rows.append((self._stream_no.get(lk.id, 0), "in", port, other, flow))
                in_agg = M.flow_add(in_agg, flow)
            else:
                rows.append((0, "in", port, "—", M.empty_flow()))
        for port in sp.outputs:
            flow = outs.get(port, M.empty_flow())
            out_agg = M.flow_add(out_agg, flow)
            lk = next((l for l in fs.links.values()
                       if l.src_node == node_id and l.src_port == port), None)
            other = fs.nodes[lk.dst_node].tag if lk and lk.dst_node in fs.nodes else "—"
            num = self._stream_no.get(lk.id, 0) if lk is not None else 0
            rows.append((num, "out", port, other, flow))
        # a sink has no output ports: report its inbound as the "product" line
        if not sp.outputs:
            for lk in fs.links.values():
                if lk.dst_node == node_id:
                    in_agg = M.flow_add(
                        M.empty_flow(), result.stream_flows.get(lk.id, M.empty_flow()))

        self.stream_table.setRowCount(len(rows))
        for r, (num, direction, port, other, flow) in enumerate(rows):
            arrow = "◀" if direction == "in" else "▶"
            cells = [
                str(num) if num else "·",
                f"{arrow} {port} · {other}",
                _fmt_flow(M.flow_total(flow)),
                self._composition(flow),
            ]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setTextAlignment(Qt.AlignCenter)
                self.stream_table.setItem(r, c, it)

        # performance summary: totals + notable component changes
        perf = []
        if sp.inputs:
            perf.append(f"Σ in <b>{_fmt_flow(M.flow_total(in_agg))}</b>")
        if sp.outputs:
            perf.append(f"Σ out <b>{_fmt_flow(M.flow_total(out_agg))}</b>")
        deltas = []
        for comp in M.COMPONENTS:
            d = out_agg.get(comp, 0.0) - in_agg.get(comp, 0.0)
            if d > 0.05:
                deltas.append(f"{comp} +{d:,.1f} (generated)")
            elif d < -0.05:
                deltas.append(f"{comp} −{abs(d):,.1f} (removed)")
        head = " · ".join(perf) if perf else "sink"
        body = "<br>".join(deltas[:4]) if deltas else "mass conserved"
        self.perf_label.setText(f"{head}<br><span style='color:#5b6b78;'>{body}</span>")

    def _update_kpi(self, fs: M.Flowsheet, result: M.SolveResult):
        products = result.product_flows(fs)
        parts = []
        for name, flow in products.items():
            parts.append(f"<b>{name}</b> {_fmt_flow(M.flow_total(flow))}")
        text = "📦 Product sinks: " + (" · ".join(parts) if parts else "none")
        if result.warnings:
            text += "   ⚠ " + "; ".join(result.warnings)
        n_nodes = len(fs.nodes)
        n_links = len(fs.links)
        text = f"<span style='color:#5b6b78;'>{n_nodes} blocks · {n_links} streams</span>&nbsp;&nbsp;|&nbsp;&nbsp;" + text
        self.kpi.setText(text)

    # ------------------------------------------------------------------ #
    # File / lifecycle
    # ------------------------------------------------------------------ #
    def save_flowsheet(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save flowsheet", "flowsheet.flow.json", "Flowsheet (*.flow.json *.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.scene.flowsheet.to_dict(), indent=2), encoding="utf-8")

    def load_flowsheet(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load flowsheet", "", "Flowsheet (*.flow.json *.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            fs = M.Flowsheet.from_dict(data)
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", f"Could not read flowsheet:\n{exc}")
            return
        self.scene.set_flowsheet(fs)
        self._show_placeholder()
        self.solve_and_annotate()
        self.view.fit_content()

    def load_example(self):
        self.scene.set_flowsheet(M.starter_flowsheet())
        self._show_placeholder()
        self.solve_and_annotate()
        self.view.fit_content()

    def clear_flowsheet(self):
        if QMessageBox.question(self, "Clear canvas", "Remove all blocks and streams?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.scene.set_flowsheet(M.Flowsheet())
        self._show_placeholder()
        self.solve_and_annotate()
