"""Aset Tetap — the register, the monthly run, and what happens to an asset.

The register is the easy half. The hard half is that a fixed asset changes
value every month without anybody touching it, and the books only say so if
somebody posts the entry — so the month's run is the thing this module
exists for, and everything else is in service of it being right.

What that means in practice:

- **A month runs once.** The guard is a row, not a flag: the run either
  exists for that period or it does not, and a second attempt is refused
  with the number the first one posted.
- **A month can be previewed.** Finance sees what it is about to post,
  per asset, before it becomes permanent — because a depreciation run
  touches every asset at once and the alternative to previewing it is
  reversing it.
- **Disposal is arithmetic, not deletion.** Cost comes off, accumulated
  depreciation comes off, the proceeds come in, and whatever does not
  balance is the gain or the loss. That residual is the entire point of
  disposing rather than deleting: it is a real number that belongs on the
  profit report.
- **Nothing that has been depreciated is deleted.** The entries that walked
  it down are in the ledger, and a register that loses the asset they refer
  to cannot be audited.
"""

from datetime import date as date_t
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.asset import (
    METHODS, TAX_GROUPS, AssetCategory, AssetChange, AssetDepreciation,
    DepreciationRun, FixedAsset,
)
from app.models.journal import JournalEntry
from app.models.user import User
from app.services import depreciation as depr
from app.services import journal as journal_svc
from app.services.numbering import _next_suffix

router = APIRouter()

_DESK = require(Role.FINANCE, Role.DIRECTOR)
_READERS = require(Role.FINANCE, Role.DIRECTOR, Role.MANAGER)


async def _account(db: AsyncSession, account_no: str | None, *, label: str,
                   required: bool = False) -> str | None:
    if not account_no or not str(account_no).strip():
        if required:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"{label} is needed for this.")
        return None
    no = str(account_no).strip()
    acc = await db.scalar(select(Account).where(Account.account_no == no))
    if not acc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{label}: no such account {no}")
    if acc.is_parent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label}: {no} {acc.name} is a heading, not an account.")
    if acc.is_suspended:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{label}: {no} {acc.name} is suspended.")
    return no


# ------------------------------------------------------------- Kategori Aset

class CategoryIn(BaseModel):
    name: str
    scope: str = "commercial"
    tax_group: str | None = None
    method: str = "straight_line"
    useful_life_months: int = 48
    asset_account_no: str | None = None
    accum_account_no: str | None = None
    expense_account_no: str | None = None
    is_active: bool = True
    notes: str | None = None


class CategoryPatch(BaseModel):
    name: str | None = None
    method: str | None = None
    useful_life_months: int | None = None
    tax_group: str | None = None
    asset_account_no: str | None = None
    accum_account_no: str | None = None
    expense_account_no: str | None = None
    is_active: bool | None = None
    notes: str | None = None


def _cat_out(c: AssetCategory) -> dict:
    group = TAX_GROUPS.get(c.tax_group or "")
    return {
        "id": str(c.id), "name": c.name, "scope": c.scope,
        "tax_group": c.tax_group,
        "tax_group_label": group["label"] if group else None,
        "method": c.method, "useful_life_months": c.useful_life_months,
        "useful_life_years": round(c.useful_life_months / 12, 2),
        "asset_account_no": c.asset_account_no,
        "accum_account_no": c.accum_account_no,
        "expense_account_no": c.expense_account_no,
        "is_active": c.is_active, "notes": c.notes,
    }


@router.get("/tax-groups")
async def tax_groups(user: User = Depends(_READERS)):
    """The statutory groups, with the lives and rates the law fixes.

    Offered rather than typed, because these are not the company's numbers
    to choose — a Kelompok 2 asset depreciates over eight years whatever
    anyone thinks of the truck.
    """
    return [{"value": k, **v} for k, v in TAX_GROUPS.items()]


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db),
                          user: User = Depends(_READERS),
                          scope: str | None = None,
                          active_only: bool = False):
    stmt = select(AssetCategory)
    if scope:
        stmt = stmt.where(AssetCategory.scope == scope)
    if active_only:
        stmt = stmt.where(AssetCategory.is_active.is_(True))
    rows = (await db.scalars(
        stmt.order_by(AssetCategory.scope.asc(), AssetCategory.name.asc()))).all()
    return [_cat_out(c) for c in rows]


