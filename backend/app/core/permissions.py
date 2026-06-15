"""Role-based access control + helpers used across the app."""

from collections.abc import Iterable
from enum import StrEnum

from fastapi import Depends, HTTPException, status

from app.core.deps import get_current_user
from app.models.user import User


class Role(StrEnum):
    SALES = "sales"
    ADMIN = "admin"
    HR = "hr"
    FINANCE = "finance"
    MANAGER = "manager"
    DIRECTOR = "director"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    PURCHASING = "purchasing"


_HIERARCHY = {
    Role.CUSTOMER: 0, Role.SUPPLIER: 0,
    Role.SALES: 1,
    Role.ADMIN: 2, Role.HR: 2, Role.PURCHASING: 2, Role.FINANCE: 2,
    Role.MANAGER: 3,
    Role.DIRECTOR: 4,
}


def at_least(required: Role, actual: Role) -> bool:
    return _HIERARCHY[Role(actual)] >= _HIERARCHY[required]


def require(*allowed: Role | str):
    """FastAPI dependency: only listed roles may pass."""
    allowed_set = {Role(a) for a in allowed}

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if Role(user.role) not in allowed_set:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return _dep


def require_min(role: Role):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if not at_least(role, user.role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return _dep


def can_view_customer(user: User, sales_pic_id) -> bool:
    """Sales sees only their own customers; everyone else sees all."""
    if Role(user.role) == Role.SALES:
        return user.id == sales_pic_id
    return True


def can_approve_quotation(user: User) -> bool:
    return Role(user.role) in (Role.MANAGER, Role.DIRECTOR)


def filter_to_role_scope(user: User, query, sales_pic_column):
    """Apply RBAC scoping to a SQLAlchemy query."""
    if Role(user.role) == Role.SALES:
        return query.where(sales_pic_column == user.id)
    return query


def all_roles() -> Iterable[Role]:
    return tuple(Role)
