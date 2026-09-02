"""Keeping a quotation in step with the price request it was built from.

A quotation made from a price request is that request, dressed for the
customer: same lines, same quantities, and the selling prices the director
approved. Until now the copy was taken once and the two drifted apart
immediately — the price request page said so outright ("changing it here does
not change the quotation"), which is an honest warning and a bad answer. The
customer gets the old wording, the old quantity and the old price, and the
only thing that notices is whoever eventually reads both.

So a change to the request now reaches the quotation. Two rules decide what
that means:

**A quotation that has not gone anywhere is rewritten.** Draft or rejected,
nobody outside the company has seen it, so it should simply say what the
request says.

**A quotation that has gone somewhere is not.** Submitted for approval,
approved, sent, won — those are documents other people are acting on, and a
customer holding a quotation for Rp 12 million must not find it silently
became Rp 14 million. Those get a note instead, saying the request moved and
by how much, so a person decides whether to revise it.

The second rule is the one that matters. Syncing everything would be easier
to write and would eventually rewrite a number under somebody's signature.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_request import PriceRequest
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User

# A quotation nobody outside the company has acted on yet.
REWRITABLE = ("draft", "rejected")


def _line_of(it: dict, i: int) -> dict:
    """One quotation line as the price request would have it.

    Mirrors `create_from_price_request` exactly — if the two ever disagree,
    a synced quotation and a freshly built one would differ, which is a
    difference nobody could explain from the screen.
    """
    return {
        "line_no": it.get("line_no") or (i + 1),
        "description": it.get("description") or "",
        "qty": float(it.get("qty") or 0),
        "uom": it.get("uom") or "pcs",
        "unit_price": float(it.get("sell_price") or 0),
        "cost_estimate": float(it.get("cost_price") or 0),
    }


def _differs(existing: list[QuotationItem], wanted: list[dict]) -> bool:
    if len(existing) != len(wanted):
        return True
    have = sorted(({"line_no": int(x.line_no or 0),
                    "description": x.description or "",
                    "qty": float(x.qty or 0),
                    "uom": x.uom or "pcs",
                    "unit_price": float(x.unit_price or 0)}
                   for x in existing), key=lambda r: r["line_no"])
    want = sorted(({k: v for k, v in w.items() if k != "cost_estimate"}
                   for w in wanted), key=lambda r: r["line_no"])
    return have != want


async def sync_from_price_request(
    db: AsyncSession, pr: PriceRequest, actor: User | None = None,
) -> list[dict]:
    """Push the request's lines onto the quotations built from it.

    Returns one entry per quotation touched or flagged, for the caller to
    hand back to whoever made the change — a sync nobody is told about is
    indistinguishable from no sync at all.
    """
    from app.api.v1.endpoints.quotations import _recalc

    quotes = list((await db.scalars(
        select(Quotation).where(Quotation.price_request_id == pr.id)
    )).all())
    # The link is kept on both rows; an older quotation may only be named
    # from the request's side.
    if pr.quotation_id and not any(q.id == pr.quotation_id for q in quotes):
        q = await db.get(Quotation, pr.quotation_id)
        if q:
            quotes.append(q)
    if not quotes:
        return []

    wanted = [_line_of(it, i) for i, it in enumerate(pr.items or [])]
    out: list[dict] = []

    for q in quotes:
        existing = list(q.items)
        if not _differs(existing, wanted):
            continue
        if q.status not in REWRITABLE:
            # Not ours to rewrite. Say so on the quotation itself, where
            # whoever opens it next will see it, rather than only in an
            # audit log nobody reads on the way to sending it.
            was = float(q.total or 0)
            now = sum(w["qty"] * w["unit_price"] for w in wanted)
            note = (f"[system] {pr.number} changed after this quotation was "
                    f"{q.status.replace('_', ' ')} — it now comes to "
                    f"Rp {now:,.0f} against the Rp {was:,.0f} quoted. "
                    "Revise this quotation if the customer should see the "
                    "new figure.").replace(",", ".")
            if note not in (q.notes or ""):
                q.notes = f"{(q.notes or '').rstrip()}\n{note}".strip()
            out.append({"quotation_id": str(q.id), "number": q.number,
                        "status": q.status, "synced": False,
                        "old_total": was, "new_total": now})
            continue

        for it in existing:
            await db.delete(it)
        await db.flush()
        rows = [QuotationItem(quotation_id=q.id, source="custom", **w)
                for w in wanted]
        db.add_all(rows)
        if actor is not None:
            q.updated_by = actor.id
        _recalc(q, rows)
        out.append({"quotation_id": str(q.id), "number": q.number,
                    "status": q.status, "synced": True,
                    "lines": len(rows), "new_total": float(q.total or 0)})

    if out:
        await db.flush()
    return out


async def quotation_ids_for(db: AsyncSession, pr_id: UUID) -> list[UUID]:
    return list((await db.scalars(
        select(Quotation.id).where(Quotation.price_request_id == pr_id)
    )).all())
