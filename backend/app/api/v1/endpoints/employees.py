"""The employee register — the people, before and apart from their logins.

HR keeps this. The director creates logins against it: an internal account
cannot be created for somebody who is not on the register, which is the point
of the whole file. See `app/models/employee.py` for why the person and the
login are two records rather than one.
"""

from datetime import date as date_t
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.employee import EMPLOYEE_ROLES, Employee
from app.models.user import User

router = APIRouter()

_hr_or_director = require(Role.HR, Role.DIRECTOR)


class EmployeeIn(BaseModel):
    employee_no: str | None = None
    full_name: str
    position: str | None = None
    department: str | None = None
    intended_role: str | None = None
    join_date: date_t | None = None
    end_date: date_t | None = None
    phone: str | None = None
    personal_email: str | None = None
    notes: str | None = None


class EmployeePatch(BaseModel):
    employee_no: str | None = None
    full_name: str | None = None
    position: str | None = None
    department: str | None = None
    intended_role: str | None = None
    join_date: date_t | None = None
    end_date: date_t | None = None
    phone: str | None = None
    personal_email: str | None = None
    notes: str | None = None
    is_active: bool | None = None


def _check_role(role: str | None) -> str | None:
    """The intended access tier, or a refusal naming what is allowed."""
    if role is None or not role.strip():
        return None
    v = role.strip().lower()
    if v not in EMPLOYEE_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{role}' is not a role an employee can hold. "
            f"One of: {', '.join(EMPLOYEE_ROLES)}.",
        )
    return v


async def _next_employee_no(db: AsyncSession) -> str:
    """A staff number when HR does not supply one.

    Sequential within the year, so the number itself says when somebody
    joined. The count is of rows already numbered this year, so a manually
    typed number in the same series does not get handed out twice.
    """
    prefix = f"EMP-{date_t.today().year}-"
    used = set((await db.scalars(
        select(Employee.employee_no).where(Employee.employee_no.like(f"{prefix}%"))
    )).all())
    n = 1
    while f"{prefix}{n:03d}" in used:
        n += 1
    return f"{prefix}{n:03d}"


def _row(e: Employee, login: User | None) -> dict:
    return {
        "id": str(e.id),
        "employee_no": e.employee_no,
        "full_name": e.full_name,
        "position": e.position,
        "department": e.department,
        "intended_role": e.intended_role,
        "join_date": e.join_date,
        "end_date": e.end_date,
        "phone": e.phone,
        "personal_email": e.personal_email,
        "is_active": e.is_active,
        "notes": e.notes,
        # The login, when there is one. `has_login` is what the Users screen
        # filters on and what the register shows as "no login yet".
        "has_login": login is not None,
        "user_id": str(login.id) if login else None,
        "user_email": login.email if login else None,
        "user_role": login.role if login else None,
        "user_is_active": login.is_active if login else None,
    }


@router.get("/catalog")
async def catalog(_u: User = Depends(_hr_or_director)):
    """The roles an employee may hold — so no screen has to hardcode them."""
    return {"roles": list(EMPLOYEE_ROLES)}


@router.get("/departments/in-use")
async def departments_in_use(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    """Departments somebody is already filed under, so the next record is
    typed the same way rather than spelled a second way.

    Declared above `/{employee_id}` on purpose: routes match in the order
    they are written, and "departments" is not a UUID.
    """
    rows = (await db.execute(
        select(Employee.department, func.count(Employee.id))
        .where(Employee.department.isnot(None))
        .group_by(Employee.department)
        .order_by(Employee.department.asc())
    )).all()
    return [{"department": d, "people": n} for d, n in rows]


@router.get("")
async def list_employees(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    q: str | None = None,
    department: str | None = None,
    role: str | None = None,
    active_only: bool = True,
    # The user-creation picker asks for exactly the people who still need a
    # login; the register itself asks for everybody.
    without_login: bool = False,
):
    stmt = select(Employee).order_by(Employee.full_name.asc())
    if active_only:
        stmt = stmt.where(Employee.is_active.is_(True))
    if department:
        stmt = stmt.where(Employee.department == department)
    if role:
        stmt = stmt.where(Employee.intended_role == role)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Employee.full_name.ilike(like)
            | Employee.employee_no.ilike(like)
            | Employee.position.ilike(like)
        )
    rows = (await db.scalars(stmt)).all()
    logins = await _logins_for(db, [e.id for e in rows])
    # Tags and this month's missed days hang off the login, because that is
    # what attendance and the tag links key on. Carried here so the register
    # shows everything the old people list did rather than less.
    extras = await _login_extras(db, list(logins.values()))
    out = []
    for e in rows:
        login = logins.get(e.id)
        r = _row(e, login)
        uid = str(login.id) if login else None
        r["tags"] = extras["tags"].get(uid, []) if uid else []
        r["missed_days_this_month"] = extras["missed"].get(uid, 0.0) if uid else 0.0
        out.append(r)
    if without_login:
        out = [r for r in out if not r["has_login"]]
    return out


