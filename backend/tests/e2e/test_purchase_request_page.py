"""A purchase request has its own page, and purchasing can correct it.

* Opened, it shows its lines, prices, currency, supplier, who asked and the
  director's approval card.
* Purchasing changes lines, quantities, units, prices, the currency and the
  supplier; the totals follow. While it waits, the director's card shows the
  new total.
* Refused: no supplier (purchasing), an unknown supplier, a bad currency, a
  zero quantity, a unit we don't count in, an empty request.
* Closed: read-only until reopened. Rejected by the director: can't be reopened.
* Sales and admin can't open or edit it.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")) if isinstance(b, dict) else str(b)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, pur, adm, s1 = (await login("director@demo.local"), await login("purchasing@demo.local"),
                       await login("admin@demo.local"), await login("sales1@demo.local"))
    supA = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT SATU {TAG}"}))
    supB = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT DUA {TAG}"}))

    r = J(await c.post("/inventory/request-order", headers=pur, json={"supplier_id": supA["id"], "items": [
        {"name": f"BEARING {TAG}", "qty": 10, "uom": "pcs", "unit_price": 50_000}]}))
    pr_id = r["purchase_request_id"]
    P = f"/purchasing/pr/{pr_id}"

    print("\n── opened ──")
    x = J(await c.get(P, headers=pur))
    check("it shows its line, price, supplier and who asked",
          x.get("items", [{}])[0].get("unit_price") == 50_000 and x.get("supplier_name") == supA["name"]
          and x.get("requested_by_name") and x.get("currency") == "IDR" and x.get("totals") == {"IDR": 500000.0},
          str(x)[:240])
    check("...waiting for the director, with the card", x.get("status") == "pending_approval"
          and (x.get("approval") or {}).get("status") == "pending" and "Rp 500.000" in x["approval"]["reason"],
          str(x.get("approval"))[:200])
    check("...and editable", x.get("editable") is True)
    for who, h in (("sales", s1), ("admin", adm)):
        r = await c.get(P, headers=h)
        check(f"{who} can't open it", r.status_code == 403, str(r.status_code))

    print("\n── purchasing corrects it ──")
    body = {"currency": "CNY", "supplier_id": supB["id"], "notes": "harga baru", "items": [
        {"name": f"BEARING {TAG}", "qty": 12, "uom": "PCS", "unit_price": 22.5},
        {"name": f"OIL SEAL {TAG}", "qty": 3, "uom": "mtr", "unit_price": 4},
        {"name": f"GREASE {TAG}", "qty": 1, "uom": "box"}]}
    r = await c.put(P, headers=pur, json=body)
    x = J(r)
    L = x.get("items", [])
    check("saved: three lines, in yuan, from the new supplier", r.status_code == 200 and len(L) == 3
          and x.get("currency") == "CNY" and x.get("supplier_name") == supB["name"]
          and all(l.get("supplier_id") == supB["id"] for l in L), f"{r.status_code} {str(x)[:200]}")
    check("...units tidied (PCS → pcs, mtr → meter), totals follow: ¥270 + ¥12",
          [l["uom"] for l in L] == ["pcs", "meter", "box"] and L[0].get("amount") == 270
          and L[1].get("amount") == 12 and x.get("totals") == {"CNY": 282.0}, str(L)[:240])
    check("...a line with no price stays without one", L[2].get("unit_price") is None and "amount" not in L[2])
    check("...the director's card now shows the new total", "¥ 282" in (x.get("approval") or {}).get("reason", ""),
          str(x.get("approval"))[:200])

    print("\n── refused ──")
    bad = [
        ("no supplier (purchasing)", {**body, "supplier_id": None}, 400),
        ("an unknown supplier", {**body, "supplier_id": str(uuid.uuid4())}, 400),
        ("a currency we don't use", {**body, "currency": "XYZ"}, 400),
        ("a zero quantity", {**body, "items": [{"name": "X", "qty": 0, "uom": "pcs"}]}, 400),
        ("a unit we don't count in", {**body, "items": [{"name": "X", "qty": 1, "uom": "drum"}]}, 400),
        ("an empty request", {**body, "items": [{"name": " ", "qty": 1, "uom": "pcs"}]}, 400),
    ]
    for name, b, code in bad:
        r = await c.put(P, headers=pur, json=b)
        check(f"{name}: refused", r.status_code == code, f"{r.status_code} {why(r)}")
    r = await c.put(P, headers=s1, json=body)
    check("sales can't edit it", r.status_code == 403, str(r.status_code))

    print("\n── approved, closed, reopened ──")
    appr = J(await c.get(P, headers=d))["approval"]["id"]
    r = await c.post(f"/approvals/{appr}/approve", headers=d)
    check("the director approves it → open", r.status_code == 200 and J(await c.get(P, headers=d))["status"] == "open",
          f"{r.status_code} {why(r)}")
    await c.patch(P, headers=pur, json={"status": "closed"})
    x = J(await c.get(P, headers=pur))
    r = await c.put(P, headers=pur, json=body)
    check("closed: read-only", x.get("editable") is False and r.status_code == 409, f"{x.get('editable')} {r.status_code}")
    await c.patch(P, headers=pur, json={"status": "open"})
    r = await c.put(P, headers=pur, json=body)
    check("reopened: editable again", r.status_code == 200, f"{r.status_code} {why(r)}")

    print("\n── rejected ──")
    r2 = J(await c.post("/inventory/request-order", headers=adm, json={"items": [{"name": f"ROPE {TAG}", "qty": 1, "uom": "roll"}]}))
    P2 = f"/purchasing/pr/{r2['purchase_request_id']}"
    a2 = J(await c.get(P2, headers=d))["approval"]["id"]
    await c.post(f"/approvals/{a2}/reject", headers=d, params={"notes": "not needed"})
    r = await c.patch(P2, headers=pur, json={"status": "open"})
    check("a request the director rejected can't be reopened", r.status_code == 409, f"{r.status_code} {why(r)}")
    x = J(await c.get(P2, headers=d))
    check("...and shows the director's reason", (x.get("approval") or {}).get("decision_notes") == "not needed"
          and x.get("editable") is False, str(x.get("approval"))[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())
