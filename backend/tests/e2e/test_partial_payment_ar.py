"""A partially-paid invoice must only be owed for its remainder.

Every AR surface used to read the invoice's face value while the money already
banked sat in a separate 'paid' figure, so the director's Reports page, the
finance KPI tile and the customer card all overstated receivables the moment a
customer paid in instalments — and disagreed with the finance AR aging, which
had been fixed on its own. This locks all four to the same number.

Measured as before/after deltas around one payment, so it is safe to re-run on
a dirty database.
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
def num(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def build_project(c,H,tag):
    cust=J(await c.post("/customers",headers=H["s"],json={"company_name":f"PT Partial {tag}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=H["s"],json={"customer_id":cust,
        "items":[{"description":"Widget","qty":10,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=H["s"])
    await c.post(f"/price-requests/{pr}/price",headers=H["d"],json={"items":[{"line_no":1,"cost_price":50000,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=H["d"],json={"items":[{"line_no":1,"sell_price":100000,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=H["s"]))["id"]
    await c.post(f"/quotations/{q}/submit",headers=H["s"]); await c.post(f"/quotations/{q}/approve",headers=H["d"],json={"notes":""})
    # PO first (Won is refused without it), then Won — which is what starts
    # the project — then the PO's own approval, which attaches to it.
    cpo=J(await c.post("/customer-pos",headers=H["s"],json={"customer_id":cust,"quotation_id":q,
        "number":f"PO-PART-{tag}","items":[{"description":"Widget","qty":10,"unit_price":100000}],
        "is_downpayment":False}))["id"]
    await c.post(f"/quotations/{q}/won",headers=H["d"])
    proj=J(await c.post(f"/customer-pos/{cpo}/approve",headers=H["d"],json={"notes":""}))["project_id"]
    return cust,proj

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    H={"d":await login(c,"director@demo.local"),"s":await login(c,"sales1@demo.local"),
       "a":await login(c,"admin@demo.local"),"f":await login(c,"finance@demo.local")}
    tag=uuid.uuid4().hex[:6]

    cust,proj=await build_project(c,H,tag)
    await c.post(f"/operation/projects/{proj}/qc",headers=H["a"],json={"decision":"pass"})
    r=await c.post(f"/operation/projects/{proj}/issue-invoice",headers=H["d"],data={"invoice_type":"single"})
    check("final invoice issued", r.status_code==201, J(r))

    from app.core.db import SessionLocal
    from app.models.finance import Invoice as _Inv
    from sqlalchemy import select as _sel
    async with SessionLocal() as db:
        row=await db.scalar(_sel(_Inv).where(_Inv.project_id==proj).order_by(_Inv.created_at.desc()))
        inv_id, inv_total = str(row.id), float(row.total or 0)
    r=await c.post(f"/finance/invoices/{inv_id}/approve",headers=H["f"],data={"faktur_pajak_no":f"FP-{tag}"})
    check("invoice approved with faktur pajak", r.status_code<300, J(r))

    async def snapshot():
        ag=J(await c.get("/finance/ar/aging",headers=H["f"]))
        det=J(await c.get("/reports/ar-aging-detail",headers=H["d"]))
        mine=[i for i in det.get("items",[]) if i["invoice_id"]==inv_id]
        kpi=J(await c.get("/kpi/finance",headers=H["d"]))
        st=(J(await c.get(f"/customers/{cust}/summary",headers=H["d"])) or {}).get("stats",{})
        return {
            "finance AR aging":        sum(num(v) for v in ag.values()) if isinstance(ag,dict) else 0.0,
            "reports AR aging buckets":sum(num(v) for v in det.get("buckets",{}).values()),
            "reports AR aging row":    num(mine[0].get("outstanding")) if mine else None,
            "finance KPI outstanding": num(kpi.get("outstanding")),
            "finance KPI collected":   num(kpi.get("collected")),
            "customer outstanding_ar": num(st.get("outstanding_ar")),
        }

    before=await snapshot()
    half=round(inv_total/2,2)
    r=await c.post("/payments/manual",headers=H["f"],
                   json={"invoice_id":inv_id,"amount":half,"method":"transfer","reference":f"HALF-{tag}"})
    check("half the invoice recorded as a verified payment", r.status_code==201, J(r))
    async with SessionLocal() as db:
        row=await db.get(_Inv, uuid.UUID(inv_id))
        check("invoice went to 'partial'", row.status=="partial", f"status={row.status}")
    after=await snapshot()

    for k in ("finance AR aging","reports AR aging buckets","finance KPI outstanding",
              "customer outstanding_ar"):
        d=after[k]-before[k]
        check(f"{k} drops by the payment", abs(d+half)<1, f"moved {d:,.0f}, expected -{half:,.0f}")
    check("finance KPI collected counts the partial payment",
          abs((after["finance KPI collected"]-before["finance KPI collected"])-half)<1,
          f"moved {after['finance KPI collected']-before['finance KPI collected']:,.0f}")
    check("the AR row itself shows the remainder, not the face value",
          after["reports AR aging row"] is not None and abs(after["reports AR aging row"]-(inv_total-half))<1,
          f"row={after['reports AR aging row']}, face={inv_total}")
    check("the two AR surfaces agree to the rupiah",
          abs(after["finance AR aging"]-after["reports AR aging buckets"])<1,
          f"finance={after['finance AR aging']:,.0f} reports={after['reports AR aging buckets']:,.0f}")

    # Paying the rest must retire it from AR entirely.
    r=await c.post("/payments/manual",headers=H["f"],
                   json={"invoice_id":inv_id,"amount":inv_total-half,"method":"transfer","reference":f"REST-{tag}"})
    check("remainder recorded", r.status_code==201, J(r))
    final=await snapshot()
    check("fully-paid invoice leaves the AR buckets",
          abs(final["reports AR aging buckets"]-(before["reports AR aging buckets"]-inv_total))<1,
          f"{final['reports AR aging buckets']:,.0f} vs {before['reports AR aging buckets']-inv_total:,.0f}")
    check("fully-paid invoice drops off the AR detail list",
          final["reports AR aging row"] is None, f"row={final['reports AR aging row']}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)

asyncio.run(main())
