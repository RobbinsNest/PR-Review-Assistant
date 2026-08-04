"""Tests for the /api/settings/llm endpoints.

The real OS keyring is never touched - the ``keyring`` module is replaced
with an in-memory stub and the ``LLM_API_KEY`` env var is removed so the
endpoints only see what the tests write. Responses must never echo the
plaintext key (only masked forms).
"""

import pytest

from app.core.errors import AppError
from app.services.credentials import CredentialStore


@pytest.fixture()
def keyring_stub(monkeypatch):
    """In-memory keyring stub with no env override; never touches the OS keyring."""
    store: dict[tuple[str, str], str] = {}

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
    return store


def test_get_returns_defaults_and_unconfigured(client, keyring_stub):
    r = client.get("/api/settings/llm")
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://api.deepseek.com"
    assert body["model"] == "deepseek-v4-flash"
    assert body["api_key_configured"] is False
    assert body["api_key_masked"] is None


def test_put_sets_key_and_get_shows_masked(client, keyring_stub):
    r = client.put("/api/settings/llm", json={"api_key": "sk-abcdef1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_configured"] is True
    assert body["api_key_masked"] == "sk-****1234"
    assert "sk-abcdef1234" not in r.text

    r = client.get("/api/settings/llm")
    body = r.json()
    assert body["api_key_configured"] is True
    assert body["api_key_masked"] == "sk-****1234"
    assert "sk-abcdef1234" not in r.text


def test_put_updates_base_url_and_model(client, keyring_stub):
    r = client.put(
        "/api/settings/llm",
        json={"base_url": "https://api.openai.com", "model": "gpt-4o-mini"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://api.openai.com"
    assert body["model"] == "gpt-4o-mini"
    assert body["api_key_configured"] is False
    assert body["api_key_masked"] is None


def test_put_empty_api_key_does_not_update(client, keyring_stub):
    client.put("/api/settings/llm", json={"api_key": "sk-abcdef1234"})
    r = client.put("/api/settings/llm", json={"api_key": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_configured"] is True
    assert body["api_key_masked"] == "sk-****1234"


def test_delete_clears_key(client, keyring_stub):
    client.put("/api/settings/llm", json={"api_key": "sk-abcdef1234"})
    assert client.get("/api/settings/llm").json()["api_key_configured"] is True

    r = client.delete("/api/settings/llm")
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_configured"] is False
    assert body["api_key_masked"] is None

    assert client.get("/api/settings/llm").json()["api_key_configured"] is False


def test_test_endpoint_succeeds_and_uses_current_config(client, keyring_stub, monkeypatch):
    captured = {}

    class FakeLLMClient:
        def __init__(self, base_url, api_key, model, timeout=60.0):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            captured["model"] = model

        async def chat_json(self, messages, response_schema, temperature=0.2):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return response_schema(ok=True)

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("app.api.settings.LLMClient", FakeLLMClient)
    client.put("/api/settings/llm", json={"api_key": "sk-abcdef1234"})

    r = client.post("/api/settings/llm/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert body["error"] is None

    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["api_key"] == "sk-abcdef1234"
    assert captured["messages"] == [{"role": "user", "content": "ping"}]
    assert "sk-abcdef1234" not in r.text


def test_test_endpoint_reports_error_when_no_key(client, keyring_stub):
    r = client.post("/api/settings/llm/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] is not None


def test_test_endpoint_reports_provider_error_and_never_echoes_key(
    client, keyring_stub, monkeypatch
):
    class FailingLLMClient:
        def __init__(self, base_url, api_key, model, timeout=60.0):
            self.api_key = api_key

        async def chat_json(self, messages, response_schema, temperature=0.2):
            raise AppError("llm_api_error", message="LLM API error 401: Invalid API key")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("app.api.settings.LLMClient", FailingLLMClient)
    client.put("/api/settings/llm", json={"api_key": "sk-bad-secret-1234"})

    r = client.post("/api/settings/llm/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] is not None
    assert "sk-bad-secret-1234" not in r.text

def test_empty_key_treated_as_unconfigured(client, keyring_stub, tmp_path, monkeypatch):
    """Empty stored key: api_key_configured and api_key_masked agree (unset)."""
    monkeypatch.setattr(CredentialStore, "dotenv_path", tmp_path / ".env")
    (tmp_path / ".env").write_text("LLM_API_KEY=\n", encoding="utf-8")
    r = client.get("/api/settings/llm")
    body = r.json()
    assert body["api_key_configured"] is False
    assert body["api_key_masked"] is None
