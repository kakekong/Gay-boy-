"""Part codes in one format: the customer's code, a dash, four digits.

Asked for: *"the uniform number should be MTP-0010 … the MTP comes from PT
Mangole Timber Producer, the first letters of every name."* Codes were typed
by hand, so one series held MTP-0010, MTP-010 and mtp0010 — the same number
three ways, and sometimes two different parts under it.

* **Each customer has a code** — the first letter of each word of its name,
  leaving out PT, CV, Tbk and the like. Two customers with the same initials
  never share one: the newer gets MTP2, and the director can change either.
* **Each part belongs to the customer that asked for it** (`customer_id` on
  the catalogue row) and is numbered in that customer's series: MTP-0001,
  MTP-0002 … Parts bought with no customer — stock — go in STK-0001 …;
  parts already on file with no customer (the Accurate import) keep theirs.
* **Reorganize** renumbers a customer's series by the order its parts came
  into the system: the first is 0001, the next 0002, with no gaps and no
  number twice. Every document line naming an old code is rewritten, and the
  old code stays on the part as an alias, so a label or a line typed from it
  still lands on the right part.
* **On a price request**, a part the customer has had before takes that
  part's code, and the code can't be changed (`lock_lines`). A new part gets
  its code when the request is submitted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

STOCK_PREFIX = "STK"
WIDTH = 4

# Legal forms and filler words that are not part of a company's own name.
_SKIP = {"PT", "CV", "UD", "PD", "FA", "TBK", "PERSERO", "PERUM", "PERSEROAN",
         "TERBATAS", "KOPERASI", "KOP", "YAYASAN", "THE", "AND", "DAN", "&",
         "CO", "LTD", "LIMITED", "INC", "CORP"}

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")


def initials(company_name: str | None) -> str:
    """MTP for PT MANGOLE TIMBER PRODUCER; FRE for a one-word PT FREEPORT."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", (company_name or "").upper()) if w]
    words = [w for w in words if w not in _SKIP] or words
    if not words:
        return "CUS"
    if len(words) == 1:
        w = re.sub(r"[^A-Z]", "", words[0]) or words[0]
        return w[:3]
    return "".join(w[0] for w in words if w[0].isalpha())[:6] or "CUS"


def valid_code(code: str | None) -> str | None:
    c = (code or "").strip().upper()
    return c if _CODE_RE.match(c) else None


def parse(sku: str | None) -> tuple[str, int] | None:
    """("MTP", 10) for MTP-0010, mtp-010, MTP 10, mtp0010 — None for a plain
    number or anything else. A code with a separator (dash, space, dot,
    underscore) may have a digit in its prefix (MTP2-0001, mtp2 1); one
    without is read as letters then digits."""
    s = (sku or "").strip()
    m = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)\s*[-_./ ]\s*(\d+)", s)
    if not m:
        m = re.fullmatch(r"([A-Za-z]+)[\s_./]*(\d+)", s)
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def fmt(prefix: str, n: int) -> str:
    return f"{prefix}-{n:0{WIDTH}d}"


def canonical(sku: str | None) -> str | None:
    """The code in the one format, or None when it is not a prefixed code."""
    p = parse(sku)
    return fmt(*p) if p else None


# ─── Customer codes ──────────────────────────────────────────────────────────

async def ensure_code(db: AsyncSession, customer) -> str:
    """The customer's code, giving it one from its initials if it has none.
    Taken by another customer → MTP2, MTP3 …"""
    if customer.sku_code:
        return customer.sku_code
    from app.models.crm import Customer
    base = initials(customer.company_name)
    taken = {c for c in (await db.scalars(
        select(Customer.sku_code).where(Customer.sku_code.is_not(None),
                                        Customer.id != customer.id))).all()}
    taken.add(STOCK_PREFIX)
    code, n = base, 1
    while code in taken:
        n += 1
        code = f"{base[:7 - len(str(n))]}{n}"
    customer.sku_code = code
    await db.flush()
    return code


async def ensure_all_codes(db: AsyncSession) -> int:
    """Every customer gets a code, oldest first — so the customer that was
    here first keeps the plain initials."""
    from app.models.crm import Customer
    n = 0
    for c in (await db.scalars(select(Customer).where(Customer.sku_code.is_(None))
                               .order_by(Customer.created_at, Customer.id))).all():
        await ensure_code(db, c)
        n += 1
    return n


