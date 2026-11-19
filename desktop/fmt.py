"""Number formatting for the screens and the report.

The rule is to show no more precision than the model has. The engine is a
screening model fed with literature-typical inputs, so a derived quantity is
shown to three significant figures unless a caller has a reason to fix the
decimals (a price to the cent, a payback to a tenth of a year). Qt-free, so the
PDF report uses the same functions.
"""

from __future__ import annotations

import math

#: What an unavailable number looks like, everywhere.
DASH = "—"


def sig(value, figures: int = 3) -> str:
    """``value`` to ``figures`` significant figures, with thousands separators.

    Trailing zeros after the decimal point are dropped, integers stay integers,
    and anything that is not a finite number comes back as a dash.
    """
    if value is None:
        return DASH
    try:
        x = float(value)
    except (TypeError, ValueError):
        return DASH
    if math.isnan(x):
        return DASH
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    if x == 0:
        return "0"
    magnitude = math.floor(math.log10(abs(x)))
    decimals = max(figures - 1 - magnitude, 0)
    rounded = round(x, decimals)
    if decimals == 0:
        return f"{rounded:,.0f}"
    text = f"{rounded:,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fixed(value, decimals: int = 2) -> str:
    """``value`` with a fixed number of decimals, or a dash."""
    if value is None:
        return DASH
    try:
        x = float(value)
    except (TypeError, ValueError):
        return DASH
    if math.isnan(x):
        return DASH
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    return f"{x:,.{decimals}f}"


def money(value) -> str:
    """An amount in euro, compacted to k or M with the precision that is left."""
    if value is None:
        return DASH
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        return DASH
    if abs(v) >= 1e6:
        return f"€ {v / 1e6:,.2f} M"
    if abs(v) >= 1e3:
        return f"€ {v / 1e3:,.1f} k"
    return f"€ {v:,.0f}"


def pct(value, decimals: int = 1) -> str:
    """A fraction as a percentage string."""
    if value is None:
        return DASH
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        return DASH
    return f"{v * 100:,.{decimals}f}%"


def compact(value) -> str:
    """A plain number compacted for an axis or a tile: 1,284 / 12.9k / 4.2M."""
    if value is None:
        return DASH
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        return DASH
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:,.1f}G"
    if a >= 1e6:
        return f"{v / 1e6:,.1f}M"
    if a >= 1e4:
        return f"{v / 1e3:,.1f}k"
    return sig(v, 3)


def with_unit(text: str, unit: str) -> str:
    """Join a formatted number and its unit with a thin space."""
    unit = (unit or "").strip()
    return f"{text} {unit}" if unit else text
