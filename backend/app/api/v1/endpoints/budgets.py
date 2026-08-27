"""Anggaran, Monitor Anggaran, Transfer Anggaran.

Setting a budget is the easy part. The part worth building carefully is
Monitor: what was actually spent has to come from the ledger, over the same
period, on the same account, or the comparison is two numbers that merely
look comparable.

Three things this does that a spreadsheet does not:

- **It says which budget it used.** A month can be measured against its own
  monthly figure or against a twelfth of the annual one, and those are
  different claims. The answer carries `basis` so nobody has to guess which
  they are reading.
- **It signs the actual the way the account is read.** Spending on an
  expense account is a positive number; a refund reduces it. Taking the raw
  debit total instead would make every credit note look like more spending.
- **It refuses to move budget that is not there.** A transfer out of an
  account with nothing budgeted is not a transfer, it is an increase
  wearing a transfer's clothes, and the record would be wrong about where
  the money came from.
"""

from calendar import monthrange
from datetime import date as date_t
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.budget import Budget, BudgetTransfer
from app.models.journal import CREDIT_NORMAL, JournalEntry, JournalLine
from app.models.user import User

router = APIRouter()

_DESK = require(Role.FINANCE, Role.DIRECTOR)
_READERS = require(Role.FINANCE, Role.DIRECTOR, Role.MANAGER)


async def _account(db: AsyncSession, account_no: str) -> Account:
    no = (account_no or "").strip()
    acc = await db.scalar(select(Account).where(Account.account_no == no))
    if not acc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No such account: {no}")
    if acc.is_parent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{no} {acc.name} is a heading. Budget the accounts under it — a "
            "heading is their sum, and budgeting both counts it twice.")
    return acc


def _span(year: int, month: int | None) -> tuple[date_t, date_t]:
    if month:
        return (date_t(year, month, 1),
                date_t(year, month, monthrange(year, month)[1]))
    return date_t(year, 1, 1), date_t(year, 12, 31)


def _out(b: Budget, name: str | None = None) -> dict:
    return {
        "id": str(b.id), "period_year": b.period_year,
        "period_month": b.period_month, "account_no": b.account_no,
        "account_name": name, "amount": float(b.amount or 0),
        "notes": b.notes,
    }


async def _names(db: AsyncSession, numbers: set[str]) -> dict[str, str]:
    numbers = {n for n in numbers if n}
    if not numbers:
        return {}
    rows = (await db.scalars(
        select(Account).where(Account.account_no.in_(numbers)))).all()
    return {a.account_no: a.name for a in rows}


class BudgetIn(BaseModel):
    period_year: int
    period_month: int | None = None
    account_no: str
    amount: float
    notes: str | None = None


@router.get("")
async def list_budgets(db: AsyncSession = Depends(get_db),
                       user: User = Depends(_READERS),
                       year: int | None = None,
                       month: int | None = None,
                       annual_only: bool = False):
    stmt = select(Budget)
    if year:
        stmt = stmt.where(Budget.period_year == year)
    if month:
        stmt = stmt.where(Budget.period_month == month)
    if annual_only:
        stmt = stmt.where(Budget.period_month.is_(None))
    rows = (await db.scalars(
        stmt.order_by(Budget.period_year.desc(),
                      Budget.period_month.asc().nulls_first(),
                      Budget.account_no.asc()))).all()
    names = await _names(db, {r.account_no for r in rows})
    return [_out(r, names.get(r.account_no)) for r in rows]


