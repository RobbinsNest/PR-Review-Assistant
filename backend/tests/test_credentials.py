"""Tests for CredentialStore: keyring/env/.env lookup, masking, set/clear.

The real OS keyring is never touched: an in-memory stub replaces the
``keyring`` module and the ``.env`` path is redirected to tmp_path.
"""

import pytest

from app.services.credentials import CredentialStore, mask


@pytest.fixture(autouse=True)
def keyring_store(monkeypatch, tmp_path):
    """In-memory keyring stub + per-test .env file; never touches the OS keyring."""
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
    monkeypatch.setattr(CredentialStore, "dotenv_path", tmp_path / ".env")
    return store


def test_mask():
    assert mask("sk-abcdef1234") == "sk-****1234"
    assert mask("abc") == "****"


def test_mask_short_values_show_four_stars():
    assert mask("abcd") == "****"
    assert mask("a") == "****"
    assert mask("") == "****"


def test_mask_long_values_keep_scheme_and_last_four():
    assert mask("sk-0123456789") == "sk-****6789"
    assert mask("0123456789abcdef") == "01****cdef"


def test_get_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert CredentialStore.get_llm_api_key() is None


def test_get_returns_keyring_key(keyring_store):
    keyring_store[(CredentialStore.service, CredentialStore.username)] = "sk-keyring-1234"
    assert CredentialStore.get_llm_api_key() == "sk-keyring-1234"


def test_get_prefers_keyring_over_env(keyring_store, monkeypatch):
    keyring_store[(CredentialStore.service, CredentialStore.username)] = "sk-keyring-1234"
    monkeypatch.setenv("LLM_API_KEY", "sk-env-1234")
    assert CredentialStore.get_llm_api_key() == "sk-keyring-1234"


def test_get_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env-1234")
    assert CredentialStore.get_llm_api_key() == "sk-env-1234"


def test_get_falls_back_to_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "# comment line\n\nLLM_API_KEY=sk-dotenv-1234\n", encoding="utf-8"
    )
    assert CredentialStore.get_llm_api_key() == "sk-dotenv-1234"


def test_get_prefers_env_over_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LLM_API_KEY=sk-dotenv-1234\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-1234")
    assert CredentialStore.get_llm_api_key() == "sk-env-1234"


def test_set_writes_to_keyring(keyring_store):
    CredentialStore.set_llm_api_key("sk-set-12345678")
    assert keyring_store[(CredentialStore.service, CredentialStore.username)] == "sk-set-12345678"
    assert CredentialStore.get_llm_api_key() == "sk-set-12345678"


def test_set_falls_back_to_dotenv_when_keyring_unavailable(monkeypatch):
    class BrokenKeyring:
        @staticmethod
        def get_password(service, username):
            return None

        @staticmethod
        def set_password(service, username, password):
            raise RuntimeError("no keyring backend")

        @staticmethod
        def delete_password(service, username):
            pass

    monkeypatch.setattr("app.services.credentials.keyring", BrokenKeyring)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    CredentialStore.set_llm_api_key("sk-fallback-1234")
    assert CredentialStore.get_llm_api_key() == "sk-fallback-1234"
    text = CredentialStore.dotenv_path.read_text(encoding="utf-8")
    assert "LLM_API_KEY=sk-fallback-1234" in text


def test_set_dotenv_fallback_updates_existing_line(monkeypatch):
    class BrokenKeyring:
        @staticmethod
        def get_password(service, username):
            return None

        @staticmethod
        def set_password(service, username, password):
            raise RuntimeError("no keyring backend")

        @staticmethod
        def delete_password(service, username):
            pass

    monkeypatch.setattr("app.services.credentials.keyring", BrokenKeyring)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    CredentialStore.dotenv_path.write_text(
        "OTHER=value\nLLM_API_KEY=sk-old-key-1234\n", encoding="utf-8"
    )
    CredentialStore.set_llm_api_key("sk-new-key-1234")
    text = CredentialStore.dotenv_path.read_text(encoding="utf-8")
    assert "OTHER=value" in text
    assert "LLM_API_KEY=sk-new-key-1234" in text
    assert "sk-old-key-1234" not in text


def test_clear_removes_keyring_and_dotenv(keyring_store):
    keyring_store[(CredentialStore.service, CredentialStore.username)] = "sk-clear-1234"
    CredentialStore.dotenv_path.write_text("LLM_API_KEY=sk-dotenv-clear\n", encoding="utf-8")
    CredentialStore.clear_llm_api_key()
    assert CredentialStore.get_llm_api_key() is None
    assert (CredentialStore.service, CredentialStore.username) not in keyring_store
    text = CredentialStore.dotenv_path.read_text(encoding="utf-8")
    assert "LLM_API_KEY" not in text


def test_clear_removes_env_override(keyring_store, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env-clear")
    assert CredentialStore.get_llm_api_key() == "sk-env-clear"
    CredentialStore.clear_llm_api_key()
    assert CredentialStore.get_llm_api_key() is None
