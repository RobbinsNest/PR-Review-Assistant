"""T9 API tests: POST /api/analyze, GET /api/tasks/{id}, SSE events endpoint."""

import asyncio
import json
import time

import pytest

from app.main import app
from app.models.analysis import AnalysisResult, AnalysisSummary
from app.models.pr import PRContext, PRInfo
from app.services.task_manager import TaskManager

TERMINAL = ("succeeded", "failed", "cancelled")


class FakeEngine:
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


@pytest.fixture()
def task_client(client):
    app.state.task_manager = TaskManager()
    app.state.analysis_engine = FakeEngine()
    app.state.github_fetcher = FakeFetcher()
    app.state.rate_limiter = None  # fresh rate-limit window per test
    yield client
    app.state.task_manager = TaskManager()
    app.state.analysis_engine = None
    app.state.github_fetcher = None


def wait_for_task(client, task_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/tasks/{task_id}").json()
        if state["status"] in TERMINAL:
            return state
        time.sleep(0.01)
    raise AssertionError("task did not finish")


def test_analyze_returns_202_with_task_id(task_client):
    r = task_client.post("/api/analyze", json={"pr_url": "o/r/pull/1"})
    assert r.status_code == 202
    assert "task_id" in r.json()
    wait_for_task(task_client, r.json()["task_id"])  # let the background task finish


def test_task_reaches_succeeded(task_client):
    r = task_client.post("/api/analyze", json={"pr_url": "o/r/pull/1"})
    task_id = r.json()["task_id"]
    state = wait_for_task(task_client, task_id)
    assert state["status"] == "succeeded"
    assert state["result"] is not None
    assert state["result"]["summary"]["title"] == "t"


def test_get_task_not_found_returns_404(task_client):
    r = task_client.get("/api/tasks/does-not-exist")
    assert r.status_code == 404


def test_sse_endpoint_streams_stage_and_done(task_client):
    task_client.app.state.analysis_engine = FakeEngine(delay=0.05)
    r = task_client.post("/api/analyze", json={"pr_url": "o/r/pull/1"})
    task_id = r.json()["task_id"]
    with task_client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("x-accel-buffering") == "no"
        body = resp.read()
    assert b'"type": "stage"' in body
    assert b'"type": "done"' in body


def test_sse_heartbeat_comments(task_client, monkeypatch):
    import app.api.analyze as analyze_mod

    monkeypatch.setattr(analyze_mod, "SSE_HEARTBEAT_SECONDS", 0.02)
    task_client.app.state.analysis_engine = FakeEngine(delay=0.08)
    r = task_client.post("/api/analyze", json={"pr_url": "o/r/pull/1"})
    task_id = r.json()["task_id"]
    with task_client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
        body = resp.read()
    assert b": heartbeat" in body
    assert b'"type": "done"' in body


def test_github_token_never_exposed(task_client):
    r = task_client.post(
        "/api/analyze",
        json={"pr_url": "o/r/pull/1", "github_token": "ghp_supersecret"},
    )
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    state = wait_for_task(task_client, task_id)
    assert state["status"] == "succeeded"
    assert "token" not in state
    assert "ghp_supersecret" not in json.dumps(state)


def test_invalid_pr_url_fails_async(task_client):
    r = task_client.post("/api/analyze", json={"pr_url": "not-a-url"})
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    state = wait_for_task(task_client, task_id)
    assert state["status"] == "failed"
    assert state["error_code"] == "invalid_url"


def test_sse_disconnect_removes_subscribed_queue(task_client, monkeypatch):
    import app.api.analyze as analyze_mod

    monkeypatch.setattr(analyze_mod, "SSE_HEARTBEAT_SECONDS", 0.02)
    tm = task_client.app.state.task_manager

    class QuickEngine:
        async def run_analysis(self, ctx, progress=None):
            await asyncio.sleep(0.08)

    task_client.app.state.analysis_engine = QuickEngine()
    r = task_client.post("/api/analyze", json={"pr_url": "o/r/pull/1"})
    task_id = r.json()["task_id"]
    with task_client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        first = next(resp.iter_bytes())  # an SSE frame proves the client connected
        assert first
    # client disconnected: the subscribed queue must be removed from the set
    assert not tm._queues.get(task_id)
    tm.cancel(task_id)
    wait_for_task(task_client, task_id)
