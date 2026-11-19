"""Small painted charts for the Process Designer panels.

Each one is a plain ``QWidget`` with a ``paintEvent``: cheap enough to redraw on
every slider tick, sized by its layout, and free of a plotting library. Colours,
type sizes and radii are the app's tokens (``desktop/theme.py``) and the marks
follow the chart rules in ``docs/UI_GUIDELINES.md``: one value axis per plot,
thin bars with a gap between stacked parts and a rounded data end, text in the
ink tones (a coloured key beside it carries the identity), exact values on
hover.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .. import theme as ui
from . import process as P

INK = ui.INK
DIM = ui.INK_2           # secondary text
FAINT = ui.INK_3         # captions and axis text: the lightest tone that carries text
AXIS = ui.CHART_AXIS     # axis lines, reference ticks, connectors (never text)
LINE = ui.LINE
GRIDC = ui.CHART_GRID
GOOD = ui.SUCCESS
BAD = ui.DANGER
ACCENT = ui.ACCENT
COST_C = ui.SERIES[0]    # production cost
GWP_C = ui.SERIES[1]     # GWP
LOW_C = ui.SERIES[0]     # input moved down
HIGH_C = ui.SERIES[1]    # input moved up

GAP = 2.0                # surface gap between touching parts of a bar
BAR_R = 4.0              # radius of a bar's data end


def _font(px: int, weight=QFont.Normal) -> QFont:
    """The application font at a size of the type scale, in pixels."""
    f = QFont(QGuiApplication.font())
    f.setPixelSize(int(px))
    f.setWeight(weight)
    return f


def _alpha(color: str | QColor, a: int) -> QColor:
    c = QColor(color)
    c.setAlpha(a)
    return c


def _nice_step(span: float, n: int = 4) -> float:
    if span <= 0 or not math.isfinite(span):
        return 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _fmt_axis(v: float) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:,.1f}M"
    if a >= 1e4:
        return f"{v / 1e3:,.0f}k"
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 10:
        return f"{v:,.1f}"
    if a >= 1:
        return f"{v:,.2f}"
    if a == 0:
        return "0"
    return f"{v:.2g}"


def _sig(v: float, digits: int = 3) -> str:
    """A derived quantity to three significant figures."""
    if v == 0 or not math.isfinite(v):
        return f"{v:g}"
    decimals = max(digits - 1 - int(math.floor(math.log10(abs(v)))), 0)
    return f"{v:,.{decimals}f}"


def _share(s: float) -> str:
    """A share of the plant, in whole per cent."""
    pct = s * 100.0
    if 0 < abs(pct) < 0.5:
        return "< 1 %" if pct > 0 else "> −1 %"
    return f"{pct:,.0f} %".replace("-", "−")


def _bar(rect: QRectF, round_left: bool, round_right: bool, radius: float = BAR_R) -> QPainterPath:
    """A bar with rounded corners at its data end and square ones at its baseline."""
    path = QPainterPath()
    r = min(radius, rect.width() / 2.0, rect.height() / 2.0)
    if r < 0.75 or not (round_left or round_right):
        path.addRect(rect)
        return path
    path.addRoundedRect(rect, r, r)
    square = QPainterPath()
    half = rect.width() / 2.0
    if not round_left:
        square.addRect(QRectF(rect.left(), rect.top(), half, rect.height()))
    if not round_right:
        square.addRect(QRectF(rect.left() + half, rect.top(), rect.width() - half, rect.height()))
    return path if square.isEmpty() else path.united(square)


def _legend(p: QPainter, x: float, y: float, items, right: float) -> float:
    """Swatch-and-label legend on one line from ``x``; returns where it ended."""
    p.setFont(_font(ui.TEXT_SM))
    fm = QFontMetricsF(p.font())
    for label, color in items:
        tw = fm.horizontalAdvance(label)
        if x + 14 + tw > right:
            break
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(x, y + 4, 10, 10), 2, 2)
        p.setPen(QColor(DIM))
        p.drawText(QRectF(x + 14, y, tw + 2, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
        x += 14 + tw + 14
    return x


# --------------------------------------------------------------------------- #
# KPI tile
# --------------------------------------------------------------------------- #
class KpiTile(QWidget):
    """Headline figure of the design: value and unit, the basis it is on, its
    change against the case study and a sparkline of the values it took over the
    editing session. Painted to match the app's KPI cards, in less height."""

    H = 80
    PAD = 12.0

    def __init__(self, kpi: P.KPI, parent=None):
        super().__init__(parent)
        self.kpi = kpi
        self._value: float | None = None
        self._base: float | None = None
        self._hist: list[float] = []
        self._note = ""
        self._basis = ""
        self.setMinimumWidth(118)
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName(kpi.label)

    def set_data(self, value: float | None, baseline: float | None, history: list[float]):
        self._value, self._base = value, baseline
        self._hist = [h for h in history if h is not None and math.isfinite(h)]
        self._note = ""
        self._refresh_tip()
        self.update()

    def set_unavailable(self, note: str = "not admissible"):
        self._value = None
        self._note = note
        self.setToolTip(f"{self.kpi.label}: {note}")
        self.setAccessibleDescription(note)
        self.update()

    def set_basis(self, text: str):
        if text != self._basis:
            self._basis = text
            self._refresh_tip()
            self.update()

    def _delta(self) -> float | None:
        if self._value is None or self._base is None:
            return None
        if abs(self._base) < 1e-12:
            return None if abs(self._value) < 1e-12 else math.copysign(1.0, self._value)
        return (self._value - self._base) / abs(self._base)

    def _state(self) -> str:
        d = self._delta()
        if d is None or abs(d) < 5e-4:
            return "same"
        better = (d < 0) if self.kpi.lower_is_better else (d > 0)
        return "good" if better else "bad"

    def _delta_text(self) -> str:
        d = self._delta()
        if self._state() == "same" or d is None:
            return "= case"
        arrow = "▲" if d > 0 else "▼"
        return f"{arrow} {abs(d) * 100:,.1f} %" if abs(d) < 10 else f"{arrow} ×{1 + d:,.1f}"

    def _refresh_tip(self):
        k = self.kpi
        if self._value is None:
            return
        value = f"{P.fmt_value(self._value, k.decimals)} {k.unit}"
        tip = f"{k.label}: {value}"
        if self._basis:
            tip += f"\n{self._basis}"
        if self._base is not None:
            tip += f"\nCase study: {P.fmt_value(self._base, k.decimals)} {k.unit}"
            if self._state() != "same":
                tip += f" ({self._delta_text()})"
        self.setToolTip(tip)
        self.setAccessibleDescription(tip)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        k = self.kpi
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(LINE), 1.0))
        p.setBrush(QColor(ui.SURFACE))
        p.drawRoundedRect(r, ui.RADIUS_LG, ui.RADIUS_LG)

        left = self.PAD
        right = r.width() - self.PAD
        inner = right - left
        row1 = QRectF(left, 8, inner, 18)
        row3 = QRectF(left, 56, inner, 16)

        f_title = _font(ui.TEXT_SM, QFont.DemiBold)
        fm_title = QFontMetricsF(f_title)

        f_value = _font(ui.TEXT_XL, QFont.Bold)
        fm_value = QFontMetricsF(f_value)
        f_unit = _font(ui.TEXT_SM)
        fm_unit = QFontMetricsF(f_unit)
        f_small = _font(ui.TEXT_XS)

        if self._value is None:
            self._paint_title(p, row1, k.label, f_title, fm_title)
            p.setFont(f_value)
            p.setPen(QColor(ui.INK_DISABLED))
            p.drawText(QPointF(left, 26 + fm_value.ascent()), "—")
            p.setFont(f_small)
            p.setPen(QColor(FAINT))
            p.drawText(row3, Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetricsF(f_small).elidedText(self._note, Qt.ElideRight, inner))
            p.end()
            return

        text = P.fmt_value(self._value, k.decimals)
        value_w = fm_value.horizontalAdvance(text)
        unit_w = fm_unit.horizontalAdvance(k.unit)
        figure_w = value_w + 5 + unit_w

        state = self._state()
        # The change against the case study sits in the same corner of every
        # tile, and only when there is one; the basis line gives up the room.
        pill_text = self._delta_text() if state != "same" else ""
        f_pill = _font(ui.TEXT_XS, QFont.DemiBold)
        pill_w = QFontMetricsF(f_pill).horizontalAdvance(pill_text) + 14 if pill_text else 0.0

        self._paint_title(p, row1, k.label, f_title, fm_title)

        baseline = 27 + fm_value.ascent()
        p.setFont(f_value)
        p.setPen(QColor(INK))
        p.drawText(QPointF(left, baseline), text)
        p.setFont(f_unit)
        p.setPen(QColor(DIM))
        p.drawText(QPointF(left + value_w + 5, baseline),
                   fm_unit.elidedText(k.unit, Qt.ElideRight, max(inner - value_w - 5, 0)))

        basis_room = inner - (pill_w + 8 if pill_w else 0)
        if self._basis and basis_room > 24:
            p.setFont(f_small)
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(left, row3.top(), basis_room, row3.height()),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetricsF(f_small).elidedText(self._basis, Qt.ElideRight, basis_room))

        if pill_text:
            fg, bg = (ui.SUCCESS, ui.SUCCESS_BG) if state == "good" else (ui.DANGER, ui.DANGER_BG)
            pill = QRectF(right - pill_w, row3.center().y() - 9, pill_w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(bg))
            p.drawRoundedRect(pill, 9, 9)
            p.setFont(f_pill)
            p.setPen(QColor(fg))
            p.drawText(pill, Qt.AlignCenter, pill_text)

        # sparkline of the session, in the row of the figure when it has room
        spark_left = left + figure_w + 12
        spark_right = right
        box = QRectF(spark_left, 30, min(spark_right - spark_left, inner * 0.5), 20)
        box.moveRight(spark_right)
        hist = self._hist[-40:]
        if len(hist) >= 2 and box.width() >= 34:
            ref = self._base if self._base is not None else hist[0]
            lo, hi = min(hist + [ref]), max(hist + [ref])
            span = hi - lo or 1.0

            def pt(i, v):
                return QPointF(box.left() + box.width() * i / (len(hist) - 1),
                               box.bottom() - box.height() * (v - lo) / span)

            if self._base is not None:
                yb = box.bottom() - box.height() * (self._base - lo) / span
                p.setPen(QPen(QColor(GRIDC), 1.0))
                p.drawLine(QPointF(box.left(), yb), QPointF(box.right(), yb))
            line = QPainterPath(pt(0, hist[0]))
            for i, v in enumerate(hist[1:], 1):
                line.lineTo(pt(i, v))
            p.setPen(QPen(QColor(ui.CHART_EMPHASIS_GRAY), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(line)
            p.setPen(QPen(QColor(ui.SURFACE), 2.0))
            p.setBrush(QColor(ui.CHART_PRIMARY))
            p.drawEllipse(pt(len(hist) - 1, hist[-1]), 3.5, 3.5)
        p.end()

    @staticmethod
    def _paint_title(p: QPainter, rect: QRectF, text: str, font: QFont, fm: QFontMetricsF):
        p.setFont(font)
        p.setPen(QColor(DIM))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(text, Qt.ElideRight, rect.width()))


# --------------------------------------------------------------------------- #
# Stacked horizontal bars
# --------------------------------------------------------------------------- #
class StackedBars(QWidget):
    """One bar per row, stacked by category; negative parts grow to the left of
    zero. A tick marks each row's total in the case study when it differs."""

    ROW = 26.0
    HEAD = 52.0
    LABEL_W = 184.0
    VALUE_W = 96.0
    BAR_H = 12.0

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.rows: list = []
        self.categories: list = []
        self.unit = ""
        self.fmt = _fmt_axis
        self.note = ""
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, rows, categories, unit: str = "", fmt=None, note: str = ""):
        """``rows``: [(label, dot_colour, {category: value}, baseline_total | None)].
        ``categories``: [(key, label, colour)] in stacking order."""
        self.rows = list(rows)
        self.categories = list(categories)
        self.unit = unit
        self.fmt = fmt or _fmt_axis
        self.note = note
        if self._hover is not None and self._hover >= len(self.rows):
            self._hover = None
        self.setMinimumHeight(int(self.HEAD + self.ROW * max(len(self.rows), 1) + 30))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(560, int(self.HEAD + self.ROW * max(len(self.rows), 1) + 30))

    def table(self) -> tuple[list[str], list[list[str]]]:
        """The chart as a table: one row per bar, one column per category used."""
        used = [(k, lab) for k, lab, _c in self.categories
                if any(parts.get(k) for _l, _d, parts, _b in self.rows)]
        headers = ["Block"] + [lab for _k, lab in used] + ["Total", "Case study"]
        out = []
        for label, _dot, parts, base in self.rows:
            out.append([label] + [self.fmt(parts[k]) if parts.get(k) else "" for k, _lab in used]
                       + [self.fmt(sum(parts.values())), self.fmt(base) if base is not None else ""])
        return headers, out

    def _row_at(self, y: float) -> int | None:
        i = int(math.floor((y - self.HEAD) / self.ROW))
        return i if 0 <= i < len(self.rows) and y >= self.HEAD else None

    def mouseMoveEvent(self, event):
        i = self._row_at(event.position().y())
        if i != self._hover:
            self._hover = i
            self.update()
        if i is None:
            QToolTip.hideText()
            return
        label, _dot, parts, base = self.rows[i]
        lines = [label]
        for key, lab, _c in self.categories:
            if parts.get(key):
                lines.append(f"{lab}: {self.fmt(parts[key])}")
        lines.append(f"Total: {self.fmt(sum(parts.values()))}")
        if base is not None:
            lines.append(f"Case study: {self.fmt(base)}")
        QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        p.setFont(_font(ui.TEXT_BASE, QFont.DemiBold))
        p.setPen(QColor(INK))
        p.drawText(QRectF(8, 4, w - 16, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        if self.note and self.rows:
            p.setFont(_font(ui.TEXT_SM))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(8, 4, w - 16, 20), Qt.AlignRight | Qt.AlignVCenter, self.note)
        used = {k for _l, _c, parts, _b in self.rows for k, v in parts.items() if v}
        _legend(p, 8.0, 26.0, [(label, color) for key, label, color in self.categories if key in used],
                w - 8.0)
        if not self.rows:
            p.setFont(_font(ui.TEXT_SM))
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(8, self.HEAD, w - 16, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       self.note or "Nothing to show for this case.")
            p.end()
            return

        pos_ext = max([sum(v for v in parts.values() if v > 0) for _l, _c, parts, _b in self.rows]
                      + [b for *_x, b in self.rows if b is not None and b > 0] + [0.0])
        neg_ext = -min([sum(v for v in parts.values() if v < 0) for _l, _c, parts, _b in self.rows]
                       + [b for *_x, b in self.rows if b is not None and b < 0] + [0.0])
        span = pos_ext + neg_ext or 1.0
        left = self.LABEL_W
        right = w - self.VALUE_W
        area_w = max(right - left, 40.0)
        zero = left + area_w * neg_ext / span

        def X(v):
            return zero + area_w * v / span

        top = self.HEAD
        f_label = _font(ui.TEXT_SM)
        fm_label = QFontMetricsF(f_label)
        f_value = _font(ui.TEXT_SM, QFont.DemiBold)
        for i, (label, dot, parts, base) in enumerate(self.rows):
            y = top + i * self.ROW
            if i == self._hover:
                p.fillRect(QRectF(4, y, w - 8, self.ROW), QColor(ui.SURFACE_3))
            elif i % 2 == 0:
                p.fillRect(QRectF(4, y, w - 8, self.ROW), QColor(ui.SURFACE_2))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(dot))
            p.drawEllipse(QPointF(13, y + self.ROW / 2), 3.5, 3.5)
            p.setFont(f_label)
            p.setPen(QColor(INK))
            p.drawText(QRectF(22, y, left - 28, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       fm_label.elidedText(label, Qt.ElideRight, left - 30))
            bar_y = y + (self.ROW - self.BAR_H) / 2
            p.setPen(Qt.NoPen)
            colors = {key: color for key, _lab, color in self.categories}
            pos = [(k, parts[k]) for k, _l, _c in self.categories if parts.get(k, 0.0) > 0]
            neg = [(k, parts[k]) for k, _l, _c in self.categories if parts.get(k, 0.0) < 0]
            acc = 0.0
            for j, (key, v) in enumerate(pos):
                x0, x1 = X(acc), X(acc + v)
                acc += v
                last = j == len(pos) - 1
                width = max(x1 - x0 - (0.0 if last else GAP), 0.8)
                p.setBrush(QColor(colors[key]))
                p.drawPath(_bar(QRectF(x0, bar_y, width, self.BAR_H), False, last))
            acc = 0.0
            for j, (key, v) in enumerate(neg):
                x_right, x_left = X(acc), X(acc + v)
                acc += v
                last = j == len(neg) - 1
                edge = x_left + (0.0 if last else GAP)
                p.setBrush(QColor(colors[key]))
                p.drawPath(_bar(QRectF(edge, bar_y, max(x_right - edge, 0.8), self.BAR_H), last, False))
            total = sum(parts.values())
            if base is not None and abs(base - total) > 1e-9 * max(abs(base), 1.0):
                xb = X(base)
                p.setPen(QPen(QColor(AXIS), 1.0))
                p.drawLine(QPointF(X(total), y + self.ROW / 2), QPointF(xb, y + self.ROW / 2))
                p.setPen(QPen(QColor(DIM), 2.0, Qt.SolidLine, Qt.FlatCap))
                p.drawLine(QPointF(xb, bar_y - 3), QPointF(xb, bar_y + self.BAR_H + 3))
                p.setPen(Qt.NoPen)
            p.setFont(f_value)
            p.setPen(QColor(INK))
            p.drawText(QRectF(right + 6, y, self.VALUE_W - 12, self.ROW), Qt.AlignRight | Qt.AlignVCenter,
                       self.fmt(total))
            p.setPen(Qt.NoPen)
        p.setPen(QPen(QColor(AXIS), 1.0))
        p.drawLine(QPointF(zero, top - 2), QPointF(zero, top + len(self.rows) * self.ROW + 2))
        foot = top + len(self.rows) * self.ROW + 6
        p.setPen(QPen(QColor(DIM), 2.0, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(QPointF(left + 1, foot + 3), QPointF(left + 1, foot + 13))
        p.setFont(_font(ui.TEXT_XS))
        p.setPen(QColor(FAINT))
        p.drawText(QRectF(left + 8, foot, area_w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   f"case study, where it differs   ·   {self.unit}   ·   hover a row for the values")
        p.end()


# --------------------------------------------------------------------------- #
# Response of the headline figures to one variable
# --------------------------------------------------------------------------- #
class ResponseChart(QWidget):
    """Production cost and GWP across one variable's range, as two small plots
    over one shared input axis (two quantities, two value axes, never one plot
    with two scales)."""

    LEFT = 50.0
    RIGHT = 14.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.var: P.Variable | None = None
        self.points: list = []
        self.x_now = self.x_base = None
        self.message = "Hover a variable in the inspector, or click its name, to see how the " \
                       "headline figures respond to it."
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def clear(self, message: str = ""):
        self.var, self.points = None, []
        if message:
            self.message = message
        self.update()

    def set_curve(self, var: P.Variable, points, x_now: float, x_base: float | None):
        self.var, self.points = var, list(points)
        self.x_now, self.x_base = x_now, x_base
        self._hover = None
        self.update()

    def _plots(self) -> tuple[QRectF, QRectF]:
        """The cost plot and the GWP plot, stacked, sharing the input axis."""
        w, h = self.width(), self.height()
        width = max(w - self.LEFT - self.RIGHT, 40.0)
        # a caption above each plot 18, a gap 6, the ticks and the input's name 32
        free = max(h - 18 - 18 - 6 - 32, 60.0)
        ph = free / 2.0
        top1 = 18.0
        top2 = top1 + ph + 6 + 18
        return (QRectF(self.LEFT, top1, width, ph), QRectF(self.LEFT, top2, width, ph))

    def _x_map(self, plot: QRectF):
        xs = [x * self.var.factor for x, _c, _g in self.points]
        lo, hi = min(xs), max(xs)
        log = self.var.log and lo > 0
        if log:
            a = math.log10(lo)
            b = math.log10(hi) if hi > lo else a + 1.0

            def X(v):
                v = max(v, 1e-300)
                return plot.left() + plot.width() * (math.log10(v) - a) / ((b - a) or 1.0)
        else:
            span = (hi - lo) or 1.0

            def X(v):
                return plot.left() + plot.width() * (v - lo) / span
        return X, lo, hi, log

    def mouseMoveEvent(self, event):
        if not self.points or self.var is None:
            return
        plot, _ = self._plots()
        X, *_ = self._x_map(plot)
        px = event.position().x()
        best = min(range(len(self.points)), key=lambda i: abs(X(self.points[i][0] * self.var.factor) - px))
        if best != self._hover:
            self._hover = best
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    @staticmethod
    def _frame(vals):
        lo, hi = min(vals), max(vals)
        # a flat response stays flat on the chart instead of magnifying rounding noise
        mid = (lo + hi) / 2.0
        half = max((hi - lo) / 2.0 * 1.08, abs(mid) * 0.02, 1e-9)
        return mid - half, mid + half

    def _y_axis(self, p: QPainter, plot: QRectF, lo: float, hi: float, log: bool):
        """Gridlines and tick labels of one plot; returns its value -> y map."""
        if log:
            def Y(v):
                return plot.bottom() - plot.height() * (math.log10(max(v, 1e-300)) - lo) / (hi - lo)
            ticks = []
            for d in range(math.floor(lo), math.ceil(hi) + 1):
                for m in (1, 2, 5):
                    val = m * 10 ** d
                    if lo <= math.log10(val) <= hi:
                        ticks.append(val)
        else:
            def Y(v):
                return plot.bottom() - plot.height() * (v - lo) / (hi - lo)
            step = _nice_step(hi - lo, 3)
            v = math.ceil(lo / step) * step
            ticks = []
            while v <= hi + 1e-12:
                ticks.append(v)
                v += step
        p.setFont(_font(ui.TEXT_XS))
        for v in ticks:
            y = Y(v)
            p.setPen(QPen(QColor(GRIDC), 1.0))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(0, y - 8, plot.left() - 6, 16), Qt.AlignRight | Qt.AlignVCenter, _fmt_axis(v))
        p.setPen(QPen(QColor(AXIS), 1.0))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
        return Y

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if self.var is None or len(self.points) < 2:
            p.setFont(_font(ui.TEXT_SM))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(12, 8, w - 24, h - 16), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            p.end()
            return
        var = self.var
        cost_plot, gwp_plot = self._plots()
        X, xlo, xhi, log = self._x_map(cost_plot)
        costs = [c for _x, c, _g in self.points]
        gwps = [g for _x, _c, g in self.points]
        xs = [x * var.factor for x, _c, _g in self.points]

        # cost spanning orders of magnitude (plant size, productivity): log axis
        ylog = min(costs) > 0 and max(costs) / min(costs) > 20
        if ylog:
            clo, chi = math.log10(min(costs)) - 0.05, math.log10(max(costs)) + 0.05
        else:
            clo, chi = self._frame(costs)
        glo, ghi = self._frame(gwps)

        for plot, caption, color in ((cost_plot, "Production cost, €/kg", COST_C),
                                     (gwp_plot, "GWP, kg CO₂-eq/kg", GWP_C)):
            cy = plot.top() - 18
            p.setPen(QPen(QColor(color), 2.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(4, cy + 9), QPointF(16, cy + 9))
            p.setFont(_font(ui.TEXT_SM))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(22, cy, w - 26, 18), Qt.AlignLeft | Qt.AlignVCenter, caption)
        Yc = self._y_axis(p, cost_plot, clo, chi, ylog)
        Yg = self._y_axis(p, gwp_plot, glo, ghi, False)

        # input axis: ticks under the lower plot, gridlines through both
        if log:
            d0, d1 = math.floor(math.log10(xlo)), math.ceil(math.log10(xhi))
            ticks = [10 ** d for d in range(d0, d1 + 1) if xlo <= 10 ** d <= xhi]
            if len(ticks) < 2:
                ticks = [xlo, xhi]
        else:
            st = _nice_step(xhi - xlo, 4)
            t0 = math.ceil(xlo / st) * st
            ticks = []
            while t0 <= xhi + 1e-12:
                ticks.append(t0)
                t0 += st
        f_tick = _font(ui.TEXT_XS)
        fm_tick = QFontMetricsF(f_tick)
        p.setFont(f_tick)
        for t in ticks:
            x = X(t)
            p.setPen(QPen(QColor(GRIDC), 1.0))
            for plot in (cost_plot, gwp_plot):
                p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            label = _fmt_axis(t)
            half = fm_tick.horizontalAdvance(label) / 2 + 1
            cx = min(max(x, half), w - half)       # the last label stays inside the widget
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(cx - half, gwp_plot.bottom() + 2, 2 * half, 15), Qt.AlignCenter, label)
        p.setFont(_font(ui.TEXT_SM))
        p.setPen(QColor(DIM))
        p.drawText(QRectF(gwp_plot.left(), gwp_plot.bottom() + 16, gwp_plot.width(), 16), Qt.AlignCenter,
                   f"{var.label} [{var.unit}]" if var.unit else var.label)

        def interp(xv, vals):
            for (x1, y1), (x2, y2) in zip(zip(xs, vals), zip(xs[1:], vals[1:])):
                if x1 <= xv <= x2 or x2 <= xv <= x1:
                    k = (xv - x1) / ((x2 - x1) or 1.0)
                    return y1 + k * (y2 - y1)
            return None

        for plot, vals, Y, color in ((cost_plot, costs, Yc, COST_C), (gwp_plot, gwps, Yg, GWP_C)):
            p.save()
            p.setClipRect(plot.adjusted(-2, -4, 2, 4))
            path = QPainterPath(QPointF(X(xs[0]), Y(vals[0])))
            for xv, yv in zip(xs[1:], vals[1:]):
                path.lineTo(QPointF(X(xv), Y(yv)))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(color), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            if self.x_base is not None and xlo <= self.x_base * var.factor <= xhi:
                xb = X(self.x_base * var.factor)
                p.setPen(QPen(QColor(AXIS), 1.0))
                p.drawLine(QPointF(xb, plot.top()), QPointF(xb, plot.bottom()))
            if self.x_now is not None and xlo <= self.x_now * var.factor <= xhi:
                xn = self.x_now * var.factor
                p.setPen(QPen(QColor(DIM), 1.0))
                p.drawLine(QPointF(X(xn), plot.top()), QPointF(X(xn), plot.bottom()))
                yv = interp(xn, vals)
                if yv is not None:
                    p.setPen(QPen(QColor(ui.SURFACE), 2.0))
                    p.setBrush(QColor(color))
                    p.drawEllipse(QPointF(X(xn), Y(yv)), 4.5, 4.5)
            p.restore()
        if self.x_base is not None and xlo <= self.x_base * var.factor <= xhi:
            f_case = _font(ui.TEXT_XS)
            p.setFont(f_case)
            xb = X(self.x_base * var.factor)
            box = QRectF(xb + 3, cost_plot.top() + 1,
                         QFontMetricsF(f_case).horizontalAdvance("case study") + 6, 15)
            if box.right() > cost_plot.right():
                box.moveRight(xb - 3)
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(ui.SURFACE, 230))
            p.drawRect(box)
            p.setPen(QColor(FAINT))
            p.drawText(box, Qt.AlignCenter, "case study")

        if self._hover is not None:
            x, c, g = self.points[self._hover]
            xh = X(x * var.factor)
            p.setPen(QPen(QColor(FAINT), 1.0))
            for plot in (cost_plot, gwp_plot):
                p.drawLine(QPointF(xh, plot.top()), QPointF(xh, plot.bottom()))
            lines = [(f"{P.fmt_value(x * var.factor, var.decimals)} {var.unit}".strip(), None),
                     (f"{c:,.2f} €/kg", COST_C), (f"{_sig(g)} kg CO₂-eq/kg", GWP_C)]
            p.setFont(_font(ui.TEXT_SM, QFont.DemiBold))
            fm = QFontMetricsF(p.font())
            bw = max(fm.horizontalAdvance(t) for t, _c in lines) + 30
            bx = xh + 10 if xh + 10 + bw < cost_plot.right() else xh - 10 - bw
            box = QRectF(bx, cost_plot.top() + 4, bw, 3 * 17 + 8)
            p.setPen(QPen(QColor(LINE), 1.0))
            p.setBrush(_alpha(ui.SURFACE, 245))
            p.drawRoundedRect(box, ui.RADIUS, ui.RADIUS)
            for i, (t, col) in enumerate(lines):
                yy = box.top() + 4 + i * 17
                if col is not None:
                    p.setPen(QPen(QColor(col), 2.0, Qt.SolidLine, Qt.RoundCap))
                    p.drawLine(QPointF(box.left() + 8, yy + 8.5), QPointF(box.left() + 18, yy + 8.5))
                p.setPen(QColor(INK))
                p.drawText(QRectF(box.left() + 24, yy, bw - 28, 17), Qt.AlignLeft | Qt.AlignVCenter, t)
        p.end()


# --------------------------------------------------------------------------- #
# Tornado: which inputs move the cost most
# --------------------------------------------------------------------------- #
class TornadoChart(QWidget):
    ROW = 26.0
    HEAD = 52.0
    LABEL_W = 240.0
    BAR_H = 12.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []
        self.c0 = 0.0
        self.swing = 0.2
        self.message = "Computing…"
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, rows, c0: float, swing: float):
        """``rows``: [(label, cost_at_low_input, cost_at_high_input)], largest first."""
        self.rows, self.c0, self.swing = list(rows), c0, swing
        self._hover = None
        self.setMinimumHeight(int(self.HEAD + self.ROW * max(len(self.rows), 1) + 24))
        self.updateGeometry()
        self.update()

    def set_message(self, text: str):
        self.rows = []
        self.message = text
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(560, int(self.HEAD + self.ROW * max(len(self.rows), 1) + 24))

    def table(self) -> tuple[list[str], list[list[str]]]:
        pct = f"{self.swing * 100:,.0f} %"
        headers = ["Input", f"Cost at −{pct}, €/kg", f"Cost at +{pct}, €/kg", "Largest change"]
        out = []
        for label, lo, hi in self.rows:
            d = max(abs(lo - self.c0), abs(hi - self.c0)) / (abs(self.c0) or 1.0) * 100
            out.append([label, f"{lo:,.2f}", f"{hi:,.2f}", f"±{d:,.1f} %"])
        return headers, out

    def _row_at(self, y: float) -> int | None:
        i = int(math.floor((y - self.HEAD) / self.ROW))
        return i if 0 <= i < len(self.rows) and y >= self.HEAD else None

    def mouseMoveEvent(self, event):
        i = self._row_at(event.position().y())
        if i != self._hover:
            self._hover = i
            self.update()
        if i is None:
            QToolTip.hideText()
            return
        label, lo, hi = self.rows[i]
        pct = f"{self.swing * 100:,.0f} %"
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"{label}\nInput −{pct}: {lo:,.2f} €/kg\nInput +{pct}: {hi:,.2f} €/kg\n"
                          f"Case point: {self.c0:,.2f} €/kg", self)

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        pct = f"{self.swing * 100:,.0f} %"
        p.setFont(_font(ui.TEXT_BASE, QFont.DemiBold))
        p.setPen(QColor(INK))
        p.drawText(QRectF(8, 4, w - 16, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"Production cost when each input moves by ±{pct}")
        p.setFont(_font(ui.TEXT_SM))
        p.setPen(QColor(DIM))
        p.drawText(QRectF(8, 26, w - 16, 18), Qt.AlignRight | Qt.AlignVCenter,
                   f"case point {self.c0:,.2f} €/kg")
        _legend(p, 8.0, 26.0, [(f"input −{pct}", LOW_C), (f"input +{pct}", HIGH_C)], w - 160.0)
        if not self.rows:
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(8, self.HEAD, w - 16, 22), Qt.AlignLeft | Qt.AlignVCenter, self.message)
            p.end()
            return
        ext = max(max(abs(lo - self.c0), abs(hi - self.c0)) for _l, lo, hi in self.rows) or 1.0
        left, right = self.LABEL_W, w - 76
        mid = (left + right) / 2.0
        half = (right - left) / 2.0

        def X(v):
            return mid + half * (v - self.c0) / ext

        f_label = _font(ui.TEXT_SM)
        fm = QFontMetricsF(f_label)
        f_value = _font(ui.TEXT_SM, QFont.DemiBold)
        for i, (label, lo, hi) in enumerate(self.rows):
            y = self.HEAD + i * self.ROW
            if i == self._hover:
                p.fillRect(QRectF(4, y, w - 8, self.ROW), QColor(ui.SURFACE_3))
            elif i % 2 == 0:
                p.fillRect(QRectF(4, y, w - 8, self.ROW), QColor(ui.SURFACE_2))
            p.setFont(f_label)
            p.setPen(QColor(INK))
            p.drawText(QRectF(10, y, left - 16, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(label, Qt.ElideRight, left - 18))
            bar_y = y + (self.ROW - self.BAR_H) / 2
            # the longer bar first, so a shorter one on the same side stays visible
            for v, col in sorted(((lo, LOW_C), (hi, HIGH_C)), key=lambda vc: -abs(vc[0] - self.c0)):
                xv = X(v)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(col))
                if xv >= mid:
                    p.drawPath(_bar(QRectF(mid, bar_y, max(xv - mid, 0.8), self.BAR_H), False, True))
                else:
                    p.drawPath(_bar(QRectF(xv, bar_y, max(mid - xv, 0.8), self.BAR_H), True, False))
            d = max(abs(lo - self.c0), abs(hi - self.c0)) / (abs(self.c0) or 1.0) * 100
            p.setFont(f_value)
            p.setPen(QColor(DIM))
            p.drawText(QRectF(right + 6, y, 68, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, f"±{d:,.1f} %")
        p.setPen(QPen(QColor(DIM), 1.0))
        p.drawLine(QPointF(mid, self.HEAD - 2), QPointF(mid, self.HEAD + len(self.rows) * self.ROW + 2))
        p.end()


# --------------------------------------------------------------------------- #
# Share meter (inspector)
# --------------------------------------------------------------------------- #
class Meter(QWidget):
    """``label ........ value  share`` over a thin bar showing a share of the plant.

    The track is a light tint of the fill's own hue. A negative share (a GWP
    credit) is drawn in the credit colour whatever the meter's colour."""

    def __init__(self, label: str, color: str = ui.CHART_PRIMARY, parent=None):
        super().__init__(parent)
        self.label, self.color = label, color
        self.value_text = ""
        self.share = 0.0
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, text: str, share: float | None):
        self.value_text = text
        self.share = 0.0 if share is None else max(-1.0, min(1.0, share))
        self.setToolTip(f"{self.label}: {text}" + (f", {_share(self.share)} of the plant"
                                                    if self.share else ""))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        f_label = _font(ui.TEXT_SM)
        p.setFont(f_label)
        p.setPen(QColor(DIM))
        p.drawText(QRectF(0, 0, w * 0.5, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(f_label).elidedText(self.label, Qt.ElideRight, w * 0.5))
        share_txt = _share(self.share) if self.share else ""
        f_share = _font(ui.TEXT_SM)
        share_w = QFontMetricsF(f_share).horizontalAdvance(share_txt) if share_txt else 0.0
        if share_txt:
            p.setFont(f_share)
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(w - share_w - 1, 0, share_w + 1, 18), Qt.AlignRight | Qt.AlignVCenter, share_txt)
        p.setFont(_font(ui.TEXT_SM, QFont.DemiBold))
        p.setPen(QColor(INK))
        p.drawText(QRectF(w * 0.3, 0, w * 0.7 - share_w - (10 if share_txt else 0), 18),
                   Qt.AlignRight | Qt.AlignVCenter, self.value_text)
        hue = QColor(self.color if self.share >= 0 else ui.CREDIT)
        track = QRectF(0, 22, w, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(_alpha(hue, 46))
        p.drawRoundedRect(track, 3, 3)
        if self.share:
            p.setBrush(hue)
            p.drawRoundedRect(QRectF(0, 22, max(w * abs(self.share), 3.0), 6), 3, 3)
        p.end()