@router.post("", status_code=201)
async def set_budget(payload: BudgetIn,
                     db: AsyncSession = Depends(get_db),
                     user: User = Depends(_DESK)):
    """Set a figure for one account and one period.

    Setting one that already exists replaces it rather than refusing —
    a budget is revised far more often than it is created, and making the
    caller find out whether it exists first would be ceremony.
    """
    month = payload.period_month
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month is 1–12, or none for the year.")
    acc = await _account(db, payload.account_no)
    amount = round(float(payload.amount or 0), 2)
    if amount < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A budget is nothing or more.")
    existing = await db.scalar(select(Budget).where(
        Budget.period_year == payload.period_year,
        Budget.period_month.is_(None) if month is None
        else Budget.period_month == month,
        Budget.account_no == acc.account_no))
    if existing:
        existing.amount = amount
        if payload.notes is not None:
            existing.notes = (payload.notes or "").strip() or None
        await db.flush()
        await audit_record(db, actor=user, action="update", entity="budget",
                           entity_id=existing.id, after={"amount": amount})
        return _out(existing, acc.name)

    row = Budget(period_year=payload.period_year, period_month=month,
                 account_no=acc.account_no, amount=amount,
                 notes=(payload.notes or "").strip() or None,
                 created_by=user.id)
    db.add(row)
    await db.flush()
    await audit_record(db, actor=user, action="create", entity="budget",
                       entity_id=row.id,
                       after={"account_no": acc.account_no, "amount": amount})
    return _out(row, acc.name)


