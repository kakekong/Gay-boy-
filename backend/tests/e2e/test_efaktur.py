"""e-Faktur CSV export: approved+faktur invoices for a masa, correct FK/OF rows,
masa filter, permissions."""
import asyncio, os, sys, io, csv as _csv
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
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"}); return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.core.db import SessionLocal
    from app.models.crm import Customer
    from app.models.finance import Invoice
    from sqlalchemy import select
    from datetime import date
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    fin=await login(c,"director@demo.local"); sales=await login(c,"sales1@demo.local")

    # Seed a customer with tax fields + an approved invoice with a faktur number
    # directly in the DB (skip the whole project chain for a focused test).
    async with SessionLocal() as db:
        cust=Customer(company_name="PT Faktur Uji", industry="mining",
                      tax_id="01.234.567.8-901.000", tax_name="PT Faktur Uji Tbk",
                      tax_address="Jl. Merdeka No. 1, Jakarta", is_pkp=True)
        db.add(cust); await db.flush()
        inv=Invoice(number="INV-EF-001", customer_id=cust.id, type="single",
                    issue_date=date(2026,7,10), amount=10000000, tax_amount=1100000,
                    total=11100000, status="approved", faktur_pajak_no="010.000-26.00000009",
                    faktur_pajak_status="issued")
        # an unapproved one (should be excluded)
        inv2=Invoice(number="INV-EF-002", customer_id=cust.id, type="single",
                     issue_date=date(2026,7,12), amount=5000000, tax_amount=550000,
                     total=5550000, status="pending_finance", faktur_pajak_no=None)
        # approved but different masa (June — should be excluded for July)
        inv3=Invoice(number="INV-EF-003", customer_id=cust.id, type="single",
                     issue_date=date(2026,6,10), amount=2000000, tax_amount=220000,
                     total=2220000, status="approved", faktur_pajak_no="010.000-26.00000003",
                     faktur_pajak_status="issued")
        db.add_all([inv,inv2,inv3]); await db.commit()

    # Export July 2026
    r=await c.get("/finance/efaktur.csv",headers=fin,params={"period":"2026-07"})
    check("export 200", r.status_code==200, str(r.status_code))
    check("is csv", "text/csv" in r.headers.get("content-type",""), r.headers.get("content-type"))
    check("filename header", "efaktur-2026-07.csv" in r.headers.get("content-disposition",""), r.headers.get("content-disposition"))
    text=r.text
    rows=list(_csv.reader(io.StringIO(text)))
    fk=[row for row in rows if row and row[0]=="FK"]
    of=[row for row in rows if row and row[0]=="OF"]
    # schema header rows (FK/LT/OF) + 1 data FK + 1 data OF
    check("has schema FK header", any(row[:2]==["FK","KD_JENIS_TRANSAKSI"] for row in rows), str(rows[:1]))
    data_fk=[row for row in fk if row[1]!="KD_JENIS_TRANSAKSI"]
    data_of=[row for row in of if row[1]!="KODE_OBJEK"]
    check("my invoice present (July approved+faktur)", any(r[18]=="INV-EF-001" for r in data_fk), str(data_fk))
    check("excluded pending + June", "INV-EF-002" not in text and "INV-EF-003" not in text, "leaked excluded invoice")
    mine=[r for r in data_fk if r[18]=="INV-EF-001"]
    if mine:
        row=mine[0]
        # FK,KD,FG,NOMOR,MASA,TAHUN,TGL,NPWP,NAMA,ALAMAT,DPP,PPN,...
        check("nomor faktur digits only", row[3]=="0100002600000009", row[3])
        check("masa=7 tahun=2026", row[4]=="7" and row[5]=="2026", f"{row[4]}/{row[5]}")
        check("tanggal dd/mm/yyyy", row[6]=="10/07/2026", row[6])
        check("npwp digits only", row[7]=="012345678901000", row[7])
        check("nama = tax_name", row[8]=="PT Faktur Uji Tbk", row[8])
        check("DPP=10000000", row[10]=="10000000", row[10])
        check("PPN=1100000", row[11]=="1100000", row[11])
        check("referensi = invoice number", row[18]=="INV-EF-001", row[18])
    mine_of=[r for r in data_of if r[7]=="10000000"]
    check("OF DPP+PPN present for my invoice", mine_of and mine_of[0][8]=="1100000", str(data_of))

    # Sales must not access the finance router
    r=await c.get("/finance/efaktur.csv",headers=sales,params={"period":"2026-07"})
    check("sales forbidden", r.status_code==403, str(r.status_code))

    # Bad period rejected
    r=await c.get("/finance/efaktur.csv",headers=fin,params={"period":"2026-13"})
    check("bad period rejected", r.status_code==400, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())
