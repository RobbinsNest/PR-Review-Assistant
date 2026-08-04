"""Settings API: LLM configuration and credential status (key always masked).

Endpoints under ``/api/settings``:

- ``GET /api/settings/llm``    -> current base_url/model + key status/mask
- ``PUT /api/settings/llm``    -> update provided fields (empty api_key = no-op)
- ``DELETE /api/settings/llm`` -> clear the stored LLM API key
- ``POST /api/settings/llm/test`` -> minimal chat probe with the current config

Security: no response ever contains the plaintext key, and the test probe
reports only masked status / latency / a redacted error message.  The probe
is rate-limited per client IP (429 once the per-minute limit is exceeded).

``base_url``/``model`` updates are in-memory only (they reset on restart);
the API key is the only value persisted, via the keyring with a ``.env``
fallback (see ``CredentialStore``).
"""

import ipaddress
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import rate_limit_dependency
from app.services.credentials import CredentialStore
from app.services.llm_client import LLMClient

router = APIRouter(prefix="/api/settings", tags=["settings"])

#: Default provider base_url; the only value exempt from the single-label
#: hostname rule below (it always passes the public-https checks anyway).
_DEFAULT_BASE_URL = "https://api.deepseek.com"


def _validate_base_url(value: str) -> str:
    """Validate a settings ``base_url`` against key-exfiltration vectors.

    The stored API key is sent (``Authorization: Bearer``) to this URL by
    the connectivity probe and the analysis path, so only public ``https``
    endpoints are accepted: non-https schemes, embedded credentials, and
    local/private hosts (loopback, RFC1918, link-local, unspecified, or
    single-label hostnames) are rejected with a 400
    ``AppError("invalid_base_url")``.
    """
    value = value.strip()
    parsed = urlsplit(value)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme != "https":
        raise AppError(
            "invalid_base_url",
            message="base_url must use the https:// scheme",
            status_code=400,
        )
    if not host:
        raise AppError(
            "invalid_base_url",
            message="base_url must include a host",
            status_code=400,
        )
    if value.rstrip("/") == _DEFAULT_BASE_URL:
        return value
    if parsed.username or parsed.password:
        raise AppError(
            "invalid_base_url",
            message="base_url must not embed credentials",
            status_code=400,
        )
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise AppError(
            "invalid_base_url",
            message="base_url must not point at a local host",
            status_code=400,
        )
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise AppError(
            "invalid_base_url",
            message="base_url must not point at a private or local address",
            status_code=400,
        )
    if "." not in host:
        raise AppError(
            "invalid_base_url",
            message="base_url host must be a fully-qualified public hostname",
            status_code=400,
        )
    return value


class LLMSettingsUpdate(BaseModel):
    """Optional fields accepted by ``PUT /api/settings/llm``."""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class _PingResponse(BaseModel):
    """Tolerant schema for the connectivity probe (any JSON object passes)."""

    ok: bool = True


def _llm_settings_response(settings) -> dict:
    """Build the masked status payload shared by GET/PUT/DELETE.

    ``api_key_configured`` and ``api_key_masked`` use the same predicate: an
    empty/whitespace key counts as unconfigured, so the two fields always
    agree and an empty value never renders a mask.
    """
    key = CredentialStore.get_llm_api_key()
    configured = bool(key)
    return {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "api_key_configured": configured,
        "api_key_masked": CredentialStore.mask(key) if configured else None,
    }


@router.get("/llm")
def get_llm_settings() -> dict:
    """Return the current LLM configuration with the key masked.

    ``base_url``/``model`` are the process-local (in-memory) values - they
    are not persisted across restarts; only the API key persists (keyring,
    ``.env`` fallback).
    """
    return _llm_settings_response(get_settings())


@router.put("/llm")
def update_llm_settings(payload: LLMSettingsUpdate) -> dict:
    """Update only the provided fields; an empty ``api_key`` is a no-op.

    ``base_url``/``model`` changes are in-memory only and reset on restart;
    the API key persists via the keyring (``.env`` fallback).  ``base_url``
    is validated against key-exfiltration (public https:// only) and
    rejected with ``invalid_base_url`` (400) otherwise.
    """
    settings = get_settings()
    if payload.base_url:
        settings.llm_base_url = _validate_base_url(payload.base_url)
    if payload.model:
        settings.llm_model = payload.model
    if payload.api_key:
        CredentialStore.set_llm_api_key(payload.api_key)
    return _llm_settings_response(settings)


@router.delete("/llm")
def clear_llm_settings() -> dict:
    """Clear the stored LLM API key and return the masked status."""
    CredentialStore.clear_llm_api_key()
    return _llm_settings_response(get_settings())


@router.post("/llm/test", dependencies=[Depends(rate_limit_dependency)])
async def test_llm_settings() -> dict:
    """Probe connectivity with the current config; never logs or echoes the key."""
    settings = get_settings()
    api_key = CredentialStore.get_llm_api_key()
    if not api_key:
        return {"ok": False, "latency_ms": 0, "error": "LLM API key is not configured"}

    started = time.monotonic()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_sec,
    )
    try:
        await client.chat_json(
            [{"role": "user", "content": "ping"}],
            _PingResponse,
            temperature=0,
        )
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "error": None}
    except AppError as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": exc.message,
        }
    except Exception:
        # Never surface unexpected internals; the connectivity probe must not 500.
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": "unexpected error during connectivity test",
        }
    finally:
        # Per-request client: release the connection pool immediately.
        await client.aclose()
