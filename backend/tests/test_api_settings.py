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
    # Single source of truth for the SPA quick-start button.
    assert body["example_pr"] == "RobbinsNest/PR-Review-Assistant/pull/1"


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
    # The probe uses response_format={"type":"json_object"}, which DeepSeek
    # and other OpenAI-compatible providers only allow when the prompt
    # mentions "json" ? the ping content must satisfy that precondition or
    # the provider rejects it with HTTP 400 (regression guard).
    assert len(captured["messages"]) == 1
    ping_content = captured["messages"][0]["content"]
    assert "json" in ping_content.lower()
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

@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com",            # insecure scheme
        "ftp://api.example.com",         # non-https scheme
        "https://127.0.0.1",             # loopback
        "https://127.0.0.1:8080/v1",     # loopback with port/path
        "https://localhost",             # loopback hostname
        "https://0.0.0.0",               # unspecified address
        "https://10.0.0.5",              # RFC1918 private
        "https://172.16.0.1",            # RFC1918 private
        "https://192.168.1.10",          # RFC1918 private
        "https://169.254.169.254",       # link-local (metadata endpoint)
        "https://internal",              # single-label hostname
        "https://user:pass@example.com", # embedded credentials
    ],
)
def test_put_rejects_insecure_or_private_base_url(client, keyring_stub, bad_url):
    """Key-exfiltration guard: non-https / private / local URLs are rejected."""
    r = client.put("/api/settings/llm", json={"base_url": bad_url})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "invalid_base_url"
    assert body["error"]["message"]
    # The rejected value must not have mutated the in-memory config.
    assert client.get("/api/settings/llm").json()["base_url"] == "https://api.deepseek.com"


def test_put_accepts_https_public_base_url(client, keyring_stub):
    """A public https:// base_url is accepted and stored in memory."""
    r = client.put("/api/settings/llm", json={"base_url": "https://example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://example.com"
    assert body["api_key_configured"] is False


def test_test_endpoint_unchanged_after_rejected_base_url(client, keyring_stub):
    """A rejected base_url leaves config untouched; test probe behavior holds."""
    r = client.put("/api/settings/llm", json={"base_url": "http://evil.example.com"})
    assert r.status_code == 400
    body = client.get("/api/settings/llm").json()
    assert body["base_url"] == "https://api.deepseek.com"
    assert body["model"] == "deepseek-v4-flash"

    r = client.post("/api/settings/llm/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "LLM API key is not configured"
