"""FastAPI application entrypoint for the PR Review Assistant backend.

Startup (lifespan) wires structured logging, creates the SQLite parent dir
and the shared ``HistoryStore``, and instantiates the per-app rate limiter.
Shutdown closes the store and any shared HTTP clients so the long-running
process leaks no connection pools.  All routers are registered here:
health, settings, history (WT-3) and analyze (WT-2).  AppError responses
follow the ``ERROR_HTTP`` table in ``app/core/errors.py``.

When a built SPA exists at ``settings.static_dir`` the app mounts it at
``/`` with an index.html fallback so client-side routes work; the mount is
skipped when the directory is absent (API-only mode used by tests/dev).
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.analyze import router as analyze_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.settings import router as settings_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.rate_limit import RateLimiter
from app.services.history_store import HistoryStore
from app.services.task_manager import TaskManager


class SPAStaticFiles(StaticFiles):
    """StaticFiles with an index.html fallback for client-side SPA routes.

    Requests for unknown non-``api/`` paths (e.g. ``/history``) fall back to
    ``index.html`` so the React router can render them; ``api/`` paths are
    exempt so unknown API routes keep returning JSON 404s instead of the SPA
    shell.  API routers are registered before this mount, so known ``/api``
    and ``/healthz`` routes are never shadowed.
    """

    async def get_response(self, path: str, scope):
        # StaticFiles normalizes separators to the OS form on Windows, so a
        # request for /api/x arrives here as "api\\x"; normalize before the
        # API-prefix check.
        if path.replace("\\", "/").startswith("api/"):
            raise StarletteHTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _mount_static(app: FastAPI) -> None:
    """Mount the built SPA at ``/`` when ``settings.static_dir`` exists.

    Idempotent: repeated startups (e.g. one TestClient per test) never stack
    duplicate mounts.  Without a built frontend the mount is skipped and the
    app serves the API only.
    """
    for route in app.router.routes:
        if getattr(route, "name", None) == "spa":
            return
    static_dir = Path(get_settings().static_dir)
    if static_dir.is_dir():
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="spa")


def _unmount_static(app: FastAPI) -> None:
    """Remove the SPA mount added by :func:`_mount_static` (shutdown)."""
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "name", None) != "spa"
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging + storage + rate limiter + SPA mount; shutdown: close."""
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
        _mount_static(app)
        yield
    finally:
        _unmount_static(app)
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
app.include_router(analyze_router)

#: In-memory async task registry backing /api/analyze and /api/tasks (T9).
#: The app keeps exactly one instance; tests replace it with a fresh one.
app.state.task_manager = TaskManager()


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
