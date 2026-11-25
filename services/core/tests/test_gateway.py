"""Gateway client + chat endpoint tests.

All gateway traffic is faked with httpx.MockTransport — no real gateway, no
real API keys, no external calls. The "test-key" below is a dummy string
used only to prove the Authorization header is set on outgoing requests.

Run: python -m pytest tests/ -v
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest
from fastapi.testclient import TestClient

from app.gateway import GatewayClient, GatewayError, GatewayNotConfigured
from app.main import app
from app.routers.chat import get_gateway_client

MESSAGES = [{"role": "user", "content": "hello"}]
CHAINS = {
    "fast": ["model-a", "model-b"],
    "smart": ["model-a", "model-b"],
    "strategic": ["model-a"],
    "embedding": ["embed-a"],
}


def make_client(handler) -> GatewayClient:
    return GatewayClient(
        base_url="https://gateway.test/v1",
        api_key="test-key",
        role_chains=CHAINS,
        transport=httpx.MockTransport(handler),
    )


def ok_response(request: httpx.Request) -> httpx.Response:
    model = json.loads(request.content)["model"]
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
            ],
        },
    )


# --- (a) role chain picks the first model -----------------------------------

def test_chain_picks_first_model():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok_response(request)

    result = asyncio.run(make_client(handler).chat_completion("smart", MESSAGES))

    assert result["model"] == "model-a"
    assert len(seen) == 1
    assert seen[0].url.path == "/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer test-key"


# --- (b) 429 from model-a falls through to model-b ---------------------------

def test_fallback_on_429_then_success():
    tried = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        tried.append(model)
        if model == "model-a":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return ok_response(request)

    result = asyncio.run(make_client(handler).chat_completion("smart", MESSAGES))

    assert tried == ["model-a", "model-b"]
    assert result["model"] == "model-b"


def test_fallback_on_connection_error_then_success():
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model == "model-a":
            raise httpx.ConnectError("connection refused", request=request)
        return ok_response(request)

    result = asyncio.run(make_client(handler).chat_completion("smart", MESSAGES))
    assert result["model"] == "model-b"


# --- (c) all models fail -> GatewayError carrying per-model errors -----------

def test_all_models_fail_raises_gateway_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "upstream down"}})

    with pytest.raises(GatewayError) as excinfo:
        asyncio.run(make_client(handler).chat_completion("smart", MESSAGES))

    assert set(excinfo.value.errors) == {"model-a", "model-b"}
    assert "test-key" not in str(excinfo.value)


def test_unconfigured_client_raises_not_configured():
    client = GatewayClient(
        base_url="https://gateway.test/v1", api_key="", role_chains=CHAINS
    )
    with pytest.raises(GatewayNotConfigured):
        asyncio.run(client.chat_completion("smart", MESSAGES))


def test_list_models_via_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200, json={"object": "list", "data": [{"id": "model-a"}, {"id": "model-b"}]}
        )

    models = asyncio.run(make_client(handler).list_models())
    assert [m["id"] for m in models] == ["model-a", "model-b"]


# --- endpoint tests -----------------------------------------------------------

def override_client(handler) -> TestClient:
    app.dependency_overrides[get_gateway_client] = lambda: make_client(handler)
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


# (d) unconfigured gateway -> chat endpoint answers an honest 503
def test_chat_endpoint_503_when_gateway_unconfigured():
    client = TestClient(app)  # real settings: no GATEWAY_API_KEY in test env
    r = client.post("/api/chat/", json={"messages": MESSAGES})
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_chat_endpoint_success_with_mock_gateway():
    client = override_client(ok_response)
    r = client.post("/api/chat/", json={"messages": MESSAGES})
    assert r.status_code == 200
    assert r.json()["model"] == "model-a"


def test_chat_endpoint_rejects_empty_messages():
    client = override_client(ok_response)
    r = client.post("/api/chat/", json={"messages": []})
    assert r.status_code == 422


def test_chat_endpoint_rejects_unknown_role():
    client = override_client(ok_response)
    r = client.post("/api/chat/", json={"messages": MESSAGES, "role": "nope"})
    assert r.status_code == 400


def test_chat_models_endpoint_unconfigured():
    client = TestClient(app)
    r = client.get("/api/chat/models")
    assert r.status_code == 200
    body = r.json()
    assert body["gateway_configured"] is False
    assert set(body["roles"]) == {"fast", "smart", "strategic", "embedding"}
    assert body["gateway_models"] is None


def test_settings_models_endpoint_has_chains_and_no_secrets():
    client = TestClient(app)
    r = client.get("/api/settings/models")
    assert r.status_code == 200
    body = r.json()
    assert set(body["roles"]) == {"fast", "smart", "strategic", "embedding"}
    assert "api_key" not in r.text.lower()
    assert "gateway_api_key" not in r.text.lower()
