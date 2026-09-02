"""Moving an account from one sales rep to another.

Asked for: directors should be able to change which sales rep is in charge of
which customer. People leave, people are hired, territories are split, and an
import lands dozens of customers with nobody on them.

The interesting part is not setting a column. `Customer.sales_pic_id` is what
the whole CRM scopes on, so changing it decides who can *see* the account —
and the account's open documents carry their own copy of that rep. Set only
the customer and the new rep inherits a company whose live quotation they
cannot open, while the departed rep keeps it. So this driver watches all four
things at once:

  the account moves        the new rep can open it, the old one cannot
  the whole file moves     every price request and quotation on the account,
                           closed ones included — ownership is what grants
                           the right to edit, and an inherited account whose
                           history is read-only is half an account
  it is written down       the customer's timeline and the new rep's bell,
                           and the audit log still names who closed what

And the door it closes: reassignment used to be an ordinary field on the
customer PATCH, which meant any sales rep could quietly hand their own account
to somebody else, or to nobody. That is now the director's alone, and the
refusals are checked here rather than assumed.
"""
import asyncio, os, sys, uuid
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
                          base_url="http://t/api/v1", timeout=120)
    tag = uuid.uuid4().hex[:5]

    async def login(e, pw="test-pass-123"):
        r = await c.post("/auth/login", json={"email": e, "password": pw})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    d = await login("director@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")
    me1 = J(await c.get("/auth/me", headers=s1))

    # A second rep to hand things to, and a finance account to prove the
    # server refuses somebody who has no business holding a customer.
    rep2_name = f"Rep Dua {tag}"
    # The register entry comes before the login.
    rep2_emp = J(await c.post("/employees", headers=d, json={
        "full_name": rep2_name, "intended_role": "sales"}))
    second = J(await c.post("/users", headers=d, json={
        "email": f"rep2-{tag}@demo.local", "full_name": rep2_name,
        "role": "sales", "employee_id": rep2_emp["id"],
        "password": "test-pass-123"}))
    s2 = await login(f"rep2-{tag}@demo.local")
    me2 = J(await c.get("/auth/me", headers=s2))
    fin = J(await c.get("/users", headers=d, params={"role": "finance"}))
    fin_id = (fin[0]["id"] if isinstance(fin, list) and fin else None)

    async def new_customer(headers=s1, name=None) -> str:
        return J(await c.post("/customers", headers=headers, json={
            "company_name": name or f"PT Serah {tag}-{uuid.uuid4().hex[:4]}",
            "industry": "mining"}))["id"]

    async def approved_pr(cust: str, headers=s1) -> str:
        pr = J(await c.post("/price-requests", headers=headers, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 10, "uom": "meter"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=headers)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_400_000, "basis": "unit"}]})
        return pr

    # ══ who may do it ════════════════════════════════════════════════════════
    print("\n── only the director hands accounts around ──")
    cust = await new_customer()
    r = await c.post("/customers/reassign", headers=s1, json={
        "customer_ids": [cust], "sales_pic_id": me2["id"]})
    check("a sales rep cannot give their own account away", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:140])
    r = await c.patch(f"/customers/{cust}", headers=s1,
                      json={"sales_pic_id": me2["id"]})
    check("...nor through the ordinary customer edit", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:140])
    check("...and is told who can", "director" in str(J(r)).lower(), str(J(r))[:120])
    still = J(await c.get(f"/customers/{cust}", headers=d))
    check("...the account did not move", still["sales_pic_id"] == me1["id"],
          str(still["sales_pic_id"]))

    r = await c.patch(f"/customers/{cust}", headers=d,
                      json={"sales_pic_id": me2["id"]})
    check("even the director is sent to the reassign action instead of a field edit",
          r.status_code == 400, f"{r.status_code} {J(r)}"[:140])
    still = J(await c.get(f"/customers/{cust}", headers=d))
    check("...so that PATCH moved nothing either",
          still["sales_pic_id"] == me1["id"], str(still["sales_pic_id"]))

    # An ordinary edit that happens to echo the unchanged owner must still
    # save — the edit form posts every field it was given back.
    r = await c.patch(f"/customers/{cust}", headers=d, json={
        "sales_pic_id": me1["id"], "pic_name": "Pak Budi"})
    check("an edit that repeats the current owner still saves", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    check("...and the other field landed",
          J(await c.get(f"/customers/{cust}", headers=d))["pic_name"] == "Pak Budi")

    # ══ who may receive one ══════════════════════════════════════════════════
    print("\n── who can be put in charge ──")
    if fin_id:
        r = await c.post("/customers/reassign", headers=d, json={
            "customer_ids": [cust], "sales_pic_id": fin_id})
        check("finance cannot be handed a customer", r.status_code == 400,
              f"{r.status_code} {J(r)}"[:140])
    r = await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [cust], "sales_pic_id": str(uuid.uuid4())})
    check("neither can somebody who does not exist", r.status_code == 404, str(r.status_code))
    await c.patch(f"/users/{second['id']}", headers=d, json={"is_active": False})
    r = await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [cust], "sales_pic_id": me2["id"]})
    check("nor a disabled account", r.status_code == 400, f"{r.status_code} {J(r)}"[:140])
    check("...naming the fix", "disabled" in str(J(r)).lower(), str(J(r))[:120])
    await c.patch(f"/users/{second['id']}", headers=d, json={"is_active": True})

    reps = J(await c.get("/customers/assignable-reps", headers=d))
    ids = {r["id"] for r in reps["reps"]}
    check("the picker offers the new rep", me2["id"] in ids)
    check("...and not finance", fin_id not in ids if fin_id else True)
    check("...with each rep's current load",
          all(isinstance(r["customers"], int) for r in reps["reps"]))
    r = await c.get("/customers/assignable-reps", headers=s1)
    check("sales cannot browse the roster", r.status_code == 403, str(r.status_code))

    # ══ the handover itself ══════════════════════════════════════════════════
    print("\n── the account and its live work move together ──")
    cust = await new_customer(name=f"PT Pindah {tag}")
    live_pr = await approved_pr(cust)
    live_q = J(await c.post(f"/quotations/from-price-request/{live_pr}", headers=s1))["id"]
    # A second quotation, taken all the way to won: the record of a closed
    # deal belongs to the rep who closed it and must not follow the account.
    won_pr = await approved_pr(cust)
    won_q = J(await c.post(f"/quotations/from-price-request/{won_pr}", headers=s1))["id"]
    await c.post(f"/quotations/{won_q}/submit", headers=s1)
    await c.post(f"/quotations/{won_q}/approve", headers=d, json={})
    await c.post(f"/quotations/{won_q}/won", headers=d)
    won_state = J(await c.get(f"/quotations/{won_q}", headers=d))["status"]
    closer = J(await c.get(f"/quotations/{won_q}", headers=d))["sales_pic_id"]

    r = await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [cust], "sales_pic_id": me2["id"],
        "move_open_work": True, "note": "Rep Dua takes East Java"})
    out = J(r)
    check("the director hands it over", r.status_code == 200, f"{r.status_code} {out}"[:160])
    check("...one customer moved", out.get("moved") == 1, str(out.get("moved")))
    check("...and it says what came with it",
          out.get("price_requests_moved", 0) >= 2 and out.get("quotations_moved", 0) >= 2,
          f"prs={out.get('price_requests_moved')} quotes={out.get('quotations_moved')}")

    got = J(await c.get(f"/customers/{cust}", headers=d))
    check("the customer is the new rep's", got["sales_pic_id"] == me2["id"],
          str(got["sales_pic_id"]))
    check("...and the detail page can name them",
          got.get("sales_pic_name") == rep2_name if rep2_name
          else bool(got.get("sales_pic_name")), str(got.get("sales_pic_name")))

    check("the new rep can open it",
          (await c.get(f"/customers/{cust}", headers=s2)).status_code == 200)
    r = await c.get(f"/customers/{cust}", headers=s1)
    check("...and the old rep can no longer", r.status_code == 403, str(r.status_code))
    mine1 = [x["id"] for x in J(await c.get("/customers", headers=s1))["data"]]
    check("...it is gone from the old rep's list", cust not in mine1)
    mine2 = [x["id"] for x in J(await c.get("/customers", headers=s2))["data"]]
    check("...and present in the new rep's", cust in mine2)

    print("\n── live documents follow, decided ones stay ──")
    q_now = J(await c.get(f"/quotations/{live_q}", headers=d))
    check("the open quotation changed hands",
          q_now["sales_pic_id"] == me2["id"], str(q_now["sales_pic_id"]))
    check("...so the new rep can open it",
          (await c.get(f"/quotations/{live_q}", headers=s2)).status_code == 200)
    check("...and the old rep cannot",
          (await c.get(f"/quotations/{live_q}", headers=s1)).status_code == 403)
    won_now = J(await c.get(f"/quotations/{won_q}", headers=d))
    check(f"the {won_state} quotation came across as well",
          won_now["sales_pic_id"] == me2["id"], str(won_now["sales_pic_id"]))
    check("...so the new rep can work the repeat business on it",
          (await c.get(f"/quotations/{won_q}", headers=s2)).status_code == 200)
    check("...and it was the other rep's a moment ago",
          closer == me1["id"], str(closer))
    prs2 = J(await c.get("/price-requests", headers=s2))
    pr_ids2 = {x["id"] for x in (prs2 if isinstance(prs2, list) else prs2.get("data", []))}
    check("the price requests moved too", live_pr in pr_ids2)

    print("\n── the handover is written down ──")
    acts = J(await c.get(f"/customers/{cust}/activities", headers=d))
    handover = next((a for a in acts if a["type"] == "assignment"), None)
    check("the customer's timeline records it", handover is not None)
    check("...with both names",
          handover and me1["full_name"] in (handover["notes"] or "")
          and rep2_name in (handover["notes"] or ""),
          handover and handover["notes"])
    check("...and the reason the director gave",
          handover and "East Java" in (handover["notes"] or ""),
          handover and handover["notes"])
    bell2 = J(await c.get("/notifications", headers=s2))
    mine = [i for i in bell2["items"] if i["kind"] == "handover"]
    check("the new rep is told in the bell", len(mine) >= 1, str(len(mine)))
    check("...by name, with a link to the customer",
          any("PT Pindah" in i["title"] and cust in i["link"] for i in mine),
          str(mine[:1])[:180])
    check("...and told what came with it",
          any("quotation" in i["body"] for i in mine), str(mine[:1])[:180])
    bell1 = J(await c.get("/notifications", headers=s1))
    check("the old rep is told it left them",
          any(i["kind"] == "handover" for i in bell1["items"]))
    audit = J(await c.get("/audit", headers=d, params={"entity": "customer", "limit": 50}))
    rows = audit if isinstance(audit, list) else audit.get("data", [])
    check("and the audit log has it",
          any(str(a.get("entity_id")) == cust
              and "sales_pic_id" in str(a.get("after") or {}) for a in rows))

    # ══ leaving the work where it is ═════════════════════════════════════════
    print("\n── handing over the account only ──")
    cust2 = await new_customer()
    pr2 = await approved_pr(cust2)
    q2id = J(await c.post(f"/quotations/from-price-request/{pr2}", headers=s1))["id"]
    out = J(await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [cust2], "sales_pic_id": me2["id"], "move_open_work": False}))
    check("nothing is carried when the director says not to",
          out.get("quotations_moved") == 0 and out.get("price_requests_moved") == 0,
          str(out)[:140])
    check("...the customer still moved", out.get("moved") == 1, str(out.get("moved")))
    check("...and the quotation stayed behind",
          J(await c.get(f"/quotations/{q2id}", headers=d))["sales_pic_id"] == me1["id"])

    # ══ in bulk, which is the point after an import ══════════════════════════
    print("\n── a batch of unowned customers ──")
    batch = [J(await c.post("/customers", headers=d, json={
        "company_name": f"PT Impor {tag}-{i}", "industry": "cement"}))["id"]
        for i in range(3)]
    free = J(await c.get("/customers", headers=d, params={"unassigned": True,
                                                          "page_size": 200}))
    free_ids = {x["id"] for x in free["data"]}
    check("the unassigned filter finds all three", all(b in free_ids for b in batch),
          f"{len(free_ids)} unassigned")
    check("...and does not include an owned one", cust not in free_ids)

    out = J(await c.post("/customers/reassign", headers=d, json={
        "customer_ids": batch, "sales_pic_id": me2["id"]}))
    check("all three move in one action", out.get("moved") == 3, str(out.get("moved")))
    owned = J(await c.get("/customers", headers=d, params={"sales_pic_id": me2["id"],
                                                           "page_size": 200}))
    owned_ids = {x["id"] for x in owned["data"]}
    check("...and the by-rep filter now lists them", all(b in owned_ids for b in batch))

    out = J(await c.post("/customers/reassign", headers=d, json={
        "customer_ids": batch, "sales_pic_id": me2["id"]}))
    check("running it again moves nothing", out.get("moved") == 0, str(out.get("moved")))
    check("...and says they were already theirs", out.get("unchanged") == 3,
          str(out.get("unchanged")))

    print("\n── taking an account off somebody ──")
    out = J(await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [batch[0]], "sales_pic_id": None}))
    check("an account can be left with nobody", out.get("moved") == 1, str(out))
    got = J(await c.get(f"/customers/{batch[0]}", headers=d))
    check("...and really is unowned", got["sales_pic_id"] is None, str(got["sales_pic_id"]))
    check("...and the rep who had it can no longer see it",
          (await c.get(f"/customers/{batch[0]}", headers=s2)).status_code == 403)

    # ══ the rep the import file named ════════════════════════════════════════
    #
    # The export's Kategori column carries a rep name. When no account here
    # matches it — a rep who has not been given a login yet — the customer
    # imports unassigned, and that name used to be thrown away, leaving a pile
    # of unowned companies with no record of whose they were. It is kept now,
    # and it is what the director sorts them out by afterwards.
    print("\n── customers imported under a name with no account ──")
    import io, csv as _csv
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["ID Pelanggan", "Nama", "Kategori", "Alamat Penagihan"])
    for i in range(3):
        ws.append([f"C.9{tag}{i}", f"PT Diani Punya {tag}-{i}", f"Customer Diani {tag}",
                   "Jl. Industri 5, Gresik"])
    ws.append([f"C.8{tag}", f"PT Bukan Diani {tag}", "Umum", "Jl. Lain 2, Sidoarjo"])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    files = {"file": (f"pelanggan-{tag}.xlsx", buf.getvalue(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    prev = J(await c.post("/imports/customers/preview", headers=d, files=files))
    check("the preview says the rep has no account here",
          any(f"diani {tag}" in u.lower() for u in prev.get("unmatched_reps", [])),
          str(prev.get("unmatched_reps"))[:140])

    buf.seek(0)
    files = {"file": (f"pelanggan-{tag}.xlsx", buf.getvalue(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = J(await c.post("/imports/customers/commit", headers=d, files=files,
                         data={"limit": 10, "confirm": "IMPORT"}))
    check("the four import", res.get("created") == 4, str(res)[:160])

    got = J(await c.get("/customers", headers=d,
                        params={"q": f"PT Diani Punya {tag}", "page_size": 50}))["data"]
    check("...unassigned, because nobody here is that person",
          len(got) == 3 and all(x["sales_pic_id"] is None for x in got), str(len(got)))
    check("...but the file's name is kept on them",
          all(x.get("sales_rep_hint", "").startswith("diani") for x in got),
          str([x.get("sales_rep_hint") for x in got])[:140])

    reps = J(await c.get("/customers/assignable-reps", headers=d))
    group = next((g for g in reps.get("from_import", [])
                  if g["hint"].startswith(f"diani {tag}")), None)
    check("the roster offers them as a group to hand over", group is not None,
          str(reps.get("from_import"))[:200])
    check("...counting how many still have nobody on them",
          group and group["unassigned"] == 3, str(group))

    by_hint = J(await c.get("/customers", headers=d,
                            params={"rep_hint": group["hint"], "page_size": 50}))
    check("filtering by that name finds exactly those three",
          by_hint["total"] == 3, str(by_hint["total"]))
    check("...and not the customer the file left blank",
          all(f"Bukan Diani" not in x["company_name"] for x in by_hint["data"]))

    # Now Diani gets an account, and the director hands the three over.
    diani_emp = J(await c.post("/employees", headers=d, json={
        "full_name": f"Diani Putri {tag}", "intended_role": "sales"}))
    diani = J(await c.post("/users", headers=d, json={
        "email": f"diani-{tag}@demo.local", "full_name": f"Diani Putri {tag}",
        "role": "sales", "employee_id": diani_emp["id"],
        "password": "test-pass-123"}))
    out = J(await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [x["id"] for x in by_hint["data"]],
        "sales_pic_id": diani["id"], "note": "account created after the import"}))
    check("all three go to the new account at once", out.get("moved") == 3, str(out)[:140])
    dh = await login(f"diani-{tag}@demo.local")
    theirs = [x["company_name"] for x in J(await c.get("/customers", headers=dh))["data"]]
    check("...and Diani can now see them",
          sum(1 for n in theirs if f"PT Diani Punya {tag}" in n) == 3, str(theirs)[:160])

    reps = J(await c.get("/customers/assignable-reps", headers=d))
    group = next((g for g in reps.get("from_import", [])
                  if g["hint"].startswith(f"diani {tag}")), None)
    check("the group stops asking to be dealt with",
          group and group["unassigned"] == 0, str(group))
    check("...but still records where they came from",
          group and group["customers"] == 3, str(group))

    r = await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [], "sales_pic_id": me2["id"]})
    check("an empty selection is refused rather than silently doing nothing",
          r.status_code == 400, str(r.status_code))
    r = await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [str(uuid.uuid4())], "sales_pic_id": me2["id"]})
    check("a customer that does not exist stops the whole batch",
          r.status_code == 404, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())
