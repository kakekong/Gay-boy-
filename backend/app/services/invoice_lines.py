"""The lines an invoice prints.

The trade names one part two ways — the vendor's technical name and the one
the customer knows it by — and the two are often nothing alike. Turning one
into the other takes someone who knows both, so the invoice does not try: the
person issuing it types the lines the customer should see, and those are what
print, word for word.

An invoice nobody has typed lines for prints what it always has: the
customer's own PO lines, then the quotation's.

Typed lines still have to account for the money. They may add up to exactly
what is billed, or — on a final invoice — to more, the difference printing as
the discount the way the faktur pajak shows it. Never to less: a sheet whose
lines come to less than its total bills for something it doesn't name. A
down-payment invoice bills a share of the job, not goods, so its lines must
come to the amount exactly.
"""
from sqlalchemy import select

# Rupiah: enough to absorb rounding on a split, not enough to hide an edit.
TOLERANCE = 100.0


def clean_lines(items: list[dict]) -> list[dict]:
    """The typed lines, trimmed and checked. Raises ValueError with a message
    a person can act on."""
    out: list[dict] = []
    for n, raw in enumerate(items or [], 1):
        desc = str(raw.get("description") or "").strip()
        try:
            qty = float(raw.get("qty") or 0)
            price = float(raw.get("unit_price") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Line {n}: quantity and price must be numbers") from None
        if not desc and not qty and not price:
            continue                                   # an empty row left in the form
        if not desc:
            raise ValueError(f"Line {n} needs a name")
        if qty <= 0:
            raise ValueError(f"Line {n} ({desc}): the quantity must be more than zero")
        if price < 0:
            raise ValueError(f"Line {n} ({desc}): the price can't be negative")
        out.append({
            "description": desc,
            "sku": (str(raw.get("sku") or "").strip() or None),
            "qty": qty,
            "uom": (str(raw.get("uom") or "").strip() or "pcs"),
            "unit_price": price,
        })
    return out


def lines_total(rows: list[dict]) -> float:
    return sum(float(r.get("qty") or 0) * float(r.get("unit_price") or 0) for r in rows)


def misfit(rows: list[dict], amount: float, kind: str) -> str | None:
    """Why these lines can't stand on this invoice, or None if they can."""
    gross, billed = lines_total(rows), float(amount or 0)
    fmt = lambda v: "Rp " + f"{v:,.0f}".replace(",", ".")        # noqa: E731
    if gross + TOLERANCE < billed:
        return (f"The lines add up to {fmt(gross)}, less than the {fmt(billed)} "
                "being billed. Add what's missing, or correct the amount.")
    if kind == "dp" and gross - billed > TOLERANCE:
        return (f"The lines add up to {fmt(gross)}, but this down payment bills "
                f"{fmt(billed)}. A down-payment invoice's lines must come to its "
                "amount exactly.")
    return None


async def auto_lines(db, inv) -> tuple[list[dict], str | None]:
    """What the invoice prints when nobody has typed its lines: the customer's
    PO lines, in their words, else the quotation's — with item codes filled
    in. Also the order number the sheet quotes."""
    from app.models.customer_po import CustomerPO
    from app.models.operation import Project
    from app.services.item_codes import fill_item_codes, quotation_rows

    project = await db.get(Project, inv.project_id) if inv.project_id else None
    po = await db.get(CustomerPO, inv.customer_po_id) if inv.customer_po_id else None
    if po is None and project:
        po = (await db.scalars(
            select(CustomerPO).where(CustomerPO.project_id == project.id)
            .order_by(CustomerPO.created_at.desc()).limit(1)
        )).first()
    rows = [dict(i) for i in (po.items or [])] if po else []
    quote_rows = await quotation_rows(db, project)
    if not rows:
        rows = quote_rows
    rows = await fill_item_codes(db, rows, project, quote_rows)
    return rows, (po.number if po else None)
