"""Employee directory endpoints (HR + Director only)."""

from datetime import UTC, datetime, timedelta
from datetime import date as date_t
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require, require_min
from app.core.security import hash_password
from app.models.attendance import Attendance
from app.models.crm import Activity, Customer
from app.models.quotation import Quotation
from app.models.tag import Tag, UserTagLink
from app.models.user import User
from app.schemas.auth import UserOut

_director = require(Role.DIRECTOR)


class UserCreate(BaseModel):
    email: str
    # Optional. Where this person corresponds from, when that is not the
    # address they sign in with.
    contact_email: str | None = None
    full_name: str
    role: str   # sales | admin | hr | manager | director | customer | supplier
    password: str
    phone: str | None = None
    whatsapp_id: str | None = None
    linked_customer_id: UUID | None = None
    linked_supplier_id: UUID | None = None
    custom_role_id: UUID | None = None
    pages: list[str] | None = None


class UserPatch(BaseModel):
    full_name: str | None = None
    contact_email: str | None = None
    role: str | None = None
    phone: str | None = None
    whatsapp_id: str | None = None
    is_active: bool | None = None
    # The employment record. A date as YYYY-MM-DD, or null to clear it.
    join_date: date_t | None = None
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_account_name: str | None = None
    password: str | None = None
    linked_customer_id: UUID | None = None
    linked_supplier_id: UUID | None = None
    custom_role_id: UUID | None = None
    pages: list[str] | None = None


VALID_ROLES = {"sales", "admin", "hr", "finance", "manager", "director", "customer", "supplier", "purchasing"}


def _clean_contact_email(value: str | None) -> str | None:
    """Normalise the correspondence address, or refuse it.

    Empty clears it. Anything kept has to look like an address, because it is
    printed on quotations customers read — a typo there is a lost reply, not a
    failed login, so nothing downstream would ever surface it.

    Note what is deliberately absent: a uniqueness check. This is a contact
    detail, not an identity. Two people may share a shared mailbox, and
    nothing authenticates against it.
    """
    if value is None:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if len(v) > 255 or v.count("@") != 1 or v.startswith("@") or v.endswith("@") \
            or "." not in v.split("@")[1] or " " in v:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"'{value}' does not look like an email address")
    return v


def _validate_pages(pages: list[str] | None) -> None:
    """Reject any page path not in the shared catalog."""
    if not pages:
        return
    from app.api.v1.endpoints.custom_roles import _VALID_PAGES
    bad = [p for p in pages if p not in _VALID_PAGES]
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown pages: {bad}")

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)

_hr_or_director = require(Role.HR, Role.DIRECTOR)