async def set_code(db: AsyncSession, customer, code: str) -> str:
    from fastapi import HTTPException, status
    from app.models.crm import Customer
    c = valid_code(code)
    if not c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A code is 1–8 letters or digits, starting with a letter")
    if c == STOCK_PREFIX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{STOCK_PREFIX} is kept for stock")
    clash = await db.scalar(select(Customer).where(Customer.sku_code == c,
                                                   Customer.id != customer.id))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{c} is already {clash.company_name}'s code")
    customer.sku_code = c
    await db.flush()
    return c


# ─── Issuing ─────────────────────────────────────────────────────────────────

async def next_code(db: AsyncSession, prefix: str) -> str:
    """One past the highest number in this prefix's series, in any spelling —
    old codes kept on renamed parts included, since those still find the part
    and must not be handed to another."""
    from app.models.inventory import InventoryItem
    top = 0
    for sku, aliases in (await db.execute(select(InventoryItem.sku, InventoryItem.aliases))).all():
        for code in [sku, *[(a or {}).get("sku") for a in (aliases or [])]]:
            p = parse(code)
            if p and p[0] == prefix:
                top = max(top, p[1])
    return fmt(prefix, top + 1)


async def code_for_new_item(db: AsyncSession, customer_id) -> str:
    if customer_id:
        from app.models.crm import Customer
        cust = await db.get(Customer, customer_id if isinstance(customer_id, UUID)
                            else UUID(str(customer_id)))
        if cust is not None:
            return await next_code(db, await ensure_code(db, cust))
    return await next_code(db, STOCK_PREFIX)


# ─── Whose part is it ────────────────────────────────────────────────────────

async def infer_owners(db: AsyncSession, *, write: bool) -> dict:
    """{item_id: customer_id} for parts with no owner on file. The code's own
    prefix first, when it is one customer's code or initials; then the
    customer of the earliest price request, then quotation, naming the code."""
    from app.models.crm import Customer
    from app.models.inventory import InventoryItem
    from app.models.price_request import PriceRequest
    from app.models.quotation import Quotation, QuotationItem

    customers = (await db.scalars(select(Customer))).all()
    by_code = {c.sku_code: c.id for c in customers if c.sku_code}
    by_init: dict[str, list] = defaultdict(list)
    for c in customers:
        by_init[initials(c.company_name)].append(c.id)

    first_pr: dict[str, UUID] = {}
    for pr in (await db.scalars(select(PriceRequest).order_by(PriceRequest.created_at))).all():
        for ln in (pr.items or []):
            s = (ln.get("sku") or "").strip() if isinstance(ln, dict) else ""
            if s:
                first_pr.setdefault(s, pr.customer_id)
    first_q: dict[str, UUID] = {}
    for sku, cid in (await db.execute(
            select(QuotationItem.sku, Quotation.customer_id)
            .join(Quotation, Quotation.id == QuotationItem.quotation_id)
            .where(QuotationItem.sku.is_not(None))
            .order_by(Quotation.created_at))).all():
        first_q.setdefault(sku.strip(), cid)

    out = {}
    for it in (await db.scalars(select(InventoryItem)
                                .where(InventoryItem.customer_id.is_(None)))).all():
        s = (it.sku or "").strip()
        owner = None
        p = parse(s)
        if p and p[0] != STOCK_PREFIX:
            owner = by_code.get(p[0])
            if owner is None and len(by_init.get(p[0], [])) == 1:
                owner = by_init[p[0]][0]
        owner = owner or first_pr.get(s) or first_q.get(s)
        if owner:
            out[it.id] = owner
            if write:
                it.customer_id = owner
    if write:
        await db.flush()
    return out


# ─── Reorganizing ────────────────────────────────────────────────────────────

def _docs():
    from app.services.inventory_merge import _DOCS
    return list(_DOCS) + [("app.models.finance:Invoice", "Invoice",
                           lambda d: None)]


