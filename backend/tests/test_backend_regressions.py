import asyncio
import socket
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.gateway import LiteLLMGateway
from app.main import create_app
from tests.conftest import TEST_KEYS, FakeCompletion


def test_cached_history_preserves_all_metadata_and_null_key(backend):
    backend.client.post("/chat", json={"session_id": "live", "message": "Hello"})
    cached = backend.client.post("/chat", json={"session_id": "cached", "message": "Hello"}).json()
    history = backend.client.get("/sessions/cached/messages").json()["messages"]
    assert "metadata" not in history[0]
    assert history[1]["metadata"] == cached["metadata"]
    assert history[1]["metadata"]["key_id"] is None


def test_health_rejects_disabled_cache(backend, monkeypatch):
    monkeypatch.setattr(backend.gateway.cache, "type", "local")
    response = backend.client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "cache unavailable"}


def test_health_rejects_unreachable_disk_cache_without_leaking(backend, monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise OSError("private cache path " + TEST_KEYS[0])

    monkeypatch.setattr(backend.gateway.cache.cache.disk_cache, "set", unavailable)
    response = backend.client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "cache unavailable"}
    assert "private" not in response.text + caplog.text
    assert TEST_KEYS[0] not in response.text + caplog.text


def test_unhandled_error_does_not_escape_to_server_logs(backend, monkeypatch, caplog):
    def broken(session_id):
        raise RuntimeError("private detail " + TEST_KEYS[0])

    monkeypatch.setattr(backend.client.app.app.state.database, "load_session", broken)
    backend.client.raise_server_exceptions = True
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert all(record.exc_info is None for record in caplog.records)
    assert "private" not in caplog.text + response.text


def test_key_validation_structured_errors_are_redacted():
    secret = "private-only-one-key"
    with pytest.raises(ValidationError) as failure:
        Settings(_env_file=None, llm_api_keys=secret)
    assert secret not in str(failure.value)
    assert secret not in repr(failure.value.errors())
    assert secret not in failure.value.json()


@pytest.mark.parametrize("origin", ["http://*", "https://*.example.com", "https://example.com:0"])
def test_cors_wildcards_and_invalid_ports_are_rejected(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_api_keys=",".join(TEST_KEYS), allowed_origins=origin)


def test_invalid_gateway_reply_cannot_create_history(backend, monkeypatch):
    infer = backend.gateway.infer

    async def invalid_reply(messages, failures):
        return replace(await infer(messages, failures), reply=" ")

    monkeypatch.setattr(backend.gateway, "infer", invalid_reply)
    response = backend.client.post("/chat", json={"session_id": "s", "message": "Hello"})
    assert response.status_code == 500
    assert backend.client.get("/sessions/s/messages").status_code == 404


def test_provider_timeout_is_bounded_and_has_no_history(settings):
    bounded = settings.model_copy(update={"llm_timeout_seconds": 0.01})
    with TestClient(
        create_app(bounded, gateway=LiteLLMGateway(bounded, FakeCompletion(delay=0.2)))
    ) as client:
        response = client.post("/chat", json={"session_id": "s", "message": "Hello"})
        assert response.status_code == 502
        assert response.json() == {"detail": "could not generate a reply"}
        assert client.get("/sessions/s/messages").status_code == 404


def test_gateway_shutdown_closes_disk_handles(settings):
    gateway = LiteLLMGateway(settings, FakeCompletion())
    with TestClient(create_app(settings, gateway=gateway)) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/chat", json={"session_id": "s", "message": "Hello"}).status_code == 200
        assert (
            client.post("/chat", json={"session_id": "copy", "message": "Hello"}).status_code == 200
        )
    assert gateway.check_cache_health() is False
    # Windows rejects renaming an open SQLite file, exposing leaked thread-local cache handles.
    original = settings.llm_cache_dir / "cache.db"
    renamed = settings.llm_cache_dir / "closed.db"
    original.rename(renamed)
    renamed.rename(original)


async def test_tests_cannot_contact_external_providers():
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="External network"):
            await asyncio.to_thread(connection.connect, ("203.0.113.1", 443))
