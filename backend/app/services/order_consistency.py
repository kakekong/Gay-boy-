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
* ``supplier_po_qty``   — the live supplier POs against what each request
  line needs: the quantity ordered, the unit, what the PO pays per unit
  against the line's cost (in rupiah), and any item no supplier PO
  carries. The POs are the ones whose lines come from the request and the
  ones raised on the job itself (a line with no source is matched by its
  wording). Reported only: a placed order is changed with the supplier, on
  the PO page.
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
        # And the POs raised on the job itself, whose lines may carry no
        # source at all — typed on the PO page rather than built from the
        # request.
        from app.models.operation import Project
        from app.services.receiving import pos_for_project
        jobs = {c.project_id for c in cpos if getattr(c, "project_id", None)}
        if project_id:
            jobs.add(project_id if isinstance(project_id, UUID) else UUID(str(project_id)))
        jobs |= set((await db.scalars(select(Project.id).where(
            Project.price_request_id == pr.id))).all())
        on_job = []
        for j in jobs:
            on_job += await pos_for_project(db, j)
        seen: set = set()
        spos = []
        for x in spo_rows + more + on_job:
            if x.id in seen or (x.status or "") in _DEAD_SPO:
                continue
            seen.add(x.id)
            spos.append(x)
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
        "cost": _num(it.get("cost_price")) if it.get("cost_price") is not None else None,
    } for i, it in enumerate(pr.items or [])}


def _merge_split(lines: dict[int, dict]) -> tuple[dict[int, dict], dict[int, int]]:
    """One item written on several lines — the same part at the same unit and
    price, split (100 + 30) to suit the customer's own system — is one item to
    compare: it reads as its first line, carrying the quantity of all of them.

    Returns the merged lines and, for every line number, the line it now reads
    as (so a reference to the second half still finds the item)."""
    first: dict[tuple, int] = {}
    out: dict[int, dict] = {}
    alias: dict[int, int] = {}
    for no in sorted(lines):
        v = lines[no]
        k = (_key(v["description"]), v["uom"], v["price"])
        if k[0] and k in first:
            keep = first[k]
            out[keep] = {**out[keep], "qty": _num(out[keep]["qty"] + v["qty"]),
                         "split": out[keep].get("split", [keep]) + [no]}
            alias[no] = keep
            continue
        first[k] = no
        out[no] = dict(v)
        alias[no] = no
    return out, alias


def _match_cpo_items(q_lines: dict[int, dict], alias: dict[int, int],
                     cpo: CustomerPO) -> list[tuple[int | None, dict, int]]:
    """`_match_cpo` for the report: the customer PO's lines paired with the
    quotation's items, a split on either side counted as one item."""
    by_key = {_key(v["description"]): no for no, v in q_lines.items()}
    got: dict[int, tuple[dict, int]] = {}
    loose: list[tuple[int | None, dict, int]] = []
    for idx, it in enumerate(cpo.items or []):
        row = {"description": _txt(it.get("description")), "qty": _num(it.get("qty")),
               "uom": _txt(it.get("uom")) or "pcs", "price": _num(it.get("unit_price"))}
        try:
            no = int(it.get("line_no")) if it.get("line_no") is not None else None
        except (TypeError, ValueError):
            no = None
        no = alias.get(no) if no is not None else None
        if no is None or _key(q_lines[no]["description"]) != _key(row["description"]):
            no = by_key.get(_key(row["description"]), no)
        if no is None:
            loose.append((None, row, idx))
        elif no in got:
            had, first_idx = got[no]
            if (had["uom"], had["price"]) == (row["uom"], row["price"]):
                got[no] = ({**had, "qty": _num(had["qty"] + row["qty"])}, first_idx)
            else:
                loose.append((None, row, idx))
        else:
            got[no] = (row, idx)
    return [(no, row, idx) for no, (row, idx) in got.items()] + loose


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


