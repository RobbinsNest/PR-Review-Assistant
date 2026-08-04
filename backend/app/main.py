"""FastAPI application entrypoint for the PR Review Assistant backend."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.core.errors import AppError

app = FastAPI(title="PR Review Assistant")

app.include_router(health_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "http_error", "message": str(exc.detail)}},
    )