async def _login_extras(db: AsyncSession, users: list[User]) -> dict:
    """Tags and missed days for everyone with a login, in two queries."""
    from app.models.attendance import Attendance
    from app.models.tag import Tag, UserTagLink

    if not users:
        return {"tags": {}, "missed": {}}
    ids = [u.id for u in users]
    tags: dict[str, list[dict]] = {}
    for uid, tag in (await db.execute(
        select(UserTagLink.user_id, Tag)
        .join(Tag, Tag.id == UserTagLink.tag_id)
        .where(UserTagLink.user_id.in_(ids))
    )).all():
        tags.setdefault(str(uid), []).append({
            "id": str(tag.id), "name": tag.name,
            "color": tag.color, "description": tag.description,
        })

    today = date_t.today()
    month_start = today.replace(day=1)
    next_month = (date_t(today.year + 1, 1, 1) if today.month == 12
                  else date_t(today.year, today.month + 1, 1))
    missed: dict[str, float] = {}
    for uid, st, n in (await db.execute(
        select(Attendance.user_id, Attendance.status, func.count(Attendance.id))
        .where(Attendance.user_id.in_(ids),
               Attendance.date >= month_start, Attendance.date < next_month,
               Attendance.status.in_(["absent", "half_day"]))
        .group_by(Attendance.user_id, Attendance.status)
    )).all():
        missed[str(uid)] = round(
            missed.get(str(uid), 0.0) + n * (0.5 if st == "half_day" else 1.0), 1)
    return {"tags": tags, "missed": missed}


async def _logins_for(db: AsyncSession, ids: list[UUID]) -> dict[UUID, User]:
    """One query for everybody's login, rather than one per row."""
    if not ids:
        return {}
    users = (await db.scalars(
        select(User).where(User.employee_id.in_(ids))
    )).all()
    return {u.employee_id: u for u in users if u.employee_id}


@router.post("", status_code=201)
async def create_employee(
    payload: EmployeeIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_hr_or_director),
):
    name = (payload.full_name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An employee needs a name")
    no = (payload.employee_no or "").strip() or await _next_employee_no(db)
    clash = await db.scalar(select(Employee).where(Employee.employee_no == no))
    if clash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Staff number {no} already belongs to {clash.full_name}",
        )
    e = Employee(
        employee_no=no,
        full_name=name,
        position=(payload.position or None),
        department=(payload.department or None),
        intended_role=_check_role(payload.intended_role),
        join_date=payload.join_date,
        end_date=payload.end_date,
        phone=(payload.phone or None),
        personal_email=(payload.personal_email or None),
        notes=(payload.notes or None),
        created_by=me.id,
        is_active=True,
    )
    db.add(e)
    await db.flush()
    await audit_record(
        db, actor=me, action="create", entity="employee", entity_id=e.id,
        before=None, after={"employee_no": no, "full_name": name},
    )
    return _row(e, None)


@router.get("/{employee_id}")
async def get_employee(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    e = await db.get(Employee, employee_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    login = (await _logins_for(db, [e.id])).get(e.id)
    return _row(e, login)


@router.patch("/{employee_id}")
async def update_employee(
    employee_id: UUID,
    payload: EmployeePatch,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_hr_or_director),
):
    e = await db.get(Employee, employee_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    data = payload.model_dump(exclude_unset=True)
    if "employee_no" in data:
        no = (data["employee_no"] or "").strip()
        if not no:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "An employee needs a staff number")
        clash = await db.scalar(
            select(Employee).where(Employee.employee_no == no, Employee.id != e.id))
        if clash:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Staff number {no} already belongs to {clash.full_name}")
        data["employee_no"] = no
    if "intended_role" in data:
        data["intended_role"] = _check_role(data["intended_role"])
    if "full_name" in data:
        name = (data["full_name"] or "").strip()
        if not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An employee needs a name")
        data["full_name"] = name
    before = {k: getattr(e, k) for k in data}
    for k, v in data.items():
        setattr(e, k, v)

    login = (await _logins_for(db, [e.id])).get(e.id)
    if login:
        # The register is where the start date is decided; payroll reads it
        # off the login. Carry it across rather than leaving the two to
        # disagree about when somebody's first partial month was.
        if "join_date" in data:
            login.join_date = data["join_date"]
        # Renaming somebody here renames them everywhere. The alternative —
        # HR fixes a misspelling and the name on next month's documents is
        # still wrong — is how two spellings of one person get into a system.
        if "full_name" in data:
            login.full_name = data["full_name"]
    await audit_record(
        db, actor=me, action="update", entity="employee", entity_id=e.id,
        before={k: str(v) if v is not None else None for k, v in before.items()},
        after={k: str(v) if v is not None else None for k, v in data.items()},
    )
    return _row(e, login)


@router.delete("/{employee_id}", status_code=204)
async def deactivate_employee(
    employee_id: UUID,
    hard: bool = False,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require(Role.DIRECTOR)),
):
    """Mark a leaver, or (director, `?hard=true`) remove a record typed by
    mistake. A record with a login attached is never removed — deleting the
    person out from under an account that still signs documents is not a
    correction, it is a hole."""
    e = await db.get(Employee, employee_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    login = (await _logins_for(db, [e.id])).get(e.id)
    if not hard:
        e.is_active = False
        if not e.end_date:
            e.end_date = date_t.today()
        await audit_record(
            db, actor=me, action="deactivate", entity="employee", entity_id=e.id,
            before={"is_active": "True"}, after={"is_active": "False"},
        )
        return None
    if login:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{e.full_name} has a login ({login.email}). Delete the user "
            "account first, or mark them a leaver instead.",
        )
    await audit_record(
        db, actor=me, action="delete", entity="employee", entity_id=e.id,
        before={"employee_no": e.employee_no, "full_name": e.full_name}, after=None,
    )
    await db.delete(e)
    return None


@router.get("/{employee_id}/summary")
async def employee_summary(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    """Enough to decide whether this record is the person you meant —
    how long they have been here, and whether they can sign in."""
    e = await db.get(Employee, employee_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    login = (await _logins_for(db, [e.id])).get(e.id)
    months = None
    if e.join_date:
        end = e.end_date or date_t.today()
        months = max(0, (end.year - e.join_date.year) * 12
                     + (end.month - e.join_date.month))
    return {**_row(e, login), "months_of_service": months}
