"""Master data — Pajak and Gaji/Tunjangan.

The two lists finance sets up once and then picks from. Both are small; what
makes them worth their own tables is that each row carries the accounting
consequence of choosing it, so the document that uses it does not have to be
told twice.

A tax row carries a *pair* of accounts, because the same tax sits on
different sides of the books depending on which way the invoice points: what
we charge a customer is pajak keluaran (a liability — we are holding the
state's money), what a supplier charges us is pajak masukan (an asset — we
will claim it back). One row, two accounts, and the return only reconciles
if both are right.

A payroll row carries its *type*, and the type decides two things a payslip
cannot show: whether the amount is paid or deducted, and whether it moves
the PPh 21 base. Two deductions can look identical and differ on exactly
that — "Potongan Gaji (Tidak Mengurangi PPh)" against "Pengurangan Gaji
(Mengurangi PPh)" is the whole distinction in the name. `/compute` walks a
set of lines through those rules so payroll calculates rather than asserts.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.master import PAY_KINDS, TAX_KINDS, PayComponent, TaxType
from app.models.user import User

router = APIRouter()

# Same shape as the rest of the books: finance keeps it, the director is the
# backstop, a manager reads. HR reads the payroll half — they are the ones
# who will be picking these components on a payslip.
_DESK = require(Role.FINANCE, Role.DIRECTOR)
_READERS = require(Role.FINANCE, Role.DIRECTOR, Role.MANAGER)
_PAY_READERS = require(Role.FINANCE, Role.DIRECTOR, Role.MANAGER, Role.HR)


async def _check_account(db: AsyncSession, account_no: str | None,
                         *, label: str) -> str | None:
    """An account you can actually post to, or a refusal that says why."""
    if not account_no or not account_no.strip():
        return None
    no = account_no.strip()
    acc = await db.scalar(select(Account).where(Account.account_no == no))
    if not acc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{label}: no such account {no}")
    if acc.is_parent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label}: {no} {acc.name} is a heading. Postings land on the "
            "accounts under it, not on the heading itself.")
    if acc.is_suspended:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{label}: {no} {acc.name} is suspended.")
    return no


async def _account_names(db: AsyncSession, numbers: set[str]) -> dict[str, str]:
    """Numbers alone are unreadable; the list shows the names beside them."""
    numbers = {n for n in numbers if n}
    if not numbers:
        return {}
    rows = (await db.scalars(
        select(Account).where(Account.account_no.in_(numbers)))).all()
    return {a.account_no: a.name for a in rows}


# --------------------------------------------------------------------- Pajak

class TaxIn(BaseModel):
    kind: str
    description: str
    rate_pct: float = 0
    sales_account_no: str | None = None
    purchase_account_no: str | None = None
    is_active: bool = True
    notes: str | None = None


class TaxPatch(BaseModel):
    kind: str | None = None
    description: str | None = None
    rate_pct: float | None = None
    sales_account_no: str | None = None
    purchase_account_no: str | None = None
    is_active: bool | None = None
    notes: str | None = None


def _tax_out(t: TaxType, names: dict[str, str]) -> dict:
    return {
        "id": str(t.id),
        "kind": t.kind,
        "kind_label": TAX_KINDS.get(t.kind, t.kind),
        "description": t.description,
        "rate_pct": float(t.rate_pct or 0),
        "sales_account_no": t.sales_account_no,
        "sales_account_name": names.get(t.sales_account_no or ""),
        "purchase_account_no": t.purchase_account_no,
        "purchase_account_name": names.get(t.purchase_account_no or ""),
        "is_active": t.is_active,
        "notes": t.notes,
    }


@router.get("/tax-types/kinds")
async def tax_kinds(user: User = Depends(_READERS)):
    """The seven the forms distinguish. Not a free-text field on purpose."""
    return [{"value": k, "label": v} for k, v in TAX_KINDS.items()]


@router.get("/tax-types")
async def list_tax_types(db: AsyncSession = Depends(get_db),
                         user: User = Depends(_READERS),
                         kind: str | None = None,
                         active_only: bool = False,
                         q: str | None = None):
    stmt = select(TaxType)
    if kind:
        stmt = stmt.where(TaxType.kind == kind)
    if active_only:
        stmt = stmt.where(TaxType.is_active.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(TaxType.description.ilike(like),
                              TaxType.notes.ilike(like)))
    rows = (await db.scalars(
        stmt.order_by(TaxType.kind.asc(), TaxType.description.asc()))).all()
    names = await _account_names(
        db, {r.sales_account_no or "" for r in rows}
        | {r.purchase_account_no or "" for r in rows})
    return [_tax_out(r, names) for r in rows]


async def _tax_duplicate(db: AsyncSession, kind: str, description: str,
                         *, exclude: UUID | None = None) -> bool:
    stmt = select(func.count()).select_from(TaxType).where(
        TaxType.kind == kind,
        func.lower(TaxType.description) == description.lower())
    if exclude:
        stmt = stmt.where(TaxType.id != exclude)
    return bool(await db.scalar(stmt))


@router.post("/tax-types", status_code=201)
async def create_tax_type(payload: TaxIn,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_DESK)):
    kind = (payload.kind or "").strip()
    if kind not in TAX_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"kind must be one of: {', '.join(TAX_KINDS)}")
    description = (payload.description or "").strip()
    if not description:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Keterangan: say which one this is — 'PPN Keluaran 11%' reads on "
            "an invoice, 'PPN' does not.")
    rate = round(float(payload.rate_pct or 0), 4)
    if rate < 0 or rate > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A rate is a percentage between 0 and 100.")
    if await _tax_duplicate(db, kind, description):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"There is already a {TAX_KINDS[kind]} called “{description}”.")
    row = TaxType(
        kind=kind, description=description, rate_pct=rate,
        sales_account_no=await _check_account(
            db, payload.sales_account_no, label="Akun Pajak Penjualan"),
        purchase_account_no=await _check_account(
            db, payload.purchase_account_no, label="Akun Pajak Pembelian"),
        is_active=payload.is_active,
        notes=(payload.notes or "").strip() or None,
    )
    db.add(row)
    await db.flush()
    await audit_record(db, actor=user, action="create", entity="tax_type",
                       entity_id=row.id,
                       after={"kind": kind, "description": description,
                              "rate_pct": rate})
    names = await _account_names(
        db, {row.sales_account_no or "", row.purchase_account_no or ""})
    return _tax_out(row, names)


@router.patch("/tax-types/{tax_id}")
async def update_tax_type(tax_id: UUID, payload: TaxPatch,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_DESK)):
    row = await db.get(TaxType, tax_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tax type not found")
    data = payload.model_dump(exclude_unset=True)
    if "kind" in data:
        if data["kind"] not in TAX_KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"kind must be one of: {', '.join(TAX_KINDS)}")
        row.kind = data["kind"]
    if "description" in data:
        description = (data["description"] or "").strip()
        if not description:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Keterangan cannot be empty.")
        row.description = description
    if await _tax_duplicate(db, row.kind, row.description, exclude=row.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"There is already a {TAX_KINDS[row.kind]} called "
            f"“{row.description}”.")
    if "rate_pct" in data:
        rate = round(float(data["rate_pct"] or 0), 4)
        if rate < 0 or rate > 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A rate is a percentage between 0 and 100.")
        row.rate_pct = rate
    if "sales_account_no" in data:
        row.sales_account_no = await _check_account(
            db, data["sales_account_no"], label="Akun Pajak Penjualan")
    if "purchase_account_no" in data:
        row.purchase_account_no = await _check_account(
            db, data["purchase_account_no"], label="Akun Pajak Pembelian")
    if "is_active" in data:
        row.is_active = bool(data["is_active"])
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    await db.flush()
    await audit_record(db, actor=user, action="update", entity="tax_type",
                       entity_id=row.id, after=data)
    names = await _account_names(
        db, {row.sales_account_no or "", row.purchase_account_no or ""})
    return _tax_out(row, names)


@router.delete("/tax-types/{tax_id}")
async def delete_tax_type(tax_id: UUID,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(_DESK)):
    """Remove a row outright. To keep it on file but off the list, set
    `is_active` instead — that is what you want for a rate that changed."""
    row = await db.get(TaxType, tax_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tax type not found")
    await audit_record(db, actor=user, action="delete", entity="tax_type",
                       entity_id=row.id,
                       before={"kind": row.kind, "description": row.description})
    await db.delete(row)
    await db.flush()
    return {"ok": True}


# ------------------------------------------------------------- Gaji/Tunjangan

class PayIn(BaseModel):
    name: str
    kind: str
    account_no: str | None = None
    default_amount: float = 0
    is_active: bool = True
    notes: str | None = None


class PayPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    account_no: str | None = None
    default_amount: float | None = None
    is_active: bool | None = None
    notes: str | None = None


def _pay_out(c: PayComponent, names: dict[str, str]) -> dict:
    meta = PAY_KINDS.get(c.kind, {})
    return {
        "id": str(c.id),
        "name": c.name,
        "kind": c.kind,
        "kind_label": meta.get("label", c.kind),
        # Carried on every row so the payslip can show "+" or "−" and say
        # whether it moves the tax base without looking the type up again.
        "direction": meta.get("direction", "pay"),
        "taxable": bool(meta.get("taxable", False)),
        "regular": bool(meta.get("regular", True)),
        "account_no": c.account_no,
        "account_name": names.get(c.account_no or ""),
        "default_amount": float(c.default_amount or 0),
        "is_active": c.is_active,
        "notes": c.notes,
    }


@router.get("/pay-components/kinds")
async def pay_kinds(user: User = Depends(_PAY_READERS)):
    """The fourteen the PPh 21 form distinguishes, with what each one does."""
    return [{"value": k, "label": v["label"], "direction": v["direction"],
             "taxable": v["taxable"], "regular": v["regular"]}
            for k, v in PAY_KINDS.items()]


@router.get("/pay-components")
async def list_pay_components(db: AsyncSession = Depends(get_db),
                              user: User = Depends(_PAY_READERS),
                              kind: str | None = None,
                              active_only: bool = False,
                              q: str | None = None):
    stmt = select(PayComponent)
    if kind:
        stmt = stmt.where(PayComponent.kind == kind)
    if active_only:
        stmt = stmt.where(PayComponent.is_active.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PayComponent.name.ilike(like),
                             PayComponent.notes.ilike(like)))
    rows = (await db.scalars(stmt.order_by(PayComponent.name.asc()))).all()
    names = await _account_names(db, {r.account_no or "" for r in rows})
    return [_pay_out(r, names) for r in rows]


@router.post("/pay-components", status_code=201)
async def create_pay_component(payload: PayIn,
                               db: AsyncSession = Depends(get_db),
                               user: User = Depends(_DESK)):
    kind = (payload.kind or "").strip()
    if kind not in PAY_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"kind must be one of: {', '.join(PAY_KINDS)}")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Give the component a name — it is what appears "
                            "on the payslip.")
    dup = await db.scalar(
        select(func.count()).select_from(PayComponent)
        .where(func.lower(PayComponent.name) == name.lower()))
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"There is already a component called “{name}”.")
    amount = round(float(payload.default_amount or 0), 2)
    if amount < 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Amounts are positive — whether it is added or taken away is what "
            "the type says.")
    row = PayComponent(
        name=name, kind=kind,
        account_no=await _check_account(db, payload.account_no,
                                        label="Akun Beban"),
        default_amount=amount, is_active=payload.is_active,
        notes=(payload.notes or "").strip() or None,
    )
    db.add(row)
    await db.flush()
    await audit_record(db, actor=user, action="create", entity="pay_component",
                       entity_id=row.id, after={"name": name, "kind": kind})
    names = await _account_names(db, {row.account_no or ""})
    return _pay_out(row, names)


@router.patch("/pay-components/{component_id}")
async def update_pay_component(component_id: UUID, payload: PayPatch,
                               db: AsyncSession = Depends(get_db),
                               user: User = Depends(_DESK)):
    row = await db.get(PayComponent, component_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found")
    data = payload.model_dump(exclude_unset=True)
    if "kind" in data:
        if data["kind"] not in PAY_KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"kind must be one of: {', '.join(PAY_KINDS)}")
        row.kind = data["kind"]
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A component needs a name.")
        dup = await db.scalar(
            select(func.count()).select_from(PayComponent).where(
                func.lower(PayComponent.name) == name.lower(),
                PayComponent.id != row.id))
        if dup:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"There is already a component called “{name}”.")
        row.name = name
    if "account_no" in data:
        row.account_no = await _check_account(db, data["account_no"],
                                              label="Akun Beban")
    if "default_amount" in data:
        amount = round(float(data["default_amount"] or 0), 2)
        if amount < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Amounts are positive.")
        row.default_amount = amount
    if "is_active" in data:
        row.is_active = bool(data["is_active"])
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    await db.flush()
    await audit_record(db, actor=user, action="update", entity="pay_component",
                       entity_id=row.id, after=data)
    names = await _account_names(db, {row.account_no or ""})
    return _pay_out(row, names)


@router.delete("/pay-components/{component_id}")
async def delete_pay_component(component_id: UUID,
                               db: AsyncSession = Depends(get_db),
                               user: User = Depends(_DESK)):
    row = await db.get(PayComponent, component_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found")
    await audit_record(db, actor=user, action="delete", entity="pay_component",
                       entity_id=row.id, before={"name": row.name})
    await db.delete(row)
    await db.flush()
    return {"ok": True}


class ComputeLine(BaseModel):
    # Either a saved component or a bare type — the second is what a one-off
    # bonus looks like before anyone bothers to make it master data.
    component_id: UUID | None = None
    kind: str | None = None
    amount: float = 0


class ComputeIn(BaseModel):
    lines: list[ComputeLine] = []


@router.post("/pay-components/compute")
async def compute_pay(payload: ComputeIn,
                      db: AsyncSession = Depends(get_db),
                      user: User = Depends(_PAY_READERS)):
    """Walk a set of payroll lines through what their types mean.

    Gross is what is paid, net is what lands in the account, and the PPh 21
    base is neither — it is gross minus only the deductions that are allowed
    to reduce it. Keeping the three apart is the reason a payroll line has a
    type at all, so this is where that is done once rather than in every
    caller.
    """
    gross = deductions = 0.0
    taxable_regular = taxable_irregular = deductible = 0.0
    out: list[dict] = []
    for i, ln in enumerate(payload.lines, 1):
        kind = (ln.kind or "").strip()
        name = None
        if ln.component_id:
            comp = await db.get(PayComponent, ln.component_id)
            if not comp:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Line {i}: no such component.")
            kind, name = comp.kind, comp.name
        meta = PAY_KINDS.get(kind)
        if not meta:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Line {i}: say which type it is — one of {', '.join(PAY_KINDS)}.")
        amount = round(float(ln.amount or 0), 2)
        if amount < 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Line {i}: amounts are positive; the type says which way it "
                "goes.")
        if meta["direction"] == "pay":
            gross += amount
            if meta["taxable"]:
                if meta["regular"]:
                    taxable_regular += amount
                else:
                    taxable_irregular += amount
        else:
            deductions += amount
            # A deduction only comes off the tax base when its type says so —
            # "Tidak Mengurangi PPh" means it reduces the payout and nothing
            # else.
            if meta["taxable"]:
                deductible += amount
        out.append({"line_no": i, "kind": kind, "name": name,
                    "label": meta["label"], "direction": meta["direction"],
                    "taxable": meta["taxable"], "regular": meta["regular"],
                    "amount": amount})
    return {
        "lines": out,
        "gross": round(gross, 2),
        "deductions": round(deductions, 2),
        "net": round(gross - deductions, 2),
        "taxable_regular": round(taxable_regular, 2),
        "taxable_irregular": round(taxable_irregular, 2),
        "deductible": round(deductible, 2),
        # What PPh 21 is worked out on. Not the same as gross, and not the
        # same as net.
        "tax_base": round(taxable_regular + taxable_irregular - deductible, 2),
    }
