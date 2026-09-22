"""Refreshing a session: both shapes, because the two halves deploy apart.

The refresh token used to travel only in the query string. That is the worst
place for a credential — it is written into every proxy, load-balancer and CDN
access log between the browser and here — so it moves to the body. But the
frontend is on Vercel and this is on Render, and they ship independently: for
however long one is ahead of the other, an endpoint that accepted only the new
shape would reject every refresh in flight and sign the whole company out.

So both are accepted, the body wins when both arrive, and the query copy is
what gets removed later, once nothing sends it. This pins that, and it pins
the refusals too — a rejected refresh is the one error in the system that
ends with somebody typing their password again, so it must happen only when
the token is genuinely no good.
"""
import asyncio, os, sys, uuid
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

    login = J(await c.post("/auth/login", json={
        "email": "sales1@demo.local", "password": "test-pass-123"}))
    access, refresh = login.get("access_token"), login.get("refresh_token")
    check("signing in hands back both tokens", bool(access and refresh),
          str(sorted(login.keys())))

    # ══ the shape the old frontend sends ═════════════════════════════════
    print("\n── a frontend that has not deployed yet ──")
    r = await c.post("/auth/refresh", params={"token": refresh})
    check("the token in the query string is still accepted",
          r.status_code == 200, f"{r.status_code} {J(r)}")
    old_way = J(r)
    check("...and comes back with a working pair",
          bool(old_way.get("access_token") and old_way.get("refresh_token")),
          str(sorted(old_way.keys())))

    # ══ the shape the new frontend sends ═════════════════════════════════
    print("\n── a frontend that has ──")
    r = await c.post("/auth/refresh", json={"token": refresh})
    check("the token in the body is accepted", r.status_code == 200,
          f"{r.status_code} {J(r)}")
    new_way = J(r)
    check("...and comes back with a working pair",
          bool(new_way.get("access_token") and new_way.get("refresh_token")),
          str(sorted(new_way.keys())))

    # During the changeover the frontend sends both.
    print("\n── and one sending both, during the changeover ──")
    r = await c.post("/auth/refresh", params={"token": refresh},
                     json={"token": refresh})
    check("both at once is accepted rather than being a conflict",
          r.status_code == 200, f"{r.status_code} {J(r)}")
    both = J(r)

    # The access token that comes back has to actually work, or "refreshed"
    # is a lie that surfaces as a logout one request later.
    hdr = {"Authorization": f"Bearer {both.get('access_token')}"}
    r = await c.get("/auth/me", headers=hdr)
    check("the refreshed access token opens the session it claims to",
          r.status_code == 200, f"{r.status_code} {J(r)}")
    check("...as the same person", J(r).get("email") == "sales1@demo.local",
          str(J(r).get("email")))

    # The new refresh token must itself be good, or the session dies at the
    # NEXT renewal instead of this one — a bug that looks like a random logout
    # hours later.
    r = await c.post("/auth/refresh", json={"token": both.get("refresh_token")})
    check("the refresh token it returned can itself be refreshed with",
          r.status_code == 200, f"{r.status_code} {J(r)}")

    # The old one still works too: rotation here is not revocation, and two
    # tabs refreshing a second apart must not knock each other out.
    r = await c.post("/auth/refresh", json={"token": refresh})
    check("the previous refresh token still works, so two tabs renewing at "
          "the same moment do not sign each other out",
          r.status_code == 200, f"{r.status_code} {J(r)}")

    # ══ the refusals ═════════════════════════════════════════════════════
    print("\n── when it should be refused ──")
    r = await c.post("/auth/refresh")
    check("no token at all is refused, not a 500",
          r.status_code == 401, f"{r.status_code} {J(r)}")
    r = await c.post("/auth/refresh", json={"token": ""})
    check("an empty token is refused", r.status_code == 401,
          f"{r.status_code} {J(r)}")
    r = await c.post("/auth/refresh", json={"token": "not-a-jwt"})
    check("a token that is not a token is refused", r.status_code == 401,
          f"{r.status_code} {J(r)}")
    r = await c.post("/auth/refresh", json={"token": access})
    check("an ACCESS token is refused where a refresh token belongs — they "
          "are not interchangeable",
          r.status_code == 401, f"{r.status_code} {J(r)}")

    # Signed with the wrong key: the shape is right, the signature is not.
    import jwt as _jwt
    from datetime import UTC, datetime, timedelta
    forged = _jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh",
         "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(days=1)},
        "not-the-real-secret", algorithm="HS256")
    r = await c.post("/auth/refresh", json={"token": forged})
    check("a token signed with somebody else's key is refused",
          r.status_code == 401, f"{r.status_code} {J(r)}")

    expired = _jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh",
         "iat": datetime.now(UTC) - timedelta(days=40),
         "exp": datetime.now(UTC) - timedelta(days=10)},
        os.environ["JWT_SECRET"], algorithm="HS256")
    r = await c.post("/auth/refresh", json={"token": expired})
    check("an expired refresh token is refused", r.status_code == 401,
          f"{r.status_code} {J(r)}")

    # Every refusal here ends with somebody retyping their password, so each
    # one must say something, not just fail.
    for shape in [None, {"token": "not-a-jwt"}]:
        r = (await c.post("/auth/refresh") if shape is None
             else await c.post("/auth/refresh", json=shape))
        body = J(r)
        msg = str(body.get("detail")
                  or (body.get("errors") or [{}])[0].get("message", ""))
        check(f"...and says why ({shape and shape.get('token') or 'nothing sent'})",
              len(msg) > 3, str(body)[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())
