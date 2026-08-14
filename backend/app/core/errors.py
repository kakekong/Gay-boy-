from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _envelope(data=None, errors=None, meta=None, status_code=200):
    return JSONResponse(
        status_code=status_code,
        content={"data": data, "errors": errors, "meta": meta},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(_: Request, exc: StarletteHTTPException):
        return _envelope(
            errors=[{"code": _code_for(exc.status_code), "message": exc.detail}],
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError):
        return _envelope(
            errors=[{"code": "VALIDATION_ERROR", "message": "Invalid payload",
                     "details": exc.errors()}],
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception):
        resp = _envelope(
            errors=[{"code": "INTERNAL_ERROR", "message": str(exc)}],
            status_code=500,
        )
        # This one handler runs OUTSIDE the CORS middleware — FastAPI wires a
        # catch-all `Exception` handler into Starlette's ServerErrorMiddleware,
        # which wraps everything else. So a 500 used to go back to the browser
        # with no Access-Control-Allow-Origin, the browser refused to let the
        # page read it, and axios reported the only thing it could see: a bare
        # "Network Error". Users went looking at their wifi while the server
        # had a stack trace waiting. 4xx are fine — those are raised as
        # HTTPException and handled inside the CORS layer — so this is the
        # only response that has to put the header on itself.
        origin = _allowed_origin(request)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Vary"] = "Origin"
        return resp


def _allowed_origin(request: Request) -> str | None:
    """The Origin to echo back, if this one is allowed to read our replies.

    Deliberately re-checks the allowlist rather than reflecting whatever the
    caller sent: a 500 body carries the exception message, and handing that to
    any origin that asks would be a worse bug than the one this fixes.
    """
    origin = request.headers.get("origin")
    if not origin:
        return None
    try:
        from app.core.config import settings
        allowed = list(settings.CORS_ORIGINS or [])
    except Exception:
        return None
    if "*" in allowed:
        return "*"
    return origin if origin in allowed else None


def _code_for(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
    }.get(status_code, "ERROR")
