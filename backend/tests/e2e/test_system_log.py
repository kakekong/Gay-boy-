"""The director's system log: every sign-in, failed attempt and sign-out,
and one person's whole history.

* A successful sign-in, a wrong password, an unknown address, a deactivated
  account and a rate-limited burst are each recorded — with who, when, the IP
  and the device — and the caller still gets the same "Invalid credentials".
* Sign out is recorded. "View as" is recorded against the person viewed, with
  the director as the actor.
* Any request stamps "last seen".
* The people list, the filtered sign-in history and a person's timeline
  (sign-ins and changes, interleaved) are the director's alone.
* No password is stored anywhere.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6]
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)

    def ip_headers(ip, ua):
        return {"X-Forwarded-For": ip, "User-Agent": ua}

    async def login(e, pw="test-pass-123", ip="10.1.0.1", ua=WINDOWS):
        return await c.post("/auth/login", json={"email": e, "password": pw},
                            headers=ip_headers(ip, ua))

    def auth(r):
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    d = auth(await login("director@demo.local"))
    s1_email = "sales1@demo.local"

    print("\n── what gets recorded ──")
    r = await login(s1_email, ip=f"10.9.{TAG[:2].__hash__() % 200}.7", ua=IPHONE)
    check("sales signs in", r.status_code == 200, str(r.status_code))
    s1 = auth(r)
    s1_ip = r.request.headers["x-forwarded-for"]
    me = J(await c.get("/auth/me", headers=s1))

    r = await login(s1_email, pw="not-it-" + TAG, ip="10.66.0.1")
    check("a wrong password is refused", r.status_code == 401)
    bad_detail = J(r).get("detail")
    r = await login(f"nobody-{TAG}@demo.local", ip="10.66.0.2")
    check("an unknown address gets the very same answer",
          r.status_code == 401 and J(r).get("detail") == bad_detail, str(J(r)))

    sig = await c.get("/system-log/sign-ins", headers=d, params={"q": me["email"], "limit": 50})
    rows = J(sig)["items"]
    ok = [x for x in rows if x["event"] == "login" and x["ip"] == s1_ip]
    check("the sign-in is on the log with IP and device",
          ok and ok[0]["device"] == "Safari · iPhone" and ok[0]["user_id"] == me["id"]
          and ok[0]["user_name"] == me["full_name"], str(rows[:2])[:300])
    bad = [x for x in rows if x["event"] == "failed" and x["ip"] == "10.66.0.1"]
    check("the wrong password is on it, on that person's account",
          bad and bad[0]["reason"] == "wrong_password" and bad[0]["user_id"] == me["id"],
          str(bad)[:200])
    r = J(await c.get("/system-log/sign-ins", headers=d, params={"q": f"nobody-{TAG}"}))
    check("an attempt on an address that is nobody's is kept, by the address typed",
          r["total"] == 1 and r["items"][0]["reason"] == "unknown_email"
          and r["items"][0]["user_id"] is None, str(r)[:200])
    check("no password is stored, not even the wrong one",
          ("not-it-" + TAG) not in str(J(sig)) and "test-pass-123" not in str(J(sig)))

    print("\n── deactivated accounts and guessing bursts ──")
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.user import User
    email_x = f"leaver-{TAG}@demo.local"
    async with SessionLocal() as s:
        u = User(email=email_x, full_name=f"Leaver {TAG}", role="customer",
                 password_hash=hash_password("leaver-pass-1"), is_active=False)
        s.add(u); await s.commit(); xid = str(u.id)
    r = await login(email_x, pw="leaver-pass-1", ip="10.77.0.1")
    check("a deactivated account cannot get in", r.status_code == 401)
    r = J(await c.get("/system-log/sign-ins", headers=d, params={"q": email_x}))
    check("...and the log says why", r["items"] and r["items"][0]["reason"] == "deactivated"
          and r["items"][0]["user_id"] == xid, str(r)[:200])

    burst_ip = f"10.88.{int(TAG[:2], 16)}.9"
    codes = [(await login(email_x, pw="guess", ip=burst_ip)).status_code for _ in range(6)]
    check("the sixth guess in a minute is blocked", codes[-1] == 429, str(codes))
    r = J(await c.get("/system-log/sign-ins", headers=d,
                      params={"q": burst_ip, "event": "blocked"}))
    check("...and the block is on the log", r["total"] >= 1
          and r["items"][0]["reason"] == "too_many_attempts", str(r)[:200])

    print("\n── sign out, View as, last seen ──")
    r = await c.post("/auth/logout", headers={**s1, "User-Agent": IPHONE})
    check("signing out is accepted", r.status_code == 204, str(r.status_code))
    r = J(await c.get("/system-log/sign-ins", headers=d,
                      params={"q": me["email"], "event": "logout"}))
    check("...and recorded", r["total"] >= 1 and r["items"][0]["user_id"] == me["id"])

    dme = J(await c.get("/auth/me", headers=d))
    r = await c.post(f"/auth/impersonate/{me['id']}", headers=d)
    check("the director views as sales", r.status_code == 200, str(r.status_code))
    r = J(await c.get("/system-log/sign-ins", headers=d,
                      params={"q": me["email"], "event": "view_as"}))
    va = r["items"][0] if r["items"] else {}
    check("...which is on sales' history, with the director as who did it",
          va.get("user_id") == me["id"] and va.get("actor_id") == dme["id"]
          and va.get("actor_name") == dme["full_name"], str(va)[:200])

    people = J(await c.get("/system-log/people", headers=d))
    mine = next((p for p in people if p["id"] == me["id"]), {})
    check("the people list shows last seen and last sign-in",
          mine.get("last_seen_at") and mine.get("last_login_at")
          and mine.get("last_login_device") == "Safari · iPhone", str(mine)[:300])
    check("...with the failed attempts counted", mine.get("failed_30d", 0) >= 1, str(mine)[:300])
    leaver = next((p for p in people if p["id"] == xid), {})
    check("...including deactivated accounts, never seen", leaver.get("is_active") is False
          and leaver.get("last_seen_at") is None and leaver.get("failed_30d", 0) >= 7,
          str(leaver)[:300])

    print("\n── one person's whole history ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Log {TAG}", "industry": "mining"}))
    await c.patch(f"/customers/{cust['id']}", headers=s1, json={"industry": "cement"})
    await c.post("/price-requests", headers=s1, json={"customer_id": str(uuid.uuid4()),
                                                      "items": [{"description": "X", "qty": 1}]})
    tl = J(await c.get("/system-log/timeline", headers=d, params={"user_id": me["id"]}))
    kinds = [x["kind"] for x in tl["items"][:20]]
    acts = [x for x in tl["items"] if x["kind"] == "action"]
    made = next((x for x in acts if x["method"] == "POST" and x["path"] == "/api/v1/customers"), None)
    check("the timeline holds every change they made — even one with no audit entry",
          made is not None and made["status_code"] in (200, 201), str(acts[:3])[:300])
    edit = next((x for x in acts if x["method"] == "PATCH"
                 and x["path"] == f"/api/v1/customers/{cust['id']}"), None)
    check("...and where the audit log has the before/after, it rides on the action",
          edit is not None and any(ch["entity_id"] == cust["id"] and ch["entity"] == "customer"
                                   for ch in edit["changes"]), str(edit)[:300])
    refused = next((x for x in acts if x["path"] == "/api/v1/price-requests"), None)
    check("...a refused request is there too, with its status",
          refused is not None and refused["status_code"] >= 400, str(refused)[:200])
    check("...and their sign-ins, interleaved newest first",
          "sign_in" in kinds and "action" in kinds
          and [x["occurred_at"] for x in tl["items"]]
          == sorted([x["occurred_at"] for x in tl["items"]], reverse=True),
          str(kinds))
    check("...with a total for paging", tl["total"] >= len(tl["items"]))

    r = await c.post(f"/auth/impersonate/{me['id']}", headers=d)
    as_sales = auth(r)
    await c.patch(f"/customers/{cust['id']}", headers=as_sales, json={"industry": "mining"})
    r = J(await c.get("/system-log/actions", headers=d,
                      params={"q": f"customers/{cust['id']}", "limit": 10}))
    va = next((x for x in r["items"] if x["via_id"]), None)
    check("a change made while viewing as sales names the director as who did it",
          va is not None and va["user_id"] == me["id"] and va["via_id"] == dme["id"]
          and va["via_name"] == dme["full_name"], str(r["items"][:2])[:300])
    r = J(await c.get("/system-log/actions", headers=d, params={"failed": "true", "limit": 500}))
    check("the activity feed can show only the refused requests",
          r["items"] and all(x["status_code"] >= 400 for x in r["items"]))
    r = J(await c.get("/system-log/actions", headers=d, params={"user_id": me["id"], "limit": 500}))
    check("...and one person's", r["total"] >= 3
          and all(me["id"] in (x["user_id"], x["via_id"]) for x in r["items"]))
    r = J(await c.get("/system-log/sign-ins", headers=d, params={"limit": 5000}))
    check("token refreshes and sign-ins are not double-counted as actions", not any(
        "/auth/" in x["path"] for x in J(await c.get("/system-log/actions", headers=d,
                                                     params={"q": "/auth/"}))["items"]))

    print("\n── the director's alone ──")
    mgr = auth(await login("manager@demo.local"))
    for path in ("/system-log/people", "/system-log/sign-ins", "/system-log/actions",
                 f"/system-log/timeline?user_id={me['id']}"):
        for who, h in (("sales", s1), ("manager", mgr)):
            r = await c.get(path, headers=h)
            check(f"{who} cannot read {path.split('?')[0]}", r.status_code == 403, str(r.status_code))

    print("\n── filters ──")
    r = J(await c.get("/system-log/sign-ins", headers=d, params={"event": "failed", "limit": 500}))
    check("filtering by event", r["items"] and all(x["event"] == "failed" for x in r["items"]))
    r = J(await c.get("/system-log/sign-ins", headers=d,
                      params={"date_from": "2000-01-01", "date_to": "2000-01-02"}))
    check("a date range with nothing in it is empty", r["total"] == 0, str(r)[:100])
    r = J(await c.get("/system-log/sign-ins", headers=d,
                      params={"user_id": me["id"], "limit": 2}))
    check("paging by user returns the page and the total",
          len(r["items"]) <= 2 and r["total"] >= 3, str(r)[:150])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())
