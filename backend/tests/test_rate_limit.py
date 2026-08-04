"""Tests for the in-memory sliding-window rate limiter and the 429 dependency.

The end-to-end 429 test spins up its own TestClient with a tiny per-minute
limit so it never depends on (or pollutes) module-level state.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_allow_within_limit():
    rl = RateLimiter(limit=2)
    assert await rl.allow("ip1") is True
    assert await rl.allow("ip1") is True
    assert await rl.allow("ip1") is False
    assert await rl.allow("ip2") is True


@pytest.mark.asyncio
async def test_window_resets_after_window_sec():
    rl = RateLimiter(limit=1, window_sec=1)
    assert await rl.allow("ip1") is True
    assert await rl.allow("ip1") is False
    await asyncio.sleep(1.05)
    assert await rl.allow("ip1") is True


@pytest.mark.asyncio
async def test_keys_are_isolated():
    rl = RateLimiter(limit=1)
    assert await rl.allow("ip-a") is True
    assert await rl.allow("ip-a") is False
    assert await rl.allow("ip-b") is True


@pytest.mark.asyncio
async def test_expired_window_is_popped_after_pruning():
    """A fully expired window is dropped from `_timestamps` (no unbounded growth)."""
    rl = RateLimiter(limit=1, window_sec=1)
    assert await rl.allow("ip-a") is True
    original = rl._timestamps["ip-a"]
    await asyncio.sleep(1.05)
    # The next call prunes the expired window; the empty deque is popped and
    # replaced with a fresh window instead of lingering in the map forever.
    assert await rl.allow("ip-a") is True
    assert rl._timestamps["ip-a"] is not original
    assert len(rl._timestamps["ip-a"]) == 1


def test_rate_limit_dependency_returns_429(tmp_path, monkeypatch):
    """Exceeding the per-minute limit on a protected endpoint yields 429."""
    store: dict = {}

    class StubKeyring:
        @staticmethod
        def get_password(service, username):
            return store.get((service, username))

        @staticmethod
        def set_password(service, username, password):
            store[(service, username)] = password

        @staticmethod
        def delete_password(service, username):
            store.pop((service, username), None)

    monkeypatch.setattr("app.services.credentials.keyring", StubKeyring)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "rate-limit.db"))

    from app.main import app

    with TestClient(app) as client:
        assert client.post("/api/settings/llm/test").status_code == 200
        assert client.post("/api/settings/llm/test").status_code == 200
        limited = client.post("/api/settings/llm/test")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limited"