@router.post("/categories", status_code=201)
async def create_category(payload: CategoryIn,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_DESK)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give it a name.")
    scope = (payload.scope or "commercial").strip()
    if scope not in ("commercial", "tax"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "scope is 'commercial' or 'tax'.")
    method = (payload.method or "straight_line").strip()
    if method not in METHODS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"method must be one of: {', '.join(METHODS)}")
    life = int(payload.useful_life_months or 0)
    group = None
    if scope == "tax":
        group = (payload.tax_group or "").strip()
        if group not in TAX_GROUPS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A tax category is one of the statutory groups: "
                f"{', '.join(TAX_GROUPS)}.")
        spec = TAX_GROUPS[group]
        # The law sets the life and which methods are allowed; taking them
        # from the group rather than the form is the difference between a
        # fiscal category and a second commercial one.
        life = spec["years"] * 12
        if method == "declining_balance" and not spec.get("declining_pct"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{spec['label']} is straight line only — the law gives no "
                "declining rate for buildings.")
    if life <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A useful life is a number of months.")
    dup = await db.scalar(select(func.count()).select_from(AssetCategory)
                          .where(func.lower(AssetCategory.name) == name.lower(),
                                 AssetCategory.scope == scope))
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"There is already a category called “{name}”.")
    row = AssetCategory(
        name=name, scope=scope, tax_group=group, method=method,
        useful_life_months=life,
        asset_account_no=await _account(db, payload.asset_account_no,
                                        label="Akun Aset"),
        accum_account_no=await _account(db, payload.accum_account_no,
                                        label="Akun Akumulasi Penyusutan"),
        expense_account_no=await _account(db, payload.expense_account_no,
                                          label="Akun Beban Penyusutan"),
        is_active=payload.is_active,
        notes=(payload.notes or "").strip() or None,
    )
    db.add(row)
    await db.flush()
    await audit_record(db, actor=user, action="create", entity="asset_category",
                       entity_id=row.id, after={"name": name, "scope": scope})
    return _cat_out(row)


@router.patch("/categories/{category_id}")
async def update_category(category_id: UUID, payload: CategoryPatch,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_DESK)):
    row = await db.get(AssetCategory, category_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and (data["name"] or "").strip():
        row.name = data["name"].strip()
    if "method" in data:
        if data["method"] not in METHODS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"method must be one of: {', '.join(METHODS)}")
        row.method = data["method"]
    if "tax_group" in data and row.scope == "tax":
        if data["tax_group"] not in TAX_GROUPS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Not a statutory group.")
        row.tax_group = data["tax_group"]
        row.useful_life_months = TAX_GROUPS[row.tax_group]["years"] * 12
    elif "useful_life_months" in data and row.scope != "tax":
        # A fiscal category's life is the law's, not ours — so it is only
        # editable on the commercial side.
        life = int(data["useful_life_months"] or 0)
        if life <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A useful life is a number of months.")
        row.useful_life_months = life
    for field, label in (("asset_account_no", "Akun Aset"),
                         ("accum_account_no", "Akun Akumulasi Penyusutan"),
                         ("expense_account_no", "Akun Beban Penyusutan")):
        if field in data:
            setattr(row, field, await _account(db, data[field], label=label))
    if "is_active" in data:
        row.is_active = bool(data["is_active"])
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    await db.flush()
    await audit_record(db, actor=user, action="update", entity="asset_category",
                       entity_id=row.id, after=data)
    return _cat_out(row)


@router.delete("/categories/{category_id}")
async def delete_category(category_id: UUID,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_DESK)):
    row = await db.get(AssetCategory, category_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    used = await db.scalar(
        select(func.count()).select_from(FixedAsset).where(
            or_(FixedAsset.category_id == row.id,
                FixedAsset.tax_category_id == row.id)))
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{used} asset(s) are in this category. Set it inactive instead — "
            "deleting it would leave them pointing at nothing.")
    await db.delete(row)
    await db.flush()
    return {"ok": True}


# ------------------------------------------------------------- The register

class AssetIn(BaseModel):
    name: str
    category_id: UUID | None = None
    tax_category_id: UUID | None = None
    acquired_on: date_t
    cost: float
    salvage_value: float = 0
    useful_life_months: int | None = None
    method: str | None = None
    opening_accum: float = 0
    location: str | None = None
    department: str | None = None
    pic_id: UUID | None = None
    serial_no: str | None = None
    supplier: str | None = None
    notes: str | None = None
    # An asset usually arrives already booked by the purchase that bought
    # it, so the acquisition entry is off unless asked for.
    credit_account_no: str | None = None


class AssetPatch(BaseModel):
    name: str | None = None
    category_id: UUID | None = None
    tax_category_id: UUID | None = None
    location: str | None = None
    department: str | None = None
    pic_id: UUID | None = None
    serial_no: str | None = None
    supplier: str | None = None
    notes: str | None = None


async def _next_number(db: AsyncSession) -> str:
    from datetime import datetime
    prefix = f"AST-{datetime.now().year}-"
    return f"{prefix}{await _next_suffix(db, FixedAsset.number, prefix):04d}"


