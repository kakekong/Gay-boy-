"""Seed initial users + demo data.

Also creates the database schema if it doesn't exist yet (idempotent),
so first-run installs work without a separate migration step.

When the model gains columns on an existing table, `create_all` won't
add them automatically — we run a tiny ALTER-TABLE migrator below that
keeps demo installs upgradeable without alembic discipline.
"""

import asyncio

from sqlalchemy import select, text

from app.core.db import Base, SessionLocal, engine
import app.models  # noqa: F401  ensure all models are registered with metadata
from app.core.security import hash_password
from app.models.crm import Customer
from app.models.user import User


_USERS = [
    ("director@demo.local", "Director Demo", "director"),
    ("manager@demo.local",  "Manager Demo",  "manager"),
    ("admin@demo.local",    "Admin Demo",    "admin"),
    ("hr@demo.local",       "HR Demo",       "hr"),
    ("sales1@demo.local",   "Sales One",     "sales"),
    ("sales2@demo.local",   "Sales Two",     "sales"),
]


# ─── Lightweight forward-only migrations ─────────────────────────────────────
# Every statement here is idempotent (`ADD COLUMN IF NOT EXISTS`). Add new
# entries below as the model evolves. Postgres-only.
COLUMN_MIGRATIONS: list[str] = [
    # Quotation gained CoA linkage + ledger-posting state
    'ALTER TABLE quotations ADD COLUMN IF NOT EXISTS account_revenue_no    VARCHAR(40)',
    'ALTER TABLE quotations ADD COLUMN IF NOT EXISTS account_receivable_no VARCHAR(40)',
    'ALTER TABLE quotations ADD COLUMN IF NOT EXISTS account_discount_no   VARCHAR(40)',
    'ALTER TABLE quotations ADD COLUMN IF NOT EXISTS account_tax_no        VARCHAR(40)',
    "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS is_posted BOOLEAN NOT NULL DEFAULT false",
    'ALTER TABLE quotations ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ',
    "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS posted_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb",

    # Reminder gained recurrence
    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recurs VARCHAR(20) NOT NULL DEFAULT 'none'",
    'ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recurs_until DATE',
    'ALTER TABLE reminders ADD COLUMN IF NOT EXISTS parent_reminder_id UUID',
]


async def ensure_schema() -> None:
    """Create any tables that don't exist yet. Safe to run repeatedly."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Schema ready.")

    # Forward-only column migrations
    async with engine.begin() as conn:
        for stmt in COLUMN_MIGRATIONS:
            try:
                await conn.execute(text(stmt))
            except Exception as exc:
                # Don't block seed on a single bad migration; report so we can fix it.
                print(f"  ! migration skipped: {stmt[:80]}…  ({exc.__class__.__name__})")
    print(f"Ran {len(COLUMN_MIGRATIONS)} column migration(s) (no-op when up-to-date).")


async def main() -> None:
    await ensure_schema()
    # Chart of Accounts seed
    from app.scripts.coa_seed import seed_coa
    async with SessionLocal() as db:
        coa_created = await seed_coa(db)
        await db.commit()
        print(f"CoA: {coa_created} account(s) inserted.")
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
