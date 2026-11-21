import json

import httpx
import litellm
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from app.errors import ProvidersUnavailable
from app.gateway import LiteLLMGateway
from tests.conftest import TEST_KEYS


async def test_locked_groq_adapter_maps_statuses_keys_messages_and_usage(settings, monkeypatch):
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        key = request.headers["authorization"].removeprefix("Bearer ")
        if key == TEST_KEYS[0]:
            return httpx.Response(
                429, json={"error": {"message": "rate limited", "type": "rate_limit_error"}}
            )
        if key == TEST_KEYS[1]:
            return httpx.Response(500, json={"error": {"message": "provider unavailable"}})
        return httpx.Response(
            200,
            json={
                "id": "fake-provider-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "openai/gpt-oss-20b",
                "service_tier": "on_demand",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Paris."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 17, "completion_tokens": 3, "total_tokens": 20},
            },
        )

    def mock_client(self, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(provider), trust_env=False)

    monkeypatch.setattr(AsyncHTTPHandler, "create_client", mock_client)

    async def completion(**kwargs):
        handler = AsyncHTTPHandler(timeout=kwargs["timeout"])
        try:
            return await litellm.acompletion(client=handler, **kwargs)
        finally:
            await handler.close()

    gateway = LiteLLMGateway(settings, completion)
    messages = [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": "Capital of France?"},
    ]
    try:
        response = await gateway.infer(messages, {})
        assert response.reply == "Paris."
        assert response.input_tokens == 17 and response.output_tokens == 3
        assert response.model == "groq/openai/gpt-oss-20b"
        assert response.key_id == "key_3" and response.fallback_attempts == 2
        assert len(requests) == 3
        assert [request.headers["authorization"] for request in requests] == [
            f"Bearer {key}" for key in TEST_KEYS
        ]
        for request in requests:
            body = json.loads(request.content)
            assert request.url.path == "/openai/v1/chat/completions"
            assert body["model"] == "openai/gpt-oss-20b"
            assert body["messages"] == messages
        cached = await gateway.infer(messages, {})
        assert cached.resolution_source == "LLM_CACHE"
        assert cached.input_tokens == 17 and cached.output_tokens == 3
        assert len(requests) == 3
        try:
            await gateway.infer(messages, {"*": 429})
        except ProvidersUnavailable:
            pass
        else:
            raise AssertionError("wildcard must bypass the cache and fail")
    finally:
        gateway.close()
