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
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.user import User

router = APIRouter()

_admin_or_director = require(Role.ADMIN, Role.DIRECTOR)


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
    model_config = {"from_attributes": True}


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
async def types(_user: User = Depends(_admin_or_director)):
    return ACCOUNT_TYPES


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(_admin_or_director),
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
    return [AccountOut.model_validate(r) for r in rows]


def _idr(n) -> str:
    return "Rp " + f"{int(round(float(n or 0))):,}".replace(",", ".")


async def _coa_sections(db: AsyncSession) -> list[dict]:
    rows = (await db.scalars(select(Account).order_by(Account.account_no.asc()))).all()
    return [{
        "name": "Chart of Accounts",
        "headers": ["Account No", "Name", "Type", "Balance"],
        "rows": [[r.account_no, r.name, r.account_type, _idr(r.balance)] for r in rows],
    }]


@router.get("/export.pdf")
async def export_coa_pdf(db: AsyncSession = Depends(get_db),
                         _user: User = Depends(_admin_or_director)):
    from app.services.tabular_export import render_pdf
    data = render_pdf("Chart of Accounts", await _coa_sections(db))
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="chart-of-accounts.pdf"'})


@router.get("/export.xlsx")
async def export_coa_xlsx(db: AsyncSession = Depends(get_db),
                          _user: User = Depends(_admin_or_director)):
    from app.services.tabular_export import render_xlsx
    data = render_xlsx("Chart of Accounts", await _coa_sections(db))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="chart-of-accounts.xlsx"'},
    )


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      _user: User = Depends(_admin_or_director)):
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


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(_admin_or_director)):
    obj = await db.get(Account, account_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if float(obj.balance or 0) != 0:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cannot delete an account with a non-zero balance.")
    has_children = await db.scalar(
        select(func.count(Account.id)).where(Account.parent_account_no == obj.account_no)
    )
    if has_children:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cannot delete a parent account that still has children.")
    await db.delete(obj)
    return None


@router.post("/seed")
async def seed(db: AsyncSession = Depends(get_db),
               _user: User = Depends(_admin_or_director)):
    """Idempotent seed: inserts the default Indonesian Chart of Accounts."""
    from app.scripts.coa_seed import seed_coa
    created = await seed_coa(db)
    return {"created": created}
