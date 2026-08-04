"""Credential storage for the LLM API key.

Lookup priority: OS keyring (Windows Credential Manager via the ``keyring``
package) -> ``LLM_API_KEY`` environment variable -> plain ``backend/.env``
file (gitignored, simple ``key=value`` parsing - no third-party dotenv).

The key is never logged, echoed, or committed: only masked forms
(e.g. ``sk-****1234``) are exposed through the CLI and settings API.
"""

import os
import sys
from pathlib import Path

import keyring

#: keyring service/user names used to store the LLM API key.
_KEYRING_SERVICE = "pr-review-assistant"
_KEYRING_USERNAME = "llm_api_key"
#: environment variable consulted after the keyring.
LLM_API_KEY_ENV = "LLM_API_KEY"
#: default plaintext fallback file (``backend/.env``).
DEFAULT_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def mask(key: str) -> str:
    """Mask a credential as ``<scheme>-****<last4>``; short keys show ``****``.

    Keys with a scheme prefix such as ``sk-`` keep that prefix visible
    (``sk-****1234``); other keys keep their first two characters. Values
    of four characters or fewer are fully masked.
    """
    if len(key) <= 4:
        return "****"
    if "-" in key:
        prefix, _, _ = key.partition("-")
        return f"{prefix}-****{key[-4:]}"
    return f"{key[:2]}****{key[-4:]}"


class CredentialStore:
    """Store/retrieve the LLM API key from the keyring, env, or ``.env``."""

    service: str = _KEYRING_SERVICE
    username: str = _KEYRING_USERNAME
    env_var: str = LLM_API_KEY_ENV
    dotenv_path: Path = DEFAULT_DOTENV_PATH

    mask = staticmethod(mask)

    # -- keyring helpers (never raise: a missing backend means "not there") --

    @classmethod
    def _keyring_get(cls) -> str | None:
        try:
            return keyring.get_password(cls.service, cls.username)
        except Exception:
            return None

    @classmethod
    def _keyring_set(cls, key: str) -> None:
        keyring.set_password(cls.service, cls.username, key)

    @classmethod
    def _keyring_delete(cls) -> None:
        try:
            keyring.delete_password(cls.service, cls.username)
        except Exception:
            pass

    # -- public interface --

    @classmethod
    def get_llm_api_key(cls) -> str | None:
        """Return the configured LLM API key or ``None``.

        Checks the keyring first, then the ``LLM_API_KEY`` environment
        variable, then the ``backend/.env`` file.
        """
        key = cls._keyring_get()
        if key:
            return key
        env_key = os.environ.get(cls.env_var)
        if env_key:
            return env_key
        return cls._dotenv_get()

    @classmethod
    def set_llm_api_key(cls, key: str) -> None:
        """Persist the key; the keyring is preferred and ``.env`` is the fallback.

        When the keyring is unavailable the key is written to
        ``backend/.env`` (gitignored) and a warning is printed to stderr -
        the message never contains the key itself.
        """
        try:
            cls._keyring_set(key)
        except Exception:
            cls._dotenv_set(key)
            print(
                "warning: keyring unavailable; LLM API key stored in "
                ".env as plaintext",
                file=sys.stderr,
            )

    @classmethod
    def clear_llm_api_key(cls) -> None:
        """Remove the key from the keyring, the ``.env`` file, and the env."""
        cls._keyring_delete()
        cls._dotenv_clear()
        os.environ.pop(cls.env_var, None)

    # -- .env helpers (simple key=value parsing) --

    @classmethod
    def _dotenv_get(cls) -> str | None:
        try:
            lines = cls.dotenv_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            if name.strip() != cls.env_var:
                continue
            return value.strip()
        return None

    @classmethod
    def _dotenv_set(cls, key: str) -> None:
        cls.dotenv_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = f"{cls.env_var}="
        lines: list[str] = []
        if cls.dotenv_path.exists():
            lines = cls.dotenv_path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        updated = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                out.append(line)
                continue
            name, _, _ = stripped.partition("=")
            if name.strip() == cls.env_var:
                out.append(f"{prefix}{key}")
                updated = True
            else:
                out.append(line)
        if not updated:
            out.append(f"{prefix}{key}")
        cls.dotenv_path.write_text("\n".join(out) + "\n", encoding="utf-8")

    @classmethod
    def _dotenv_clear(cls) -> None:
        if not cls.dotenv_path.exists():
            return
        lines = cls.dotenv_path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                out.append(line)
                continue
            name, _, _ = stripped.partition("=")
            if name.strip() == cls.env_var:
                continue
            out.append(line)
        cls.dotenv_path.write_text("\n".join(out) + "\n", encoding="utf-8")
