"""App-level wiring tests: lifespan, CORS defaults, db dir creation."""

import pytest
from fastapi.testclient import TestClient


def test_startup_creates_db_parent_dir(tmp_path, monkeypatch):
    """Lifespan mkdirs the SQLite parent dir before HistoryStore.init()."""
    db_path = tmp_path / "nested" / "dir" / "analyses.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    from app.main import app

    with TestClient(app) as client:
        assert db_path.parent.exists()
        assert db_path.exists()
        assert client.get("/healthz").status_code == 200


def test_cors_same_origin_by_default(client):
    """No CORS_ORIGINS configured: cross-origin requests get no CORS headers."""
    r = client.get("/healthz", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_init_failure_closes_connection(tmp_path, monkeypatch):
    """If HistoryStore.init() raises, the opened connection is still closed."""
    from app.main import app
    from app.services.history_store import HistoryStore

    closed: list[bool] = []

    class ExplodingStore(HistoryStore):
        async def init(self):
            await super().init()  # opens a real SQLite connection first
            raise RuntimeError("init boom")

        async def close(self):
            closed.append(True)
            await super().close()

    monkeypatch.setattr("app.main.HistoryStore", ExplodingStore)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "db" / "analyses.db"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="init boom"):
        with TestClient(app):
            pass
    assert closed == [True]
