"""FastAPI application entrypoint for the PR Review Assistant backend.

Startup (lifespan) wires structured logging, creates the SQLite parent dir
and the shared ``HistoryStore``, and instantiates the per-app rate limiter.
Shutdown closes the store and any shared HTTP clients so the long-running
process leaks no connection pools.  All routers merged so far (health,
settings, history) are registered; the analyze router (T9) joins in its own
worktree.  AppError responses follow the ``ERROR_HTTP`` table in
``app/core/errors.py``.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.settings import router as settings_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.rate_limit import RateLimiter
from app.services.history_store import HistoryStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging + storage + rate limiter; shutdown: close shared state."""
    setup_logging()
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    store = HistoryStore(settings.database_path)
    # init() opens the SQLite connection; it lives inside the try so the
    # connection is always closed even when init() itself raises, and a
    # failed startup leaks no DB handle.
    try:
        await store.init()
        app.state.history_store = store
        app.state.rate_limiter = RateLimiter(limit=settings.rate_limit_per_min)
        yield
    finally:
        await store.close()


app = FastAPI(title="PR Review Assistant", lifespan=lifespan)

# CORS: same-origin by default; CORS_ORIGINS is a comma-separated allowlist.
_cors_origins = [
    origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()
]
if _cors_origins:
    # Browsers reject a "*" origin combined with allow_credentials=True (a
    # credentialed wildcard request is never permitted), so when a wildcard
    # origin is configured we disable credentials instead of refusing to
    # start. Explicit origins keep credential support.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials="*" not in _cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(settings_router)
app.include_router(history_router)
# Seam: analyze router (T9) merges from its worktree.


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
