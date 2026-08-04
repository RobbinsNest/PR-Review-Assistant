"""Tests for Settings.api_key() credential resolution (app/core/config.py).

``Settings.api_key()`` must resolve the key through ``CredentialStore`` so
keys set via the CLI (``key set``) or the settings API are honored by the
analysis path - not only the ``LLM_API_KEY`` env var.
"""

from app.core.config import Settings
from app.services.credentials import CredentialStore


def test_api_key_delegates_to_credential_store(monkeypatch):
    """api_key() returns the stored key even when the env var differs."""
    monkeypatch.setattr(
        CredentialStore,
        "get_llm_api_key",
        classmethod(lambda cls: "sk-keyring-stored"),
    )
    monkeypatch.setenv("LLM_API_KEY", "sk-env-should-lose")
    assert Settings().api_key() == "sk-keyring-stored"


def test_api_key_env_fallback_still_works(monkeypatch):
    """api_key() falls back to LLM_API_KEY when the store has no key."""
    monkeypatch.setattr(CredentialStore, "_keyring_get", classmethod(lambda cls: None))
    monkeypatch.setenv("LLM_API_KEY", "sk-env-fallback")
    assert Settings().api_key() == "sk-env-fallback"


def test_default_example_pr_is_real_public_pr():
    """The bundled example PR is this repo's own merged PR #1 (public)."""
    assert Settings().example_pr == "RobbinsNest/PR-Review-Assistant/pull/1"


def test_example_pr_overridable_via_env(monkeypatch):
    """EXAMPLE_PR env var overrides the default example PR."""
    monkeypatch.setenv("EXAMPLE_PR", "owner/repo/pull/42")
    assert Settings().example_pr == "owner/repo/pull/42"
