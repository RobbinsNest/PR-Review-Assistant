"""OpenAI-compatible chat client with JSON schema validation and repair retry.

POSTs ``{base_url}/chat/completions`` with an OpenAI-compatible payload and
validates the model output against a pydantic schema.  Invalid output triggers
one repair retry with an appended system message; transport failures (timeouts
/ connection errors) are retried once before failing with ``AppError``.

Security: logs carry status codes and latency only - never request content or
the API key.
"""

import logging
import time

import httpx
from pydantic import BaseModel

from app.core.errors import AppError

logger = logging.getLogger(__name__)

#: System message appended on the repair retry after a parse/validation failure.
REPAIR_SYSTEM_MESSAGE = "你的输出必须是合法 JSON 且符合给定 schema，请修正"
#: Initial attempt + 1 retry (applies to both transport and parse failures).
RETRY_ATTEMPTS = 2


class LLMClient:
    """Async client for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self, base_url: str, api_key: str, model: str, timeout: float = 60.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def chat_json(
        self,
        messages: list[dict],
        response_schema: type[BaseModel],
        temperature: float = 0.2,
    ) -> BaseModel:
        """Return the validated schema instance parsed from the model output.

        On the first attempt the model output is parsed with
        ``response_schema.model_validate_json``; a parse/validation failure
        appends a system repair message and retries once, then raises
        ``AppError("llm_json_parse_failed")``.
        """
        payload_messages = list(messages)
        for attempt in range(RETRY_ATTEMPTS):
            response = await self._request_chat(payload_messages, temperature)
            content = _extract_content(response)
            try:
                return response_schema.model_validate_json(content)
            except ValueError as exc:
                if attempt == 0:
                    payload_messages = [
                        *payload_messages,
                        {"role": "system", "content": REPAIR_SYSTEM_MESSAGE},
                    ]
                    continue
                raise AppError(
                    "llm_json_parse_failed",
                    message="LLM output is not valid JSON matching the requested schema",
                ) from exc
        # Unreachable: the loop returns or raises on every attempt.
        raise AppError(
            "llm_json_parse_failed",
            message="LLM output is not valid JSON matching the requested schema",
        )

    async def _request_chat(
        self, messages: list[dict], temperature: float
    ) -> httpx.Response:
        """POST a chat completion; retry once on transport errors.

        Raises ``AppError("llm_timeout")`` after the retry is exhausted.
        """
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        last_error: Exception | None = None
        for _ in range(RETRY_ATTEMPTS):
            started = time.monotonic()
            try:
                response = await self._client.post(url, json=payload)
            except httpx.TransportError as exc:
                logger.warning(
                    "llm request failed latency_ms=%.1f",
                    (time.monotonic() - started) * 1000,
                )
                last_error = exc
                continue
            logger.info(
                "llm request status=%s latency_ms=%.1f",
                response.status_code,
                (time.monotonic() - started) * 1000,
            )
            return response
        raise AppError(
            "llm_timeout",
            message=f"LLM request failed after {RETRY_ATTEMPTS} attempts",
        ) from last_error


def _extract_content(response: httpx.Response) -> str | None:
    """Return ``choices[0].message.content`` or ``None`` for malformed payloads."""
    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
