"""Shared pytest fixtures for the backend test suite."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear the get_settings() lru_cache so tests never see stale Settings."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with an isolated environment (no real keyring / DB)."""
    monkeypatch.setenv("LLM_API_KEY", "test-llm-api-key")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test-analyses.db"))
    with TestClient(app) as test_client:
        yield test_client
