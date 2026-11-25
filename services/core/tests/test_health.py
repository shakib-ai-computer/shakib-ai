"""Smoke tests for the SHAKIB AI Core scaffold.

Run: python -m pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "shakib-ai-core"
    # With no env keys set, the app must honestly report "not configured".
    assert body["gateway_configured"] is False


def test_stub_routers_return_501():
    """Feature modules are registered but must not fake functionality.

    Chat is implemented now (see tests/test_gateway.py — its POST endpoint
    answers 503, not a fake reply, while the gateway is unconfigured), the
    settings router serves /api/settings/models, research is implemented
    (tests/test_research.py — POST answers 503 while unconfigured), and
    council is implemented (tests/test_council.py — POST answers 503 while
    unconfigured); all four left this list. Auth and memory are implemented
    too (tests/test_auth_storage.py — DB-backed, JWT-protected), and files
    is implemented (tests/test_files_images_skills.py — DB-backed upload +
    extraction), so they left this list as well; only the settings index
    remains a stub.
    """
    for path in (
        "/api/settings/",
    ):
        r = client.get(path)
        assert r.status_code == 501, f"{path} returned {r.status_code}"
        assert "not implemented" in r.json()["detail"].lower()
