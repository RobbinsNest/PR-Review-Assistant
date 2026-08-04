"""FastAPI application entrypoint for the PR Review Assistant backend."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.analyze import router as analyze_router
from app.core.errors import AppError
from app.services.task_manager import TaskManager

app = FastAPI(title="PR Review Assistant")

# WT-3 (history-settings) reconciliation seam:
#   WT-3 runs in parallel and also edits this file (lifespan for SQLite init,
#   CORS middleware, settings router).  Do NOT duplicate that logic here; it
#   will be reconciled at merge.  This worktree only adds the T9 analyze
#   router and the in-memory TaskManager on app.state.
app.include_router(health_router)
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
