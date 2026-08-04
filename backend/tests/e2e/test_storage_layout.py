"""How uploaded files are laid out in the bucket.

The old key was `attachments/<year>/<month>/<uuid>_<name>`. That is fine for a
program reading a path out of a database column and useless for a person who
opens the R2 console wanting the scans attached to one purchase order: every
upload in the company sits in one folder per month, named after a uuid.

The shape is now::

    attachments/<owner_type>/<year>/<month>/<owner_id>/<uuid8>_<label>_<name>

What has to hold:

* The path says what the file **is** — you can read the owner type, the month
  and the document off the key without a database.
* Everything belonging to one document shares a prefix, so `ls` on that prefix
  is that document's file list.
* **Files written under the old layout still download.** Every row stores its
  own full `s3://bucket/key` and reads dispatch on that string, so the change
  applies to new uploads only. This is the property that makes the change safe
  to ship without a migration, and the one worth a test.
* Nothing user-supplied can escape its folder. A filename is attacker-chosen;
  a `/` or a `..` inside one must not invent a path level or climb out.
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
    except: return {"_":r.text[:200]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.services import storage
    from datetime import UTC, datetime
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    tag = uuid.uuid4().hex[:5]
    now = datetime.now(UTC)
    ym = f"{now.year}/{now.month:02d}"

    # ── 1. the key itself ────────────────────────────────────────────────────
    k = storage.build_key("site-photo.jpg", owner_type="project", owner_id="abc-123")
    check("the key is grouped by owner type", k.startswith("attachments/project/"), k)
    check("...then by year and month", f"/{ym}/" in k, k)
    check("...then by the document it belongs to", f"/{ym}/abc-123/" in k, k)
    check("...and still ends in a readable filename", k.endswith("_site-photo.jpg"), k)

    k2 = storage.build_key("d.pdf", "drawing", owner_type="project", owner_id="abc-123")
    check("two files for one document share a prefix",
          k.rsplit("/", 1)[0] == k2.rsplit("/", 1)[0], f"{k}\n{k2}")
    check("a label stays in the name, so you can see what a file is",
          "_drawing_" in k2, k2)

    a, b = (storage.build_key("same.pdf", owner_type="project", owner_id="x"),
            storage.build_key("same.pdf", owner_type="project", owner_id="x"))
    check("two uploads of the same filename do not collide", a != b, f"{a}\n{b}")

    # A caller with no owner context still works — it just lands under misc/.
    k3 = storage.build_key("loose.txt")
    check("a file with no owner is not lost, it goes to misc/",
          k3.startswith(f"attachments/misc/{ym}/"), k3)
    check("...with no empty path segment where the owner would be",
          "//" not in k3, k3)

    # ── 2. nothing escapes its folder ────────────────────────────────────────
    eek = storage.build_key("../../etc/passwd", owner_type="../../root",
                            owner_id="../../..")
    check("a filename cannot invent a folder level",
          eek.count("/") == k.count("/"), eek)
    # `..` surviving inside a segment is harmless — a segment is only a
    # directory if a slash makes it one, and the stem is always prefixed with
    # hex so it can never *be* `..`. The property that matters is that no
    # segment traverses.
    check("...nor climb out of the tree",
          all(seg not in ("..", ".", "") for seg in eek.split("/")), eek)
    check("the owner type is sanitised too", eek.startswith("attachments/root/"), eek)
    weird = storage.build_key("rap💥ort.pdf", owner_type="quo tation!", owner_id="a/b")
    check("odd characters in the owner type collapse safely",
          weird.startswith("attachments/quo-tation/"), weird)
    check("...and in the owner id", f"/{ym}/a-b/" in weird, weird)

    # ── 3. the round trip through the real API ───────────────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Berkas {tag}", "industry": "mining"}))["id"]
    up = J(await c.post("/attachments", headers=s1,
                        files={"file": ("survey.txt", b"site survey", "text/plain")},
                        data={"owner_type": "customer", "owner_id": cust,
                              "description": "site survey"}))
    att_id = up.get("id")
    check("a file uploads through the API", bool(att_id), str(up)[:160])

    from sqlalchemy import select
    from app.core.db import SessionLocal
    from app.models.attachment import Attachment
    async with SessionLocal() as db:
        row = await db.get(Attachment, att_id)
        stored = row.storage_path
    check("the stored path carries the owner type",
          f"attachments/customer/{ym}/{cust}/" in stored, stored)
    check("...and the readable filename", stored.endswith("_survey.txt"), stored)

    # `customer` files are director-only to read — a deliberate
    # boundary that predates this change, so read back as the director.
    r = await c.get(f"/attachments/{att_id}/download", headers=d)
    check("it downloads back", r.status_code == 200 and r.content == b"site survey",
          f"{r.status_code} {r.content[:40]}")

    # A second file on the same customer lands beside the first.
    up2 = J(await c.post("/attachments", headers=s1,
                         files={"file": ("quote.txt", b"second", "text/plain")},
                         data={"owner_type": "customer", "owner_id": cust}))
    async with SessionLocal() as db:
        stored2 = (await db.get(Attachment, up2.get("id"))).storage_path
    check("a second file on the same customer sits in the same folder",
          stored.rsplit("/", 1)[0] == stored2.rsplit("/", 1)[0], f"{stored}\n{stored2}")

    # ── 4. the old layout keeps working ──────────────────────────────────────
    # Write a file at an old-style key by hand and point a row at it, exactly
    # as an upload from before this change would look.
    from pathlib import Path
    legacy_key = f"attachments/{now.year}/{now.month:02d}/{uuid.uuid4().hex}_old.txt"
    legacy_path = Path(os.environ["STORAGE_LOCAL_DIR"]) / legacy_key
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_bytes(b"written before the change")
    async with SessionLocal() as db:
        old_row = Attachment(
            owner_type="customer", owner_id=cust, filename="old.txt",
            content_type="text/plain", size=25, storage_path=str(legacy_path),
            description="pre-existing file",
            uploaded_by=(await db.scalars(select(Attachment.uploaded_by)
                                          .where(Attachment.id == att_id))).first(),
        )
        db.add(old_row); await db.commit(); old_id = old_row.id

    r = await c.get(f"/attachments/{old_id}/download", headers=d)
    check("a file stored under the OLD layout still downloads",
          r.status_code == 200 and r.content == b"written before the change",
          f"{r.status_code} {r.content[:40]}")
    check("...and reads through the storage service directly too",
          await storage.load(str(legacy_path)) == b"written before the change")
    check("...and the service can still see it exists",
          await storage.exists(str(legacy_path)) is True)

    listed = J(await c.get("/attachments", headers=d,
                           params={"owner_type": "customer", "owner_id": cust}))
    names = {a["filename"] for a in (listed if isinstance(listed, list) else [])}
    check("old and new files list together, indistinguishable to the user",
          {"survey.txt", "quote.txt", "old.txt"} <= names, str(names))

    # Deleting an old-layout file still removes it.
    r = await c.delete(f"/attachments/{old_id}", headers=d)
    check("an old-layout file can still be deleted", r.status_code in (200, 204),
          str(r.status_code))
    check("...and the bytes are gone", not legacy_path.exists(), str(legacy_path))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())
