"""Shared pytest fixtures for the backend test suite."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with an isolated environment (no real keyring / DB)."""
    monkeypatch.setenv("LLM_API_KEY", "test-llm-api-key")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test-analyses.db"))
    with TestClient(app) as test_client:
        yield test_client
