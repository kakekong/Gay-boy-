"""Seed initial users + demo data.

Also creates the database schema if it doesn't exist yet (idempotent),
so first-run installs work without a separate migration step.

When the model gains columns on an existing table, `create_all` won't
add them automatically — we run a tiny ALTER-TABLE migrator below that
keeps demo installs upgradeable without alembic discipline.
"""

import asyncio
import os

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
    # Stage-task kinds like "stage:negotiation:second_follow_up" can exceed 30
    'ALTER TABLE reminders ALTER COLUMN kind TYPE VARCHAR(80)',

    # CustomerContact table is created by create_all; nothing to migrate.

    # User gained portal-scope links (for customer / supplier accounts)
    'ALTER TABLE users ADD COLUMN IF NOT EXISTS linked_customer_id UUID',
    'ALTER TABLE users ADD COLUMN IF NOT EXISTS linked_supplier_id UUID',
    'CREATE INDEX IF NOT EXISTS ix_users_linked_customer_id ON users (linked_customer_id)',
    'CREATE INDEX IF NOT EXISTS ix_users_linked_supplier_id ON users (linked_supplier_id)',

    # Customer gained tax info (NPWP / NPPKP / PKP status)
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_id      VARCHAR(32)',
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_name    VARCHAR(255)',
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_address TEXT',
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_pkp BOOLEAN NOT NULL DEFAULT false",
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS nppkp_no    VARCHAR(64)',
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_notes   TEXT',

    # Project gained a shipping timeline + import flag
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_ship_from_origin DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS act_ship_from_origin DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_arrive_our_warehouse DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS act_arrive_our_warehouse DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_arrive_customer DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS act_arrive_customer DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin_location VARCHAR(120)',
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_import BOOLEAN NOT NULL DEFAULT false",
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
    from app.core.config import settings
    is_prod = settings.APP_ENV.lower() == "prod"

    await ensure_schema()
    # Chart of Accounts seed
    from app.scripts.coa_seed import seed_coa
    async with SessionLocal() as db:
        coa_created = await seed_coa(db)
        await db.commit()
        print(f"CoA: {coa_created} account(s) inserted.")

    # Demo users — only in dev. In prod, the director creates real accounts
    # via Admin → Users, and any stray demo accounts get deactivated.
    async with SessionLocal() as db:
        if is_prod:
            seeded_emails = [u[0] for u in _USERS]
            stale = (await db.scalars(
                select(User).where(User.email.in_(seeded_emails), User.is_active.is_(True))
            )).all()
            for u in stale:
                u.is_active = False
            if stale:
                print(f"PROD: deactivated {len(stale)} demo user(s) "
                      f"(set APP_ENV=dev if you want them).")
        else:
            # Demo password must be supplied per-deployment so a public
            # instance never ships with a known director password — even if
            # APP_ENV is misconfigured. Leave DEMO_SEED_PASSWORD unset to
            # skip seeding privileged demo accounts entirely.
            demo_pw = os.getenv("DEMO_SEED_PASSWORD", "").strip()
            if not demo_pw:
                print("Skipping demo-user seed: DEMO_SEED_PASSWORD not set.")
            else:
                for email, name, role in _USERS:
                    existing = await db.scalar(select(User).where(User.email == email))
                    if existing:
                        continue
                    db.add(User(email=email, full_name=name, role=role,
                                password_hash=hash_password(demo_pw), is_active=True))
                await db.flush()

        if not is_prod:
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

    # Backfill stage-task reminders for every existing customer
    async with SessionLocal() as db:
        from app.core.stage_tasks import ensure_stage_tasks
        customers = (await db.scalars(select(Customer))).all()
        spawned = 0
        for c in customers:
            spawned += len(await ensure_stage_tasks(db, c, c.stage))
        await db.commit()
        if spawned:
            print(f"Stage tasks: spawned {spawned} reminder(s).")
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