@router.get("")
async def list_employees(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_hr_or_director),
    role: str | None = None,
    q: str | None = None,
    active_only: bool = True,
):
    stmt = select(User).order_by(User.full_name.asc())
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.full_name.ilike(like)) | (User.email.ilike(like)))
    rows = (await db.scalars(stmt)).all()

    # Bulk-load custom role names for the assigned users.
    from app.models.custom_role import CustomRole
    cr_ids = {r.custom_role_id for r in rows if r.custom_role_id}
    cr_names: dict = {}
    if cr_ids:
        for cr in (await db.scalars(
            select(CustomRole).where(CustomRole.id.in_(cr_ids))
        )).all():
            cr_names[cr.id] = cr.name

    # Bulk load tags for all users in one query
    tag_map: dict[str, list[dict]] = {}
    if rows:
        user_ids = [r.id for r in rows]
        result = await db.execute(
            select(UserTagLink.user_id, Tag)
            .join(Tag, Tag.id == UserTagLink.tag_id)
            .where(UserTagLink.user_id.in_(user_ids))
        )
        for uid, tag in result.all():
            tag_map.setdefault(str(uid), []).append({
                "id": str(tag.id), "name": tag.name,
                "color": tag.color, "description": tag.description,
            })

    # Bulk-compute this month's missed days for everyone (absent + half_day*0.5)
    today = date_t.today()
    month_start = today.replace(day=1)
    # First of next month
    if today.month == 12:
        next_month = date_t(today.year + 1, 1, 1)
    else:
        next_month = date_t(today.year, today.month + 1, 1)

    missed_map: dict[str, float] = {}
    if rows:
        att_q = await db.execute(
            select(Attendance.user_id, Attendance.status, func.count(Attendance.id))
            .where(
                Attendance.user_id.in_([r.id for r in rows]),
                Attendance.date >= month_start,
                Attendance.date < next_month,
                Attendance.status.in_(["absent", "half_day"]),
            )
            .group_by(Attendance.user_id, Attendance.status)
        )
        for uid, st, n in att_q.all():
            missed_map[str(uid)] = (
                missed_map.get(str(uid), 0.0) + (n * (0.5 if st == "half_day" else 1.0))
            )

    # HR sees the directory but not personal contact details (email/phone).
    hide_contact = Role(me.role) == Role.HR
    return [
        {
            "id": str(r.id),
            "email": "(hidden)" if hide_contact else r.email,
            "contact_email": None if hide_contact else r.contact_email,
            "full_name": r.full_name,
            "role": r.role,
            "custom_role_id": str(r.custom_role_id) if r.custom_role_id else None,
            "custom_role_name": cr_names.get(r.custom_role_id) if r.custom_role_id else None,
            "pages": r.pages or [],
            "phone": None if hide_contact else r.phone,
            # The employment record. Not contact details — this is the
            # payroll side of the person, which is HR's whole job, so it
            # stays visible to them when email and phone do not.
            "join_date": r.join_date,
            "bank_name": r.bank_name,
            "bank_account_no": r.bank_account_no,
            "bank_account_name": r.bank_account_name,
            "is_active": r.is_active,
            "tags": tag_map.get(str(r.id), []),
            "missed_days_this_month": round(missed_map.get(str(r.id), 0.0), 1),
        }
        for r in rows
    ]


@router.get("/{user_id}", response_model=UserOut)
async def get_employee(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    # employees can always read their own profile; HR + Director can read anyone
    if me.id != user_id and Role(me.role) not in (Role.HR, Role.DIRECTOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    obj = await db.get(User, user_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    # HR administers people but must not see employees' personal contact info.
    # Build a detached copy so we never mutate (and accidentally persist) the row.
    if Role(me.role) == Role.HR and me.id != user_id:
        return UserOut.model_validate(obj).model_copy(
            update={"email": "(hidden)", "phone": None}
        )
    return obj


@router.get("/{user_id}/stats")
async def employee_stats(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_hr_or_director),
):
    from app.models.operation import Project

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    customers_count = await db.scalar(
        select(func.count(Customer.id)).where(
            Customer.sales_pic_id == user_id, Customer.is_deleted.is_(False)
        )
    ) or 0
    quotations_count = await db.scalar(
        select(func.count(Quotation.id)).where(Quotation.sales_pic_id == user_id)
    ) or 0
    won = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "won"
        )
    ) or 0
    lost = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "lost"
        )
    ) or 0
    pipeline_value = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(
            Quotation.sales_pic_id == user_id,
            Quotation.status.in_(["draft", "pending_approval", "approved", "sent"]),
        )
    )
    won_revenue = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "won"
        )
    )
    activities_30d = await db.scalar(
        select(func.count(Activity.id)).where(
            Activity.user_id == user_id,
            Activity.occurred_at >= datetime.now(UTC) - timedelta(days=30),
        )
    ) or 0
    # All-time attendance tally (present-like vs absent-like days)
    att_present = await db.scalar(
        select(func.count(Attendance.id)).where(
            Attendance.user_id == user_id, Attendance.status.in_(["present", "wfh"])
        )
    ) or 0
    att_absent = await db.scalar(
        select(func.count(Attendance.id)).where(
            Attendance.user_id == user_id, Attendance.status == "absent"
        )
    ) or 0
    att_leave = await db.scalar(
        select(func.count(Attendance.id)).where(
            Attendance.user_id == user_id, Attendance.status.in_(["leave", "sick"])
        )
    ) or 0
    decided = won + lost

    # Fulfillment counts (no names, no money) — these are what HR is allowed
    # to see: how much of the person's work is done vs. overdue.
    _FULFILLED = {"delivered", "invoiced", "paid", "closed"}
    proj_rows = (await db.execute(
        select(Project.status, Project.target_delivery, Project.actual_delivery)
        .join(Customer, Project.customer_id == Customer.id)
        # A deleted project must not keep counting against an employee's
        # overdue tally — deleting it IS the resolution.
        .where(Customer.sales_pic_id == user_id, Project.is_deleted.is_(False))
    )).all()
    today = date_t.today()
    projects_total = len(proj_rows)
    projects_fulfilled = sum(1 for st, _t, _a in proj_rows if st in _FULFILLED)
    projects_overdue = sum(
        1 for st, td, ad in proj_rows
        if td and td < today and not ad and st not in _FULFILLED
    )

    # Attendance + fulfillment only — the slice HR may see.
    base = {
        "user_id": str(user_id),
        "full_name": user.full_name,
        "role": user.role,
        "attendance_present_total": att_present,
        "attendance_absent_total": att_absent,
        "attendance_leave_total": att_leave,
        "projects_total": projects_total,
        "projects_fulfilled": projects_fulfilled,
        "projects_overdue": projects_overdue,
    }
    if Role(me.role) == Role.HR:
        # No sales performance, revenue, pipeline, or customer counts for HR.
        return base
    return {
        **base,
        "customers": customers_count,
        "quotations": quotations_count,
        "won": won,
        "lost": lost,
        "win_rate": round((won / decided), 3) if decided else 0,
        "pipeline_value": float(pipeline_value or 0),
        "won_revenue": float(won_revenue or 0),
        "activities_30d": activities_30d,
    }


