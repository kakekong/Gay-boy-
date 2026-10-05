"""Sign-in history: every attempt to get into the system, and every exit.

The audit log answers "who changed this record". This answers the question
before it — who got in, when, from where — including the attempts that did
not get in, which is the half a director most wants to see: a password tried
five times against one account at night is a story the audit log never tells,
because nothing was changed.

One row per event:

* ``login``    — signed in with a password.
* ``failed``   — a wrong password, an unknown address, or a deactivated
  account (``reason`` says which). ``user_id`` is set when the address
  belongs to an account, so a guessing attempt shows on that person's history.
* ``blocked``  — refused by the rate limit before the password was checked.
* ``logout``   — pressed Sign out.
* ``view_as``  — the director opened this account with "View as";
  ``actor_id`` is the director.

Passwords are never stored, not even the wrong ones.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPK


class LoginEvent(Base, UUIDPK):
    __tablename__ = "login_events"

    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # The address typed, kept as typed (lower-cased) so an attempt on an
    # address that is nobody's still reads as something.
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    event: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(40))
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    # "Safari · iPhone" — worked out once, at write time.
    device: Mapped[str | None] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ActionLog(Base, UUIDPK):
    """One row per change request anybody made — every POST, PUT, PATCH and
    DELETE that carried a sign-in.

    The audit log records the important changes in detail (before and after),
    but only where an endpoint writes one. This is the complete list, in less
    detail: who, what (method and path), the outcome, when. Request bodies are
    never stored. Together with `LoginEvent` it is one person's whole history.
    """
    __tablename__ = "action_log"

    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # The director, when this was done in a "View as" session.
    via_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
