"""Some jobs have no drawing, and the pipeline has to admit it.

A catalogue part bought off the shelf has nothing to draw and nothing for the
customer to approve. The pipeline held those at the drawing gate anyway —
logistics could not be set until a customer drawing was approved — so the way
through was to upload *something*, a photo or the supplier's web page, and
approve that. That is worse than the delay it avoids: the file then says a
drawing was approved on a job that never had one, and nobody reading it later
can tell which approvals were real.

So skipping is a decision rather than a workaround. It is recorded — who, when,
why — and it is **the director's**, the same signature that approves a real
drawing. Purchasing and ops may ask; the request goes to the director's queue.

The two things that matter beyond "the button works":

* **It must not become a way past the director.** Sales cannot touch it,
  purchasing gets a request rather than a skip, and the request has to be
  approved before anything changes.
* **It must not fake an approved drawing.** The job moves on because the
  drawing question is settled, not because a drawing exists — so the drawings
  list stays empty and the record says "skipped", not "approved".
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
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")).lower()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    n = [0]

    async def a_project(label):
        """A won deal, so there is a real project sitting at the drawing gate."""
        n[0] += 1
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {label} {TAG}-{n[0]}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Sprocket {label} {TAG}-{n[0]}", "qty": 4,
                       "uom": "pcs", "category": "sprocket"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur,
                     json={"items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"decision": "approve"})
        po = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"],
            "number": f"PO-{TAG}-{n[0]}", "po_date": "2026-09-08",
            "items": [{"description": f"Sprocket {TAG}", "qty": 4, "unit_price": 200_000}]}))
        await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"decision": "approve"})
        return J(await c.get(f"/customer-pos/{po['id']}", headers=d))["project_id"]

    async def proj(pid, headers=None):
        return J(await c.get(f"/operation/projects/{pid}/full", headers=headers or d))["project"]

    # ══ the gate that made people invent drawings ════════════════════════
    print("\n── a job with nothing to draw is stuck at the drawing gate ──")
    p1 = await a_project("Katalog")
    r = await c.patch(f"/operation/projects/{p1}/logistics", headers=pur,
                      json={"delivery_mode": "local", "est_delivery_date": "2026-10-01"})
    check("logistics is refused before the drawing is settled", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    check("...and the refusal now offers the way out", "skip" in why(r), why(r)[:180])

    # ══ who may decide ═══════════════════════════════════════════════════
    print("\n── and it is not something anybody can wave through ──")
    r = await c.post(f"/operation/projects/{p1}/skip-drawing", headers=s1,
                     json={"reason": "off the shelf"})
    check("sales cannot even ask", r.status_code == 403, str(r.status_code))

    r = await c.post(f"/operation/projects/{p1}/skip-drawing", headers=pur,
                     json={"reason": "catalogue part, nothing to draw"})
    check("purchasing asks, and is told it went to the director",
          r.status_code == 202, f"{r.status_code} {why(r)}")
    check("...nothing has been skipped yet",
          (await proj(p1)).get("drawing_skipped") is False,
          str((await proj(p1)).get("drawing_skipped")))
    r = await c.patch(f"/operation/projects/{p1}/logistics", headers=pur,
                      json={"est_delivery_date": "2026-10-01"})
    check("...and the gate is still shut while it is only a request",
          r.status_code == 409, str(r.status_code))

    r = await c.post(f"/operation/projects/{p1}/skip-drawing", headers=pur,
                     json={"reason": "again"})
    check("asking twice does not queue a second request", r.status_code == 202,
          str(r.status_code))
    reqs = [a for a in J(await c.get("/approvals", headers=d))
            if a.get("target_type") == "project_skip_drawing"
            and a.get("target_id") == p1]
    check("...there is exactly one waiting on the director", len(reqs) == 1,
          str(len(reqs)))

    # ══ the director signs it off ════════════════════════════════════════
    print("\n── the director signs it off, and the job moves ──")
    r = await c.post(f"/approvals/{reqs[0]['id']}/approve", headers=d,
                     params={"notes": "agreed, catalogue part"})
    check("the approval is decided", r.status_code == 200, f"{r.status_code} {why(r)}")
    after = await proj(p1)
    check("...the drawing is skipped", after.get("drawing_skipped") is True,
          str(after.get("drawing_skipped")))
    check("...with the reason kept",
          "catalogue" in (after.get("drawing_skip_reason") or "").lower(),
          str(after.get("drawing_skip_reason")))
    check("...and the project has reached drawing_approved",
          after["status"] == "drawing_approved", after["status"])

    r = await c.patch(f"/operation/projects/{p1}/logistics", headers=pur,
                      json={"delivery_mode": "local", "est_delivery_date": "2026-10-01"})
    check("logistics can now be set", r.status_code == 200, f"{r.status_code} {why(r)}")

    # ══ it must not look like an approved drawing ════════════════════════
    print("\n── but nothing pretends a drawing was approved ──")
    full = J(await c.get(f"/operation/projects/{p1}/full", headers=d))
    check("the drawings list is still empty", not (full.get("drawings") or []),
          str(len(full.get("drawings") or [])))

    # ══ BOTH stages, not just the first ══════════════════════════════════
    # "Skip the drawing" has to mean the approval too, or the job trades one
    # gate for another: nothing to approve, and a stage still waiting for an
    # approval of it. The status walk is forward-only and lands directly on
    # drawing_approved, so `drawing` and `drawing_approved` are both behind
    # the job in one move — this pins that rather than trusting it.
    print("\n── and the approval stage is skipped with it, not left waiting ──")
    ORDER = ["new", "purchasing", "drawing", "drawing_approved",
             "production", "qc", "packaging", "invoiced", "delivered",
             "paid", "closed"]
    here = ORDER.index((await proj(p1))["status"])
    check("the job is past 'drawing'", here > ORDER.index("drawing"),
          (await proj(p1))["status"])
    check("...and past 'drawing_approved' too — neither is still pending",
          here >= ORDER.index("drawing_approved"), (await proj(p1))["status"])

    queue = J(await c.get("/approvals/pending-documents", headers=d))
    rows = queue if isinstance(queue, list) else (queue.get("items") or [])
    check("nothing is waiting in the director's drawing sign-off queue for it",
          not [x for x in rows
               if x.get("kind") == "drawing" and p1 in str(x.get("link") or "")],
          str([x.get("title") for x in rows if x.get("kind") == "drawing"])[:200])

    # ══ the director's own direct path ═══════════════════════════════════
    print("\n── the director can also just do it ──")
    p2 = await a_project("Langsung")
    r = await c.post(f"/operation/projects/{p2}/skip-drawing", headers=d,
                     json={"reason": "standard chain, no drawing"})
    check("no queue, no second signature", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...it is skipped on the spot", J(r).get("drawing_skipped") is True, str(J(r)))
    check("...pressing it again is harmless",
          J(await c.post(f"/operation/projects/{p2}/skip-drawing", headers=d,
                         json={})).get("drawing_skipped") is True)

    # ══ undoing it ═══════════════════════════════════════════════════════
    print("\n── and can take it back, while that still means something ──")
    r = await c.post(f"/operation/projects/{p2}/unskip-drawing", headers=pur)
    check("purchasing may not undo it", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/operation/projects/{p2}/unskip-drawing", headers=d)
    check("the director may", r.status_code == 200, f"{r.status_code} {why(r)}")
    back = await proj(p2)
    check("...the job is back behind the drawing gate",
          back.get("drawing_skipped") is False, str(back.get("drawing_skipped")))
    check("...and the record shows the decision was withdrawn, not erased",
          "withdrawn" in (back.get("drawing_skip_reason") or "").lower(),
          str(back.get("drawing_skip_reason")))

    print("\n── once the goods are on the way, the question is behind us ──")
    # Confirming delivery needs the commercial documents on file and signed
    # off — that gate is unrelated to the drawing and stays exactly as it was.
    for key in ("invoice", "packing_list"):
        await c.post(f"/operation/projects/{p1}/import-docs/{key}/upload", headers=pur,
                     files={"file": (f"{key}.pdf", b"%PDF-1.4 doc", "application/pdf")},
                     data={"note": "for test"})
        await c.post(f"/operation/projects/{p1}/import-docs/{key}/decide", headers=d,
                     json={"decision": "approve"})
    r = await c.post(f"/operation/projects/{p1}/confirm-delivery", headers=pur)
    check("delivery is confirmed", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.post(f"/operation/projects/{p1}/unskip-drawing", headers=d)
    check("...and the skip can no longer be undone", r.status_code == 409,
          f"{r.status_code} {why(r)}")

    # ══ a job that DID have a drawing ════════════════════════════════════
    print("\n── and a job with a real approved drawing has nothing to skip ──")
    p3 = await a_project("Gambar")
    r = await c.post(f"/operation/projects/{p3}/drawings", headers=d,
                     files={"file": ("part.pdf", b"%PDF-1.4 drawing", "application/pdf")},
                     data={"kind": "customer", "notes": "rev A"})
    check("a customer drawing is filed", r.status_code == 201, f"{r.status_code} {why(r)}")
    draw_id = J(r).get("drawing_id") or J(r).get("id")
    r = await c.post(f"/operation/drawings/{draw_id}/decide", headers=d,
                     json={"decision": "approve"})
    check("...and approved", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.post(f"/operation/projects/{p3}/skip-drawing", headers=d, json={})
    check("skipping it is refused — there is nothing to skip", r.status_code == 409,
          f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())
