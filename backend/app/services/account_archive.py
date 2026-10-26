"""Deleting an account from the chart — and getting it back.

The director deletes an account: the account and every line the app ever
posted to it (ledger_entries) are written to one JSON file in the document
store — Cloudflare R2 in production — and taken out of the database, so
neither the chart nor any report sees them any more. The balance goes with
it, the same as a balance set by hand: nothing is booked on the other side.

For a week (GRACE) the same copy is also kept in the account_archives row,
so a restore is instant and doesn't depend on the store. After that the copy
is dropped (`purge_expired`) and the row is only a pointer to the file — which
can still restore the account, exactly as it was.

What can't be deleted: a heading with accounts under it, an account the app
posts to on its own, the computed profit line, and an account a live general
journal entry uses (void the entry first — its lines are half of a balanced
entry, and taking one away would leave the other half standing alone).
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountArchive
from app.models.finance import LedgerEntry
from app.models.journal import JournalEntry, JournalLine

GRACE = timedelta(days=7)
FORMAT = "transmisi.account-archive/1"


class ArchiveError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def protected_accounts() -> dict[str, str]:
    """Accounts the app posts to by itself, and why each can't go."""
    from app.services import ledger
    from app.services.financials import EARNINGS_ACCOUNT

    out = {
        EARNINGS_ACCOUNT: "it is the computed Laba/Rugi Tahun Berjalan line",
        ledger.INVENTORY_ACCOUNT: "goods receipts post to it",
        ledger.PAYABLE_ACCOUNT: "goods receipts and supplier payments post to it",
        ledger.COGS_ACCOUNT: "the cost of paid jobs posts to it",
        ledger.FX_REALISED_ACCOUNT: "exchange differences on supplier payments post to it",
        ledger.PAYMENT_CASH_DEFAULT: "customer payments post to it by default",
        ledger.PAYMENT_RECEIVABLE: "customer payments post to it",
    }
    for key, no in ledger.DEFAULTS.items():
        out.setdefault(no, f"won quotations post their {key} to it")
    return out


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def _row(obj) -> dict:
    return {c.name: _plain(getattr(obj, c.key)) for c in obj.__table__.columns}


def _unrow(model, data: dict):
    """A row back from its JSON form, each value its column's own type."""
    kw = {}
    for c in model.__table__.columns:
        if c.name not in data:
            continue
        v = data[c.name]
        if v is not None:
            try:
                py = c.type.python_type
            except NotImplementedError:
                py = None
            if py is datetime:
                v = datetime.fromisoformat(v)
            elif py is date:
                v = date.fromisoformat(v)
            elif py is UUID:
                v = UUID(v)
        kw[c.key] = v
    return model(**kw)


async def check_deletable(db: AsyncSession, acc: Account) -> None:
    why = protected_accounts().get(acc.account_no)
    if why:
        raise ArchiveError(f"{acc.account_no} can't be deleted: {why}.")
    kids = await db.scalar(select(func.count(Account.id))
                           .where(Account.parent_account_no == acc.account_no))
    if kids:
        raise ArchiveError(f"{acc.account_no} is a heading with {kids} account(s) under it — "
                           "delete or move those first.")
    used = (await db.scalars(
        select(JournalEntry.number).join(JournalLine, JournalLine.journal_id == JournalEntry.id)
        .where(JournalLine.account_no == acc.account_no, JournalEntry.is_void.is_(False))
        .distinct().limit(5))).all()
    if used:
        raise ArchiveError(f"{acc.account_no} is used by journal entr{'y' if len(used) == 1 else 'ies'} "
                           f"{', '.join(used)} — void {'it' if len(used) == 1 else 'them'} first.")


async def archive_account(db: AsyncSession, acc: Account, *, actor, reason: str | None = None
                          ) -> AccountArchive:
    """Write the account and its lines to a file, then take them out."""
    from app.services import storage

    await check_deletable(db, acc)
    entries = (await db.scalars(select(LedgerEntry)
                                .where(LedgerEntry.account_no == acc.account_no)
                                .order_by(LedgerEntry.entry_date, LedgerEntry.created_at))).all()
    now = datetime.now(UTC)
    payload = {
        "format": FORMAT,
        "deleted_at": now.isoformat(),
        "deleted_by": getattr(actor, "full_name", None),
        "reason": reason,
        "account": _row(acc),
        "ledger_entries": [_row(e) for e in entries],
    }
    blob = json.dumps(payload, ensure_ascii=False, indent=1).encode()
    path = await storage.save(blob, filename=f"{acc.account_no}-{now:%Y%m%d-%H%M%S}.json",
                              owner_type="account-archive", owner_id=acc.account_no)

    arc = AccountArchive(
        account_no=acc.account_no, name=acc.name, account_type=acc.account_type,
        balance=float(acc.balance or 0), entry_count=len(entries), reason=reason,
        deleted_at=now, deleted_by=getattr(actor, "id", None),
        deleted_by_name=getattr(actor, "full_name", None),
        storage_path=path, data=payload,
    )
    db.add(arc)
    await db.execute(delete(LedgerEntry).where(LedgerEntry.account_no == acc.account_no))
    await db.delete(acc)
    await db.flush()
    return arc


async def restore_archive(db: AsyncSession, arc: AccountArchive, *, actor) -> Account:
    """Put a deleted account back, from the copy here or from its file."""
    from app.services import storage

    if arc.restored_at:
        raise ArchiveError(f"{arc.account_no} was already restored.")
    payload = arc.data
    if payload is None:
        blob = await storage.load(arc.storage_path) if arc.storage_path else None
        if not blob:
            raise ArchiveError("The archive file can't be found in storage any more.", 410)
        payload = json.loads(blob)
    if payload.get("format") != FORMAT:
        raise ArchiveError("That file isn't an account archive.", 400)
    no = payload["account"]["account_no"]
    if await db.scalar(select(Account.id).where(Account.account_no == no)):
        raise ArchiveError(f"There is an account numbered {no} again — rename or delete it "
                           "before restoring this one.")

    acc = _unrow(Account, payload["account"])
    db.add(acc)
    ids = [UUID(e["id"]) for e in payload["ledger_entries"] if e.get("id")]
    there = set((await db.scalars(select(LedgerEntry.id).where(LedgerEntry.id.in_(ids)))).all()) \
        if ids else set()
    for e in payload["ledger_entries"]:
        if e.get("id") and UUID(e["id"]) in there:
            continue
        db.add(_unrow(LedgerEntry, e))
    arc.restored_at = datetime.now(UTC)
    arc.restored_by_name = getattr(actor, "full_name", None)
    arc.data = None
    await db.flush()
    return acc


async def purge_expired(db: AsyncSession) -> int:
    """Past the week: drop the copy kept here; the file stays."""
    rows = (await db.scalars(select(AccountArchive).where(
        AccountArchive.data.is_not(None), AccountArchive.storage_path.is_not(None),
        AccountArchive.deleted_at < datetime.now(UTC) - GRACE))).all()
    for a in rows:
        a.data = None
        a.purged_at = datetime.now(UTC)
    if rows:
        await db.flush()
    return len(rows)