def _asset_out(a: FixedAsset, *, cats: dict[str, AssetCategory] | None = None,
               with_entries: bool = False) -> dict:
    cats = cats or {}
    cost = float(a.cost or 0)
    accum = float(a.accumulated_depreciation or 0)
    cat = cats.get(str(a.category_id)) if a.category_id else None
    tax_cat = cats.get(str(a.tax_category_id)) if a.tax_category_id else None
    out = {
        "id": str(a.id), "number": a.number, "name": a.name,
        "category_id": str(a.category_id) if a.category_id else None,
        "category_name": cat.name if cat else None,
        "tax_category_id": str(a.tax_category_id) if a.tax_category_id else None,
        "tax_category_name": tax_cat.name if tax_cat else None,
        "tax_group": tax_cat.tax_group if tax_cat else None,
        "acquired_on": a.acquired_on,
        "cost": cost,
        "salvage_value": float(a.salvage_value or 0),
        "useful_life_months": a.useful_life_months,
        "method": a.method,
        "opening_accum": float(a.opening_accum or 0),
        "accumulated_depreciation": accum,
        # Derived, never stored — a third number is a third thing to drift.
        "book_value": round(cost - accum, 2),
        "location": a.location, "department": a.department,
        "serial_no": a.serial_no, "supplier": a.supplier, "notes": a.notes,
        "status": a.status, "disposed_on": a.disposed_on,
        "disposal_proceeds": float(a.disposal_proceeds or 0),
        "disposal_reason": a.disposal_reason,
    }
    if with_entries:
        out["entries"] = [{
            "period_year": e.period_year, "period_month": e.period_month,
            "amount": float(e.amount or 0),
            "book_value_after": float(e.book_value_after or 0),
            "journal_id": str(e.journal_id) if e.journal_id else None,
        } for e in (a.entries or [])]
    return out


async def _cat_map(db: AsyncSession, assets: list[FixedAsset]
                   ) -> dict[str, AssetCategory]:
    ids = {a.category_id for a in assets if a.category_id}
    ids |= {a.tax_category_id for a in assets if a.tax_category_id}
    if not ids:
        return {}
    rows = (await db.scalars(
        select(AssetCategory).where(AssetCategory.id.in_(ids)))).all()
    return {str(c.id): c for c in rows}


@router.get("")
async def list_assets(db: AsyncSession = Depends(get_db),
                      user: User = Depends(_READERS),
                      status_filter: str | None = None,
                      category_id: UUID | None = None,
                      location: str | None = None,
                      q: str | None = None,
                      limit: int = 100, offset: int = 0):
    stmt = select(FixedAsset)
    if status_filter:
        stmt = stmt.where(FixedAsset.status == status_filter)
    if category_id:
        stmt = stmt.where(FixedAsset.category_id == category_id)
    if location:
        stmt = stmt.where(FixedAsset.location == location)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(FixedAsset.number.ilike(like),
                              FixedAsset.name.ilike(like),
                              FixedAsset.serial_no.ilike(like),
                              FixedAsset.location.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(FixedAsset.acquired_on.desc(), FixedAsset.number.desc())
        .limit(min(limit, 500)).offset(max(0, offset)))).all()
    cats = await _cat_map(db, list(rows))

    # The register's totals, over everything that matches — not just the
    # page — because "what do we own" is not a per-page question.
    cost_total = await db.scalar(
        select(func.coalesce(func.sum(FixedAsset.cost), 0))
        .where(FixedAsset.status == "active")) or 0
    accum_total = await db.scalar(
        select(func.coalesce(func.sum(FixedAsset.accumulated_depreciation), 0))
        .where(FixedAsset.status == "active")) or 0
    return {
        "total": total,
        "items": [_asset_out(a, cats=cats) for a in rows],
        "summary": {
            "cost": round(float(cost_total), 2),
            "accumulated": round(float(accum_total), 2),
            "book_value": round(float(cost_total) - float(accum_total), 2),
        },
    }


@router.get("/by-location")
async def by_location(db: AsyncSession = Depends(get_db),
                      user: User = Depends(_READERS)):
    """Aset per Lokasi — what is where, and what it is worth there.

    The list somebody walks around a site with. Unplaced assets get their
    own bucket rather than being dropped, because "we do not know where it
    is" is the finding, not a gap in the report.
    """
    rows = (await db.execute(
        select(FixedAsset.location,
               func.count(FixedAsset.id),
               func.coalesce(func.sum(FixedAsset.cost), 0),
               func.coalesce(func.sum(FixedAsset.accumulated_depreciation), 0))
        .where(FixedAsset.status == "active")
        .group_by(FixedAsset.location)
        .order_by(FixedAsset.location.asc().nulls_last()))).all()
    return [{
        "location": loc,
        "count": count,
        "cost": round(float(cost), 2),
        "accumulated": round(float(accum), 2),
        "book_value": round(float(cost) - float(accum), 2),
    } for loc, count, cost, accum in rows]


