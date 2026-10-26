"""Chart of Accounts endpoints."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user  # noqa: F401  (kept for symmetry)
from app.core.permissions import Role, require, require_min
from app.models.account import Account
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)

# Writes (create / edit / delete / seed) stay restricted to admin and the
# director — they shape the books. Reads (list / detail / types / export) are
# also visible to finance and management, who need the CoA to do their job
# without being able to change it.
_admin_or_director = require(Role.ADMIN, Role.DIRECTOR)
_coa_viewer = require(
    Role.ADMIN, Role.DIRECTOR, Role.FINANCE, Role.MANAGER,
)


ACCOUNT_TYPES = [
    "Cash & Bank", "Receivable", "Inventory", "Other Current Asset",
    "Fixed Asset", "Accumulated Depreciation",
    "Payable", "Other Current Liability", "Long Term Liability",
    "Equity",
    "Revenue", "Cost Of Good Sold", "Expense",
    "Other Income", "Other Expense",
]

ACCOUNT_NO_RE = re.compile(r"^[A-Za-z0-9\-]+$")


# ─── Schemas ─────────────────────────────────────────────────────────────────

class AccountIn(BaseModel):
    account_no: str
    name: str
    name_en: str | None = None
    account_type: str
    balance: float = 0
    parent_account_no: str | None = None
    is_parent: bool = False
    is_suspended: bool = False
    level: int = 0
    is_tax: bool = False
    description: str | None = None


class AccountPatch(BaseModel):
    name: str | None = None
    name_en: str | None = None
    account_type: str | None = None
    balance: float | None = None
    parent_account_no: str | None = None
    is_parent: bool | None = None
    is_suspended: bool | None = None
    is_tax: bool | None = None
    description: str | None = None


class AccountOut(AccountIn):
    id: UUID
    # Laba/Rugi Tahun Berjalan: the balance shown is worked out, not stored.
    computed: bool = False
    model_config = {"from_attributes": True}


async def _out(db: AsyncSession, rows) -> list[AccountOut]:
    """Accounts as the page shows them — the profit line with its figure."""
    from app.services.financials import EARNINGS_ACCOUNT
    out = [AccountOut.model_validate(r) for r in rows]
    if any(o.account_no == EARNINGS_ACCOUNT for o in out):
        earned = (await current_earnings_totals(db))["net_income"]
        for o in out:
            if o.account_no == EARNINGS_ACCOUNT:
                o.balance, o.computed = round(earned, 2), True
    return out


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_no(value: str) -> None:
    if not ACCOUNT_NO_RE.match(value or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Account No must contain only letters, digits, and dashes.")


def _validate_type(value: str) -> None:
    if value not in ACCOUNT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Invalid account_type. Expected one of: {', '.join(ACCOUNT_TYPES)}")


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/types")
async def types(_user: User = Depends(_coa_viewer)):
    return ACCOUNT_TYPES


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(_coa_viewer),
    account_type: str | None = None,
    suspended: str | None = Query(None, description="all | active | suspended"),
    q: str | None = None,
    limit: int = 1000,
):
    stmt = select(Account).order_by(Account.account_no.asc()).limit(limit)
    if account_type and account_type != "All":
        stmt = stmt.where(Account.account_type == account_type)
    if suspended == "active":
        stmt = stmt.where(Account.is_suspended.is_(False))
    elif suspended == "suspended":
        stmt = stmt.where(Account.is_suspended.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Account.account_no.ilike(like)) | (Account.name.ilike(like)))
    rows = (await db.scalars(stmt)).all()
    return await _out(db, rows)


def _idr(n) -> str:
    return "Rp " + f"{int(round(float(n or 0))):,}".replace(",", ".")


async def _coa_sections(db: AsyncSession) -> list[dict]:
    rows = (await db.scalars(select(Account).order_by(Account.account_no.asc()))).all()
    out = [[r.account_no, r.name + (f" — {EARNINGS_NAME} (computed)" if r.computed else ""),
            r.account_type, _idr(r.balance)] for r in await _out(db, rows)]
    return [{
        "name": "Chart of Accounts",
        "headers": ["Account No", "Name", "Type", "Balance"],
        "rows": out,
    }]


from app.services.financials import EARNINGS_TITLE as EARNINGS_NAME  # noqa: E402


async def current_earnings_totals(db: AsyncSession) -> dict:
    """Every revenue account less every cost and expense account, from the
    balances as they stand — the profit not yet closed into equity. Computed
    each time, never posted: the P&L ends on this figure and the balance
    sheet carries it under equity."""
    from app.services.financials import pnl_from_balances
    return (await pnl_from_balances(db))["totals"]


@router.get("/export.pdf")
async def export_coa_pdf(db: AsyncSession = Depends(get_db),
                         _user: User = Depends(_coa_viewer)):
    from app.services.tabular_export import render_pdf
    data = render_pdf("Chart of Accounts", await _coa_sections(db))
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="chart-of-accounts.pdf"'})


@router.get("/export.xlsx")
async def export_coa_xlsx(db: AsyncSession = Depends(get_db),
                          _user: User = Depends(_coa_viewer)):
    from app.services.tabular_export import render_xlsx
    data = render_xlsx("Chart of Accounts", await _coa_sections(db))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="chart-of-accounts.xlsx"'},
    )


@router.get("/current-earnings")
async def current_earnings(db: AsyncSession = Depends(get_db),
                           _user: User = Depends(_coa_viewer)):
    from app.services.financials import EARNINGS_ACCOUNT
    acc = await db.scalar(select(Account).where(Account.account_no == EARNINGS_ACCOUNT))
    return {"name": EARNINGS_NAME, "account_no": EARNINGS_ACCOUNT,
            "account_name": acc.name if acc else None,
            **await current_earnings_totals(db)}


# ─── Deleted accounts ────────────────────────────────────────────────────────
# Deleting writes the account and its lines to a file in the document store
# (Cloudflare R2) — see services/account_archive. Kept here for a week, then
# only the file; either way it can be restored.

def _archive_out(a, now) -> dict:
    from app.services.account_archive import GRACE
    return {
        "id": str(a.id), "account_no": a.account_no, "name": a.name,
        "account_type": a.account_type, "balance": float(a.balance or 0),
        "entry_count": a.entry_count, "reason": a.reason,
        "deleted_at": a.deleted_at, "deleted_by": a.deleted_by_name,
        "kept_until": a.deleted_at + GRACE,
        "in_database": a.data is not None,
        "has_file": bool(a.storage_path),
        "restored_at": a.restored_at, "restored_by": a.restored_by_name,
    }


@router.get("/archives")
async def list_archives(db: AsyncSession = Depends(get_db),
                        _user: User = Depends(require(Role.DIRECTOR))):
    from datetime import UTC, datetime

    from app.models.account import AccountArchive
    from app.services.account_archive import purge_expired
    await purge_expired(db)
    rows = (await db.scalars(select(AccountArchive)
                             .order_by(AccountArchive.deleted_at.desc()).limit(500))).all()
    now = datetime.now(UTC)
    return [_archive_out(a, now) for a in rows]


@router.post("/archives/{archive_id}/restore")
async def restore_archived(archive_id: UUID, db: AsyncSession = Depends(get_db),
                           user: User = Depends(require(Role.DIRECTOR))):
    from app.models.account import AccountArchive
    from app.services.account_archive import ArchiveError, restore_archive
    arc = await db.get(AccountArchive, archive_id)
    if not arc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    from_file = arc.data is None
    try:
        acc = await restore_archive(db, arc, actor=user)
    except ArchiveError as e:
        raise HTTPException(e.code, str(e))
    await audit_record(db, actor=user, action="restore", entity="account", entity_id=acc.id,
                       after={"account_no": acc.account_no, "from_file": from_file})
    return {"ok": True, "account_no": acc.account_no, "from_file": from_file}


@router.get("/archives/{archive_id}/file")
async def download_archive(archive_id: UUID, db: AsyncSession = Depends(get_db),
                           _user: User = Depends(require(Role.DIRECTOR))):
    from app.models.account import AccountArchive
    from app.services import storage
    arc = await db.get(AccountArchive, archive_id)
    if not arc or not arc.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    blob = await storage.load(arc.storage_path)
    if not blob:
        raise HTTPException(status.HTTP_410_GONE, "The archive file can't be found in storage.")
    return Response(content=blob, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{arc.account_no}-deleted.json"'})


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      _user: User = Depends(_coa_viewer)):
    obj = await db.get(Account, account_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return obj


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(payload: AccountIn,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(_admin_or_director)):
    _validate_no(payload.account_no)
    _validate_type(payload.account_type)

    # uniqueness
    existing = await db.scalar(select(Account).where(Account.account_no == payload.account_no))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Account No already exists.")

    # parent must exist if given
    if payload.parent_account_no:
        parent = await db.scalar(select(Account).where(Account.account_no == payload.parent_account_no))
        if not parent:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent account does not exist.")
        # auto-derive level if not provided
        if payload.level == 0:
            payload.level = parent.level + 1

    obj = Account(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await audit_record(db, actor=_user, action="create", entity="account",
                       entity_id=obj.id, after=payload.model_dump())
    return obj


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(account_id: UUID,
                         payload: AccountPatch,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(_admin_or_director)):
    obj = await db.get(Account, account_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    data = payload.model_dump(exclude_unset=True)
    from app.services.financials import EARNINGS_ACCOUNT
    if obj.account_no == EARNINGS_ACCOUNT:
        # Its balance is worked out; the figure the form sends back is that.
        data.pop("balance", None)
    # Setting an account's balance by hand is the director's: it moves the
    # books with nothing on the other side. It shows in the account's ledger
    # as "set by hand", with who and when.
    if ("balance" in data and Role(_user.role) != Role.DIRECTOR
            and abs(float(data["balance"] or 0) - float(obj.balance or 0)) >= 0.005):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the director can change an account's balance.")
    if "account_type" in data:
        _validate_type(data["account_type"])
    if "parent_account_no" in data and data["parent_account_no"]:
        parent = await db.scalar(select(Account).where(Account.account_no == data["parent_account_no"]))
        if not parent:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent account does not exist.")
        if parent.account_no == obj.account_no:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account cannot be its own parent.")
    before = {k: getattr(obj, k) for k in data.keys()}
    for k, v in data.items():
        setattr(obj, k, v)
    await audit_record(db, actor=_user, action="update", entity="account",
                       entity_id=obj.id, before=before, after=data)
    return obj


@router.post("/{account_no}/clear-unrecorded")
async def clear_unrecorded(account_no: str,
                           db: AsyncSession = Depends(get_db),
                           _user: User = Depends(require(Role.DIRECTOR))):
    """Remove the part of a balance nothing on record explains — the "No
    record" row on the account's ledger (brought in with the chart, or test
    figures). The balance drops by exactly that amount, and the row leaves
    the ledger: nothing that happened is unwritten. The audit log keeps it."""
    from app.services.account_history import account_events

    acc = await db.scalar(select(Account).where(Account.account_no == account_no))
    if not acc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    events = (await account_events(db, [acc]))[acc.account_no]
    rest = next((e["delta"] for e in events if e["kind"] == "unrecorded"), 0.0)
    if abs(rest) < 0.005:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Everything on this account is on record — nothing to remove.")
    before = float(acc.balance or 0)
    acc.balance = round(before - rest, 2)
    await audit_record(db, actor=_user, action="clear_unrecorded", entity="account",
                       entity_id=acc.id, before={"balance": before},
                       after={"balance": float(acc.balance), "removed": rest})
    await db.flush()
    return {"ok": True, "removed": rest, "balance": float(acc.balance)}


@router.delete("/{account_id}")
async def delete_account(account_id: UUID,
                         reason: str | None = Query(None, max_length=500),
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(require(Role.DIRECTOR))):
    """The director deletes an account. It and every line posted to it go to
    a file in the document store and leave the database; for a week a copy
    is also kept here. Either way it can be restored (Recently deleted)."""
    from app.services.account_archive import ArchiveError, archive_account, purge_expired
    obj = await db.get(Account, account_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    acc_id, no, bal = obj.id, obj.account_no, float(obj.balance or 0)
    try:
        arc = await archive_account(db, obj, actor=user, reason=reason)
    except ArchiveError as e:
        raise HTTPException(e.code, str(e))
    await audit_record(db, actor=user, action="delete", entity="account", entity_id=acc_id,
                       before={"account_no": no, "balance": bal},
                       after={"archive_id": str(arc.id), "file": arc.storage_path})
    await purge_expired(db)
    return {"ok": True, "archive_id": str(arc.id), "entries": arc.entry_count}


@router.post("/seed")
async def seed(db: AsyncSession = Depends(get_db),
               _user: User = Depends(_admin_or_director)):
    """Idempotent seed: inserts the default Indonesian Chart of Accounts."""
    from app.scripts.coa_seed import seed_coa
    created = await seed_coa(db)
    return {"created": created}
