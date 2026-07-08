"""Per-stage CRM playbook.

Each CRM stage has a required list of "stage tasks" the assigned sales PIC
must complete. When a customer enters a stage, these are auto-spawned as
Reminders (kind=`stage:<stage>:<key>`). The Customer detail page renders
them as a checklist; the notifications bell surfaces overdue ones.

Keep `key` snake_case and stable — it's used inside the Reminder.kind string.
"""

from typing import TypedDict


class StageTask(TypedDict):
    key: str
    title: str
    due_after_days: int
    hint: str  # short helper text shown under the title
    roles: list[str]  # roles that actually DO this task — routes notifications


# `roles` routes each task's notification to the department that executes
# it: "Issue invoice" pings finance, "Raise purchase request" pings
# purchasing, "Schedule delivery" pings admin (ops). Manager/director see
# everything regardless. The reminder rows themselves stay owned by the
# deal's sales PIC — this only controls who gets nagged about them.
STAGE_PLAYBOOK: dict[str, list[StageTask]] = {
    "lead": [
        {"key": "first_contact",     "title": "Make first contact",            "due_after_days": 1, "hint": "Call or WhatsApp within 24 hours",             "roles": ["sales"]},
        {"key": "qualify_need",      "title": "Qualify need + budget",         "due_after_days": 3, "hint": "Log discovery notes on the customer",          "roles": ["sales"]},
    ],
    "presentation": [
        {"key": "schedule_demo",     "title": "Schedule presentation/demo",    "due_after_days": 3, "hint": "Confirm date with PIC",                        "roles": ["sales"]},
        {"key": "send_company_deck", "title": "Send company profile / deck",   "due_after_days": 2, "hint": "Attach the PDF to the customer",               "roles": ["sales"]},
    ],
    "engineering": [
        {"key": "spec_review",       "title": "Engineering spec review",       "due_after_days": 5, "hint": "Confirm technical scope with engineering",     "roles": ["sales"]},
        {"key": "site_survey",       "title": "Schedule site survey if needed","due_after_days": 7, "hint": "Skip if remote-only project",                  "roles": ["sales"]},
    ],
    "quotation": [
        {"key": "draft_quote",       "title": "Draft quotation",               "due_after_days": 2, "hint": "Use the New quotation form",                   "roles": ["sales"]},
        {"key": "send_quote",        "title": "Send quotation to customer",    "due_after_days": 4, "hint": "Send via WhatsApp/email and log the activity", "roles": ["sales"]},
    ],
    "negotiation": [
        {"key": "follow_up_quote",   "title": "Follow up on quotation",        "due_after_days": 3, "hint": "Check pricing/term objections",                "roles": ["sales"]},
        {"key": "second_follow_up",  "title": "Second follow-up if no answer", "due_after_days": 7, "hint": "Escalate to manager if silent",                "roles": ["sales"]},
    ],
    "po": [
        {"key": "collect_po",        "title": "Collect signed PO",             "due_after_days": 5, "hint": "Upload to the customer's attachments",         "roles": ["sales"]},
        {"key": "confirm_terms",     "title": "Confirm payment terms",         "due_after_days": 3, "hint": "Tempo days / DP %",                            "roles": ["sales"]},
    ],
    "drawing": [
        {"key": "send_drawing",      "title": "Send drawing for approval",     "due_after_days": 5, "hint": "From Operations → Drawings",                   "roles": ["admin"]},
        {"key": "drawing_signoff",   "title": "Collect customer sign-off",     "due_after_days": 10, "hint": "Required before purchasing",                  "roles": ["sales"]},
    ],
    "purchasing": [
        {"key": "raise_pr",          "title": "Raise purchase request",        "due_after_days": 3, "hint": "Open Purchasing → New PR",                     "roles": ["purchasing"]},
        {"key": "select_supplier",   "title": "Select supplier & issue PO",    "due_after_days": 7, "hint": "From RFQ comparisons",                         "roles": ["purchasing"]},
    ],
    "delivery": [
        {"key": "schedule_delivery", "title": "Schedule delivery to customer", "due_after_days": 3, "hint": "Set arrival date in project shipping",         "roles": ["admin"]},
        {"key": "delivery_proof",    "title": "Upload delivery proof",         "due_after_days": 7, "hint": "BAST / packing list",                          "roles": ["admin"]},
    ],
    "invoicing": [
        {"key": "issue_invoice",     "title": "Issue invoice",                 "due_after_days": 2, "hint": "From Finance → Invoices",                      "roles": ["finance"]},
        {"key": "send_invoice",      "title": "Send invoice to customer",      "due_after_days": 3, "hint": "Email/WhatsApp",                               "roles": ["finance"]},
    ],
    "payment": [
        {"key": "follow_payment",    "title": "Follow up on payment",          "due_after_days": 7, "hint": "Verify in Payment verification when received", "roles": ["sales", "finance"]},
    ],
    # closed_won / closed_lost get no required tasks
    "closed_won":  [],
    "closed_lost": [],
}


