"""Small painted charts for the Process Designer panels.

Each one is a plain ``QWidget`` with a ``paintEvent``: cheap enough to redraw on
every slider tick, sized by its layout, and free of a plotting library. They use
the light palette of the side panels whatever the canvas theme.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import process as P

INK = "#0f172a"
DIM = "#64748b"
FAINT = "#94a3b8"
LINE = "#e2e8f0"
GRIDC = "#eef2f6"
GOOD = "#15803d"
BAD = "#c2410c"
ACCENT = "#1565c0"
GWP_C = "#7c3aed"
LOW_C = "#2563eb"
HIGH_C = "#ea580c"


def _font(size: float, weight=QFont.Normal, family: str = "Segoe UI") -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
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


# --------------------------------------------------------------------------- #
# KPI tile
# --------------------------------------------------------------------------- #
class KpiTile(QWidget):
    """Headline figure with its change against the case study and a sparkline of
    the values it took over the editing session."""

    H = 74

    def __init__(self, kpi: P.KPI, parent=None):
        super().__init__(parent)
        self.kpi = kpi
        self._value: float | None = None
        self._base: float | None = None
        self._hist: list[float] = []
        self._note = ""
        self.setMinimumWidth(118)
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
        self.update()

    def _delta(self) -> float | None:
        if self._value is None or self._base is None:
            return None
        if abs(self._base) < 1e-12:
            return None if abs(self._value) < 1e-12 else math.copysign(1.0, self._value)
        return (self._value - self._base) / abs(self._base)

    def _refresh_tip(self):
        k = self.kpi
        if self._value is None:
            return
        tip = f"{k.label}: {P.fmt_value(self._value, k.decimals)} {k.unit}"
        if self._base is not None:
            tip += f"\nCase study: {P.fmt_value(self._base, k.decimals)} {k.unit}"
        self.setToolTip(tip)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        k = self.kpi
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        d = self._delta()
        state = "same"
        if d is not None and abs(d) >= 5e-4:
            better = (d < 0) if k.lower_is_better else (d > 0)
            state = "good" if better else "bad"
        accent = {"good": GOOD, "bad": BAD}.get(state, "#cbd5e1")
        p.setPen(QPen(QColor(LINE), 1.0))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawRoundedRect(r, 8, 8)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), 3, r.height()), QColor(accent))
        p.restore()

        p.setFont(_font(6.8, QFont.Bold))
        p.setPen(QColor(DIM))
        p.drawText(QRectF(12, 6, r.width() - 18, 13), Qt.AlignLeft | Qt.AlignVCenter, k.label.upper())

        if self._value is None:
            p.setFont(_font(13, QFont.Bold))
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(12, 20, r.width() - 18, 24), Qt.AlignLeft | Qt.AlignVCenter, "—")
            p.setFont(_font(7))
            p.drawText(QRectF(12, 46, r.width() - 18, 14), Qt.AlignLeft | Qt.AlignVCenter, self._note)
            p.end()
            return

        f_val = _font(13.5, QFont.Bold)
        text = P.fmt_value(self._value, k.decimals)
        p.setFont(f_val)
        p.setPen(QColor(INK))
        vw = QFontMetricsF(f_val).horizontalAdvance(text)
        p.drawText(QRectF(12, 19, vw + 4, 26), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.setFont(_font(7.5))
        p.setPen(QColor(DIM))
        p.drawText(QRectF(16 + vw, 23, r.width() - vw - 20, 20), Qt.AlignLeft | Qt.AlignVCenter, k.unit)

        # change against the case study
        p.setFont(_font(7, QFont.DemiBold))
        if d is None or state == "same":
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(12, 47, 90, 14), Qt.AlignLeft | Qt.AlignVCenter, "= case study")
        else:
            arrow = "▲" if d > 0 else "▼"
            txt = f"{arrow} {abs(d) * 100:,.1f} %" if abs(d) < 10 else f"{arrow} ×{1 + d:,.1f}"
            fm = QFontMetricsF(p.font())
            w = fm.horizontalAdvance(txt) + 10
            pill = QRectF(11, 47, w, 15)
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(accent, 30))
            p.drawRoundedRect(pill, 7, 7)
            p.setPen(QColor(accent))
            p.drawText(pill, Qt.AlignCenter, txt)

        # sparkline of the session
        hist = self._hist[-40:]
        box = QRectF(r.width() * 0.52, 48, r.width() * 0.48 - 10, 16)
        if len(hist) >= 2 and box.width() > 20:
            lo, hi = min(hist + [self._base or hist[0]]), max(hist + [self._base or hist[0]])
            span = hi - lo or 1.0

            def pt(i, v):
                return QPointF(box.left() + box.width() * i / (len(hist) - 1),
                               box.bottom() - box.height() * (v - lo) / span)

            if self._base is not None:
                yb = box.bottom() - box.height() * (self._base - lo) / span
                pen = QPen(QColor(FAINT), 0.8, Qt.DashLine)
                p.setPen(pen)
                p.drawLine(QPointF(box.left(), yb), QPointF(box.right(), yb))
            line = QPainterPath(pt(0, hist[0]))
            for i, v in enumerate(hist[1:], 1):
                line.lineTo(pt(i, v))
            p.setPen(QPen(QColor(ACCENT), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPath(line)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(accent if state != "same" else ACCENT))
            p.drawEllipse(pt(len(hist) - 1, hist[-1]), 2.4, 2.4)
        p.end()


# --------------------------------------------------------------------------- #
# Stacked horizontal bars
# --------------------------------------------------------------------------- #
class StackedBars(QWidget):
    """One bar per row, stacked by category; negative parts grow to the left of
    zero. A thin outline marks each row's total in the case study."""

    ROW = 21.0
    HEAD = 40.0
    LABEL_W = 156.0
    VALUE_W = 92.0

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.rows: list = []
        self.categories: list = []
        self.unit = ""
        self.fmt = _fmt_axis
        self.note = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, rows, categories, unit: str = "", fmt=None, note: str = ""):
        """``rows``: [(label, dot_colour, {category: value}, baseline_total | None)].
        ``categories``: [(key, label, colour)] in stacking order."""
        self.rows = list(rows)
        self.categories = list(categories)
        self.unit = unit
        self.fmt = fmt or _fmt_axis
        self.note = note
        self.setMinimumHeight(int(self.HEAD + self.ROW * max(len(self.rows), 1) + 26))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(560, int(self.HEAD + self.ROW * max(len(self.rows), 1) + 26))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        p.setFont(_font(8.5, QFont.Bold))
        p.setPen(QColor(INK))
        p.drawText(QRectF(8, 4, w - 16, 16), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        if self.note and self.rows:
            p.setFont(_font(7))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(8, 4, w - 16, 16), Qt.AlignRight | Qt.AlignVCenter, self.note)
        used = {k for _l, _c, parts, _b in self.rows for k, v in parts.items() if v}
        x = 8.0
        p.setFont(_font(7))
        for key, label, color in self.categories:
            if key not in used:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, 25, 9, 9), 2, 2)
            tw = QFontMetricsF(p.font()).horizontalAdvance(label)
            p.setPen(QColor(DIM))
            p.drawText(QRectF(x + 12, 21, tw + 4, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += tw + 26
        if not self.rows:
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(8, self.HEAD, w - 16, 20), Qt.AlignLeft | Qt.AlignVCenter,
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
        for i, (label, dot, parts, base) in enumerate(self.rows):
            y = top + i * self.ROW
            if i % 2 == 0:
                p.fillRect(QRectF(4, y, w - 8, self.ROW), QColor("#f8fafc"))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(dot))
            p.drawEllipse(QPointF(12, y + self.ROW / 2), 3.2, 3.2)
            p.setFont(_font(7.8))
            p.setPen(QColor(INK))
            fm = QFontMetricsF(p.font())
            p.drawText(QRectF(20, y, left - 26, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(label, Qt.ElideRight, left - 28))
            bar_y, bar_h = y + 4.5, self.ROW - 9
            xp, xn = 0.0, 0.0
            for key, _lab, color in self.categories:
                v = parts.get(key, 0.0)
                if not v:
                    continue
                if v > 0:
                    rect = QRectF(X(xp), bar_y, X(xp + v) - X(xp), bar_h)
                    xp += v
                else:
                    rect = QRectF(X(xn + v), bar_y, X(xn) - X(xn + v), bar_h)
                    xn += v
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color))
                p.drawRect(rect.adjusted(0, 0, -0.6 if rect.width() > 2 else 0, 0))
            total = sum(parts.values())
            if base is not None and abs(base - total) > 1e-9 * max(abs(base), 1.0):
                xb = X(base)
                p.setPen(QPen(QColor(INK), 1.2))
                p.drawLine(QPointF(xb, bar_y - 2.5), QPointF(xb, bar_y + bar_h + 2.5))
                p.setPen(QPen(QColor(FAINT), 1.0, Qt.DotLine))
                p.drawLine(QPointF(X(total), y + self.ROW / 2), QPointF(xb, y + self.ROW / 2))
            p.setFont(_font(7.8, QFont.DemiBold))
            p.setPen(QColor(INK))
            p.drawText(QRectF(right + 6, y, self.VALUE_W - 10, self.ROW), Qt.AlignRight | Qt.AlignVCenter,
                       self.fmt(total))
        p.setPen(QPen(QColor(FAINT), 1.0))
        p.drawLine(QPointF(zero, top - 2), QPointF(zero, top + len(self.rows) * self.ROW + 2))
        p.setFont(_font(6.8))
        p.setPen(QColor(DIM))
        foot = top + len(self.rows) * self.ROW + 4
        p.drawText(QRectF(left, foot, area_w, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   f"│ marks the case study   ·   {self.unit}")
        p.end()


# --------------------------------------------------------------------------- #
# Response of the headline figures to one variable
# --------------------------------------------------------------------------- #
class ResponseChart(QWidget):
    """Production cost (solid) and GWP (dashed) across one variable's range."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.var: P.Variable | None = None
        self.points: list = []
        self.x_now = self.x_base = None
        self.message = "Hover a variable in the inspector, or click its name, to see how the " \
                       "headline figures respond to it."
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
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

    def _plot_rect(self) -> QRectF:
        return QRectF(52, 30, max(self.width() - 108, 40), max(self.height() - 62, 40))

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
        if not self.points:
            return
        plot = self._plot_rect()
        X, *_ = self._x_map(plot)
        px = event.position().x()
        best = min(range(len(self.points)), key=lambda i: abs(X(self.points[i][0] * self.var.factor) - px))
        if best != self._hover:
            self._hover = best
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if self.var is None or len(self.points) < 2:
            p.setFont(_font(8))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(12, 8, w - 24, h - 16), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            p.end()
            return
        var = self.var
        plot = self._plot_rect()
        X, xlo, xhi, log = self._x_map(plot)
        costs = [c for _x, c, _g in self.points]
        gwps = [g for _x, _c, g in self.points]

        def frame(vals):
            lo, hi = min(vals), max(vals)
            # a flat response stays flat on the chart instead of magnifying rounding noise
            mid = (lo + hi) / 2.0
            half = max((hi - lo) / 2.0 * 1.08, abs(mid) * 0.02, 1e-9)
            return mid - half, mid + half

        clo, chi = frame(costs)
        glo, ghi = frame(gwps)
        # cost spanning orders of magnitude (plant size, productivity): log axis
        ylog = min(costs) > 0 and max(costs) / min(costs) > 20
        if ylog:
            clo, chi = math.log10(min(costs)) - 0.05, math.log10(max(costs)) + 0.05

        def Yc(v):
            if ylog:
                v = math.log10(max(v, 1e-300))
            return plot.bottom() - plot.height() * (v - clo) / (chi - clo)

        def Yg(v):
            return plot.bottom() - plot.height() * (v - glo) / (ghi - glo)

        p.setFont(_font(8.5, QFont.Bold))
        p.setPen(QColor(INK))
        p.drawText(QRectF(10, 4, w - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, var.label)
        p.setFont(_font(7))
        legend = "━ production cost €/kg     ┅ GWP kg CO₂-eq/kg"
        p.setPen(QColor(DIM))
        p.drawText(QRectF(10, 4, w - 20, 18), Qt.AlignRight | Qt.AlignVCenter, legend)

        # grid and y ticks
        p.setFont(_font(6.8))
        if ylog:
            yticks = []
            for d in range(math.floor(clo), math.ceil(chi) + 1):
                for m in (1, 2, 5):
                    val = m * 10 ** d
                    if clo <= math.log10(val) <= chi:
                        yticks.append(val)
        else:
            step = _nice_step(chi - clo)
            v = math.ceil(clo / step) * step
            yticks = []
            while v <= chi + 1e-12:
                yticks.append(v)
                v += step
        for v in yticks:
            y = Yc(v)
            p.setPen(QPen(QColor(GRIDC), 1.0))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(ACCENT))
            p.drawText(QRectF(2, y - 7, plot.left() - 6, 14), Qt.AlignRight | Qt.AlignVCenter, _fmt_axis(v))
        gstep = _nice_step(ghi - glo)
        v = math.ceil(glo / gstep) * gstep
        p.setPen(QColor(GWP_C))
        while v <= ghi + 1e-12:
            y = Yg(v)
            p.drawText(QRectF(plot.right() + 5, y - 7, 50, 14), Qt.AlignLeft | Qt.AlignVCenter, _fmt_axis(v))
            v += gstep
        p.setPen(QPen(QColor("#cbd5e1"), 1.0))
        p.drawRect(plot)

        # x ticks
        p.setPen(QColor(DIM))
        if log:
            d0, d1 = math.floor(math.log10(xlo)), math.ceil(math.log10(xhi))
            ticks = [10 ** d for d in range(d0, d1 + 1) if xlo <= 10 ** d <= xhi]
            if len(ticks) < 2:
                ticks = [xlo, xhi]
        else:
            st = _nice_step(xhi - xlo, 5)
            t0 = math.ceil(xlo / st) * st
            ticks = []
            while t0 <= xhi + 1e-12:
                ticks.append(t0)
                t0 += st
        for t in ticks:
            x = X(t)
            p.setPen(QPen(QColor(GRIDC), 1.0))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(x - 30, plot.bottom() + 3, 60, 13), Qt.AlignCenter, _fmt_axis(t))
        p.drawText(QRectF(plot.left(), plot.bottom() + 15, plot.width(), 13), Qt.AlignCenter,
                   f"{var.label} [{var.unit}]" if var.unit else var.label)

        p.save()
        p.setClipRect(plot.adjusted(-2, -2, 2, 2))
        cost_path = QPainterPath(QPointF(X(self.points[0][0] * var.factor), Yc(costs[0])))
        gwp_path = QPainterPath(QPointF(X(self.points[0][0] * var.factor), Yg(gwps[0])))
        for x, c, g in self.points[1:]:
            cost_path.lineTo(QPointF(X(x * var.factor), Yc(c)))
            gwp_path.lineTo(QPointF(X(x * var.factor), Yg(g)))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(GWP_C), 1.6, Qt.DashLine))
        p.drawPath(gwp_path)
        p.setPen(QPen(QColor(ACCENT), 2.2))
        p.drawPath(cost_path)

        def interp(xv, idx):
            pts = [(x * var.factor, (c, g)[idx]) for x, c, g in self.points]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                if x1 <= xv <= x2 or x2 <= xv <= x1:
                    k = (xv - x1) / ((x2 - x1) or 1.0)
                    return y1 + k * (y2 - y1)
            return None

        if self.x_base is not None:
            xb = self.x_base * var.factor
            if xlo <= xb <= xhi:
                p.setPen(QPen(QColor(FAINT), 1.0, Qt.DashLine))
                p.drawLine(QPointF(X(xb), plot.top()), QPointF(X(xb), plot.bottom()))
                p.setFont(_font(6.5, QFont.Bold))
                p.drawText(QRectF(X(xb) - 30, plot.top() + 2, 60, 12), Qt.AlignCenter, "case")
        if self.x_now is not None:
            xn = self.x_now * var.factor
            if xlo <= xn <= xhi:
                p.setPen(QPen(QColor(GOOD), 1.2))
                p.drawLine(QPointF(X(xn), plot.top()), QPointF(X(xn), plot.bottom()))
                for idx, Y, col in ((0, Yc, ACCENT), (1, Yg, GWP_C)):
                    yv = interp(xn, idx)
                    if yv is not None:
                        p.setPen(QPen(QColor("#ffffff"), 1.5))
                        p.setBrush(QColor(col))
                        p.drawEllipse(QPointF(X(xn), Y(yv)), 4.2, 4.2)
        p.restore()

        if self._hover is not None:
            x, c, g = self.points[self._hover]
            xs = X(x * var.factor)
            p.setPen(QPen(QColor(INK), 0.8, Qt.DotLine))
            p.drawLine(QPointF(xs, plot.top()), QPointF(xs, plot.bottom()))
            lines = [f"{P.fmt_value(x * var.factor, var.decimals)} {var.unit}",
                     f"{c:,.3f} €/kg", f"{g:,.3f} kg CO₂-eq/kg"]
            p.setFont(_font(7.2, QFont.DemiBold))
            fm = QFontMetricsF(p.font())
            bw = max(fm.horizontalAdvance(t) for t in lines) + 14
            bx = xs + 8 if xs + 8 + bw < plot.right() else xs - 8 - bw
            box = QRectF(bx, plot.top() + 8, bw, 46)
            p.setPen(QPen(QColor(LINE), 1.0))
            p.setBrush(QColor(255, 255, 255, 240))
            p.drawRoundedRect(box, 5, 5)
            for i, (t, col) in enumerate(zip(lines, (INK, ACCENT, GWP_C))):
                p.setPen(QColor(col))
                p.drawText(QRectF(box.left() + 7, box.top() + 3 + i * 14, bw - 10, 14),
                           Qt.AlignLeft | Qt.AlignVCenter, t)
        p.end()


# --------------------------------------------------------------------------- #
# Tornado: which inputs move the cost most
# --------------------------------------------------------------------------- #
class TornadoChart(QWidget):
    ROW = 21.0
    HEAD = 40.0
    LABEL_W = 210.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []
        self.c0 = 0.0
        self.swing = 0.2
        self.message = "Computing…"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, rows, c0: float, swing: float):
        """``rows``: [(label, cost_at_low_input, cost_at_high_input)], largest first."""
        self.rows, self.c0, self.swing = list(rows), c0, swing
        self.setMinimumHeight(int(self.HEAD + self.ROW * max(len(self.rows), 1) + 24))
        self.updateGeometry()
        self.update()

    def set_message(self, text: str):
        self.rows = []
        self.message = text
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(560, int(self.HEAD + self.ROW * max(len(self.rows), 1) + 24))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        pct = f"{self.swing * 100:,.0f} %"
        p.setFont(_font(8.5, QFont.Bold))
        p.setPen(QColor(INK))
        p.drawText(QRectF(8, 4, w - 16, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   f"Production cost when each input moves by ±{pct}")
        p.setFont(_font(7))
        for i, (txt, col) in enumerate(((f"input −{pct}", LOW_C), (f"input +{pct}", HIGH_C))):
            x = 8 + i * 96
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x, 25, 9, 9), 2, 2)
            p.setPen(QColor(DIM))
            p.drawText(QRectF(x + 12, 21, 90, 16), Qt.AlignLeft | Qt.AlignVCenter, txt)
        p.drawText(QRectF(8, 21, w - 16, 16), Qt.AlignRight | Qt.AlignVCenter,
                   f"case point {self.c0:,.3f} €/kg")
        if not self.rows:
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(8, self.HEAD, w - 16, 20), Qt.AlignLeft | Qt.AlignVCenter, self.message)
            p.end()
            return
        ext = max(max(abs(lo - self.c0), abs(hi - self.c0)) for _l, lo, hi in self.rows) or 1.0
        left, right = self.LABEL_W, w - 70
        mid = (left + right) / 2.0
        half = (right - left) / 2.0

        def X(v):
            return mid + half * (v - self.c0) / ext

        for i, (label, lo, hi) in enumerate(self.rows):
            y = self.HEAD + i * self.ROW
            if i % 2 == 0:
                p.fillRect(QRectF(4, y, w - 8, self.ROW), QColor("#f8fafc"))
            p.setFont(_font(7.8))
            p.setPen(QColor(INK))
            fm = QFontMetricsF(p.font())
            p.drawText(QRectF(10, y, left - 16, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(label, Qt.ElideRight, left - 18))
            for v, col in ((lo, LOW_C), (hi, HIGH_C)):
                x0, x1 = sorted((mid, X(v)))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(col))
                p.drawRect(QRectF(x0, y + 4.5, max(x1 - x0, 0.8), self.ROW - 9))
            d = max(abs(lo - self.c0), abs(hi - self.c0)) / (abs(self.c0) or 1.0) * 100
            p.setFont(_font(7.2, QFont.DemiBold))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(right + 4, y, 64, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, f"±{d:,.1f} %")
        p.setPen(QPen(QColor(INK), 1.0))
        p.drawLine(QPointF(mid, self.HEAD - 2), QPointF(mid, self.HEAD + len(self.rows) * self.ROW + 2))
        p.end()


# --------------------------------------------------------------------------- #
# Share meter (inspector)
# --------------------------------------------------------------------------- #
class Meter(QWidget):
    """``label ........ value`` over a thin bar showing a share of the plant."""

    def __init__(self, label: str, color: str = ACCENT, parent=None):
        super().__init__(parent)
        self.label, self.color = label, color
        self.value_text = ""
        self.share = 0.0
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, text: str, share: float | None):
        self.value_text = text
        self.share = 0.0 if share is None else max(-1.0, min(1.0, share))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        p.setFont(_font(7.8))
        p.setPen(QColor(DIM))
        p.drawText(QRectF(0, 0, w * 0.55, 16), Qt.AlignLeft | Qt.AlignVCenter, self.label)
        p.setFont(_font(7.8, QFont.DemiBold))
        p.setPen(QColor(INK))
        txt = self.value_text
        if self.share:
            txt += f"   {self.share * 100:,.1f} %"
        p.drawText(QRectF(w * 0.35, 0, w * 0.65, 16), Qt.AlignRight | Qt.AlignVCenter, txt)
        track = QRectF(0, 19, w, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#eef2f6"))
        p.drawRoundedRect(track, 2.5, 2.5)
        if self.share:
            col = QColor(self.color if self.share > 0 else GOOD)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(0, 19, w * abs(self.share), 5), 2.5, 2.5)
        p.end()
