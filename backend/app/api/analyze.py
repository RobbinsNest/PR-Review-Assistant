"""HTTP API for starting analysis tasks and streaming their progress.

- ``POST /api/analyze`` registers an async task and returns ``202 {task_id}``.
- ``GET /api/tasks/{task_id}`` returns the current task state JSON.
- ``GET /api/tasks/{task_id}/events`` streams SSE progress events
  (``text/event-stream``, ``X-Accel-Buffering: no``, 15s heartbeat comments).

The optional ``github_token`` is session-memory only: it is handed to the
task manager for the duration of the run and is never logged or persisted,
and the state responses/SSE events never include it.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.analysis_engine import AnalysisEngine
from app.services.github_fetcher import GitHubFetcher
from app.services.llm_client import LLMClient
from app.services.task_manager import TaskManager, TaskState

router = APIRouter()

#: Idle SSE connections get a comment line every 15s so proxies do not time
#: out; task state is idempotent, so a dropped connection can always resume
#: via ``GET /api/tasks/{task_id}``.
SSE_HEARTBEAT_SECONDS = 15.0

try:  # WT-3 (history-settings) reconciliation seam: prefer the shared module.
    from app.core.rate_limit import rate_limit_dependency  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only until WT-3 merges
    # WT-3 introduces backend/app/core/rate_limit.py with a shared rate
    # limiter + dependency.  Until that branch merges into this worktree,
    # apply a minimal in-process fixed-window limiter reading
    # Settings.rate_limit_per_min.  At merge, drop this fallback and keep the
    # import above.
    class _LocalRateLimiter:
        """Minimal in-process fixed-window limiter (WT-3 seam)."""

        def __init__(self, per_minute: int) -> None:
            self._per_minute = max(1, per_minute)
            self._lock = asyncio.Lock()
            self._window_start = 0.0
            self._count = 0

        async def acquire(self) -> None:
            async with self._lock:
                now = time.monotonic()
                if now - self._window_start >= 60.0:
                    self._window_start = now
                    self._count = 0
                if self._count >= self._per_minute:
                    raise AppError(
                        "rate_limited", message="too many requests, slow down"
                    )
                self._count += 1

    async def rate_limit_dependency(request: Request) -> None:
        settings = get_settings()
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            limiter = _LocalRateLimiter(settings.rate_limit_per_min)
            request.app.state.rate_limiter = limiter
        await limiter.acquire()


class AnalyzeRequest(BaseModel):
    """Body of ``POST /api/analyze``."""

    pr_url: str
    github_token: str | None = None


def _task_manager(request: Request) -> TaskManager:
    """Return the app-wide TaskManager registered on ``app.state`` (T9)."""
    return request.app.state.task_manager


def _engine(request: Request) -> AnalysisEngine:
    """Return the app-wide engine, building the default from Settings on first use."""
    engine = getattr(request.app.state, "analysis_engine", None)
    if engine is None:
        settings = get_settings()
        api_key = settings.api_key()
        if not api_key:
            raise AppError("llm_api_error", message="LLM API key not configured")
        engine = AnalysisEngine(
            LLMClient(
                base_url=settings.llm_base_url,
                api_key=api_key,
                model=settings.llm_model,
                timeout=settings.llm_timeout_sec,
            ),
            concurrency=settings.analysis_concurrency,
        )
        request.app.state.analysis_engine = engine
    return engine


def _fetcher(request: Request) -> GitHubFetcher:
    """Return the app-wide fetcher, building a tokenless default on first use."""
    fetcher = getattr(request.app.state, "github_fetcher", None)
    if fetcher is None:
        fetcher = GitHubFetcher()
        request.app.state.github_fetcher = fetcher
    return fetcher


def _public_state(state: TaskState) -> dict:
    """State JSON for clients - never includes the session-memory token."""
    return {key: value for key, value in state.items() if key != "token"}


def _sse(event: dict) -> str:
    """Serialize one SSE event as a ``data:`` frame."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post(
    "/api/analyze",
    status_code=202,
    dependencies=[Depends(rate_limit_dependency)],
)
async def analyze(request: Request, body: AnalyzeRequest) -> dict:
    """Register an analysis task; returns ``202 {"task_id": ...}``."""
    task_id = _task_manager(request).create(
        body.pr_url, body.github_token, _engine(request), _fetcher(request)
    )
    return {"task_id": task_id}


@router.get("/api/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict:
    """Return the current state JSON for a task (404 for unknown ids)."""
    state = _task_manager(request).get(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _public_state(state)


@router.get("/api/tasks/{task_id}/events")
async def task_events(request: Request, task_id: str) -> StreamingResponse:
    """Stream SSE events for a task until it finishes (404 for unknown ids)."""
    task_manager = _task_manager(request)
    if task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")

    async def event_stream() -> AsyncIterator[str]:
        try:
            queue = task_manager.subscribe(task_id)
        except KeyError:  # task vanished between the 404 check and subscribe
            yield _sse(
                {"type": "error", "code": "not_found", "message": "task not found"}
            )
            return
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=SSE_HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield _sse(event)
            if event["type"] in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
