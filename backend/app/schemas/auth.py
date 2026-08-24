from datetime import date
from uuid import UUID

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: UUID
    email: str
    # Where this person is reachable, when it differs from the login.
    contact_email: str | None = None
    full_name: str
    role: str
    phone: str | None = None
    is_active: bool
    # The employment record HR keeps: the day they started, and the account
    # payroll pays into. Only ever returned where the whole profile already
    # is — the person themselves, HR, and the director.
    join_date: date | None = None
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_account_name: str | None = None
    # Custom role overlay (display name + allowed pages), when assigned.
    custom_role_id: UUID | None = None
    custom_role_name: str | None = None
    custom_role_pages: list[str] | None = None

    model_config = {"from_attributes": True}
