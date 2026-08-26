"""Kas & Bank — Pembayaran, Penerimaan, Transfer Bank, and the bank statement.

The journal underneath is the record; this is the desk. Somebody paying a
supplier is not thinking in debits and credits, they are thinking "eight
million out of BCA to PT Sinar, transfer, slip 88123, for the chain and the
freight". This takes that and writes the entry.

Which way the money went is the only real difference between the three:

- **Pembayaran** credits the bank and debits whatever it was for.
- **Penerimaan** debits the bank and credits whatever it came from.
- **Transfer Bank** credits one of our accounts and debits another. It is
  its own kind rather than a payment that happens to name a bank, because
  booked as a payment it would read as money spent.

**Rekening Koran / Histori Bank** is the same account walked as Buku Besar
walks any other, with the reconciliation state alongside — which lines have
been ticked off against the bank's own statement and which have not.
"""

from datetime import date as date_t
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.cash import KINDS, CashLine, CashTransaction
from app.models.journal import JournalEntry
from app.models.user import User
from app.services import journal as journal_svc

router = APIRouter()

# The cash desk is finance's, with the director as backstop; a manager reads.
_DESK = require(Role.FINANCE, Role.DIRECTOR)
_READERS = require(Role.FINANCE, Role.DIRECTOR, Role.MANAGER)

_PREFIX = {"payment": "BKK", "receipt": "BKM", "transfer": "BTR"}


class LineIn(BaseModel):
    account_no: str
    amount: float
    memo: str | None = None
    customer_id: UUID | None = None
    invoice_id: UUID | None = None


class TxIn(BaseModel):
    kind: str
    tx_date: date_t | None = None
    bank_account_no: str
    to_account_no: str | None = None
    counterparty: str | None = None
    method: str | None = None
    reference: str | None = None
    memo: str | None = None
    # A transfer needs only an amount; a payment or receipt needs the lines
    # that say what it was for.
    amount: float | None = None
    lines: list[LineIn] = []


async def _next_number(db: AsyncSession, kind: str) -> str:
    """BKK / BKM / BTR — the slips an Indonesian cash desk already numbers by."""
    from datetime import datetime

    from app.services.numbering import _next_suffix
    prefix = f"{_PREFIX[kind]}-{datetime.now().year}-"
    return f"{prefix}{await _next_suffix(db, CashTransaction.number, prefix):04d}"


def _tx_out(tx: CashTransaction, *, with_lines: bool = True) -> dict:
    out = {
        "id": str(tx.id), "number": tx.number, "kind": tx.kind,
        "tx_date": tx.tx_date,
        "bank_account_no": tx.bank_account_no,
        "to_account_no": tx.to_account_no,
        "counterparty": tx.counterparty, "method": tx.method,
        "reference": tx.reference, "memo": tx.memo,
        "amount": float(tx.amount or 0),
        "journal_id": str(tx.journal_id) if tx.journal_id else None,
        "is_void": tx.is_void, "void_reason": tx.void_reason,
        "cleared_on": tx.cleared_on,
        "created_at": tx.created_at,
    }
    if with_lines:
        out["lines"] = [{
            "line_no": ln.line_no, "account_no": ln.account_no,
            "amount": float(ln.amount or 0), "memo": ln.memo,
            "invoice_id": str(ln.invoice_id) if ln.invoice_id else None,
        } for ln in (tx.lines or [])]
    return out


async def _bank_account(db: AsyncSession, account_no: str) -> Account:
    acc = await db.scalar(select(Account).where(Account.account_no == account_no))
    if not acc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No such account: {account_no}")
    if acc.account_type != "Cash & Bank":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{acc.account_no} {acc.name} is a {acc.account_type} account. "
            "Money moves out of and into Cash & Bank accounts — the other "
            "side of the entry is what it was for.",
        )
    if acc.is_parent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{acc.account_no} is a heading, not an account.")
    return acc


@router.get("/accounts")
async def bank_accounts(db: AsyncSession = Depends(get_db),
                        user: User = Depends(_READERS)):
    """The company's own cash and bank accounts, with what is in them."""
    rows = (await db.scalars(
        select(Account).where(Account.account_type == "Cash & Bank",
                              Account.is_parent.is_(False),
                              Account.is_suspended.is_(False))
        .order_by(Account.account_no.asc())
    )).all()
    return [{"account_no": a.account_no, "name": a.name,
             "balance": float(a.balance or 0)} for a in rows]


