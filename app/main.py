import logging

from fastapi import FastAPI, Request
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

    return app


app = create_app()