def playbook_for(stage: str) -> list[StageTask]:
    return STAGE_PLAYBOOK.get(stage, [])


# ─── Canonical pipeline order ────────────────────────────────────────────────
# The deal pipeline must be walked in order — you can't skip a stage. A
# forward move is only allowed to the immediately-next stage. Backward
# moves (regressions) are allowed (you can always pull a deal back).
STAGE_ORDER: list[str] = [
    "lead", "presentation", "engineering", "quotation", "negotiation",
    "po", "drawing", "purchasing", "delivery", "invoicing", "payment",
    "closed_won", "closed_lost",
]


def stage_index(stage: str) -> int:
    """Position in the pipeline, or -1 if unknown."""
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def is_forward_skip(from_stage: str, to_stage: str) -> bool:
    """True when moving forward by more than one stage (skipping). Backward
    moves and single-step forward moves return False. closed_lost is a
    valid jump from anywhere (a deal can die at any point)."""
    if to_stage == "closed_lost":
        return False
    fi, ti = stage_index(from_stage), stage_index(to_stage)
    if fi < 0 or ti < 0:
        return False
    return ti > fi + 1


# ─── Project → customer stage mirror ─────────────────────────────────────────
# The customer's deal pipeline mirrors what's happening on the project, so we
# don't have two sources of truth. Map project statuses to the customer stage
# they should imply — always advance forward, never regress.
PROJECT_TO_CUSTOMER_STAGE: dict[str, str] = {
    "drawing": "drawing",
    "drawing_approved": "drawing",
    "purchasing": "purchasing",
    "production": "purchasing",
    "qc": "purchasing",
    "packaging": "purchasing",
    "invoiced": "invoicing",
    "delivered": "invoicing",
    "paid": "payment",
    "closed": "closed_won",
}


def customer_stage_for_project(project_status: str) -> str | None:
    """Return the customer deal-pipeline stage implied by a project status,
    or None if the project status doesn't map (e.g. 'new')."""
    return PROJECT_TO_CUSTOMER_STAGE.get(project_status)


def bump_customer_stage(customer, to_stage: str) -> bool:
    """Forward-only bump of the customer's deal stage.

    Used to fuse deal-document approvals with the CRM pipeline: when the
    director approves a quotation / Mark-Won / customer PO, the customer's
    stage advances to match — sales no longer files a separate stage-move
    request for ground the deal has already covered. Never regresses; a
    customer already at or past `to_stage` is untouched. Returns True if
    the stage changed (caller should then ensure_stage_tasks)."""
    ti = stage_index(to_stage)
    if ti < 0 or stage_index(customer.stage) >= ti:
        return False
    customer.stage = to_stage
    return True


def sync_customer_stage_from_projects(customer, project_statuses: list[str]) -> bool:
    """Bump `customer.stage` forward to the furthest stage implied by any of
    the given project statuses. Never regresses. Returns True if changed."""
    if not project_statuses:
        return False
    best = customer.stage
    best_i = stage_index(best)
    for s in project_statuses:
        mapped = PROJECT_TO_CUSTOMER_STAGE.get(s)
        if not mapped:
            continue
        i = stage_index(mapped)
        if i > best_i:
            best_i = i
            best = mapped
    if best != customer.stage:
        customer.stage = best
        return True
    return False
