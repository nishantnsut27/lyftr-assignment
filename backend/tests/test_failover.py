import sqlite3

import litellm
import pytest
from fastapi.testclient import TestClient

from app.gateway import LiteLLMGateway
from app.main import create_app
from tests.conftest import TEST_KEYS, FakeCompletion, ProviderFailure


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_single_simulated_failure_uses_second_key(backend, status):
    response = backend.client.post(
        "/chat",
        json={"session_id": "s", "message": "Hello"},
        headers={"X-Simulate-Failure": f"key_1={status}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Reply: Hello"
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    assert body["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert [call["api_key"] for call in backend.completion.calls] == [TEST_KEYS[1]]


def test_two_simulated_failures_use_third_key(backend):
    response = backend.client.post(
        "/chat",
        json={"session_id": "s", "message": "Hello"},
        headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_3"
    assert response.json()["metadata"]["fallback_attempts"] == 2
    assert [call["api_key"] for call in backend.completion.calls] == [TEST_KEYS[2]]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_all_simulated_failures_return_exact_503_without_session(backend, status):
    response = backend.client.post(
        "/chat",
        json={"session_id": "failed", "message": "Hello", "system_prompt": "Never saved"},
        headers={"X-Simulate-Failure": f"*={status}"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert response.text == '{"detail":"all providers unavailable"}'
    assert backend.completion.calls == []
    assert backend.client.get("/sessions/failed/messages").json() == {"detail": "session not found"}
    with sqlite3.connect(backend.settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_wildcard_failure_bypasses_warm_cache_and_recovery_is_request_local(backend):
    successful = backend.client.post(
        "/chat", json={"session_id": "warm", "message": "Hello"}
    ).json()
    failed = backend.client.post(
        "/chat",
        json={"session_id": "failed", "message": "Hello"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert failed.status_code == 503
    assert backend.client.get("/sessions/failed/messages").status_code == 404
    recovered = backend.client.post(
        "/chat", json={"session_id": "failed", "message": "Hello"}
    ).json()
    assert recovered["reply"] == successful["reply"]
    assert recovered["metadata"]["resolution_source"] == "LLM_CACHE"
    assert len(backend.completion.calls) == 1


def test_single_failure_bypasses_warm_cache(backend):
    backend.client.post("/chat", json={"session_id": "warm", "message": "Hello"})
    response = backend.client.post(
        "/chat",
        json={"session_id": "demo", "message": "Hello"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert len(backend.completion.calls) == 2


def test_existing_session_history_and_prompt_unchanged_on_503(backend):
    backend.client.post(
        "/chat", json={"session_id": "s", "message": "Hello", "system_prompt": "Saved"}
    )
    before = backend.client.get("/sessions/s/messages").json()
    response = backend.client.post(
        "/chat",
        json={"session_id": "s", "message": "Do not save", "system_prompt": "Changed"},
        headers={"X-Simulate-Failure": "*=503"},
    )
    assert response.status_code == 503
    assert backend.client.get("/sessions/s/messages").json() == before
    backend.client.post("/chat", json={"session_id": "s", "message": "Continue"})
    assert backend.completion.calls[-1]["messages"][0] == {"role": "system", "content": "Saved"}


@pytest.mark.parametrize(
    "header",
    [
        "",
        "key_1",
        "key_1=401",
        "key_4=429",
        "*=504",
        "key_1=429,",
        "key_1=429,key_1=500",
        "key_1=429=500",
        "bad=429",
    ],
)
def test_invalid_enabled_simulation_is_422_and_has_no_effect(backend, header):
    response = backend.client.post(
        "/chat",
        json={"session_id": "s", "message": "Hello"},
        headers={"X-Simulate-Failure": header},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid failure simulation header"}
    assert backend.completion.calls == []
    assert backend.client.get("/sessions/s/messages").status_code == 404


@pytest.mark.parametrize("header", ["*=429", "invalid format"])
def test_disabled_simulation_is_completely_ignored(settings, header):
    disabled = settings.model_copy(update={"enable_failure_simulation": False})
    fake = FakeCompletion()
    with TestClient(create_app(disabled, gateway=LiteLLMGateway(disabled, fake))) as client:
        response = client.post(
            "/chat",
            json={"session_id": "s", "message": "Hello"},
            headers={"X-Simulate-Failure": header},
        )
        assert response.status_code == 200
        assert response.json()["metadata"]["key_id"] == "key_1"


@pytest.mark.parametrize("status", [429, 500, 501, 502, 503, 504, 599])
def test_actual_provider_status_falls_back_in_order(backend, status):
    backend.completion.failures[TEST_KEYS[0]] = ProviderFailure(status)
    backend.completion.failures[TEST_KEYS[1]] = ProviderFailure(500)
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_3"
    assert response.json()["metadata"]["fallback_attempts"] == 2
    assert [call["api_key"] for call in backend.completion.calls] == list(TEST_KEYS)
    assert all(
        call["num_retries"] == 0 and call["caching"] is False for call in backend.completion.calls
    )


@pytest.mark.parametrize(
    "marker", ["insufficient_quota", "quota exceeded", "quota exhausted", "exceeded your quota"]
)
def test_quota_errors_without_retryable_status_fall_back(backend, marker):
    backend.completion.failures[TEST_KEYS[0]] = ProviderFailure(
        403, marker + " secret provider text"
    )
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"


def test_litellm_rate_limit_exception_falls_back(backend):
    backend.completion.failures[TEST_KEYS[0]] = litellm.RateLimitError(
        "rate limited", llm_provider="groq", model="openai/gpt-oss-20b"
    )
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"


def test_every_real_key_failure_returns_exact_503_and_no_writes(backend):
    backend.completion.failures = {key: ProviderFailure(429, "private " + key) for key in TEST_KEYS}
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert [call["api_key"] for call in backend.completion.calls] == list(TEST_KEYS)
    assert all(key not in response.text for key in TEST_KEYS)
    assert backend.client.get("/sessions/s/messages").status_code == 404


def test_two_key_pool_is_supported(settings):
    configured = settings.model_copy(
        update={"llm_api_keys": type(settings.llm_api_keys)(",".join(TEST_KEYS[:2]))}
    )
    fake = FakeCompletion()
    with TestClient(create_app(configured, gateway=LiteLLMGateway(configured, fake))) as client:
        assert client.get("/health").json()["keys_configured"] == 2
        response = client.post(
            "/chat",
            json={"session_id": "s", "message": "Hello"},
            headers={"X-Simulate-Failure": "key_1=500"},
        )
        assert response.json()["metadata"]["key_id"] == "key_2"
