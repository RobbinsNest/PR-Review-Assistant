"""T9 TaskManager tests: async registry, state machine, SSE event queue, cancel."""

import asyncio
import time

from app.core.errors import AppError
from app.models.analysis import AnalysisResult, AnalysisSummary
from app.models.pr import PRContext, PRInfo
from app.services.task_manager import MAX_TERMINAL_TASKS, TaskManager

TERMINAL = ("succeeded", "failed", "cancelled")


class FakeEngine:
    """Minimal engine stub emitting every stage progress event and a result."""

    def __init__(self, delay=0.0):
        self.delay = delay

    async def run_analysis(self, ctx, progress=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        if progress is not None:
            progress("building", 1, 1)
            progress("analyzing", 1, 1)
            progress("verifying", 1, 1)
            progress("aggregating", 1, 1)
        return AnalysisResult(
            summary=AnalysisSummary(
                title="t", overview="o", key_points=["k"], risk_highlights=["r"]
            ),
            findings=[],
            meta={
                "stage_durations": {},
                "token_estimate": {},
                "skipped_files": [],
                "partial": False,
            },
        )


class FakeFetcher:
    """Minimal fetcher stub returning a bare PRContext."""

    def __init__(self):
        self.calls = 0

    async def fetch_context(self, owner, repo, number):
        self.calls += 1
        return PRContext(
            info=PRInfo(
                owner=owner, repo=repo, number=number,
                title="t", html_url="u", base_sha="a", head_sha="b",
            ),
            files=[],
        )


async def wait_terminal(tm, task_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = tm.get(task_id)
        if state and state["status"] in TERMINAL:
            return state
        await asyncio.sleep(0.01)
    raise AssertionError("task did not reach a terminal state")


async def test_task_state_machine():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    state = await wait_terminal(tm, task_id)
    assert state["status"] == "succeeded"
    assert state["result"] is not None
    assert state["result"].summary.title == "t"


async def test_task_events_emitted():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    queue = tm.subscribe(task_id)
    events = []
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=2)
        except asyncio.TimeoutError:
            break
        events.append(event["type"])
        if event["type"] in ("done", "error"):
            break
    assert "stage" in events and events[-1] == "done"


async def test_stage_events_carry_progress():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    queue = tm.subscribe(task_id)
    stages = {}
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=2)
        if event["type"] == "stage":
            stages[event["stage"]] = (event["done"], event["total"])
        if event["type"] in ("done", "error"):
            break
    assert set(stages) >= {
        "fetching", "building", "analyzing", "verifying", "aggregating",
    }
    assert stages["aggregating"] == (1, 1)


async def test_done_event_contains_result():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    queue = tm.subscribe(task_id)
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=2)
        if event["type"] == "done":
            break
    assert event["result"]["summary"]["title"] == "t"
    assert event["result"]["findings"] == []


async def test_task_fails_and_emits_error_event():
    tm = TaskManager()

    class BoomEngine:
        async def run_analysis(self, ctx, progress=None):
            raise AppError("llm_api_error", message="upstream failed")

    task_id = tm.create("o/r/pull/1", None, BoomEngine(), FakeFetcher())
    state = await wait_terminal(tm, task_id)
    assert state["status"] == "failed"
    assert state["error"] == "upstream failed"
    queue = tm.subscribe(task_id)
    event = await asyncio.wait_for(queue.get(), timeout=2)
    assert event == {
        "type": "error",
        "code": "llm_api_error",
        "message": "upstream failed",
    }


async def test_token_removed_from_state_after_run():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", "ghp_secret", FakeEngine(), FakeFetcher())
    state = await wait_terminal(tm, task_id)
    assert "token" not in state


async def test_repo_not_found_error_is_enriched_with_private_hint():
    tm = TaskManager()

    class NotFoundFetcher:
        async def fetch_context(self, owner, repo, number):
            raise AppError(
                "repo_not_found",
                message="GitHub repo/PR not found: https://api.github.com/repos/o/r/pulls/1",
            )

    task_id = tm.create("o/r/pull/1", None, FakeEngine(), NotFoundFetcher())
    state = await wait_terminal(tm, task_id)
    assert state["status"] == "failed"
    assert state["error_code"] == "repo_not_found"
    assert "私有仓库可能需要提供 GitHub token" in state["error"]
    queue = tm.subscribe(task_id)
    event = await asyncio.wait_for(queue.get(), timeout=2)
    assert "私有仓库可能需要提供 GitHub token" in event["message"]


async def test_cancel_stops_task_and_marks_cancelled():
    tm = TaskManager()

    class SlowEngine:
        async def run_analysis(self, ctx, progress=None):
            await asyncio.sleep(30)

    task_id = tm.create("o/r/pull/1", None, SlowEngine(), FakeFetcher())
    tm.cancel(task_id)
    state = await wait_terminal(tm, task_id)
    assert state["status"] == "cancelled"
    assert state["error"] is not None


async def test_invalid_pr_url_fails_with_invalid_url():
    tm = TaskManager()
    task_id = tm.create("not-a-pr-url", None, FakeEngine(), FakeFetcher())
    state = await wait_terminal(tm, task_id)
    assert state["status"] == "failed"
    assert state["error_code"] == "invalid_url"