@router.post("", status_code=201)
async def create_asset(payload: AssetIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_DESK)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give it a name.")
    cost = round(float(payload.cost or 0), 2)
    if cost <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "An asset has a cost — that is what gets "
                            "depreciated.")
    salvage = round(float(payload.salvage_value or 0), 2)
    if salvage < 0 or salvage > cost:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Residual value is between nothing and what it cost. More than "
            "cost would mean depreciating upwards.")

    cat = None
    if payload.category_id:
        cat = await db.get(AssetCategory, payload.category_id)
        if not cat or cat.scope != "commercial":
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "That is not a commercial asset category.")
    tax_cat = None
    if payload.tax_category_id:
        tax_cat = await db.get(AssetCategory, payload.tax_category_id)
        if not tax_cat or tax_cat.scope != "tax":
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "That is not a tax asset category.")

    life = int(payload.useful_life_months
               or (cat.useful_life_months if cat else 0) or 0)
    if life <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "How long will it last? Either pick a category or say how many "
            "months.")
    method = (payload.method or (cat.method if cat else "straight_line"))
    if method not in METHODS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"method must be one of: {', '.join(METHODS)}")
    opening = round(float(payload.opening_accum or 0), 2)
    if opening < 0 or opening > cost - salvage:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "What was already written off cannot exceed what there is to "
            "write off.")

    asset = FixedAsset(
        number=await _next_number(db), name=name,
        category_id=cat.id if cat else None,
        tax_category_id=tax_cat.id if tax_cat else None,
        acquired_on=payload.acquired_on, cost=cost, salvage_value=salvage,
        useful_life_months=life, method=method,
        opening_accum=opening, accumulated_depreciation=opening,
        location=(payload.location or "").strip() or None,
        department=(payload.department or "").strip() or None,
        pic_id=payload.pic_id,
        serial_no=(payload.serial_no or "").strip() or None,
        supplier=(payload.supplier or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        created_by=user.id,
    )
    db.add(asset)
    await db.flush()

    # Only when asked. The purchase that bought it has usually already put
    # it on the balance sheet, and booking it twice is how a register ends
    # up worth double the company.
    if payload.credit_account_no:
        asset_acc = await _account(
            db, cat.asset_account_no if cat else None, label="Akun Aset",
            required=True)
        credit = await _account(db, payload.credit_account_no,
                                label="Akun lawan", required=True)
        try:
            entry = await journal_svc.create_entry(
                db, entry_date=payload.acquired_on,
                rows=[{"account_no": asset_acc, "debit": cost, "memo": name},
                      {"account_no": credit, "credit": cost, "memo": name}],
                memo=f"Perolehan {asset.number} — {name}",
                source_type="asset", source_id=asset.id,
                source_ref=asset.number, created_by=user.id,
                post=True, posted_by=user.id)
            db.add(AssetChange(asset_id=asset.id, kind="cost",
                               changed_on=payload.acquired_on,
                               before_value="0", after_value=str(cost),
                               journal_id=entry.id, memo="Perolehan",
                               actor_id=user.id))
        except journal_svc.JournalError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    await audit_record(db, actor=user, action="create", entity="fixed_asset",
                       entity_id=asset.id,
                       after={"number": asset.number, "name": name,
                              "cost": cost})
    cats = await _cat_map(db, [asset])
    return _asset_out(asset, cats=cats)


@router.get("/depreciation/runs")
async def list_runs(db: AsyncSession = Depends(get_db),
                    user: User = Depends(_READERS),
                    year: int | None = None):
    stmt = select(DepreciationRun)
    if year:
        stmt = stmt.where(DepreciationRun.period_year == year)
    rows = (await db.scalars(
        stmt.order_by(DepreciationRun.period_year.desc(),
                      DepreciationRun.period_month.desc()))).all()
    return [{
        "id": str(r.id), "period_year": r.period_year,
        "period_month": r.period_month, "asset_count": r.asset_count,
        "total_amount": float(r.total_amount or 0),
        "journal_id": str(r.journal_id) if r.journal_id else None,
        "run_at": r.run_at, "is_reversed": r.is_reversed,
    } for r in rows]


class RunIn(BaseModel):
    year: int
    month: int
    # False walks the register and reports; True writes the entry. The
    # preview is the default because a run touches everything at once.
    post: bool = False


async def _accum_this_year(db: AsyncSession, asset_id: UUID, year: int) -> float:
    v = await db.scalar(
        select(func.coalesce(func.sum(AssetDepreciation.amount), 0))
        .where(AssetDepreciation.asset_id == asset_id,
               AssetDepreciation.period_year == year))
    return round(float(v or 0), 2)


@router.post("/depreciation/run")
async def run_depreciation(payload: RunIn,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(_DESK)):
    """Walk the register for one month. Preview by default; post on request."""
    year, month = int(payload.year), int(payload.month)
    if not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month is 1–12.")
    if (year, month) > (date_t.today().year, date_t.today().month):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That month has not happened yet. Depreciation is posted for a "
            "month that has been lived through, not booked ahead.")

    existing = await db.scalar(
        select(DepreciationRun).where(DepreciationRun.period_year == year,
                                      DepreciationRun.period_month == month,
                                      DepreciationRun.is_reversed.is_(False)))
    if existing and payload.post:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{month:02d}/{year} has already been run — "
            f"{existing.asset_count} asset(s), "
            f"{float(existing.total_amount or 0):,.2f}. Reverse that run "
            "before running it again.")

    assets = (await db.scalars(
        select(FixedAsset).order_by(FixedAsset.number.asc()))).all()
    cats = await _cat_map(db, list(assets))

    items: list[dict] = []
    rows: list[dict] = []
    total = 0.0
    skipped: list[dict] = []
    for a in assets:
        if not depr.due_for(acquired_on=a.acquired_on, year=year, month=month,
                            status=a.status, disposed_on=a.disposed_on):
            continue
        already = await db.scalar(
            select(func.count()).select_from(AssetDepreciation).where(
                AssetDepreciation.asset_id == a.id,
                AssetDepreciation.period_year == year,
                AssetDepreciation.period_month == month))
        if already:
            continue
        accum = float(a.accumulated_depreciation or 0)
        this_year = await _accum_this_year(db, a.id, year)
        tax_cat = cats.get(str(a.tax_category_id)) if a.tax_category_id else None
        amount = depr.monthly_amount(
            method=a.method, cost=float(a.cost or 0),
            salvage=float(a.salvage_value or 0),
            life_months=a.useful_life_months, accumulated=accum,
            accumulated_start_of_year=round(accum - this_year, 2),
            tax_group=tax_cat.tax_group if tax_cat else None)
        if amount <= 0:
            continue

        cat = cats.get(str(a.category_id)) if a.category_id else None
        expense = cat.expense_account_no if cat else None
        accum_acc = cat.accum_account_no if cat else None
        if not expense or not accum_acc:
            # Named rather than silently dropped: an asset missing its
            # accounts is a setup mistake somebody has to fix, and a run
            # that quietly skips it under-depreciates the company.
            skipped.append({
                "id": str(a.id), "number": a.number, "name": a.name,
                "amount": amount,
                "why": "No depreciation accounts on its category.",
            })
            continue

        total = round(total + amount, 2)
        items.append({
            "id": str(a.id), "number": a.number, "name": a.name,
            "category_name": cat.name if cat else None,
            "amount": amount,
            "book_value_after": round(float(a.cost or 0) - accum - amount, 2),
        })
        rows.append({"account_no": expense, "debit": amount,
                     "memo": f"{a.number} {a.name}"})
        rows.append({"account_no": accum_acc, "credit": amount,
                     "memo": f"{a.number} {a.name}"})

    preview = {
        "period_year": year, "period_month": month,
        "asset_count": len(items), "total_amount": total,
        "items": items, "skipped": skipped, "posted": False,
        "already_run": bool(existing),
    }
    if not payload.post:
        return preview
    if not items:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Nothing to depreciate for {month:02d}/{year}.")

    # The last day of the month, which is when a month's depreciation
    # belongs — not the first, which would land it in the wrong period on
    # any report cut at a month boundary.
    if month == 12:
        when = date_t(year, 12, 31)
    else:
        from datetime import timedelta
        when = date_t(year, month + 1, 1) - timedelta(days=1)

    try:
        entry = await journal_svc.create_entry(
            db, entry_date=when, rows=rows,
            memo=f"Penyusutan {month:02d}/{year}",
            source_type="depreciation", source_ref=f"{year}-{month:02d}",
            created_by=user.id, post=True, posted_by=user.id)
    except journal_svc.JournalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    run = DepreciationRun(period_year=year, period_month=month,
                          asset_count=len(items), total_amount=total,
                          journal_id=entry.id, run_at=date_t.today(),
                          run_by=user.id)
    db.add(run)
    for it in items:
        asset = await db.get(FixedAsset, UUID(it["id"]))
        asset.accumulated_depreciation = round(
            float(asset.accumulated_depreciation or 0) + it["amount"], 2)
        db.add(AssetDepreciation(
            asset_id=asset.id, period_year=year, period_month=month,
            amount=it["amount"], book_value_after=it["book_value_after"],
            journal_id=entry.id, posted_by=user.id))
    await db.flush()
    await audit_record(db, actor=user, action="post", entity="depreciation_run",
                       entity_id=run.id,
                       after={"period": f"{year}-{month:02d}",
                              "assets": len(items), "total": total})
    preview.update({"posted": True, "journal_id": str(entry.id),
                    "journal_number": entry.number, "run_id": str(run.id)})
    return preview


