"""A cost changed on a price request follows to the supplier quote behind it.

Asked for: *"if a director changes a price request cost make it auto sync to
the supplier price request."* A supplier price request (SPR) is where a cost
comes from — purchasing records the vendor's quote and applies it. When the
director then corrects that cost on the price request (at approval, in
Reprice, or on the job's order), the quote on file still said the old price,
so the two documents disagreed about what the vendor charges.

Now the quote line moves with it:

* **Which quote.** The one the line's cost came from (`cost_source`). A line
  costed by hand has none named — then the one supplier request asking about
  that line, if there is exactly one. Several and none named: no guess; the
  line is reported as not synced.
* **In the quote's own currency.** Typed in the same currency as the quote
  (¥12 on a yuan quote), the quote takes that figure. Otherwise the rupiah
  cost is turned back into the quote's currency at the quote's own rate. A
  foreign quote with no rate can't be converted, and says so.
* A cancelled request is left alone. Each change is written into the quote's
  log and the audit trail, and the price request line is linked to the quote
  it now agrees with.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


def _src(spr, line: dict) -> tuple[str | None, int]:
    pr_id = line.get("source_pr_id") or (str(spr.price_request_id) if spr.price_request_id else None)
    return (str(pr_id) if pr_id else None,
            int(line.get("source_line_no") or line.get("line_no") or 0))


async def push_costs_to_suppliers(db: AsyncSession, pr, line_nos, user=None) -> list[dict]:
    """Bring the supplier quote lines behind `line_nos` of `pr` to their new
    cost. Returns one row per line: the quote updated, or why not."""
    from app.core.audit import record as audit_record
    from app.models.purchasing import SupplierPriceRequest

    line_nos = {int(n) for n in (line_nos or [])}
    if not line_nos:
        return []
    sprs = (await db.scalars(select(SupplierPriceRequest).where(
        or_(SupplierPriceRequest.price_request_id == pr.id,
            SupplierPriceRequest.source_pr_ids.contains([str(pr.id)])),
        SupplierPriceRequest.status != "cancelled",
    ).order_by(SupplierPriceRequest.created_at))).all()

    # Which quote lines ask about each price request line.
    asking: dict[int, list] = {}
    for spr in sprs:
        for idx, ln in enumerate(spr.items or []):
            if not isinstance(ln, dict):
                continue
            src_pr, src_ln = _src(spr, ln)
            if src_pr == str(pr.id) and src_ln in line_nos:
                asking.setdefault(src_ln, []).append((spr, idx))

    out: list[dict] = []
    changed_sprs: dict = {}
    pr_items = [dict(it) for it in (pr.items or [])]
    for it in pr_items:
        n = int(it.get("line_no") or 0)
        if n not in line_nos or it.get("cost_price") is None:
            continue
        cands = asking.get(n, [])
        named = [c for c in cands if c[0].number == it.get("cost_source")]
        pick = named[0] if named else (cands[0] if len({c[0].id for c in cands}) == 1 else None)
        if pick is None:
            out.append({"line_no": n, "skipped": "no supplier quote asks about this line"
                        if not cands else "several supplier quotes — none named as its source"})
            continue
        spr, idx = pick
        cur = (spr.currency or "IDR").upper()
        rate = 1.0 if cur == "IDR" else (float(spr.fx_rate) if spr.fx_rate else None)
        if it.get("cost_currency") and it["cost_currency"].upper() == cur and it.get("cost_original") is not None:
            quoted = float(it["cost_original"])
        elif cur == "IDR":
            quoted = float(it["cost_price"])
        elif rate:
            quoted = float(it["cost_price"]) / rate
        else:
            out.append({"line_no": n, "spr": spr.number,
                        "skipped": f"{spr.number} is in {cur} with no rate to convert at"})
            continue
        quoted = round(quoted, 4)
        lines = changed_sprs.get(spr.id, (spr, [dict(x) for x in (spr.items or [])]))[1]
        old = lines[idx].get("quoted_price")
        if old is not None and abs(float(old) - quoted) < 0.00005:
            out.append({"line_no": n, "spr": spr.number, "unchanged": True})
            continue
        lines[idx]["quoted_price"] = quoted
        lines[idx]["quoted_basis"] = "unit"
        changed_sprs[spr.id] = (spr, lines)
        it["cost_source"] = spr.number
        out.append({"line_no": n, "spr": spr.number, "spr_id": str(spr.id),
                    "from": old, "to": quoted, "currency": cur})

    by_role = getattr(getattr(user, "role", None), "value", None) or getattr(user, "role", None) or "system"
    for spr, lines in changed_sprs.values():
        spr.items = lines
        moved = [r for r in out if r.get("spr") == spr.number and "to" in r]
        spr.notes = ((spr.notes or "") + "".join(
            f"\n[{by_role}] line for {pr.number} #{r['line_no']}: "
            f"{r['from'] if r['from'] is not None else '—'} → {r['to']:g} {r['currency']} "
            "(cost changed on the price request)" for r in moved)).strip()
        await audit_record(db, actor=user, action="sync_from_price_request",
                           entity="supplier_price_request", entity_id=spr.id,
                           after={"price_request": pr.number,
                                  "lines": [{k: r[k] for k in ("line_no", "from", "to")} for r in moved]})
    if changed_sprs:
        pr.items = pr_items
        await db.flush()
    return out