def _supplier_po_lines(pr: PriceRequest, spos) -> tuple[list[dict], dict[int, float], dict[int, float]]:
    """The supplier POs against what each request line needs: the lines that
    differ (quantity, unit, cost per unit in rupiah, or not ordered); for
    each line whose cost differs, what the POs really pay per unit; and for
    each whose quantity differs, what they order. A line the order splits in
    two (100 + 30) is left out of the quantity: which half would change?"""
    from app.services.ledger import po_rate
    need, pr_alias = _merge_split(_pr_lines(pr))
    by_key = {_key(v["description"]): no for no, v in need.items()}
    ordered: dict[int, float] = {}
    units: dict[int, set] = {}
    # What the orders pay for each line, in rupiah — None once any of them
    # is a foreign order with no rate yet.
    paid: dict[int, float | None] = {}
    for spo in spos:
        rate = po_rate(spo)
        shared = len({str(x) for x in (spo.project_ids or []) if x}) > 1
        for it in (spo.items or []):
            src = str(it.get("source_pr_id") or "")
            if src and src != str(pr.id):
                continue            # another job's line on a shared order
            no = it.get("source_line_no")
            if src or spo.price_request_id == pr.id:
                if no is None:
                    no = by_key.get(_key(it.get("description") or ""))
            elif not shared:
                # Typed on the PO page: the job's item it names.
                no = by_key.get(_key(it.get("description") or ""))
            else:
                no = None
            if no is None:
                continue
            no = pr_alias.get(int(no), int(no))
            if no not in need:
                continue
            ordered[no] = ordered.get(no, 0) + _num(it.get("qty"))
            units.setdefault(no, set()).add(_txt(it.get("uom")) or "pcs")
            unit = it.get("unit_price") if it.get("unit_price") is not None else it.get("unit_cost")
            if rate is None or unit is None or paid.get(no, 0) is None:
                paid[no] = None
            else:
                paid[no] = paid.get(no, 0) + _num(it.get("qty")) * float(unit) * rate
    lines: list[dict] = []
    cost_to: dict[int, float] = {}
    qty_to: dict[int, float] = {}
    for no, v in sorted(need.items()):
        if no not in ordered:
            lines.append({"line_no": no, "change": "only_left", "description": v["description"]})
            continue
        fields = []
        if abs(ordered[no] - v["qty"]) > 1e-6:
            fields.append({"field": "qty", "left": v["qty"], "right": ordered[no]})
            if len(v.get("split", [no])) == 1 and ordered[no] > 0:
                qty_to[no] = ordered[no]
        other = sorted(u for u in units.get(no, set()) if u.lower() != v["uom"].lower())
        if other:
            fields.append({"field": "uom", "left": v["uom"], "right": ", ".join(other)})
        # The cost the order card carries against what the supplier PO
        # really pays per unit. Seen by purchasing and management only —
        # this check is never built for anyone else.
        if v.get("cost") is not None and paid.get(no) is not None and ordered[no] > 0:
            per_unit = round(paid[no] / ordered[no], 2)
            if abs(per_unit - v["cost"]) >= 1:
                fields.append({"field": "cost", "left": v["cost"], "right": per_unit})
                for each in v.get("split", [no]):
                    cost_to[each] = per_unit
        if fields:
            lines.append({"line_no": no, "change": "differs",
                          "description": v["description"], "fields": fields})
    return lines, cost_to, qty_to


# ── The report ───────────────────────────────────────────────────────────────

