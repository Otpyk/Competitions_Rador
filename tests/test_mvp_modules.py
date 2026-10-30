"""MVP 组装后的链路测试：真实快照 → 抽取 → B 适配核验 → 补搜规划 → 编排推荐。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api_models import SearchRequest
from competition_radar import CandidateContest, SourceDocument, VerificationResult
from competition_radar.validation import validate_evidence, validate_verification
from extractor import extract_competitions
from research_service import RealSnapshotEngine

ROOT = Path(__file__).resolve().parents[1]
BATCH = json.loads((ROOT / "examples" / "research_result_real_batch.json").read_text(encoding="utf-8"))
SOURCES_JSON = BATCH["sources"]


def _sources():
    return [SourceDocument.model_validate(s) for s in SOURCES_JSON]


def _extract():
    return extract_competitions({"task_id": BATCH["task_id"], "query": BATCH["query"], "sources": SOURCES_JSON})


def test_fixture_engine_returns_real_six_key_snapshots():
    engine = RealSnapshotEngine()
    report, sources = asyncio.run(engine.conduct("任意查询"))
    assert report
    assert len(sources) == 5
    for s in sources:
        assert s.source_id and s.url and s.content
        assert s.fetched_at is not None


def test_extractor_produces_candidates_with_verbatim_quotes():
    candidates = _extract()
    assert len(candidates) == 5
    parsed = [CandidateContest.model_validate(c) for c in candidates]
    issues = validate_evidence(parsed, _sources())
    assert not issues, [i.message for i in issues]


def test_extractor_never_invents_missing_year_dates():
    candidates = {c["record_id"]: c for c in _extract()}
    dlut = candidates["real-icnc-dlut-2026-0827-rec"]
    scu = candidates["real-icnc-scu-2026-0828-rec"]
    for cand in (dlut, scu):
        fields = {claim["field"] for claim in cand["claims"]}
        assert "registration_deadline" not in fields  # 原文无年份，不得猜测


def test_extractor_edition_recognized_for_all_real_notices():
    editions = {claim["field"]: claim["value"] for c in _extract() for claim in c["claims"]}
    assert editions.get("edition") is not None


def test_b_adapter_returns_one_verification_per_candidate():
    from evidence_verifier import verify

    parsed = [CandidateContest.model_validate(c) for c in _extract()]
    results = verify([c.model_dump(mode="json") for c in parsed],
                     sources=[s.model_dump(mode="json") for s in _sources()])
    assert len(results) == len(parsed)
    for candidate, raw in zip(parsed, results):
        verification = VerificationResult.model_validate(raw)
        validate_verification(candidate, verification)
        assert len(verification.fields) == 11


def test_b_adapter_official_url_verifiable_by_page_self_rule():
    from evidence_verifier import verify

    parsed = [CandidateContest.model_validate(c) for c in _extract()]
    results = verify([c.model_dump(mode="json") for c in parsed],
                     sources=[s.model_dump(mode="json") for s in _sources()])
    verified = [
        d for r in results for d in r["fields"]
        if d["field"] == "official_url" and d["status"] == "verified"
    ]
    assert verified, "至少应有通知页面自证规则核验通过的 official_url"


def test_query_planner_adapter_returns_a_request_shape():
    from evidence_verifier import verify
    from query_planner import plan_queries

    parsed = [CandidateContest.model_validate(c) for c in _extract()]
    results = verify([c.model_dump(mode="json") for c in parsed],
                     sources=[s.model_dump(mode="json") for s in _sources()])
    requests = plan_queries(
        results,
        competitions=[c.model_dump(mode="json") for c in parsed],
        sources=[s.model_dump(mode="json") for s in _sources()],
        research_history=[],
    )
    assert isinstance(requests, list)
    assert requests, "真实通知缺字段时应有补搜请求"
    for r in requests:
        assert {"action", "contest_name", "target_fields", "query", "reason"} <= set(r)
        assert r["action"] == "search"


def test_full_pipeline_end_to_end(monkeypatch):
    import config
    import main

    monkeypatch.setenv("RESEARCHER_MODE", "fixture")
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None, researcher_mode="fixture"))
    from research_service import ResearchService

    main.service = ResearchService(config.Settings(_env_file=None, researcher_mode="fixture"))
    profile = {
        "education_level": "本科", "major": "数学", "grade": 2, "team_size": 3,
        "interests": ["数学建模"], "deadline_from": None, "deadline_to": None,
    }
    resp = asyncio.run(main.run_pipeline(
        SearchRequest(query="全国大学生学科竞赛 2026", profile=profile, max_rounds=1)))
    data = resp.model_dump(mode="json")
    assert data["status"] == "completed"
    stages = {s["name"]: s["status"] for s in data["stages"]}
    assert stages["research"] == "success" and stages["extract"] == "ran"
    assert stages["verify_and_supplement"] == "ran" and stages["rank"] == "ran"
    assert data["recommendations"] is not None
    assert len(data["recommendations"]["recommended"] + data["recommendations"]["pending"] + data["recommendations"]["excluded"]) == 5
    assert len(data["research_history"]) >= 2  # 初始研究 + 至少一次补搜
