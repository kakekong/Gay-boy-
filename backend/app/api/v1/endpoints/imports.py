"""Bring existing records in from the old accounting system.

Two endpoints on purpose. `preview` reads the file and reports exactly what
committing would do — nothing is written, so it can be run as often as needed
while the mapping is checked. `commit` does the same work and then writes,
capped by `limit` so the first run can be a handful of rows rather than the
whole book.

Re-running is safe. A customer already carrying the same Accurate code, or the
same company name, is reported as `existing` and skipped rather than
duplicated — which is what makes "import 10, look at them, import the rest"
a workable way to do this.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.crm import Customer
from app.models.user import User
from app.services.customer_import import MappedCustomer, map_customers, read_rows

router = APIRouter()

_director_only = require(Role.DIRECTOR)
MAX_UPLOAD_MB = 10


def _name_key(s: str) -> str:
    """Company names for duplicate detection.

    The same company is written `PT. Mayora Indah`, `PT.MAYORA INDAH` and
    `PT MAYORA INDAH TBK` across the file, so punctuation, case and the legal
    form prefix all have to come off before comparing.
    """
    import re
    s = (s or "").lower()
    s = re.sub(r"^\s*\[.*?\]\s*", "", s)          # [C.00013] duplicate marker
    s = re.sub(r"\b(pt|cv|ud|tbk|persero)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


async def _resolve_reps(db: AsyncSession) -> dict[str, UUID]:
    """First-name -> user id, for the sales people named in `Kategori`.

    Matched on first name because that is all the export carries. A first name
    shared by two staff is left unmatched rather than guessed at.
    """
    rows = (await db.scalars(
        select(User).where(User.is_active.is_(True),
                           User.role.notin_(["customer", "supplier"]))
    )).all()
    counts: dict[str, int] = {}
    first: dict[str, UUID] = {}
    for u in rows:
        key = (u.full_name or "").strip().split(" ")[0].lower()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        first[key] = u.id
    return {k: v for k, v in first.items() if counts.get(k) == 1}


async def _plan(db: AsyncSession, mapped: list[MappedCustomer]) -> list[dict]:
    """Decide, per row, what committing would do — without doing it."""
    reps = await _resolve_reps(db)

    existing = (await db.execute(
        select(Customer.id, Customer.company_name, Customer.meta)
        .where(Customer.is_deleted.is_(False))
    )).all()
    by_name = {_name_key(n): i for i, n, _ in existing}
    by_code = {
        (m or {}).get("external_code"): i
        for i, _, m in existing if (m or {}).get("external_code")
    }

    seen_in_file: dict[str, int] = {}
    plan: list[dict] = []
    for row in mapped:
        warnings = list(row.warnings)
        action = "create"

        if row.external_code and row.external_code in by_code:
            action = "existing"
        elif _name_key(row.company_name) in by_name:
            action = "existing"
            warnings.append("matched an existing customer by name, not by code")

        key = _name_key(row.company_name)
        if action == "create" and key in seen_in_file:
            action = "duplicate_in_file"
            warnings.append(f"same company as row {seen_in_file[key]} in this file")
        elif action == "create":
            seen_in_file[key] = row.row_no

        rep_id = reps.get(row.sales_rep_hint) if row.sales_rep_hint else None
        if row.sales_rep_hint and not rep_id:
            warnings.append(
                f"no active user matches '{row.sales_rep_hint}' — will import "
                f"unassigned; create the account first to link it")

        plan.append({
            "row_no": row.row_no,
            "action": action,
            "external_code": row.external_code,
            "company_name": row.company_name,
            "industry": row.industry,
            "pic_name": row.pic_name,
            "phone": row.phone,
            "email": row.email,
            "company_address": row.company_address,
            "delivery_address": row.delivery_address,
            "tax_id": row.tax_id,
            "payment_terms": row.payment_terms,
            "sales_rep_hint": row.sales_rep_hint,
            "sales_pic_id": str(rep_id) if rep_id else None,
            "warnings": warnings,
        })
    return plan


async def _read_upload(file: UploadFile) -> tuple[list[str], list[list[str]]]:
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File too large (max {MAX_UPLOAD_MB} MB)")
    try:
        return read_rows(data, file.filename or "")
    except Exception as exc:                       # noqa: BLE001 — user-facing
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Could not read the spreadsheet: {exc}") from exc


@router.post("/customers/preview")
async def preview_customers(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director_only),
):
    """What importing this file would do. Writes nothing."""
    header, rows = await _read_upload(file)
    mapped, problems = map_customers(header, rows)
    plan = await _plan(db, mapped)
    counts: dict[str, int] = {}
    for p in plan:
        counts[p["action"]] = counts.get(p["action"], 0) + 1
    return {
        "filename": file.filename,
        "rows_in_file": len(rows),
        "problems": problems,
        "counts": counts,
        "unmatched_reps": sorted({
            p["sales_rep_hint"] for p in plan
            if p["sales_rep_hint"] and not p["sales_pic_id"]
        }),
        "rows": plan,
    }


@router.post("/customers/commit")
async def commit_customers(
    file: UploadFile = File(...),
    limit: int = Form(10),
    confirm: str = Form(""),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_director_only),
):
    """Create the customers this file describes, at most `limit` of them.

    `limit` is the point of this endpoint: the first run should be small
    enough to eyeball in the CRM before the rest follows. Rows already present
    are skipped, so raising the limit and running again continues where the
    last run stopped instead of duplicating it.
    """
    if confirm.strip().upper() != "IMPORT":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Type IMPORT to confirm")
    if limit < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit must be at least 1")

    header, rows = await _read_upload(file)
    mapped, problems = map_customers(header, rows)
    if problems and not mapped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems[0])

    plan = await _plan(db, mapped)
    by_row = {m.row_no: m for m in mapped}

    created: list[dict] = []
    for p in plan:
        if len(created) >= limit:
            break
        if p["action"] != "create":
            continue
        src = by_row[p["row_no"]]
        cust = Customer(
            company_name=src.company_name,
            industry=src.industry,
            pic_name=src.pic_name,
            phone=src.phone,
            whatsapp=src.whatsapp,
            email=src.email,
            company_address=src.company_address,
            delivery_address=src.delivery_address,
            tax_id=src.tax_id,
            tax_name=src.tax_name,
            tax_address=src.tax_address,
            is_pkp=src.is_pkp,
            payment_terms=src.payment_terms,
            # Imported customers are existing business, not fresh leads — but
            # they have no open deal here yet, so they start at the beginning
            # of the pipeline rather than being invented into a later stage.
            stage="lead",
            sales_pic_id=UUID(p["sales_pic_id"]) if p["sales_pic_id"] else None,
            created_by=me.id,
            meta={
                "external_code": src.external_code,
                "imported_from": file.filename,
                "import_notes": src.notes,
            },
        )
        db.add(cust)
        await db.flush()
        created.append({"id": str(cust.id), "company_name": cust.company_name,
                        "external_code": src.external_code,
                        "sales_pic_id": p["sales_pic_id"]})

    await record(db, actor=me, action="import", entity="customer", entity_id=None,
                 after={"source": file.filename, "created": len(created),
                        "limit": limit})
    await db.commit()

    remaining = sum(1 for p in plan if p["action"] == "create") - len(created)
    return {
        "created": len(created),
        "remaining_to_import": max(0, remaining),
        "skipped_existing": sum(1 for p in plan if p["action"] == "existing"),
        "duplicates_in_file": sum(1 for p in plan if p["action"] == "duplicate_in_file"),
        "customers": created,
    }
