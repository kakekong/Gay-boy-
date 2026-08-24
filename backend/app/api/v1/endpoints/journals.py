"""Jurnal Umum and Buku Besar — the general journal and the account ledger.

Two views of one record. The journal is chronological: every entry, in the
order it was written, with both sides of each. The account ledger takes one
account and walks it — opening balance, every line that touched it in the
period, a running balance down the page. That second one is what somebody
means when they ask "where did this number come from", and until now there
was no answer: balances moved and nothing said why.
"""

from datetime import date as date_t
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.journal import JournalEntry, JournalLine, signed_delta
from app.models.user import User
from app.services import journal as journal_svc

router = APIRouter()

# Who keeps the books. Finance writes them; the director signs off on the
# company's numbers and so may write too. A manager reads without writing —
# oversight, not bookkeeping.
_KEEPERS = require(Role.FINANCE, Role.DIRECTOR)
_READERS = require(Role.FINANCE, Role.DIRECTOR, Role.MANAGER)


class LineIn(BaseModel):
    account_no: str
    debit: float = 0
    credit: float = 0
    memo: str | None = None
    customer_id: UUID | None = None
    sales_pic_id: UUID | None = None


class EntryIn(BaseModel):
    entry_date: date_t | None = None
    memo: str | None = None
    lines: list[LineIn] = []
    # Write it and apply it in one action, which is what the form does. A
    # draft is for an entry somebody is still assembling.
    post: bool = True


class EntryPatch(BaseModel):
    entry_date: date_t | None = None
    memo: str | None = None
    lines: list[LineIn] | None = None


def _entry_out(e: JournalEntry, *, with_lines: bool = True) -> dict:
    total = sum(float(ln.debit or 0) for ln in (e.lines or []))
    out = {
        "id": str(e.id), "number": e.number, "entry_date": e.entry_date,
        "memo": e.memo, "source_type": e.source_type,
        "source_ref": e.source_ref,
        "source_id": str(e.source_id) if e.source_id else None,
        "is_posted": e.is_posted, "posted_at": e.posted_at,
        "total": total,
        "reverses_id": str(e.reverses_id) if e.reverses_id else None,
        "reversed_by_id": str(e.reversed_by_id) if e.reversed_by_id else None,
        "created_at": e.created_at,
    }
    if with_lines:
        out["lines"] = [{
            "line_no": ln.line_no, "account_no": ln.account_no,
            "account_name": ln.account_name, "account_type": ln.account_type,
            "debit": float(ln.debit or 0), "credit": float(ln.credit or 0),
            "memo": ln.memo,
        } for ln in (e.lines or [])]
    return out


def _period_bounds(period: str | None) -> tuple[date_t | None, date_t | None]:
    """'2026-03' → the first and last day of that month."""
    if not period:
        return None, None
    try:
        y, m = (int(x) for x in period.split("-")[:2])
        start = date_t(y, m, 1)
        end = date_t(y + 1, 1, 1) if m == 12 else date_t(y, m + 1, 1)
        return start, end
    except (ValueError, TypeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "period must look like 2026-03") from e


@router.get("")
async def list_entries(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_READERS),
    period: str | None = None,
    date_from: date_t | None = None,
    date_to: date_t | None = None,
    source_type: str | None = None,
    posted: bool | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    stmt = select(JournalEntry)
    p_start, p_end = _period_bounds(period)
    if p_start:
        stmt = stmt.where(JournalEntry.entry_date >= p_start,
                          JournalEntry.entry_date < p_end)
    if date_from:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    if source_type:
        stmt = stmt.where(JournalEntry.source_type == source_type)
    if posted is not None:
        stmt = stmt.where(JournalEntry.is_posted.is_(posted))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(JournalEntry.number.ilike(like),
                              JournalEntry.memo.ilike(like),
                              JournalEntry.source_ref.ilike(like)))
    total = await db.scalar(
        select(func.count()).select_from(stmt.subquery())
    ) or 0
    rows = (await db.scalars(
        stmt.order_by(JournalEntry.entry_date.desc(),
                      JournalEntry.number.desc())
        .limit(min(limit, 500)).offset(offset)
    )).all()
    return {"total": total, "items": [_entry_out(e) for e in rows]}


@router.post("", status_code=201)
async def create_entry(payload: EntryIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_KEEPERS)):
    """Write a journal entry. It balances or it is refused."""
    try:
        entry = await journal_svc.create_entry(
            db,
            entry_date=payload.entry_date or date_t.today(),
            rows=[ln.model_dump() for ln in payload.lines],
            memo=payload.memo,
            source_type="manual",
            created_by=user.id,
            post=payload.post,
            posted_by=user.id,
        )
    except journal_svc.JournalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await audit_record(db, actor=user, action="create", entity="journal_entry",
                       entity_id=entry.id,
                       after={"number": entry.number, "posted": entry.is_posted})
    return _entry_out(entry)


@router.post("/opening-balances", status_code=201)
async def opening_balances(
    on: date_t | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_KEEPERS),
):
    """Write down where the balances that were already here came from.

    The chart of accounts arrived carrying balances — brought over from
    whatever kept the books before this. Open one of those accounts and the
    ledger that is meant to explain its balance shows nothing: neither number
    is wrong, there is simply no record of the starting point.

    This posts that record, once: every account's balance as of the day the
    books opened here, carried to opening-balance equity so it balances like
    any other entry. It changes no balance — they are already right — and
    stays out of the profit report, so last year's trading is not counted as
    this month's.
    """
    from app.services.journal import post_opening_balances
    try:
        entry = await post_opening_balances(
            db, on=on or date_t.today(), actor_id=user.id)
    except journal_svc.JournalError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    if entry is None:
        return {"ok": True, "written": False,
                "detail": "Every account is at zero — there is nothing to "
                          "write down."}
    await audit_record(db, actor=user, action="opening_balances",
                       entity="journal_entry", entity_id=entry.id,
                       after={"number": entry.number,
                              "lines": len(entry.lines)})
    return {"ok": True, "written": True, **_entry_out(entry)}


