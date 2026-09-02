"""Talking to a colleague is not a decision.

Cross-department chat used to need the director's approval: anyone below
director/manager/HR filed a request and waited before they could message
someone on another team. That was a request, then a queue, then an approval,
for a conversation.

It was already the second version of this rule. The first was a flat refusal;
that got replaced by request-and-approve because a blocked conversation does
not stop happening, it moves to WhatsApp where nobody can oversee it. The same
argument finishes the job: the work crosses those lines constantly — purchasing
asks sales what the customer actually wants, finance asks admin where an
invoice went — and a queue in front of it just moves the conversation off the
system again.

So it opens. What has to still hold:

* **Oversight, not permission.** The director still sees cross-department
  channels and can read them silently. Knowing what was said is the part worth
  keeping; gating whether it may be said was not.
* **Externals stay out.** A customer or supplier portal login must never reach
  an internal person's inbox. That is not governance, it is the tenancy
  boundary, and it is enforced in the policy as well as by the router.
* **The old asking endpoint still answers**, because the button that calls it
  is still on somebody's screen until the frontend catches up — it just opens
  the conversation now instead of filing anything.
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
    except Exception: return {"_":r.text[:200]}
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
        # The person goes on the employee register first; the login is
        # created against that record.
        emp = J(await c.post("/employees", headers=d, json={
            "full_name": f"{name.title()} {tag}", "intended_role": role}))
        J(await c.post("/users", headers=d, json={
            "email": email, "full_name": f"{name.title()} {tag}",
            "role": role, "employee_id": emp["id"], "password": "test-pass-123"}))
        return email, await login(c, email)

    s_email, sales = await mkuser("xsales", "sales")
    f_email, fin = await mkuser("xfin", "finance")
    s2_email, sales2 = await mkuser("xsales2", "sales")
    # Deliberately the existing demo account rather than a fresh one: a
    # second user with the same role pollutes role-keyed pickers in other
    # drivers sharing this database.
    pur = await login(c, "purchasing@demo.local")

    ids = {u["full_name"]: u["id"] for u in J(await c.get("/chat/contacts", headers=d))}
    fin_id = ids[f"Xfin {tag}"]
    sales2_id = ids[f"Xsales2 {tag}"]
    pur_id = next(u["id"] for u in J(await c.get("/chat/contacts", headers=d))
                  if u.get("role") == "purchasing"
                  and u["full_name"] == "Purchasing Demo")
    sales_id = ids[f"Xsales {tag}"]

    # ══ it just opens ════════════════════════════════════════════════════════
    print("\n── a sales rep messages finance ──")
    r = await c.post(f"/chat/dm/{fin_id}", headers=sales)
    check("the conversation opens, with nobody asked", r.status_code == 200,
          f"{r.status_code} {r.text[:160]}")
    chan = J(r).get("id")
    check("...handing back the channel", bool(chan), str(J(r))[:150])

    r = await c.post(f"/chat/channels/{chan}/messages", headers=sales,
                     json={"body": f"invoice status? {tag}"})
    check("...and they can actually say something", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:150])
    rows = J(await c.get(f"/chat/channels/{chan}/messages", headers=fin))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    check("...which the other side reads",
          any(f"invoice status? {tag}" in (m.get("body") or "") for m in rows),
          str(rows)[:200])
    r = await c.post(f"/chat/channels/{chan}/messages", headers=fin,
                     json={"body": f"paid friday {tag}"})
    check("...and answers", r.status_code == 201, f"{r.status_code} {J(r)}"[:150])

    print("\n── every other pairing too ──")
    for who, hdr, target, label in (
        ("purchasing → sales", pur, sales_id, "purchasing to sales"),
        ("sales → purchasing", sales, pur_id, "sales to purchasing"),
        ("finance → purchasing", fin, pur_id, "finance to purchasing"),
    ):
        r = await c.post(f"/chat/dm/{target}", headers=hdr)
        check(f"{who} opens straight away", r.status_code == 200,
              f"{r.status_code} {r.text[:140]}")

    r = await c.post(f"/chat/dm/{sales2_id}", headers=sales)
    check("a same-department chat is unaffected", r.status_code == 200,
          str(r.status_code))

    # ══ the old asking endpoint ══════════════════════════════════════════════
    print("\n── the button that used to file a request ──")
    r = await c.post("/chat/cross-dept-request", headers=sales,
                     json={"user_id": fin_id, "reason": "need the payment status"})
    check("still answers rather than 404ing", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    check("...saying the conversation is open", J(r).get("already_open") is True,
          str(J(r))[:150])
    check("...and pointing at the same channel it already opened",
          J(r).get("channel_id") == chan, f"{J(r).get('channel_id')} vs {chan}")

    pending = J(await c.get("/chat/cross-dept-requests", headers=sales))
    pending = pending if isinstance(pending, list) else pending.get("data", [])
    check("nothing was filed for anybody to decide",
          not [x for x in pending if x.get("status") == "pending"], str(pending)[:200])

    inbox = J(await c.get("/approvals", headers=d))
    inbox = inbox if isinstance(inbox, list) else inbox.get("data", [])
    check("...and the director's queue stays clear of chat requests",
          not [x for x in inbox if x.get("target_type") == "cross_dept_chat"
               and str(x.get("requested_by")) == str(ids.get(f"Xsales {tag}"))],
          str([x.get("target_type") for x in inbox])[:200])

    # ══ what did not change ══════════════════════════════════════════════════
    print("\n── the oversight that was the point ──")
    seen = J(await c.get("/chat/monitor", headers=d))
    seen = seen if isinstance(seen, list) else seen.get("data", [])
    check("the director still sees cross-department channels",
          any(str(x.get("id")) == str(chan) for x in seen), str(seen)[:250])
    r = await c.get(f"/chat/channels/{chan}/messages", headers=d)
    check("...and can read them without joining", r.status_code == 200,
          str(r.status_code))

    print("\n── and the boundary that is not governance ──")
    from app.core.db import SessionLocal
    from app.services.chat_policy import may_start_cross_dept
    check("a customer portal login may never start one",
          may_start_cross_dept("customer") is False)
    check("...nor a supplier one", may_start_cross_dept("supplier") is False)
    check("...while every internal role may",
          all(may_start_cross_dept(r) for r in
              ("sales", "purchasing", "finance", "admin", "hr", "manager",
               "director")))
    r = await c.post(f"/chat/dm/{fin_id}", headers={"Authorization": "Bearer nope"})
    check("an unauthenticated caller gets nowhere", r.status_code in (401, 403),
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


asyncio.run(main())
