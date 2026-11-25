"""Security test suite for SHAKIB AI Core.

Covers: JWT tampering/expiry/unknown-subject handling, the cross-user
access matrix (another user's data must be 404/invisible, never leaked),
upload abuse (path traversal names, double extensions, extension-based
extraction, empty files, content-type spoofing), injection payloads stored
inert, AUTH_REQUIRED enforcement on every protected POST, CORS allowlist
behaviour, the register-atomicity regression (no JWT_SECRET -> 503 with
no side effects), and a response-body scan proving stored provider keys,
passwords and password hashes never appear in any API response.

Same harness pattern as the other suites: throwaway SQLite DB, throwaway
JWT secret, all credentials/keys are clearly fake test values.
"""

import io
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="shakib-security-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-for-production"
os.environ.pop("ENCRYPTION_KEY", None)

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db as db_module
import app.files_service as files_service
from app.config import settings
from app.main import app
from app.models import User

db_module.reset_engine()
db_module.init_db()

client = TestClient(app)

TEST_JWT_SECRET = "test-only-jwt-secret-not-for-production"
SEC_A = {"email": "sec-a@example.com", "password": "sec-a-test-password"}
SEC_B = {"email": "sec-b@example.com", "password": "sec-b-test-password"}
SEC_KEY = "sk-test-FAKE-security-scan-key-4242"


@pytest.fixture(scope="module", autouse=True)
def uploads_dir(tmp_path_factory):
    """Redirect on-disk upload storage to a throwaway directory."""
    path = tmp_path_factory.mktemp("sec-uploads")
    old = files_service.UPLOADS_DIR
    files_service.UPLOADS_DIR = path
    yield path
    files_service.UPLOADS_DIR = old


def _register(creds: dict) -> dict:
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 201, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def a_token() -> str:
    return _register(SEC_A)["access_token"]


@pytest.fixture(scope="module")
def b_token() -> str:
    return _register(SEC_B)["access_token"]


def _upload(data: bytes, filename: str, token: str, content_type: str = "application/octet-stream"):
    return client.post(
        "/api/files/upload",
        files={"file": (filename, io.BytesIO(data), content_type)},
        headers=_auth(token),
    )


# ------------------------------------------------------------- JWT attacks
def test_jwt_flipped_signature_401(a_token):
    head, payload, sig = a_token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    bad = f"{head}.{payload}.{flipped}"
    assert client.get("/api/auth/me", headers=_auth(bad)).status_code == 401


def test_jwt_flipped_payload_401(a_token):
    head, payload, sig = a_token.split(".")
    flipped = ("A" if payload[0] != "A" else "B") + payload[1:]
    bad = f"{head}.{flipped}.{sig}"
    assert client.get("/api/auth/me", headers=_auth(bad)).status_code == 401


def test_jwt_wrong_secret_401(a_token):
    import app.security as security

    user_id = client.get("/api/auth/me", headers=_auth(a_token)).json()["user_id"]
    forged = pyjwt.encode(
        {"sub": str(user_id), "email": SEC_A["email"],
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "attacker-controlled-secret",
        algorithm="HS256",
    )
    assert security  # silence linter; token above is the attack artifact
    assert client.get("/api/auth/me", headers=_auth(forged)).status_code == 401


def test_jwt_expired_401(a_token):
    user_id = client.get("/api/auth/me", headers=_auth(a_token)).json()["user_id"]
    past = datetime.now(timezone.utc) - timedelta(hours=25)
    expired = pyjwt.encode(
        {"sub": str(user_id), "email": SEC_A["email"], "iat": past, "exp": past},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers=_auth(expired)).status_code == 401


def test_jwt_nonexistent_user_401():
    ghost = pyjwt.encode(
        {"sub": "99999999", "email": "ghost@example.com",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers=_auth(ghost)).status_code == 401


def test_jwt_deleted_user_401():
    body = _register({"email": "sec-gone@example.com", "password": "gone-test-password"})
    token = body["access_token"]
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200
    db = db_module.SessionLocal()
    try:
        user = db.get(User, body["user_id"])
        db.delete(user)
        db.commit()
    finally:
        db.close()
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_jwt_alg_none_401(a_token):
    user_id = client.get("/api/auth/me", headers=_auth(a_token)).json()["user_id"]
    none_token = pyjwt.encode(
        {"sub": str(user_id), "email": SEC_A["email"],
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        key="",
        algorithm="none",
    )
    assert client.get("/api/auth/me", headers=_auth(none_token)).status_code == 401


# ------------------------------------------------- register atomicity fix
def test_register_without_jwt_secret_is_atomic(monkeypatch):
    """Regression: with JWT_SECRET unset, register must 503 and leave NO
    user row behind (previously the row was committed, then token creation
    failed — the account existed but its owner could never get a token,
    and a retry hit 409)."""
    creds = {"email": "sec-atomic@example.com", "password": "atomic-test-password"}
    monkeypatch.setattr(settings, "jwt_secret", "")
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 503
    monkeypatch.undo()
    # No side effects: login fails (user does not exist) ...
    r = client.post("/api/auth/login", json=creds)
    assert r.status_code == 401
    # ... and registering the same email now succeeds (no phantom 409).
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 201


# --------------------------------------------------- cross-user access matrix
@pytest.fixture(scope="module")
def a_assets(a_token) -> dict:
    r = client.post(
        "/api/conversations/", json={"title": "A private chat"}, headers=_auth(a_token)
    )
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]
    r = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "A secret message"},
        headers=_auth(a_token),
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/memory/",
        json={"kind": "fact", "content": "A private memory"},
        headers=_auth(a_token),
    )
    assert r.status_code == 201, r.text
    mem_id = r.json()["id"]
    r = _upload(b"A private document", "a-private.txt", a_token)
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    r = client.post(
        "/api/settings/keys",
        json={"provider": "secprovider", "api_key": SEC_KEY},
        headers=_auth(a_token),
    )
    assert r.status_code == 201, r.text
    assets = {"conv_id": conv_id, "mem_id": mem_id, "doc_id": doc_id}
    yield assets
    # Teardown: remove A's assets so this module leaves shared tables
    # (notably user_api_keys, which test_auth_storage inspects unscoped)
    # exactly as it found them, whatever order suites run in.
    client.delete("/api/settings/keys/secprovider", headers=_auth(a_token))
    client.delete(f"/api/conversations/{conv_id}", headers=_auth(a_token))
    client.delete(f"/api/memory/{mem_id}", headers=_auth(a_token))
    client.delete(f"/api/files/{doc_id}", headers=_auth(a_token))