@router.get("/account/{account_no}")
async def account_ledger(
    account_no: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_READERS),
    period: str | None = None,
    date_from: date_t | None = None,
    date_to: date_t | None = None,
    limit: int = 500,
):
    """Buku Besar: one account, walked.

    The opening balance is everything posted before the window; the lines are
    what happened inside it; the running balance is the two added up as you
    read down. Without the opening figure the closing one is unexplained,
    which is the reason a plain filtered list of movements is never enough.
    """
    acc = await db.scalar(select(Account).where(Account.account_no == account_no))
    if not acc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    start, end = _period_bounds(period)
    if date_from:
        start = date_from
    if date_to:
        end = date_to
    if end and not period:
        # An inclusive `date_to` reads better on a form than an exclusive one.
        from datetime import timedelta
        end = end + timedelta(days=1)

    base = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
        .where(JournalLine.account_no == account_no,
               JournalEntry.is_posted.is_(True))
    )
    opening = 0.0
    if start:
        prior = (await db.execute(
            base.where(JournalEntry.entry_date < start)
        )).all()
        opening = sum(signed_delta(ln.account_type, ln.debit, ln.credit)
                      for ln, _e in prior)

    window = base
    if start:
        window = window.where(JournalEntry.entry_date >= start)
    if end:
        window = window.where(JournalEntry.entry_date < end)
    rows = (await db.execute(
        window.order_by(JournalEntry.entry_date.asc(), JournalEntry.number.asc(),
                        JournalLine.line_no.asc()).limit(min(limit, 2000))
    )).all()

    running = opening
    items = []
    total_d = total_c = 0.0
    for ln, e in rows:
        delta = signed_delta(ln.account_type, ln.debit, ln.credit)
        running += delta
        total_d += float(ln.debit or 0)
        total_c += float(ln.credit or 0)
        items.append({
            "journal_id": str(e.id), "number": e.number,
            "entry_date": e.entry_date,
            "memo": ln.memo or e.memo,
            "source_type": e.source_type, "source_ref": e.source_ref,
            "debit": float(ln.debit or 0), "credit": float(ln.credit or 0),
            "balance": round(running, 2),
        })
    return {
        "account": {"account_no": acc.account_no, "name": acc.name,
                    "account_type": acc.account_type,
                    "balance": float(acc.balance or 0)},
        "opening_balance": round(opening, 2),
        "closing_balance": round(running, 2),
        "total_debit": round(total_d, 2), "total_credit": round(total_c, 2),
        "items": items,
    }


@router.get("/{entry_id}")
async def get_entry(entry_id: UUID,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(_READERS)):
    e = await db.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    return _entry_out(e)


@router.patch("/{entry_id}")
async def update_entry(entry_id: UUID, payload: EntryPatch,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_KEEPERS)):
    """Correct a draft. A posted entry is corrected by reversing it."""
    e = await db.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    if e.is_posted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{e.number} is posted — the balances already moved. Reverse it "
            "and post a correction; that way both stay on the record.",
        )
    data = payload.model_dump(exclude_unset=True)
    if "entry_date" in data and data["entry_date"]:
        e.entry_date = data["entry_date"]
    if "memo" in data:
        e.memo = data["memo"]
    if data.get("lines") is not None:
        try:
            e.lines = await journal_svc.build_lines(db, data["lines"])
        except journal_svc.JournalError as err:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err)) from err
    await db.flush()
    return _entry_out(e)


@router.post("/{entry_id}/post")
async def post_entry(entry_id: UUID,
                     db: AsyncSession = Depends(get_db),
                     user: User = Depends(_KEEPERS)):
    e = await db.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    if e.is_posted:
        return {"ok": True, "already": True, **_entry_out(e)}
    await journal_svc.post_entry(db, e, actor_id=user.id)
    await audit_record(db, actor=user, action="post", entity="journal_entry",
                       entity_id=e.id, after={"number": e.number})
    return {"ok": True, **_entry_out(e)}


@router.post("/{entry_id}/reverse")
async def reverse_entry(entry_id: UUID,
                        reason: str | None = None,
                        on: date_t | None = None,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(_KEEPERS)):
    """Post the mirror image, leaving both entries on the record."""
    e = await db.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    try:
        mirror = await journal_svc.reverse_entry(
            db, e, actor_id=user.id, reason=reason, on=on)
    except journal_svc.JournalError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    await audit_record(db, actor=user, action="reverse", entity="journal_entry",
                       entity_id=e.id,
                       after={"number": e.number, "reversal": mirror.number})
    return {"ok": True, "reversal": _entry_out(mirror)}


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_KEEPERS)):
    """Throw away a draft. A posted entry is never deleted — reverse it."""
    e = await db.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    if e.is_posted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{e.number} is posted and stays on the record. Reverse it "
            "instead — a deleted entry is a hole nobody can explain.",
        )
    before = {"number": e.number, "memo": e.memo}
    await db.delete(e)
    await db.flush()
    await audit_record(db, actor=user, action="delete", entity="journal_entry",
                       entity_id=entry_id, before=before)
    return None
