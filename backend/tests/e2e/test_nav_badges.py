"""One request for every sidebar badge — and the same numbers as before.

The shell used to poll eight endpoints on 15–30 second timers for everyone
with the app open, which kept the serverless database awake all day. It now
asks `/nav/badges` once a minute. A badge that disagrees with the list it
opens is worse than a slow one, so this checks each count against the full
endpoint it replaces, for each role that sees it. Also: the push sweeper's
working-hours window, which lets the database sleep at night.
"""
import asyncio, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def length(path, h, **params):
        r = await c.get(path, headers=h, params=params)
        b = J(r)
        return len(b) if isinstance(b, list) else None

    for email, role in (("director@demo.local", "director"), ("finance@demo.local", "finance"),
                        ("manager@demo.local", "manager"), ("sales1@demo.local", "sales"),
                        ("purchasing@demo.local", "purchasing")):
        print(f"\n── {role} ──")
        h = await login(email)
        r = await c.get("/nav/badges", headers=h)
        b = J(r)
        check(f"{role}: one request answers", r.status_code == 200, f"{r.status_code} {str(b)[:150]}")
        want = {
            "chat_unread": J(await c.get("/chat/unread", headers=h)).get("unread"),
            "mentions_unread": await length("/comments/mentions", h, unread_only=True),
        }
        if role in ("director", "finance", "manager"):
            want["pending_invoices"] = await length("/finance/invoices/pending", h)
            want["pending_claims"] = await length("/payments/claims", h, status_eq="pending")
            want["pending_approvals"] = await length("/approvals", h)
            want["pending_documents"] = await length("/approvals/pending-documents", h)
        if role in ("director", "manager", "sales"):
            want["commission_claimable"] = int(
                (J(await c.get("/commissions/summary", headers=h)).get("totals") or {})
                .get("claimable_jobs") or 0)
        if role in ("director", "finance"):
            want["pending_dp"] = await length("/customer-pos", h, status_eq="pending_finance")
        got = {k: b.get(k) for k in want}
        check(f"{role}: every badge equals the list it opens", got == want, f"got {got} want {want}")
        extra = set(b) - set(want)
        check(f"{role}: and no badge for a queue that isn't theirs", not extra, str(extra))

    print("\n── the push sweeper sleeps outside working hours ──")
    from app.services.webpush import seconds_until_active as f
    tz = ZoneInfo("Asia/Jakarta")
    at = lambda s: datetime.fromisoformat(s).replace(tzinfo=tz)
    check("open on a weekday morning", f(at("2026-10-07 10:00")) == 0)
    check("closed at night, until 07:00", f(at("2026-10-07 23:00")) == 8 * 3600)
    check("open Saturday daytime", f(at("2026-10-10 12:00")) == 0)
    check("closed Saturday night through Sunday, until Monday 07:00",
          f(at("2026-10-10 20:00")) == 35 * 3600)
    check("closed at 19:00 sharp", f(at("2026-10-07 19:00")) == 12 * 3600)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())
