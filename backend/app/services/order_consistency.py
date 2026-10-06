"""Do the documents of one deal still agree — and if not, where, and the fix.

One deal is written down several times: the **price request** (what was asked
for, costed and priced), the **quotation** (what the customer was offered, the
document the deal is negotiated on), the **customer PO** (what the customer
actually ordered, typed from their paper), and on the buy side the **supplier
price requests** and **supplier POs** built from the request's lines.

Some of those copies follow each other on their own (see `quotation_sync` and
`price_request_sync`), and some deliberately don't: a customer's PO says what
the customer's paper says, and a supplier request is a list the vendor has
already priced. A sync that rewrote those would make a document say something
its author never said. So this module does the other half — it **compares**
every pair, says exactly which line and which field disagree, and offers the
fix in either direction, under the same rules as editing that document by
hand. Nothing here bypasses an approval: a change to an approved quotation by
anyone but the director is filed for the director, exactly as the edit form
would file it.

The checks, and the direction each fix can go:

* ``pr_quotation``      — request ↔ quotation lines (description, qty, unit,
  selling price). Either side can be made to match the other.
* ``quotation_cpo:<id>``— quotation ↔ one customer PO (description, qty, unit,
  unit price; matched by the quotation line number the PO line carries, or by
  description for older POs). Either side can be made to match.
* ``supplier_request:<id>`` — request → a supplier price request built from
  it (description, qty, unit). One direction only: refresh the supplier
  request (the vendor's prices per unit are kept).
* ``supplier_po_qty``   — how much is on live supplier POs against what each
  request line needs. Reported only: a placed order is changed with the
  supplier, on the PO page.
"""
from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Role
from app.models.customer_po import CustomerPO
from app.models.price_request import PriceRequest
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User

# Customer POs that no longer stand for an order.
_DEAD_CPO = ("rejected", "cancelled", "void")
# Quotation states a line edit can reach at all (see `update_quotation`).
_Q_DIRECT = ("draft", "rejected")
_Q_VIA_DIRECTOR = ("approved", "sent", "won")
_DEAD_SPO = ("cancelled", "rejected")


