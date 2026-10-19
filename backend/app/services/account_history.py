"""Every way an account's balance moved — one reader for the account ledger
and the Buku Besar report, so the two never disagree.

A balance moves four ways, and all four are read:

* journal entries — manual ones, the cash desk, assets, opening balances;
* the postings the app makes on its own — goods received, supplier and
  customer payments, a quotation won, payroll, a PO's cost. These never go
  through the journal (they write the reporting journal directly), so a
  ledger that read only the journal said "nothing has ever been posted"
  beside an account holding 1,8 billion of goods receipts;
* balances typed in or changed by hand on the chart of accounts, read from
  the audit trail, with who and when;
* and whatever is still left, as one row saying plainly there is no record
  of it — so the closing figure always is the account's balance.

Voided (batal) journal entries and their reversals are left out: as if they
had never been entered.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.journal import CREDIT_NORMAL, JournalEntry, JournalLine, signed_delta

# Labels for the postings the app makes on its own, keyed by source_type.
AUTO_LABEL = {
    "goods_receipt": "Goods received",
    "supplier_payment": "Supplier payment",
    "supplier_po_cogs": "PO cost (HPP)",
    "quotation": "Quotation won",
    "payment": "Customer payment",
    "salary": "Payroll",
}

NO_RECORD_MEMO = ("No record of where this came from — it was on the account "
                  "before changes were recorded (brought in with the chart of "
                  "accounts, or moved by something that kept no trail).")


def debit_credit(account_type: str, delta: float) -> tuple[float, float]:
    """A change in the account's own direction, as a debit or a credit."""
    up = delta >= 0
    if account_type in CREDIT_NORMAL:
        return (0.0, delta) if up else (-delta, 0.0)
    return (delta, 0.0) if up else (0.0, -delta)


async def _auto_links(db: AsyncSession, rows) -> dict:
    """Where each automatic posting came from, as a page to open."""
    from app.models.finance import Payment
    from app.models.purchasing import GoodsReceipt, SupplierPayment

    out: dict = {}
    for r in rows:
        if not r.source_id:
            continue
        if r.source_type == "quotation":
            out[r.id] = f"/quotations/{r.source_id}"
        elif r.source_type == "supplier_po_cogs":
            out[r.id] = f"/purchase-orders/{r.source_id}"
    for model, kind, fk, path in (
        (GoodsReceipt, "goods_receipt", "po_id", "/purchase-orders/"),
        (SupplierPayment, "supplier_payment", "po_id", "/purchase-orders/"),
        (Payment, "payment", "invoice_id", "/invoices/"),
    ):
        keys = {r.source_id for r in rows if r.source_type == kind and r.source_id}
        if not keys:
            continue
        found = {x.id: getattr(x, fk) for x in (await db.scalars(
            select(model).where(model.id.in_(keys)))).all()}
        for r in rows:
            if r.source_type == kind and found.get(r.source_id):
                out[r.id] = f"{path}{found[r.source_id]}"
    return out


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _sort_key(e):
    at = e["_at"]
    return (e["entry_date"], at.replace(tzinfo=None) if at else datetime.min)


