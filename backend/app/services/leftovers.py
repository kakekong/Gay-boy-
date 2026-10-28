"""Postings whose record has been deleted — and taking them off the books.

The director's data clean-up deletes test records with everything under them.
It took a deleted invoice's payments with it (they cascade) but not their
ledger lines, which point at the payment rather than the invoice; nor did it
take any deleted line's amount back off its account. So the books kept test
money nothing explains — Piutang went billions below zero on payments of
invoices that no longer exist, and a new invoice that later took the freed
number seemed to have been paid them.

A posting is left over when the record its `source_id` names is gone. Taking
it off removes every line of that posting (both sides) and moves each
account's balance back by what the line had moved it.
"""
from __future__ import annotations

import importlib
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.finance import LedgerEntry
from app.services.account_history import SOURCES


async def find(db: AsyncSession) -> list[dict]:
    """Every left-over posting, one entry per (source_type, source_id)."""
    out: list[dict] = []
    for kind, (mod, cls, _fk, _path) in SOURCES.items():
        model = getattr(importlib.import_module(mod), cls)
        rows = (await db.scalars(select(LedgerEntry).where(
            LedgerEntry.source_type == kind, LedgerEntry.source_id.is_not(None),
            LedgerEntry.source_id.not_in(select(model.id))))).all()
        groups: dict = defaultdict(list)
        for r in rows:
            groups[r.source_id].append(r)
        for sid, lines in groups.items():
            out.append({
                "source_type": kind, "source_id": str(sid),
                "ref": next((x.source_ref for x in lines if x.source_ref), None),
                "date": min(x.entry_date for x in lines),
                "lines": [{"id": str(x.id), "account_no": x.account_no,
                           "account_name": x.account_name, "amount": float(x.amount or 0),
                           "memo": x.memo} for x in lines],
            })
    out.sort(key=lambda g: (g["date"], g["ref"] or ""))
    return out


async def remove(db: AsyncSession, *, source_type: str, source_id) -> dict:
    """Take one left-over posting off the books: its lines go, and each
    account moves back by what the line had moved it."""
    if source_type not in SOURCES:
        raise ValueError("That kind of posting can't be taken off here.")
    mod, cls, _fk, _path = SOURCES[source_type]
    model = getattr(importlib.import_module(mod), cls)
    if await db.get(model, source_id) is not None:
        raise ValueError("Its record still exists — this posting isn't left over.")
    lines = (await db.scalars(select(LedgerEntry).where(
        LedgerEntry.source_type == source_type, LedgerEntry.source_id == source_id))).all()
    if not lines:
        raise LookupError("Nothing on the books for that.")
    moved: dict[str, float] = defaultdict(float)
    for r in lines:
        moved[r.account_no] += float(r.amount or 0)
    for no, amt in moved.items():
        acc = await db.scalar(select(Account).where(Account.account_no == no))
        if acc is not None:
            acc.balance = round(float(acc.balance or 0) - amt, 2)
    removed = [{"account_no": r.account_no, "amount": float(r.amount or 0),
                "memo": r.memo, "date": r.entry_date.isoformat()} for r in lines]
    for r in lines:
        await db.delete(r)
    await db.flush()
    return {"ref": next((r.source_ref for r in lines if r.source_ref), None),
            "lines": removed}
