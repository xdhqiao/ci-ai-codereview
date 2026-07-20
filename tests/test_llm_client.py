import httpx
import pytest

from app.core.config import Settings
from app.services.llm_client import LLMClient


def _success_response(model: str = "provider-model") -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://llm.example.com/chat/completions"),
        json={
            "model": model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )


def _error_response(status_code: int, *, retry_after: str = "") -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://llm.example.com/chat/completions"),
        headers=headers,
        json={"error": "temporary failure"},
    )


def test_default_primary_and_fallback_models_match_current_deepseek_configuration():
    settings = Settings()

    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.llm_fallback_model == "deepseek-v4-flash"
    assert settings.llm_api_retry_times == 2


def test_chat_retries_twice_with_fallback_model_after_transient_failures(monkeypatch):
    requested_models: list[str] = []
    responses = [
        _error_response(503),
        httpx.ReadTimeout(
            "read timed out",
            request=httpx.Request("POST", "https://llm.example.com/chat/completions"),
        ),
        _success_response(),
    ]

    def fake_post(*_args, **kwargs):
        requested_models.append(kwargs["json"]["model"])
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    sleep_delays: list[float] = []
    monkeypatch.setattr("app.services.llm_client.httpx.post", fake_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", sleep_delays.append)
    settings = Settings(
        llm_url="https://llm.example.com",
        llm_mock_enabled=False,
        llm_model="primary-model",
        llm_fallback_model="stable-model",
        llm_api_retry_times=2,
        llm_retry_backoff_seconds=0,
    )

    message = LLMClient(settings).chat([{"role": "user", "content": "review"}])

    assert requested_models == ["primary-model", "stable-model", "stable-model"]
    assert sleep_delays == [0.0, 0.0]
    assert message["content"] == "ok"
    assert message["_llm_trace"]["model"] == "provider-model"
    assert message["_llm_trace"]["requested_model"] == "stable-model"
    assert message["_llm_trace"]["fallback_used"] is True
    assert message["_llm_trace"]["api_attempt_count"] == 3


@pytest.mark.parametrize("status_code", [400, 401, 402, 403, 404, 422])
def test_chat_does_not_retry_permanent_http_errors(monkeypatch, status_code):
    requested_models: list[str] = []

    def fake_post(*_args, **kwargs):
        requested_models.append(kwargs["json"]["model"])
        return _error_response(status_code)

    monkeypatch.setattr("app.services.llm_client.httpx.post", fake_post)
    settings = Settings(
        llm_url="https://llm.example.com",
        llm_mock_enabled=False,
        llm_model="primary-model",
        llm_fallback_model="stable-model",
        llm_api_retry_times=2,
    )

    with pytest.raises(httpx.HTTPStatusError):
        LLMClient(settings).chat([{"role": "user", "content": "review"}])

    assert requested_models == ["primary-model"]


def test_chat_honors_retry_after_and_uses_primary_as_empty_fallback(monkeypatch):
    requested_models: list[str] = []
    responses = [_error_response(429, retry_after="2"), _success_response("primary-model")]

    def fake_post(*_args, **kwargs):
        requested_models.append(kwargs["json"]["model"])
        return responses.pop(0)

    sleep_delays: list[float] = []
    monkeypatch.setattr("app.services.llm_client.httpx.post", fake_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", sleep_delays.append)
    settings = Settings(
        llm_url="https://llm.example.com",
        llm_mock_enabled=False,
        llm_model="primary-model",
        llm_fallback_model="",
        llm_api_retry_times=2,
        llm_retry_backoff_max_seconds=8,
    )

    message = LLMClient(settings).chat([{"role": "user", "content": "review"}])

    assert requested_models == ["primary-model", "primary-model"]
    assert sleep_delays == [2.0]
    assert message["_llm_trace"]["api_attempt_count"] == 2


def test_chat_retries_malformed_success_response_with_fallback(monkeypatch):
    requested_models: list[str] = []
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://llm.example.com/chat/completions"),
            json={"choices": []},
        ),
        _success_response("stable-model"),
    ]

    def fake_post(*_args, **kwargs):
        requested_models.append(kwargs["json"]["model"])
        return responses.pop(0)

    monkeypatch.setattr("app.services.llm_client.httpx.post", fake_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda _delay: None)
    settings = Settings(
        llm_url="https://llm.example.com",
        llm_mock_enabled=False,
        llm_model="primary-model",
        llm_fallback_model="stable-model",
        llm_api_retry_times=2,
        llm_retry_backoff_seconds=0,
    )

    message = LLMClient(settings).chat([{"role": "user", "content": "review"}])

    assert requested_models == ["primary-model", "stable-model"]
    assert message["_llm_trace"]["requested_model"] == "stable-model"
