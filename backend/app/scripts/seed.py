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
    # Both of these are roles the product has had for a long time; the demo
    # seed simply never grew them, so every test run had to create them by
    # hand afterwards and a demo instance had no way to look at finance or
    # purchasing at all.
    ("finance@demo.local",    "Finance Demo",    "finance"),
    ("purchasing@demo.local", "Purchasing Demo", "purchasing"),
]


# ─── Lightweight forward-only migrations ─────────────────────────────────────
# Every statement here is idempotent (`ADD COLUMN IF NOT EXISTS`). Add new
# entries below as the model evolves. Postgres-only.
COLUMN_MIGRATIONS: list[str] = [
    # Cash & bank: the statement is read per account and per date, and
    # reconciliation asks "what has not cleared yet".
    "CREATE INDEX IF NOT EXISTS ix_cash_tx_account_date "
    "ON cash_transactions (bank_account_no, tx_date)",
    "CREATE INDEX IF NOT EXISTS ix_cash_tx_uncleared "
    "ON cash_transactions (bank_account_no) WHERE cleared_on IS NULL",

    # ── Indexes for lookups the app makes on every page ──────────────────
    # Attachments are read by (owner_type, owner_id) everywhere — every
    # detail screen, the approval preview, the invoice queue — and the two
    # columns were indexed separately, so Postgres had to pick one and
    # filter the rest by hand. One composite index answers the actual query.
    "CREATE INDEX IF NOT EXISTS ix_attachments_owner "
    "ON attachments (owner_type, owner_id)",
    # Stock movements are looked up by the document that caused them, on
    # every PO release and every delivery order, twice each. `reference`
    # had no index at all, so both were a full scan of the table that grows
    # fastest in the whole system.
    "CREATE INDEX IF NOT EXISTS ix_inventory_movements_ref "
    "ON inventory_movements (reference, reason)",
    # Finance types a faktur pajak number and the server checks nobody else
    # has it — a scan of every invoice ever issued, on every keystroke-sized
    # save.
    "CREATE INDEX IF NOT EXISTS ix_invoices_faktur_pajak_no "
    "ON invoices (faktur_pajak_no) WHERE faktur_pajak_no IS NOT NULL",
    # The inventory list sorts by name and filters on is_active; the
    # catalogue now grows a SKU per purchase-order line, so it will not stay
    # small.
    "CREATE INDEX IF NOT EXISTS ix_inventory_items_active_name "
    "ON inventory_items (is_active, name)",
    # Comments and mentions are read per document, same shape as attachments.
    "CREATE INDEX IF NOT EXISTS ix_entity_comments_owner "
    "ON entity_comments (owner_type, owner_id)",
    # Approval requests are looked up by what they point at — the delivery
    # order desk does this for every row of the deliveries table.
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_target "
    "ON approval_requests (target_type, target_id)",
    # The journal walks one account over a date range.
    "CREATE INDEX IF NOT EXISTS ix_journal_lines_account "
    "ON journal_lines (account_no, journal_id)",

    # A catalogue row can carry the supplier / datasheet link sales pasted
    # into the price request that created it.
    "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS link VARCHAR(1000)",

    # A supplier's quote carries the currency it was given in and the rate
    # that turns it into rupiah — without the rate a CNY quote was applied
    # as its face value and the cost was wrong by a factor of two thousand.
    "ALTER TABLE supplier_price_requests ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18,6)",

    # Users gained an optional per-user sidebar page override
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pages JSONB",
    # …and an employment record: the day they started, and where payroll
    # sends their salary.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS join_date DATE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS bank_name VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS bank_account_no VARCHAR(60)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS bank_account_name VARCHAR(255)",
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
    # One-shot: relax due_at AND clear the auto-generated deadlines on
    # existing stage tasks (they flooded the bell/calendar). Guarded on the
    # column still being NOT NULL so re-boots never wipe user-set dates.
    """DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_attribute a
                 JOIN pg_class c ON c.oid = a.attrelid
                 WHERE c.relname = 'reminders'
                   AND a.attname = 'due_at' AND a.attnotnull) THEN
        ALTER TABLE reminders ALTER COLUMN due_at DROP NOT NULL;
        UPDATE reminders SET due_at = NULL
          WHERE kind LIKE 'stage:%' AND status = 'pending';
      END IF;
    END $$""",

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

    # Down-payment path — a DP PO routes through finance + sales confirm
    # before the project spawns. Booleans + timestamps added lazily so
    # older installs migrate on next boot.
    "ALTER TABLE customer_pos ADD COLUMN IF NOT EXISTS is_downpayment BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE customer_pos ADD COLUMN IF NOT EXISTS dp_finance_approved_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE customer_pos ADD COLUMN IF NOT EXISTS dp_finance_approved_at TIMESTAMPTZ",
    # Confirming a deposit arrived moved from sales to finance: it is a
    # fact about the bank account, and finance is who can see it. The
    # columns and the status are renamed rather than duplicated, so a row
    # cannot end up with the old name holding a finance user's id. Both
    # halves are guarded on information_schema, so re-running is a no-op.
    """DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'customer_pos'
                   AND column_name = 'dp_sales_confirmed_by')
         AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'customer_pos'
                   AND column_name = 'dp_payment_confirmed_by')
      THEN
        ALTER TABLE customer_pos
          RENAME COLUMN dp_sales_confirmed_by TO dp_payment_confirmed_by;
      END IF;
      IF EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'customer_pos'
                   AND column_name = 'dp_sales_confirmed_at')
         AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'customer_pos'
                   AND column_name = 'dp_payment_confirmed_at')
      THEN
        ALTER TABLE customer_pos
          RENAME COLUMN dp_sales_confirmed_at TO dp_payment_confirmed_at;
      END IF;
    END $$;""",
    "ALTER TABLE customer_pos ADD COLUMN IF NOT EXISTS dp_payment_confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE customer_pos ADD COLUMN IF NOT EXISTS dp_payment_confirmed_at TIMESTAMPTZ",
    # POs already mid-flight keep their place in the queue under the new name.
    "UPDATE customer_pos SET status = 'pending_payment_confirm' "
    "WHERE status = 'pending_sales_confirm'",

    # DP invoices are issued against the customer PO before the project
    # exists; project_id is backfilled at payment-confirm via this link.
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_po_id UUID REFERENCES customer_pos(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_invoices_customer_po_id ON invoices (customer_po_id)",

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
    # Director-side proof verification on a delivery order.
    'ALTER TABLE delivery_orders ADD COLUMN IF NOT EXISTS verified_by UUID',
    'ALTER TABLE delivery_orders ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ',
    # The director's release of the DO itself (not of the proof that comes
    # back after delivery) — nothing prints until it is set — plus the
    # ship-to note that goes in the printed Remarks column.
    'ALTER TABLE delivery_orders ADD COLUMN IF NOT EXISTS approved_by UUID',
    'ALTER TABLE delivery_orders ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ',
    'ALTER TABLE delivery_orders ADD COLUMN IF NOT EXISTS remarks TEXT',

    # One-off: for projects whose every delivery order is already delivered but
    # the project's own status is still upstream (someone marked DOs delivered
    # before the mark-delivered → project-advance wire was in place), bump the
    # project to 'delivered'. Idempotent: never regresses (paid/closed unchanged).
    """
    UPDATE projects p
       SET status = 'delivered'
     WHERE p.status IN ('new', 'drawing', 'drawing_approved', 'purchasing',
                         'production', 'qc', 'packaging', 'invoiced')
       AND EXISTS (SELECT 1 FROM delivery_orders do1 WHERE do1.project_id = p.id)
       AND NOT EXISTS (
         SELECT 1 FROM delivery_orders do2
          WHERE do2.project_id = p.id AND do2.status <> 'delivered'
       )
    """,

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
    # exists for them but the status is still 'new'. Under the REORDERED
    # pipeline (new -> purchasing -> drawing -> drawing_approved -> ...)
    # 'drawing'/'drawing_approved' sit AFTER purchasing, so the old version
    # of this statement — which listed them in the WHERE — regressed those
    # projects back to 'purchasing' on every boot. Only 'new' is upstream
    # of purchasing now.
    """
    UPDATE projects p
       SET status = 'purchasing'
     WHERE p.status = 'new'
       AND EXISTS (
         SELECT 1 FROM supplier_pos sp WHERE sp.project_id = p.id
       )
    """,

    # Repair the projects the old backfill knocked backwards: a project
    # sitting at 'purchasing' (or 'drawing') whose drawing was already
    # APPROVED belongs at 'drawing_approved'; one with any drawing filed
    # at all belongs at least at 'drawing'. Forward-only and idempotent —
    # projects already past these stages are untouched.
    """
    UPDATE projects p
       SET status = 'drawing_approved'
     WHERE p.status IN ('purchasing', 'drawing')
       AND EXISTS (
         SELECT 1 FROM drawings d
          WHERE d.project_id = p.id AND d.status = 'approved'
       )
    """,
    """
    UPDATE projects p
       SET status = 'drawing'
     WHERE p.status = 'purchasing'
       AND EXISTS (SELECT 1 FROM drawings d WHERE d.project_id = p.id)
    """,
    # Attachments can be an external link instead of an uploaded file
    # (durable across Space rebuilds, which wipe local file storage).
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS external_url VARCHAR(1000)",
    # One-shot cleanup: stage tasks left pending on a stage the deal has
    # already left could never be ticked (the checklist only renders the
    # CURRENT stage), so they nagged forever in the bell/calendar/AI queue.
    # Retire every pending stage task for a customer that has since closed.
    """
    UPDATE reminders r
       SET status = 'done'
      FROM customers c
     WHERE r.customer_id = c.id
       AND r.kind LIKE 'stage:%'
       AND r.status = 'pending'
       AND c.stage IN ('closed_won', 'closed_lost')
    """,

    # Quoted replies + forwarding, on both conversation surfaces (the chat
    # page and the discussion thread on a document).
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS reply_to_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_reply_to_id ON chat_messages (reply_to_id)",
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS forwarded_from_kind VARCHAR(20)",
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS forwarded_from_id UUID",
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS forwarded_from_author_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE entity_comments ADD COLUMN IF NOT EXISTS reply_to_id UUID REFERENCES entity_comments(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_entity_comments_reply_to_id ON entity_comments (reply_to_id)",
    "ALTER TABLE entity_comments ADD COLUMN IF NOT EXISTS forwarded_from_kind VARCHAR(20)",
    "ALTER TABLE entity_comments ADD COLUMN IF NOT EXISTS forwarded_from_id UUID",
    "ALTER TABLE entity_comments ADD COLUMN IF NOT EXISTS forwarded_from_author_id UUID REFERENCES users(id) ON DELETE SET NULL",

    # A maintenance action is about the database as a whole, so an audit row
    # can legitimately have no single entity to point at.
    "ALTER TABLE audit_log ALTER COLUMN entity_id DROP NOT NULL",

    # Price-request negotiation history (who proposed what, and the decision).
    "ALTER TABLE price_requests ADD COLUMN IF NOT EXISTS revisions JSONB NOT NULL DEFAULT '[]'::jsonb",
    # Director repricing after approval — what changed, and why
    "ALTER TABLE price_requests ADD COLUMN IF NOT EXISTS price_history JSONB NOT NULL DEFAULT '[]'::jsonb",
    # Why a quotation was rejected, on the quotation itself
    "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS decision_notes TEXT",
    # A correspondence address separate from the login email
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255)",
    # Scanned signature, drawn onto the documents this person signs
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_path VARCHAR(500)",

    # Suppliers gained an address and company-level contact details — the
    # switchboard and the sales@ mailbox, as opposed to a named person's own
    # number, which now lives on supplier_contacts (created by create_all).
    "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS company_address TEXT",
    "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS warehouse_address TEXT",
    "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS phone VARCHAR(40)",
    "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS whatsapp VARCHAR(40)",
    "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS email VARCHAR(255)",

    # A supplier price request can draw its lines from several customer price
    # requests at once (one vendor, several jobs, one shipment), so the single
    # price_request_id is no longer the whole story.
    "ALTER TABLE supplier_price_requests ADD COLUMN IF NOT EXISTS "
    "source_pr_ids JSONB NOT NULL DEFAULT '[]'::jsonb",

    # A supplier PO is one shipment with its own ETA, and one order to one
    # vendor can cover several projects (one truck, several jobs).
    "ALTER TABLE supplier_pos ADD COLUMN IF NOT EXISTS eta DATE",
    "ALTER TABLE supplier_pos ADD COLUMN IF NOT EXISTS "
    "project_ids JSONB NOT NULL DEFAULT '[]'::jsonb",

    # Which currency the order is written in. Existing rows are rupiah —
    # every PO raised before this column existed was an Indonesian one.
    "ALTER TABLE supplier_pos ADD COLUMN IF NOT EXISTS "
    "currency VARCHAR(8) NOT NULL DEFAULT 'IDR'",

    # What that currency is worth in rupiah on this order. Left NULL rather
    # than defaulted, so "nobody has set a rate" stays distinguishable from a
    # rate that happens to be 1 — except on rupiah orders, where 1 is simply
    # the truth and backfilling it saves every reader a special case.
    "ALTER TABLE supplier_pos ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18,6)",
    "UPDATE supplier_pos SET fx_rate = 1 "
    "WHERE fx_rate IS NULL AND (currency IS NULL OR currency = 'IDR')",

    # A drawing is either the customer's or the supplier's, and that decides
    # who may open it. Existing rows are classified by who uploaded them —
    # purchasing only ever filed the supplier's — because defaulting them all
    # to 'customer' would hand sales a pile of vendor drawings on the next
    # deploy, and defaulting to 'supplier' would hide the customer's own.
    #
    # Added nullable on purpose, so the backfill can key off NULL and run
    # exactly once; the default and the NOT NULL go on afterwards. A sweep
    # keyed off 'customer' instead would re-run every boot and would reclassify
    # any customer drawing a purchasing user ever legitimately owned.
    "ALTER TABLE drawings ADD COLUMN IF NOT EXISTS kind VARCHAR(20)",
    "ALTER TABLE drawings ADD COLUMN IF NOT EXISTS source_drawing_id UUID",
    """UPDATE drawings SET kind = CASE
           WHEN uploaded_by IN (SELECT id FROM users WHERE role = 'purchasing')
           THEN 'supplier' ELSE 'customer' END
       WHERE kind IS NULL""",
    "ALTER TABLE drawings ALTER COLUMN kind SET DEFAULT 'customer'",
    "ALTER TABLE drawings ALTER COLUMN kind SET NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_drawings_kind ON drawings (kind)",

    # ── The part number reaches the customer's document ──────────────────
    # KODE BARANG on an exported quotation used to fall back to the line's
    # position whenever the line had no catalogue product behind it — which
    # is every line of every quotation built from a price request. So the
    # SKU the request issued never left the building, and the first line of
    # each document read "001".
    "ALTER TABLE quotation_items ADD COLUMN IF NOT EXISTS sku VARCHAR(60)",
    # Quotations already sent were built before the line carried one. Their
    # price request still knows it, matched by line number, so the number
    # can be put back rather than left as a position forever. Only fills
    # blanks, so it runs once and is a no-op after that.
    """UPDATE quotation_items qi
          SET sku = src.sku
         FROM (
              SELECT q.id AS quotation_id,
                     (it->>'line_no')::int AS line_no,
                     NULLIF(it->>'sku', '') AS sku
                FROM quotations q
                JOIN price_requests pr ON pr.id = q.price_request_id
                CROSS JOIN LATERAL jsonb_array_elements(pr.items) AS it
               WHERE q.price_request_id IS NOT NULL
         ) src
        WHERE qi.quotation_id = src.quotation_id
          AND qi.line_no = src.line_no
          AND qi.sku IS NULL
          AND src.sku IS NOT NULL""",

    # ── The employee register comes before the login ─────────────────────
    # A login now belongs to somebody on the register. Unique so one person
    # cannot end up with two accounts; nullable because portal logins
    # (customer / supplier) are not employees and never get a record.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id UUID",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_employee_id "
    "ON users (employee_id)",
    # Everybody who already had a login predates the register, so give each
    # of them a record and link it. Without this the register would open
    # empty on the first deploy — every employee in the company missing —
    # and every existing account would violate the rule the next screen
    # enforces.
    #
    # Keyed off `employee_id IS NULL`, so it runs once per unlinked account
    # and is a no-op afterwards. The staff numbers are numbered from the
    # highest already issued in the same series, so a second run (an account
    # created directly in the database, say) cannot collide with the first.
    """DO $mig$
    DECLARE r RECORD; new_id UUID; n INT;
    BEGIN
        IF to_regclass('public.employees') IS NULL THEN RETURN; END IF;
        SELECT COALESCE(MAX(NULLIF(regexp_replace(employee_no,
                   '^EMP-LEGACY-', ''), '')::int), 0)
          INTO n FROM employees WHERE employee_no LIKE 'EMP-LEGACY-%';
        FOR r IN
            SELECT id, full_name, role, join_date, phone, is_active
              FROM users
             WHERE employee_id IS NULL
               AND role NOT IN ('customer', 'supplier')
             ORDER BY created_at
        LOOP
            n := n + 1;
            INSERT INTO employees (id, employee_no, full_name, intended_role,
                                   join_date, phone, is_active)
            VALUES (gen_random_uuid(), 'EMP-LEGACY-' || lpad(n::text, 3, '0'),
                    r.full_name, r.role, r.join_date, r.phone, r.is_active)
            RETURNING id INTO new_id;
            UPDATE users SET employee_id = new_id WHERE id = r.id;
        END LOOP;
    END $mig$""",
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
                from app.models.employee import Employee
                for i, (email, name, role) in enumerate(_USERS, start=1):
                    existing = await db.scalar(select(User).where(User.email == email))
                    if existing:
                        continue
                    # Every internal login belongs to somebody on the
                    # register, demo accounts included — otherwise the very
                    # first thing a demo shows is a Users list full of people
                    # who are not employees.
                    emp = Employee(
                        employee_no=f"EMP-DEMO-{i:03d}", full_name=name,
                        intended_role=role, is_active=True,
                    )
                    db.add(emp)
                    await db.flush()
                    db.add(User(email=email, full_name=name, role=role,
                                employee_id=emp.id,
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
