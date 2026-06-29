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
    # Users gained an optional per-user sidebar page override
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pages JSONB",
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

    # Quotation gained an addressed-to contact (which customer PIC this
    # quotation is for). NULL means "use the primary PIC on the customer."
    'ALTER TABLE quotations ADD COLUMN IF NOT EXISTS contact_id UUID',
    'CREATE INDEX IF NOT EXISTS ix_quotations_contact_id ON quotations (contact_id)',

    # customer_pos table — created lazily here for installs upgrading from
    # before the model existed. create_all() also handles fresh installs.
    """
    CREATE TABLE IF NOT EXISTS customer_pos (
        id UUID PRIMARY KEY,
        number VARCHAR(80) NOT NULL,
        po_date DATE,
        customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
        quotation_id UUID REFERENCES quotations(id) ON DELETE SET NULL,
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
        total NUMERIC(18,2) NOT NULL DEFAULT 0,
        items JSONB NOT NULL DEFAULT '[]'::jsonb,
        notes TEXT,
        status VARCHAR(30) NOT NULL DEFAULT 'pending_approval',
        decided_by UUID REFERENCES users(id) ON DELETE SET NULL,
        decided_at TIMESTAMPTZ,
        decision_notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by UUID,
        updated_by UUID
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_customer_pos_customer_id ON customer_pos (customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_customer_pos_quotation_id ON customer_pos (quotation_id)",
    "CREATE INDEX IF NOT EXISTS ix_customer_pos_project_id ON customer_pos (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_customer_pos_status ON customer_pos (status)",
    "CREATE INDEX IF NOT EXISTS ix_customer_pos_number ON customer_pos (number)",

    # entity_comments — chat thread on quotations + POs
    """
    CREATE TABLE IF NOT EXISTS entity_comments (
        id UUID PRIMARY KEY,
        owner_type VARCHAR(40) NOT NULL,
        owner_id UUID NOT NULL,
        author_id UUID REFERENCES users(id) ON DELETE SET NULL,
        body TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_entity_comments_owner ON entity_comments (owner_type, owner_id)",

    # custom_roles — director-defined named roles with a page permission set
    """
    CREATE TABLE IF NOT EXISTS custom_roles (
        id UUID PRIMARY KEY,
        name VARCHAR(60) NOT NULL,
        base_role VARCHAR(20) NOT NULL DEFAULT 'sales',
        pages JSONB NOT NULL DEFAULT '[]'::jsonb,
        description VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_custom_roles_name ON custom_roles (name)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_role_id UUID",
    "CREATE INDEX IF NOT EXISTS ix_users_custom_role_id ON users (custom_role_id)",

    # Customer gained tax info (NPWP / NPPKP / PKP status)
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_id      VARCHAR(32)',
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_name    VARCHAR(255)',
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_address TEXT',
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_pkp BOOLEAN NOT NULL DEFAULT false",
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS nppkp_no    VARCHAR(64)',
    'ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_notes   TEXT',

    # ledger_entries — the company transaction journal (created lazily for
    # installs upgrading from before the model existed; create_all() handles
    # fresh installs).
    """
    CREATE TABLE IF NOT EXISTS ledger_entries (
        id UUID PRIMARY KEY,
        entry_date DATE NOT NULL,
        account_no VARCHAR(40) NOT NULL,
        account_type VARCHAR(40) NOT NULL,
        account_name VARCHAR(255),
        amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        cash_delta NUMERIC(18,2) NOT NULL DEFAULT 0,
        source_type VARCHAR(30) NOT NULL,
        source_id UUID,
        source_ref VARCHAR(120),
        memo TEXT,
        customer_id UUID,
        sales_pic_id UUID,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_entry_date ON ledger_entries (entry_date)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_account_no ON ledger_entries (account_no)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_account_type ON ledger_entries (account_type)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_source ON ledger_entries (source_type, source_id)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_sales_pic_id ON ledger_entries (sales_pic_id)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_customer_id ON ledger_entries (customer_id)",

    # price_requests — pre-quotation pricing workflow (sales lists goods →
    # purchasing costs → director sets selling price + approves).
    """
    CREATE TABLE IF NOT EXISTS price_requests (
        id UUID PRIMARY KEY,
        number VARCHAR(40) NOT NULL,
        customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
        sales_pic_id UUID,
        status VARCHAR(30) NOT NULL DEFAULT 'draft',
        items JSONB NOT NULL DEFAULT '[]'::jsonb,
        notes TEXT,
        priced_by UUID,
        priced_at TIMESTAMPTZ,
        approved_by UUID,
        approved_at TIMESTAMPTZ,
        decision_notes TEXT,
        quotation_id UUID,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ,
        created_by UUID,
        updated_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_price_requests_number ON price_requests (number)",
    "CREATE INDEX IF NOT EXISTS ix_price_requests_customer_id ON price_requests (customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_price_requests_sales_pic_id ON price_requests (sales_pic_id)",
    "CREATE INDEX IF NOT EXISTS ix_price_requests_status ON price_requests (status)",
    "CREATE INDEX IF NOT EXISTS ix_price_requests_quotation_id ON price_requests (quotation_id)",
    # Quotation can be generated from an approved price request.
    "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS price_request_id UUID",
    "CREATE INDEX IF NOT EXISTS ix_quotations_price_request_id ON quotations (price_request_id)",
    # Project records which price request it fulfils (so purchasing knows the order).
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS price_request_id UUID",
    "CREATE INDEX IF NOT EXISTS ix_projects_price_request_id ON projects (price_request_id)",

    # Project gained a shipping timeline + import flag
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_ship_from_origin DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS act_ship_from_origin DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_arrive_our_warehouse DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS act_arrive_our_warehouse DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_arrive_customer DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS act_arrive_customer DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin_location VARCHAR(120)',
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_import BOOLEAN NOT NULL DEFAULT false",

    # Post-drawing logistics (purchasing): delivery mode, ETA, import docs.
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(20) NOT NULL DEFAULT 'local'",
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS est_delivery_date DATE',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_confirmed_at TIMESTAMPTZ',
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS import_docs JSONB NOT NULL DEFAULT '{}'::jsonb",

    # Operations QC + customer handover.
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS qc_decision VARCHAR(20)',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS qc_passed_at TIMESTAMPTZ',
    'ALTER TABLE projects ADD COLUMN IF NOT EXISTS customer_received_at TIMESTAMPTZ',

    # Faktur Pajak + invoice approval (admin issues, finance approves).
    'ALTER TABLE invoices ADD COLUMN IF NOT EXISTS faktur_pajak_no VARCHAR(40)',
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS faktur_pajak_status VARCHAR(20) NOT NULL DEFAULT 'none'",
    'ALTER TABLE invoices ADD COLUMN IF NOT EXISTS issued_by UUID',
    'ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approved_by UUID',
    'ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ',

    # Supplier PO can be linked to the price request it sources against, so the
    # PO auto-fills the buying (cost) price purchasing already entered.
    'ALTER TABLE supplier_pos ADD COLUMN IF NOT EXISTS price_request_id UUID',
    "CREATE INDEX IF NOT EXISTS ix_supplier_pos_price_request_id ON supplier_pos (price_request_id)",

    # Drawings gained an internal director sign-off (who/when), distinct from
    # the legacy customer_decision_at.
    'ALTER TABLE drawings ADD COLUMN IF NOT EXISTS decided_by UUID',
    'ALTER TABLE drawings ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ',
    # Who posted the drawing — lets them re-upload after a revision request.
    'ALTER TABLE drawings ADD COLUMN IF NOT EXISTS uploaded_by UUID',

    # Backfill: link projects to the price request behind their quotation where
    # the direct link was never recorded (projects created before Phase C).
    """
    UPDATE projects p
       SET price_request_id = q.price_request_id
      FROM quotations q
     WHERE p.quotation_id = q.id
       AND p.price_request_id IS NULL
       AND q.price_request_id IS NOT NULL
    """,

    # Backfill: advance projects to 'purchasing' if a supplier PO already
    # exists for them but the status is still upstream (drawing_approved or
    # earlier). Matches the new rule that "supplier PO triggers purchasing".
    # Idempotent: only nudges projects that are at the listed pre-purchasing
    # statuses, never regresses anything past purchasing.
    """
    UPDATE projects p
       SET status = 'purchasing'
     WHERE p.status IN ('new', 'drawing', 'drawing_approved')
       AND EXISTS (
         SELECT 1 FROM supplier_pos sp WHERE sp.project_id = p.id
       )
    """,
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

    # Demo users — only in dev. In prod, we never auto-seed or auto-
    # deactivate anything: the director manages real accounts through
    # Admin → Users. Aggressively deactivating demo emails on every
    # startup was kicking real users out when the HF Space cold-started
    # (the seed runs again, flips is_active=false, next request 401s).
    # If a director wants to remove a legacy demo account they can do
    # it once from the UI.
    async with SessionLocal() as db:
        if is_prod:
            # Safety net: if a previous version of this script deactivated
            # every director (the bug we just removed), reactivate them so
            # the user isn't permanently locked out. Only triggers when
            # there is literally no active director on the system.
            active_directors = (await db.scalars(
                select(User).where(User.role == "director", User.is_active.is_(True))
            )).all()
            if not active_directors:
                stale_directors = (await db.scalars(
                    select(User).where(User.role == "director", User.is_active.is_(False))
                )).all()
                for u in stale_directors:
                    u.is_active = True
                if stale_directors:
                    await db.commit()
                    print(f"PROD: reactivated {len(stale_directors)} director "
                          f"account(s) that had no active counterpart.")
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
