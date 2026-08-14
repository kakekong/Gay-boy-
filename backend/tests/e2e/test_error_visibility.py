"""A server error the browser is allowed to read.

Reported as "when I try to approve as director it says network error even
though I have good wifi". The wifi was fine. The server was throwing a 500,
and the browser was refusing to let the page read it.

FastAPI wires a catch-all `Exception` handler into Starlette's
ServerErrorMiddleware, which wraps every other middleware — including CORS.
So a 500 went back with no `Access-Control-Allow-Origin`, the browser blocked
the response, and axios reported the only thing left to report: a bare
"Network Error". Every 4xx was fine, because those are raised as
HTTPException and handled *inside* the CORS layer. The one response class
that carried a real diagnosis was the one class nobody could see.

The fix puts the header on that response itself, re-checking the allowlist
rather than reflecting whatever Origin turned up — a 500 body carries the
exception message, and handing that to any site that asks would be a worse
bug than the one being fixed.

What this driver pins down is the header, on all three classes of response
and for both a caller we trust and one we don't.
"""
import asyncio, os, sys
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))


async def main():
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from app.core.config import settings
    from app.core.errors import install_error_handlers

    OURS = "https://transmisisuplindo.com"
    THEIRS = "https://not-us.example"
    settings.CORS_ORIGINS = [OURS]

    # The real app's wiring, minus the routes: CORS added as middleware, the
    # error handlers installed after it. Reproducing the arrangement is the
    # point — the defect was in how the two compose, not in either alone.
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                       allow_credentials=True, allow_methods=["*"],
                       allow_headers=["*"])
    install_error_handlers(app)

    @app.post("/ok")
    async def ok():
        return {"ok": True}

    @app.post("/refused")
    async def refused():
        raise HTTPException(403, "not yours to approve")

    @app.post("/approve")
    async def approve():
        # What a missing column or a bad payload looks like from the outside.
        raise RuntimeError("column supplier_pos.fx_rate does not exist")

    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://t", timeout=30)

    async def call(path, origin):
        return await c.post(path, headers={"Origin": origin})

    print("\n── the page can read every answer it is given ──")
    r = await call("/ok", OURS)
    check("a success comes back readable", r.status_code == 200
          and r.headers.get("access-control-allow-origin") == OURS,
          f"{r.status_code} {r.headers.get('access-control-allow-origin')}")
    r = await call("/refused", OURS)
    check("a refusal comes back readable, with its reason",
          r.status_code == 403
          and r.headers.get("access-control-allow-origin") == OURS
          and "not yours" in r.text,
          f"{r.status_code} {r.headers.get('access-control-allow-origin')} {r.text[:80]}")

    r = await call("/approve", OURS)
    check("a crash comes back as a 500, not as nothing", r.status_code == 500,
          str(r.status_code))
    check("...and the browser is allowed to read it",
          r.headers.get("access-control-allow-origin") == OURS,
          str(r.headers.get("access-control-allow-origin")))
    check("...so the user sees the cause instead of 'network error'",
          "fx_rate" in r.text, r.text[:120])
    check("...and credentialed requests are told so too",
          r.headers.get("access-control-allow-credentials") == "true",
          str(r.headers.get("access-control-allow-credentials")))
    check("...with Vary: Origin, so a proxy can't cache one site's answer "
          "for another", "origin" in (r.headers.get("vary") or "").lower(),
          str(r.headers.get("vary")))

    print("\n── and no more than that ──")
    # The 500 body carries the exception message. Echoing the Origin back
    # unchecked would hand our stack traces to anything that asked.
    for path in ("/ok", "/refused", "/approve"):
        r = await call(path, THEIRS)
        check(f"a site we don't know still cannot read {path}",
              r.headers.get("access-control-allow-origin") is None,
              str(r.headers.get("access-control-allow-origin")))

    r = await c.post("/approve")          # no Origin at all — server to server
    check("a request with no Origin gets no header invented for it",
          r.status_code == 500
          and r.headers.get("access-control-allow-origin") is None,
          f"{r.status_code} {r.headers.get('access-control-allow-origin')}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())
