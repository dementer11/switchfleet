from __future__ import annotations

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.exceptions import ApprovalRequiredError, ConflictError, NotFoundError, SafetyError
from app.core.logging import configure_logging


async def _approval_required_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


async def _safety_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


async def _conflict_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


async def _not_found_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title="Network Control Platform",
        version="0.2.0",
        description="Intent-based multi-vendor switch management platform.",
    )
    application.include_router(api_router)
    application.add_exception_handler(ApprovalRequiredError, _approval_required_handler)
    application.add_exception_handler(SafetyError, _safety_error_handler)
    application.add_exception_handler(ConflictError, _conflict_error_handler)
    application.add_exception_handler(NotFoundError, _not_found_error_handler)
    return application


app = create_app()