@router.post("/depreciation/runs/{run_id}/reverse")
async def reverse_run(run_id: UUID, reason: str | None = None,
                      db: AsyncSession = Depends(get_db),
                      user: User = Depends(_DESK)):
    """Undo a month by reversing its entry. Both stay on the record."""
    run = await db.get(DepreciationRun, run_id)
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run.is_reversed:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "That run was already reversed.")
    if run.journal_id:
        entry = await db.get(JournalEntry, run.journal_id)
        if entry:
            try:
                await journal_svc.reverse_entry(
                    db, entry, actor_id=user.id,
                    reason=(reason or f"Reversal of penyusutan "
                                      f"{run.period_month:02d}/{run.period_year}"))
            except journal_svc.JournalError as e:
                raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    # Take the month back off each asset, then drop the rows — otherwise the
    # next run would think the month was still done.
    stmt = select(AssetDepreciation).where(
        AssetDepreciation.period_year == run.period_year,
        AssetDepreciation.period_month == run.period_month)
    if run.journal_id:
        # Only this run's rows. A period can hold rows from more than one
        # run if a later one picked up assets the first one skipped.
        stmt = stmt.where(AssetDepreciation.journal_id == run.journal_id)
    rows = (await db.scalars(stmt)).all()
    for r in rows:
        a = await db.get(FixedAsset, r.asset_id)
        if a:
            a.accumulated_depreciation = round(
                float(a.accumulated_depreciation or 0) - float(r.amount or 0), 2)
        await db.delete(r)
    run.is_reversed = True
    await db.flush()
    await audit_record(db, actor=user, action="reverse",
                       entity="depreciation_run", entity_id=run.id,
                       after={"reason": reason})
    return {"ok": True, "assets": len(rows)}


