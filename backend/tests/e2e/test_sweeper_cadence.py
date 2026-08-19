"""The background sweeper must not keep the database awake around the clock.

What went wrong: the web-push sweeper woke every 90 seconds, forever, from
the moment the API booted. Each tick opened a session, took an advisory
lock, ran the notification aggregator for every subscribed user and issued
two DELETEs — and it did all of that whether or not a single device was
subscribed, and whether or not anybody was using the app.

A serverless Postgres bills for compute time and only suspends after some
minutes of quiet. A query every 90 seconds means it never suspends: the
database is billed 24 hours a day for an app that gets used in office hours
by a handful of people. That is what emptied the month's compute allowance
and put "Your account or project has exceeded the compute time quota" on the
login screen, which is a total outage — nobody can sign in, because signing
in is a database query.

So the cadence is now a setting with a slow default, it backs off further
when nothing is subscribed, the ledger prune runs once a day instead of
every tick, and it can be switched off entirely.

This measures the thing that costs money — statements issued and seconds
slept — rather than trusting the constants.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))


class Stop(Exception):
    """Ends the loop after we have watched enough of it."""


async def run_loop(ticks: int, **kw):
    """Run the sweeper for `ticks` naps, counting SQL as it goes.

    `asyncio.sleep` is replaced so the test doesn't actually wait a quarter
    of an hour — the durations it was asked for are the measurement.
    """
    from sqlalchemy import event
    from app.core.db import engine
    from app.services import webpush

    naps: list[float] = []
    sql: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _seen(conn, cursor, statement, params, context, many):
        sql.append(" ".join(statement.split())[:90])

    real_sleep = asyncio.sleep

    async def fake_sleep(sec, *a, **k):
        naps.append(sec)
        if len(naps) > ticks:
            raise Stop
        await real_sleep(0)

    asyncio.sleep = fake_sleep
    try:
        await webpush.sweeper_loop(**kw)
    except Stop:
        pass
    finally:
        asyncio.sleep = real_sleep
        event.remove(engine.sync_engine, "before_cursor_execute", _seen)
    return naps, sql


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.models.push import PushSubscription
    from app.models.user import User
    from sqlalchemy import delete, select

    print("\n── the default cadence ──")
    check("the sweeper no longer runs on a 90-second timer",
          settings.WEBPUSH_SWEEP_SECONDS >= 300,
          f"{settings.WEBPUSH_SWEEP_SECONDS}s")
    check("...and idles slower still when nothing is subscribed",
          settings.WEBPUSH_IDLE_SECONDS >= settings.WEBPUSH_SWEEP_SECONDS,
          f"{settings.WEBPUSH_IDLE_SECONDS}s vs {settings.WEBPUSH_SWEEP_SECONDS}s")
    per_day = 86_400 / settings.WEBPUSH_SWEEP_SECONDS
    check("...which is under a hundred wake-ups a day, not a thousand",
          per_day <= 100, f"{per_day:.0f}/day")

    # ══ nothing subscribed ═══════════════════════════════════════════════════
    async with SessionLocal() as db:
        await db.execute(delete(PushSubscription))
        await db.commit()

    print("\n── with no device subscribed ──")
    naps, sql = await run_loop(2, interval=900, idle_interval=3600)
    check("it waits for boot to finish before the first tick", naps[0] == 15,
          str(naps[:1]))
    check("...then backs off to the idle interval", naps[1] == 3600,
          str(naps))
    joined = " | ".join(sql).lower()
    check("...having taken the lock and counted subscriptions",
          "pg_try_advisory_lock" in joined and "count(*)" in joined,
          joined[:200])
    check("...and released it", "pg_advisory_unlock" in joined, joined[:200])
    check("...without running the aggregator for anybody",
          "quotations" not in joined and "price_requests" not in joined,
          joined[:300])
    first_tick = len(sql)

    print("\n── the prune ──")
    check("the first tick sweeps the 30-day ledgers",
          "push_delivered" in joined and "notification_dismissed" in joined,
          joined[:300])
    naps2, sql2 = await run_loop(3, interval=900, idle_interval=3600)
    second_tick = [s for s in sql2 if "delete" in s.lower()]
    # Two ticks in this run; only the first may prune, and it does because
    # the loop is fresh. What matters is that the second one does not.
    check("...but a later tick in the same run does not prune again",
          len(second_tick) <= 2, str(second_tick))
    check("...so a quiet tick is a handful of statements, not a page of them",
          first_tick <= 8, f"{first_tick} statements: {joined[:200]}")

    # ══ a subscribed device ══════════════════════════════════════════════════
    print("\n── with a device subscribed ──")
    async with SessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.is_active.is_(True)).limit(1))
        db.add(PushSubscription(
            user_id=uid, endpoint=f"https://push.example/{uuid.uuid4().hex}",
            p256dh="x" * 20, auth="y" * 10, user_agent="test"))
        await db.commit()
    naps, sql = await run_loop(2, interval=900, idle_interval=3600)
    check("it drops back to the working cadence", naps[1] == 900, str(naps))
    check("...and does run the aggregator now",
          any("quotation" in s.lower() or "invoice" in s.lower() for s in sql),
          " | ".join(sql)[:200])
    async with SessionLocal() as db:
        await db.execute(delete(PushSubscription))
        await db.commit()

    # ══ the off switch and the guard rail ════════════════════════════════════
    print("\n── switched off ──")
    naps, sql = await run_loop(2, interval=0)
    check("interval 0 stops the sweeper dead", naps == [] and sql == [],
          f"{naps} / {len(sql)} statements")

    print("\n── a misconfigured idle interval ──")
    naps, sql = await run_loop(2, interval=900, idle_interval=60)
    check("an idle interval shorter than the working one is clamped, "
          "not obeyed", naps[1] == 900, str(naps))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())
