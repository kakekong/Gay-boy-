"""Discussion access control and @mentions.

Two things are being pinned here.

The hole: /comments never checked the parent document, so any internal login
could read (and post to) any thread by knowing an id — a rival sales rep, or
purchasing, could read the customer name and sell price straight out of a
quotation discussion despite being 403'd on the quotation itself.

The exception: being @-mentioned grants that ONE thread and nothing else. That
is what lets someone pull a colleague into a conversation on a document the
colleague cannot open, without the mention becoming a back door to the
document, its prices, or the customer behind it.
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
    except: return {"_":r.text[:150]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

SECRET = "PT Secret pays 9,000,000 — do not reveal our cost"

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    d=await login(c,"director@demo.local"); s1=await login(c,"sales1@demo.local")
    s2=await login(c,"sales2@demo.local");  pu=await login(c,"purchasing@demo.local")
    hr=await login(c,"hr@demo.local")
    tag=uuid.uuid4().hex[:5]

    # sales1 builds a deal and says something confidential on the quotation
    cust=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Secret {tag}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=s1,json={"customer_id":cust,
        "items":[{"description":"X","qty":1,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=s1)
    await c.post(f"/price-requests/{pr}/price",headers=pu,json={"items":[{"line_no":1,"cost_price":5000000,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=d,json={"items":[{"line_no":1,"sell_price":9000000,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=s1))["id"]

    r=await c.post("/comments",headers=s1,json={"owner_type":"quotation","owner_id":q,"body":SECRET})
    check("owner can post on their own quotation thread", r.status_code==201, J(r))

    # ---------- 1. the hole is closed ----------
    check("owner can read it back",
          (await c.get("/comments",headers=s1,params={"owner_type":"quotation","owner_id":q})).status_code==200)
    r=await c.get("/comments",headers=s2,params={"owner_type":"quotation","owner_id":q})
    check("another sales rep cannot read the thread", r.status_code==403, str(r.status_code))
    check("...and the secret is not in the body", SECRET not in r.text, r.text[:80])
    r=await c.get("/comments",headers=pu,params={"owner_type":"quotation","owner_id":q})
    check("purchasing (customer-blind) cannot read the thread", r.status_code==403, str(r.status_code))
    r=await c.post("/comments",headers=pu,json={"owner_type":"quotation","owner_id":q,"body":"sneaking in"})
    check("purchasing cannot post to it either", r.status_code==403, str(r.status_code))
    r=await c.get("/comments",headers=hr,params={"owner_type":"quotation","owner_id":q})
    check("HR cannot read it", r.status_code==403, str(r.status_code))

    # ---------- 2. the picker offers people who can't see the page ----------
    cands=J(await c.get("/comments/mentionable",headers=s1,
                        params={"owner_type":"quotation","owner_id":q}))
    by_role={x["role"]: x for x in cands}
    check("picker offers colleagues outside the document", "purchasing" in by_role, str(list(by_role)))
    check("...flagged as having no access", by_role.get("purchasing",{}).get("has_access") is False,
          str(by_role.get("purchasing")))
    check("...and the director is flagged as already having access",
          by_role.get("director",{}).get("has_access") is True, str(by_role.get("director")))
    check("picker never offers the portal roles",
          not {"customer","supplier"} & set(by_role), str(list(by_role)))

    # ---------- 3. a mention grants the thread, and only the thread ----------
    pu_id=by_role["purchasing"]["id"]
    r=await c.post("/comments",headers=s1,json={
        "owner_type":"quotation","owner_id":q,
        "body":f"@{by_role['purchasing']['name']} can you check the lead time?",
        "mention_user_ids":[pu_id]})
    check("mentioning purchasing is accepted", r.status_code==201, J(r))
    check("the comment reports who was mentioned",
          len(J(r).get("mentions") or [])==1, str(J(r).get("mentions")))

    r=await c.get("/comments",headers=pu,params={"owner_type":"quotation","owner_id":q})
    check("the mentioned user can NOW read the thread", r.status_code==200, str(r.status_code))
    r2=await c.post("/comments",headers=pu,json={"owner_type":"quotation","owner_id":q,
                                                 "body":"about 6 weeks"})
    check("the mentioned user can reply into the thread", r2.status_code==201, J(r2))

    # The "grants nothing extra" guarantee has to be measured against a role
    # that genuinely cannot reach the document. purchasing/hr/admin can all
    # read the CRM straight off the API today (a separate, pre-existing gap —
    # their sidebar hides it but require_min(SALES) lets every tier-2 role in),
    # so a rival sales rep is the honest subject: 403 on both before and after.
    # Match the demo rep by name, not by role: earlier drivers leave throwaway
    # sales users in the database and picking "the first sales" grabs one of
    # those, then asserts against sales2 — a test artifact that reads exactly
    # like a product bug.
    s2_id=next(x["id"] for x in cands if x["name"]=="Sales Two")
    before_q=(await c.get(f"/quotations/{q}",headers=s2)).status_code
    before_c=(await c.get(f"/customers/{cust}",headers=s2)).status_code
    r=await c.post("/comments",headers=s1,json={
        "owner_type":"quotation","owner_id":q,
        "body":"@colleague please weigh in","mention_user_ids":[s2_id]})
    check("a second rep can be mentioned in", r.status_code==201, J(r))
    check("the mentioned rep can now read the thread",
          (await c.get("/comments",headers=s2,params={"owner_type":"quotation","owner_id":q})).status_code==200)
    check("the mention did NOT grant the quotation itself",
          (await c.get(f"/quotations/{q}",headers=s2)).status_code in (403,404),
          f"was {before_q}, now {(await c.get(f'/quotations/{q}',headers=s2)).status_code}")
    check("the mention did NOT grant the customer record",
          (await c.get(f"/customers/{cust}",headers=s2)).status_code in (403,404),
          f"was {before_c}, now {(await c.get(f'/customers/{cust}',headers=s2)).status_code}")

    # a mention on THIS thread must not open a different one
    q2=J(await c.post("/quotations",headers=d,json={"customer_id":cust,
        "items":[{"description":"Y","qty":1,"unit_price":100}]})).get("id")
    if q2:
        await c.post("/comments",headers=d,json={"owner_type":"quotation","owner_id":q2,"body":"other deal"})
        check("being mentioned on one thread does not open another",
              (await c.get("/comments",headers=pu,
                           params={"owner_type":"quotation","owner_id":q2})).status_code==403)

    # ---------- 4. the mentions inbox ----------
    inbox=J(await c.get("/comments/mentions",headers=pu))
    mine=[m for m in inbox if str(m.get("owner_id"))==str(q)]
    check("the mention appears in the inbox", len(mine)==1, str(len(mine)))
    if mine:
        m=mine[0]
        check("the inbox carries the message body", "lead time" in (m.get("body") or ""), m.get("body"))
        check("the inbox names the document", bool(m.get("document")), str(m.get("document")))
        check("the inbox does NOT leak the customer name",
              "PT Secret" not in str(m), str(m)[:120])
        check("it starts unread", m.get("read_at") is None, str(m.get("read_at")))
        unread=J(await c.get("/comments/mentions",headers=pu,params={"unread_only":True}))
        check("unread filter finds it", any(str(x["id"])==m["id"] for x in unread))
        r=await c.post(f"/comments/mentions/{m['id']}/read",headers=pu)
        check("marking read works", r.status_code==200, J(r))
        unread=J(await c.get("/comments/mentions",headers=pu,params={"unread_only":True}))
        check("it leaves the unread list", not any(str(x["id"])==m["id"] for x in unread))

    # nobody else's mentions are visible. HR is the subject here: sales2 was
    # deliberately mentioned above, so their inbox SHOULD carry this thread.
    check("the inbox is per-user", not [m for m in J(await c.get("/comments/mentions",headers=hr))
                                        if str(m.get("owner_id"))==str(q)])
    check("a mentioned colleague does see it in theirs",
          any(str(m.get("owner_id"))==str(q) for m in J(await c.get("/comments/mentions",headers=s2))))

    # ---------- 5. the bell ----------
    r=await c.post("/comments",headers=s1,json={
        "owner_type":"quotation","owner_id":q,
        "body":f"@{by_role['purchasing']['name']} one more thing",
        "mention_user_ids":[pu_id]})
    notif=J(await c.get("/notifications",headers=pu))
    items=notif.get("items",[]) if isinstance(notif,dict) else notif
    mentions=[i for i in items if i.get("kind")=="mention"]
    check("an unread mention raises a bell item", len(mentions)>=1, str(len(mentions)))
    if mentions:
        check("it is high severity", mentions[0]["severity"]=="high", mentions[0]["severity"])
        check("it links to the mentions inbox", mentions[0]["link"]=="/mentions", mentions[0]["link"])
    # sales1 replied last, so a reply from purchasing should show for sales1
    await c.post("/comments",headers=pu,json={"owner_type":"quotation","owner_id":q,"body":"noted"})
    notif=J(await c.get("/notifications",headers=s1))
    items=notif.get("items",[]) if isinstance(notif,dict) else notif
    check("a reply on your thread raises a discussion bell item",
          any(i.get("kind")=="discussion" for i in items),
          str([i.get("kind") for i in items][:8]))
    notif=J(await c.get("/notifications",headers=hr))
    items=notif.get("items",[]) if isinstance(notif,dict) else notif
    check("someone with no part in the thread gets nothing",
          not any(i.get("kind") in ("discussion","mention") for i in items),
          str([i.get("kind") for i in items][:8]))

    # ---------- 6. the two new owner types ----------
    for owner_type, oid in (("project", None), ("invoice", None)):
        pass
    proj=None
    cpo=J(await c.post("/customer-pos",headers=s1,json={"customer_id":cust,"quotation_id":q,
        "number":f"PO-MEN-{tag}","items":[{"description":"X","qty":1,"unit_price":9000000}],
        "is_downpayment":False}))
    if cpo.get("id"):
        await c.post(f"/quotations/{q}/won",headers=d)
        proj=J(await c.post(f"/customer-pos/{cpo['id']}/approve",headers=d,json={"notes":""})).get("project_id")
    if proj:
        r=await c.post("/comments",headers=s1,json={"owner_type":"project","owner_id":proj,
                                                    "body":"kick-off next Monday"})
        check("project threads accept comments", r.status_code==201, J(r))
        check("admin can read a project thread",
              (await c.get("/comments",headers=await login(c,"admin@demo.local"),
                           params={"owner_type":"project","owner_id":proj})).status_code==200)
    r=await c.post("/comments",headers=s1,json={"owner_type":"employee","owner_id":str(uuid.uuid4()),
                                                "body":"nope"})
    check("an owner type outside the allowed set is rejected", r.status_code==400, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)

asyncio.run(main())
