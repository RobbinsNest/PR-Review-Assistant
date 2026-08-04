import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.core.errors import AppError
from app.services.llm_client import LLMClient


class Out(BaseModel):
    ok: bool


@respx.mock
async def test_chat_json_ok():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}))
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    out = await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert out.ok is True


@respx.mock
async def test_chat_json_repair_retry():
    route = respx.post("https://api.deepseek.com/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": false}'}}]}),
    ]
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    out = await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert out.ok is False
    assert len(route.calls) == 2


@respx.mock
async def test_chat_json_fails_after_retries():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]}))
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    with pytest.raises(AppError) as ei:
        await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert ei.value.code == "llm_json_parse_failed"


@respx.mock
async def test_repair_retry_appends_system_message():
    route = respx.post("https://api.deepseek.com/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
    ]
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert len(route.calls) == 2
    second_body = route.calls[1].request.content
    assert b"\xe4\xbf\xae\xe6\xad\xa3" in second_body  # second request carries the repair system message


@respx.mock
async def test_timeout_retries_once_then_succeeds():
    route = respx.post("https://api.deepseek.com/chat/completions")
    route.side_effect = [
        httpx.ReadTimeout("boom"),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
    ]
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    out = await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert out.ok is True
    assert route.call_count == 2


@respx.mock
async def test_timeout_retries_exhausted_raises_llm_timeout():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        side_effect=httpx.ReadTimeout("boom"))
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    with pytest.raises(AppError) as ei:
        await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert ei.value.code == "llm_timeout"


@respx.mock
async def test_request_payload_and_auth_header():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}))
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash", timeout=5.0)
    await client.chat_json([{"role": "user", "content": "hi"}], Out, temperature=0.1)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer k"
    body = request.read()
    payload = json.loads(body)
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["temperature"] == 0.1
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False
