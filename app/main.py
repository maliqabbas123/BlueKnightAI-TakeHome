import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware import RequestIdMiddleware
from app.routers.reports import router as reports_router
from app.services.errors import AppError


def create_app() -> FastAPI:
    logging.basicConfig(level=get_settings().log_level, format="%(message)s")
    app = FastAPI(title="BlueKnight MRR Collaboration")
    app.add_middleware(RequestIdMiddleware)
    app.include_router(reports_router)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        code = "http_error"
        message = exc.detail
        if exc.status_code == 401:
            code = "unauthenticated"
            message = "unauthenticated"
        elif exc.status_code == 403:
            code = "forbidden"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "request validation failed", "details": exc.errors()}},
        )

    return app


app = create_app()
