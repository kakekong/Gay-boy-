"""Keeping a price request in step with the quotation made from it — and the
supplier requests made from *that*.

`quotation_sync` pushes one way: the request changes, the quotation follows.
That was the only direction, which left the other one open, and it is the one
people actually walk. The quotation is the document a deal is negotiated on:
the customer asks for four more of item eight, a price moves in a phone call,
a line gets reworded to match what they call it. All of that lands on the
quotation — and the price request it came from sat there still saying what was
asked for a fortnight ago.

That matters because the price request is not an archive. It is what
purchasing buys against and what the project page shows as the order being
fulfilled, so a stale one sends the wrong quantity to a supplier and shows the
wrong job on the floor. Two screens of the same order disagreeing, with
nothing saying which is right, is worse than either being wrong on its own.

So three movements, and the difference between them is who is already holding
a copy:

**Quotation → price request: automatic.** Nobody outside the company reads a
price request; it is our own note of what was agreed. And a line change on a
price-request-backed quotation has already passed the director — sales cannot
make one, and a non-director's edit to an approved quotation queues for
approval before it applies — so by the time it is on the quotation it *is* the
decision. The request follows it.

**Price request → supplier request: by hand.** A supplier has been sent a
list, and may have priced it. Rewriting that under them is not a sync, it is a
different question they were never asked. So purchasing gets told the lines
moved, and presses the button when they mean to.

**Project: nothing to do.** The project page reads the request live, so once
the request is right, the project is right. The button there exists for orders
that predate this file.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_request import PriceRequest
from app.models.quotation import Quotation
from app.models.user import User

# Fields a quotation line owns once a deal is being negotiated on it. Cost is
# not among them: what we pay is purchasing's, arrived at on the buy side, and
# a quotation carries it only as an estimate copied along for margin.
_MONEY = "sell_price"


def _rounded(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _wanted_from(q: Quotation, items=None) -> dict[int, dict]:
    """The quotation's lines, keyed by line number, as a request would say them.

    `items` is passed explicitly by callers that have just replaced the lines,
    for the same reason `_recalc` takes them: the rows are built with
    `quotation_id=` and added to the session rather than appended to the
    relationship, so `q.items` is still the collection as it was loaded. Read
    that and a sync run straight after an edit compares the old lines with
    themselves, finds nothing, and silently does nothing at all.
    """
    rows = q.items if items is None else items
    out: dict[int, dict] = {}
    for i, it in enumerate(sorted(rows, key=lambda x: int(x.line_no or 0))):
        no = int(it.line_no or (i + 1))
        out[no] = {
            "line_no": no,
            "description": it.description or "",
            "qty": _rounded(it.qty),
            "uom": it.uom or "pcs",
            "sell_price": _rounded(it.unit_price),
        }
    return out


def diff_against_quotation(pr: PriceRequest, q: Quotation) -> list[dict]:
    """What the quotation says that the request does not. Read-only.

    One entry per line that differs, so a screen can say *what* drifted rather
    than only that something did — "line 8: qty 8 → 10" is actionable, "out of
    sync" is not.
    """
    wanted = _wanted_from(q)
    have = {int(it.get("line_no") or 0): it for it in (pr.items or [])}
    rows: list[dict] = []
    for no in sorted(set(wanted) | set(have)):
        w, h = wanted.get(no), have.get(no)
        if w is None:
            rows.append({"line_no": no, "change": "only_on_request",
                         "description": (h or {}).get("description")})
            continue
        if h is None:
            rows.append({"line_no": no, "change": "only_on_quotation",
                         "description": w["description"]})
            continue
        fields = []
        for k in ("description", "qty", "uom", _MONEY):
            was = h.get(k) if k != _MONEY else _rounded(h.get(_MONEY))
            now = w[k]
            if k in ("qty",):
                was = _rounded(was)
            if k in ("description", "uom"):
                was = (was or "") or ("pcs" if k == "uom" else "")
            if was != now:
                fields.append({"field": k, "was": was, "now": now})
        if fields:
            rows.append({"line_no": no, "change": "differs",
                         "description": w["description"], "fields": fields})
    return rows


async def sync_from_quotation(
    db: AsyncSession, q: Quotation, actor: User | None = None, items=None,
) -> dict | None:
    """Write the quotation's lines back onto the price request behind it.

    Returns a summary of what moved, or None when there is nothing behind it
    and nothing to do — a caller that reports "synced" on every save teaches
    people to ignore the message.

    The cost stays exactly as purchasing left it. A quotation knows the
    selling price; it carries cost only as an estimate, and letting that
    estimate overwrite a real quoted cost would quietly change the margin on
    a deal nobody was discussing the cost of.
    """
    if not q.price_request_id:
        return None
    pr = await db.get(PriceRequest, q.price_request_id)
    if not pr:
        return None

    wanted = _wanted_from(q, items)
    have = {int(it.get("line_no") or 0): dict(it) for it in (pr.items or [])}
    changed: list[dict] = []
    new_items: list[dict] = []

    for no in sorted(wanted):
        w = wanted[no]
        old = have.get(no)
        if old is None:
            # A line added on the quotation. It joins the request with no cost
            # against it, which is the truthful state: nobody has been asked
            # what it costs us yet, and the blank is what makes that visible
            # on purchasing's screen.
            row = {**w, "spec": {}, "cost_price": None, "category": None}
            new_items.append(row)
            changed.append({"line_no": no, "change": "added",
                            "description": w["description"]})
            continue
        row = {**old}
        fields = []
        for k in ("description", "qty", "uom", _MONEY):
            before = row.get(k)
            if k in ("qty", _MONEY):
                before = _rounded(before)
            if before != w[k]:
                fields.append({"field": k, "was": before, "now": w[k]})
            row[k] = w[k]
        row["line_no"] = no
        new_items.append(row)
        if fields:
            changed.append({"line_no": no, "change": "updated",
                            "description": w["description"], "fields": fields})

    # A line taken off the quotation is taken off the request. The deal is
    # what is being negotiated; a request that keeps billing purchasing for an
    # item the customer dropped is the same drift in the other direction.
    for no in sorted(set(have) - set(wanted)):
        changed.append({"line_no": no, "change": "removed",
                        "description": have[no].get("description")})

    if not changed:
        return None

    pr.items = new_items
    # Say it on the request too. Whoever opens it next sees why a figure they
    # remember approving now reads differently, without going to an audit log.
    note = (f"[system] Updated from quotation {q.number}: "
            + ", ".join(
                f"line {c['line_no']} "
                + (c["change"] if c["change"] != "updated"
                   else ", ".join(f["field"] for f in c.get("fields", [])))
                for c in changed[:8])
            + ("…" if len(changed) > 8 else ""))
    pr.notes = f"{(pr.notes or '').rstrip()}\n{note}".strip()
    if actor is not None:
        pr.updated_by = actor.id
    await db.flush()
    return {
        "price_request_id": str(pr.id),
        "number": pr.number,
        "quotation_id": str(q.id),
        "quotation_number": q.number,
        "lines_changed": len(changed),
        "changes": changed,
    }


async def quotation_for_request(
    db: AsyncSession, pr: PriceRequest,
) -> Quotation | None:
    """The live quotation a request's figures should agree with.

    The newest one that is not superseded or lost: a revision replaces the
    quote it came from, so the latest live one is the deal as it stands.
    """
    rows = list((await db.scalars(
        select(Quotation).where(Quotation.price_request_id == pr.id)
        .order_by(Quotation.created_at.desc())
    )).all())
    if pr.quotation_id and not any(x.id == pr.quotation_id for x in rows):
        one = await db.get(Quotation, pr.quotation_id)
        if one:
            rows.append(one)
    live = [x for x in rows if x.status not in ("superseded", "lost", "rejected")]
    return (live or rows or [None])[0]


async def pr_ids_touched_by(db: AsyncSession, q_id: UUID) -> list[UUID]:
    q = await db.get(Quotation, q_id)
    return [q.price_request_id] if q and q.price_request_id else []
