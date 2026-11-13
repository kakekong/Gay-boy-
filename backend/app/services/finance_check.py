"""Finance check — where the money records disagree with each other.

Asked for: the client says finance is "wrong", most likely because invoices
were left unpaid — money that came in but was never recorded, or recorded on
the wrong invoice. Nobody outside the company can look at the live books, so
this reads them where they are and says, in one place, what does not add up.
It writes nothing.

Each finding is one section: what it means, how serious, and the rows behind
it. The same result downloads as an Excel workbook, so it can be read by
someone who isn't logged in — an accountant, or support going through it.

The sections:

* **Unpaid invoices** — every approved invoice not yet fully paid: who issued
  it, when it was due, what is still owed, how late.
* **Status disagrees with payments** — "paid" with money missing, or unpaid
  with the money in.
* **Paid more than the invoice** — a receipt recorded twice, or on the
  wrong invoice.
* **Money on an invoice that isn't approved** — payments against a draft,
  pending or rejected invoice.
* **Payments missing from the books** — a receipt with no ledger lines, so
  cash and Piutang never moved.
* **Ledger lines with no payment** — the books moved for a receipt that no
  longer exists.
* **Recorded receipts not counted** — a receipt finance verified that never
  became a payment on the invoice.
* **Delivered but not fully invoiced** — the goods left, the invoices fall
  short of the deal. (Deals still in progress are listed apart: normal.)
* **Invoices waiting on finance** — sent to finance and not approved for
  over a week.
* **Piutang reconciliation** — the receivable account against what the
  documents say is owed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

TOL = 1.0          # rupiah: rounding, not money
STUCK_DAYS = 7


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


async def run(db: AsyncSession) -> dict:
    from app.models.account import Account
    from app.models.crm import Customer
    from app.models.finance import (
        OUTSTANDING_INVOICE_STATUSES, Invoice, LedgerEntry, Payment,
    )
    from app.models.operation import Project
    from app.models.payment_claim import PaymentClaim
    from app.models.quotation import Quotation
    from app.models.user import User
    from app.services.ledger import PAYMENT_RECEIVABLE

    today = date.today()
    invoices = (await db.scalars(select(Invoice))).all()
    payments = (await db.scalars(select(Payment))).all()
    customers = {c.id: c.company_name for c in (await db.scalars(select(Customer))).all()}
    users = {u.id: u.full_name for u in (await db.scalars(select(User))).all()}
    projects = {p.id: p for p in (await db.scalars(select(Project))).all()}

    paid_by_inv: dict = defaultdict(float)
    for p in payments:
        paid_by_inv[p.invoice_id] += _f(p.amount)

    def inv_row(i, **extra) -> dict:
        pj = projects.get(i.project_id) if i.project_id else None
        total, paid = _f(i.total), round(paid_by_inv.get(i.id, 0.0), 2)
        return {"invoice": i.number, "customer": customers.get(i.customer_id),
                "project": pj.code if pj else None, "status": i.status,
                "issued_by": users.get(i.issued_by), "issue_date": i.issue_date,
                "due_date": i.due_date, "total": total, "paid": paid,
                "outstanding": round(total - paid, 2), **extra}

    sections: list[dict] = []

    def section(key, title, severity, explain, rows, columns):
        sections.append({"key": key, "title": title, "severity": severity,
                         "explain": explain, "count": len(rows),
                         "columns": columns, "rows": rows})

    # ── 1. unpaid invoices ───────────────────────────────────────────────
    unpaid = []
    for i in invoices:
        if i.status not in OUTSTANDING_INVOICE_STATUSES:
            continue
        r = inv_row(i)
        if r["outstanding"] <= TOL:
            continue
        r["days_overdue"] = (today - i.due_date).days if i.due_date and i.due_date < today else 0
        unpaid.append(r)
    unpaid.sort(key=lambda r: (-r["days_overdue"], -r["outstanding"]))
    inv_cols = ["invoice", "customer", "project", "status", "issued_by", "issue_date",
                "due_date", "total", "paid", "outstanding"]
    section("unpaid", "Unpaid invoices", "info",
            "Approved invoices not yet fully paid. If the customer did pay one of these, "
            "the payment was never recorded — record it on Finance → Record payment.",
            unpaid, inv_cols + ["days_overdue"])

    # ── 2. status vs payments ────────────────────────────────────────────
    mismatch = []
    for i in invoices:
        total, paid = _f(i.total), round(paid_by_inv.get(i.id, 0.0), 2)
        if total <= 0:
            continue
        should = ("paid" if paid >= total - 0.01 else "partial" if paid > 0 else None)
        if i.status == "paid" and should != "paid":
            mismatch.append(inv_row(i, should_be=should or "approved (unpaid)"))
        elif i.status in OUTSTANDING_INVOICE_STATUSES and should == "paid":
            mismatch.append(inv_row(i, should_be="paid"))
        elif i.status == "partial" and should is None:
            mismatch.append(inv_row(i, should_be="approved (unpaid)"))
    section("status_mismatch", "Status disagrees with payments", "error",
            "The invoice's status says one thing and the payments on it say another — "
            "so lists, reminders and Piutang read it differently.",
            mismatch, inv_cols + ["should_be"])

    # ── 3. overpaid ──────────────────────────────────────────────────────
    over = [inv_row(i) for i in invoices
            if _f(i.total) > 0 and paid_by_inv.get(i.id, 0.0) > _f(i.total) + TOL]
    section("overpaid", "Paid more than the invoice", "error",
            "More money is recorded than the invoice is for — usually a receipt "
            "entered twice, or put on the wrong invoice.", over, inv_cols)

    # ── 4. money on an invoice that isn't approved ───────────────────────
    early = [inv_row(i) for i in invoices
             if i.status in ("draft", "pending_finance", "rejected")
             and abs(paid_by_inv.get(i.id, 0.0)) > TOL]
    section("paid_unapproved", "Money on an invoice that isn't approved", "warning",
            "Payments sit on a draft, pending or rejected invoice, so they count "
            "nowhere a receivable is read.", early, inv_cols)

    # ── 5. payments missing from the books ───────────────────────────────
    led_pay = (await db.execute(
        select(LedgerEntry.source_id, func.count(LedgerEntry.id))
        .where(LedgerEntry.source_type == "payment").group_by(LedgerEntry.source_id))).all()
    has_ledger = {sid for sid, n in led_pay if sid}
    inv_by_id = {i.id: i for i in invoices}
    no_ledger = []
    for p in payments:
        if _f(p.amount) <= 0 or p.id in has_ledger:
            continue
        i = inv_by_id.get(p.invoice_id)
        no_ledger.append({"invoice": i.number if i else None,
                          "customer": customers.get(i.customer_id) if i else None,
                          "paid_at": p.paid_at.date() if p.paid_at else None,
                          "amount": _f(p.amount), "method": p.method, "reference": p.reference,
                          "recorded": p.created_at.date() if p.created_at else None})
    section("payment_no_ledger", "Payments missing from the books", "error",
            "A receipt is on the invoice but wrote no ledger lines, so Bank/Kas and "
            "Piutang never moved for it — cash on the reports is short by this much.",
            no_ledger, ["invoice", "customer", "paid_at", "amount", "method", "reference", "recorded"])

    # ── 6. ledger lines with no payment ──────────────────────────────────
    pay_ids = {p.id for p in payments}
    orphans = (await db.scalars(select(LedgerEntry).where(
        LedgerEntry.source_type == "payment"))).all()
    orphan_rows = [{"date": e.entry_date, "account": f"{e.account_no} {e.account_name or ''}".strip(),
                    "amount": _f(e.amount), "for": e.source_ref, "memo": e.memo}
                   for e in orphans if e.source_id and e.source_id not in pay_ids]
    section("ledger_no_payment", "Ledger lines with no payment", "warning",
            "The books moved for a receipt that no longer exists — the payment was "
            "deleted but its ledger lines stayed.",
            orphan_rows, ["date", "account", "amount", "for", "memo"])

    # ── 7. verified receipts not counted ─────────────────────────────────
    claims = (await db.scalars(select(PaymentClaim))).all()
    verified: dict = defaultdict(float)
    pending_claims = []
    for c in claims:
        if c.status == "verified":
            verified[c.invoice_id] += _f(c.amount)
        elif c.status == "pending":
            i = inv_by_id.get(c.invoice_id)
            pending_claims.append(i)
    receipts = defaultdict(float)
    for p in payments:
        if _f(p.amount) > 0:
            receipts[p.invoice_id] += _f(p.amount)
    lost = []
    for iid, v in verified.items():
        if v > receipts.get(iid, 0.0) + TOL and iid in inv_by_id:
            lost.append(inv_row(inv_by_id[iid], verified_receipts=round(v, 2)))
    for i in pending_claims:
        if i is not None:
            lost.append(inv_row(i, verified_receipts="waiting for verification"))
    section("receipts_not_counted", "Recorded receipts not counted", "error",
            "Finance recorded money against these invoices (or a receipt still waits to "
            "be checked), but less of it reached the invoice as a payment.",
            lost, inv_cols + ["verified_receipts"])

    # ── 8. won deals not fully invoiced ──────────────────────────────────
    # A deal is booked as owed when its quotation is won — before the job
    # exists, sometimes — so it is counted per quotation. An invoice belongs
    # to a quotation through its job, or through the customer PO a deposit
    # invoice is raised on before there is a job.
    from app.models.customer_po import CustomerPO
    cpo_quote = {c.id: c.quotation_id for c in (await db.scalars(select(CustomerPO))).all()}
    job_of_quote = {p.quotation_id: p for p in projects.values() if p.quotation_id}
    invoiced_by_quote: dict = defaultdict(float)
    for i in invoices:
        if i.status in ("rejected", "draft"):
            continue
        qid = (projects[i.project_id].quotation_id if i.project_id in projects else None) \
            or cpo_quote.get(i.customer_po_id)
        if qid:
            invoiced_by_quote[qid] += _f(i.total)
    short = []
    for q in (await db.scalars(select(Quotation).where(Quotation.is_posted.is_(True)))).all():
        p = job_of_quote.get(q.id)
        if p is not None and ((p.status or "") == "cancelled" or getattr(p, "is_deleted", False)):
            continue
        gap = round(_f(q.total) - invoiced_by_quote.get(q.id, 0.0), 2)
        if gap > TOL:
            short.append({"quotation": q.number, "project": p.code if p else "(no job yet)",
                          "customer": customers.get(q.customer_id), "deal_total": _f(q.total),
                          "invoiced": round(invoiced_by_quote.get(q.id, 0.0), 2),
                          "not_invoiced": gap, "project_status": p.status if p else None})
    short.sort(key=lambda r: -r["not_invoiced"])
    # Goods that have left are the ones that should have been billed by now;
    # a job still in production not being invoiced yet is normal.
    shipped = {"delivered", "invoiced", "paid", "closed"}
    cols = ["quotation", "project", "customer", "deal_total", "invoiced",
            "not_invoiced", "project_status"]
    section("not_invoiced", "Delivered but not fully invoiced", "warning",
            "The goods have gone out (or the job is closed) but its invoices fall short "
            "of the deal — money that can't be collected because it was never invoiced.",
            [r for r in short if r["project_status"] in shipped], cols)
    section("not_invoiced_yet", "Won, not invoiced yet (in progress)", "info",
            "Deals still being made or not yet a job. Booked as owed (Piutang) when won, "
            "so they explain part of the Piutang balance; normal until delivery.",
            [r for r in short if r["project_status"] not in shipped], cols)

    # ── 9. stuck with finance ────────────────────────────────────────────
    stuck = []
    for i in invoices:
        if i.status == "pending_finance" and i.created_at:
            days = (datetime.now(UTC) - i.created_at).days
            if days >= STUCK_DAYS:
                stuck.append(inv_row(i, waiting_days=days))
    section("stuck", f"Invoices waiting on finance over {STUCK_DAYS} days", "warning",
            "Sent to finance and never approved, so the customer hasn't been asked to pay.",
            stuck, inv_cols + ["waiting_days"])

    # ── 10. Piutang reconciliation ───────────────────────────────────────
    acc = await db.scalar(select(Account).where(Account.account_no == PAYMENT_RECEIVABLE))
    ar_balance = _f(acc.balance) if acc else 0.0
    ar_ledger = _f(await db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0))
                                   .where(LedgerEntry.account_no == PAYMENT_RECEIVABLE)))
    outstanding_total = round(sum(r["outstanding"] for r in unpaid), 2)
    not_invoiced_total = round(sum(r["not_invoiced"] for r in short), 2)
    recon = [
        {"figure": f"Piutang account {PAYMENT_RECEIVABLE} balance", "amount": ar_balance},
        {"figure": "Piutang per its ledger lines", "amount": ar_ledger},
        {"figure": "Owed on unpaid invoices", "amount": outstanding_total},
        {"figure": "Won but not yet invoiced", "amount": not_invoiced_total},
        {"figure": "Documents say owed (invoices + not invoiced)",
         "amount": round(outstanding_total + not_invoiced_total, 2)},
        {"figure": "Difference: account − documents",
         "amount": round(ar_balance - outstanding_total - not_invoiced_total, 2)},
        {"figure": "Difference: account − its ledger lines", "amount": round(ar_balance - ar_ledger, 2)},
    ]
    off = abs(recon[-2]["amount"]) > TOL or abs(recon[-1]["amount"]) > TOL
    section("piutang", "Piutang reconciliation", "error" if off else "ok",
            "The receivable account against what the documents say is owed. A difference "
            "means money moved on one side without the other — the sections above say where.",
            recon, ["figure", "amount"])

    problems = sum(s["count"] for s in sections
                   if s["severity"] in ("error", "warning") and s["key"] != "piutang") + (1 if off else 0)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "invoices": len(invoices), "payments": len(payments),
            "unpaid_invoices": len(unpaid), "unpaid_total": outstanding_total,
            "problems": problems,
        },
        "sections": sections,
    }


def to_xlsx(result: dict) -> bytes:
    """The check as a workbook: a summary sheet, then one sheet per finding."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Finance check", result["generated_at"][:19].replace("T", " ") + " UTC"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    for k, v in result["summary"].items():
        ws.append([k.replace("_", " "), v])
    ws.append([])
    ws.append(["Section", "Severity", "Rows", "What it means"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for s in result["sections"]:
        ws.append([s["title"], s["severity"], s["count"], s["explain"]])
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["D"].width = 90
    for s in result["sections"]:
        sh = wb.create_sheet(s["title"][:31].replace("/", "-"))
        sh.append([s["explain"]])
        sh.append(s["columns"])
        for c in sh[2]:
            c.font = Font(bold=True)
        for r in s["rows"]:
            sh.append([r.get(col) if not isinstance(r.get(col), (dict, list)) else str(r.get(col))
                       for col in s["columns"]])
        for idx, _ in enumerate(s["columns"], start=1):
            sh.column_dimensions[sh.cell(row=2, column=idx).column_letter].width = 18
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
