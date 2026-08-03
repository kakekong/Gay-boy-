"""Cross-department chat by request instead of a flat refusal.

The old rule was a dead end: anyone below director/manager/HR simply could not
start a conversation with another department. The intent is right — the
director wants to see cross-team traffic — but a blocked conversation doesn't
stop happening, it just moves to WhatsApp where nobody can oversee it at all.

So it becomes a request. What has to hold:

* Approving actually **opens the conversation**, and both sides can then use it
  without asking again — the gate is about starting one.
* Rejecting opens nothing, and the requester can see that it was refused.
* Nobody can spam the queue with the same request twice.
* A conversation that never needed approval still opens immediately, so the
  button never claims to have asked when it just opened a chat.
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
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local")
    tag = uuid.uuid4().hex[:5]

    # Fresh people, so leftovers from other drivers can't have opened a DM
    # between them already.
    async def mkuser(name, role):
        email = f"{name}-{tag}@demo.local"
        J(await c.post("/users", headers=d, json={
            "email": email, "full_name": f"{name.title()} {tag}",
            "role": role, "password": "test-pass-123"}))
        return email, await login(c, email)

    s_email, sales = await mkuser("xsales", "sales")
    f_email, fin = await mkuser("xfin", "finance")
    s2_email, sales2 = await mkuser("xsales2", "sales")

    ids = {u["full_name"]: u["id"] for u in J(await c.get("/chat/contacts", headers=d))}
    fin_id = ids[f"Xfin {tag}"]
    sales2_id = ids[f"Xsales2 {tag}"]

    # ── 1. same department needs no approval ─────────────────────────────────
    r = J(await c.post("/chat/cross-dept-request", headers=sales,
                       json={"user_id": sales2_id}))
    check("a same-department chat opens straight away", r.get("already_open") is True, str(r))
    check("...and hands back the channel", bool(r.get("channel_id")), str(r))

    # ── 2. crossing departments is refused, but points somewhere ─────────────
    r = await c.post(f"/chat/dm/{fin_id}", headers=sales)
    check("opening a cross-department DM directly is still refused",
          r.status_code == 403, str(r.status_code))
    check("...and the message tells you to ask the director",
          "director" in r.text.lower(), r.text[:160])

    # ── 3. the request ───────────────────────────────────────────────────────
    r = await c.post("/chat/cross-dept-request", headers=sales,
                     json={"user_id": fin_id, "reason": "need the payment status"})
    check("sales can ask for the conversation", r.status_code == 200, J(r))
    check("...and it is not open yet", J(r).get("already_open") is False, str(J(r)))
    req_id = J(r).get("approval_request_id")

    r2 = await c.post("/chat/cross-dept-request", headers=sales, json={"user_id": fin_id})
    check("asking twice is refused", r2.status_code == 409, str(r2.status_code))

    mine = J(await c.get("/chat/cross-dept-requests", headers=sales))
    check("the requester can see it pending",
          any(x["status"] == "pending" and x["with_user_id"] == fin_id for x in mine),
          str(mine)[:200])

    q = J(await c.get("/approvals", headers=d))
    row = [a for a in q if str(a.get("id")) == str(req_id)] if isinstance(q, list) else []
    check("it lands in the director's queue", len(row) == 1, str(len(row)))
    check("...naming both people and the reason",
          all(w in (row[0].get("reason") or "") for w in ("Xsales", "Xfin", "payment status"))
          if row else False, str(row[0].get("reason") if row else None))

    # Still nothing open while it waits.
    ch = J(await c.get("/chat/channels", headers=sales))
    check("no conversation exists while it waits",
          not any(f"Xfin {tag}" == (x.get("title") or "") for x in ch), str(len(ch)))

    # ── 4. approving opens it ────────────────────────────────────────────────
    r = await c.post(f"/approvals/{req_id}/approve", headers=d)
    check("the director approves it", r.status_code == 200, J(r))
    check("...and the response says a channel was opened",
          bool((J(r).get("applied") or {}).get("channel_id")), str(J(r))[:200])

    ch = J(await c.get("/chat/channels", headers=sales))
    opened = [x for x in ch if (x.get("title") or "") == f"Xfin {tag}"]
    check("the conversation is now in the requester's list", len(opened) == 1, str(len(opened)))
    if opened:
        cid = opened[0]["id"]
        r = await c.post(f"/chat/channels/{cid}/messages", headers=sales,
                         json={"body": f"hello from sales [{tag}]"})
        check("the requester can actually message in it", r.status_code == 201, J(r))
        msgs = J(await c.get(f"/chat/channels/{cid}/messages", headers=fin))
        check("and the other side sees it",
              any(f"hello from sales [{tag}]" == m["body"] for m in msgs), str(msgs)[:160])
        # The gate is about *starting* — now it exists, no more asking.
        r = await c.post(f"/chat/dm/{fin_id}", headers=sales)
        check("reopening it needs no further approval", r.status_code == 200, J(r))

    mine = J(await c.get("/chat/cross-dept-requests", headers=sales))
    check("the requester sees it approved",
          any(x["with_user_id"] == fin_id and x["status"] == "approved" for x in mine),
          str(mine)[:200])

    # ── 5. rejection opens nothing ───────────────────────────────────────────
    a_email, adm = await mkuser("xadm", "admin")
    adm_id = {u["full_name"]: u["id"]
              for u in J(await c.get("/chat/contacts", headers=d))}[f"Xadm {tag}"]
    r = J(await c.post("/chat/cross-dept-request", headers=sales,
                       json={"user_id": adm_id, "reason": "no"}))
    rej_id = r.get("approval_request_id")
    check("a second request can be raised for a different person", bool(rej_id), str(r))
    await c.post(f"/approvals/{rej_id}/reject", headers=d, params={"notes": "use the group"})
    ch = J(await c.get("/chat/channels", headers=sales))
    check("a rejected request opens no conversation",
          not any((x.get("title") or "") == f"Xadm {tag}" for x in ch),
          str([x.get("title") for x in ch])[:160])
    mine = J(await c.get("/chat/cross-dept-requests", headers=sales))
    check("the requester sees it was refused",
          any(x["with_user_id"] == adm_id and x["status"] == "rejected" for x in mine),
          str(mine)[:200])
    check("...with the director's note",
          any("use the group" in (x.get("decision_notes") or "") for x in mine),
          str(mine)[:240])

    # And asking again after a refusal is allowed — circumstances change.
    r = await c.post("/chat/cross-dept-request", headers=sales, json={"user_id": adm_id})
    check("you may ask again after a refusal", r.status_code == 200, J(r))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())
