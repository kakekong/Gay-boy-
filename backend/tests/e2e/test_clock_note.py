"""Clock-in / clock-out carry an optional note.

The note shares the day's single `notes` column with HR's manual entry, so the
thing worth pinning is that nobody overwrites anybody: clocking out keeps the
clock-in note, and an HR note written in between survives both.
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
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)

    # A throwaway user, so re-runs never collide on the one-row-per-user-per-day
    # unique constraint.
    tag=uuid.uuid4().hex[:6]
    email=f"clocknote-{tag}@demo.local"
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.user import User
    async with SessionLocal() as db:
        u=User(email=email, full_name=f"Clock Note {tag}", role="sales",
               password_hash=hash_password("test-pass-123"), is_active=True)
        db.add(u); await db.commit(); uid=str(u.id)
    H=await login(c,email)
    hr=await login(c,"hr@demo.local")

    r=await c.post("/attendance/clock-in",headers=H,json={"note":"Late, traffic on the toll road"})
    check("clock-in accepts a note", r.status_code==201, J(r))
    check("the note is stored on the day",
          "Late, traffic on the toll road" in (J(r).get("notes") or ""), J(r).get("notes"))

    t=J(await c.get("/attendance/me/today",headers=H))
    check("today's card serves the note back",
          "traffic on the toll road" in (t.get("notes") or ""), t.get("notes"))

    # HR annotates the same day between the two punches.
    rows=J(await c.get("/attendance",headers=hr))
    rows=rows if isinstance(rows,list) else rows.get("items",[])
    mine=next((x for x in rows if str(x.get("user_id"))==uid), None)
    check("HR can see the row", mine is not None)
    if mine:
        r=await c.patch(f"/attendance/{mine['id']}",headers=hr,
                        json={"notes":(mine.get("notes") or "")+"\nHR: counted as late"})
        check("HR note saved", r.status_code<300, J(r))

    r=await c.post("/attendance/clock-out",headers=H,json={"note":"Left early for the site visit"})
    check("clock-out accepts a note", r.status_code==200, J(r))
    notes=J(r).get("notes") or ""
    check("clock-out keeps the clock-in note", "traffic on the toll road" in notes, notes)
    check("clock-out keeps HR's note", "counted as late" in notes, notes)
    check("clock-out note is recorded", "Left early for the site visit" in notes, notes)
    check("each line is labelled", "In:" in notes and "Out:" in notes, notes)

    # A punch with no note must not append a blank line or clear anything.
    tag2=uuid.uuid4().hex[:6]
    email2=f"clocknote-{tag2}@demo.local"
    async with SessionLocal() as db:
        u2=User(email=email2, full_name=f"Clock Bare {tag2}", role="sales",
                password_hash=hash_password("test-pass-123"), is_active=True)
        db.add(u2); await db.commit()
    H2=await login(c,email2)
    r=await c.post("/attendance/clock-in",headers=H2,json={"note":"  "})
    check("a whitespace-only note leaves notes empty", not (J(r).get("notes") or ""), J(r).get("notes"))
    r=await c.post("/attendance/clock-out",headers=H2)
    check("clock-out with no body still works", r.status_code==200, J(r))
    check("still no note", not (J(r).get("notes") or ""), J(r).get("notes"))
    check("hours were computed", J(r).get("hours") is not None, J(r))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)

asyncio.run(main())
