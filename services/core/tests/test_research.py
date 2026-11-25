"""Tests for the research module: credibility scoring, contradiction check,
exports, ResearchService (mocked gpt-researcher) and the HTTP endpoints.

No live LLM or search calls: gpt-researcher is replaced by a fake factory
and the gateway by a fake client. Run: python -m pytest tests/ -v
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.research import exports
from app.research.contradiction import check_contradictions, extract_claims
from app.research.credibility import score_sources
from app.research.service import (
    ResearchNotConfigured,
    ResearchService,
    researcher_env,
)
from app.routers import research as research_router

BENGALI_SAMPLE = "বাংলা গবেষণা প্রতিবেদন"

SAMPLE_REPORT = f"""# {BENGALI_SAMPLE}

The population of Dhaka was 23 million in 2023 according to official
statistics released by the national bureau this year.

Dhaka population reached only 10 million in 2023 according to the same
official statistics bureau report published recently.

এটি একটি পরীক্ষামূলক প্রতিবেদন যা বাংলা লেখা যাচাই করার জন্য তৈরি করা হয়েছে।
"""

SAMPLE_SOURCES = [
    {"url": "https://www.bbs.gov.bd/report", "title": "Dhaka population statistics 2023"},
    {"url": "https://arxiv.org/abs/2401.00001", "title": "Dhaka population statistics study"},
    {"url": "http://random-blog.example.com/post", "title": "My thoughts on cities"},
    {"url": "https://www.reddit.com/r/dhaka/comments/x", "title": "Dhaka population chat"},
]


# ---------------------------------------------------------------------------
# Credibility scoring
# ---------------------------------------------------------------------------

def test_credibility_is_deterministic():
    first = score_sources(SAMPLE_SOURCES)
    second = score_sources(list(reversed(SAMPLE_SOURCES)))
    by_url_first = {s["url"]: s["credibility_score"] for s in first}
    by_url_second = {s["url"]: s["credibility_score"] for s in second}
    assert by_url_first == by_url_second


def test_credibility_ordering_and_reasons():
    scored = score_sources(SAMPLE_SOURCES)
    scores = [s["credibility_score"] for s in scored]
    assert scores == sorted(scores, reverse=True)
    by_url = {s["url"]: s for s in scored}
    gov = by_url["https://www.bbs.gov.bd/report"]
    reddit = by_url["https://www.reddit.com/r/dhaka/comments/x"]
    blog = by_url["http://random-blog.example.com/post"]
    assert gov["credibility_score"] > reddit["credibility_score"]
    assert gov["credibility_score"] >= 75
    assert any("government" in r for r in gov["credibility_reasons"])
    assert any("social" in r for r in reddit["credibility_reasons"])
    # plain HTTP is penalised relative to an identical HTTPS source
    assert any("HTTP" in r for r in blog["credibility_reasons"])
    assert all(0 <= s["credibility_score"] <= 100 for s in scored)


def test_credibility_corroboration_bonus():
    scored = score_sources(SAMPLE_SOURCES)
    by_url = {s["url"]: s for s in scored}
    arxiv = by_url["https://arxiv.org/abs/2401.00001"]
    assert any("corroborated" in r for r in arxiv["credibility_reasons"])
    lone = score_sources([SAMPLE_SOURCES[2]])[0]
    assert not any("corroborated" in r for r in lone["credibility_reasons"])


# ---------------------------------------------------------------------------
# Contradiction check
# ---------------------------------------------------------------------------

class FakeGateway:
    def __init__(self, configured=True, content=None):
        self.configured = configured
        self._content = content

    async def chat_completion(self, role, messages, **params):
        return {"choices": [{"message": {"content": self._content}}]}


def test_extract_claims_prefers_figures():
    claims = extract_claims(SAMPLE_REPORT)
    assert len(claims) >= 2
    assert any("23 million" in c for c in claims)


def test_contradiction_skipped_when_gateway_unconfigured():
    result = asyncio.run(
        check_contradictions(SAMPLE_REPORT, SAMPLE_SOURCES, FakeGateway(configured=False))
    )
    assert result["status"] == "skipped"
    assert "not configured" in result["reason"]


def test_contradiction_flags_pair_from_fake_gateway():
    payload = json.dumps(
        {"contradictions": [{"claim_a": 0, "claim_b": 1, "explanation": "23M vs 10M"}]}
    )
    result = asyncio.run(
        check_contradictions(SAMPLE_REPORT, SAMPLE_SOURCES, FakeGateway(content=payload))
    )
    assert result["status"] == "ok"
    assert result["claims_checked"] >= 2
    assert len(result["contradictions"]) == 1
    pair = result["contradictions"][0]
    assert "23 million" in pair["claim_a"]
    assert "10 million" in pair["claim_b"]


def test_contradiction_bad_json_is_error_not_silence():
    result = asyncio.run(
        check_contradictions(SAMPLE_REPORT, SAMPLE_SOURCES, FakeGateway(content="not json"))
    )
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def test_docx_export_contains_text_and_bengali(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "report.docx"
    exports.export_docx(SAMPLE_REPORT, SAMPLE_SOURCES, out)
    assert out.is_file() and out.stat().st_size > 0
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert BENGALI_SAMPLE in text
    assert "পরীক্ষামূলক" in text
    assert "bbs.gov.bd" in text  # source list appended


def test_markdown_export_appends_sources(tmp_path):
    out = tmp_path / "report.md"
    exports.export_markdown(SAMPLE_REPORT, SAMPLE_SOURCES, out)
    text = out.read_text(encoding="utf-8")
    assert BENGALI_SAMPLE in text
    assert "## Sources" in text


def test_pdf_export_unavailable_without_font(tmp_path, monkeypatch):
    monkeypatch.setattr(exports, "bengali_font_available", lambda: False)
    with pytest.raises(exports.ExportUnavailable):
        exports.export_pdf(SAMPLE_REPORT, SAMPLE_SOURCES, tmp_path / "r.pdf")


def test_pdf_export_when_weasyprint_and_font_present(tmp_path):
    pytest.importorskip("weasyprint")
    if not exports.bengali_font_available():
        pytest.skip("no Bengali-capable font on this system")
    out = tmp_path / "report.pdf"
    exports.export_pdf(SAMPLE_REPORT, SAMPLE_SOURCES, out)
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 1000


# ---------------------------------------------------------------------------
# ResearchService with a fake gpt-researcher
# ---------------------------------------------------------------------------

class FakeResearcher:
    instances = []

    def __init__(self, query, report_type="research_report"):
        self.query = query
        self.report_type = report_type
        FakeResearcher.instances.append(self)

    async def conduct_research(self):
        return None

    async def write_report(self):
        return SAMPLE_REPORT

    def get_research_sources(self):
        return SAMPLE_SOURCES

    def get_costs(self):
        return 0.0123


def _configured_settings(**overrides):
    base = dict(
        gateway_base_url="http://gateway.test:3000",
        gateway_api_key="test-gateway-key",
        tavily_api_key="test-tavily-key",
        model_fast="fast-a,fast-b",
        model_smart="smart-a",
        model_strategic="strat-a",
    )
    base.update(overrides)
    return Settings(**base)


def test_researcher_env_mapping():
    env = researcher_env(_configured_settings())
    assert env["OPENAI_BASE_URL"] == "http://gateway.test:3000/v1"
    assert env["OPENAI_API_KEY"] == "test-gateway-key"
    assert env["FAST_LLM"] == "openai:fast-a"  # first of the chain only
    assert env["SMART_LLM"] == "openai:smart-a"
    assert env["STRATEGIC_LLM"] == "openai:strat-a"
    assert env["RETRIEVER"] == "tavily"
    assert env["TAVILY_API_KEY"] == "test-tavily-key"


def test_research_configured_logic():
    assert _configured_settings().research_configured is True
    # key-free retriever works without a Tavily key
    assert _configured_settings(tavily_api_key="", retriever="duckduckgo").research_configured
    # tavily without key and without gateway key -> not configured
    s = _configured_settings(tavily_api_key="", gateway_api_key="")
    assert s.research_configured is False
    assert any("GATEWAY_API_KEY" in m for m in s.research_missing())
    assert any("TAVILY_API_KEY" in m for m in s.research_missing())


def test_service_run_stores_artifacts(tmp_path):
    FakeResearcher.instances.clear()
    service = ResearchService(
        settings_obj=_configured_settings(),
        reports_dir=tmp_path,
        researcher_factory=FakeResearcher,
    )
    result = asyncio.run(service.run("Dhaka population", language="en"))
    run_dir = tmp_path / result["run_id"]
    assert (run_dir / "report.md").read_text(encoding="utf-8") == SAMPLE_REPORT
    stored_sources = json.loads((run_dir / "sources.json").read_text(encoding="utf-8"))
    assert stored_sources[0]["url"].startswith("https://www.bbs.gov.bd")
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["query"] == "Dhaka population"
    assert result["costs"] == 0.0123
    loaded = service.load_run(result["run_id"])
    assert loaded["report_markdown"] == SAMPLE_REPORT
    assert service.load_run("../etc") is None
    assert service.load_run("no-such-run") is None


def test_service_bengali_instruction_appended(tmp_path):
    FakeResearcher.instances.clear()
    service = ResearchService(
        settings_obj=_configured_settings(),
        reports_dir=tmp_path,
        researcher_factory=FakeResearcher,
    )
    result = asyncio.run(service.run("ঢাকার জনসংখ্যা", language="bn"))
    asked = FakeResearcher.instances[-1].query
    assert "Bengali" in asked and "বাংলা" in asked
    assert "instruction" in result["meta"]["language_handling"]


def test_service_unconfigured_raises(tmp_path):
    service = ResearchService(
        settings_obj=Settings(gateway_api_key="", tavily_api_key=""),
        reports_dir=tmp_path,
        researcher_factory=FakeResearcher,
    )
    with pytest.raises(ResearchNotConfigured):
        asyncio.run(service.run("anything"))


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

client = TestClient(app)


def test_research_post_503_when_unconfigured():
    r = client.post("/api/research/", json={"query": "Dhaka population"})
    assert r.status_code == 503
    assert "missing" in r.json()["detail"].lower()


def _override_service(tmp_path):
    service = ResearchService(
        settings_obj=_configured_settings(),
        reports_dir=tmp_path,
        researcher_factory=FakeResearcher,
    )
    payload = json.dumps({"contradictions": []})
    app.dependency_overrides[research_router.get_research_service] = lambda: service
    app.dependency_overrides[research_router.get_gateway_client] = lambda: FakeGateway(
        content=payload
    )
    return service


def test_research_post_and_export_flow(tmp_path):
    _override_service(tmp_path)
    try:
        r = client.post(
            "/api/research/", json={"query": "Dhaka population", "language": "en"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"]
        assert body["report_markdown"] == SAMPLE_REPORT
        assert body["sources"][0]["credibility_score"] >= body["sources"][-1][
            "credibility_score"
        ]
        assert body["contradiction"]["status"] == "ok"

        run_id = body["run_id"]
        r_md = client.get(f"/api/research/{run_id}/export", params={"format": "md"})
        assert r_md.status_code == 200
        assert BENGALI_SAMPLE in r_md.text

        r_docx = client.get(f"/api/research/{run_id}/export", params={"format": "docx"})
        assert r_docx.status_code == 200
        assert r_docx.content[:2] == b"PK"  # docx is a zip

        r_404 = client.get("/api/research/nope/export", params={"format": "md"})
        assert r_404.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_export_pdf_503_when_unavailable(tmp_path, monkeypatch):
    _override_service(tmp_path)
    monkeypatch.setattr(exports, "bengali_font_available", lambda: False)
    try:
        r = client.post("/api/research/", json={"query": "Dhaka population"})
        run_id = r.json()["run_id"]
        r_pdf = client.get(f"/api/research/{run_id}/export", params={"format": "pdf"})
        assert r_pdf.status_code == 503
        assert "font" in r_pdf.json()["detail"].lower() or "weasyprint" in r_pdf.json()[
            "detail"
        ].lower()
    finally:
        app.dependency_overrides.clear()