async def plan(db: AsyncSession, customer_ids: list[UUID] | None = None,
               *, write: bool = False, user=None) -> dict:
    """Each customer's series renumbered by entry date. With `write`, done."""
    from app.models.crm import Customer
    from app.models.inventory import InventoryItem, InventoryMovement

    await ensure_all_codes(db)
    inferred = await infer_owners(db, write=write)
    items = (await db.scalars(select(InventoryItem))).all()
    owner = {i.id: (i.customer_id or inferred.get(i.id)) for i in items}
    series: dict = defaultdict(list)
    for i in items:
        if owner[i.id]:
            series[owner[i.id]].append(i)
    wanted = set(customer_ids) if customer_ids else None
    customers = {c.id: c for c in (await db.scalars(
        select(Customer).where(Customer.id.in_(list(series))))).all()}

    renames: dict[UUID, tuple[str, str]] = {}
    groups = []
    for cid, its in series.items():
        cust = customers.get(cid)
        if cust is None:
            continue
        its.sort(key=lambda i: (i.created_at, (parse(i.sku) or ("", 10**9))[1],
                                i.sku or "", str(i.id)))
        rows = []
        for n, i in enumerate(its, start=1):
            new = fmt(cust.sku_code, n)
            rows.append({"id": str(i.id), "name": i.name, "old": i.sku, "new": new,
                         "changes": i.sku != new,
                         "entered": i.created_at.isoformat() if i.created_at else None})
            if i.sku != new and (wanted is None or cid in wanted):
                renames[i.id] = (i.sku, new)
        groups.append({"customer_id": str(cid), "customer": cust.company_name,
                       "code": cust.sku_code, "items": rows,
                       "changing": sum(1 for r in rows if r["changes"]),
                       "duplicates": _dupes(its)})
    groups.sort(key=lambda g: (-g["changing"], g["code"]))

    # A new number already held by a part outside the series being
    # renumbered — another customer's left unticked, or a stock part — can't
    # be given out: two parts would answer to one code. Said in the preview,
    # and refused rather than half-done.
    moving = {i.id for i in items if owner[i.id] and (wanted is None or owner[i.id] in wanted)}
    held: dict[str, object] = {}
    for i in items:
        if i.id in moving or not (i.sku or "").strip():
            continue
        held.setdefault(i.sku.strip(), i)
        c = canonical(i.sku)
        if c:
            held.setdefault(c, i)
    blocked = []
    for g in groups:
        g["conflicts"] = []
        if wanted is not None and UUID(g["customer_id"]) not in wanted:
            continue
        for row in g["items"]:
            hit = held.get(row["new"])
            if hit is not None and row["changes"]:
                who = customers.get(owner[hit.id]) if owner[hit.id] else None
                g["conflicts"].append({"code": row["new"], "held_by": hit.sku, "name": hit.name,
                                       "customer": who.company_name if who else None})
        if g["conflicts"]:
            blocked.append(g)
    if write and blocked:
        from fastapi import HTTPException, status
        first = blocked[0]["conflicts"][0]
        whose = (f"{first['customer']}'s part {first['held_by']}" if first["customer"]
                 else f"the stock part {first['held_by']}")
        more = sum(len(g["conflicts"]) for g in blocked) - 1
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{first['code']} is already {whose} ({first['name']})"
            + (f", and {more} more" if more else "")
            + ". Tick that customer too, or give that part another code first.")

    # Document lines, rewritten through one old→new map so a swap
    # (0001↔0002) can't chain into a wrong code.
    old_to_new = {old: new for old, new in renames.values() if old}
    documents = await rewrite_codes(db, old_to_new, write=write)

    result = {"groups": groups, "renaming": len(renames), "documents": documents,
              "unowned": sum(1 for i in items if not owner[i.id])}
    if not write or not renames:
        return result

    # The code is unique, so step every renamed part aside first.
    by_id = {i.id: i for i in items}
    for iid in renames:
        by_id[iid].sku = f"~{str(iid)[:30]}"
    await db.flush()
    for iid, (old, new) in renames.items():
        it = by_id[iid]
        it.sku = new
        aliases = list(it.aliases or [])
        if old and not any(a.get("sku") == old for a in aliases):
            aliases.append({"sku": old, "name": it.name})
        it.aliases = aliases
        db.add(InventoryMovement(item_id=it.id, delta=0, reason="recode", reference=new,
                                 user_id=user.id if user else None,
                                 notes=f"Code {old} → {new} (reorganized by entry date)"))
    await db.flush()
    return result


