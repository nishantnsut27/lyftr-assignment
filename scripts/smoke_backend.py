import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


class SmokeFailure(Exception):
    pass


def require(condition: bool, description: str) -> None:
    if not condition:
        raise SmokeFailure(description)


def json_request(client: httpx.Client, method: str, path: str, status: int, **kwargs: Any) -> Any:
    response = client.request(method, path, **kwargs)
    require(
        response.status_code == status,
        f"{method} {path}: expected {status}, got {response.status_code}",
    )
    require(
        response.headers.get("content-type", "").startswith("application/json"),
        f"{path}: response must be JSON",
    )
    return response.json()


def history_digest(history: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(history, sort_keys=True).encode()).hexdigest()


def assert_metadata(body: dict[str, Any], model: str) -> None:
    require(
        isinstance(body.get("reply"), str) and bool(body["reply"].strip()),
        "reply must be non-empty text",
    )
    metadata = body.get("metadata", {})
    require(metadata.get("model") == model, "model does not match configured LiteLLM model")
    require(
        metadata.get("resolution_source") in {"LIVE_INFERENCE", "LLM_CACHE"},
        "invalid resolution source",
    )
    for field in ("latency_ms", "input_tokens", "output_tokens", "fallback_attempts"):
        require(
            type(metadata.get(field)) is int and metadata[field] >= 0,
            f"{field} must be a non-negative integer",
        )
    require(
        metadata["output_tokens"] > 0,
        "completion must report provider output token usage",
    )
    if metadata["resolution_source"] == "LLM_CACHE":
        require(
            metadata.get("key_id") is None and metadata["fallback_attempts"] == 0,
            "cache must have null key ID and zero fallbacks",
        )
    else:
        require(
            isinstance(metadata.get("key_id"), str) and metadata["key_id"].startswith("key_"),
            "live response must report a safe key ID",
        )