def _num(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _txt(v) -> str:
    return (v or "").strip()


def _key(desc: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (desc or "").lower())


def _sees_sell(role: Role) -> bool:
    return role != Role.PURCHASING


def _sees_buy(role: Role) -> bool:
    return role in (Role.PURCHASING, Role.MANAGER, Role.DIRECTOR)


def _doc(kind: str, obj, extra: dict | None = None) -> dict:
    return {"kind": kind, "id": str(obj.id), "number": obj.number,
            "status": getattr(obj, "status", None), **(extra or {})}


# ── Finding the deal ─────────────────────────────────────────────────────────

async def resolve_chain(db: AsyncSession, *, price_request_id=None, quotation_id=None,
                        customer_po_id=None, project_id=None) -> dict:
    """Every document of the deal, from whichever one the caller is on."""
    from app.models.operation import Project
    pr = q = None
    cpo = None
    if customer_po_id:
        cpo = await db.get(CustomerPO, customer_po_id)
        if cpo and cpo.quotation_id:
            q = await db.get(Quotation, cpo.quotation_id)
    if quotation_id:
        q = await db.get(Quotation, quotation_id)
    if project_id:
        p = await db.get(Project, project_id)
        if p and p.price_request_id:
            price_request_id = p.price_request_id
        elif p:
            cpo_p = await db.scalar(select(CustomerPO).where(CustomerPO.project_id == p.id)
                                    .order_by(CustomerPO.created_at.desc()).limit(1))
            if cpo_p and cpo_p.quotation_id:
                q = await db.get(Quotation, cpo_p.quotation_id)
    if price_request_id:
        pr = await db.get(PriceRequest, price_request_id)
    if q is not None and pr is None and q.price_request_id:
        pr = await db.get(PriceRequest, q.price_request_id)
    if pr is not None and q is None:
        from app.services.price_request_sync import quotation_for_request
        q = await quotation_for_request(db, pr)
    if pr is not None and getattr(pr, "is_deleted", False):
        pr = None

    cpos: list[CustomerPO] = []
    if q is not None:
        cpos = list((await db.scalars(
            select(CustomerPO).where(CustomerPO.quotation_id == q.id)
            .order_by(CustomerPO.created_at))).all())
    if cpo is not None and all(x.id != cpo.id for x in cpos):
        cpos.append(cpo)
    cpos = [x for x in cpos if (x.status or "") not in _DEAD_CPO]

    sprs, spos = [], []
    if pr is not None:
        from app.models.purchasing import SupplierPO, SupplierPriceRequest
        sprs = list((await db.scalars(select(SupplierPriceRequest).where(or_(
            SupplierPriceRequest.price_request_id == pr.id,
            SupplierPriceRequest.source_pr_ids.contains([str(pr.id)]),
        )))).all())
        sprs = [s for s in sprs if (s.status or "") not in ("cancelled", "void", "voided")]
        spo_rows = list((await db.scalars(select(SupplierPO).where(
            SupplierPO.price_request_id == pr.id))).all())
        # Lines carry their source request even on a PO raised from elsewhere.
        more = list((await db.scalars(select(SupplierPO).where(
            SupplierPO.items.contains([{"source_pr_id": str(pr.id)}])))).all())
        seen = {x.id for x in spo_rows}
        spos = [x for x in spo_rows + [m for m in more if m.id not in seen]
                if (x.status or "") not in _DEAD_SPO]
    return {"price_request": pr, "quotation": q, "customer_pos": cpos,
            "supplier_requests": sprs, "supplier_pos": spos}


# ── Comparing ────────────────────────────────────────────────────────────────

def _q_lines(q: Quotation, items=None) -> dict[int, dict]:
    rows = q.items if items is None else items
    return {int(it.line_no or 0): {
        "line_no": int(it.line_no or 0), "description": _txt(it.description),
        "qty": _num(it.qty), "uom": _txt(it.uom) or "pcs", "price": _num(it.unit_price),
    } for it in rows}


def _pr_lines(pr: PriceRequest) -> dict[int, dict]:
    return {int(it.get("line_no") or (i + 1)): {
        "line_no": int(it.get("line_no") or (i + 1)), "description": _txt(it.get("description")),
        "qty": _num(it.get("qty")), "uom": _txt(it.get("uom")) or "pcs",
        "price": _num(it.get("sell_price")),
    } for i, it in enumerate(pr.items or [])}


def _compare(a: dict[int, dict], b: dict[int, dict], fields,
             a_only: str, b_only: str) -> list[dict]:
    out = []
    for no in sorted(set(a) | set(b)):
        x, y = a.get(no), b.get(no)
        if y is None:
            out.append({"line_no": no, "change": a_only, "description": x["description"]})
        elif x is None:
            out.append({"line_no": no, "change": b_only, "description": y["description"]})
        else:
            diffs = [{"field": f, "left": x[f], "right": y[f]} for f in fields if x[f] != y[f]]
            if diffs:
                out.append({"line_no": no, "change": "differs",
                            "description": y["description"] or x["description"],
                            "fields": diffs})
    return out


def _match_cpo(q_lines: dict[int, dict], cpo: CustomerPO) -> list[tuple[int | None, dict, int]]:
    """Pair each customer PO line with the quotation line it stands for.

    New PO lines carry `line_no` (the quotation's); older ones are paired by
    description, which is what they were copied from."""
    by_key = {_key(v["description"]): no for no, v in q_lines.items()}
    used: set[int] = set()
    out = []
    for idx, it in enumerate(cpo.items or []):
        no = it.get("line_no")
        try:
            no = int(no) if no is not None else None
        except (TypeError, ValueError):
            no = None
        if no is None or no not in q_lines:
            no = by_key.get(_key(it.get("description") or ""))
        if no is not None and no in used:
            no = None
        if no is not None:
            used.add(no)
        out.append((no, {
            "description": _txt(it.get("description")), "qty": _num(it.get("qty")),
            "uom": _txt(it.get("uom")) or "pcs", "price": _num(it.get("unit_price")),
        }, idx))
    return out


# ── Who may fix what ─────────────────────────────────────────────────────────

def _quotation_edit_rule(q: Quotation, user: User) -> tuple[bool, str | None, str]:
    """(allowed, why-not, how) — the edit form's own rules, restated."""
    role = Role(user.role)
    if q.status in _Q_DIRECT:
        if role == Role.SALES and q.price_request_id:
            return False, "Prices on a quotation from a price request are set by the director.", ""
        if role == Role.PURCHASING:
            return False, "Purchasing doesn't edit quotations.", ""
        return True, None, "direct"
    if q.status in _Q_VIA_DIRECTOR:
        if role == Role.DIRECTOR:
            return True, None, "direct"
        if role == Role.PURCHASING:
            return False, "Purchasing doesn't edit quotations.", ""
        return True, None, "approval"
    if q.status == "pending_approval":
        return False, "The quotation is waiting for approval — take it back to draft first.", ""
    return False, f"A {q.status} quotation can't be changed.", ""


def _cpo_edit_rule(cpo: CustomerPO, user: User) -> tuple[bool, str | None]:
    role = Role(user.role)
    if role == Role.PURCHASING:
        return False, "Purchasing doesn't edit customer POs."
    if cpo.status in ("pending_approval", "rejected") or role == Role.DIRECTOR:
        return True, None
    return False, "The customer PO is approved — only the director can change it now."


def _pr_edit_rule(pr: PriceRequest, user: User) -> tuple[bool, str | None]:
    role = Role(user.role)
    if role in (Role.DIRECTOR, Role.MANAGER):
        return True, None
    if role == Role.SALES:
        return True, None   # matching the deal's own quotation — see `fix`
    return False, "Only sales, a manager or the director can update the price request."


# ── The report ───────────────────────────────────────────────────────────────

async def report(db: AsyncSession, chain: dict, user: User) -> dict:
    role = Role(user.role)
    pr, q = chain["price_request"], chain["quotation"]
    checks: list[dict] = []

    if pr is not None and q is not None and _sees_sell(role):
        lines = _compare(_pr_lines(pr), _q_lines(q), ("description", "qty", "uom", "price"),
                         "only_left", "only_right")
        ok_q, why_q, how_q = _quotation_edit_rule(q, user)
        ok_p, why_p = _pr_edit_rule(pr, user)
        checks.append({
            "key": "pr_quotation", "left": _doc("price_request", pr), "right": _doc("quotation", q),
            "lines": lines,
            "actions": [] if not lines else [
                {"id": "use_right", "label": f"Make {pr.number} match {q.number}",
                 "label_id": f"Samakan {pr.number} dengan {q.number}",
                 "allowed": ok_p, "reason": why_p, "how": "direct"},
                {"id": "use_left", "label": f"Make {q.number} match {pr.number}",
                 "label_id": f"Samakan {q.number} dengan {pr.number}",
                 "allowed": ok_q, "reason": why_q, "how": how_q},
            ],
        })

    if q is not None and _sees_sell(role):
        ql = _q_lines(q)
        for cpo in chain["customer_pos"]:
            pairs = _match_cpo(ql, cpo)
            single = len(chain["customer_pos"]) == 1
            lines = []
            for no, row, idx in pairs:
                if no is None:
                    lines.append({"line_no": None, "po_index": idx, "change": "only_right",
                                  "description": row["description"]})
                    continue
                fields = ("description", "uom", "price") + (("qty",) if single else ())
                diffs = [{"field": f, "left": ql[no][f], "right": row[f]}
                         for f in fields if ql[no][f] != row[f]]
                if diffs:
                    lines.append({"line_no": no, "po_index": idx, "change": "differs",
                                  "description": ql[no]["description"], "fields": diffs})
            if single:
                matched = {no for no, _, _ in pairs if no is not None}
                for no in sorted(set(ql) - matched):
                    lines.append({"line_no": no, "change": "only_left",
                                  "description": ql[no]["description"]})
            ok_c, why_c = _cpo_edit_rule(cpo, user)
            ok_q, why_q, how_q = _quotation_edit_rule(q, user)
            checks.append({
                "key": f"quotation_cpo:{cpo.id}", "left": _doc("quotation", q),
                "right": _doc("customer_po", cpo), "partial": not single, "lines": lines,
                "actions": [] if not lines else [
                    {"id": "use_left", "label": f"Make customer PO {cpo.number} match {q.number}",
                     "label_id": f"Samakan PO pelanggan {cpo.number} dengan {q.number}",
                     "allowed": ok_c, "reason": why_c, "how": "direct"},
                    {"id": "use_right", "label": f"Make {q.number} match customer PO {cpo.number}",
                     "label_id": f"Samakan {q.number} dengan PO pelanggan {cpo.number}",
                     "allowed": ok_q, "reason": why_q, "how": how_q},
                ],
            })

    if pr is not None and _sees_buy(role):
        from app.api.v1.endpoints.supplier_price_requests import _source_drift
        for spr in chain["supplier_requests"]:
            drift = _source_drift(spr, {pr.id: pr})
            lines = [{"line_no": d.get("line_no"), "change": "differs" if d["change"] == "differs"
                      else "only_right", "description": d.get("description"),
                      "fields": [{"field": f["field"], "left": f["on_source"],
                                  "right": f["on_request"]} for f in d.get("fields", [])]}
                     for d in drift]
            checks.append({
                "key": f"supplier_request:{spr.id}", "left": _doc("price_request", pr),
                "right": _doc("supplier_price_request", spr), "lines": lines,
                "actions": [] if not lines else [
                    {"id": "use_left", "label": f"Refresh {spr.number} from {pr.number}",
                     "label_id": f"Perbarui {spr.number} dari {pr.number}",
                     "allowed": True, "reason": None, "how": "direct"}],
            })

        if chain["supplier_pos"]:
            need = {no: v for no, v in _pr_lines(pr).items()}
            ordered: dict[int, float] = {}
            for spo in chain["supplier_pos"]:
                for it in (spo.items or []):
                    from_here = (str(it.get("source_pr_id") or "") == str(pr.id)
                                 or spo.price_request_id == pr.id)
                    if not from_here:
                        continue
                    no = it.get("source_line_no")
                    if no is None:
                        continue
                    ordered[int(no)] = ordered.get(int(no), 0) + _num(it.get("qty"))
            lines = []
            for no, v in sorted(need.items()):
                if no in ordered and abs(ordered[no] - v["qty"]) > 1e-6:
                    lines.append({"line_no": no, "change": "differs",
                                  "description": v["description"],
                                  "fields": [{"field": "qty", "left": v["qty"],
                                              "right": ordered[no]}]})
            checks.append({
                "key": "supplier_po_qty", "left": _doc("price_request", pr),
                "right": {"kind": "supplier_pos", "id": None,
                          "number": ", ".join(s.number for s in chain["supplier_pos"]),
                          "docs": [_doc("supplier_po", s) for s in chain["supplier_pos"]]},
                "lines": lines, "info_only": True, "actions": [],
            })

    return {
        "documents": {
            "price_request": _doc("price_request", pr) if pr is not None else None,
            "quotation": _doc("quotation", q) if q is not None and _sees_sell(role) else None,
            "customer_pos": [_doc("customer_po", c) for c in chain["customer_pos"]]
                            if _sees_sell(role) else [],
            "supplier_requests": [_doc("supplier_price_request", s)
                                  for s in chain["supplier_requests"]]
                                 if _sees_buy(role) else [],
            "supplier_pos": [_doc("supplier_po", s) for s in chain["supplier_pos"]]
                            if _sees_buy(role) else [],
        },
        "checks": checks,
        "issues": sum(len(c["lines"]) for c in checks),
    }


# ── Fixing ───────────────────────────────────────────────────────────────────

class FixRefused(Exception):
    pass


def _item_payload(it: QuotationItem) -> dict:
    return {"line_no": int(it.line_no), "source": it.source or "custom",
            "product_id": str(it.product_id) if it.product_id else None,
            "sku": it.sku, "description": it.description, "spec": it.spec or {},
            "qty": float(it.qty or 0), "uom": it.uom or "pcs",
            "unit_price": float(it.unit_price or 0),
            "cost_estimate": float(it.cost_estimate or 0)}


async def _write_quotation(db: AsyncSession, q: Quotation, items: list[dict],
                           user: User, why: str) -> dict:
    """Put new lines on a quotation the way the edit form would."""
    from app.api.v1.endpoints.quotations import _apply_quotation_changes
    from app.core.approval import file_or_revise
    from app.core.audit import record as audit_record

    ok, reason, how = _quotation_edit_rule(q, user)
    if not ok:
        raise FixRefused(reason or "Not allowed")
    if how == "approval":
        await file_or_revise(
            db, target_type="quotation_edit", target_id=q.id, requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Edit approved quotation {q.number}: items ({why})",
            changes={"items": items})
        await audit_record(db, actor=user, action="edit_requested", entity="quotation",
                           entity_id=q.id, after={"changes": ["items"], "why": why})
        return {"queued": True,
                "message": f"Sent to the director — {q.number} changes once they approve."}
    await _apply_quotation_changes(db, q, {"items": items})
    q.updated_by = user.id
    await audit_record(db, actor=user, action="update", entity="quotation",
                       entity_id=q.id, after={"why": why})
    return {"queued": False, "message": f"{q.number} updated."}


async def fix(db: AsyncSession, chain: dict, user: User, check_key: str, action: str) -> dict:
    from app.core.audit import record as audit_record
    role = Role(user.role)
    pr, q = chain["price_request"], chain["quotation"]

    if check_key == "pr_quotation":
        if pr is None or q is None or not _sees_sell(role):
            raise FixRefused("Nothing to compare.")
        if action == "use_right":                 # request follows the quotation
            ok, why = _pr_edit_rule(pr, user)
            if not ok:
                raise FixRefused(why)
            from app.services.price_request_sync import sync_from_quotation
            res = await sync_from_quotation(db, q, user)
            return {"queued": False, "message": f"{pr.number} now matches {q.number}"
                    + ("" if res else " (it already did)") + "."}
        if action == "use_left":                  # quotation follows the request
            from app.services.quotation_sync import _line_of
            current = {int(it.line_no): it for it in q.items}
            items = []
            for i, it in enumerate(pr.items or []):
                w = _line_of(it, i)
                old = current.get(int(w["line_no"]))
                row = _item_payload(old) if old is not None else {
                    "line_no": w["line_no"], "source": "custom", "product_id": None,
                    "spec": it.get("spec") or {}}
                row.update({k: w[k] for k in ("sku", "description", "qty", "uom",
                                              "unit_price", "cost_estimate")})
                row["sku"] = row.get("sku") or (old.sku if old is not None else None)
                items.append(row)
            return await _write_quotation(db, q, items, user, f"matched to {pr.number}")
        raise FixRefused("Unknown action.")

    if check_key.startswith("quotation_cpo:"):
        cpo_id = check_key.split(":", 1)[1]
        cpo = next((c for c in chain["customer_pos"] if str(c.id) == cpo_id), None)
        if cpo is None or q is None or not _sees_sell(role):
            raise FixRefused("That customer PO isn't part of this deal.")
        ql = {int(it.line_no): it for it in q.items}
        pairs = _match_cpo(_q_lines(q), cpo)
        single = len(chain["customer_pos"]) == 1
        if action == "use_left":                  # customer PO follows the quotation
            ok, why = _cpo_edit_rule(cpo, user)
            if not ok:
                raise FixRefused(why)
            items = []
            for no, _row, idx in pairs:
                old = dict((cpo.items or [])[idx])
                if no is not None:
                    src = ql[no]
                    old.update({"line_no": no, "description": src.description,
                                "uom": src.uom, "unit_price": float(src.unit_price or 0)})
                    if single:
                        old["qty"] = float(src.qty or 0)
                items.append(old)
            if single:
                have = {no for no, _, _ in pairs if no is not None}
                for no in sorted(set(ql) - have):
                    src = ql[no]
                    items.append({"line_no": no, "description": src.description,
                                  "qty": float(src.qty or 0), "uom": src.uom,
                                  "unit_price": float(src.unit_price or 0)})
            before = list(cpo.items or [])
            cpo.items = items
            cpo.total = sum(float(i.get("qty") or 0) * float(i.get("unit_price") or 0)
                            for i in items)
            cpo.updated_by = user.id
            await audit_record(db, actor=user, action="update", entity="customer_po",
                               entity_id=cpo.id, before={"items": before},
                               after={"items": items, "why": f"matched to {q.number}"})
            await db.flush()
            return {"queued": False, "message": f"Customer PO {cpo.number} now matches {q.number}."}
        if action == "use_right":                 # quotation follows the customer PO
            items = [_item_payload(it) for it in sorted(q.items, key=lambda x: x.line_no)]
            by_no = {r["line_no"]: r for r in items}
            next_no = max(by_no or [0]) + 1
            for no, row, _idx in pairs:
                if no is None:
                    items.append({"line_no": next_no, "source": "custom", "product_id": None,
                                  "sku": None, "description": row["description"], "spec": {},
                                  "qty": row["qty"], "uom": row["uom"],
                                  "unit_price": row["price"], "cost_estimate": 0})
                    next_no += 1
                    continue
                r = by_no[no]
                r.update({"description": row["description"], "uom": row["uom"],
                          "unit_price": row["price"]})
                if single:
                    r["qty"] = row["qty"]
            return await _write_quotation(db, q, items, user,
                                          f"matched to customer PO {cpo.number}")
        raise FixRefused("Unknown action.")

    if check_key.startswith("supplier_request:"):
        if not _sees_buy(role):
            raise FixRefused("Not yours to change.")
        spr_id = check_key.split(":", 1)[1]
        if not any(str(s.id) == spr_id for s in chain["supplier_requests"]):
            raise FixRefused("That supplier request isn't part of this deal.")
        from app.api.v1.endpoints.supplier_price_requests import refresh_from_source
        await refresh_from_source(UUID(spr_id), None, db, user)
        return {"queued": False, "message": "Supplier request refreshed."}

    raise FixRefused("Nothing to fix there.")
