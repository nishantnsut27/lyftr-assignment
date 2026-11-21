import sqlite3

import pytest
from fastapi.testclient import TestClient
from litellm.caching.disk_cache import DiskCache

from app.gateway import LiteLLMGateway
from app.main import create_app
from tests.conftest import TEST_KEYS, FakeCompletion


def chat(client, session, message, **kwargs):
    response = client.post("/chat", json={"session_id": session, "message": message, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def test_identical_first_prompt_uses_real_litellm_disk_cache_with_original_usage(backend):
    assert isinstance(backend.gateway.cache.cache, DiskCache)
    live = chat(backend.client, "session-one", "What is the capital of France?")
    cached = chat(backend.client, "session-two", "What is the capital of France?")
    assert cached["reply"] == live["reply"]
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
    assert cached["metadata"]["key_id"] is None
    assert cached["metadata"]["fallback_attempts"] == 0
    assert cached["metadata"]["latency_ms"] < live["metadata"]["latency_ms"]
    for token_field in ["input_tokens", "output_tokens"]:
        assert cached["metadata"][token_field] == live["metadata"][token_field]
    assert len(backend.completion.calls) == 1
    stored = backend.client.get("/sessions/session-two/messages").json()["messages"][1]
    assert stored["metadata"]["resolution_source"] == "LLM_CACHE"
    assert stored["metadata"]["input_tokens"] == cached["metadata"]["input_tokens"]
    assert backend.settings.llm_cache_dir.joinpath("cache.db").exists()


def test_different_first_prompt_never_reuses_cached_response(backend):
    first = chat(backend.client, "s-one", "Capital of France?")
    second = chat(backend.client, "s-two", "Capital of Japan?")
    assert second["reply"] != first["reply"]
    assert second["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert len(backend.completion.calls) == 2


def test_system_prompt_changes_cache_identity_and_is_persisted_but_hidden(backend):
    chat(backend.client, "s-one", "Hello", system_prompt="Answer in French.")
    different = chat(backend.client, "s-two", "Hello", system_prompt="Answer in English.")
    same = chat(backend.client, "s-three", "Hello", system_prompt="Answer in French.")
    assert different["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert same["metadata"]["resolution_source"] == "LLM_CACHE"
    chat(backend.client, "s-one", "Continue")
    assert backend.completion.calls[-1]["messages"][0] == {
        "role": "system",
        "content": "Answer in French.",
    }
    history = backend.client.get("/sessions/s-one/messages").json()
    assert [message["role"] for message in history["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert "Answer in French" not in str(history)


def test_session_prompt_can_be_updated_and_empty_prompt_is_retained(backend):
    chat(backend.client, "s", "Hello", system_prompt="Initial prompt")
    chat(backend.client, "s", "Continue", system_prompt="Updated prompt")
    chat(backend.client, "s", "More")
    assert backend.completion.calls[-1]["messages"][0]["content"] == "Updated prompt"
    chat(backend.client, "s", "Clear", system_prompt="")
    chat(backend.client, "s", "Again")
    assert backend.completion.calls[-1]["messages"][0]["content"] == ""
    assert backend.client.get("/sessions/s/messages").status_code == 200


def test_multiturn_includes_history_in_order_and_usage_is_not_accumulated(backend):
    first = chat(backend.client, "s", "My name is Mira")
    second = chat(backend.client, "s", "What is my name?")
    sent_messages = backend.completion.calls[-1]["messages"]
    assert sent_messages == [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": "My name is Mira"},
        {"role": "assistant", "content": first["reply"]},
        {"role": "user", "content": "What is my name?"},
    ]
    expected_input = sum(len(message["content"].split()) + 4 for message in sent_messages)
    assert second["metadata"]["input_tokens"] == expected_input
    assert second["metadata"]["output_tokens"] == len(second["reply"].split())
    assert second["metadata"]["input_tokens"] != expected_input + first["metadata"]["input_tokens"]
    assert second["metadata"]["input_tokens"] != 9999
    history = backend.client.get("/sessions/s/messages").json()["messages"]
    assert [message["content"] for message in history] == [
        "My name is Mira",
        first["reply"],
        "What is my name?",
        second["reply"],
    ]


def test_sessions_and_cache_histories_are_isolated(backend):
    first = chat(backend.client, "s-one", "I am Mira")
    chat(backend.client, "s-two", "I am Arun")
    second_turn = chat(backend.client, "s-one", "Who am I?")
    assert "Arun" not in second_turn["reply"]
    new_first = chat(backend.client, "s-three", "Who am I?")
    assert new_first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert new_first["reply"] != second_turn["reply"]
    chat(backend.client, "s-copy", "I am Mira")
    copied_turn = chat(backend.client, "s-copy", "Who am I?")
    assert copied_turn["metadata"]["resolution_source"] == "LLM_CACHE"
    assert copied_turn["reply"] == second_turn["reply"]
    assert len(backend.client.get("/sessions/s-two/messages").json()["messages"]) == 2
    assert (
        backend.client.get("/sessions/s-one/messages").json()["messages"][1]["content"]
        == first["reply"]
    )


def test_history_prompt_and_disk_cache_survive_app_restart(settings):
    fake = FakeCompletion()
    with TestClient(create_app(settings, gateway=LiteLLMGateway(settings, fake))) as client:
        original = chat(client, "persisted", "Remember Mira", system_prompt="Be concise")
        original_history = client.get("/sessions/persisted/messages").json()

    next_fake = FakeCompletion()
    with TestClient(create_app(settings, gateway=LiteLLMGateway(settings, next_fake))) as restarted:
        assert restarted.get("/sessions/persisted/messages").json() == original_history
        cached = chat(restarted, "after-restart", "Remember Mira", system_prompt="Be concise")
        assert cached["reply"] == original["reply"]
        assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
        assert cached["metadata"]["input_tokens"] == original["metadata"]["input_tokens"]
        assert next_fake.calls == []
        chat(restarted, "persisted", "Continue")
        assert next_fake.calls[-1]["messages"][0]["content"] == "Be concise"
        assert len(next_fake.calls[-1]["messages"]) == 4


def test_configured_model_is_part_of_cache_identity(settings):
    fake = FakeCompletion()
    with TestClient(create_app(settings, gateway=LiteLLMGateway(settings, fake))) as client:
        chat(client, "s-one", "Hello")
    changed = settings.model_copy(update={"llm_model": "groq/llama-3.3-70b-versatile"})
    next_fake = FakeCompletion()
    with TestClient(create_app(changed, gateway=LiteLLMGateway(changed, next_fake))) as client:
        response = chat(client, "s-two", "Hello")
        assert response["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert response["metadata"]["model"] == changed.llm_model
        assert len(next_fake.calls) == 1


def test_changed_credentials_do_not_change_cache_identity(settings):
    with TestClient(
        create_app(settings, gateway=LiteLLMGateway(settings, FakeCompletion()))
    ) as client:
        original = chat(client, "first", "Hello")
    changed = settings.model_copy(
        update={"llm_api_keys": type(settings.llm_api_keys)("other-alpha,other-beta")}
    )
    next_fake = FakeCompletion()
    with TestClient(create_app(changed, gateway=LiteLLMGateway(changed, next_fake))) as client:
        response = chat(client, "second", "Hello")
        assert response["reply"] == original["reply"]
        assert response["metadata"]["resolution_source"] == "LLM_CACHE"
        assert next_fake.calls == []


def test_sqlite_rollback_covers_prompt_and_both_messages(backend):
    chat(backend.client, "s", "Hello", system_prompt="Saved prompt")
    before = backend.client.get("/sessions/s/messages").json()
    with sqlite3.connect(backend.settings.database_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_assistant BEFORE INSERT ON messages
               WHEN NEW.role = 'assistant'
               BEGIN SELECT RAISE(ABORT, 'test failure'); END"""
        )
    response = backend.client.post(
        "/chat", json={"session_id": "s", "message": "Rejected", "system_prompt": "Not saved"}
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert backend.client.get("/sessions/s/messages").json() == before
    with sqlite3.connect(backend.settings.database_path) as connection:
        assert (
            connection.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = 's'"
            ).fetchone()[0]
            == "Saved prompt"
        )
    new = backend.client.post("/chat", json={"session_id": "new", "message": "Rejected"})
    assert new.status_code == 500
    assert backend.client.get("/sessions/new/messages").status_code == 404


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_provider_reply_is_rejected_without_history(backend, content):
    from litellm.types.utils import ModelResponse

    backend.completion.response_override = ModelResponse(
        choices=[{"message": {"role": "assistant", "content": content}}],
        usage={"prompt_tokens": 12, "completion_tokens": 0},
    )
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 502
    assert response.json() == {"detail": "could not generate a reply"}
    assert backend.client.get("/sessions/s/messages").status_code == 404


def test_cache_fallback_keeps_original_usage_and_clears_key_metadata(backend):
    from tests.conftest import ProviderFailure

    backend.completion.failures[TEST_KEYS[0]] = ProviderFailure(429)
    live = chat(backend.client, "live", "Hello")
    cached = chat(backend.client, "cached", "Hello")
    assert live["metadata"]["key_id"] == "key_2"
    assert live["metadata"]["fallback_attempts"] == 1
    assert cached["metadata"]["key_id"] is None
    assert cached["metadata"]["fallback_attempts"] == 0
    assert cached["metadata"]["input_tokens"] == live["metadata"]["input_tokens"]
