"""Seed initial users + demo data.

Also creates the database schema if it doesn't exist yet (idempotent),
so first-run installs work without a separate migration step.
"""

import asyncio

from sqlalchemy import select

from app.core.db import Base, SessionLocal, engine
import app.models  # noqa: F401  ensure all models are registered with metadata
from app.core.security import hash_password
from app.models.crm import Customer
from app.models.user import User


_USERS = [
    ("director@demo.local", "Director Demo", "director"),
    ("manager@demo.local",  "Manager Demo",  "manager"),
    ("admin@demo.local",    "Admin Demo",    "admin"),
    ("sales1@demo.local",   "Sales One",     "sales"),
    ("sales2@demo.local",   "Sales Two",     "sales"),
]


async def ensure_schema() -> None:
    """Create any tables that don't exist yet. Safe to run repeatedly."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Schema ready.")


async def main() -> None:
    await ensure_schema()
    async with SessionLocal() as db:
        for email, name, role in _USERS:
            existing = await db.scalar(select(User).where(User.email == email))
            if existing:
                continue
            db.add(User(email=email, full_name=name, role=role,
                        password_hash=hash_password("demo1234"), is_active=True))
        await db.flush()

        sales1 = await db.scalar(select(User).where(User.email == "sales1@demo.local"))

        if not await db.scalar(select(Customer).limit(1)):
            db.add_all([
                Customer(company_name="PT Bara Kalsel", industry="mining",
                         pic_name="Andi", phone="+628123456789",
                         whatsapp="+628123456789", email="andi@bara.example",
                         sales_pic_id=sales1.id if sales1 else None,
                         stage="negotiation", payment_terms={"type": "termin"}),
                Customer(company_name="PT Semen Sukses", industry="cement",
                         pic_name="Ratna", whatsapp="+628199990001",
                         sales_pic_id=sales1.id if sales1 else None,
                         stage="quotation", payment_terms={"type": "tempo", "days": 60}),
                Customer(company_name="PLTU Cilacap", industry="pltu",
                         pic_name="Bambang", whatsapp="+628155551111",
                         sales_pic_id=sales1.id if sales1 else None,
                         stage="presentation"),
            ])
        await db.commit()
    print("Seed complete. Login with director@demo.local / demo1234 etc.")


if __name__ == "__main__":
    asyncio.run(main())
