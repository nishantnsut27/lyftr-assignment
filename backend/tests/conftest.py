import asyncio
import os
import socket
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from litellm.types.utils import ModelResponse

from app.config import Settings
from app.gateway import LiteLLMGateway
from app.main import create_app

TEST_KEYS = ("test-credential-alpha", "test-credential-beta", "test-credential-gamma")


class ProviderFailure(Exception):
    def __init__(self, status: int, message: str = "provider detail must remain private") -> None:
        super().__init__(message)
        self.status_code = status


class FakeCompletion:
    def __init__(self, delay: float = 0.04) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failures: dict[str, Exception] = {}
        self.delay = delay
        self.response_override: ModelResponse | None = None
        self.started: asyncio.Event | None = None

    async def __call__(self, **kwargs: Any) -> ModelResponse:
        self.calls.append(deepcopy(kwargs))
        if self.started is not None:
            self.started.set()
        await asyncio.sleep(self.delay)
        if kwargs["api_key"] in self.failures:
            raise self.failures[kwargs["api_key"]]
        if self.response_override is not None:
            return self.response_override
        messages = kwargs["messages"]
        reply = "Reply: " + " | ".join(
            message["content"] for message in messages if message["role"] == "user"
        )
        return ModelResponse(
            model="openai/gpt-oss-20b",
            choices=[{"message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
            usage={
                "prompt_tokens": sum(len(message["content"].split()) + 4 for message in messages),
                "completion_tokens": len(reply.split()),
                "total_tokens": 9999,
            },
        )


@dataclass
class BackendHarness:
    client: TestClient
    settings: Settings
    completion: FakeCompletion
    gateway: LiteLLMGateway


@pytest.fixture
def test_directory(request):
    artifact_root = os.getenv("LYFTR_TEST_ARTIFACTS")
    if not artifact_root:
        return request.getfixturevalue("tmp_path")
    # Restricted Windows tokens cannot read private mode-0700 pytest temp folders.
    directory = Path(artifact_root).resolve() / uuid4().hex
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def settings(test_directory):
    return Settings(
        _env_file=None,
        llm_api_keys=",".join(TEST_KEYS),
        database_url=f"sqlite:///{test_directory / 'app.db'}",
        llm_cache_dir=test_directory / "cache",
        enable_failure_simulation=True,
        allowed_origins="http://localhost:3000,https://lyftr.example",
        default_system_prompt="Answer briefly.",
    )


@pytest.fixture
def backend(settings):
    completion = FakeCompletion()
    gateway = LiteLLMGateway(settings, completion=completion)
    app = create_app(settings, gateway=gateway)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield BackendHarness(client, settings, completion, gateway)


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def checked_connect(connection, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("External network access is disabled in backend tests")
        return original_connect(connection, address)

    def checked_connect_ex(connection, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("External network access is disabled in backend tests")
        return original_connect_ex(connection, address)

    monkeypatch.setattr(socket.socket, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_connect_ex)
