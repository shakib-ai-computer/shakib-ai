"""Live API integration check for SHAKIB AI Core (NOT a pytest module).

Boots the real Core app with uvicorn on a throwaway port, against a
throwaway SQLite DB and a dev-only JWT_SECRET, then walks the golden
path over real HTTP:

    health -> register -> login -> me -> memory add/list ->
    conversation + message -> file upload + read -> skills ->
    settings keys (masked) -> chat (503 expected: no gateway configured)
    -> CORS preflight -> cleanup

Every step's expected status is asserted; the script prints the REAL
observed status for each step and exits non-zero on any mismatch. Chat
returning 503 is the honest, expected result here: no model gateway is
configured in this environment, and the endpoint must say so instead of
fabricating a reply.

Run:  .venv/bin/python tests/integration_live.py
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

CORE_DIR = Path(__file__).resolve().parents[1]
PORT = 8137
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = "http://localhost:5173"

RESULTS: list[tuple[str, int, int, bool]] = []


def check(step: str, expected: int, resp: httpx.Response) -> httpx.Response:
    ok = resp.status_code == expected
    RESULTS.append((step, expected, resp.status_code, ok))
    print(f"[{'OK ' if ok else 'FAIL'}] {step:<46} expected {expected}  got {resp.status_code}")
    if not ok:
        print("       body:", resp.text[:300])
    return resp


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="shakib-live-")
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp}/live.db",
        "JWT_SECRET": "dev-only-live-check-secret",
        "AUTH_REQUIRED": "false",
    }
    env.pop("GATEWAY_API_KEY", None)  # chat MUST be unconfigured for step 10
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=CORE_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # trust_env=False: ignore HTTP(S)_PROXY env vars — this is a
        # localhost check and sandbox proxy settings corrupt URL parsing.
        client = httpx.Client(base_url=BASE, timeout=10, trust_env=False)
        # Wait for the server to come up.
        deadline = time.time() + 30
        while True:
            try:
                r = client.get("/health")
                if r.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.time() > deadline:
                print("server did not start within 30s")
                return 1
            time.sleep(0.5)

        check("GET /health", 200, r)
        print("       health body:", r.json())

        creds = {"email": "live-check@example.com", "password": "live-check-password"}
        r = check("POST /api/auth/register", 201, client.post("/api/auth/register", json=creds))
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        check("POST /api/auth/login", 200, client.post("/api/auth/login", json=creds))
        check("GET /api/auth/me", 200, client.get("/api/auth/me", headers=auth))

        r = check(
            "POST /api/memory/",
            201,
            client.post(
                "/api/memory/",
                json={"kind": "fact", "content": "live check memory"},
                headers=auth,
            ),
        )
        mem_id = r.json()["id"]
        r = check("GET /api/memory/", 200, client.get("/api/memory/", headers=auth))
        assert any(i["id"] == mem_id for i in r.json()["items"]), "memory item missing"

        r = check(
            "POST /api/conversations/",
            201,
            client.post("/api/conversations/", json={"title": "live check"}, headers=auth),
        )
        conv_id = r.json()["id"]
        check(
            "POST /api/conversations/{id}/messages",
            201,
            client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"role": "user", "content": "hello live"},
                headers=auth,
            ),
        )
        r = check(
            "GET /api/conversations/{id}",
            200,
            client.get(f"/api/conversations/{conv_id}", headers=auth),
        )
        assert [m["content"] for m in r.json()["messages"]] == ["hello live"]

        r = check(
            "POST /api/files/upload",
            201,
            client.post(
                "/api/files/upload",
                files={"file": ("live.txt", b"live upload text", "text/plain")},
                headers=auth,
            ),
        )
        doc_id = r.json()["id"]
        r = check("GET /api/files/{id}", 200, client.get(f"/api/files/{doc_id}", headers=auth))
        assert r.json()["text"] == "live upload text"

        r = check("GET /api/skills/", 200, client.get("/api/skills/"))
        print("       skills:", {s["name"]: s["status"] for s in r.json()["skills"]})

        fake_key = "sk-live-FAKE-key-0000111122223333"
        r = check(
            "POST /api/settings/keys",
            201,
            client.post(
                "/api/settings/keys",
                json={"provider": "livecheck", "api_key": fake_key},
                headers=auth,
            ),
        )
        assert fake_key not in r.text and r.json()["last4"] == fake_key[-4:], "key leaked!"
        r = check("GET /api/settings/keys", 200, client.get("/api/settings/keys", headers=auth))
        assert fake_key not in r.text, "key leaked in list!"
        print("       keys list (masked):", r.json()["keys"])

        # No gateway configured in this environment: 503 is the honest,
        # expected live result — NOT a failure of the integration.
        check(
            "POST /api/chat/ (no gateway -> honest 503)",
            503,
            client.post(
                "/api/chat/",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=auth,
            ),
        )

        r = client.options(
            "/health",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
        )
        cors_ok = r.headers.get("access-control-allow-origin") == ORIGIN
        RESULTS.append(("CORS preflight from dev origin", 200, r.status_code, cors_ok))
        print(f"[{'OK ' if cors_ok else 'FAIL'}] {'CORS preflight from dev origin':<46} "
              f"allow-origin: {r.headers.get('access-control-allow-origin')}")

        # Cleanup: remove everything this script created.
        client.delete("/api/settings/keys/livecheck", headers=auth)
        client.delete(f"/api/files/{doc_id}", headers=auth)
        client.delete(f"/api/conversations/{conv_id}", headers=auth)
        client.delete(f"/api/memory/{mem_id}", headers=auth)
        print("cleanup: key, document, conversation and memory item deleted via API")

        failed = [x for x in RESULTS if not x[3]]
        print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} steps OK")
        return 1 if failed else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
