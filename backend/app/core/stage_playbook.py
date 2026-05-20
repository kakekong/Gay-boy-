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


STAGE_PLAYBOOK: dict[str, list[StageTask]] = {
    "lead": [
        {"key": "first_contact",     "title": "Make first contact",            "due_after_days": 1, "hint": "Call or WhatsApp within 24 hours"},
        {"key": "qualify_need",      "title": "Qualify need + budget",         "due_after_days": 3, "hint": "Log discovery notes on the customer"},
    ],
    "presentation": [
        {"key": "schedule_demo",     "title": "Schedule presentation/demo",    "due_after_days": 3, "hint": "Confirm date with PIC"},
        {"key": "send_company_deck", "title": "Send company profile / deck",   "due_after_days": 2, "hint": "Attach the PDF to the customer"},
    ],
    "engineering": [
        {"key": "spec_review",       "title": "Engineering spec review",       "due_after_days": 5, "hint": "Confirm technical scope with engineering"},
        {"key": "site_survey",       "title": "Schedule site survey if needed","due_after_days": 7, "hint": "Skip if remote-only project"},
    ],
    "quotation": [
        {"key": "draft_quote",       "title": "Draft quotation",               "due_after_days": 2, "hint": "Use the New quotation form"},
        {"key": "send_quote",        "title": "Send quotation to customer",    "due_after_days": 4, "hint": "Send via WhatsApp/email and log the activity"},
    ],
    "negotiation": [
        {"key": "follow_up_quote",   "title": "Follow up on quotation",        "due_after_days": 3, "hint": "Check pricing/term objections"},
        {"key": "second_follow_up",  "title": "Second follow-up if no answer", "due_after_days": 7, "hint": "Escalate to manager if silent"},
    ],
    "po": [
        {"key": "collect_po",        "title": "Collect signed PO",             "due_after_days": 5, "hint": "Upload to the customer's attachments"},
        {"key": "confirm_terms",     "title": "Confirm payment terms",         "due_after_days": 3, "hint": "Tempo days / DP %"},
    ],
    "drawing": [
        {"key": "send_drawing",      "title": "Send drawing for approval",     "due_after_days": 5, "hint": "From Operations → Drawings"},
        {"key": "drawing_signoff",   "title": "Collect customer sign-off",     "due_after_days": 10, "hint": "Required before purchasing"},
    ],
    "purchasing": [
        {"key": "raise_pr",          "title": "Raise purchase request",        "due_after_days": 3, "hint": "Open Purchasing → New PR"},
        {"key": "select_supplier",   "title": "Select supplier & issue PO",    "due_after_days": 7, "hint": "From RFQ comparisons"},
    ],
    "delivery": [
        {"key": "schedule_delivery", "title": "Schedule delivery to customer", "due_after_days": 3, "hint": "Set arrival date in project shipping"},
        {"key": "delivery_proof",    "title": "Upload delivery proof",         "due_after_days": 7, "hint": "BAST / packing list"},
    ],
    "invoicing": [
        {"key": "issue_invoice",     "title": "Issue invoice",                 "due_after_days": 2, "hint": "From Finance → Invoices"},
        {"key": "send_invoice",      "title": "Send invoice to customer",      "due_after_days": 3, "hint": "Email/WhatsApp"},
    ],
    "payment": [
        {"key": "follow_payment",    "title": "Follow up on payment",          "due_after_days": 7, "hint": "Verify in Payment verification when received"},
    ],
    # closed_won / closed_lost get no required tasks
    "closed_won":  [],
    "closed_lost": [],
}


def playbook_for(stage: str) -> list[StageTask]:
    return STAGE_PLAYBOOK.get(stage, [])
