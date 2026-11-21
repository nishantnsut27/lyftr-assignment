from fastapi.testclient import TestClient
from scripts.smoke_backend import run_smoke, verify_restart

from app.gateway import LiteLLMGateway
from app.main import create_app
from tests.conftest import TEST_KEYS, FakeCompletion


def test_smoke_journeys_and_restart_checkpoint_with_fake_inference(settings, capsys):
    # Compare actual disk-cache latency with a realistic provider delay on busy hosts.
    with TestClient(
        create_app(settings, gateway=LiteLLMGateway(settings, FakeCompletion(delay=0.5)))
    ) as client:
        checkpoint = run_smoke(client, settings.llm_model, "http://localhost:3000")
    with TestClient(
        create_app(settings, gateway=LiteLLMGateway(settings, FakeCompletion()))
    ) as client:
        verify_restart(client, checkpoint)
    output = capsys.readouterr().out
    assert "PASS deterministic failover with real replies" in output
    assert "PASS restart" in output
    assert all(key not in output for key in TEST_KEYS)
