"""Settings API: LLM configuration and credential status (key always masked).

Endpoints under ``/api/settings``:

- ``GET /api/settings/llm``    -> current base_url/model + key status/mask
- ``PUT /api/settings/llm``    -> update provided fields (empty api_key = no-op)
- ``DELETE /api/settings/llm`` -> clear the stored LLM API key
- ``POST /api/settings/llm/test`` -> minimal chat probe with the current config

Security: no response ever contains the plaintext key, and the test probe
reports only masked status / latency / a redacted error message.
"""

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.credentials import CredentialStore
from app.services.llm_client import LLMClient

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMSettingsUpdate(BaseModel):
    """Optional fields accepted by ``PUT /api/settings/llm``."""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class _PingResponse(BaseModel):
    """Tolerant schema for the connectivity probe (any JSON object passes)."""

    ok: bool = True


def _llm_settings_response(settings) -> dict:
    """Build the masked status payload shared by GET/PUT/DELETE."""
    key = CredentialStore.get_llm_api_key()
    return {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "api_key_configured": key is not None,
        "api_key_masked": CredentialStore.mask(key) if key else None,
    }


@router.get("/llm")
def get_llm_settings() -> dict:
    """Return the current LLM configuration with the key masked."""
    return _llm_settings_response(get_settings())


@router.put("/llm")
def update_llm_settings(payload: LLMSettingsUpdate) -> dict:
    """Update only the provided fields; an empty ``api_key`` is a no-op."""
    settings = get_settings()
    if payload.base_url:
        settings.llm_base_url = payload.base_url
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


@router.post("/llm/test")
async def test_llm_settings() -> dict:
    """Probe connectivity with the current config; never logs or echoes the key."""
    settings = get_settings()
    api_key = CredentialStore.get_llm_api_key()
    if not api_key:
        return {"ok": False, "latency_ms": 0, "error": "LLM API key is not configured"}

    started = time.monotonic()
    try:
        client = LLMClient(
            base_url=settings.llm_base_url,
            api_key=api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_sec,
        )
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
