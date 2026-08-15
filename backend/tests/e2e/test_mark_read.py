"""Marking a section's alerts as read from the sidebar badge.

The bell already had an X per row and a Clear all. Neither helps with the thing
people actually complain about: a red `Attendance 2` sitting in the sidebar.
Clearing it meant opening the bell and finding those two rows among a dozen
others, so in practice the badge just stayed there being ignored — which is how
a notification system stops working.

The badge itself now clears its own alerts, which needs the dismiss endpoint to
take a batch. What has to hold:

* One request clears the whole set. Dismissing them one call at a time would
  make the badge count down on screen, and a half-failed sequence would leave
  it stuck at an arbitrary number.
* It is per user. One person clearing their own badge must not clear anyone
  else's — these are the same alert ids for everybody.
* Partly-stale input is fine. The sidebar sends the ids it was showing; by the
  time the request lands one may have resolved on its own, and that is not an
  error.
* Only what was asked for goes. Everything else stays in the bell.
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


def under(items, prefix):
    """The ids the sidebar would count under a nav path — same rule it uses."""
    return [i["id"] for i in items
            if (i.get("link") or "") == prefix
            or (i.get("link") or "").startswith(prefix + "/")
            or (i.get("link") or "").startswith(prefix + "?")]


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local")
    tag = uuid.uuid4().hex[:5]

    # A second decision-maker who sees the same alerts, to prove dismissals
    # do not leak between people.
    other_email = f"mgr2-{tag}@demo.local"
    J(await c.post("/users", headers=d, json={
        "email": other_email, "full_name": f"Manager Two {tag}",
        "role": "manager", "password": "test-pass-123"}))
    m = await login(c, other_email)

    # This driver dismisses alerts that are day- or state-scoped, so a second
    # run the same day would otherwise start from its own leftovers.
    from sqlalchemy import text as _sql
    from app.core.db import SessionLocal as _S
    async with _S() as _db:
        await _db.execute(_sql("DELETE FROM notification_dismissed"))
        await _db.commit()

    before = J(await c.get("/notifications", headers=d))
    items = before.get("items", [])
    check("the director has alerts to work with", len(items) >= 3, str(len(items)))

    # Attendance is the section this was written against, but that alert is
    # weekdays-only by design — so on a Saturday the driver was asserting
    # against a rule the product deliberately does not apply. What is being
    # tested is "one request clears a section", not which section, so pick one
    # that has something in it.
    section = next((p for p in ("/attendance", "/approvals", "/price-requests",
                                "/projects", "/quotations", "/chat")
                    if under(items, p)), None)
    check("some of them sit under one section", section is not None,
          str([i.get("link") for i in items])[:200])
    att = under(items, section) if section else []

    # What the other manager sees BEFORE the director clears anything. Read
    # here rather than compared against the director's own list: the two do
    # not see the same approvals (a manager only gets the ones routed to
    # them), so "same length" was only ever true by luck of which section
    # came up.
    theirs_before = under(J(await c.get("/notifications", headers=m)).get("items", []),
                          section)

    # ── 1. one request clears the whole section ──────────────────────────────
    r = await c.post("/notifications/dismiss", headers=d, json={"item_ids": att})
    check("the section can be marked read in one call", r.status_code == 200, J(r))
    check("...and the response says how many went", J(r).get("dismissed") == len(att),
          str(J(r)))

    after = J(await c.get("/notifications", headers=d))
    left = after.get("items", [])
    check("the section's badge is now empty", under(left, section) == [],
          str(under(left, section)))
    check("...and nothing else was taken with it",
          len(left) == len(items) - len(att), f"{len(items)} - {len(att)} != {len(left)}")
    check("the total count agrees with the list",
          after.get("counts", {}).get("total") == len(left), str(after.get("counts")))

    # ── 2. it is per person ──────────────────────────────────────────────────
    theirs = J(await c.get("/notifications", headers=m))
    check("the other manager's own list is untouched by it",
          under(theirs.get("items", []), section) == theirs_before,
          f"{under(theirs.get('items', []), section)} vs {theirs_before}")

    # ── 3. stale and repeat input ────────────────────────────────────────────
    r = await c.post("/notifications/dismiss", headers=d, json={"item_ids": att})
    check("marking the same section read again is harmless", r.status_code == 200, J(r))
    r = await c.post("/notifications/dismiss", headers=d, json={
        "item_ids": att + [f"gone-{tag}:resolved-before-we-asked"]})
    check("an id that already resolved is not an error", r.status_code == 200, J(r))
    check("duplicates are counted once",
          J(await c.post("/notifications/dismiss", headers=d,
                         json={"item_ids": ["dup-x", "dup-x", "dup-y"]})).get("dismissed") == 2,
          "expected 2")

    # ── 4. the old single-item shape still works ─────────────────────────────
    rest = J(await c.get("/notifications", headers=d)).get("items", [])
    if rest:
        one = rest[0]["id"]
        r = await c.post("/notifications/dismiss", headers=d, json={"item_id": one})
        check("the X button on a single row still works", r.status_code == 200, J(r))
        now = J(await c.get("/notifications", headers=d)).get("items", [])
        check("...and that row is gone", all(i["id"] != one for i in now), str(len(now)))

    # ── 5. an empty ask is refused rather than silently doing nothing ────────
    r = await c.post("/notifications/dismiss", headers=d, json={"item_ids": []})
    check("an empty list is refused", r.status_code == 400, str(r.status_code))
    r = await c.post("/notifications/dismiss", headers=d, json={})
    check("...and so is a request naming nothing", r.status_code == 400, str(r.status_code))

    # ── 6. it needs a login ──────────────────────────────────────────────────
    r = await c.post("/notifications/dismiss", json={"item_ids": ["x"]})
    check("an anonymous caller cannot clear anyone's alerts",
          r.status_code in (401, 403), str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())
