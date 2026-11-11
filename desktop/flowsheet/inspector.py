"""Inspector: the process variables and the figures of the selected block.

For a block generated from the case study every knob is a scenario field
(:class:`~desktop.flowsheet.process.Variable`): moving it re-runs the engine and
the whole drawing follows. A block drawn by hand from the palette shows its own
sketch parameters instead, which only drive the canvas mass balance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, model as M
from . import process as P
from .charts import ACCENT, BAD, DIM, FAINT, GWP_C, INK, Meter, ResponseChart
from .theme import THIN_SCROLLBAR, category_color

_STATUS_COLOR = {"ok": "#22c55e", "warning": "#f59e0b", "error": "#ef4444", "idle": "#a8b4c0"}


@dataclass
class Context:
    """What the inspector needs to know about the current state of the design."""

    session: P.DesignSession
    results: object | None          # engine results at the current point (None: not admissible)
    drawn: object | None            # results the canvas shows (the last admissible point)
    att: P.Attribution | None
    status: dict = field(default_factory=dict)   # base role -> (level, [messages])
    library: object | None = None
    streams_for: object | None = None            # callable(node_id) -> rows for the stream table


def _round_sig(v: float, sig: int = 3) -> float:
    if v == 0 or not math.isfinite(v):
        return v
    return round(v, sig - 1 - int(math.floor(math.log10(abs(v)))))


class _ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


def _section_head(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(f"color:{FAINT}; font-size:9px; font-weight:700; letter-spacing:0.6px; "
                      "padding:8px 0 2px 0;")
    return lbl


def _kv_table(rows) -> str:
    cells = "".join(
        f"<tr><td style='color:{DIM}; padding:1px 8px 1px 0'>{k}</td>"
        f"<td align='right' style='color:{INK}; font-weight:600; padding:1px 0'>{v}</td></tr>"
        for k, v in rows)
    return f"<table width='100%' cellspacing='0' cellpadding='0'>{cells}</table>"


# --------------------------------------------------------------------------- #
# One process variable
# --------------------------------------------------------------------------- #
class VariableRow(QWidget):
    """Label, numeric field, slider, reset to the case value and the elasticity."""

    edited = Signal(object, float, bool)    # variable, value in engine units, start a new step
    focused = Signal(object)
    resetRequested = Signal(object)

    STEPS = 1000

    def __init__(self, var: P.Variable, value: float, baseline: float | None, parent=None):
        super().__init__(parent)
        self.var = var
        self._baseline = baseline
        self._updating = False
        self._fresh = True
        self._lo, self._hi = self._span(value, baseline)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 3, 0, 3)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)

        self.dot = QLabel("●")
        self.dot.setFixedWidth(9)
        unit = f" <span style='color:{FAINT}; font-weight:400'>[{var.unit}]</span>" if var.unit else ""
        self.name = _ClickLabel(f"{var.label}{unit}")
        self.name.setWordWrap(True)
        self.name.setStyleSheet(f"color:{INK}; font-size:11px; font-weight:600;")
        self.name.setCursor(Qt.PointingHandCursor)
        self.name.setToolTip(var.help or var.label)
        self.name.clicked.connect(lambda: self.focused.emit(self.var))

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(var.decimals)
        lo = var.limit_lo * var.factor if var.limit_lo is not None else -1e15
        hi = var.limit_hi * var.factor if var.limit_hi is not None else 1e15
        self.spin.setRange(lo, hi)
        self.spin.setKeyboardTracking(False)
        self.spin.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        self.spin.setFixedWidth(110)
        self.spin.setGroupSeparatorShown(True)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setToolTip(var.help or var.label)

        self.btn_reset = QToolButton()
        self.btn_reset.setText("↺")
        self.btn_reset.setAutoRaise(True)
        self.btn_reset.setFixedWidth(22)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.STEPS)
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal{height:4px; background:#e2e8f0; border-radius:2px;}"
            f"QSlider::sub-page:horizontal{{background:{ACCENT}; border-radius:2px;}}"
            "QSlider::handle:horizontal{width:12px; margin:-5px 0; border-radius:6px; "
            f"background:#ffffff; border:2px solid {ACCENT};}}")

        self.info = QLabel("")
        self.info.setTextFormat(Qt.RichText)
        self.info.setWordWrap(True)
        self.info.setStyleSheet("font-size:10px;")
        self.info.setToolTip("Elasticity at the current point: the % change of the production "
                             "cost (and of the GWP) for a 1 % change of this input.")

        grid.addWidget(self.dot, 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(self.spin, 0, 2)
        grid.addWidget(self.btn_reset, 0, 3)
        grid.addWidget(self.slider, 1, 1, 1, 3)
        grid.addWidget(self.info, 2, 1, 1, 3)
        grid.setColumnStretch(1, 1)

        self.slider.sliderPressed.connect(self._pressed)
        self.slider.valueChanged.connect(self._slider_moved)
        self.spin.valueChanged.connect(self._spin_changed)
        self.btn_reset.clicked.connect(lambda: self.resetRequested.emit(self.var))
        self._ecost = self._egwp = None
        self.set_value(value, baseline)

    # -- mapping ---------------------------------------------------------- #
    def _span(self, value: float, baseline: float | None) -> tuple[float, float]:
        lo, hi = self.var.span(value)
        if baseline is not None:
            lo, hi = min(lo, baseline), max(hi, baseline)
        if self.var.log:
            lo = max(lo, 1e-9)
            if hi <= lo:
                hi = lo * 10.0
        elif hi <= lo:
            hi = lo + 1.0
        return lo, hi

    def _to_slider(self, v: float) -> int:
        lo, hi = self._lo, self._hi
        if self.var.log and v > 0:
            t = (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo))
        else:
            t = (v - lo) / (hi - lo)
        return int(round(max(0.0, min(1.0, t)) * self.STEPS))

    def _from_slider(self, i: int) -> float:
        t = i / self.STEPS
        if self.var.log:
            v = _round_sig(self._lo * (self._hi / self._lo) ** t, 3)
        else:
            v = self._lo + (self._hi - self._lo) * t
            v = round(v * self.var.factor, self.var.decimals) / self.var.factor
        return self.var.clip(v)

    # -- user input -------------------------------------------------------- #
    def _pressed(self):
        self._fresh = True
        self.focused.emit(self.var)

    def _slider_moved(self, i: int):
        if self._updating:
            return
        v = self._from_slider(i)
        self._updating = True
        self.spin.setValue(v * self.var.factor)
        self._updating = False
        fresh, self._fresh = self._fresh, False
        self.edited.emit(self.var, v, fresh)

    def _spin_changed(self, shown: float):
        if self._updating:
            return
        v = self.var.clip(shown / self.var.factor)
        self._updating = True
        if not (self._lo <= v <= self._hi):
            self._lo, self._hi = self._span(v, self._baseline)
        self.slider.setValue(self._to_slider(v))
        self._updating = False
        self.focused.emit(self.var)
        self.edited.emit(self.var, v, False)

    def is_active(self) -> bool:
        return self.slider.isSliderDown()

    # -- state pushed by the editor --------------------------------------- #
    def set_value(self, value: float, baseline: float | None):
        self._baseline = baseline
        self._updating = True
        if not (self._lo <= value <= self._hi):
            self._lo, self._hi = self._span(value, baseline)
        if abs(self.spin.value() - value * self.var.factor) > 10 ** (-self.var.decimals - 1):
            self.spin.setValue(value * self.var.factor)
        if not self.slider.isSliderDown():
            self.slider.setValue(self._to_slider(value))
        self._updating = False
        changed = baseline is not None and abs(value - baseline) > 1e-12 * max(1.0, abs(baseline))
        self.dot.setStyleSheet(f"color:{ACCENT if changed else 'transparent'}; font-size:9px;")
        self.dot.setToolTip("Changed from the case study" if changed else "")
        self.btn_reset.setEnabled(changed)
        self.btn_reset.setToolTip(
            f"Back to the case-study value ({P.fmt_value(baseline * self.var.factor, self.var.decimals)}"
            f" {self.var.unit})" if baseline is not None else "")
        self._render_info()

    def set_elasticity(self, e_cost, e_gwp):
        self._ecost, self._egwp = e_cost, e_gwp
        self._render_info()

    def _render_info(self):
        def chip(name, e, color):
            if e is None:
                return f"<span style='color:{FAINT}'>{name} —</span>"
            strong = abs(e) >= 0.5
            col = color if abs(e) >= 0.05 else FAINT
            weight = 700 if strong else 500
            return f"<span style='color:{col}; font-weight:{weight}'>{name} {e:+.2f}</span>"

        parts = ["<span style='color:#94a3b8'>ε</span> " + chip("cost", self._ecost, ACCENT),
                 chip("GWP", self._egwp, GWP_C)]
        text = " &nbsp;·&nbsp; ".join(parts)
        b = self._baseline
        if b is not None and self.btn_reset.isEnabled():
            text += (f" &nbsp;&nbsp;<span style='color:{FAINT}'>case "
                     f"{P.fmt_value(b * self.var.factor, self.var.decimals)}</span>")
        self.info.setText(text)


# --------------------------------------------------------------------------- #
# The inspector panel
# --------------------------------------------------------------------------- #
class Inspector(QWidget):
    variableEdited = Signal(object, float, bool)
    variableFocused = Signal(object)
    variableReset = Signal(object)
    technologyChosen = Signal(str, str)        # role, preset name
    nodeParamEdited = Signal(str, str, float)  # node id, key, value
    nodeRenamed = Signal(str, str)
    deleteRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(330)
        self.setMaximumWidth(460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().setStyleSheet(THIN_SCROLLBAR)
        outer.addWidget(self.scroll, 1)

        self.response = ResponseChart()
        self.response.setFixedHeight(200)
        self.response.setStyleSheet("background:#ffffff;")
        frame = QFrame()
        frame.setObjectName("respFrame")
        frame.setStyleSheet("#respFrame{background:#ffffff; border:1px solid #e2e8f0; border-radius:8px;}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(4, 4, 4, 4)
        fl.addWidget(self.response)
        outer.addWidget(frame, 0)
        self._response_frame = frame

        self._mode: tuple = ("empty", None)
        self._rows: dict[str, VariableRow] = {}
        self._paths: list[str] = []
        self._specs: QLabel | None = None
        self._meters: dict[str, Meter] = {}
        self._header_status: QLabel | None = None
        self._streams: QLabel | None = None
        self._items: QLabel | None = None
        self.show_empty("Select a block on the canvas to inspect it.")

    # -- helpers -------------------------------------------------------- #
    def _new_page(self) -> QVBoxLayout:
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 2, 10, 8)
        lay.setSpacing(2)
        self.scroll.setWidget(page)
        # the response chart only means something for knobs wired to the engine
        self._response_frame.setVisible(self._mode[0] in ("linked", "plant"))
        self._rows, self._paths, self._meters = {}, [], {}
        self._specs = self._header_status = self._streams = self._items = None
        return lay

    def variables(self) -> list[P.Variable]:
        return [row.var for row in self._rows.values()]

    def is_editing(self) -> bool:
        """True while a slider is held down (the page must not be rebuilt under it)."""
        return any(row.is_active() for row in self._rows.values())

    @property
    def mode(self) -> tuple:
        return self._mode

    def _header(self, lay, icon_key: str, color: str, tag: str, name: str, sub: str):
        box = QFrame()
        box.setObjectName("inspHead")
        box.setStyleSheet("#inspHead{background:#ffffff; border:1px solid #e2e8f0; border-radius:8px;}")
        h = QHBoxLayout(box)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)
        if icon_key:
            ic = QLabel()
            ic.setPixmap(icons.icon_pixmap(icon_key, 46, QColor(color)))
            ic.setFixedSize(46, 46)
            h.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(f"<span style='font-family:Consolas; font-weight:800; font-size:15px; color:{INK}'>"
                   f"{tag}</span>&nbsp; <span style='font-size:12px; font-weight:600; color:{INK}'>"
                   f"{name}</span>")
        t.setTextFormat(Qt.RichText)
        t.setWordWrap(True)
        s = QLabel(sub)
        s.setTextFormat(Qt.RichText)
        s.setWordWrap(True)
        s.setStyleSheet(f"color:{color}; font-size:10px; font-weight:600;")
        st = QLabel("")
        st.setTextFormat(Qt.RichText)
        st.setWordWrap(True)
        st.setStyleSheet("font-size:10px;")
        col.addWidget(t)
        col.addWidget(s)
        col.addWidget(st)
        h.addLayout(col, 1)
        lay.addWidget(box)
        self._header_status = st

    def _set_status(self, level: str, messages: list[str]):
        if self._header_status is None:
            return
        text = {"ok": "Linked to the case study", "warning": "Linked · input warning",
                "error": "Linked · input refused by the engine", "idle": "Drawn by hand"}[level]
        html = f"<span style='color:{_STATUS_COLOR[level]}'>●</span> <span style='color:{DIM}'>{text}</span>"
        for m in messages[:3]:
            html += f"<br><span style='color:{BAD if level == 'error' else '#b45309'}'>{m}</span>"
        self._header_status.setText(html)

    def _add_rows(self, lay, variables, scn, session):
        groups: dict[str, list[P.Variable]] = {}
        for v in variables:
            groups.setdefault(v.group, []).append(v)
        for g in P.GROUPS:
            if g not in groups:
                continue
            lay.addWidget(_section_head(g))
            for v in groups[g]:
                try:
                    value = P.get_value(scn, v.path)
                except (AttributeError, IndexError):
                    continue
                row = VariableRow(v, value, session.baseline_value(v.path))
                row.edited.connect(self.variableEdited)
                row.focused.connect(self.variableFocused)
                row.resetRequested.connect(self.variableReset)
                lay.addWidget(row)
                self._rows[v.path] = row
                self._paths.append(v.path)

    # -- pages ---------------------------------------------------------- #
    def show_empty(self, text: str):
        self._mode = ("empty", None)
        lay = self._new_page()
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color:{DIM}; padding:12px 4px;")
        lay.addWidget(msg)
        lay.addStretch(1)
        self.response.clear("")

    def show_linked(self, node: M.UnitNode, ctx: Context):
        self._mode = ("linked", node.id)
        scn = ctx.session.scenario
        lay = self._new_page()
        sp = node.spec
        color = category_color(sp.category)
        sec = P.section_of(node.role)
        sub = f"{sp.label}"
        if sec is not None:
            sub += f" &nbsp;·&nbsp; <span style='color:{sec.color}'>AREA {sec.code} {sec.label}</span>"
        self._header(lay, sp.icon, color, node.tag, node.name, sub)
        base = P.role_base(node.role)

        tech = P.technology_options(node.role, scn, ctx.library)
        if tech is not None:
            current, choices = tech
            lay.addWidget(_section_head("Technology"))
            combo = QComboBox()
            # long preset names must not widen the panel
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
            combo.addItems(choices)
            if current in choices:
                combo.setCurrentText(current)
            else:
                combo.insertItem(0, current)
                combo.setCurrentIndex(0)
            combo.setToolTip("Swap the library preset behind this block, as on the Scenario tab. "
                             "The drawing is rebuilt if the equipment changes.")
            combo.currentTextChanged.connect(lambda name, r=node.role: self.technologyChosen.emit(r, name))
            lay.addWidget(combo)

        variables = P.variables_for(node.role, scn)
        if node.role != base:
            note = QLabel("Second stage of the dewatering train. The engine treats the train as one "
                          "step, so both stages share these variables.")
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{DIM}; font-size:10px; padding-top:4px;")
            lay.addWidget(note)
        if variables:
            self._add_rows(lay, variables, scn, ctx.session)

        lay.addWidget(_section_head("At this operating point"))
        self._specs = QLabel("")
        self._specs.setTextFormat(Qt.RichText)
        self._specs.setStyleSheet("font-size:11px;")
        lay.addWidget(self._specs)

        if ctx.att is not None and base in ctx.att.units:
            lay.addWidget(_section_head("Share of the plant"))
            for key, label, color_ in (("annual_cost", "Operating cost", ACCENT),
                                       ("capital", "Fixed capital", "#0f766e"),
                                       ("power_kw", "Electric load", "#d4a106"),
                                       ("heat_kw", "Heat duty", "#dc2626"),
                                       ("gwp", "GWP", GWP_C)):
                m = Meter(label, color_)
                lay.addWidget(m)
                self._meters[key] = m
            self._items = QLabel("")
            self._items.setTextFormat(Qt.RichText)
            self._items.setStyleSheet("font-size:10px;")
            lay.addWidget(self._items)

        lay.addWidget(_section_head("Streams"))
        self._streams = QLabel("")
        self._streams.setTextFormat(Qt.RichText)
        self._streams.setStyleSheet("font-size:10px;")
        lay.addWidget(self._streams)
        lay.addStretch(1)
        self.refresh(ctx, node)

    def show_plant(self, ctx: Context):
        self._mode = ("plant", None)
        scn = ctx.session.scenario
        lay = self._new_page()
        self._header(lay, "", ACCENT, "PLANT", scn.organism.name,
                     f"{scn.system.name} &nbsp;·&nbsp; plant-wide inputs")
        self._add_rows(lay, P.variables_for(P.PLANT, scn), scn, ctx.session)
        lay.addWidget(_section_head("Plant summary"))
        self._specs = QLabel("")
        self._specs.setTextFormat(Qt.RichText)
        self._specs.setStyleSheet("font-size:11px;")
        lay.addWidget(self._specs)
        tip = QLabel("Click a block on the drawing to tune its own variables.")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{DIM}; font-size:10px; padding-top:6px;")
        lay.addWidget(tip)
        lay.addStretch(1)
        self.refresh(ctx)

    def show_free(self, node: M.UnitNode, stream_rows):
        """A block drawn by hand: its sketch parameters drive the canvas balance only."""
        self._mode = ("free", node.id)
        lay = self._new_page()
        sp = node.spec
        color = category_color(sp.category)
        self._header(lay, sp.icon, color, node.tag, node.name, sp.label)
        self._set_status("idle", [])
        if sp.hint:
            h = QLabel(sp.hint)
            h.setWordWrap(True)
            h.setStyleSheet(f"color:{DIM}; font-size:10px;")
            lay.addWidget(h)
        lay.addWidget(_section_head("Name"))
        name = QLineEdit(node.name)
        name.textChanged.connect(lambda t, nid=node.id: self.nodeRenamed.emit(nid, t))
        lay.addWidget(name)
        if sp.params:
            lay.addWidget(_section_head("Sketch parameters"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for i, prm in enumerate(sp.params):
            lbl = QLabel(prm.label)
            lbl.setStyleSheet(f"color:{INK}; font-size:11px;")
            if prm.key == "component":
                combo = QComboBox()
                for idx in sorted(M._FEED_COMPONENT):
                    combo.addItem(M._FEED_COMPONENT[idx].capitalize(), idx)
                combo.setCurrentIndex(int(node.params.get("component", prm.default)))
                combo.currentIndexChanged.connect(
                    lambda _i, nid=node.id, cb=combo: self.nodeParamEdited.emit(
                        nid, "component", float(cb.currentData())))
                w = combo
            else:
                sb = QDoubleSpinBox()
                sb.setRange(prm.lo, prm.hi)
                sb.setDecimals(prm.decimals)
                sb.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
                sb.setKeyboardTracking(False)
                sb.setValue(float(node.params.get(prm.key, prm.default)))
                if prm.unit:
                    sb.setSuffix(f"  {prm.unit}")
                sb.valueChanged.connect(
                    lambda v, nid=node.id, key=prm.key: self.nodeParamEdited.emit(nid, key, v))
                w = sb
            grid.addWidget(lbl, i, 0)
            grid.addWidget(w, i, 1)
        lay.addLayout(grid)
        note = QLabel("Drawn by hand: this block is part of the sketch balance on the canvas, "
                      "not of the TEA/LCA case study.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{DIM}; font-size:10px; padding-top:6px;")
        lay.addWidget(note)
        lay.addWidget(_section_head("Streams"))
        self._streams = QLabel(self._stream_html(stream_rows))
        self._streams.setTextFormat(Qt.RichText)
        self._streams.setStyleSheet("font-size:10px;")
        lay.addWidget(self._streams)
        lay.addStretch(1)
        btn = QPushButton("Delete block")
        btn.setStyleSheet("QPushButton{background:#b0392f; color:white; border:none; border-radius:5px; "
                          "padding:6px;} QPushButton:hover{background:#8f2d25;}")
        btn.clicked.connect(lambda _=False, nid=node.id: self.deleteRequested.emit(nid))
        lay.addWidget(btn)
        self.response.clear("Sketch blocks are not linked to the engine, so there is no cost "
                            "response to show.")

    # -- in-place refresh ----------------------------------------------- #
    def needs_rebuild(self, ctx: Context, node: M.UnitNode | None) -> bool:
        """True when the knobs on show no longer match the block (technology, mode)."""
        kind, _nid = self._mode
        if kind not in ("linked", "plant"):
            return False
        role = node.role if (kind == "linked" and node is not None) else P.PLANT
        paths = {v.path for v in P.variables_for(role, ctx.session.scenario)}
        return paths != set(self._paths)

    def refresh(self, ctx: Context, node: M.UnitNode | None = None):
        kind, nid = self._mode
        scn = ctx.session.scenario
        for path, row in self._rows.items():
            if row.is_active():
                continue
            try:
                row.set_value(P.get_value(scn, path), ctx.session.baseline_value(path))
            except (AttributeError, IndexError):
                pass
        r, att = ctx.drawn, ctx.att
        if kind == "linked":
            role = node.role if node is not None else ""
            base = P.role_base(role)
            level, msgs = ctx.status.get(base, ("ok", []))
            self._set_status(level, msgs)
            if self._specs is not None:
                rows = P.specs(role, r, att) if r is not None else []
                self._specs.setText(_kv_table(rows) if rows else
                                    f"<span style='color:{FAINT}'>No figures for this block.</span>")
            u = att.units.get(base) if att is not None else None
            if u is not None and self._meters:
                tot_cap = sum(x.capital for x in att.units.values()) or 1.0
                vals = {
                    "annual_cost": (P.fmt_money(u.annual_cost) + "/yr", att.share(role, "annual_cost")),
                    "capital": (P.fmt_money(u.capital), u.capital / tot_cap),
                    "power_kw": (P.fmt_power(u.power_kw), att.share(role, "power_kw")),
                    "heat_kw": (P.fmt_power(u.heat_kw) + " th", att.share(role, "heat_kw")),
                    "gwp": (f"{u.gwp:,.3f} kg/kg", att.share(role, "gwp")),
                }
                for key, m in self._meters.items():
                    text, share = vals[key]
                    m.set_value(text, share)
                if self._items is not None:
                    items = sorted(u.cost_items.items(), key=lambda kv: -abs(kv[1]))[:5]
                    gw = sorted(u.gwp_items.items(), key=lambda kv: -abs(kv[1]))[:4]
                    html = ""
                    if items:
                        html += "<b style='color:#334155'>Cost lines</b>" + _kv_table(
                            [(k, P.fmt_money(v) + "/yr") for k, v in items])
                    if gw:
                        html += "<br><b style='color:#334155'>GWP lines (per kg DW)</b>" + _kv_table(
                            [(k, f"{v:+,.3f}") for k, v in gw])
                    if u.purchase_cost:
                        html += "<br>" + _kv_table(
                            [("Purchased equipment", P.fmt_money(u.purchase_cost)),
                             ("Units in parallel", f"{u.units_parallel}")])
                    self._items.setText(html)
            if self._streams is not None and ctx.streams_for is not None and nid:
                self._streams.setText(self._stream_html(ctx.streams_for(nid)))
        elif kind == "plant":
            if self._specs is not None and r is not None and att is not None:
                k = P.kpis(r)
                plant = att.units.get(P.PLANT)
                rows = [("Annual output", f"{k['output']:,.1f} t/yr"),
                        ("Operating hours", f"{att.op_hours:,.0f} h/yr"),
                        ("Total investment", f"{k['capex']:,.2f} M€"),
                        ("Operating cost", f"{k['opex']:,.2f} M€/yr"),
                        ("Labour, overhead & other", P.fmt_money(plant.annual_cost if plant else 0.0) + "/yr"),
                        ("NPV", f"{k['npv']:,.1f} M€"),
                        ("Production cost", f"{k['cost']:,.3f} €/kg"),
                        ("GWP", f"{k['gwp']:,.3f} kg CO₂-eq/kg")]
                self._specs.setText(_kv_table(rows))

    def set_elasticities(self, values: dict):
        for path, (ec, eg) in values.items():
            row = self._rows.get(path)
            if row is not None:
                row.set_elasticity(ec, eg)

    @staticmethod
    def _stream_html(rows) -> str:
        if not rows:
            return f"<span style='color:{FAINT}'>No streams.</span>"
        cells = ""
        for num, direction, port, other, total in rows:
            arrow = "◀" if direction == "in" else "▶"
            cells += (f"<tr><td style='color:{FAINT}; padding-right:6px'>{num or '·'}</td>"
                      f"<td style='color:{DIM}'>{arrow} {port}</td>"
                      f"<td style='color:{DIM}; padding:0 6px'>{other}</td>"
                      f"<td align='right' style='color:{INK}; font-weight:600'>{total}</td></tr>")
        return f"<table width='100%' cellspacing='0' cellpadding='1'>{cells}</table>"


__all__ = ["Context", "Inspector", "VariableRow"]
