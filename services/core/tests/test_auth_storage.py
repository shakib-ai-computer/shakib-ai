"""Tests for secure storage + authentication.

Covers: register/login/me, duplicate + wrong-password handling, per-user
isolation for conversations and memory, encrypted user API-key storage,
and AUTH_REQUIRED enforcement on the chat router.

Runs against a throwaway SQLite file; DATABASE_URL and JWT_SECRET are set
BEFORE the app modules are imported so settings/db bind to the test DB.
All passwords/keys here are throwaway test values, not real secrets.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="shakib-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-for-production"
os.environ.pop("ENCRYPTION_KEY", None)  # exercise the JWT-derived dev path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db as db_module
from app.config import settings
from app.main import app

db_module.reset_engine()
db_module.init_db()

client = TestClient(app)

ALICE = {"email": "alice@example.com", "password": "alice-test-password"}
BOB = {"email": "bob@example.com", "password": "bob-test-password"}
FAKE_PROVIDER_KEY = "sk-test-FAKE-provider-key-9876"


def _register(creds: dict) -> str:
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def alice_token() -> str:
    return _register(ALICE)


@pytest.fixture(scope="module")
def bob_token() -> str:
    return _register(BOB)


# ------------------------------------------------------------------- auth
def test_register_login_me_round_trip():
    token = _register({"email": "carol@example.com", "password": "carol-test-password"})
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["email"] == "carol@example.com"

    r = client.post(
        "/api/auth/login",
        json={"email": "carol@example.com", "password": "carol-test-password"},
    )
    assert r.status_code == 200
    login_token = r.json()["access_token"]
    r = client.get("/api/auth/me", headers=_auth(login_token))
    assert r.status_code == 200
    assert r.json()["email"] == "carol@example.com"


def test_register_short_password_rejected():
    r = client.post(
        "/api/auth/register", json={"email": "short@example.com", "password": "short"}
    )
    assert r.status_code == 422


def test_duplicate_register_409(alice_token):
    r = client.post("/api/auth/register", json=ALICE)
    assert r.status_code == 409


def test_wrong_password_401():
    r = client.post(
        "/api/auth/login",
        json={"email": ALICE["email"], "password": "definitely-wrong-password"},
    )
    assert r.status_code == 401


def test_me_without_token_401():
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=_auth("not-a-token")).status_code == 401


# ----------------------------------------------------------- conversations
def test_conversations_require_auth():
    assert client.get("/api/conversations/").status_code == 401
    assert client.post("/api/conversations/", json={"title": "x"}).status_code == 401


def test_conversation_crud_and_messages(alice_token):
    r = client.post(
        "/api/conversations/", json={"title": "First chat"}, headers=_auth(alice_token)
    )
    assert r.status_code == 201
    conv_id = r.json()["id"]

    r = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "hello"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201

    r = client.get(f"/api/conversations/{conv_id}", headers=_auth(alice_token))
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "First chat"
    assert [m["content"] for m in body["messages"]] == ["hello"]

    r = client.get("/api/conversations/", headers=_auth(alice_token))
    assert any(c["id"] == conv_id for c in r.json()["conversations"])

    r = client.delete(f"/api/conversations/{conv_id}", headers=_auth(alice_token))
    assert r.status_code == 204
    r = client.get(f"/api/conversations/{conv_id}", headers=_auth(alice_token))
    assert r.status_code == 404


def test_other_users_conversation_is_404(alice_token, bob_token):
    r = client.post(
        "/api/conversations/", json={"title": "Alice only"}, headers=_auth(alice_token)
    )
    conv_id = r.json()["id"]

    # Bob must not learn the conversation exists: 404, not 403.
    assert client.get(f"/api/conversations/{conv_id}", headers=_auth(bob_token)).status_code == 404
    assert client.delete(f"/api/conversations/{conv_id}", headers=_auth(bob_token)).status_code == 404
    r = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "intrusion"},
        headers=_auth(bob_token),
    )
    assert r.status_code == 404
    # Bob's list does not contain it either.
    r = client.get("/api/conversations/", headers=_auth(bob_token))
    assert all(c["id"] != conv_id for c in r.json()["conversations"])


# ----------------------------------------------------------------- memory
def test_memory_requires_auth():
    assert client.get("/api/memory/").status_code == 401
    assert client.post("/api/memory/", json={"content": "x"}).status_code == 401


def test_memory_crud_round_trip(alice_token, bob_token):
    r = client.post(
        "/api/memory/",
        json={"kind": "fact", "content": "Alice prefers Bengali reports"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201
    item_id = r.json()["id"]

    r = client.get("/api/memory/", headers=_auth(alice_token))
    assert [i["content"] for i in r.json()["items"]] == ["Alice prefers Bengali reports"]

    # Bob sees none of Alice's memory and cannot delete it.
    r = client.get("/api/memory/", headers=_auth(bob_token))
    assert r.json()["items"] == []
    assert client.delete(f"/api/memory/{item_id}", headers=_auth(bob_token)).status_code == 404

    assert client.delete(f"/api/memory/{item_id}", headers=_auth(alice_token)).status_code == 204
    r = client.get("/api/memory/", headers=_auth(alice_token))
    assert r.json()["items"] == []


# ------------------------------------------------------------- API keys
def test_api_key_stored_encrypted_and_never_returned(alice_token):
    r = client.post(
        "/api/settings/keys",
        json={"provider": "openai", "api_key": FAKE_PROVIDER_KEY},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "openai"
    assert body["last4"] == FAKE_PROVIDER_KEY[-4:]
    assert FAKE_PROVIDER_KEY not in r.text

    r = client.get("/api/settings/keys", headers=_auth(alice_token))
    assert r.status_code == 200
    assert FAKE_PROVIDER_KEY not in r.text
    keys = r.json()["keys"]
    assert len(keys) == 1 and keys[0]["last4"] == FAKE_PROVIDER_KEY[-4:]

    # Raw DB value must be Fernet ciphertext, not the plaintext key.
    with db_module.engine.connect() as conn:
        raw = conn.execute(text("SELECT encrypted_key FROM user_api_keys")).scalar_one()
    assert raw != FAKE_PROVIDER_KEY
    assert FAKE_PROVIDER_KEY not in raw

    # And it must decrypt back to the original (server-side use only).
    from app.security import decrypt_secret

    assert decrypt_secret(raw) == FAKE_PROVIDER_KEY

    r = client.delete("/api/settings/keys/openai", headers=_auth(alice_token))
    assert r.status_code == 204
    r = client.get("/api/settings/keys", headers=_auth(alice_token))
    assert r.json()["keys"] == []


def test_api_keys_require_auth():
    assert client.get("/api/settings/keys").status_code == 401
    assert (
        client.post(
            "/api/settings/keys", json={"provider": "x", "api_key": "y"}
        ).status_code
        == 401
    )


# ---------------------------------------------------------- AUTH_REQUIRED
def test_auth_required_enforcement(alice_token, monkeypatch):
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    monkeypatch.setattr(settings, "auth_required", True)
    try:
        # No token -> 401 before any gateway work happens.
        r = client.post("/api/chat/", json=payload)
        assert r.status_code == 401
        # Valid token -> passes auth and reaches the gateway-config check,
        # which honestly answers 503 while no gateway key is configured.
        r = client.post("/api/chat/", json=payload, headers=_auth(alice_token))
        assert r.status_code == 503
    finally:
        monkeypatch.setattr(settings, "auth_required", False)
    # And with the setting off, anonymous chat reaches the same 503.
    r = client.post("/api/chat/", json=payload)
    assert r.status_code == 503
