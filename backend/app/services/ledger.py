"""Post-to-ledger service for quotations.

Keeps the Chart-of-Accounts balances in sync with what a won quotation
implies. Pure single-entry-style balance updates here (we are not
building a full double-entry general ledger). Each posting is recorded
as a snapshot on the quotation so it can be reversed cleanly.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.quotation import Quotation


DEFAULTS = {
    "revenue":    "400001",   # Penjualan
    "receivable": "110301",   # Piutang Usaha IDR
    "discount":   "400004",   # Diskon Penjualan
    "tax":        "2102-01",  # PPN Keluaran
}


def _ensure_defaults(q: Quotation) -> None:
    """Fall back to standard accounts if the user hasn't customised them."""
    if not q.account_revenue_no:    q.account_revenue_no    = DEFAULTS["revenue"]
    if not q.account_receivable_no: q.account_receivable_no = DEFAULTS["receivable"]
    if not q.account_discount_no:   q.account_discount_no   = DEFAULTS["discount"]
    if not q.account_tax_no:        q.account_tax_no        = DEFAULTS["tax"]


def compute_amounts(q: Quotation) -> dict:
    """Recompute the four ledger amounts from the quotation totals."""
    subtotal = float(q.subtotal or 0)
    discount_amount = float(q.discount_amount or 0)
    after_discount = subtotal - discount_amount
    total = float(q.total or 0)
    tax_amount = total - after_discount
    return {
        "receivable": total,
        "revenue":    after_discount,
        "discount":   discount_amount,
        "tax":        tax_amount,
    }


async def _bump(db: AsyncSession, account_no: str | None, delta: float) -> dict | None:
    if not account_no:
        return None
    acc = await db.scalar(select(Account).where(Account.account_no == account_no))
    if not acc:
        return None
    new_balance = float(acc.balance or 0) + delta
    acc.balance = new_balance
    return {
        "account_no": account_no,
        "name": acc.name,
        "delta": delta,
        "new_balance": new_balance,
    }


async def post_quotation(db: AsyncSession, q: Quotation) -> dict:
    """Add the implied amounts to the linked accounts. Idempotent."""
    if q.is_posted:
        return {"already_posted": True, "snapshot": q.posted_snapshot}

    _ensure_defaults(q)
    amounts = compute_amounts(q)

    movements = []
    for key in ("receivable", "revenue", "discount", "tax"):
        m = await _bump(db, getattr(q, f"account_{key}_no"), amounts[key])
        if m:
            movements.append({**m, "role": key})

    q.is_posted = True
    q.posted_at = datetime.now(UTC)
    q.posted_snapshot = {
        "amounts": amounts,
        "movements": movements,
        "posted_at": q.posted_at.isoformat(),
    }
    await db.flush()
    return q.posted_snapshot


async def reverse_quotation(db: AsyncSession, q: Quotation) -> dict:
    """Subtract previously-posted amounts from the linked accounts."""
    if not q.is_posted:
        return {"not_posted": True}

    movements = []
    snapshot = q.posted_snapshot or {}
    for m in snapshot.get("movements", []):
        rev = await _bump(db, m.get("account_no"), -float(m.get("delta") or 0))
        if rev:
            movements.append({**rev, "role": m.get("role"), "reversed": True})

    q.is_posted = False
    q.posted_at = None
    q.posted_snapshot = {
        "reversed_at": datetime.now(UTC).isoformat(),
        "previous": snapshot,
        "movements": movements,
    }
    await db.flush()
    return q.posted_snapshot