async def account_events(db: AsyncSession, accounts: list[Account]) -> dict[str, list[dict]]:
    """Every movement on each of `accounts`, oldest first, keyed by number.

    Three queries for however many accounts — the Buku Besar reads the whole
    chart at once."""
    from app.models.audit import AuditLog
    from app.models.finance import LedgerEntry
    from app.models.user import User

    by_no = {a.account_no: a for a in accounts}
    events: dict[str, list[dict]] = {no: [] for no in by_no}
    if not by_no:
        return events
    nos = list(by_no)

    # 1. The general journal.
    for ln, e in (await db.execute(
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
        .where(JournalLine.account_no.in_(nos),
               JournalEntry.is_posted.is_(True),
               JournalEntry.is_void.is_(False))     # batal: as if never entered
    )).all():
        events[ln.account_no].append({
            "kind": "journal", "journal_id": str(e.id), "number": e.number,
            "entry_date": e.entry_date, "_at": e.created_at,
            "memo": ln.memo or e.memo,
            "source_type": e.source_type, "source_ref": e.source_ref,
            "debit": float(ln.debit or 0), "credit": float(ln.credit or 0),
            "delta": signed_delta(ln.account_type, ln.debit, ln.credit),
            "link": None, "by": None,
        })

    # 2. What the app posted on its own. A journal entry mirrors itself into
    # the same table with its own id as the source — those are in 1 already.
    auto = (await db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.account_no.in_(nos),
            or_(LedgerEntry.source_id.is_(None),
                LedgerEntry.source_id.not_in(select(JournalEntry.id))),
        )
    )).all()
    links = await _auto_links(db, auto)
    for r in auto:
        acc = by_no[r.account_no]
        delta = float(r.amount or 0)
        debit, credit = debit_credit(acc.account_type, delta)
        events[r.account_no].append({
            "kind": "auto", "journal_id": None,
            "number": r.source_ref or AUTO_LABEL.get(r.source_type, r.source_type),
            "entry_date": r.entry_date, "_at": r.created_at,
            "memo": r.memo, "source_type": r.source_type, "source_ref": r.source_ref,
            "label": AUTO_LABEL.get(r.source_type, r.source_type.replace("_", " ")),
            "debit": debit, "credit": credit, "delta": delta,
            "link": links.get(r.id), "by": None,
        })

    # 3. Balances set by hand — typed in when the account was made, or
    # changed on the chart of accounts. A cash correction is in the audit too,
    # but it went through the journal, so it is in 1 already.
    by_id = {a.id: a for a in accounts}
    hand = (await db.scalars(
        select(AuditLog).where(AuditLog.entity == "account",
                               AuditLog.entity_id.in_(list(by_id)))
        .order_by(AuditLog.occurred_at.asc())
    )).all()
    names = {u.id: u.full_name for u in (await db.scalars(
        select(User).where(User.id.in_({a.actor_id for a in hand if a.actor_id}))
    )).all()} if hand else {}
    for a in hand:
        acc = by_id.get(a.entity_id)
        if acc is None:
            continue
        after, before = a.after or {}, a.before or {}
        if "balance" not in after or "journal" in after:
            continue
        # Recorded opening balances state the account as it stood then, so a
        # balance typed in before them is already inside that figure.
        opened = [e["_at"] for e in events[acc.account_no]
                  if e["source_type"] == "opening" and e["_at"] is not None]
        if opened and a.occurred_at <= min(opened):
            continue
        if a.action == "create":
            delta = _num(after["balance"])
            memo = "Balance entered when the account was created"
        elif a.action == "update":
            delta = _num(after["balance"]) - _num(before.get("balance"))
            memo = (f"Balance changed by hand on the chart of accounts: "
                    f"{_num(before.get('balance')):,.2f} → {_num(after['balance']):,.2f}")
        else:
            continue
        if abs(delta) < 0.005:
            continue
        debit, credit = debit_credit(acc.account_type, delta)
        events[acc.account_no].append({
            "kind": "by_hand", "journal_id": None, "number": "—",
            "entry_date": a.occurred_at.date(), "_at": a.occurred_at,
            "memo": memo, "source_type": "by_hand", "source_ref": None,
            "label": "Set by hand",
            "debit": debit, "credit": credit, "delta": delta,
            "link": None, "by": names.get(a.actor_id),
        })

    # 4. What none of that explains: there before anything was recorded.
    for no, acc in by_no.items():
        rest = round(float(acc.balance or 0) - sum(e["delta"] for e in events[no]), 2)
        if abs(rest) >= 0.005:
            debit, credit = debit_credit(acc.account_type, rest)
            made = acc.created_at or datetime.min
            events[no].append({
                "kind": "unrecorded", "journal_id": None, "number": "—",
                "entry_date": made.date(), "_at": made,
                "memo": NO_RECORD_MEMO,
                "source_type": "unrecorded", "source_ref": None,
                "label": "No record",
                "debit": debit, "credit": credit, "delta": rest,
                "link": None, "by": None,
            })
        events[no].sort(key=_sort_key)
    return events


def walk(events: list[dict], start: date | None, end: date | None,
         limit: int = 2000) -> dict:
    """An account's movements over [start, end): the opening balance (all
    that came before), each line with its running balance, the totals."""
    opening = sum(e["delta"] for e in events if start and e["entry_date"] < start)
    window = [e for e in events
              if (not start or e["entry_date"] >= start)
              and (not end or e["entry_date"] < end)]
    running = opening
    items = []
    total_d = total_c = 0.0
    for e in window[:limit]:
        running += e["delta"]
        total_d += e["debit"]
        total_c += e["credit"]
        items.append({k: v for k, v in e.items() if not k.startswith("_")}
                     | {"balance": round(running, 2)})
    return {
        "opening_balance": round(opening, 2),
        "closing_balance": round(running, 2),
        "total_debit": round(total_d, 2), "total_credit": round(total_c, 2),
        "items": items,
    }