async def test_subscribe_replays_terminal_event_for_finished_task():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    await wait_terminal(tm, task_id)
    queue = tm.subscribe(task_id)
    event = await asyncio.wait_for(queue.get(), timeout=2)
    assert event["type"] == "done"
    assert event["result"]["summary"]["title"] == "t"


async def test_bounded_retention_evicts_oldest_terminal_task():
    tm = TaskManager()
    ids = [
        tm.create("o/r/pull/1", None, FakeEngine(delay=i * 0.001), FakeFetcher())
        for i in range(MAX_TERMINAL_TASKS + 5)
    ]
    # Completion is staggered in creation order, so eviction deterministically
    # removes the oldest terminal tasks first.
    await wait_terminal(tm, ids[-1], timeout=5.0)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(tm._tasks) > MAX_TERMINAL_TASKS:
        await asyncio.sleep(0.01)
    assert len(tm._tasks) == MAX_TERMINAL_TASKS
    assert ids[0] not in tm._tasks  # oldest terminal task evicted
    assert ids[-1] in tm._tasks  # newest task retained
    assert ids[0] not in tm._queues
    assert ids[0] not in tm._async_tasks
    assert all(tm._tasks[tid]["status"] in TERMINAL for tid in tm._tasks)


async def test_non_terminal_tasks_are_never_evicted():
    tm = TaskManager()
    slow_id = tm.create(
        "o/r/pull/1", None, FakeEngine(delay=30.0), FakeFetcher()
    )
    fast_ids = [
        tm.create("o/r/pull/1", None, FakeEngine(delay=i * 0.001), FakeFetcher())
        for i in range(MAX_TERMINAL_TASKS + 5)
    ]
    await wait_terminal(tm, fast_ids[-1], timeout=5.0)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(tm._tasks) > MAX_TERMINAL_TASKS + 1:
        await asyncio.sleep(0.01)
    assert len(tm._tasks) == MAX_TERMINAL_TASKS + 1
    assert slow_id in tm._tasks  # oldest but still running: never evicted
    assert tm._tasks[slow_id]["status"] not in TERMINAL
    tm.cancel(slow_id)
    await wait_terminal(tm, slow_id, timeout=5.0)


async def test_unsubscribe_removes_queue_from_subscriber_set():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    queue = tm.subscribe(task_id)
    assert queue in tm._queues[task_id]
    tm.unsubscribe(task_id, queue)
    assert not tm._queues.get(task_id)
    # other subscribers for the same task are unaffected
    q1 = tm.subscribe(task_id)
    q2 = tm.subscribe(task_id)
    tm.unsubscribe(task_id, q1)
    assert q1 not in tm._queues[task_id]
    assert q2 in tm._queues[task_id]


# ---------------------------------------------------------------------------
# T16 integration fix wave: history persistence on successful runs
# ---------------------------------------------------------------------------


async def test_successful_task_saves_history_with_history_id(tmp_path):
    from app.services.history_store import HistoryStore

    store = HistoryStore(str(tmp_path / "analyses.db"))
    await store.init()
    tm = TaskManager()
    task_id = tm.create(
        "o/r/pull/1", None, FakeEngine(), FakeFetcher(), history_store=store
    )
    try:
        state = await wait_terminal(tm, task_id)
        assert state["status"] == "succeeded"
        assert state["result"] is not None
        history_id = state["result"].meta["history_id"]
        assert isinstance(history_id, str) and history_id
        # The saved record matches the task's PR and carries a non-secret
        # config snapshot (model/base_url only).
        rows = await store.list()
        assert len(rows) == 1
        assert rows[0]["id"] == history_id
        assert rows[0]["pr_number"] == 1
        assert rows[0]["status"] == "succeeded"
        assert set(rows[0]["config_snapshot"]) == {"model", "base_url"}
        assert rows[0]["duration_ms"] >= 0
        # The replayed done event exposes history_id too (SSE consumers read
        # it from the done event result).
        queue = tm.subscribe(task_id)
        event = await asyncio.wait_for(queue.get(), timeout=2)
        assert event["type"] == "done"
        assert event["result"]["meta"]["history_id"] == history_id
    finally:
        await store.close()


async def test_task_without_history_store_still_succeeds():
    tm = TaskManager()
    task_id = tm.create("o/r/pull/1", None, FakeEngine(), FakeFetcher())
    state = await wait_terminal(tm, task_id)
    assert state["status"] == "succeeded"
    assert state["result"] is not None
    assert "history_id" not in state["result"].meta


async def test_failed_task_is_not_saved(tmp_path):
    from app.services.history_store import HistoryStore

    store = HistoryStore(str(tmp_path / "analyses.db"))
    await store.init()

    class BoomEngine:
        async def run_analysis(self, ctx, progress=None):
            raise AppError("llm_api_error", message="upstream failed")

    tm = TaskManager()
    try:
        task_id = tm.create(
            "o/r/pull/1", None, BoomEngine(), FakeFetcher(), history_store=store
        )
        state = await wait_terminal(tm, task_id)
        assert state["status"] == "failed"
        assert await store.count() == 0
    finally:
        await store.close()