@router.get("/{asset_id}")
async def get_asset(asset_id: UUID,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(_READERS)):
    a = await db.scalar(
        select(FixedAsset).options(selectinload(FixedAsset.entries))
        .where(FixedAsset.id == asset_id))
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    cats = await _cat_map(db, [a])
    out = _asset_out(a, cats=cats, with_entries=True)
    changes = (await db.scalars(
        select(AssetChange).where(AssetChange.asset_id == a.id)
        .order_by(AssetChange.changed_on.asc()))).all()
    out["changes"] = [{
        "kind": c.kind, "changed_on": c.changed_on,
        "before_value": c.before_value, "after_value": c.after_value,
        "memo": c.memo,
        "journal_id": str(c.journal_id) if c.journal_id else None,
    } for c in changes]
    out["may"] = {
        "edit": a.status == "active",
        "dispose": a.status == "active",
        "move": a.status == "active",
        "adjust": a.status == "active",
        # An asset that has never been depreciated is a data-entry mistake
        # somebody may still take back. One that has is history.
        "delete": a.status == "active" and not (a.entries or []),
    }
    if a.status == "disposed":
        out["locked_because"] = (
            f"Disposed on {a.disposed_on}. The entry that took it off the "
            "books is posted.")
    elif a.entries:
        out["locked_because"] = (
            f"{len(a.entries)} month(s) of depreciation have been posted "
            "against it.")
    return out


@router.get("/{asset_id}/schedule")
async def asset_schedule(asset_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(_READERS),
                         scope: str = "commercial"):
    """The whole life month by month — commercially, or as the tax return
    will see it.

    Both are offered because both are true at once and they disagree. The
    gap between them is the fiscal reconciliation, and it is easier to argue
    about when it can be looked at.
    """
    a = await db.get(FixedAsset, asset_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    cats = await _cat_map(db, [a])
    life, method, group = a.useful_life_months, a.method, None
    if scope == "tax":
        tax_cat = cats.get(str(a.tax_category_id)) if a.tax_category_id else None
        if not tax_cat:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{a.number} has no tax category, so there is no fiscal "
                "schedule to show.")
        life, method, group = (tax_cat.useful_life_months, tax_cat.method,
                               tax_cat.tax_group)
    rows = depr.schedule(
        acquired_on=a.acquired_on, cost=float(a.cost or 0),
        salvage=float(a.salvage_value or 0), life_months=life, method=method,
        opening_accum=float(a.opening_accum or 0), tax_group=group)
    return {
        "asset": {"id": str(a.id), "number": a.number, "name": a.name,
                  "cost": float(a.cost or 0)},
        "scope": scope, "method": method, "useful_life_months": life,
        "tax_group": group,
        "total": round(sum(r["amount"] for r in rows), 2),
        "items": rows,
    }


@router.patch("/{asset_id}")
async def update_asset(asset_id: UUID, payload: AssetPatch,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_DESK)):
    """The descriptive half. Cost, life and whereabouts change through the
    endpoints that record *why*, not by being overwritten here."""
    a = await db.get(FixedAsset, asset_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    if a.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{a.number} was disposed of on {a.disposed_on}.")
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "location", "department", "serial_no", "supplier",
                  "notes"):
        if field in data:
            setattr(a, field, (data[field] or "").strip() or None
                    if isinstance(data[field], str) else data[field])
    if "pic_id" in data:
        a.pic_id = data["pic_id"]
    for field, scope in (("category_id", "commercial"), ("tax_category_id", "tax")):
        if field in data and data[field]:
            cat = await db.get(AssetCategory, data[field])
            if not cat or cat.scope != scope:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"That is not a {scope} asset category.")
            setattr(a, field, cat.id)
    await db.flush()
    await audit_record(db, actor=user, action="update", entity="fixed_asset",
                       entity_id=a.id, after=data)
    cats = await _cat_map(db, [a])
    return _asset_out(a, cats=cats)