@router.get("/{user_id}/projects")
async def employee_projects(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_hr_or_director),
    limit: int = 200,
):
    """Projects tied to the employee's customers. Project values are shown to
    the director only — HR sees the list without deal economics."""
    from app.models.operation import Project

    rows = (await db.execute(
        select(Project, Customer)
        .join(Customer, Project.customer_id == Customer.id)
        .where(Customer.sales_pic_id == user_id, Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )).all()
    # HR sees fulfillment status only — no customer names, no deal value.
    is_hr = Role(me.role) == Role.HR
    show_money = Role(me.role) == Role.DIRECTOR
    return [
        {
            "id": str(p.id),
            "code": p.code,
            "status": p.status,
            "customer_id": None if is_hr else str(c.id),
            "customer_name": None if is_hr else c.company_name,
            "po_value": float(p.po_value or 0) if show_money else None,
            "target_delivery": p.target_delivery,
        }
        for p, c in rows
    ]


@router.get("/{user_id}/quotations")
async def employee_quotations(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
    status_eq: str | None = None,
    limit: int = 200,
):
    stmt = (
        select(Quotation, Customer)
        .join(Customer, Quotation.customer_id == Customer.id)
        .where(Quotation.sales_pic_id == user_id)
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    if status_eq:
        stmt = stmt.where(Quotation.status == status_eq)
    out = []
    for q, c in (await db.execute(stmt)).all():
        out.append({
            "id": str(q.id),
            "number": q.number,
            "customer_id": str(c.id),
            "customer_name": c.company_name,
            "variant": q.variant,
            "status": q.status,
            "discount_pct": float(q.discount_pct or 0),
            "total": float(q.total or 0),
            "valid_until": q.valid_until,
            "created_at": q.created_at,
        })
    return out


@router.get("/{user_id}/customers")
async def employee_customers(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
    limit: int = 200,
):
    rows = (await db.scalars(
        select(Customer).where(
            Customer.sales_pic_id == user_id, Customer.is_deleted.is_(False)
        ).order_by(Customer.company_name.asc()).limit(limit)
    )).all()
    return [
        {
            "id": str(c.id),
            "company_name": c.company_name,
            "industry": c.industry,
            "stage": c.stage,
            "lifetime_value": float(c.lifetime_value or 0),
        }
        for c in rows
    ]


@router.get("/{user_id}/activities")
async def employee_activities(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
    limit: int = 100,
):
    stmt = (
        select(Activity, Customer)
        .join(Customer, Activity.customer_id == Customer.id)
        .where(Activity.user_id == user_id)
        .order_by(Activity.occurred_at.desc())
        .limit(limit)
    )
    out = []
    for a, c in (await db.execute(stmt)).all():
        out.append({
            "id": str(a.id),
            "type": a.type,
            "direction": a.direction,
            "occurred_at": a.occurred_at,
            "notes": a.notes,
            "customer_id": str(c.id),
            "customer_name": c.company_name,
        })
    return out


# ─── Director-only user management ───────────────────────────────────────────

@router.post("", status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"role must be one of: {', '.join(sorted(VALID_ROLES))}")
    if len(payload.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "password must be at least 6 chars")
    existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
    if payload.role == "customer" and not payload.linked_customer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "customer accounts need linked_customer_id")
    if payload.role == "supplier" and not payload.linked_supplier_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "supplier accounts need linked_supplier_id")
    # If a custom role is chosen, force the base role to the custom role's
    # base_role so all API security checks stay consistent.
    role = payload.role
    if payload.custom_role_id:
        from app.models.custom_role import CustomRole
        cr = await db.get(CustomRole, payload.custom_role_id)
        if not cr:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown custom_role_id")
        role = cr.base_role
    _validate_pages(payload.pages)
    u = User(
        email=payload.email.lower(),
        contact_email=_clean_contact_email(payload.contact_email),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=role,
        phone=payload.phone,
        whatsapp_id=payload.whatsapp_id,
        linked_customer_id=payload.linked_customer_id,
        linked_supplier_id=payload.linked_supplier_id,
        custom_role_id=payload.custom_role_id,
        pages=payload.pages or None,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return {"id": str(u.id), "email": u.email, "role": u.role}


# What HR may correct on somebody's record. The employment side of the
# person — who they are, when they started, where their salary goes — which
# is the job HR actually does and the reason this page exists for them.
#
# Everything else stays the director's: the role (that is the security
# tier), the pages, the password, the login address, and whether the account
# is active at all. Phone and contact email are absent for a different
# reason — HR cannot even read those, so being able to set them would be
# writing blind into a field they are not allowed to see.
_HR_EDITABLE = {
    "full_name", "join_date", "bank_name", "bank_account_no",
    "bank_account_name",
}


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID,
    payload: UserPatch,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    if Role(_u.role) is Role.HR:
        beyond = sorted(set(data) - _HR_EDITABLE)
        if beyond:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "HR keeps the employment record — the name, the start date "
                "and the bank details. "
                f"{', '.join(beyond)} is the director's to change.",
            )
    # Where the salary goes is money-routing data, so a change to it is
    # written down: who changed whose, and to what. Same for the start date,
    # which decides a first month's pay.
    before = {k: getattr(u, k) for k in data if k in _HR_EDITABLE}
    if "role" in data and data["role"] not in VALID_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role")
    if "pages" in data:
        _validate_pages(data["pages"])
        # An empty list clears the override (stored as NULL).
        data["pages"] = data["pages"] or None
    if "contact_email" in data:
        data["contact_email"] = _clean_contact_email(data["contact_email"])
    if "password" in data:
        if len(data["password"]) < 6:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "password too short")
        u.password_hash = hash_password(data.pop("password"))
    # Assigning a custom role pins the base role to the custom role's tier;
    # clearing it (custom_role_id=None) leaves the explicit role as-is.
    if "custom_role_id" in data and data["custom_role_id"]:
        from app.models.custom_role import CustomRole
        cr = await db.get(CustomRole, data["custom_role_id"])
        if not cr:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown custom_role_id")
        data["role"] = cr.base_role
    for k, v in data.items():
        setattr(u, k, v)
    touched = {k: v for k, v in data.items() if k in _HR_EDITABLE}
    if touched:
        from app.core.audit import record as audit_record
        await audit_record(
            db, actor=_u, action="update", entity="employee", entity_id=u.id,
            before={k: str(v) if v is not None else None
                    for k, v in before.items()},
            after={k: str(v) if v is not None else None
                   for k, v in touched.items()},
        )
    return {"id": str(u.id), "ok": True}


