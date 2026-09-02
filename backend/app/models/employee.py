"""The person, as HR knows them — recorded before there is a login.

Until now the only record of an employee was their user account, so somebody
only existed once IT had given them a password. That is backwards: a person is
hired, given a staff number and a position, and *then* gets a way to sign in —
sometimes weeks later, sometimes never (a workshop hand who never touches the
system is still an employee the company has to account for).

So this is the person; `users` is the login. One employee has at most one
login, and creating that login now requires the employee to exist first.

What is deliberately NOT here: bank details. Payroll routes money using
`users.bank_*`, and duplicating those columns would create two answers to
"where does this person's salary go" with nothing to say which wins. A person
with no login cannot be paid through the system anyway (a salary row keys on a
user), so the bank details are collected at the point they can first be used.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK

# The roles an employee can hold. Deliberately the internal set only —
# `customer` and `supplier` are portal logins for people outside the company,
# who are not employees and never get an employee record.
EMPLOYEE_ROLES = (
    "sales", "admin", "hr", "finance", "purchasing", "manager", "director",
)


class Employee(Base, UUIDPK, TimestampMixin):
    __tablename__ = "employees"

    # The staff number HR files them under (NIK). Unique, because it is the
    # number written on paperwork that has to point at exactly one person.
    employee_no: Mapped[str] = mapped_column(
        String(40), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Job title as it appears on a contract ("Sales Engineer"), which is not
    # the same thing as the access tier below and should not be confused with
    # it — two people can both be `sales` and hold different titles.
    position: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    # The access tier their login should get. Recorded at hire because it is
    # an HR decision, not an IT one; the director still confirms it when the
    # login is actually created.
    intended_role: Mapped[str | None] = mapped_column(String(20))
    join_date: Mapped[date | None] = mapped_column(Date)
    # The day they left. Set on a leaver — the record stays, because payroll,
    # attendance and every document they signed still refer to them.
    end_date: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(40))
    # Their own address, for reaching them before there is a company login and
    # after there isn't one any more. Never authenticated against.
    personal_email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