@router.delete("/{asset_id}")
async def delete_asset(asset_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_DESK)):
    a = await db.get(FixedAsset, asset_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    posted = await db.scalar(
        select(func.count()).select_from(AssetDepreciation)
        .where(AssetDepreciation.asset_id == a.id))
    if posted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{a.number} has {posted} month(s) of depreciation posted against "
            "it. Dispose of it instead — deleting it would leave those "
            "entries pointing at nothing.")
    if a.status == "disposed":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{a.number} was disposed of, not mislaid.")
    await audit_record(db, actor=user, action="delete", entity="fixed_asset",
                       entity_id=a.id, before={"number": a.number,
                                               "name": a.name})
    await db.delete(a)
    await db.flush()
    return {"ok": True}


class MoveIn(BaseModel):
    location: str
    on: date_t | None = None
    memo: str | None = None


@router.post("/{asset_id}/move")
async def move_asset(asset_id: UUID, payload: MoveIn,
                     db: AsyncSession = Depends(get_db),
                     user: User = Depends(_DESK)):
    """Pindah Aset. No entry — the company owns it either way; only the
    question "where is it" has a new answer."""
    a = await db.get(FixedAsset, asset_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    if a.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{a.number} was disposed of on {a.disposed_on}.")
    where = (payload.location or "").strip()
    if not where:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Moved to where?")
    if where == (a.location or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{a.number} is already at {where}.")
    before = a.location
    a.location = where
    db.add(AssetChange(asset_id=a.id, kind="move",
                       changed_on=payload.on or date_t.today(),
                       before_value=before, after_value=where,
                       memo=(payload.memo or "").strip() or None,
                       actor_id=user.id))
    await db.flush()
    await audit_record(db, actor=user, action="move", entity="fixed_asset",
                       entity_id=a.id, before={"location": before},
                       after={"location": where})
    return {"ok": True, "location": where}


class AdjustIn(BaseModel):
    kind: str  # "cost" | "life"
    on: date_t | None = None
    new_cost: float | None = None
    new_life_months: int | None = None
    # A cost change moves the balance sheet, so it needs the other side.
    counter_account_no: str | None = None
    memo: str | None = None


@router.post("/{asset_id}/adjust")
async def adjust_asset(asset_id: UUID, payload: AdjustIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_DESK)):
    """Perubahan Aset Tetap — a revaluation or a change of expected life.

    A cost change is real money on the balance sheet and carries an entry.
    A life change is an estimate being corrected: no entry, but every month
    after it is a different number, which is exactly why the before and the
    after are kept.
    """
    a = await db.get(FixedAsset, asset_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    if a.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{a.number} was disposed of on {a.disposed_on}.")
    kind = (payload.kind or "").strip()
    if kind not in ("cost", "life"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "kind is 'cost' or 'life'.")
    when = payload.on or date_t.today()

    if kind == "life":
        life = int(payload.new_life_months or 0)
        if life <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A useful life is a number of months.")
        before = a.useful_life_months
        if life == before:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"{a.number} is already on {life} months.")
        a.useful_life_months = life
        db.add(AssetChange(asset_id=a.id, kind="life", changed_on=when,
                           before_value=str(before), after_value=str(life),
                           memo=(payload.memo or "").strip() or None,
                           actor_id=user.id))
        await db.flush()
        await audit_record(db, actor=user, action="adjust",
                           entity="fixed_asset", entity_id=a.id,
                           after={"useful_life_months": life})
        return {"ok": True, "useful_life_months": life}

    new_cost = round(float(payload.new_cost or 0), 2)
    old_cost = round(float(a.cost or 0), 2)
    if new_cost <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A cost is a positive amount.")
    if new_cost == old_cost:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{a.number} already stands at {old_cost:,.2f}.")
    if new_cost < float(a.accumulated_depreciation or 0):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{new_cost:,.2f} is below what has already been written off "
            f"({float(a.accumulated_depreciation or 0):,.2f}) — that would "
            "put the asset at a negative book value.")
    cat = await db.get(AssetCategory, a.category_id) if a.category_id else None
    asset_acc = await _account(db, cat.asset_account_no if cat else None,
                               label="Akun Aset", required=True)
    counter = await _account(db, payload.counter_account_no,
                             label="Akun lawan", required=True)
    delta = round(new_cost - old_cost, 2)
    rows = ([{"account_no": asset_acc, "debit": delta},
             {"account_no": counter, "credit": delta}] if delta > 0 else
            [{"account_no": counter, "debit": -delta},
             {"account_no": asset_acc, "credit": -delta}])
    try:
        entry = await journal_svc.create_entry(
            db, entry_date=when, rows=rows,
            memo=(payload.memo or f"Perubahan nilai {a.number}"),
            source_type="asset", source_id=a.id, source_ref=a.number,
            created_by=user.id, post=True, posted_by=user.id)
    except journal_svc.JournalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    a.cost = new_cost
    db.add(AssetChange(asset_id=a.id, kind="cost", changed_on=when,
                       before_value=str(old_cost), after_value=str(new_cost),
                       journal_id=entry.id,
                       memo=(payload.memo or "").strip() or None,
                       actor_id=user.id))
    await db.flush()
    await audit_record(db, actor=user, action="adjust", entity="fixed_asset",
                       entity_id=a.id, before={"cost": old_cost},
                       after={"cost": new_cost})
    return {"ok": True, "cost": new_cost, "journal_number": entry.number}