@router.post("/{user_id}/signature")
async def upload_signature(
    user_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Store a scanned signature for this person.

    Anyone may set their own; the director may set anybody's, because in
    practice one person collects the scans and uploads them rather than
    chasing eleven people to each log in and do it.

    A PNG with a transparent background prints best — it sits over the rule
    in the signature block instead of covering it with a white rectangle —
    but a phone photo of a signature on white paper works too.
    """
    from app.services import signature as sig
    from app.services import storage

    if me.id != user_id and Role(me.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "You can only change your own signature")
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    data = await file.read()
    try:
        width, height = sig.validate(data, file.content_type)
    except sig.SignatureError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    old = u.signature_path
    u.signature_path = await storage.save(
        data, filename=file.filename or "signature.png", label="signature",
        owner_type="user", owner_id=u.id,
    )
    # Replacing one should not leave the old file behind; failing to delete
    # it must not fail the upload, which has already succeeded.
    if old and old != u.signature_path:
        try:
            await storage.delete(old)
        except Exception:
            pass
    await db.flush()
    return {"ok": True, "width": width, "height": height,
            "transparent_background": (file.content_type or "").endswith("png")}


@router.get("/{user_id}/signature")
async def get_signature(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """The stored signature image, for previewing it before it goes on a
    document. Readable by the person themselves and by management — it
    appears on documents they all handle anyway."""
    from fastapi.responses import Response as _Response

    from app.services import signature as sig

    if me.id != user_id and Role(me.role) not in (
            Role.DIRECTOR, Role.MANAGER, Role.ADMIN, Role.HR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    u = await db.get(User, user_id)
    if not u or not u.signature_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No signature on file")
    data = await sig.load_for(u)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signature file is missing")
    kind = "image/png" if u.signature_path.lower().endswith(".png") else "image/jpeg"
    return _Response(content=data, media_type=kind,
                     headers={"Cache-Control": "private, max-age=60"})


@router.delete("/{user_id}/signature", status_code=204)
async def delete_signature(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Remove it. Documents go back to leaving a blank space to sign by hand."""
    from app.services import storage

    if me.id != user_id and Role(me.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "You can only change your own signature")
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if u.signature_path:
        try:
            await storage.delete(u.signature_path)
        except Exception:
            pass
        u.signature_path = None
        await db.flush()
    return None


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    hard: bool = False,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_director),
):
    """Soft-disable by default. Pass ?hard=true for a permanent delete
    (keeps audit log entries via SET NULL FK; refuses if the user is
    referenced anywhere we can't safely null out)."""
    if user_id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not hard:
        u.is_active = False
        return None
    # Hard delete: explicitly NULL the cached author/owner columns first
    # so we never hit a NOT NULL FK constraint. Tables that ON DELETE
    # SET NULL or CASCADE handle themselves at DB level.
    from app.models.crm import Customer
    from app.models.quotation import Quotation
    for col, model in [
        (Customer.sales_pic_id, Customer),
        (Customer.created_by,   Customer),
        (Customer.updated_by,   Customer),
        (Quotation.sales_pic_id, Quotation),
        (Quotation.created_by,   Quotation),
        (Quotation.updated_by,   Quotation),
    ]:
        rows = (await db.scalars(select(model).where(col == user_id))).all()
        for r in rows:
            setattr(r, col.key, None)
    await db.flush()
    await db.delete(u)
    return None
