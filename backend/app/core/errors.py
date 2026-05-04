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
    async def unhandled_exc(_: Request, exc: Exception):
        return _envelope(
            errors=[{"code": "INTERNAL_ERROR", "message": str(exc)}],
            status_code=500,
        )


def _code_for(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
    }.get(status_code, "ERROR")
