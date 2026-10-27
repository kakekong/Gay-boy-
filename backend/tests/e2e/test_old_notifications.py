"""Old notifications stay dealt with.

The director's bell and phone kept bringing back approvals from months ago:
the "pushed" and "dismissed" records were cleared after 30 days while the
approvals were still open, so each came back as new — and the phone was then
fed the whole backlog five at a time.

* An item that is already old is recorded as delivered, not pushed.
* A new item is pushed.
* The 30-day clear-out keeps the delivered and dismissed records of anything
  that can still show; only the new-each-day items (unread chat count,
  attendance, the daily roll-up) are cleared.
* A dismissed old approval stays dismissed after the clear-out.
"""
import asyncio, os, sys, uuid
from datetime import UTC, datetime, timedelta
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
    from app.models.approval import ApprovalRequest
    from app.models.push import NotificationDismissed, PushDelivered, PushSubscription
    from app.models.user import User
    from app.services import webpush
    from sqlalchemy import select, update, delete
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")

    sent: list[str] = []
    async def fake_push(db, uid, *, title, body="", url="/"):
        sent.append(body)
        return 1
    webpush.push_to_user = fake_push

    async with SessionLocal() as s:
        me = await s.scalar(select(User).where(User.email == "director@demo.local"))
        uid = me.id
        if not await s.scalar(select(PushSubscription.id).where(PushSubscription.user_id == uid)):
            s.add(PushSubscription(user_id=uid, endpoint=f"https://push.invalid/{TAG}",
                                   p256dh="x", auth="y"))
        old = ApprovalRequest(target_type="quotation", target_id=uuid.uuid4(), requested_by=uid,
                              required_role="director", reason=f"Old approval {TAG}",
                              payload={}, status="pending")
        new = ApprovalRequest(target_type="quotation", target_id=uuid.uuid4(), requested_by=uid,
                              required_role="director", reason=f"New approval {TAG}",
                              payload={}, status="pending")
        s.add_all([old, new]); await s.flush()
        await s.execute(update(ApprovalRequest).where(ApprovalRequest.id == old.id)
                        .values(created_at=datetime.now(UTC) - timedelta(days=90)))
        await s.commit()
        old_id, new_id = f"approval:{old.id}", f"approval:{new.id}"

    async def sweep():
        async with SessionLocal() as s:
            await webpush.sweep_once(s)
            await s.commit()

    async def delivered(item):
        async with SessionLocal() as s:
            return bool(await s.scalar(select(PushDelivered.id).where(
                PushDelivered.user_id == uid, PushDelivered.item_id == item)))

    print("\n── what goes to the phone ──")
    for _ in range(60):                   # drain whatever else is waiting
        before = len(sent)
        await sweep()
        if await delivered(old_id) and await delivered(new_id) and len(sent) == before:
            break
    check("the 90-day-old approval is recorded as delivered", await delivered(old_id))
    check("...without being pushed", not any(f"Old approval {TAG}" in b for b in sent))
    check("the new approval is pushed", any(f"New approval {TAG}" in b for b in sent))
    n = len(sent)
    await sweep()
    check("the next sweep pushes neither again", len(sent) == n, str(len(sent) - n))

    print("\n── the 30-day clear-out ──")
    r = await c.post("/notifications/dismiss", headers=d, json={"item_id": old_id})
    check("the director dismisses the old approval", r.status_code == 200, str(r.status_code))
    long_ago = datetime.now(UTC) - timedelta(days=45)
    async with SessionLocal() as s:
        s.add(PushDelivered(user_id=uid, item_id=f"chat-unread:9{TAG}"))
        await s.flush()
        await s.execute(update(PushDelivered).where(PushDelivered.user_id == uid,
                        PushDelivered.item_id.in_([old_id, new_id, f"chat-unread:9{TAG}"]))
                        .values(sent_at=long_ago))
        await s.execute(update(NotificationDismissed).where(NotificationDismissed.user_id == uid,
                        NotificationDismissed.item_id == old_id).values(created_at=long_ago))
        await s.commit()
        await webpush.prune_ledgers(s)
        await s.commit()
    check("an open approval stays delivered past 30 days", await delivered(old_id) and await delivered(new_id))
    check("...the unread-chat count is cleared", not await delivered(f"chat-unread:9{TAG}"))
    bell = J(await c.get("/notifications", headers=d)).get("items", [])
    check("the dismissed old approval stays out of the bell",
          not any(i["id"] == old_id for i in bell), str([i["id"] for i in bell if TAG in (i.get("body") or "")]))
    n = len(sent)
    await sweep()
    check("...and off the phone", len(sent) == n and not any(f"Old approval {TAG}" in b for b in sent))

    async with SessionLocal() as s:
        await s.execute(delete(ApprovalRequest).where(ApprovalRequest.reason.like(f"%approval {TAG}")))
        await s.execute(delete(PushSubscription).where(PushSubscription.endpoint == f"https://push.invalid/{TAG}"))
        await s.commit()
    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())
