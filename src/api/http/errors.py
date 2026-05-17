"""HTTP error handlers mapping Application API errors to HTTP responses."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from src.app.errors import (
    AppError,
    AppExecutionError,
    AppValidationError,
    ResourceUnavailableError,
    ResourceValidationError,
)


async def app_validation_error_handler(request: Request, exc: AppValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "VALIDATION_ERROR", "message": str(exc)}},
    )


async def resource_unavailable_error_handler(
    request: Request, exc: ResourceUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "RESOURCE_NOT_FOUND", "message": str(exc)}},
    )


async def resource_validation_error_handler(
    request: Request, exc: ResourceValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "RESOURCE_INVALID", "message": str(exc)}},
    )


async def app_execution_error_handler(request: Request, exc: AppExecutionError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "EXECUTION_ERROR", "message": str(exc)}},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
    )


def register_error_handlers(app) -> None:
    """Register all application error handlers on the FastAPI app."""
    app.add_exception_handler(AppValidationError, app_validation_error_handler)
    app.add_exception_handler(ResourceUnavailableError, resource_unavailable_error_handler)
    app.add_exception_handler(ResourceValidationError, resource_validation_error_handler)
    app.add_exception_handler(AppExecutionError, app_execution_error_handler)
    app.add_exception_handler(AppError, app_error_handler)