@router.get("")
async def list_transactions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_READERS),
    kind: str | None = None,
    account_no: str | None = None,
    date_from: date_t | None = None,
    date_to: date_t | None = None,
    uncleared: bool = False,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    stmt = select(CashTransaction)
    if kind:
        stmt = stmt.where(CashTransaction.kind == kind)
    if account_no:
        stmt = stmt.where(or_(CashTransaction.bank_account_no == account_no,
                              CashTransaction.to_account_no == account_no))
    if date_from:
        stmt = stmt.where(CashTransaction.tx_date >= date_from)
    if date_to:
        stmt = stmt.where(CashTransaction.tx_date <= date_to)
    if uncleared:
        stmt = stmt.where(CashTransaction.cleared_on.is_(None),
                          CashTransaction.is_void.is_(False))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CashTransaction.number.ilike(like),
                              CashTransaction.counterparty.ilike(like),
                              CashTransaction.reference.ilike(like),
                              CashTransaction.memo.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(CashTransaction.tx_date.desc(),
                      CashTransaction.number.desc())
        .limit(min(limit, 500)).offset(max(0, offset))
    )).all()
    return {"total": total, "items": [_tx_out(t) for t in rows]}


@router.post("", status_code=201)
async def create_transaction(payload: TxIn,
                             db: AsyncSession = Depends(get_db),
                             user: User = Depends(_DESK)):
    """Record money moving, and post the entry that says so."""
    kind = (payload.kind or "").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"kind must be one of: {', '.join(KINDS)}")
    bank = await _bank_account(db, payload.bank_account_no)
    when = payload.tx_date or date_t.today()

    rows: list[dict] = []
    lines: list[CashLine] = []
    if kind == "transfer":
        if not payload.to_account_no:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A transfer needs the account it goes to.")
        to_acc = await _bank_account(db, payload.to_account_no)
        if to_acc.account_no == bank.account_no:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "That is the same account on both sides — a transfer moves "
                "money between two of ours.",
            )
        amount = round(float(payload.amount or 0), 2)
        if amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A transfer needs an amount.")
        rows = [
            {"account_no": to_acc.account_no, "debit": amount,
             "memo": payload.memo or "Bank transfer"},
            {"account_no": bank.account_no, "credit": amount,
             "memo": payload.memo or "Bank transfer"},
        ]
        lines = [CashLine(line_no=1, account_no=to_acc.account_no,
                          amount=amount, memo=payload.memo)]
    else:
        if not payload.lines:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Say what the money was for — one line per account it is "
                "split across.",
            )
        amount = 0.0
        for i, ln in enumerate(payload.lines, 1):
            value = round(float(ln.amount or 0), 2)
            if value <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Line {i} has no amount.")
            amount += value
            lines.append(CashLine(
                line_no=i, account_no=ln.account_no.strip(), amount=value,
                memo=ln.memo, customer_id=ln.customer_id,
                invoice_id=ln.invoice_id))
        amount = round(amount, 2)
        if kind == "payment":
            rows = [{"account_no": ln.account_no, "debit": float(ln.amount),
                     "memo": ln.memo or payload.memo} for ln in lines]
            rows.append({"account_no": bank.account_no, "credit": amount,
                         "memo": payload.memo or payload.counterparty})
        else:
            rows = [{"account_no": ln.account_no, "credit": float(ln.amount),
                     "memo": ln.memo or payload.memo,
                     "customer_id": ln.customer_id} for ln in lines]
            rows.append({"account_no": bank.account_no, "debit": amount,
                         "memo": payload.memo or payload.counterparty})

    tx = CashTransaction(
        number=await _next_number(db, kind), kind=kind, tx_date=when,
        bank_account_no=bank.account_no,
        to_account_no=(payload.to_account_no if kind == "transfer" else None),
        counterparty=(payload.counterparty or "").strip() or None,
        method=(payload.method or "").strip() or None,
        reference=(payload.reference or "").strip() or None,
        memo=(payload.memo or "").strip() or None,
        amount=amount, created_by=user.id,
    )
    tx.lines = lines
    db.add(tx)
    await db.flush()

    try:
        entry = await journal_svc.create_entry(
            db, entry_date=when, rows=rows,
            memo=(tx.memo or tx.counterparty or f"{kind.title()} {tx.number}"),
            source_type="cash", source_id=tx.id, source_ref=tx.number,
            created_by=user.id, post=True, posted_by=user.id,
        )
    except journal_svc.JournalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    tx.journal_id = entry.id
    await db.flush()
    await audit_record(db, actor=user, action="create", entity="cash_transaction",
                       entity_id=tx.id,
                       after={"number": tx.number, "kind": kind, "amount": amount})
    return _tx_out(tx)


