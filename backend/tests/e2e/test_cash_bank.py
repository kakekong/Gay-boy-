"""Kas & Bank — money out, money in, money moved; and the invoice's own screen.

Asked for: *"continue with kas & bank and also make it so that the invoice has
the same open view"* — the same treatment the delivery order got, applied to
the invoice beside it.

**Kas & Bank is the desk in front of the journal.** Nobody paying a supplier
thinks in debits and credits; they think "eight million out of BCA to PT
Sinar, transfer, slip 88123, for the chain and the freight". So the document
carries the payee, the method, the slip number and the split across accounts,
and the balanced entry writes itself underneath. Three kinds, and the only
real difference between them is which way the money went:

- **Pembayaran** credits the bank and debits what it was for.
- **Penerimaan** debits the bank and credits what it came from.
- **Transfer Bank** moves between two of our own accounts. Its own kind on
  purpose: booked as a payment it would read as money spent, and the profit
  report would be wrong by the amount of every transfer ever made.

**Rekening Koran** is the reconciliation. Our balance is what the books say;
the bank's is what has actually cleared. Ticking lines off is what closes the
gap, and the page states the gap rather than leaving it to be worked out.

**And nothing here is edited after the fact.** Voiding reverses the journal
and leaves both on the record — the same rule the journal keeps, for the same
reason.

**The invoice's own screen** is the other half: the money it bills, what has
landed against it, the tax number, the files, the discussion — none of which
fitted in a row on the project page.
"""
import asyncio, os, sys, uuid
from datetime import date, timedelta
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
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]
    today = date.today()

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")
    adm = await login("admin@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    banks = J(await c.get("/cash/accounts", headers=fin))
    check("the company's own accounts are listed", len(banks) >= 2,
          str(banks)[:200])
    if len(banks) < 2:
        sys.exit(1)
    bank_a, bank_b = banks[0], banks[1]

    accs = J(await c.get("/accounts", headers=fin, params={"limit": 500}))
    rows = accs if isinstance(accs, list) else accs.get("items", [])
    expense = next(a for a in rows if a["account_type"] == "Expense"
                   and not a.get("is_parent") and not a.get("is_suspended"))
    income = next(a for a in rows if a["account_type"] in ("Revenue", "Other Income")
                  and not a.get("is_parent") and not a.get("is_suspended"))

    async def balance(no):
        data = J(await c.get("/accounts", headers=fin,
                             params={"q": no, "limit": 500}))
        got = data if isinstance(data, list) else data.get("items", [])
        row = next((a for a in got if a["account_no"] == no), None)
        return float((row or {}).get("balance") or 0)

    a_before, exp_before = await balance(bank_a["account_no"]), await balance(expense["account_no"])

    # ══ money out ════════════════════════════════════════════════════════════
    print("\n── a payment ──")
    r = await c.post("/cash", headers=fin, json={
        "kind": "payment", "tx_date": today.isoformat(),
        "bank_account_no": bank_a["account_no"],
        "counterparty": f"PT Sinar {tag}", "method": "transfer",
        "reference": f"SLIP-{tag}", "memo": f"chain and freight {tag}",
        "lines": [{"account_no": expense["account_no"], "amount": 6_000_000,
                   "memo": "chain"},
                  {"account_no": expense["account_no"], "amount": 2_000_000,
                   "memo": "freight"}]})
    check("a payment records", r.status_code == 201, f"{r.status_code} {str(J(r))[:170]}")
    pay = J(r)
    check("...numbered like the slip a cash desk already keeps",
          pay["number"].startswith("BKK-"), str(pay.get("number")))
    check("...adding its lines up", float(pay["amount"]) == 8_000_000.0,
          str(pay.get("amount")))
    check("...and carrying who it went to and on what slip",
          pay["counterparty"] == f"PT Sinar {tag}" and pay["reference"] == f"SLIP-{tag}",
          str(pay)[:200])
    check("...with the split kept, so the profit report can say which three things",
          len(pay["lines"]) == 2, str(pay.get("lines"))[:170])
    check("the bank went down by what left it",
          abs(await balance(bank_a["account_no"]) - (a_before - 8_000_000)) < 0.01,
          f"{await balance(bank_a['account_no'])} vs {a_before - 8_000_000}")
    check("...and the expense went up by the same",
          abs(await balance(expense["account_no"]) - (exp_before + 8_000_000)) < 0.01,
          str(await balance(expense["account_no"])))
    check("...through a journal entry that exists and balances",
          bool(pay.get("journal_id")), str(pay.get("journal_id")))
    entry = J(await c.get(f"/journals/{pay['journal_id']}", headers=fin))
    check("...naming both sides", len(entry["lines"]) == 3, str(entry)[:200])
    check("...and filed as a cash entry, not a hand-typed one",
          entry["source_type"] == "cash" and entry["source_ref"] == pay["number"],
          str(entry)[:200])

    # ══ money in ═════════════════════════════════════════════════════════════
    print("\n── a receipt ──")
    a_now = await balance(bank_a["account_no"])
    r = await c.post("/cash", headers=fin, json={
        "kind": "receipt", "tx_date": today.isoformat(),
        "bank_account_no": bank_a["account_no"],
        "counterparty": f"PT Pelanggan {tag}", "method": "transfer",
        "memo": f"scrap sale {tag}",
        "lines": [{"account_no": income["account_no"], "amount": 1_500_000}]})
    check("a receipt records", r.status_code == 201, f"{r.status_code} {str(J(r))[:170]}")
    rec = J(r)
    check("...numbered in its own series", rec["number"].startswith("BKM-"),
          str(rec.get("number")))
    check("the bank went up by what arrived",
          abs(await balance(bank_a["account_no"]) - (a_now + 1_500_000)) < 0.01,
          str(await balance(bank_a["account_no"])))

    # ══ moving between our own accounts ══════════════════════════════════════
    print("\n── a transfer ──")
    a_now, b_before = await balance(bank_a["account_no"]), await balance(bank_b["account_no"])
    r = await c.post("/cash", headers=fin, json={
        "kind": "transfer", "tx_date": today.isoformat(),
        "bank_account_no": bank_a["account_no"],
        "to_account_no": bank_b["account_no"],
        "amount": 2_000_000, "memo": f"topping up {tag}"})
    check("a transfer records", r.status_code == 201, f"{r.status_code} {str(J(r))[:170]}")
    tr = J(r)
    check("...in its own series again", tr["number"].startswith("BTR-"),
          str(tr.get("number")))
    check("one account went down",
          abs(await balance(bank_a["account_no"]) - (a_now - 2_000_000)) < 0.01,
          str(await balance(bank_a["account_no"])))
    check("...and the other up by exactly the same",
          abs(await balance(bank_b["account_no"]) - (b_before + 2_000_000)) < 0.01,
          str(await balance(bank_b["account_no"])))
    # The point of it being its own kind.
    exp_after = await balance(expense["account_no"])
    check("...while nothing was spent — a transfer is not expenditure",
          abs(exp_after - (exp_before + 8_000_000)) < 0.01, str(exp_after))

    r = await c.post("/cash", headers=fin, json={
        "kind": "transfer", "bank_account_no": bank_a["account_no"],
        "to_account_no": bank_a["account_no"], "amount": 100})
    check("...and the same account on both sides is refused",
          r.status_code == 400, f"{r.status_code} {str(J(r))[:130]}")
    r = await c.post("/cash", headers=fin, json={
        "kind": "payment", "bank_account_no": expense["account_no"],
        "lines": [{"account_no": expense["account_no"], "amount": 100}]})
    check("money can only move through a Cash & Bank account",
          r.status_code == 400 and "Cash & Bank" in str(J(r)),
          f"{r.status_code} {str(J(r))[:150]}")
    r = await c.post("/cash", headers=fin, json={
        "kind": "payment", "bank_account_no": bank_a["account_no"], "lines": []})
    check("...and a payment has to say what it was for",
          r.status_code == 400, f"{r.status_code} {str(J(r))[:130]}")

    # ══ the bank statement ═══════════════════════════════════════════════════
    print("\n── the statement, and reconciling it ──")
    st = J(await c.get(f"/cash/statement/{bank_a['account_no']}", headers=fin))
    check("the statement opens on the account",
          st["account"]["account_no"] == bank_a["account_no"], str(st)[:170])
    mine = {x["number"] for x in st["items"]}
    check("...carrying everything that moved through it",
          {pay["number"], rec["number"], tr["number"]} <= mine, str(sorted(mine))[:200])
    row_pay = next(x for x in st["items"] if x["number"] == pay["number"])
    row_rec = next(x for x in st["items"] if x["number"] == rec["number"])
    row_tr = next(x for x in st["items"] if x["number"] == tr["number"])
    check("...with money out shown as out", row_pay["direction"] == "out"
          and row_pay["amount"] < 0, str(row_pay)[:150])
    check("...money in as in", row_rec["direction"] == "in" and row_rec["amount"] > 0,
          str(row_rec)[:150])
    check("...and the transfer reading as out of THIS account",
          row_tr["direction"] == "out", str(row_tr)[:150])
    other = J(await c.get(f"/cash/statement/{bank_b['account_no']}", headers=fin))
    row_tr_b = next(x for x in other["items"] if x["number"] == tr["number"])
    check("...and as in, on the account it went to — one row, two statements",
          row_tr_b["direction"] == "in", str(row_tr_b)[:150])

    check("nothing has cleared yet, so the bank should show less than we do",
          st["cleared_total"] == 0 and st["statement_balance"] != st["account"]["balance"],
          f"{st['cleared_total']} / {st['statement_balance']} vs {st['account']['balance']}")
    r = await c.post(f"/cash/{pay['id']}/clear", headers=fin, json={"cleared": True})
    check("a line can be ticked off against the bank's own copy",
          r.status_code == 200, f"{r.status_code} {str(J(r))[:130]}")
    st2 = J(await c.get(f"/cash/statement/{bank_a['account_no']}", headers=fin))
    check("...which moves it out of the outstanding column",
          abs(st2["cleared_total"] + 8_000_000) < 0.01, str(st2["cleared_total"]))
    check("...and closes the gap by that much",
          abs((st2["statement_balance"] - st["statement_balance"]) + 8_000_000) < 0.01,
          f"{st['statement_balance']} → {st2['statement_balance']}")
    only = J(await c.get(f"/cash/statement/{bank_a['account_no']}", headers=fin,
                         params={"uncleared_only": True}))
    check("...and asking for what is still outstanding leaves it out",
          pay["number"] not in {x["number"] for x in only["items"]},
          str([x["number"] for x in only["items"]])[:170])
    r = await c.post(f"/cash/{pay['id']}/clear", headers=fin, json={"cleared": False})
    check("a tick can be taken back", r.status_code == 200
          and J(r).get("cleared_on") is None, str(J(r))[:130])

    # ══ voiding ══════════════════════════════════════════════════════════════
    print("\n── voiding one ──")
    a_now = await balance(bank_a["account_no"])
    r = await c.post(f"/cash/{rec['id']}/void", headers=fin,
                     params={"reason": f"duplicate {tag}"})
    check("a transaction can be voided", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:150]}")
    check("...which puts the money back exactly",
          abs(await balance(bank_a["account_no"]) - (a_now - 1_500_000)) < 0.01,
          str(await balance(bank_a["account_no"])))
    check("...by reversing the entry rather than deleting it",
          J(await c.get(f"/journals/{rec['journal_id']}", headers=fin))
          .get("reversed_by_id") is not None, "no reversal on the journal")
    check("...and it stays on the record, marked",
          J(await c.get(f"/cash/{rec['id']}", headers=fin))["is_void"] is True,
          "not marked void")
    again = await c.post(f"/cash/{rec['id']}/void", headers=fin)
    check("...once only", again.status_code == 409, str(again.status_code))
    await c.post(f"/cash/{tr['id']}/clear", headers=fin, json={"cleared": True})
    r = await c.post(f"/cash/{tr['id']}/void", headers=fin)
    check("a reconciled line can't be voided out from under the statement",
          r.status_code == 409, f"{r.status_code} {str(J(r))[:150]}")

    # ══ who runs the cash desk ═══════════════════════════════════════════════
    print("\n── who may ──")
    r = await c.get("/cash", headers=mgr)
    check("a manager can read the cash book", r.status_code == 200, str(r.status_code))
    r = await c.post("/cash", headers=mgr, json={
        "kind": "payment", "bank_account_no": bank_a["account_no"],
        "lines": [{"account_no": expense["account_no"], "amount": 100}]})
    check("...but not spend from it", r.status_code in (401, 403), str(r.status_code))
    for label, hdr in (("sales", s1), ("admin", adm), ("purchasing", pur)):
        r = await c.get("/cash", headers=hdr)
        check(f"{label} cannot open the cash book",
              r.status_code in (401, 403), str(r.status_code))

    # ══ the invoice's own screen ═════════════════════════════════════════════
    print("\n── an invoice on its own screen ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Faktur {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN {tag}", "qty": 2, "uom": "EA"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d,
                 json={"items": [{"line_no": 1, "cost_price": 500000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 1000000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    po_no = f"PO-INV-{tag}"
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": po_no,
        "items": [{"description": f"CHAIN {tag}", "qty": 2, "uom": "EA",
                   "unit_price": 1000000}], "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    await c.post(f"/operation/projects/{proj}/qc", headers=adm, json={"decision": "pass"})
    issued = J(await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                            data={"invoice_type": "final",
                                  "create_delivery_order": "true"}))
    inv_id, inv_no = issued["invoice"]["id"], issued["invoice"]["number"]

    r = await c.get(f"/finance/invoices/{inv_id}", headers=fin)
    check("an invoice opens on its own", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:150]}")
    v = J(r)
    check("...headed by its number and kind", v["number"] == inv_no
          and v["type"] == "final", str(v)[:200])
    check("...naming the customer and the project",
          v["customer_name"] == f"PT Faktur {tag}" and v["project_code"],
          f"{v.get('customer_name')} / {v.get('project_code')}")
    check("...and the customer's PO it bills against", v["po_number"] == po_no,
          str(v.get("po_number")))
    check("...with the money broken out, not just a total",
          abs(v["amount"] + v["tax_amount"] - v["total"]) < 0.01,
          f"{v['amount']} + {v['tax_amount']} vs {v['total']}")
    check("...saying what is still outstanding",
          abs(v["outstanding"] - v["total"]) < 0.01 and v["paid_amount"] == 0,
          f"{v.get('outstanding')} / {v.get('paid_amount')}")
    check("...and that it is waiting for finance",
          v["status"] == "pending_finance" and v["may"]["approve"] is True,
          f"{v.get('status')} {v.get('may')}")
    check("...which is not admin's to give",
          J(await c.get(f"/finance/invoices/{inv_id}", headers=adm))
          ["may"]["approve"] is False, "admin offered the sign-off")
    check("...though admin may still correct it before it is signed",
          J(await c.get(f"/finance/invoices/{inv_id}", headers=adm))["may"]["edit"] is True,
          "admin cannot edit an unsigned invoice")
    check("...and nothing prints yet", v["may"]["download"] is False,
          str(v.get("may")))

    fp = f"010.000-26.{tag}"
    await c.post(f"/finance/invoices/{inv_id}/approve", headers=fin,
                 data={"faktur_pajak_no": fp})
    v2 = J(await c.get(f"/finance/invoices/{inv_id}", headers=fin))
    check("once signed, the screen says so", v2["status"] == "approved",
          str(v2.get("status")))
    check("...carries the tax number", v2["faktur_pajak_no"] == fp,
          str(v2.get("faktur_pajak_no")))
    check("...offers the sheet", v2["may"]["download"] is True, str(v2.get("may")))
    check("...and closes the edit, because it belongs to the tax record now",
          v2["may"]["edit"] is False and "tax record" in (v2.get("locked_because") or ""),
          f"{v2.get('may')} / {v2.get('locked_because')}")

    r = await c.get(f"/finance/invoices/{inv_id}", headers=s1)
    check("sales cannot open an invoice's screen", r.status_code in (401, 403),
          str(r.status_code))
    r = await c.get(f"/finance/invoices/{inv_id}", headers=pur)
    check("...nor purchasing, who never bills", r.status_code in (401, 403),
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())