async def report(db: AsyncSession, chain: dict, user: User) -> dict:
    role = Role(user.role)
    pr, q = chain["price_request"], chain["quotation"]
    checks: list[dict] = []

    if pr is not None and q is not None and _sees_sell(role):
        lines = _compare(_merge_split(_pr_lines(pr))[0], _merge_split(_q_lines(q))[0],
                         ("description", "qty", "uom", "price"), "only_left", "only_right")
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
        ql, alias = _merge_split(_q_lines(q))
        for cpo in chain["customer_pos"]:
            pairs = _match_cpo_items(ql, alias, cpo)
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
            lines, cost_to, qty_to = _supplier_po_lines(pr, chain["supplier_pos"])
            may_cost = role in (Role.PURCHASING, Role.DIRECTOR)
            checks.append({
                "key": "supplier_po_qty", "left": _doc("price_request", pr),
                "right": {"kind": "supplier_pos", "id": None,
                          "number": ", ".join(s.number for s in chain["supplier_pos"]),
                          "docs": [_doc("supplier_po", s) for s in chain["supplier_pos"]]},
                "lines": lines, "info_only": True,
                # Settled from here: the order following the supplier PO —
                # its cost per unit, and its quantity (the director's, as
                # arranging the order is). The PO itself is changed with
                # the supplier, on the PO page.
                "actions": [] if not (cost_to or qty_to) else [
                    {"id": "use_right",
                     "label": ("Use the supplier PO's cost and quantity on the order"
                               if cost_to and qty_to else
                               "Use the supplier PO's quantity on the order" if qty_to
                               else "Use the supplier PO's cost on the order"),
                     "label_id": ("Pakai biaya dan jumlah PO supplier di pesanan"
                                  if cost_to and qty_to else
                                  "Pakai jumlah PO supplier di pesanan" if qty_to
                                  else "Pakai biaya PO supplier di pesanan"),
                     "carries": [k for k, v in (("cost", cost_to), ("qty", qty_to)) if v],
                     "allowed": may_cost,
                     "reason": None if may_cost else "What a line costs is purchasing's and the director's to change.",
                     "how": "direct"}],
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


async def _order_qty_from_pos(db: AsyncSession, pr: PriceRequest, user: User,
                              qty_to: dict[int, float], pos: str) -> dict:
    """The order's quantities set to what the supplier POs order — through
    Arrange order, so its rules hold: the director's applies now and the
    quotation follows the request; anyone else's goes to the director."""
    from fastapi import HTTPException

    from app.api.v1.endpoints import project_order as po_mod
    from app.core.approval import request_approval
    from app.core.audit import record as audit_record
    from app.models.approval import ApprovalStatus
    from app.models.operation import Project

    p = await db.scalar(select(Project).where(Project.price_request_id == pr.id,
                                              Project.is_deleted.is_(False)).limit(1))
    if p is None:
        raise FixRefused("This order has no project to arrange — change the quantity on the price request.")
    lines = [po_mod.OrderLineIn(line_no=int(it.get("line_no")),
                                qty=qty_to.get(int(it.get("line_no"))))
             for it in po_mod._ordered(pr, p)]
    try:
        plan = po_mod._plan(pr, p, lines, director=Role(user.role) == Role.DIRECTOR)
    except HTTPException as e:
        raise FixRefused(str(e.detail)) from e
    n = len(qty_to)
    what = f"the quantity on {n} line{'s' if n != 1 else ''}"
    if Role(user.role) == Role.DIRECTOR:
        before = {"items": pr.items, "item_order": p.item_order}
        po_mod.apply_order(p, pr, plan)
        # A proposal waiting on this order — purchasing asking the same — is
        # answered by this, as when the director arranges the order.
        waiting = await po_mod.pending_for(db, p.id)
        if waiting:
            from datetime import UTC, datetime
            waiting.status = ApprovalStatus.APPROVED.value
            waiting.decided_by = user.id
            waiting.decided_at = datetime.now(UTC)
            waiting.decision_notes = f"Applied from the deal check — the order now matches the {pos}"
        from app.services.quotation_sync import sync_from_price_request
        await sync_from_price_request(db, pr, user)
        await audit_record(db, actor=user, action="order_change", entity="project",
                           entity_id=p.id, before=before,
                           after={"summary": plan["summary"], "from": pos})
        return {"queued": False, "said": what}
    stored = {"lines": [ln.model_dump() for ln in lines], "summary": plan["summary"],
              "note": f"Matched to the {pos}", "project_code": p.code}
    reason = f"Change the order on {p.code}: " + "; ".join(plan["summary"]) + f" — to match the {pos}"
    req = await po_mod.pending_for(db, p.id)
    if req and req.status == ApprovalStatus.PENDING.value:
        req.payload, req.reason, req.requested_by = stored, reason, user.id
    else:
        await request_approval(db, target_type=po_mod.TARGET, target_id=p.id,
                               requested_by=user.id, required_role=Role.DIRECTOR,
                               reason=reason, payload=stored)
    return {"queued": True, "said": f"{what} sent to the director to approve"}


async def fix(db: AsyncSession, chain: dict, user: User, check_key: str, action: str) -> dict:
    from app.core.audit import record as audit_record
    role = Role(user.role)
    pr, q = chain["price_request"], chain["quotation"]

    if check_key == "supplier_po_qty":
        # The order follows the supplier POs: the cost per unit they really
        # pay — the same change as "Edit costs", purchasing's or the
        # director's — and the quantity they order, which changes what the
        # customer is sold: arranging the order, so the director's own
        # applies now (and reaches the quotation) and anyone else's goes to
        # the director.
        if action != "use_right":
            raise FixRefused("A placed order is changed with the supplier, on the PO page.")
        if role not in (Role.PURCHASING, Role.DIRECTOR):
            raise FixRefused("What a line costs is purchasing's and the director's to change.")
        if pr is None or not chain["supplier_pos"]:
            raise FixRefused("No supplier PO on this order.")
        _lines, cost_to, qty_to = _supplier_po_lines(pr, chain["supplier_pos"])
        if not cost_to and not qty_to:
            raise FixRefused("The order already matches the supplier POs.")
        pos = f"supplier PO{'s' if len(chain['supplier_pos']) > 1 else ''}"
        said: list[str] = []
        queued = False
        if cost_to:
            from app.services.quotation_sync import sync_costs
            before = [dict(it) for it in (pr.items or [])]
            items, changed = [], []
            for i, it in enumerate(pr.items or []):
                it = dict(it)
                no = int(it.get("line_no") or (i + 1))
                if no in cost_to:
                    changed.append(f"“{it.get('description')}”: {it.get('cost_price')} → {cost_to[no]}")
                    it["cost_price"] = cost_to[no]
                    it["cost_basis"] = "unit"
                items.append(it)
            pr.items = items
            await sync_costs(db, pr)
            await audit_record(db, actor=user, action="order_costs", entity="price_request",
                               entity_id=pr.id, before={"items": before},
                               after={"from_supplier_pos": [s.number for s in chain["supplier_pos"]],
                                      "changed": changed})
            n = len(changed)
            said.append(f"the cost on {n} line{'s' if n != 1 else ''}")
        if qty_to:
            res = await _order_qty_from_pos(db, pr, user, qty_to, pos)
            queued = res["queued"]
            said.append(res["said"])
        await db.flush()
        return {"queued": queued,
                "message": f"The order now follows the {pos}: " + "; ".join(said) + "."}

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