@router.get("/statement/{account_no}")
async def statement(account_no: str,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(_READERS),
                    date_from: date_t | None = None,
                    date_to: date_t | None = None,
                    uncleared_only: bool = False):
    """Rekening Koran: one bank account's movements, with what has cleared.

    The account ledger already walks any account; what this adds is the half
    a bank statement is actually reconciled by — whether each line has been
    ticked off against the bank's own copy, and what the two therefore
    disagree by.
    """
    acc = await _bank_account(db, account_no)
    stmt = select(CashTransaction).where(
        or_(CashTransaction.bank_account_no == account_no,
            CashTransaction.to_account_no == account_no),
        CashTransaction.is_void.is_(False),
    )
    if date_from:
        stmt = stmt.where(CashTransaction.tx_date >= date_from)
    if date_to:
        stmt = stmt.where(CashTransaction.tx_date <= date_to)
    if uncleared_only:
        stmt = stmt.where(CashTransaction.cleared_on.is_(None))
    rows = (await db.scalars(
        stmt.order_by(CashTransaction.tx_date.asc(), CashTransaction.number.asc())
    )).all()

    items = []
    cleared_total = uncleared_total = 0.0
    for t in rows:
        # A transfer is money out of `bank_account_no` and into
        # `to_account_no`, so its sign depends on which side we are looking
        # at — the same row reads as a payment on one statement and a
        # receipt on the other.
        into = t.kind == "receipt" or (t.kind == "transfer"
                                       and t.to_account_no == account_no)
        signed = float(t.amount or 0) * (1 if into else -1)
        if t.cleared_on:
            cleared_total += signed
        else:
            uncleared_total += signed
        items.append({
            "id": str(t.id), "number": t.number, "kind": t.kind,
            "tx_date": t.tx_date, "counterparty": t.counterparty,
            "method": t.method, "reference": t.reference, "memo": t.memo,
            "amount": signed,
            "direction": "in" if into else "out",
            "cleared_on": t.cleared_on,
            "journal_id": str(t.journal_id) if t.journal_id else None,
        })
    return {
        "account": {"account_no": acc.account_no, "name": acc.name,
                    "balance": float(acc.balance or 0)},
        "items": items,
        "cleared_total": round(cleared_total, 2),
        "uncleared_total": round(uncleared_total, 2),
        # What the bank should be showing if everything uncleared is still
        # in flight — the figure a reconciliation is trying to land on.
        "statement_balance": round(
            float(acc.balance or 0) - uncleared_total, 2),
    }


@router.get("/{tx_id}")
async def get_transaction(tx_id: UUID,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_READERS)):
    tx = await db.get(CashTransaction, tx_id)
    if not tx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return _tx_out(tx)


class ClearIn(BaseModel):
    cleared: bool = True
    on: date_t | None = None


@router.post("/{tx_id}/clear")
async def clear_transaction(tx_id: UUID, payload: ClearIn,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(_DESK)):
    """Tick a line off against the bank's own statement, or untick it."""
    tx = await db.get(CashTransaction, tx_id)
    if not tx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    if tx.is_void:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This one was voided — there is nothing to clear.")
    tx.cleared_on = (payload.on or date_t.today()) if payload.cleared else None
    tx.cleared_by = user.id if payload.cleared else None
    await db.flush()
    return {"ok": True, "cleared_on": tx.cleared_on}


@router.post("/{tx_id}/void")
async def void_transaction(tx_id: UUID,
                           reason: str | None = None,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(_DESK)):
    """Undo one by reversing its journal. Both stay on the record."""
    from datetime import UTC, datetime

    tx = await db.get(CashTransaction, tx_id)
    if not tx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    if tx.is_void:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{tx.number} was already voided.")
    if tx.cleared_on:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{tx.number} has been reconciled against the bank statement. "
            "Untick it first if it really has to be reversed.",
        )
    if tx.journal_id:
        entry = await db.get(JournalEntry, tx.journal_id)
        if entry:
            try:
                await journal_svc.reverse_entry(
                    db, entry, actor_id=user.id,
                    reason=(reason or f"Void of {tx.number}"))
            except journal_svc.JournalError as e:
                raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    tx.is_void = True
    tx.void_reason = reason
    tx.voided_at = datetime.now(UTC)
    tx.voided_by = user.id
    await db.flush()
    await audit_record(db, actor=user, action="void", entity="cash_transaction",
                       entity_id=tx.id,
                       after={"number": tx.number, "reason": reason})
    return {"ok": True, **_tx_out(tx)}
