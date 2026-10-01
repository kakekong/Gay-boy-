"""What the director is told is waiting is what the inbox shows.

Reported: approval requests for purchasing POs (and others) reached the
director — the bell said "Approval needed" — but were not in the approvals
inbox. Two causes:

* the inbox drops requests whose document has moved past needing a decision,
  and the bell did not, so the two disagreed;
* receiving goods on a PO still waiting for the director flipped it to
  'received', which the inbox read as decided — the director never saw it.

Now one rule decides what is settled for both, receiving leaves a waiting
order waiting, and approving an order received early marks it received.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.purchasing import Supplier, SupplierPO
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    pur = await login("purchasing@demo.local")

    async with SessionLocal() as db:
        sup = await db.scalar(select(Supplier).limit(1))
        sup_id = str(sup.id)

    async def inbox_ids():
        return {r["target_id"] for r in J(await c.get("/approvals", headers=d))
                if r["target_type"] == "supplier_po"}

    async def bell_and_inbox_agree(po_id=None):
        """Nothing in the bell that the inbox lacks — the reported bug. (The
        inbox may hold more: a bell item can be dismissed on purpose.) And
        for the order in hand, it is in both or in neither."""
        inbox = {r["id"]: r for r in J(await c.get("/approvals", headers=d))}
        bell = {i["id"].split(":", 1)[1] for i in
                J(await c.get("/notifications", headers=d)).get("items", [])
                if i.get("kind") == "approval" and i["id"].startswith("approval:")}
        extra = bell - set(inbox)
        if extra:
            return False, f"in the bell but not the inbox: {sorted(extra)[:3]}"
        if po_id:
            async with SessionLocal() as db:
                from app.models.approval import ApprovalRequest
                req_ids = {str(x) for x in (await db.scalars(select(ApprovalRequest.id).where(
                    ApprovalRequest.target_id == uuid.UUID(po_id),
                    ApprovalRequest.status == "pending"))).all()}
            in_inbox = bool(req_ids & set(inbox))
            in_bell = bool(req_ids & bell)
            if in_inbox != in_bell:
                return False, f"inbox {in_inbox} vs bell {in_bell}"
        return True, ""

    async def a_po(n):
        r = await c.post("/purchasing/po", headers=pur, json={
            "supplier_id": sup_id, "number": f"PO-INBOX-{TAG}-{n}",
            "currency": "IDR", "total": 1_000_000,
            "items": [{"description": f"PIN {TAG} {n}", "qty": 10, "unit_price": 100_000}]})
        body = J(r)
        return body.get("id"), body.get("status")

    print("\n── goods arrive before the director has signed the order ──")
    po1, st = await a_po(1)
    check("purchasing's order waits for the director", st == "pending_approval", str(st))
    check("...and is in the director's inbox", po1 in await inbox_ids())
    r = await c.post(f"/purchasing/po/{po1}/gr", headers=pur, json={
        "items": [{"description": f"PIN {TAG} 1", "qty": 10}]})
    check("goods are received against it", r.status_code in (200, 201), f"{r.status_code} {J(r)}")
    async with SessionLocal() as db:
        po = await db.get(SupplierPO, uuid.UUID(po1))
        check("the order is still waiting for the director — receiving didn't decide it",
              po.status == "pending_approval", po.status)
    check("...so it is still in the inbox", po1 in await inbox_ids())
    ok, why = await bell_and_inbox_agree(po1)
    check("the bell says only what the inbox shows", ok, why)
    req = next(r for r in J(await c.get("/approvals", headers=d)) if r["target_id"] == po1)
    r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
    check("the director approves it", r.status_code == 200, f"{r.status_code} {J(r)}")
    async with SessionLocal() as db:
        po = await db.get(SupplierPO, uuid.UUID(po1))
        check("...and it reads received, not wound back to open", po.status == "received", po.status)

    print("\n── an order stuck that way from before ──")
    po2, _ = await a_po(2)
    async with SessionLocal() as db:
        po = await db.get(SupplierPO, uuid.UUID(po2))
        po.status = "received"          # what receiving used to do
        await db.commit()
    check("an order received before approval is back in the inbox", po2 in await inbox_ids())
    ok, why = await bell_and_inbox_agree(po2)
    check("...and the bell agrees", ok, why)

    print("\n── an order that really is settled ──")
    po3, _ = await a_po(3)
    async with SessionLocal() as db:
        po = await db.get(SupplierPO, uuid.UUID(po3))
        po.status = "cancelled"
        await db.commit()
    check("a cancelled order drops out of the inbox", po3 not in await inbox_ids())
    ok, why = await bell_and_inbox_agree(po3)
    check("...and out of the bell too", ok, why)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())
