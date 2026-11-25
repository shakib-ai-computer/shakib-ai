"""Tests for the Critical Thinking Council: CouncilService with a fake
gateway, member retry/error behaviour, role fallback, Bengali prompting,
the stored-run flow (run created via the research module's fake
gpt-researcher pattern) and the HTTP endpoints.

No live LLM calls: the gateway is a fake client returning canned strict
JSON per member. Run: python -m pytest tests/ -v
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.council import MEMBER_ORDER, CouncilNotConfigured, CouncilService
from app.gateway import GatewayError
from app.main import app
from app.research.service import ResearchService
from app.routers import council as council_router

REPORT = """# Dhaka population report

The population of Dhaka was 23 million in 2023 according to official
statistics, and the city will keep growing rapidly over the next decade
because rural migration continues at a high rate every single year.
"""

SOURCES = [
    {"url": "https://www.bbs.gov.bd/report", "title": "Dhaka population statistics 2023"},
    {"url": "https://arxiv.org/abs/2401.00001", "title": "Dhaka population statistics study"},
]

MEMBER_PAYLOADS = {
    "devils_advocate": {
        "member": "devils_advocate",
        "summary": "The growth conclusion rests on one official figure.",
        "points": [
            {
                "point": "A single census figure cannot support a decade-long trend claim.",
                "target_claim": "the city will keep growing rapidly over the next decade",
                "strength": "high",
            }
        ],
    },
    "autopsy": {
        "member": "autopsy",
        "summary": "The leap from one data point to a trend is unsupported.",
        "findings": [
            {
                "issue": "Trend inferred from a single year's population figure.",
                "severity": "high",
                "evidence_gap": "No time series or migration data is cited.",
            }
        ],
    },
    "red_team": {
        "member": "red_team",
        "summary": "Official figures could be politically massaged.",
        "scenarios": [
            {
                "scenario": "The statistics bureau inflates city population to attract funding.",
                "plausibility": "medium",
                "impact": "Planning decisions would be based on phantom residents.",
            }
        ],
    },
    "expose": {
        "member": "expose",
        "summary": "Only official and academic voices are heard.",
        "gaps": [
            {
                "gap": "No informal-settlement or commuter perspectives are examined.",
                "why_it_matters": "A large share of Dhaka's de-facto population is invisible.",
            }
        ],
    },
}


class FakeCouncilGateway:
    """Fake gateway: returns the canned payload for whichever council
    member the system prompt names. ``bad_member`` always gets invalid
    JSON; roles in ``fail_roles`` raise GatewayError."""

    def __init__(self, configured=True, bad_member=None, fail_roles=()):
        self.configured = configured
        self.bad_member = bad_member
        self.fail_roles = set(fail_roles)
        self.calls = []  # list of (role, member)
        self.system_prompts = {}  # member -> system prompt seen

    async def chat_completion(self, role, messages, **params):
        if role in self.fail_roles:
            raise GatewayError(f"role {role!r} unavailable (fake)")
        system = messages[0]["content"]
        member = next((m for m in MEMBER_ORDER if f'"member": "{m}"' in system), None)
        assert member is not None, f"no member named in system prompt: {system[:80]}"
        self.calls.append((role, member))
        self.system_prompts[member] = system
        if member == self.bad_member:
            content = "this is not json"
        else:
            content = json.dumps(MEMBER_PAYLOADS[member])
        return {"choices": [{"message": {"content": content}}]}


def _service(tmp_path, gateway):
    return CouncilService(gateway=gateway, reports_dir=tmp_path)


# ---------------------------------------------------------------------------
# Service-level behaviour
# ---------------------------------------------------------------------------

def test_all_four_members_present_with_parsed_content(tmp_path):
    gateway = FakeCouncilGateway()
    result = asyncio.run(_service(tmp_path, gateway).analyze(REPORT, SOURCES))
    assert set(result["members"]) == set(MEMBER_ORDER)
    for member, payload in MEMBER_PAYLOADS.items():
        section = result["members"][member]
        assert section["status"] == "ok"
        assert section["member"] == member
        assert section["summary"] == payload["summary"]
    da = result["members"]["devils_advocate"]
    assert da["points"][0]["strength"] == "high"
    assert da["points"][0]["target_claim"].startswith("the city will keep growing")
    assert result["members"]["autopsy"]["findings"][0]["severity"] == "high"
    assert result["members"]["red_team"]["scenarios"][0]["plausibility"] == "medium"
    assert result["members"]["expose"]["gaps"][0]["gap"].startswith("No informal")
    assert result["generated_by_role"] == "strategic"
    assert result["language"] == "en"
    assert "run_id" not in result


def test_member_bad_json_twice_errors_others_fine(tmp_path):
    gateway = FakeCouncilGateway(bad_member="red_team")
    result = asyncio.run(_service(tmp_path, gateway).analyze(REPORT, SOURCES))
    red_team = result["members"]["red_team"]
    assert red_team["status"] == "error"
    assert "JSON" in red_team["reason"]
    for member in ("devils_advocate", "autopsy", "expose"):
        assert result["members"][member]["status"] == "ok"
    # the failing member was called exactly twice: initial try + one retry
    red_team_calls = [c for c in gateway.calls if c[1] == "red_team"]
    assert len(red_team_calls) == 2
    others = [c for c in gateway.calls if c[1] != "red_team"]
    assert len(others) == 3


def test_role_fallback_strategic_to_smart(tmp_path):
    gateway = FakeCouncilGateway(fail_roles={"strategic"})
    result = asyncio.run(_service(tmp_path, gateway).analyze(REPORT, SOURCES))
    assert all(s["status"] == "ok" for s in result["members"].values())
    assert result["generated_by_role"] == "smart"


def test_bengali_language_instructs_members(tmp_path):
    gateway = FakeCouncilGateway()
    result = asyncio.run(
        _service(tmp_path, gateway).analyze(REPORT, SOURCES, language="bn")
    )
    assert result["language"] == "bn"
    assert all("বাংলা" in p for p in gateway.system_prompts.values())


def test_service_unconfigured_raises(tmp_path):
    service = _service(tmp_path, FakeCouncilGateway(configured=False))
    with pytest.raises(CouncilNotConfigured):
        asyncio.run(service.analyze(REPORT, SOURCES))


# ---------------------------------------------------------------------------
# Stored-run flow (research run created with the research test pattern)
# ---------------------------------------------------------------------------

class FakeResearcher:
    def __init__(self, query, report_type="research_report"):
        self.query = query
        self.report_type = report_type

    async def conduct_research(self):
        return None

    async def write_report(self):
        return REPORT

    def get_research_sources(self):
        return SOURCES

    def get_costs(self):
        return 0.0


def _make_stored_run(tmp_path) -> str:
    settings = Settings(
        gateway_base_url="http://gateway.test:3000",
        gateway_api_key="test-gateway-key",
        tavily_api_key="test-tavily-key",
        model_fast="fast-a",
        model_smart="smart-a",
        model_strategic="strat-a",
    )
    research = ResearchService(
        settings_obj=settings,
        reports_dir=tmp_path,
        researcher_factory=FakeResearcher,
    )
    result = asyncio.run(research.run("Dhaka population", language="en"))
    return result["run_id"]


client = TestClient(app)


def _override(tmp_path, gateway):
    service = _service(tmp_path, gateway)
    app.dependency_overrides[council_router.get_council_service] = lambda: service
    return service


def test_run_id_path_loads_stored_run_and_stores_council(tmp_path):
    run_id = _make_stored_run(tmp_path)
    _override(tmp_path, FakeCouncilGateway())
    try:
        r = client.post("/api/council/", json={"run_id": run_id})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] == run_id
        assert set(body["members"]) == set(MEMBER_ORDER)
        assert all(s["status"] == "ok" for s in body["members"].values())
        stored = json.loads(
            (tmp_path / run_id / "council.json").read_text(encoding="utf-8")
        )
        assert stored["run_id"] == run_id
        assert stored["members"]["expose"]["gaps"][0]["gap"].startswith("No informal")
    finally:
        app.dependency_overrides.clear()


def test_report_file_unchanged_after_council_run(tmp_path):
    run_id = _make_stored_run(tmp_path)
    report_path = tmp_path / run_id / "report.md"
    before = report_path.read_bytes()
    _override(tmp_path, FakeCouncilGateway())
    try:
        r = client.post("/api/council/", json={"run_id": run_id})
        assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.clear()
    assert report_path.read_bytes() == before


def test_unknown_run_id_404(tmp_path):
    _override(tmp_path, FakeCouncilGateway())
    try:
        r = client.post("/api/council/", json={"run_id": "no-such-run"})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_unconfigured_gateway_503(tmp_path):
    _override(tmp_path, FakeCouncilGateway(configured=False))
    try:
        r = client.post(
            "/api/council/", json={"report_markdown": REPORT, "sources": SOURCES}
        )
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_inline_report_flow(tmp_path):
    _override(tmp_path, FakeCouncilGateway())
    try:
        r = client.post(
            "/api/council/",
            json={"report_markdown": REPORT, "sources": SOURCES, "language": "bn"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "run_id" not in body
        assert body["language"] == "bn"
        assert body["members"]["autopsy"]["status"] == "ok"
    finally:
        app.dependency_overrides.clear()
