"""CLI tests: hidden input, empty rejection, masking, and exit codes.

The real OS keyring and ``backend/.env`` are never touched: the ``keyring``
module is replaced with an in-memory stub and the dotenv path is redirected
to a per-test tmp directory. Plaintext keys must never reach stdout/stderr.
"""

import pytest

from app.cli import main
from app.services.credentials import CredentialStore


@pytest.fixture()
def isolated_credentials(monkeypatch, tmp_path):
    """In-memory keyring + per-test .env; never touches the OS keyring."""
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


def test_key_set_uses_hidden_input_and_masks_output(
    capsys, monkeypatch, isolated_credentials
):
    secret = "sk-secret-12345678"
    monkeypatch.setattr("app.cli.getpass.getpass", lambda prompt: secret)
    assert main(["key", "set"]) == 0
    captured = capsys.readouterr()
    assert CredentialStore.get_llm_api_key() == secret
    assert secret not in captured.out
    assert secret not in captured.err
    assert "sk-****5678" in captured.out


def test_key_set_rejects_empty_input(capsys, monkeypatch, isolated_credentials):
    monkeypatch.setattr("app.cli.getpass.getpass", lambda prompt: "")
    assert main(["key", "set"]) == 1
    captured = capsys.readouterr()
    assert "No key entered" in captured.err
    assert CredentialStore.get_llm_api_key() is None


def test_key_status_masks_configured_key(capsys, isolated_credentials):
    secret = "sk-status-12345678"
    CredentialStore.set_llm_api_key(secret)
    assert main(["key", "status"]) == 0
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert "sk-****5678" in captured.out


def test_key_status_reports_unconfigured(capsys, isolated_credentials):
    assert main(["key", "status"]) == 0
    captured = capsys.readouterr()
    assert "sk-" not in captured.out


def test_key_clear_removes_key(capsys, isolated_credentials):
    secret = "sk-clear-12345678"
    CredentialStore.set_llm_api_key(secret)
    assert main(["key", "clear"]) == 0
    assert CredentialStore.get_llm_api_key() is None


def test_missing_command_exits_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_missing_action_exits_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["key"])
    assert excinfo.value.code == 2
