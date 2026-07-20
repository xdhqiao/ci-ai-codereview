from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any

import httpx

from app.core.config import Settings


logger = logging.getLogger(__name__)
RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_mock(self) -> bool:
        return self.settings.llm_mock_enabled or not self.settings.llm_url

    def complete_json(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if self.is_mock:
            return {}
        message = self.chat(messages=messages, tools=tools)
        content = message.get("content") or ""
        return self._extract_json(content)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if self.is_mock:
            return {
                "role": "assistant",
                "content": "{}",
                "_llm_trace": {
                    "model": self.settings.llm_model,
                    "usage": {},
                    "elapsed_ms": 0,
                    "finish_reason": "mock",
                },
            }

        payload: dict[str, Any] = {
            "messages": [self._sanitize_message(message) for message in messages],
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        primary_model = self.settings.llm_model.strip()
        fallback_model = self.settings.llm_fallback_model.strip() or primary_model
        retry_times = max(0, self.settings.llm_api_retry_times)
        total_attempts = retry_times + 1
        request_started_at = time.monotonic()

        for attempt in range(1, total_attempts + 1):
            request_model = primary_model if attempt == 1 else fallback_model
            attempt_payload = {**payload, "model": request_model}
            attempt_started_at = time.monotonic()
            try:
                response = httpx.post(
                    self._chat_completions_url(),
                    headers=headers,
                    json=attempt_payload,
                    timeout=self.settings.llm_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                message = choice["message"]
                if not isinstance(message, dict):
                    raise ValueError("LLM response choice.message must be an object")
                message["_llm_trace"] = {
                    "model": data.get("model") or request_model,
                    "requested_model": request_model,
                    "fallback_used": attempt > 1,
                    "api_attempt_count": attempt,
                    "usage": data.get("usage") or {},
                    "elapsed_ms": int((time.monotonic() - request_started_at) * 1000),
                    "attempt_elapsed_ms": int((time.monotonic() - attempt_started_at) * 1000),
                    "finish_reason": choice.get("finish_reason") or "",
                }
                return message
            except Exception as exc:
                if attempt >= total_attempts or not self._is_retryable_error(exc):
                    raise
                delay_seconds = self._retry_delay_seconds(exc, attempt)
                logger.warning(
                    "LLM API request failed; retrying with fallback model: "
                    "attempt=%s/%s failed_model=%s next_model=%s delay_seconds=%.2f error=%s",
                    attempt,
                    total_attempts,
                    request_model,
                    fallback_model,
                    delay_seconds,
                    f"{type(exc).__name__}: {exc}",
                )
                time.sleep(delay_seconds)

        raise RuntimeError("LLM request exhausted without a response")

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in RETRYABLE_HTTP_STATUS_CODES
        if isinstance(error, httpx.TransportError):
            return True
        return isinstance(error, (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError))

    def _retry_delay_seconds(self, error: Exception, failed_attempt: int) -> float:
        maximum = max(0.0, self.settings.llm_retry_backoff_max_seconds)
        retry_after = self._retry_after_seconds(error)
        if retry_after is not None:
            return min(maximum, retry_after) if maximum else retry_after
        base = max(0.0, self.settings.llm_retry_backoff_seconds)
        exponential = base * (2 ** max(0, failed_attempt - 1))
        bounded = min(maximum, exponential) if maximum else exponential
        return random.uniform(bounded * 0.8, bounded * 1.2) if bounded else 0.0

    @staticmethod
    def _retry_after_seconds(error: Exception) -> float | None:
        if not isinstance(error, httpx.HTTPStatusError):
            return None
        value = error.response.headers.get("Retry-After", "").strip()
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    def _chat_completions_url(self) -> str:
        base_url = self.settings.llm_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _extract_json(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        if not stripped:
            return {}
        if stripped.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
            if match:
                stripped = match.group(1).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _sanitize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in message.items() if not key.startswith("_")}
