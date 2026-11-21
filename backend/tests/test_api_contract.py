import json
import sqlite3
from datetime import datetime

import pytest

from tests.conftest import TEST_KEYS, ProviderFailure


def send(backend, session="session-a", message="Hello", **kwargs):
    return backend.client.post("/chat", json={"session_id": session, "message": message, **kwargs})


def test_health_and_exact_public_routes(backend):
    response = backend.client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "keys_configured": 3, "cache_enabled": True}
    routes = {(route.path, tuple(sorted(route.methods))) for route in backend.client.app.app.routes}
    assert routes == {
        ("/health", ("GET",)),
        ("/chat", ("POST",)),
        ("/sessions/{session_id}/messages", ("GET",)),
    }
    assert backend.client.get("/docs").status_code == 404


def test_live_response_and_persisted_schema(backend):
    response = send(backend, message="  Capital of France?  ")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "session-a"
    assert body["reply"] == "Reply: Capital of France?"
    metadata = body["metadata"]
    assert metadata["resolution_source"] == "LIVE_INFERENCE"
    assert metadata["model"] == "groq/openai/gpt-oss-20b"
    assert metadata["key_id"] == "key_1"
    assert metadata["fallback_attempts"] == 0
    assert type(metadata["latency_ms"]) is int and metadata["latency_ms"] >= 0
    assert metadata["input_tokens"] == 13
    assert metadata["output_tokens"] == 4
    assert all(key not in response.text for key in TEST_KEYS)

    history = backend.client.get("/sessions/session-a/messages").json()
    assert history == {
        "session_id": "session-a",
        "messages": [
            {"role": "user", "content": "Capital of France?"},
            {"role": "assistant", "content": body["reply"], "metadata": metadata},
        ],
    }
    with sqlite3.connect(backend.settings.database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
        assert {"id", "session_id", "role", "content", "metadata", "created_at"} <= columns
        rows = connection.execute(
            "SELECT role, metadata, created_at FROM messages ORDER BY id"
        ).fetchall()
        assert rows[0][1] is None
        assert json.loads(rows[1][1]) == metadata
        assert all(datetime.fromisoformat(row[2]).tzinfo is not None for row in rows)
        assert connection.execute("PRAGMA index_list(messages)").fetchall()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": "Hello"},
        {"session_id": "invalid"},
        {"session_id": "", "message": "Hello"},
        {"session_id": "   ", "message": "Hello"},
        {"session_id": "x" * 129, "message": "Hello"},
        {"session_id": 123, "message": "Hello"},
        {"session_id": None, "message": "Hello"},
        {"session_id": ["invalid"], "message": "Hello"},
        {"session_id": "invalid", "message": ""},
        {"session_id": "invalid", "message": "\t\n "},
        {"session_id": "invalid", "message": "x" * 4001},
        {"session_id": "invalid", "message": None},
        {"session_id": "invalid", "message": 123},
        {"session_id": "invalid", "message": ["Hello"]},
        {"session_id": "invalid", "message": True},
        {"session_id": "invalid", "message": "Hello", "system_prompt": 123},
        [],
        None,
    ],
)
def test_invalid_payload_is_422_without_any_write(backend, payload):
    response = backend.client.post(
        "/chat", content=json.dumps(payload), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "detail" in response.json()
    assert response.headers["content-type"].startswith("application/json")
    assert backend.completion.calls == []
    with sqlite3.connect(backend.settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


@pytest.mark.parametrize("payload", ["{", "", '{"session_id": "s", "message":', "not json"])
def test_malformed_json_is_safe_422(backend, payload):
    response = backend.client.post(
        "/chat", content=payload, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "detail" in response.json()
    assert backend.completion.calls == []


def test_trimmed_message_boundaries_and_session_boundaries(backend):
    assert send(backend, session="x", message=" a ").status_code == 200
    assert send(backend, session="x" * 128, message=" " + "b" * 4000 + " ").status_code == 200
    assert backend.completion.calls[-1]["messages"][-1]["content"] == "b" * 4000


def test_unknown_session_exact_404(backend):
    response = backend.client.get("/sessions/unknown/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_invalid_request_does_not_change_existing_history(backend):
    send(backend)
    before = backend.client.get("/sessions/session-a/messages").json()
    response = send(backend, message=" ", system_prompt="Do not save this")
    assert response.status_code == 422
    assert backend.client.get("/sessions/session-a/messages").json() == before
    assert len(backend.completion.calls) == 1


def test_sql_parameters_preserve_session_identity(backend):
    session = "s'; DROP TABLE messages; --"
    assert send(backend, session=session).status_code == 200
    assert backend.client.get(f"/sessions/{session}/messages").status_code == 200
    assert backend.client.get("/health").status_code == 200


def test_real_provider_error_is_json_and_redacted(backend, caplog):
    backend.completion.failures[TEST_KEYS[0]] = ProviderFailure(
        401, "SECRET provider token " + TEST_KEYS[0]
    )
    response = send(backend)
    assert response.status_code == 502
    assert response.json() == {"detail": "could not generate a reply"}
    assert len(backend.completion.calls) == 1
    assert backend.client.get("/sessions/session-a/messages").status_code == 404
    assert "SECRET" not in response.text + caplog.text
    assert all(key not in response.text + caplog.text for key in TEST_KEYS)


def test_health_fails_when_database_unreachable(backend, monkeypatch):
    def unavailable():
        raise sqlite3.OperationalError("private filesystem detail")

    monkeypatch.setattr(backend.client.app.app.state.database, "check_health", unavailable)
    response = backend.client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


def test_unhandled_errors_are_json_with_cors_and_safe_logs(backend, monkeypatch, caplog):
    def broken(session_id):
        raise RuntimeError("private traceback detail " + TEST_KEYS[0])

    monkeypatch.setattr(backend.client.app.app.state.database, "load_session", broken)
    response = backend.client.post(
        "/chat",
        json={"session_id": "broken", "message": "Hello"},
        headers={"Origin": "https://lyftr.example"},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert response.headers["access-control-allow-origin"] == "https://lyftr.example"
    assert "private" not in response.text + caplog.text
    assert TEST_KEYS[0] not in response.text + caplog.text


def test_cors_allows_frontend_and_failure_header(backend):
    response = backend.client.options(
        "/chat",
        headers={
            "Origin": "https://lyftr.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://lyftr.example"
    assert "x-simulate-failure" in response.headers["access-control-allow-headers"].lower()
    denied = backend.client.options(
        "/chat",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.status_code == 400
    assert denied.json() == {"detail": "origin, method, or headers not allowed"}
    assert "access-control-allow-origin" not in denied.headers


def test_cors_present_on_validation_and_503(backend):
    for payload, failure, status in [
        ({}, "key_1=429", 422),
        ({"session_id": "s", "message": "Hello"}, "*=429", 503),
    ]:
        response = backend.client.post(
            "/chat",
            json=payload,
            headers={"Origin": "https://lyftr.example", "X-Simulate-Failure": failure},
        )
        assert response.status_code == status
        assert response.headers["access-control-allow-origin"] == "https://lyftr.example"