def test_cross_user_conversation_get_404(a_assets, b_token):
    r = client.get(f"/api/conversations/{a_assets['conv_id']}", headers=_auth(b_token))
    assert r.status_code == 404


def test_cross_user_conversation_delete_404(a_assets, b_token, a_token):
    r = client.delete(f"/api/conversations/{a_assets['conv_id']}", headers=_auth(b_token))
    assert r.status_code == 404
    # Still there for the owner.
    assert client.get(
        f"/api/conversations/{a_assets['conv_id']}", headers=_auth(a_token)
    ).status_code == 200


def test_cross_user_messages_404(a_assets, b_token):
    cid = a_assets["conv_id"]
    assert client.get(
        f"/api/conversations/{cid}/messages", headers=_auth(b_token)
    ).status_code == 404
    r = client.post(
        f"/api/conversations/{cid}/messages",
        json={"role": "user", "content": "intrusion"},
        headers=_auth(b_token),
    )
    assert r.status_code == 404


def test_cross_user_conversation_not_in_list(a_assets, b_token):
    r = client.get("/api/conversations/", headers=_auth(b_token))
    assert all(c["id"] != a_assets["conv_id"] for c in r.json()["conversations"])


def test_cross_user_memory_delete_404_and_list_clean(a_assets, b_token, a_token):
    r = client.delete(f"/api/memory/{a_assets['mem_id']}", headers=_auth(b_token))
    assert r.status_code == 404
    r = client.get("/api/memory/", headers=_auth(b_token))
    assert all(i["id"] != a_assets["mem_id"] for i in r.json()["items"])
    # Still there for the owner.
    r = client.get("/api/memory/", headers=_auth(a_token))
    assert any(i["id"] == a_assets["mem_id"] for i in r.json()["items"])


def test_cross_user_document_get_delete_404(a_assets, b_token, a_token):
    did = a_assets["doc_id"]
    assert client.get(f"/api/files/{did}", headers=_auth(b_token)).status_code == 404
    assert client.delete(f"/api/files/{did}", headers=_auth(b_token)).status_code == 404
    r = client.get("/api/files/", headers=_auth(b_token))
    assert all(d["id"] != did for d in r.json()["documents"])
    # Anonymous scope must not see it either.
    assert client.get(f"/api/files/{did}").status_code == 404
    # Still there for the owner.
    assert client.get(f"/api/files/{did}", headers=_auth(a_token)).status_code == 200


def test_cross_user_keys_list_never_contains_others(a_assets, b_token):
    r = client.get("/api/settings/keys", headers=_auth(b_token))
    assert r.status_code == 200
    providers = [k["provider"] for k in r.json()["keys"]]
    assert "secprovider" not in providers
    assert SEC_KEY not in r.text
    assert SEC_KEY[-4:] not in r.text


# ------------------------------------------------------------ upload abuse
def test_upload_traversal_filename_neutralised(a_token):
    r = _upload(b"traversal attempt", "../../evil.txt", a_token)
    assert r.status_code == 201, r.text
    body = r.json()
    # Path.name strips the directories: stored name is a bare filename.
    assert body["filename"] == "evil.txt"
    assert "/" not in body["filename"] and ".." not in body["filename"]
    # And the bytes landed inside the uploads sandbox, nowhere else.
    stored = files_service.UPLOADS_DIR / str(
        client.get("/api/auth/me", headers=_auth(a_token)).json()["user_id"]
    ) / str(body["id"])
    assert stored.exists()