def chat(client: httpx.Client, session: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
    return json_request(
        client,
        "POST",
        "/chat",
        200,
        json={"session_id": session, "message": prompt, **kwargs},
    )


def run_smoke(client: httpx.Client, model: str, origin: str) -> dict[str, Any]:
    health = json_request(client, "GET", "/health", 200)
    require(
        health.get("status") == "ok"
        and health.get("keys_configured", 0) >= 2
        and health.get("cache_enabled") is True,
        "health requires a loaded key pool, SQLite, and enabled cache",
    )
    print(f"PASS health: {health['keys_configured']} keys, cache enabled")

    run_id = uuid4().hex
    live_session = f"smoke-live-{run_id}"
    prompt = f"Reply with exactly this text: cache-check-{run_id}"
    live = chat(client, live_session, prompt)
    assert_metadata(live, model)
    require(
        live["metadata"]["resolution_source"] == "LIVE_INFERENCE",
        "fresh unique prompt must use live inference",
    )
    cached = chat(client, f"smoke-cache-{run_id}", prompt)
    assert_metadata(cached, model)
    require(
        cached["metadata"]["resolution_source"] == "LLM_CACHE",
        "identical first prompt must hit cache",
    )
    require(cached["reply"] == live["reply"], "cache reply differs from original")
    for field in ("input_tokens", "output_tokens"):
        require(
            cached["metadata"][field] == live["metadata"][field],
            "cache token usage differs from original",
        )
    require(
        cached["metadata"]["latency_ms"] < live["metadata"]["latency_ms"],
        "cache hit must have lower measured latency",
    )
    print(
        f"PASS cache: live {live['metadata']['latency_ms']} ms, "
        f"cache {cached['metadata']['latency_ms']} ms, "
        f"input {live['metadata']['input_tokens']}, output {live['metadata']['output_tokens']}"
    )

    different = chat(client, f"smoke-different-{run_id}", prompt + " and then add a period.")
    assert_metadata(different, model)
    require(
        different["metadata"]["resolution_source"] == "LIVE_INFERENCE",
        "different prompt reused cache",
    )

    stored = json_request(client, "GET", f"/sessions/{live_session}/messages", 200)
    require(
        [message["role"] for message in stored["messages"]] == ["user", "assistant"],
        "history must include the successful pair only",
    )
    require(stored["messages"][1]["metadata"] == live["metadata"], "stored metadata changed")
    json_request(client, "GET", f"/sessions/unknown-{run_id}/messages", 404)
    invalid = json_request(
        client,
        "POST",
        "/chat",
        422,
        json={"session_id": f"invalid-{run_id}", "message": " "},
    )
    require("detail" in invalid, "validation error missing detail")

    context_session = f"smoke-context-{run_id}"
    chat(
        client,
        context_session,
        "My name is Mira. Acknowledge in one sentence.",
        system_prompt="You are a concise assistant. Remember what the user tells you.",
    )
    follow_up = chat(client, context_session, "What is my name?")
    assert_metadata(follow_up, model)
    require(
        "mira" in follow_up["reply"].lower(),
        "follow-up did not remember the first turn",
    )
    context_history = json_request(client, "GET", f"/sessions/{context_session}/messages", 200)
    require(
        [message["role"] for message in context_history["messages"]]
        == ["user", "assistant", "user", "assistant"],
        "multi-turn history must exclude the system prompt",
    )
    print("PASS history, session prompt, multi-turn context, and validation")

    for failure_status in (429, 500):
        fallback = json_request(
            client,
            "POST",
            "/chat",
            200,
            json={
                "session_id": f"smoke-fallback-{failure_status}-{run_id}",
                "message": prompt,
            },
            headers={"X-Simulate-Failure": f"key_1={failure_status}"},
        )
        assert_metadata(fallback, model)
        require(
            fallback["metadata"]["key_id"] == "key_2"
            and fallback["metadata"]["fallback_attempts"] == 1,
            f"simulated {failure_status} must succeed on key_2",
        )
    if health["keys_configured"] >= 3:
        third_key = json_request(
            client,
            "POST",
            "/chat",
            200,
            json={"session_id": f"smoke-third-{run_id}", "message": prompt},
            headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
        )
        assert_metadata(third_key, model)
        require(
            third_key["metadata"]["key_id"] == "key_3"
            and third_key["metadata"]["fallback_attempts"] == 2,
            "two failures must succeed on key_3",
        )
    print("PASS deterministic failover with real replies")

    before_failure = json_request(client, "GET", f"/sessions/{live_session}/messages", 200)
    unavailable = json_request(
        client,
        "POST",
        "/chat",
        503,
        json={
            "session_id": live_session,
            "message": "Do not save this",
            "system_prompt": "Do not persist this prompt",
        },
        headers={"X-Simulate-Failure": "*=429"},
    )
    require(
        unavailable == {"detail": "all providers unavailable"},
        "wildcard error differs from exact contract",
    )
    after_failure = json_request(client, "GET", f"/sessions/{live_session}/messages", 200)
    require(after_failure == before_failure, "failed inference changed history")
    warm_failure = json_request(
        client,
        "POST",
        "/chat",
        503,
        json={"session_id": f"smoke-failed-{run_id}", "message": prompt},
        headers={"X-Simulate-Failure": "*=429"},
    )
    require(warm_failure == unavailable, "warm cache bypassed wildcard failure")
    unknown = json_request(client, "GET", f"/sessions/smoke-failed-{run_id}/messages", 404)
    require(unknown == {"detail": "session not found"}, "failure created a session")
    recovered = chat(client, f"smoke-failed-{run_id}", prompt)
    require(
        recovered["metadata"]["resolution_source"] == "LLM_CACHE",
        "failure leaked into the next request",
    )
    print("PASS exact wildcard 503, unchanged history, and recovery")

    cors = client.options(
        "/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    require(
        cors.status_code == 200 and cors.headers.get("access-control-allow-origin") == origin,
        "frontend CORS preflight failed",
    )
    print(f"PASS CORS: {origin}")
    return {
        "session_id": live_session,
        "prompt": prompt,
        "reply": live["reply"],
        "metadata": live["metadata"],
        "history_digest": history_digest(stored),
    }


def verify_restart(client: httpx.Client, checkpoint: dict[str, Any]) -> None:
    stored = json_request(client, "GET", f"/sessions/{checkpoint['session_id']}/messages", 200)
    require(
        history_digest(stored) == checkpoint["history_digest"],
        "history changed or disappeared after restart",
    )
    cached = chat(client, f"smoke-restart-{uuid4().hex}", checkpoint["prompt"])
    require(
        cached["metadata"]["resolution_source"] == "LLM_CACHE"
        and cached["reply"] == checkpoint["reply"],
        "disk cache did not survive restart",
    )
    for field in ("input_tokens", "output_tokens"):
        require(
            cached["metadata"][field] == checkpoint["metadata"][field],
            "cached usage changed after restart",
        )
    print("PASS restart: SQLite history and LiteLLM disk cache retained")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the live backend contract without reading or printing API keys."
    )
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--model", default="groq/openai/gpt-oss-20b")
    parser.add_argument("--origin", default="http://localhost:3000")
    parser.add_argument("--checkpoint", type=Path, default=Path(".cache/smoke/backend.json"))
    parser.add_argument(
        "--verify-restart",
        action="store_true",
        help="Run after restarting the backend; uses the prior checkpoint.",
    )
    args = parser.parse_args()
    try:
        with httpx.Client(base_url=args.url.rstrip("/"), timeout=120, trust_env=False) as client:
            if args.verify_restart:
                verify_restart(client, json.loads(args.checkpoint.read_text(encoding="utf-8")))
            else:
                checkpoint = run_smoke(client, args.model, args.origin)
                args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
                args.checkpoint.write_text(
                    json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8"
                )
                print("Checkpoint saved. Restart the backend and rerun with --verify-restart.")
    except (SmokeFailure, httpx.HTTPError, OSError, ValueError, KeyError) as error:
        description = str(error) if isinstance(error, SmokeFailure) else type(error).__name__
        print(f"FAIL {description}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
