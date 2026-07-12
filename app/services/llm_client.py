from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from app.core.config import Settings


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
            "model": self.settings.llm_model,
            "messages": [self._sanitize_message(message) for message in messages],
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        started_at = time.monotonic()
        response = httpx.post(
            self._chat_completions_url(),
            headers=headers,
            json=payload,
            timeout=self.settings.llm_timeout_seconds,
        )
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        message["_llm_trace"] = {
            "model": data.get("model") or self.settings.llm_model,
            "usage": data.get("usage") or {},
            "elapsed_ms": elapsed_ms,
            "finish_reason": choice.get("finish_reason") or "",
        }
        return message

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
