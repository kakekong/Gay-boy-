"""Daily log: write, edit, links, file attach, history, team view, scoping."""
import asyncio
import io
import os
import sys
from datetime import date, timedelta

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test"
os.environ["APP_ENV"] = "dev"
os.environ["DEMO_SEED_PASSWORD"] = "test-pass-123"
os.environ["STORAGE_LOCAL_DIR"] = "/tmp/storage_test"
os.environ["JWT_SECRET"] = "e2e-test-secret"

sys.path.insert(0, "/home/user/Gay-boy-/backend")

import httpx  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


async def login(c, email):
    r = await c.post("/auth/login", json={"email": email, "password": "test-pass-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def main():
    from app.scripts.seed import ensure_schema
    await ensure_schema()

    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://test/api/v1")
    sales_h = await login(c, "sales1@demo.local")
    sales2_h = await login(c, "sales2@demo.local")
    dir_h = await login(c, "director@demo.local")
    today = date.today().isoformat()

    # Empty stub for a date never written
    stub_date = (date.today() - timedelta(days=400)).isoformat()
    r = await c.get("/attendance/daily-log", headers=sales_h, params={"date": stub_date})
    check("stub when none", r.status_code == 200 and r.json()["id"] is None, r.text[:200])
    check("stub editable (past date)", r.json().get("editable") is True)

    # Create with body + links (bare domain should get https://)
    r = await c.put("/attendance/daily-log", headers=sales_h, json={
        "date": today,
        "body": "Followed up PT Bara Kalsel; drafted revised BOM.",
        "links": [{"label": "BOM", "url": "docs.google.com/x"},
                  {"label": "", "url": "https://jira.local/T-12"}],
    })
    check("create 200", r.status_code == 200, r.text[:200])
    log = r.json()
    log_id = log["id"]
    check("has id", bool(log_id))
    check("link normalized to https", log["links"][0]["url"].startswith("https://docs.google.com"),
          str(log["links"]))

    # GET now returns the saved content
    r = await c.get("/attendance/daily-log", headers=sales_h, params={"date": today})
    check("get returns body", "Bara Kalsel" in r.json()["body"], r.text[:200])
    check("get same id (upsert, not dup)", r.json()["id"] == log_id)

    # Update (edit body, drop a link)
    r = await c.put("/attendance/daily-log", headers=sales_h, json={
        "date": today, "body": "Edited: closed the BOM.", "links": [
            {"label": "BOM", "url": "https://docs.google.com/x"}]})
    check("update keeps same id", r.json()["id"] == log_id, r.text[:200])
    check("update body applied", "Edited" in r.json()["body"])
    check("update links applied", len(r.json()["links"]) == 1)

    # Attach a file to the log
    files = {"file": ("note.txt", io.BytesIO(b"daily evidence"), "text/plain")}
    r = await c.post("/attachments", headers=sales_h,
                     data={"owner_type": "daily_log", "owner_id": log_id}, files=files)
    check("file attach 201", r.status_code == 201, r.text[:200])

    r = await c.get("/attendance/daily-log", headers=sales_h, params={"date": today})
    check("file_count reflects attach", r.json()["file_count"] >= 1, r.text[:200])

    # History lists it
    r = await c.get("/attendance/daily-log/history", headers=sales_h)
    check("history includes today", any(l["id"] == log_id for l in r.json()), r.text[:200])

    # Future date rejected
    future = (date.today() + timedelta(days=2)).isoformat()
    r = await c.put("/attendance/daily-log", headers=sales_h,
                    json={"date": future, "body": "nope", "links": []})
    check("future date rejected", r.status_code == 400, r.text[:120])

    # Scoping: sales2's own log is separate; sales2 can't see sales1's via own GET
    r = await c.put("/attendance/daily-log", headers=sales2_h,
                    json={"date": today, "body": "sales2 stuff", "links": []})
    check("sales2 own log distinct", r.json()["id"] != log_id, r.text[:120])
    r = await c.get("/attendance/daily-log", headers=sales2_h, params={"date": today})
    check("sales2 sees only own", "sales2 stuff" in r.json()["body"])

    # Attachment ownership: sales2 can't list or upload to sales1's log files;
    # the owner and an overseer (director) can list them.
    r = await c.get("/attachments", headers=sales2_h,
                    params={"owner_type": "daily_log", "owner_id": log_id})
    check("peer can't list others' log files", r.status_code == 403, str(r.status_code))
    r = await c.get("/attachments", headers=sales_h,
                    params={"owner_type": "daily_log", "owner_id": log_id})
    check("owner can list own log files", r.status_code == 200, str(r.status_code))
    r = await c.get("/attachments", headers=dir_h,
                    params={"owner_type": "daily_log", "owner_id": log_id})
    check("director (overseer) can list log files", r.status_code == 200, str(r.status_code))
    files2 = {"file": ("sneaky.txt", io.BytesIO(b"x"), "text/plain")}
    r = await c.post("/attachments", headers=sales2_h,
                     data={"owner_type": "daily_log", "owner_id": log_id}, files=files2)
    check("peer can't upload to others' log", r.status_code == 403, str(r.status_code))

    # Team view: director sees everyone; sales is forbidden
    r = await c.get("/attendance/daily-log/team", headers=dir_h, params={"date": today})
    check("director team view ok", r.status_code == 200, r.text[:120])
    names = {l["user_id"] for l in r.json()}
    check("team view has both authors", len(names) >= 2, str(len(names)))
    check("team entries carry names", all("user_name" in l for l in r.json()))
    r = await c.get("/attendance/daily-log/team", headers=sales_h, params={"date": today})
    check("sales forbidden from team view", r.status_code == 403, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


asyncio.run(main())
