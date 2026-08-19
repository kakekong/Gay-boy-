"""Two small fixes that both bite in daily use.

**A lost deal must say why.** The composer already insisted on a reason, but
the API accepted an empty one — so anything not going through that screen
could close a deal with no explanation, and the lost-deal report is built
entirely from those explanations.

**A dismissed alert must stay dismissed.** Some notification ids embedded a
live count, so the moment the count moved the "same" alert came back as a new
id and the red badge in the sidebar reappeared. The attendance one was the
worst of them: dismiss "5 not clocked in", somebody clocks in, and it returns
as "4 not clocked in" — all morning, every morning.
"""
import asyncio, os, sys, uuid
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=60)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    pu = await login(c, "purchasing@demo.local")
    tag = uuid.uuid4().hex[:5]

    # Undo this driver's own dismissal from an earlier run. There is no
    # un-dismiss endpoint, by design — and the fix under test is precisely that
    # the id is day-scoped, so a second run on the same day would otherwise
    # find the alert already dismissed and report a fixture artefact as a bug.
    from sqlalchemy import text as _sql
    from app.core.db import SessionLocal as _S
    async with _S() as _db:
        await _db.execute(_sql("DELETE FROM notification_dismissed "
                               "WHERE item_id LIKE 'attendance-%'"))
        await _db.commit()

    async def a_quotation():
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Kalah {tag}-{uuid.uuid4().hex[:3]}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": "Gearbox", "qty": 1, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=pu,
                     json={"items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": 9_000_000, "basis": "unit"}]})
        return J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]

    # ── 1. marking lost needs a real reason ──────────────────────────────────
    q = await a_quotation()
    for label, reason in (("empty", ""), ("whitespace", "   "), ("too short", "x")):
        r = await c.post(f"/quotations/{q}/lost", headers=s1, params={"reason": reason})
        check(f"a {label} reason is rejected", r.status_code == 400, str(r.status_code))
    check("...and the quotation is still open",
          J(await c.get(f"/quotations/{q}", headers=s1)).get("status") != "lost",
          str(J(await c.get(f"/quotations/{q}", headers=s1)).get("status")))

    r = await c.post(f"/quotations/{q}/lost", headers=s1,
                     params={"reason": "Lost on price — competitor 12% lower"})
    check("a real reason is accepted", r.status_code == 200, J(r))
    got = J(await c.get(f"/quotations/{q}", headers=s1))
    check("the quotation is lost", got.get("status") == "lost", str(got.get("status")))
    check("the reason is kept on the record",
          "competitor 12% lower" in (got.get("notes") or ""), str(got.get("notes"))[:120])

    # ── 2. a dismissed alert stays dismissed ─────────────────────────────────
    # The attendance alert is the one that misbehaved: its id carried the count
    # of people not yet clocked in.
    notif = J(await c.get("/notifications", headers=d))
    items = notif.get("items", []) if isinstance(notif, dict) else []
    att = [i for i in items if i.get("kind") == "attendance"]
    # "Who has not clocked in" is a weekday question, and not one worth asking
    # before the office is expected to be working — the product stays silent
    # at a weekend and until 08:30 WIB (see test_attendance_alert_window).
    # Asserting the alert exists on a Saturday, or at seven in the morning,
    # was testing a rule nobody wrote.
    import datetime as _dt
    _wib = _dt.timezone(_dt.timedelta(hours=7))
    _now = _dt.datetime.now(_dt.UTC).astimezone(_wib)
    open_hours = _now.date().weekday() < 5 and _now.time() >= _dt.time(8, 30)
    if open_hours:
        check("the director has an attendance alert to dismiss", len(att) >= 1,
              str([i.get("kind") for i in items])[:160])
    else:
        check("no attendance nag outside working hours — that is the rule",
              not att, f"{_now:%a %H:%M} WIB: " + str([i.get("id") for i in att]))

    if att:
        target = next((i for i in att if i["id"].startswith("attendance-missing")), att[0])
        check("its id carries no live count — just the day",
              target["id"].count(":") == 1 and target["id"].split(":")[1][:2] == "20",
              target["id"])

        r = await c.post("/notifications/dismiss", headers=d, json={"item_id": target["id"]})
        check("dismissing it works", r.status_code in (200, 201, 204), str(r.status_code))
        again = J(await c.get("/notifications", headers=d))
        check("it is gone from the bell",
              not [i for i in again.get("items", []) if i["id"] == target["id"]],
              str([i["id"] for i in again.get("items", [])])[:160])

        # Clear the rest of the attendance alerts too — the user story is
        # "I cleared the badge", not "I cleared one row".
        for i in att:
            if i["id"] != target["id"]:
                await c.post("/notifications/dismiss", headers=d, json={"item_id": i["id"]})

        # Now move the number the old id used to embed: clock somebody in. The
        # alert must NOT come back — that regression is the whole bug.
        await c.post("/attendance/clock-in", headers=s1, json={"note": "probe"})
        after = J(await c.get("/notifications", headers=d))
        still_gone = not [i for i in after.get("items", [])
                          if i.get("kind") == "attendance" and i["id"] == target["id"]]
        check("it stays gone after the count changes", still_gone,
              str([i["id"] for i in after.get("items", []) if i.get("kind") == "attendance"]))
        check("no attendance alert resurfaces under a different id either",
              not [i for i in after.get("items", [])
                   if i.get("kind") == "attendance" and i["id"].startswith("attendance-missing")],
              str([i["id"] for i in after.get("items", []) if i.get("kind") == "attendance"]))

    # The sidebar badge is a count of notification items per link, so an alert
    # that won't stay dismissed is exactly a badge that won't clear.
    final = J(await c.get("/notifications", headers=d))
    links = [i.get("link") for i in final.get("items", [])]
    check("the attendance badge is clear", "/attendance" not in links,
          str(links)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())
