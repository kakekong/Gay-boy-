"""Bring existing records in from the old accounting system.

Four things can be imported — customers, the chart of accounts, the parts
catalogue and historical quotations — and every one of them works the same way,
because the way is the point.

Two endpoints per shape. `preview` reads the file and reports exactly what
committing would do; it writes nothing, so it can be run as often as needed
while the mapping is argued with. `commit` does the same work and then writes,
capped by `limit` so the first run can be a handful of rows rather than the
whole book.

Re-running is safe everywhere. A record already carrying the same identifier —
the Accurate customer code, the account number, the part number, the quotation
number — is reported as `existing` and skipped rather than duplicated. That is
what makes "import 10, look at them, import the rest" a workable way to do
this, instead of a thing you get one attempt at.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.account import Account
from app.models.crm import Customer
from app.models.inventory import InventoryItem, InventoryMovement
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User
from app.services.account_import import MappedAccount, map_accounts
from app.services.customer_import import (
    MappedCustomer, map_customers, name_key as _name_key, read_rows,
)
from app.services.item_import import MappedItem, map_items
from app.services.quotation_import import (
    MappedQuotation, map_quotations, read_workbook,
)

router = APIRouter()

_director_only = require(Role.DIRECTOR)
MAX_UPLOAD_MB = 10


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


async def _bytes(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File too large (max {MAX_UPLOAD_MB} MB)")
    return data


async def _read_upload(file: UploadFile) -> tuple[list[str], list[list[str]]]:
    data = await _bytes(file)
    try:
        return read_rows(data, file.filename or "")
    except Exception as exc:                       # noqa: BLE001 — user-facing
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Could not read the spreadsheet: {exc}") from exc


def _require_confirm(confirm: str, limit: int) -> None:
    if confirm.strip().upper() != "IMPORT":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Type IMPORT to confirm")
    if limit < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit must be at least 1")


def _tally(plan: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in plan:
        counts[p["action"]] = counts.get(p["action"], 0) + 1
    return counts


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
    return {
        "filename": file.filename,
        "rows_in_file": len(rows),
        "problems": problems,
        "counts": _tally(plan),
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
    _require_confirm(confirm, limit)

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


# ── Chart of accounts ────────────────────────────────────────────────────────
# Mostly a confirmation exercise: the app's chart was seeded from this same
# company's books, so a fresh export agrees with it about ~97 accounts out of
# 112. The value is in the difference, and in seeing it before acting on it.

async def _plan_accounts(db: AsyncSession, mapped: list[MappedAccount]) -> list[dict]:
    existing = {
        a.account_no: a for a in
        (await db.scalars(select(Account))).all()
    }
    seen: set[str] = set()
    plan: list[dict] = []
    for row in mapped:
        warnings = list(row.warnings)
        action = "create"
        current = existing.get(row.account_no)
        if current:
            action = "existing"
            # Reported, never applied. An account number is referenced by
            # posted ledger entries and by the account_*_no columns on
            # quotations and invoices; renaming one because a spreadsheet
            # spelled it differently rewrites labels on statements that have
            # already been signed off.
            if (current.name or "").strip().lower() != row.name.strip().lower():
                warnings.append(
                    f"the app calls this '{current.name}' — the export says "
                    f"'{row.name}'. Left as it is; change it in Chart of "
                    f"Accounts if the export is right.")
            if current.account_type != row.account_type:
                warnings.append(
                    f"type differs: app '{current.account_type}', export "
                    f"'{row.account_type}'")
        elif row.account_no in seen:
            action = "duplicate_in_file"
            warnings.append("this account number appears twice in the file")
        if action == "create":
            seen.add(row.account_no)

        if row.parent_account_no and row.parent_account_no not in existing \
                and not any(m.account_no == row.parent_account_no for m in mapped):
            warnings.append(
                f"parent account {row.parent_account_no} is neither in the app "
                f"nor in this file — it will import without a parent")

        plan.append({
            "row_no": row.row_no,
            "action": action,
            "account_no": row.account_no,
            "name": row.name,
            "account_type": row.account_type,
            "parent_account_no": row.parent_account_no,
            "is_parent": row.is_parent,
            "is_tax": row.is_tax,
            "balance": row.balance,
            "warnings": warnings,
        })
    return plan


@router.post("/accounts/preview")
async def preview_accounts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director_only),
):
    header, rows = await _read_upload(file)
    mapped, problems = map_accounts(header, rows)
    plan = await _plan_accounts(db, mapped)
    return {
        "filename": file.filename,
        "rows_in_file": len(rows),
        "problems": problems,
        "counts": _tally(plan),
        "renamed": [p for p in plan if p["action"] == "existing"
                    and any("the app calls this" in w for w in p["warnings"])],
        "rows": plan,
    }


@router.post("/accounts/commit")
async def commit_accounts(
    file: UploadFile = File(...),
    limit: int = Form(10),
    confirm: str = Form(""),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_director_only),
):
    _require_confirm(confirm, limit)
    header, rows = await _read_upload(file)
    mapped, problems = map_accounts(header, rows)
    if problems and not mapped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems[0])

    plan = await _plan_accounts(db, mapped)
    by_row = {m.row_no: m for m in mapped}

    created: list[dict] = []
    for p in plan:
        if len(created) >= limit:
            break
        if p["action"] != "create":
            continue
        src = by_row[p["row_no"]]
        db.add(Account(
            account_no=src.account_no,
            name=src.name,
            account_type=src.account_type,
            parent_account_no=src.parent_account_no,
            is_parent=src.is_parent,
            level=src.level,
            balance=src.balance,
            is_tax=src.is_tax,
            description=src.description,
        ))
        await db.flush()
        created.append({"account_no": src.account_no, "name": src.name,
                        "account_type": src.account_type})

    await record(db, actor=me, action="import", entity="account", entity_id=None,
                 after={"source": file.filename, "created": len(created), "limit": limit})
    await db.commit()

    remaining = sum(1 for p in plan if p["action"] == "create") - len(created)
    return {
        "created": len(created),
        "remaining_to_import": max(0, remaining),
        "skipped_existing": sum(1 for p in plan if p["action"] == "existing"),
        "duplicates_in_file": sum(1 for p in plan if p["action"] == "duplicate_in_file"),
        "accounts": created,
    }


# ── Parts catalogue ──────────────────────────────────────────────────────────

async def _plan_items(db: AsyncSession, mapped: list[MappedItem]) -> list[dict]:
    rows = (await db.execute(
        select(InventoryItem.id, InventoryItem.sku, InventoryItem.name)
    )).all()
    by_sku = {s: i for i, s, _ in rows}
    by_name = {(n or "").strip().lower(): s for _, s, n in rows}

    seen: set[str] = set()
    plan: list[dict] = []
    for row in mapped:
        warnings = list(row.warnings)
        action = "create"
        if row.sku in by_sku:
            action = "existing"
        elif row.sku in seen:
            action = "duplicate_in_file"
            warnings.append("this part number appears twice in the file")
        if action == "create":
            seen.add(row.sku)
            other = by_name.get(row.name.strip().lower())
            if other:
                warnings.append(
                    f"an item called this already exists under part number "
                    f"{other} — importing anyway, since the part number differs")

        plan.append({
            "row_no": row.row_no,
            "action": action,
            "sku": row.sku,
            "name": row.name,
            "category": row.category,
            "uom": row.uom,
            "unit_cost": row.unit_cost,
            "sell_price": row.sell_price,
            "opening_qty": row.opening_qty,
            "supplier_hint": row.supplier_hint,
            "is_active": row.is_active,
            "warnings": warnings,
        })
    return plan


@router.post("/items/preview")
async def preview_items(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director_only),
):
    header, rows = await _read_upload(file)
    mapped, problems = map_items(header, rows)
    plan = await _plan_items(db, mapped)
    cats: dict[str, int] = {}
    for p in plan:
        cats[p["category"] or "—"] = cats.get(p["category"] or "—", 0) + 1
    return {
        "filename": file.filename,
        "rows_in_file": len(rows),
        "problems": problems,
        "counts": _tally(plan),
        "categories": sorted(cats.items(), key=lambda kv: -kv[1]),
        "priced": sum(1 for p in plan if p["unit_cost"] or p["sell_price"]),
        "rows": plan,
    }


@router.post("/items/commit")
async def commit_items(
    file: UploadFile = File(...),
    limit: int = Form(10),
    confirm: str = Form(""),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_director_only),
):
    _require_confirm(confirm, limit)
    header, rows = await _read_upload(file)
    mapped, problems = map_items(header, rows)
    if not mapped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            problems[0] if problems else "Nothing to import")

    plan = await _plan_items(db, mapped)
    by_row = {m.row_no: m for m in mapped}

    created: list[dict] = []
    for p in plan:
        if len(created) >= limit:
            break
        if p["action"] != "create":
            continue
        src = by_row[p["row_no"]]
        item = InventoryItem(
            sku=src.sku,
            name=src.name,
            category=src.category,
            uom=src.uom,
            unit_cost=src.unit_cost,
            reorder_point=src.reorder_point,
            location=src.location,
            supplier_hint=src.supplier_hint,
            notes=src.notes,
            is_active=src.is_active,
            current_stock=0,
        )
        db.add(item)
        await db.flush()
        # Opening stock arrives the same way every other quantity in this app
        # does — as a movement — so the item's history starts with something
        # that can be accounted for rather than a number from nowhere.
        if src.opening_qty:
            item.current_stock = src.opening_qty
            db.add(InventoryMovement(
                item_id=item.id, delta=src.opening_qty, reason="adjust",
                reference=f"import:{file.filename}", user_id=me.id,
                notes="Opening stock from the Accurate item list",
            ))
        created.append({"id": str(item.id), "sku": item.sku, "name": item.name,
                        "category": item.category})

    await record(db, actor=me, action="import", entity="inventory_item",
                 entity_id=None,
                 after={"source": file.filename, "created": len(created), "limit": limit})
    await db.commit()

    remaining = sum(1 for p in plan if p["action"] == "create") - len(created)
    return {
        "created": len(created),
        "remaining_to_import": max(0, remaining),
        "skipped_existing": sum(1 for p in plan if p["action"] == "existing"),
        "duplicates_in_file": sum(1 for p in plan if p["action"] == "duplicate_in_file"),
        "items": created,
    }


# ── Historical quotations ────────────────────────────────────────────────────
# These are finished documents from a system being retired, not live deals.
# They import as drafts by default and that is deliberate: the "at-risk deal"
# alert fires on quotations in `sent`, `pending_approval` and `approved`, so
# importing 137 quotations from 2023 in any of those states would hand every
# sales rep and the manager a screenful of "idle for 700 days" the next
# morning, and teach them to ignore the bell. The director can pick a
# different state, and can mark any individual one won or lost afterwards.
IMPORT_STATUSES = {"draft", "sent", "won", "lost"}


def _near_customer(key: str, by_name: dict[str, tuple]) -> str | None:
    """The one customer this name is probably a shortened form of, or None.

    Deliberately narrow: one side must be a whole-word prefix of the other,
    and exactly one candidate must qualify. Two candidates means it is
    genuinely ambiguous, and saying nothing beats picking.
    """
    if len(key) < 8:
        return None
    hits = [v[1] for k, v in by_name.items()
            if k != key and (k.startswith(key + " ") or key.startswith(k + " "))]
    return hits[0] if len(hits) == 1 else None


async def _plan_quotations(db: AsyncSession, mapped: list[MappedQuotation],
                           accept_near: bool = False) -> list[dict]:
    customers = (await db.execute(
        select(Customer.id, Customer.company_name, Customer.sales_pic_id)
        .where(Customer.is_deleted.is_(False))
    )).all()
    by_name: dict[str, tuple] = {}
    for cid, cname, pic in customers:
        by_name.setdefault(_name_key(cname), (cid, cname, pic))

    numbers = set((await db.scalars(select(Quotation.number))).all())

    seen: set[str] = set()
    plan: list[dict] = []
    for q in mapped:
        warnings = list(q.warnings)
        key = _name_key(q.customer_name)
        match = by_name.get(key)
        near_name = None if match else _near_customer(key, by_name)
        if near_name and accept_near:
            match = by_name[_name_key(near_name)]
            warnings.append(
                f"the export shortened the name to '{q.customer_name}'; filed "
                f"under '{near_name}'")

        if q.number in numbers:
            action = "existing"
        elif q.number in seen:
            action = "duplicate_in_file"
            warnings.append("this quotation number appears twice in the file")
        elif not match:
            # A quotation cannot exist without a customer to belong to, so
            # this is a hard skip rather than a warning on an imported row.
            action = "no_customer"
            warnings.append(
                f"no customer in the CRM matches '{q.customer_name}' — import "
                f"the customer list first, then run this again")
            # Some names come out of Accurate truncated ("PT PESONA
            # KHATULISTIWA" for "…NUSANTARA"). Naming the likely customer
            # saves a search; matching it automatically would be a guess, and
            # a quotation filed against the wrong company is worse than one
            # left out. So it is offered, not taken: the director sees exactly
            # which quotations these are and turns them on if they agree.
            if near_name:
                warnings.append(f"did you mean '{near_name}'?")
        elif not q.lines:
            action = "no_lines"
        else:
            action = "create"
            seen.add(q.number)

        plan.append({
            "sheet": q.sheet,
            "number": q.number,
            "action": action,
            "date": q.quote_date.isoformat() if q.quote_date else None,
            "customer_name": q.customer_name,
            "customer_id": str(match[0]) if match else None,
            "matched_customer": match[1] if match else None,
            "lines": len(q.lines),
            "dropped_rows": q.dropped_rows,
            "subtotal": q.computed_subtotal,
            "stated_subtotal": q.stated_subtotal,
            "warnings": warnings,
        })
    return plan


async def _read_quotation_upload(file: UploadFile) -> list[tuple[str, list[list]]]:
    data = await _bytes(file)
    try:
        sheets = read_workbook(data)
    except Exception as exc:                       # noqa: BLE001 — user-facing
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Could not read the workbook: {exc}. This import needs the .xlsx "
            f"file itself — one worksheet per quotation — not a CSV.") from exc
    return sheets


@router.post("/quotations/preview")
async def preview_quotations(
    file: UploadFile = File(...),
    accept_near_names: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director_only),
):
    sheets = await _read_quotation_upload(file)
    mapped, problems = map_quotations(sheets)
    plan = await _plan_quotations(db, mapped, accept_near_names)
    # How many more would come in if the shortened names were accepted — so
    # the offer can be made with a number attached rather than in the abstract.
    near = [p for p in plan if p["action"] == "no_customer"
            and any("did you mean" in w for w in p["warnings"])]
    return {
        "near_name_matches": len(near),
        "filename": file.filename,
        "sheets_in_file": len(sheets),
        "problems": problems,
        "counts": _tally(plan),
        "total_lines": sum(p["lines"] for p in plan),
        "dropped_rows": sum(p["dropped_rows"] for p in plan),
        "unmatched_customers": sorted({
            p["customer_name"] for p in plan if p["action"] == "no_customer"
        }),
        # What the file is worth, not what is left to import — the section this
        # feeds is headed "what this file contains", and counting only the
        # not-yet-imported rows made it read "Rp 0" the moment a run finished.
        "value": round(sum(p["subtotal"] for p in plan), 2),
        "rows": plan,
    }


@router.post("/quotations/commit")
async def commit_quotations(
    file: UploadFile = File(...),
    limit: int = Form(10),
    confirm: str = Form(""),
    quote_status: str = Form("draft"),
    accept_near_names: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_director_only),
):
    _require_confirm(confirm, limit)
    if quote_status not in IMPORT_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"status must be one of {', '.join(sorted(IMPORT_STATUSES))}")

    sheets = await _read_quotation_upload(file)
    mapped, problems = map_quotations(sheets)
    if not mapped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            problems[0] if problems else "Nothing to import")

    plan = await _plan_quotations(db, mapped, accept_near_names)
    by_number = {m.number: m for m in mapped}
    reps = {
        cid: pic for cid, pic in (await db.execute(
            select(Customer.id, Customer.sales_pic_id))).all()
    }

    created: list[dict] = []
    for p in plan:
        if len(created) >= limit:
            break
        if p["action"] != "create":
            continue
        src = by_number[p["number"]]
        cust_id = UUID(p["customer_id"])
        quo = Quotation(
            number=src.number,
            customer_id=cust_id,
            # The rep who owns the customer owns their history too — otherwise
            # the import is invisible to the only person it is useful to.
            sales_pic_id=reps.get(cust_id),
            status=quote_status,
            currency="IDR",
            subtotal=src.computed_subtotal,
            # The export states a subtotal and nothing else. Inventing 11% PPN
            # on top would change what these documents say they were worth.
            tax_pct=0,
            total=src.computed_subtotal,
            valid_until=None,
            notes=(f"Imported from {file.filename} (sheet {src.sheet}), "
                   f"dated {src.quote_date.isoformat() if src.quote_date else 'unknown'}."),
            created_by=me.id,
        )
        db.add(quo)
        await db.flush()
        for ln in src.lines:
            db.add(QuotationItem(
                quotation_id=quo.id,
                line_no=ln.line_no,
                source="custom",
                description=ln.description,
                qty=ln.qty,
                uom="pcs",
                unit_price=ln.unit_price,
                line_total=ln.line_total,
            ))
        await db.flush()
        created.append({"id": str(quo.id), "number": quo.number,
                        "customer": p["matched_customer"],
                        "lines": len(src.lines), "total": src.computed_subtotal})

    await record(db, actor=me, action="import", entity="quotation", entity_id=None,
                 after={"source": file.filename, "created": len(created),
                        "limit": limit, "status": quote_status})
    await db.commit()

    remaining = sum(1 for p in plan if p["action"] == "create") - len(created)
    return {
        "created": len(created),
        "remaining_to_import": max(0, remaining),
        "skipped_existing": sum(1 for p in plan if p["action"] == "existing"),
        "skipped_no_customer": sum(1 for p in plan if p["action"] == "no_customer"),
        "duplicates_in_file": sum(1 for p in plan if p["action"] == "duplicate_in_file"),
        "quotations": created,
    }
