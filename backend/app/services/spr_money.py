"""The money on a supplier price request line: which currency, at what rate.

A request has one currency and rate for the whole quote, and a line may have
its own: one vendor quotes the chain in yuan and the shackles in rupiah, or
two lines were bought at different rates. A line with no currency of its own
follows the request's.
"""

from __future__ import annotations


def line_money(spr, line: dict) -> tuple[str, float | None]:
    """(currency, rupiah per unit) for this line. Rupiah's rate is 1; None
    means a foreign currency with no rate stated yet."""
    head = (getattr(spr, "currency", None) or "IDR").upper()
    head_rate = getattr(spr, "fx_rate", None)
    cur = ((line or {}).get("currency") or head).upper()
    if cur == "IDR":
        return "IDR", 1.0
    own = (line or {}).get("fx_rate")
    if (line or {}).get("currency") and own:
        return cur, float(own)
    if cur == head and head_rate:
        return cur, float(head_rate)
    return cur, None


def line_idr(spr, line: dict) -> float | None:
    """The line's quoted unit price in rupiah, or None (not quoted / no rate)."""
    if line.get("quoted_price") is None:
        return None
    _, rate = line_money(spr, line)
    return None if rate is None else float(line["quoted_price"]) * rate


def total_in(spr, lines: list[dict], currency: str | None = None) -> float | None:
    """What these lines come to (quoted price × qty) in `currency` — the
    request's own by default. Lines in another currency are converted through
    rupiah. None when a line isn't quoted or a rate needed is missing."""
    want = (currency or getattr(spr, "currency", None) or "IDR").upper()
    if not lines or any(l.get("quoted_price") is None for l in lines):
        return None
    same = all(line_money(spr, l)[0] == want for l in lines)
    if same:
        return sum(float(l["quoted_price"]) * float(l.get("qty") or 0) for l in lines)
    if want == "IDR":
        want_rate = 1.0
    else:
        want_rate = float(spr.fx_rate) if (getattr(spr, "currency", "") or "").upper() == want and spr.fx_rate else None
    if not want_rate:
        return None
    total = 0.0
    for l in lines:
        idr = line_idr(spr, l)
        if idr is None:
            return None
        total += idr * float(l.get("qty") or 0) / want_rate
    return total


def is_mixed(spr, lines: list[dict]) -> bool:
    return len({line_money(spr, l)[0] for l in lines}) > 1