def test_upload_double_extension_415(a_token):
    r = _upload(b"MZ fake", "evil.pdf.exe", a_token)
    assert r.status_code == 415


def test_upload_pdf_content_with_txt_extension_uses_extension(a_token):
    """Behaviour record: extraction is chosen by EXTENSION, content is not
    sniffed. PDF-flavoured ASCII bytes named .txt are stored as text."""
    payload = b"%PDF-1.4 this is not really a pdf, just bytes"
    r = _upload(payload, "disguised.txt", a_token)
    assert r.status_code == 201, r.text
    assert r.json()["mime"] == "text/plain"
    doc = client.get(f"/api/files/{r.json()['id']}", headers=_auth(a_token)).json()
    assert doc["text"] == payload.decode()


def test_upload_empty_file(a_token):
    r = _upload(b"", "empty.txt", a_token)
    assert r.status_code == 201, r.text
    assert r.json()["size"] == 0
    assert r.json()["text_chars"] == 0


def test_upload_content_type_spoofing_ignored(a_token):
    """The declared multipart content type is never trusted: a .txt file
    claiming to be a PDF is still handled (and labelled) as text."""
    r = _upload(b"plain words", "note.txt", a_token, content_type="application/pdf")
    assert r.status_code == 201, r.text
    assert r.json()["mime"] == "text/plain"


# ---------------------------------------------------------------- injection
SQLI_TITLE = "'); DROP TABLE users; --"
XSS_TITLE = "<script>alert('xss')</script>"


def test_injection_conversation_title_stored_verbatim(a_token):
    title = SQLI_TITLE + XSS_TITLE
    r = client.post("/api/conversations/", json={"title": title}, headers=_auth(a_token))
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]
    assert r.json()["title"] == title  # inert, stored verbatim
    r = client.get(f"/api/conversations/{conv_id}", headers=_auth(a_token))
    assert r.status_code == 200
    assert r.json()["title"] == title
    # The users table obviously survived: a fresh registration still works.
    r = client.post(
        "/api/auth/register",
        json={"email": "sec-after-sqli@example.com", "password": "after-test-password"},
    )
    assert r.status_code == 201


def test_injection_memory_content_stored_verbatim(a_token):
    content = "Robert'); DROP TABLE memory_items; -- <script>alert(2)</script>"
    r = client.post(
        "/api/memory/", json={"kind": "note", "content": content}, headers=_auth(a_token)
    )
    assert r.status_code == 201, r.text
    assert r.json()["content"] == content
    r = client.get("/api/memory/", headers=_auth(a_token))
    assert r.status_code == 200
    assert any(i["content"] == content for i in r.json()["items"])


# --------------------------------------------------------- AUTH_REQUIRED on
def test_auth_required_blocks_all_protected_posts(monkeypatch):
    monkeypatch.setattr(settings, "auth_required", True)
    try:
        r = client.post(
            "/api/chat/", json={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert r.status_code == 401, r.text
        r = client.post("/api/research/", json={"query": "a test query"})
        assert r.status_code == 401, r.text
        r = client.post("/api/council/", json={"report_markdown": "# report"})
        assert r.status_code == 401, r.text
        r = client.post("/api/images/generate", json={"prompt": "a cat"})
        assert r.status_code == 401, r.text
        # File upload too (optional-user dependency enforces when required).
        r = client.post(
            "/api/files/upload",
            files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
        )
        assert r.status_code == 401, r.text
    finally:
        monkeypatch.setattr(settings, "auth_required", False)


# -------------------------------------------------------------------- CORS
def test_cors_allows_configured_dev_origin():
    r = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_cors_rejects_unlisted_origin():
    r = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# ------------------------------------------- secrets never leak in responses
def test_secrets_never_appear_in_any_response(a_assets, a_token):
    # A's stored provider key, A's password and A's bcrypt hash must not
    # appear in ANY response body, from any endpoint, for either user.
    with db_module.engine.connect() as conn:
        pw_hash = conn.execute(
            text("SELECT password_hash FROM users WHERE email = :e"),
            {"e": SEC_A["email"]},
        ).scalar_one()
    forbidden = [SEC_KEY, SEC_A["password"], pw_hash, "password_hash", "encrypted_key"]

    responses = [
        client.post("/api/auth/login", json=SEC_A),
        client.get("/api/auth/me", headers=_auth(a_token)),
        client.get("/api/settings/keys", headers=_auth(a_token)),
        client.get("/api/settings/models"),
        client.get("/api/conversations/", headers=_auth(a_token)),
        client.get("/api/memory/", headers=_auth(a_token)),
        client.get("/api/files/", headers=_auth(a_token)),
        client.get("/api/skills/"),
        client.get("/health"),
    ]
    for resp in responses:
        for needle in forbidden:
            assert needle not in resp.text, f"{needle!r} leaked in {resp.request.url}"