class DisposeIn(BaseModel):
    on: date_t | None = None
    proceeds: float = 0
    # Where the money landed. Only needed when there was any.
    proceeds_account_no: str | None = None
    # Where the difference goes — the gain or the loss on disposal.
    gain_loss_account_no: str
    reason: str | None = None


@router.post("/{asset_id}/dispose")
async def dispose_asset(asset_id: UUID, payload: DisposeIn,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(_DESK)):
    """Disposisi Aset — sold, scrapped, or written off.

    The entry takes the cost off, takes the accumulated depreciation off,
    brings the proceeds in, and whatever is left over is the gain or the
    loss. That residual is the number the whole operation exists to produce:
    it says whether the asset was worth what the books claimed.
    """
    a = await db.get(FixedAsset, asset_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    if a.status == "disposed":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{a.number} was already disposed of on "
                            f"{a.disposed_on}.")
    when = payload.on or date_t.today()
    if when < a.acquired_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{a.number} was not acquired until "
                            f"{a.acquired_on}.")
    proceeds = round(float(payload.proceeds or 0), 2)
    if proceeds < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Proceeds are nothing or more.")

    cat = await db.get(AssetCategory, a.category_id) if a.category_id else None
    asset_acc = await _account(db, cat.asset_account_no if cat else None,
                               label="Akun Aset", required=True)
    accum_acc = await _account(db, cat.accum_account_no if cat else None,
                               label="Akun Akumulasi Penyusutan", required=True)
    gain_acc = await _account(db, payload.gain_loss_account_no,
                              label="Akun Laba/Rugi Pelepasan", required=True)
    cash_acc = None
    if proceeds > 0:
        cash_acc = await _account(db, payload.proceeds_account_no,
                                  label="Akun penerimaan", required=True)

    cost = round(float(a.cost or 0), 2)
    accum = round(float(a.accumulated_depreciation or 0), 2)
    book = round(cost - accum, 2)
    result = round(proceeds - book, 2)   # positive = gain, negative = loss

    rows: list[dict] = [
        {"account_no": accum_acc, "debit": accum,
         "memo": f"Akumulasi {a.number}"} if accum > 0 else None,
        {"account_no": cash_acc, "debit": proceeds,
         "memo": f"Hasil pelepasan {a.number}"} if proceeds > 0 else None,
        {"account_no": asset_acc, "credit": cost, "memo": f"{a.number} {a.name}"},
    ]
    rows = [r for r in rows if r]
    if result > 0:
        rows.append({"account_no": gain_acc, "credit": result,
                     "memo": f"Laba pelepasan {a.number}"})
    elif result < 0:
        rows.append({"account_no": gain_acc, "debit": -result,
                     "memo": f"Rugi pelepasan {a.number}"})

    try:
        entry = await journal_svc.create_entry(
            db, entry_date=when, rows=rows,
            memo=(payload.reason or f"Pelepasan {a.number} — {a.name}"),
            source_type="asset", source_id=a.id, source_ref=a.number,
            created_by=user.id, post=True, posted_by=user.id)
    except journal_svc.JournalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    a.status = "disposed"
    a.disposed_on = when
    a.disposal_proceeds = proceeds
    a.disposal_reason = (payload.reason or "").strip() or None
    a.disposal_journal_id = entry.id
    await db.flush()
    await audit_record(db, actor=user, action="dispose", entity="fixed_asset",
                       entity_id=a.id,
                       after={"on": str(when), "proceeds": proceeds,
                              "book_value": book, "result": result})
    return {
        "ok": True, "number": a.number, "disposed_on": when,
        "cost": cost, "accumulated": accum, "book_value": book,
        "proceeds": proceeds,
        "gain": result if result > 0 else 0.0,
        "loss": -result if result < 0 else 0.0,
        "journal_id": str(entry.id), "journal_number": entry.number,
    }
