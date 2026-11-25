"""Tests for the file reader, image generation and skills registry.

Files: a real PDF is built in the test with WeasyPrint (HTML -> PDF, the
same renderer the research export uses) carrying a known English and a
known Bengali string; upload must extract both. Uploads are stored under a
throwaway directory (files_service.UPLOADS_DIR is monkeypatched) and a
throwaway SQLite DB; DATABASE_URL/JWT_SECRET are set BEFORE the app is
imported, mirroring tests/test_auth_storage.py.

Images: gateway traffic is faked with httpx.MockTransport — no real
gateway, no real keys, no external calls (same pattern as
tests/test_gateway.py).

Skills: statuses must flip with the same settings flags the feature
endpoints check.
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="shakib-files-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-for-production"
os.environ.pop("ENCRYPTION_KEY", None)

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db as db_module
import app.files_service as files_service
from app.config import settings
from app.gateway import GatewayClient
from app.main import app
from app.routers.chat import get_gateway_client

db_module.reset_engine()
db_module.init_db()

client = TestClient(app)

EN_TEXT = "SHAKIB AI file reader test document."
BN_TEXT = "ঢাকা বাংলাদেশের রাজধানী।"

DAVE = {"email": "dave@example.com", "password": "dave-test-password"}
ERIN = {"email": "erin@example.com", "password": "erin-test-password"}


@pytest.fixture(scope="module", autouse=True)
def uploads_dir(tmp_path_factory):
    """Redirect on-disk upload storage to a throwaway directory."""
    path = tmp_path_factory.mktemp("uploads")
    old = files_service.UPLOADS_DIR
    files_service.UPLOADS_DIR = path
    yield path
    files_service.UPLOADS_DIR = old


def _register(creds: dict) -> str:
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def dave_token() -> str:
    return _register(DAVE)


@pytest.fixture(scope="module")
def erin_token() -> str:
    return _register(ERIN)


def _sample_pdf() -> bytes:
    from weasyprint import HTML

    html = f"<html><body><p>{EN_TEXT}</p><p>{BN_TEXT}</p></body></html>"
    return HTML(string=html).write_pdf()


def _upload(data: bytes, filename: str, token: str | None = None):
    return client.post(
        "/api/files/upload",
        files={"file": (filename, io.BytesIO(data), "application/octet-stream")},
        headers=_auth(token) if token else {},
    )


# ------------------------------------------------------------------- files
def test_pdf_upload_extracts_english_and_bengali(dave_token):
    r = _upload(_sample_pdf(), "sample.pdf", dave_token)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "sample.pdf"
    assert body["mime"] == "application/pdf"
    assert body["size"] > 0
    assert body["text_chars"] > 0

    r = client.get(f"/api/files/{body['id']}", headers=_auth(dave_token))
    assert r.status_code == 200
    doc = r.json()
    assert EN_TEXT in doc["text"]
    assert BN_TEXT in doc["text"]
    assert doc["truncated"] is False


def test_txt_upload_and_anon_scope_round_trip():
    r = _upload("hello plain text".encode(), "note.txt")  # no token -> anon
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    assert r.json()["mime"] == "text/plain"

    # Anonymous list + read see it; the bytes landed under the anon scope.
    r = client.get("/api/files/")
    assert any(d["id"] == doc_id for d in r.json()["documents"])
    assert "text" not in r.json()["documents"][0]  # list is metadata only
    r = client.get(f"/api/files/{doc_id}")
    assert r.status_code == 200
    assert r.json()["text"] == "hello plain text"
    assert (files_service.UPLOADS_DIR / "anon" / str(doc_id)).exists()

    # Delete works and removes the document.
    assert client.delete(f"/api/files/{doc_id}").status_code == 204
    assert client.get(f"/api/files/{doc_id}").status_code == 404
    assert not (files_service.UPLOADS_DIR / "anon" / str(doc_id)).exists()


def test_docx_upload_extracts_text():
    import docx

    buffer = io.BytesIO()
    document = docx.Document()
    document.add_paragraph(EN_TEXT)
    document.save(buffer)

    r = _upload(buffer.getvalue(), "report.docx")
    assert r.status_code == 201, r.text
    r = client.get(f"/api/files/{r.json()['id']}")
    assert EN_TEXT in r.json()["text"]


def test_unsupported_type_415():
    r = _upload(b"MZ fake executable bytes", "evil.exe")
    assert r.status_code == 415
    assert "unsupported" in r.json()["detail"].lower()


def test_oversized_upload_413(monkeypatch):
    monkeypatch.setattr(files_service, "MAX_UPLOAD_BYTES", 16)
    r = _upload(b"x" * 64, "big.txt")
    assert r.status_code == 413


def test_corrupt_pdf_422_without_stack_trace():
    r = _upload(b"this is not a pdf at all", "broken.pdf")
    assert r.status_code == 422
    assert "could not be read" in r.json()["detail"]
    assert "Traceback" not in r.text


def test_cross_user_document_is_404(dave_token, erin_token):
    r = _upload(_sample_pdf(), "dave-only.pdf", dave_token)
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]

    # Erin must not learn the document exists: 404 on read and delete,
    # and it never appears in her list.
    assert client.get(f"/api/files/{doc_id}", headers=_auth(erin_token)).status_code == 404
    assert client.delete(f"/api/files/{doc_id}", headers=_auth(erin_token)).status_code == 404
    r = client.get("/api/files/", headers=_auth(erin_token))
    assert all(d["id"] != doc_id for d in r.json()["documents"])
    # Anonymous callers don't see a signed-in user's document either.
    assert client.get(f"/api/files/{doc_id}").status_code == 404
    # Dave still can.
    assert client.get(f"/api/files/{doc_id}", headers=_auth(dave_token)).status_code == 200


def test_invalid_token_is_401_not_anon():
    r = client.get("/api/files/", headers=_auth("not-a-token"))
    assert r.status_code == 401


# ------------------------------------------------------------------ images
CHAINS = {
    "fast": ["model-a"],
    "smart": ["image-model-a"],
    "strategic": ["model-a"],
    "embedding": ["embed-a"],
}

IMAGE_PAYLOAD = {
    "created": 1700000000,
    "data": [{"url": "https://images.test/cat.png", "revised_prompt": "a cat"}],
}


def _image_client(handler) -> GatewayClient:
    return GatewayClient(
        base_url="https://gateway.test/v1",
        api_key="test-key",
        role_chains=CHAINS,
        transport=httpx.MockTransport(handler),
    )


def teardown_function():
    app.dependency_overrides.clear()


def test_images_503_when_gateway_unconfigured():
    r = client.post("/api/images/generate", json={"prompt": "a cat"})
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_images_success_passes_gateway_payload_through():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=IMAGE_PAYLOAD)

    app.dependency_overrides[get_gateway_client] = lambda: _image_client(handler)
    r = client.post(
        "/api/images/generate",
        json={"prompt": "a cat", "size": "1024x1024"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == IMAGE_PAYLOAD  # payload passed through unchanged
    assert seen["path"] == "/v1/images/generations"
    assert seen["body"]["prompt"] == "a cat"
    assert seen["body"]["size"] == "1024x1024"
    # Default model = first of the smart chain; key only in the header.
    assert seen["body"]["model"] == "image-model-a"
    assert seen["auth"] == "Bearer test-key"
    assert "test-key" not in r.text


def test_images_explicit_model_and_gateway_error_502():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "custom-img"
        return httpx.Response(500, json={"error": {"message": "upstream down"}})

    app.dependency_overrides[get_gateway_client] = lambda: _image_client(handler)
    r = client.post(
        "/api/images/generate", json={"prompt": "a cat", "model": "custom-img"}
    )
    assert r.status_code == 502
    assert "upstream down" in r.json()["detail"]


# ------------------------------------------------------------------ skills
EXPECTED_SKILLS = {
    "deep_research",
    "critical_council",
    "file_reader",
    "image_generation",
    "long_term_memory",
    "voice",
}


def _skills_by_name() -> dict:
    r = client.get("/api/skills/")
    assert r.status_code == 200
    return {s["name"]: s for s in r.json()["skills"]}


def test_skills_registry_unconfigured_statuses():
    skills = _skills_by_name()
    assert set(skills) == EXPECTED_SKILLS
    for entry in skills.values():
        assert entry["description"]
    # Nothing configured in the test env: gateway-backed skills must say so.
    assert skills["deep_research"]["status"] == "needs_configuration"
    assert any("GATEWAY_API_KEY" in m for m in skills["deep_research"]["missing"])
    assert any("TAVILY_API_KEY" in m for m in skills["deep_research"]["missing"])
    assert skills["critical_council"]["status"] == "needs_configuration"
    assert skills["image_generation"]["status"] == "needs_configuration"
    # Server-local and browser capabilities are honest constants.
    assert skills["file_reader"]["status"] == "ready"
    assert skills["long_term_memory"]["status"] == "ready"
    assert skills["voice"]["status"] == "client_side"


def test_skills_statuses_flip_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "gateway_api_key", "test-only-key")
    monkeypatch.setattr(settings, "retriever", "duckduckgo")  # key-free
    skills = _skills_by_name()
    assert skills["deep_research"]["status"] == "ready"
    assert skills["deep_research"]["missing"] == []
    assert skills["critical_council"]["status"] == "ready"
    assert skills["image_generation"]["status"] == "ready"
    # Unchanged by gateway configuration:
    assert skills["file_reader"]["status"] == "ready"
    assert skills["voice"]["status"] == "client_side"
