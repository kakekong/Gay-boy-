"""Post-to-ledger service for quotations and payments.

Keeps the Chart-of-Accounts balances in sync with what a won quotation
implies, and now mirrors every movement into the `ledger_entries`
transaction journal so finance can slice activity by period and by
salesperson. Pure single-entry-style balance updates here (we are not
building a full double-entry general ledger). Each quotation posting is
also recorded as a snapshot on the quotation so it can be reversed cleanly.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.finance import LedgerEntry
from app.models.quotation import Quotation


DEFAULTS = {
    "revenue":    "400001",   # Penjualan
    "receivable": "110301",   # Piutang Usaha IDR
    "discount":   "400004",   # Diskon Penjualan
    "tax":        "2102-01",  # PPN Keluaran
}

# Where a received customer payment lands by default, and which receivable
# it draws down. Cash up + receivable down is the standard collection entry.
PAYMENT_CASH_DEFAULT = "1101-01"   # Bank Bca
PAYMENT_RECEIVABLE = "110301"      # Piutang Usaha IDR


async def journal_post(
    db: AsyncSession,
    *,
    entry_date: date,
    account_no: str,
    account_type: str,
    account_name: str | None,
    amount: float,
    source_type: str,
    source_id: UUID | None = None,
    source_ref: str | None = None,
    memo: str | None = None,
    customer_id: UUID | None = None,
    sales_pic_id: UUID | None = None,
    created_by: UUID | None = None,
    cash_delta: float | None = None,
) -> LedgerEntry:
    """Append one line to the transaction journal.

    `cash_delta` defaults to `amount` for Cash & Bank lines and 0 otherwise,
    so money-in / money-out is always a plain SUM over cash_delta.
    """
    if cash_delta is None:
        cash_delta = amount if account_type == "Cash & Bank" else 0.0
    entry = LedgerEntry(
        entry_date=entry_date, account_no=account_no, account_type=account_type,
        account_name=account_name, amount=amount, cash_delta=cash_delta,
        source_type=source_type, source_id=source_id, source_ref=source_ref,
        memo=memo, customer_id=customer_id, sales_pic_id=sales_pic_id,
        created_by=created_by,
    )
    db.add(entry)
    return entry


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
        "account_type": acc.account_type,
        "delta": delta,
        "new_balance": new_balance,
    }


async def post_quotation(db: AsyncSession, q: Quotation) -> dict:
    """Add the implied amounts to the linked accounts. Idempotent."""
    if q.is_posted:
        return {"already_posted": True, "snapshot": q.posted_snapshot}

    _ensure_defaults(q)
    amounts = compute_amounts(q)
    entry_date = datetime.now(UTC).date()

    movements = []
    for key in ("receivable", "revenue", "discount", "tax"):
        m = await _bump(db, getattr(q, f"account_{key}_no"), amounts[key])
        if m:
            movements.append({**m, "role": key})
            await journal_post(
                db, entry_date=entry_date, account_no=m["account_no"],
                account_type=m["account_type"], account_name=m["name"],
                amount=m["delta"], source_type="quotation", source_id=q.id,
                source_ref=q.number, memo=f"Quotation {q.number} posted ({key})",
                customer_id=q.customer_id, sales_pic_id=q.sales_pic_id,
            )

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
    entry_date = datetime.now(UTC).date()
    for m in snapshot.get("movements", []):
        rev = await _bump(db, m.get("account_no"), -float(m.get("delta") or 0))
        if rev:
            movements.append({**rev, "role": m.get("role"), "reversed": True})
            await journal_post(
                db, entry_date=entry_date, account_no=rev["account_no"],
                account_type=rev["account_type"], account_name=rev["name"],
                amount=rev["delta"], source_type="quotation", source_id=q.id,
                source_ref=q.number,
                memo=f"Quotation {q.number} reversed ({m.get('role')})",
                customer_id=q.customer_id, sales_pic_id=q.sales_pic_id,
            )

    q.is_posted = False
    q.posted_at = None
    q.posted_snapshot = {
        "reversed_at": datetime.now(UTC).isoformat(),
        "previous": snapshot,
        "movements": movements,
    }
    await db.flush()
    return q.posted_snapshot


async def post_payment(
    db: AsyncSession,
    *,
    amount: float,
    entry_date: date,
    invoice_number: str | None = None,
    customer_id: UUID | None = None,
    sales_pic_id: UUID | None = None,
    payment_id: UUID | None = None,
    created_by: UUID | None = None,
    cash_account_no: str = PAYMENT_CASH_DEFAULT,
) -> list[dict]:
    """Record a received customer payment in the ledger: cash up, receivable
    down. Bumps the Chart-of-Accounts balances (so cash-held and AR stay
    accurate) and writes the matching journal lines. Returns the movements.
    """
    if amount <= 0:
        return []
    moves: list[dict] = []
    cash = await _bump(db, cash_account_no, amount)
    recv = await _bump(db, PAYMENT_RECEIVABLE, -amount)
    for m, role in ((cash, "cash"), (recv, "receivable")):
        if not m:
            continue
        await journal_post(
            db, entry_date=entry_date, account_no=m["account_no"],
            account_type=m["account_type"], account_name=m["name"],
            amount=m["delta"], source_type="payment", source_id=payment_id,
            source_ref=invoice_number,
            memo=f"Payment received for {invoice_number or 'invoice'} ({role})",
            customer_id=customer_id, sales_pic_id=sales_pic_id,
            created_by=created_by,
        )
        moves.append({**m, "role": role})
    return moves
