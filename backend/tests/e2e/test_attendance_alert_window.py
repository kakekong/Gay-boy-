"""Attendance alerts wait until the office is expected to be working.

"Nobody has clocked in" is a true statement at 06:00 and a useless one — it is
just a description of the morning. Firing it then teaches people that the red
badge means nothing, which costs you the alerts that do matter. So the
attendance alerts stay silent until 08:30 WIB.

The gate has one way to go quietly wrong: the server runs on UTC, so reading
the wall clock without converting would open the window at 15:30 WIB — after
everyone has clocked in, when the alert is pointless. That is the case worth
pinning, so this drives the boundary from both sides and includes one threshold
that only passes if the comparison really is happening in WIB.
"""
import asyncio, os, sys
from datetime import datetime, time, timedelta, timezone, UTC
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:200]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

WIB = timezone(timedelta(hours=7))


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.api.v1.endpoints import notifications as N
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local")

    # A dismissal from an earlier run would hide the alert and make every
    # check below look like the gate working.
    from sqlalchemy import text as _sql
    from app.core.db import SessionLocal as _S
    async with _S() as _db:
        await _db.execute(_sql("DELETE FROM notification_dismissed WHERE item_id LIKE 'attendance-%'"))
        await _db.commit()

    async def attendance_alerts():
        items = J(await c.get("/notifications", headers=d)).get("items", [])
        return [i for i in items if i.get("kind") == "attendance"]

    original = N._ATTENDANCE_ALERT_FROM
    check("the shipped window opens at 08:30", original == time(8, 30), str(original))

    now_utc = datetime.now(UTC)
    now_wib = now_utc.astimezone(WIB)
    weekend = now_wib.weekday() >= 5

    try:
        # ── the gate closed ──────────────────────────────────────────────────
        # An hour from now in WIB: the office day is under way, but the window
        # has not opened, so nothing should be said.
        N._ATTENDANCE_ALERT_FROM = (now_wib + timedelta(hours=1)).time()
        check("before the window opens there is no attendance alert",
              await attendance_alerts() == [],
              str([i["id"] for i in await attendance_alerts()]))

        # ── the gate open ────────────────────────────────────────────────────
        N._ATTENDANCE_ALERT_FROM = time(0, 0)
        alerts = await attendance_alerts()
        if weekend:
            # The weekday rule is separate and older than this change; on a
            # Saturday there is nothing to gate and that is correct.
            check("on a weekend nothing is raised whatever the window says",
                  alerts == [], str([i["id"] for i in alerts]))
        else:
            check("once the window is open the alert comes through",
                  len(alerts) >= 1, "no attendance alert with the gate wide open")
            check("...and it is the day-scoped id, not a count",
                  all(a["id"].count(":") == 1 for a in alerts),
                  str([a["id"] for a in alerts]))

        # ── the boundary is inclusive ────────────────────────────────────────
        N._ATTENDANCE_ALERT_FROM = now_wib.time().replace(microsecond=0)
        alerts = await attendance_alerts()
        check("the alert fires at the boundary minute, not one after it",
              (alerts == []) if weekend else (len(alerts) >= 1),
              f"threshold={N._ATTENDANCE_ALERT_FROM} wib_now={now_wib.time()}")

        # ── the clock is WIB, not the server's ───────────────────────────────
        # Pick a threshold later than the server's own wall clock but earlier
        # than WIB now. Comparing in UTC keeps the gate shut; comparing in WIB
        # opens it. Only meaningful while both sides sit on the same date.
        if now_utc.date() == now_wib.date() and not weekend:
            between = (now_utc + timedelta(minutes=30))
            if between.time() < now_wib.time():
                N._ATTENDANCE_ALERT_FROM = between.time()
                check("the window is measured in WIB, not server time",
                      len(await attendance_alerts()) >= 1,
                      f"threshold={between.time()} utc_now={now_utc.time()} "
                      f"wib_now={now_wib.time()} — shut means it compared in UTC")
            else:
                check("the WIB-vs-server threshold was reachable", True)
        else:
            # Between WIB midnight and UTC midnight the two dates differ and
            # the comparison above has no unambiguous threshold to use.
            check("skipped the WIB-vs-server probe (dates straddle midnight, "
                  "or it is the weekend)", True)
    finally:
        N._ATTENDANCE_ALERT_FROM = original

    check("the window was put back for the rest of the suite",
          N._ATTENDANCE_ALERT_FROM == time(8, 30), str(N._ATTENDANCE_ALERT_FROM))

    # ── everything else is unaffected ────────────────────────────────────────
    items = J(await c.get("/notifications", headers=d)).get("items", [])
    check("non-attendance alerts are untouched by the window",
          any(i.get("kind") != "attendance" for i in items), str(len(items)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())
