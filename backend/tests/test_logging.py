"""Grep-assert tests (SPEC 4.4): keys/tokens never appear in log output."""

import logging

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.core.errors import AppError
from app.services.llm_client import LLMClient


class _Ping(BaseModel):
    ok: bool = True


@respx.mock
async def test_key_never_appears_in_log_output(caplog):
    """A provider error echoing the key must not leak it into logs."""
    secret = "sk-super-secret-key-12345678"
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(
            401,
            json={"error": {"message": f"upstream echoed {secret}"}},
        )
    )
    client = LLMClient("https://api.deepseek.com", secret, "deepseek-v4-flash")
    with caplog.at_level(logging.INFO):
        with pytest.raises(AppError) as excinfo:
            await client.chat_json([{"role": "user", "content": "ping"}], _Ping)
    assert secret not in caplog.text
    assert secret not in excinfo.value.message
    assert "llm request status=401" in caplog.text


def test_app_startup_wires_logging(client):
    """App startup calls setup_logging(): root logger is configured."""
    root = logging.getLogger()
    assert root.level <= logging.INFO
    assert any(isinstance(h, logging.Handler) for h in root.handlers)
