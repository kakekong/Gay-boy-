"""Correcting the currency on a supplier quote — after it is closed.

Everything on an answered supplier price request is frozen, and rightly: the
vendor is holding the list they were sent, and rewording it underneath them
would mean their answer no longer says what it looks like it says.

The currency is the exception, because it is not a decision anybody made. It
is a fact read off the vendor's sheet, and reading it wrong is quiet: a quote
in CNY typed as though it were rupiah looks like a bargain, applies at face
value, and sets a margin on a number that never existed. That mistake is
noticed *after* the quote has been applied — which under the old rules was
precisely when it stopped being fixable.

So the real content of this driver is the second half. Changing the label is
easy and worthless on its own; what has to hold is that the cost this quote
put on the price request moves with it, in the same call, and that when it
cannot move — because the price request has gone past re-costing — the whole
change is refused rather than half-applied, leaving the record exactly as it
was found.
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
    return str(b.get("detail")
               or (b.get("errors") or [{}])[0].get("message", "")).lower()


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

    async def build(label):
        """A costed job: customer price request, one supplier asked."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {label} {TAG}", "industry": "mining"}))["id"]
        sup = J(await c.post("/purchasing/suppliers", headers=d, json={
            "name": f"Jiangsu {label} {TAG}"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Rotor {label} {TAG}", "qty": 4,
                       "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        spr = J(await c.post("/purchasing/price-requests", headers=pur, json={
            "supplier_ids": [sup], "price_request_id": pr["id"]}))[0]
        return pr["id"], spr["id"]

    # ══ the mistake ══════════════════════════════════════════════════════
    print("\n── a yuan quote typed as rupiah ──")
    pr_id, spr_id = await build("Kurs")
    # 1,800 a unit — the vendor said CNY, purchasing left the currency alone.
    r = await c.post(f"/purchasing/price-requests/{spr_id}/quote", headers=pur,
                     json={"items": [{"line_no": 1, "quoted_price": 1800,
                                      "basis": "unit"}]})
    check("the quote is recorded", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...in rupiah, because nobody said otherwise",
          J(r).get("currency") == "IDR", str(J(r).get("currency")))
    r = await c.post(f"/purchasing/price-requests/{spr_id}/apply", headers=pur)
    check("...and applied", r.status_code == 200, f"{r.status_code} {why(r)}")
    spr = J(await c.get(f"/purchasing/price-requests/{spr_id}", headers=pur))
    check("...which closes the request", spr.get("status") == "closed",
          str(spr.get("status")))
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=pur))
    check("...leaving Rp 1.800 on the price request — the wrong number",
          float(pr["items"][0]["cost_price"]) == 1800,
          str(pr["items"][0].get("cost_price")))

    # ══ the correction ═══════════════════════════════════════════════════
    print("\n── purchasing notices, after the fact ──")
    # The old rules: the general edit route is still shut, which is the point
    # of giving the currency its own way in rather than reopening the record.
    r = await c.patch(f"/purchasing/price-requests/{spr_id}", headers=pur,
                      json={"notes": "reopen me"})
    check("a closed request still refuses ordinary edits",
          r.status_code == 409, f"{r.status_code} {why(r)}")

    r = await c.patch(f"/purchasing/price-requests/{spr_id}/currency",
                      headers=pur, json={"currency": "CNY"})
    check("...and a foreign currency with no rate is refused",
          r.status_code == 400 and "how many rupiah" in why(r),
          f"{r.status_code} {why(r)}")
    r = await c.patch(f"/purchasing/price-requests/{spr_id}/currency",
                      headers=pur, json={"currency": "CNY", "fx_rate": 0})
    check("...as is a rate of nothing",
          r.status_code == 400 and "positive" in why(r), f"{r.status_code} {why(r)}")
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=pur))
    check("...and a refusal changes nothing",
          float(pr["items"][0]["cost_price"]) == 1800,
          str(pr["items"][0].get("cost_price")))

    r = await c.patch(f"/purchasing/price-requests/{spr_id}/currency",
                      headers=pur, json={"currency": "CNY", "fx_rate": 2250})
    check("the currency can be corrected on a closed request",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    got = J(r)
    check("...and the request says so", got.get("currency") == "CNY"
          and float(got.get("fx_rate") or 0) == 2250,
          f"{got.get('currency')} @ {got.get('fx_rate')}")
    check("...still closed — this is a correction, not a reopening",
          got.get("status") == "closed", str(got.get("status")))
    check("...reporting what it re-costed, rather than leaving you to check",
          got.get("recosted") and got["recosted"][0]["recosted_lines"] == 1,
          str(got.get("recosted"))[:200])

    pr = J(await c.get(f"/price-requests/{pr_id}", headers=pur))
    check("the cost moves with it — 1.800 CNY is Rp 4.050.000",
          float(pr["items"][0]["cost_price"]) == 1800 * 2250,
          str(pr["items"][0].get("cost_price")))
    check("...and the price request says why it changed",
          "quoted in CNY" in (pr.get("notes") or ""), str(pr.get("notes"))[:220])

    # Correcting back is the same operation in reverse, rate and all.
    r = await c.patch(f"/purchasing/price-requests/{spr_id}/currency",
                      headers=pur, json={"currency": "IDR"})
    check("correcting back to rupiah needs no rate typed",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and rupiah is its own rate",
          float(J(r).get("fx_rate") or 0) == 1, str(J(r).get("fx_rate")))
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=pur))
    check("...so the cost goes back to where it started",
          float(pr["items"][0]["cost_price"]) == 1800,
          str(pr["items"][0].get("cost_price")))

    # ══ when it cannot be finished ═══════════════════════════════════════
    print("\n── once the price has been decided downstream ──")
    pr2_id, spr2_id = await build("Putus")
    await c.post(f"/purchasing/price-requests/{spr2_id}/quote", headers=pur,
                 json={"items": [{"line_no": 1, "quoted_price": 2000,
                                  "basis": "unit"}]})
    await c.post(f"/purchasing/price-requests/{spr2_id}/apply", headers=pur)
    # The director prices it and it leaves purchasing's hands.
    r = await c.post(f"/price-requests/{pr2_id}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": 5000,
                                      "basis": "unit"}]})
    check("the director approves the price", r.status_code in (200, 201),
          f"{r.status_code} {why(r)}")

    r = await c.patch(f"/purchasing/price-requests/{spr2_id}/currency",
                      headers=pur, json={"currency": "USD", "fx_rate": 16200})
    check("a correction that cannot reach the cost is refused whole",
          r.status_code == 409 and "moved past re-costing" in why(r),
          f"{r.status_code} {why(r)}")
    spr2 = J(await c.get(f"/purchasing/price-requests/{spr2_id}", headers=pur))
    check("...leaving the currency as it was",
          spr2.get("currency") == "IDR", str(spr2.get("currency")))
    pr2 = J(await c.get(f"/price-requests/{pr2_id}", headers=pur))
    check("...and the cost as it was", float(pr2["items"][0]["cost_price"]) == 2000,
          str(pr2["items"][0].get("cost_price")))

    # ══ a quote nothing depends on ═══════════════════════════════════════
    print("\n── and one that was never applied ──")
    pr3_id, spr3_id = await build("Tutup")
    await c.post(f"/purchasing/price-requests/{spr3_id}/quote", headers=pur,
                 json={"items": [{"line_no": 1, "quoted_price": 900,
                                  "basis": "unit"}]})
    await c.post(f"/purchasing/price-requests/{spr3_id}/close", headers=pur,
                 json={"reason": "another vendor won"})
    r = await c.patch(f"/purchasing/price-requests/{spr3_id}/currency",
                      headers=pur, json={"currency": "USD", "fx_rate": 16200})
    check("a losing quote can be corrected too — it is still the record",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...with nothing to re-cost", J(r).get("recosted") == [],
          str(J(r).get("recosted")))
    pr3 = J(await c.get(f"/price-requests/{pr3_id}", headers=pur))
    check("...and the price request left alone",
          pr3["items"][0].get("cost_price") in (None, ""),
          str(pr3["items"][0].get("cost_price")))

    # ══ the rate belongs to the currency ═════════════════════════════════
    print("\n── revising a rupiah quote into yuan ──")
    pr4_id, spr4_id = await build("Revisi")
    await c.post(f"/purchasing/price-requests/{spr4_id}/quote", headers=pur,
                 json={"items": [{"line_no": 1, "quoted_price": 1500,
                                  "basis": "unit"}]})
    got = J(await c.get(f"/purchasing/price-requests/{spr4_id}", headers=pur))
    check("a rupiah quote carries a rate of 1, as it should",
          float(got.get("fx_rate") or 0) == 1, str(got.get("fx_rate")))
    # The vendor calls back: that was yuan. Purchasing changes the currency
    # and forgets the rate. The old 1 must not survive — it is a rate `apply`
    # would accept, and 1,500 CNY would land as Rp 1,500.
    r = await c.post(f"/purchasing/price-requests/{spr4_id}/quote", headers=pur,
                     json={"items": [{"line_no": 1, "quoted_price": 1500,
                                      "basis": "unit"}], "currency": "CNY"})
    check("changing the currency drops the old currency's rate",
          r.status_code == 200 and J(r).get("fx_rate") is None,
          f"{r.status_code} rate={J(r).get('fx_rate')}")
    r = await c.post(f"/purchasing/price-requests/{spr4_id}/apply", headers=pur)
    check("...so applying asks for the rate instead of inventing one",
          r.status_code == 409 and "no exchange rate" in why(r),
          f"{r.status_code} {why(r)}")

    # ══ who may ══════════════════════════════════════════════════════════
    print("\n── whose correction it is ──")
    r = await c.patch(f"/purchasing/price-requests/{spr3_id}/currency",
                      headers=s1, json={"currency": "IDR"})
    check("sales cannot touch what a vendor charges us",
          r.status_code == 403, str(r.status_code))
    r = await c.patch(f"/purchasing/price-requests/{spr3_id}/currency",
                      headers=d, json={"currency": "IDR"})
    check("the director can", r.status_code == 200, f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())
