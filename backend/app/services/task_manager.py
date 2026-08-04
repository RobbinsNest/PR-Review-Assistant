"""In-memory async task registry for ``/api/analyze`` runs with SSE progress.

Each :meth:`TaskManager.create` call registers a task, schedules ``_run`` as
an ``asyncio`` task, and returns a ``uuid4`` task id.  ``_run`` advances the
state machine ``pending -> fetching -> building -> analyzing -> verifying ->
aggregating -> succeeded/failed/cancelled`` and pushes one event per stage to
every subscribed queue:

- ``{"type": "stage", "stage": "...", "done": n, "total": m}``
- ``{"type": "done", "result": {...}}``
- ``{"type": "error", "code": "...", "message": "..."}``

The GitHub token passed to :meth:`create` lives only in the task's in-memory
state for the duration of the run (never logged or persisted) and is removed
when the task reaches a terminal state.  The application keeps exactly one
instance on ``app.state``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from app.core.errors import AppError
from app.models.analysis import AnalysisResult
from app.services.analysis_engine import AnalysisEngine
from app.services.github_fetcher import GitHubFetcher, parse_pr_url

logger = logging.getLogger(__name__)

#: Statuses that end the state machine; the token is dropped and no further
#: events are produced once a task reaches one of these.
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")

#: Retention bound for the in-memory registry: at most this many TERMINAL
#: tasks are kept (oldest terminal tasks are evicted first).  Non-terminal
#: tasks are never evicted so live runs always stay queryable.
MAX_TERMINAL_TASKS = 100

#: Hint appended to ``repo_not_found`` errors (US-3 UX) without touching T3's
#: error code - private repos surface as 404 when no token is supplied.
_PRIVATE_REPO_HINT = "私有仓库可能需要提供 GitHub token"


class TaskState(TypedDict):
    """Public task state returned by :meth:`TaskManager.get`.

    The session-memory ``token`` is stored as an extra internal key while the
    run is active and removed at the end; it is never part of this public
    shape and never exposed by the API layer.
    """

    id: str
    status: str
    stage: str
    progress_done: int
    progress_total: int
    result: AnalysisResult | None
    error: str | None
    created_at: str
    updated_at: str


def _now() -> str:
    """ISO-8601 UTC timestamp for ``created_at``/``updated_at``."""
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    """Registry of analysis tasks with per-task SSE event queues.

    Not a classic singleton class - the application keeps exactly one instance
    on ``app.state`` (``app.state.task_manager``) and the API routers read it
    from there, which also lets tests swap in a fresh manager per test.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}
        self._queues: dict[str, set[asyncio.Queue]] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}

    # -- public API ---------------------------------------------------------

    def create(
        self,
        pr_url: str,
        token: str | None,
        engine: AnalysisEngine,
        fetcher: GitHubFetcher,
    ) -> str:
        """Register a task and start ``_run``; return the new ``uuid4`` id."""
        task_id = str(uuid.uuid4())
        now = _now()
        state: TaskState = {
            "id": task_id,
            "status": "pending",
            "stage": "pending",
            "progress_done": 0,
            "progress_total": 0,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        # Token is session-memory only: kept on the state dict while the run
        # is active, removed in _run's finally.  Never logged or persisted.
        state["token"] = token
        self._tasks[task_id] = state
        self._queues[task_id] = set()
        self._async_tasks[task_id] = asyncio.create_task(
            self._run(task_id, pr_url, engine, fetcher)
        )
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        """Return the current state dict, or ``None`` for an unknown task."""
        return self._tasks.get(task_id)

    def subscribe(self, task_id: str) -> asyncio.Queue:
        """Return a queue that receives this task's future events.

        Raises ``KeyError`` for an unknown task.  When the task has already
        finished, the terminal event (``done``/``error``) is replayed so a
        reconnecting SSE client immediately sees the final state.
        """
        if task_id not in self._tasks:
            raise KeyError(task_id)
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(task_id, set()).add(queue)
        state = self._tasks[task_id]
        if state["status"] in TERMINAL_STATUSES:
            queue.put_nowait(self._terminal_event(state))
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        """Remove ``queue`` from the task's subscriber set (client disconnect).

        The empty set is dropped so a fully-disconnected task's registry entry
        does not linger; a later :meth:`subscribe` recreates it via
        ``setdefault``.  Unknown task ids and queues that were never
        subscribed are no-ops.
        """
        subscribers = self._queues.get(task_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._queues.pop(task_id, None)

    def cancel(self, task_id: str) -> None:
        """Cancel a running task and mark its state ``cancelled``.

        ``asyncio.Task.cancel()`` alone would leave the state ``pending`` when
        the task is cancelled before its coroutine ever ran, so the terminal
        state is set here directly; ``_run``'s ``CancelledError`` handler is
        idempotent and never double-emits.
        """
        task = self._async_tasks.get(task_id)
        if task is None:
            return
        state = self._tasks[task_id]
        if state["status"] in TERMINAL_STATUSES:
            return
        task.cancel()
        if state.get("status") != "cancelled":
            self._update(
                state,
                status="cancelled",
                stage="cancelled",
                error="task cancelled",
                error_code="task_cancelled",
            )
            self._emit(
                task_id,
                {"type": "error", "code": "task_cancelled", "message": "task cancelled"},
            )
        state.pop("token", None)

    # -- internals ----------------------------------------------------------

    async def _run(
        self,
        task_id: str,
        pr_url: str,
        engine: AnalysisEngine,
        fetcher: GitHubFetcher,
    ) -> None:
        """Advance the state machine and push stage/done/error events."""
        state = self._tasks[task_id]
        try:
            # -- fetching ----------------------------------------------------
            self._update(
                state, status="fetching", stage="fetching",
                progress_done=0, progress_total=1,
            )
            self._emit(
                task_id,
                {"type": "stage", "stage": "fetching", "done": 0, "total": 1},
            )
            owner, repo, number = parse_pr_url(pr_url)
            run_fetcher = self._tokenized_fetcher(fetcher, state.get("token"))
            try:
                ctx = await run_fetcher.fetch_context(owner, repo, number)
            except AppError as exc:
                if exc.code == "repo_not_found":
                    # US-3 UX: private repos surface as 404 without a token;
                    # append the hint, keeping T3's error code unchanged.
                    exc = AppError(exc.code, message=f"{exc.message}；{_PRIVATE_REPO_HINT}")
                raise exc
            self._update(state, stage="fetching", progress_done=1, progress_total=1)
            self._emit(
                task_id,
                {"type": "stage", "stage": "fetching", "done": 1, "total": 1},
            )

            # -- engine stages ----------------------------------------------
            def on_progress(stage: str, done: int, total: int) -> None:
                self._update(
                    state, status=stage, stage=stage,
                    progress_done=done, progress_total=total,
                )
                self._emit(
                    task_id,
                    {"type": "stage", "stage": stage, "done": done, "total": total},
                )

            result = await engine.run_analysis(ctx, progress=on_progress)

            self._update(state, status="succeeded", stage="succeeded", result=result)
            self._emit(task_id, {"type": "done", "result": result.model_dump()})
        except asyncio.CancelledError:
            # cancel() already set the terminal state; keep this idempotent so
            # a mid-run cancel never emits duplicate error events.
            if state.get("status") != "cancelled":
                self._update(
                    state,
                    status="cancelled",
                    stage="cancelled",
                    error="task cancelled",
                    error_code="task_cancelled",
                )
                self._emit(
                    task_id,
                    {"type": "error", "code": "task_cancelled", "message": "task cancelled"},
                )
            raise
        except AppError as exc:
            self._update(
                state, status="failed", stage="failed",
                error=exc.message, error_code=exc.code,
            )
            self._emit(
                task_id, {"type": "error", "code": exc.code, "message": exc.message},
            )
        except Exception as exc:
            logger.warning("task %s failed error=%s", task_id, exc.__class__.__name__)
            self._update(
                state, status="failed", stage="failed",
                error="internal analysis error", error_code="internal_error",
            )
            self._emit(
                task_id,
                {"type": "error", "code": "internal_error", "message": "internal analysis error"},
            )
        finally:
            state.pop("token", None)
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        """Evict the oldest terminal task once the retention bound is exceeded.

        Keeps at most :data:`MAX_TERMINAL_TASKS` terminal tasks; non-terminal
        tasks are never evicted.  The evicted task's queue set and async-task
        handle are dropped with it so the registry does not grow without
        bound.  Insertion order makes the first terminal task in ``_tasks``
        the oldest.
        """
        terminal = [
            task_id
            for task_id, state in self._tasks.items()
            if state["status"] in TERMINAL_STATUSES
        ]
        for task_id in terminal[: max(0, len(terminal) - MAX_TERMINAL_TASKS)]:
            self._tasks.pop(task_id, None)
            self._queues.pop(task_id, None)
            self._async_tasks.pop(task_id, None)

    def _tokenized_fetcher(
        self, fetcher: GitHubFetcher, token: str | None
    ) -> GitHubFetcher:
        """Return a per-task fetcher carrying ``token`` when one is supplied.

        The app-level fetcher is built without a token; when the caller
        supplied one it must live only for this task's run (session memory,
        never logged or persisted).  Test fakes are left untouched.
        """
        if token and isinstance(fetcher, GitHubFetcher):
            return GitHubFetcher(token=token)
        return fetcher

    def _terminal_event(self, state: TaskState) -> dict:
        """Replay the terminal event for a finished task (reconnect path)."""
        if state["status"] == "succeeded":
            return {"type": "done", "result": state["result"].model_dump()}
        code = state.get("error_code") or "internal_error"
        return {"type": "error", "code": code, "message": state["error"] or "task failed"}

    def _update(self, state: TaskState, **changes: object) -> None:
        state.update(changes)
        state["updated_at"] = _now()

    def _emit(self, task_id: str, event: dict) -> None:
        for queue in list(self._queues.get(task_id, ())):
            queue.put_nowait(event)