@router.delete("/{budget_id}")
async def delete_budget(budget_id: UUID,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(_DESK)):
    row = await db.get(Budget, budget_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    await audit_record(db, actor=user, action="delete", entity="budget",
                       entity_id=row.id,
                       before={"account_no": row.account_no,
                               "amount": float(row.amount or 0)})
    await db.delete(row)
    await db.flush()
    return {"ok": True}


@router.get("/monitor")
async def monitor(db: AsyncSession = Depends(get_db),
                  user: User = Depends(_READERS),
                  year: int | None = None,
                  month: int | None = None,
                  over_only: bool = False):
    """Monitor Anggaran — budget against actual, for one period.

    The actual comes from posted journal lines over the same span, signed
    the way the account is read: spending on an expense account counts up,
    a credit note counts down. Accounts with activity but no budget are
    listed too, at zero — an unbudgeted cost is the finding, not a row to
    leave out.
    """
    year = year or date_t.today().year
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month is 1–12.")
    start, end = _span(year, month)

    # The budget side. A month falls back to a twelfth of the annual figure
    # when it has none of its own, and says so.
    monthly = {}
    if month:
        rows = (await db.scalars(select(Budget).where(
            Budget.period_year == year, Budget.period_month == month))).all()
        monthly = {r.account_no: float(r.amount or 0) for r in rows}
    else:
        rows = (await db.execute(
            select(Budget.account_no, func.coalesce(func.sum(Budget.amount), 0))
            .where(Budget.period_year == year,
                   Budget.period_month.is_not(None))
            .group_by(Budget.account_no))).all()
        monthly = {no: float(total) for no, total in rows}

    annual_rows = (await db.scalars(select(Budget).where(
        Budget.period_year == year, Budget.period_month.is_(None)))).all()
    annual = {r.account_no: float(r.amount or 0) for r in annual_rows}

    # The actual side, from the ledger itself.
    actual_rows = (await db.execute(
        select(JournalLine.account_no, JournalLine.account_type,
               func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
        .where(JournalEntry.is_posted.is_(True),
               JournalEntry.entry_date >= start,
               JournalEntry.entry_date <= end)
        .group_by(JournalLine.account_no, JournalLine.account_type))).all()
    actual: dict[str, float] = {}
    types: dict[str, str] = {}
    for no, kind, debit, credit in actual_rows:
        types[no] = kind
        signed = (float(credit) - float(debit)) if kind in CREDIT_NORMAL \
            else (float(debit) - float(credit))
        actual[no] = round(actual.get(no, 0.0) + signed, 2)

    numbers = set(monthly) | set(annual) | set(actual)
    names = await _names(db, numbers)

    items = []
    total_budget = total_actual = 0.0
    for no in sorted(numbers):
        if no in monthly:
            budget, basis = monthly[no], "monthly" if month else "monthly total"
        elif no in annual:
            budget = round(annual[no] / 12, 2) if month else annual[no]
            basis = "annual pro-rated" if month else "annual"
        else:
            budget, basis = 0.0, "unbudgeted"
        spent = actual.get(no, 0.0)
        variance = round(budget - spent, 2)
        over = budget > 0 and spent > budget
        if over_only and not over:
            continue
        total_budget = round(total_budget + budget, 2)
        total_actual = round(total_actual + spent, 2)
        items.append({
            "account_no": no, "account_name": names.get(no),
            "account_type": types.get(no),
            "budget": budget, "basis": basis, "actual": spent,
            "variance": variance,
            "used_pct": round(spent / budget * 100, 1) if budget else None,
            "over": over,
        })
    return {
        "period_year": year, "period_month": month,
        "from": start, "to": end,
        "total_budget": total_budget, "total_actual": total_actual,
        "total_variance": round(total_budget - total_actual, 2),
        "items": items,
    }


class TransferIn(BaseModel):
    period_year: int
    period_month: int | None = None
    from_account_no: str
    to_account_no: str
    amount: float
    on: date_t | None = None
    memo: str | None = None


@router.get("/transfers")
async def list_transfers(db: AsyncSession = Depends(get_db),
                         user: User = Depends(_READERS),
                         year: int | None = None):
    stmt = select(BudgetTransfer)
    if year:
        stmt = stmt.where(BudgetTransfer.period_year == year)
    rows = (await db.scalars(
        stmt.order_by(BudgetTransfer.created_at.desc()))).all()
    names = await _names(db, {r.from_account_no for r in rows}
                         | {r.to_account_no for r in rows})
    return [{
        "id": str(r.id), "period_year": r.period_year,
        "period_month": r.period_month,
        "from_account_no": r.from_account_no,
        "from_account_name": names.get(r.from_account_no),
        "to_account_no": r.to_account_no,
        "to_account_name": names.get(r.to_account_no),
        "amount": float(r.amount or 0), "moved_on": r.moved_on, "memo": r.memo,
    } for r in rows]


@router.post("/transfer", status_code=201)
async def transfer(payload: TransferIn,
                   db: AsyncSession = Depends(get_db),
                   user: User = Depends(_DESK)):
    """Move budget between two accounts in the same period.

    No journal — nothing has been spent, only re-allocated. What moves is
    the yardstick, which is why the move itself is recorded: a variance
    that looks healthy only because the budget was shifted last week should
    be able to say so.
    """
    month = payload.period_month
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month is 1–12.")
    src = await _account(db, payload.from_account_no)
    dst = await _account(db, payload.to_account_no)
    if src.account_no == dst.account_no:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That is the same account on both sides.")
    amount = round(float(payload.amount or 0), 2)
    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A transfer needs an amount.")

    def _where(account_no: str):
        return (Budget.period_year == payload.period_year,
                Budget.period_month.is_(None) if month is None
                else Budget.period_month == month,
                Budget.account_no == account_no)

    from_row = await db.scalar(select(Budget).where(*_where(src.account_no)))
    have = float(from_row.amount or 0) if from_row else 0.0
    if have < amount:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{src.account_no} {src.name} has {have:,.2f} budgeted for that "
            f"period, not {amount:,.2f}. Moving more than is there would be "
            "an increase wearing a transfer's clothes — the record would be "
            "wrong about where it came from.")
    from_row.amount = round(have - amount, 2)

    to_row = await db.scalar(select(Budget).where(*_where(dst.account_no)))
    if to_row:
        to_row.amount = round(float(to_row.amount or 0) + amount, 2)
    else:
        to_row = Budget(period_year=payload.period_year, period_month=month,
                        account_no=dst.account_no, amount=amount,
                        created_by=user.id)
        db.add(to_row)

    move = BudgetTransfer(
        period_year=payload.period_year, period_month=month,
        from_account_no=src.account_no, to_account_no=dst.account_no,
        amount=amount, moved_on=payload.on or date_t.today(),
        memo=(payload.memo or "").strip() or None, actor_id=user.id)
    db.add(move)
    await db.flush()
    await audit_record(db, actor=user, action="transfer", entity="budget",
                       entity_id=move.id,
                       after={"from": src.account_no, "to": dst.account_no,
                              "amount": amount})
    names = {src.account_no: src.name, dst.account_no: dst.name}
    return {
        "ok": True, "id": str(move.id),
        "from": _out(from_row, names.get(from_row.account_no)),
        "to": _out(to_row, names.get(to_row.account_no)),
        "amount": amount,
    }