async def rewrite_codes(db: AsyncSession, old_to_new: dict[str, str],
                        *, write: bool) -> list[dict]:
    """Every document line carrying an old code, given the new one. Returns
    the documents touched; with `write`, rewrites them."""
    from app.services.inventory_merge import _model
    documents: list[dict] = []
    if not old_to_new:
        return documents

    def fix(line: dict) -> bool:
        s = (line.get("sku") or "").strip()
        if s in old_to_new:
            line["sku"] = old_to_new[s]
            return True
        return False

    for path, label, link in _docs():
        M = _model(path)
        for doc in (await db.scalars(select(M))).all():
            lines = [dict(x) if isinstance(x, dict) else x for x in (doc.items or [])]
            n = sum(1 for ln in lines if isinstance(ln, dict) and fix(ln))
            if not n:
                continue
            if write:
                doc.items = lines
            documents.append({"type": label, "number": getattr(doc, "number", None)
                              or str(doc.id)[:8], "link": link(doc), "lines": n})
    from app.models.quotation import Quotation, QuotationItem
    per_q: dict = defaultdict(int)
    for it in (await db.scalars(select(QuotationItem)
                                .where(QuotationItem.sku.in_(list(old_to_new))))).all():
        per_q[it.quotation_id] += 1
        if write:
            it.sku = old_to_new.get(it.sku.strip(), it.sku)
    for qid, n in per_q.items():
        q = await db.get(Quotation, qid)
        documents.append({"type": "Quotation", "number": q.number if q else str(qid)[:8],
                          "link": f"/quotations/{qid}", "lines": n})
    return documents


async def rename_item(db: AsyncSession, item, new_sku: str, *, user=None) -> dict:
    """Give one part a new code — a temporary one replaced by the real one.

    Stored in the one format when it is a prefixed code (mtp-12 → MTP-0012).
    Refused when another part already answers to it, in any spelling or as an
    old code. Every document line with the old code takes the new one, and
    the old code stays on the part as an alias, so a label printed with it
    still finds the part."""
    from fastapi import HTTPException, status
    from app.models.inventory import InventoryItem, InventoryMovement
    from app.services.stock_sync import ItemIndex

    typed = (new_sku or "").strip()
    if not typed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A part needs a code")
    new = canonical(typed) or typed
    if len(new) > 40:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A code is at most 40 characters")
    old = item.sku
    if new == old:
        return {"sku": old, "documents": []}
    others = (await db.scalars(select(InventoryItem)
                               .where(InventoryItem.id != item.id))).all()
    clash = ItemIndex(others).find(new, None)
    if clash is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{new} is already {clash.sku} {clash.name}")
    documents = await rewrite_codes(db, {old: new}, write=True)
    item.sku = new
    aliases = list(item.aliases or [])
    if old and not any(a.get("sku") == old for a in aliases):
        aliases.append({"sku": old, "name": item.name})
    item.aliases = aliases
    db.add(InventoryMovement(item_id=item.id, delta=0, reason="recode", reference=new,
                             user_id=user.id if user else None,
                             notes=f"Code {old} → {new}"))
    await db.flush()
    return {"sku": new, "was": old, "documents": documents}


def _dupes(its) -> int:
    """How many parts share a number with another in the same series."""
    seen: dict = defaultdict(int)
    for i in its:
        p = parse(i.sku)
        if p:
            seen[p] += 1
    return sum(n for n in seen.values() if n > 1)


# ─── Price request lines ─────────────────────────────────────────────────────

async def lock_lines(db: AsyncSession, customer_id, lines: list[dict],
                     carried: set[str] | frozenset = frozenset()) -> list[dict]:
    """A line for a part this customer has had before carries that part's
    code, whatever was typed. Any other code is cleared — a new part gets
    the next number in the customer's series when the request is submitted,
    never a hand-typed one or another customer's.

    A code the request already had (`carried`) is left alone: it was issued
    to this line, and the quotation and orders after it already name it."""
    from app.models.inventory import InventoryItem
    from app.services.stock_sync import ItemIndex
    if not customer_id:
        return lines
    cid = customer_id if isinstance(customer_id, UUID) else UUID(str(customer_id))
    own = (await db.scalars(select(InventoryItem)
                            .where(InventoryItem.customer_id == cid))).all()
    idx = ItemIndex(own)
    for ln in lines:
        s = (ln.get("sku") or "").strip()
        if s and s in carried:
            ln["sku_locked"] = True
            continue
        hit = idx.find(s or None, ln.get("description"))
        ln["sku"] = hit.sku if hit is not None else None
        ln["sku_locked"] = hit is not None
    return lines


async def lookup(db: AsyncSession, customer_id, name: str | None,
                 sku: str | None = None):
    """The part this customer has had under this name (or code), or None."""
    from app.models.inventory import InventoryItem
    from app.services.stock_sync import ItemIndex
    if not customer_id or not ((name or "").strip() or (sku or "").strip()):
        return None
    own = (await db.scalars(select(InventoryItem).where(
        InventoryItem.customer_id == (customer_id if isinstance(customer_id, UUID)
                                      else UUID(str(customer_id)))))).all()
    return ItemIndex(own).find((sku or "").strip() or None, name)
