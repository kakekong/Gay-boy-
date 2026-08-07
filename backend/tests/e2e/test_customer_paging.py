"""Is the whole import actually in there?

Reported: "i imported the whole data ... i feel like its incomplete but i
don't want to spend forever counting."

They were right to be suspicious, and the cause was the list, not the import.
`GET /customers` is paged, the page defaults to 20 and the screen asked for
50 — with no way to reach row 51. An import of 87 customers showed 50 rows
under a heading that said 87, so the app was simultaneously telling the truth
and looking like it had lost a third of the data.

Two things have to hold for that question to be answerable without counting
by hand:

  paging is honest       every page reaches every row exactly once, the
                         total is the real total, and the last page is not
                         silently the last row anyone can see

  the file can be
  re-checked             re-uploading an already-imported file must report
                         every row as "already here" — that, and not a
                         head-count, is what proves nothing was dropped

The second is the one that answers the question directly, so it is checked
against a file that was deliberately imported only *half* way as well: a
partial import must report the remainder as missing, by name.
"""
import asyncio, io, os, sys, uuid
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


def workbook(tag: str, n: int) -> bytes:
    """`n` customers, in the shape the Accurate export writes them."""
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["ID Pelanggan", "Nama", "Kategori", "Alamat Penagihan", "Kota"])
    for i in range(1, n + 1):
        ws.append([f"C.{tag}{i:03d}", f"PT Hitung {tag} {i:03d}", "Customer Candra",
                   f"Jl. Industri {i}", "Gresik"])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:4]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")

    N = 87                                   # the real customer export's count
    data = workbook(tag, N)
    up = lambda: {"file": (f"pelanggan-{tag}.xlsx", data,
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    # ══ a partial import, and being told so ══════════════════════════════════
    print("\n── half the file imported ──")
    half = J(await c.post("/imports/customers/commit", headers=d, files=up(),
                          data={"limit": 40, "confirm": "IMPORT"}))
    check("only the batch that was asked for is created", half.get("created") == 40,
          str(half)[:160])
    check("...and it says how many are left", half.get("remaining_to_import") == N - 40,
          str(half.get("remaining_to_import")))

    prev = J(await c.post("/imports/customers/preview", headers=d, files=up()))
    check("re-reading the file finds the 40 that landed",
          prev["counts"].get("existing") == 40, str(prev["counts"]))
    check("...and names the 47 that did not",
          prev["counts"].get("create") == N - 40, str(prev["counts"]))
    missing = [r["company_name"] for r in prev["rows"] if r["action"] == "create"]
    check("...every one of them, by name", len(missing) == N - 40, str(len(missing)))
    absent = []
    for m in missing[:5]:
        absent.append(J(await c.get("/customers", headers=d,
                                    params={"q": m, "page_size": 5}))["total"])
    check("...and they really are absent", absent == [0] * len(absent), str(absent))

    # ══ the rest, and the all-clear ═════════════════════════════════════════
    print("\n── the rest imported ──")
    rest = J(await c.post("/imports/customers/commit", headers=d, files=up(),
                          data={"limit": 500, "confirm": "IMPORT"}))
    check("the remainder goes in", rest.get("created") == N - 40, str(rest)[:160])
    check("...and nothing is left over", rest.get("remaining_to_import") == 0,
          str(rest.get("remaining_to_import")))

    prev = J(await c.post("/imports/customers/preview", headers=d, files=up()))
    check("re-reading the file now finds every row already here",
          prev["counts"].get("existing") == N, str(prev["counts"]))
    check("...with nothing left to import", prev["counts"].get("create", 0) == 0,
          str(prev["counts"]))
    check("...which is the answer to 'is it all in there'",
          prev["rows_in_file"] == N
          and prev["counts"]["existing"] + prev["counts"].get("create", 0) == N,
          f"{prev['rows_in_file']} rows")

    # ══ paging that reaches every row ═══════════════════════════════════════
    print("\n── the list can actually show them all ──")
    page1 = J(await c.get("/customers", headers=d,
                          params={"q": f"PT Hitung {tag}", "page": 1, "page_size": 50}))
    check("the total is the real total", page1["total"] == N, str(page1["total"]))
    check("...and one page is not all of them", len(page1["data"]) == 50,
          str(len(page1["data"])))

    seen: list[str] = []
    for p in range(1, 10):
        got = J(await c.get("/customers", headers=d, params={
            "q": f"PT Hitung {tag}", "page": p, "page_size": 20}))
        if not got["data"]:
            break
        seen.extend(x["id"] for x in got["data"])
    check("paging through reaches every one", len(seen) == N, f"{len(seen)} of {N}")
    check("...with no row served twice", len(set(seen)) == N, str(len(set(seen))))

    big = J(await c.get("/customers", headers=d,
                        params={"q": f"PT Hitung {tag}", "page_size": 500}))
    check("...and one big page holds the lot", len(big["data"]) == N,
          str(len(big["data"])))
    check("...the same rows, not different ones",
          {x["id"] for x in big["data"]} == set(seen))

    past = J(await c.get("/customers", headers=d, params={
        "q": f"PT Hitung {tag}", "page": 99, "page_size": 50}))
    check("a page past the end is empty rather than wrong",
          past["data"] == [] and past["total"] == N, str(past["total"]))

    # ══ the count a filter reports is the count it can show ═════════════════
    print("\n── a filtered count means the same thing ──")
    users = J(await c.get("/users", headers=d, params={"role": "sales"}))
    candra = next((u for u in users if u["full_name"].lower().startswith("candra")), None)
    if candra:
        owned = J(await c.get("/customers", headers=d, params={
            "sales_pic_id": candra["id"], "page_size": 500}))
        check("the by-rep filter agrees with itself",
              owned["total"] == len(owned["data"]),
              f"{owned['total']} vs {len(owned['data'])}")
    free = J(await c.get("/customers", headers=d,
                         params={"unassigned": True, "page_size": 500}))
    check("so does the unassigned filter",
          free["total"] == len(free["data"]), f"{free['total']} vs {len(free['data'])}")
    hinted = J(await c.get("/customers", headers=d,
                           params={"rep_hint": "candra", "page_size": 500}))
    check("and the imported-name filter",
          hinted["total"] == len(hinted["data"]),
          f"{hinted['total']} vs {len(hinted['data'])}")
    check("...which found this file's customers",
          hinted["total"] >= N, str(hinted["total"]))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())
