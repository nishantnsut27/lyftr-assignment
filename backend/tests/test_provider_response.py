import pytest
from litellm.types.utils import ModelResponse


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_tokens", -1),
        ("completion_tokens", -1),
        ("prompt_tokens", None),
        ("completion_tokens", None),
        ("prompt_tokens", True),
    ],
)
def test_invalid_provider_usage_is_not_cached_or_persisted(backend, field, value):
    response = ModelResponse(
        choices=[{"message": {"role": "assistant", "content": "Valid reply"}}],
        usage={"prompt_tokens": 12, "completion_tokens": 2},
    )
    setattr(response.usage, field, value)
    backend.completion.response_override = response
    invalid = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert invalid.status_code == 502
    assert invalid.json() == {"detail": "could not generate a reply"}
    assert backend.client.get("/sessions/s/messages").status_code == 404
    backend.completion.response_override = None
    recovered = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert recovered.status_code == 200
    assert recovered.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


@pytest.mark.parametrize("field,value", [("choices", []), ("usage", None)])
def test_missing_provider_completion_fields_return_safe_error(backend, field, value):
    response = ModelResponse(
        choices=[{"message": {"role": "assistant", "content": "Valid reply"}}],
        usage={"prompt_tokens": 12, "completion_tokens": 2},
    )
    setattr(response, field, value)
    backend.completion.response_override = response
    invalid = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert invalid.status_code == 502
    assert backend.client.get("/sessions/s/messages").status_code == 404


def test_corrupt_cache_entry_recovers_with_live_inference(backend):
    messages = [
        {"role": "system", "content": backend.settings.default_system_prompt},
        {"role": "user", "content": "Hello"},
    ]
    cache_key = backend.gateway.cache.get_cache_key(
        model=backend.settings.llm_model, messages=messages
    )
    backend.gateway.cache.cache.disk_cache.set(cache_key, "invalid serialized completion")
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 200
    assert response.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    second = backend.client.post("/chat", json={"session_id": "cached", "message": "Hello"})
    assert second.json()["metadata"]["resolution_source"] == "LLM_CACHE"
