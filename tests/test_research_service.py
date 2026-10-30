"""研究服务封装的最小接口测试（离线，不访问外部服务）。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime

from api_models import ResearchRequest, SupplementarySearchRequest
from config import Settings
from research_service import MockEngine, ResearchService, _coerce_source


def make_service(timeout: float = 5.0) -> ResearchService:
    settings = Settings(researcher_mode="mock", researcher_timeout_seconds=timeout)
    return ResearchService(settings, MockEngine())


def test_mock_run_returns_success() -> None:
    svc = make_service()
    result = asyncio.run(svc.run(ResearchRequest(query="大学生 人工智能 竞赛")))
    assert result.status.value == "success"
    assert result.report
    assert len(result.sources) > 0
    assert result.engine == "mock"
    assert result.error is None
    assert result.task_id
    assert result.logs


def test_mock_run_is_deterministic() -> None:
    svc = make_service()
    r1 = asyncio.run(svc.run(ResearchRequest(query="编程 竞赛")))
    r2 = asyncio.run(svc.run(ResearchRequest(query="编程 竞赛")))
    assert r1.report == r2.report


def test_supplementary_search() -> None:
    svc = make_service()
    req = SupplementarySearchRequest(
        task_id="task-123",
        contest_name="某项竞赛",
        target_fields=["registration_deadline"],
        query="某项竞赛 官方 报名截止时间",
        reason="报名截止日期缺失",
        round=2,
    )
    result = asyncio.run(svc.supplementary(req))
    assert result.status.value == "success"
    assert result.round == 2
    assert result.task_id == "task-123"


def test_timeout_returns_timed_out() -> None:
    class SlowEngine(MockEngine):
        async def conduct(self, query: str, report_type: str = "research_report"):
            await asyncio.sleep(1)
            return "x", []

    settings = Settings(researcher_mode="mock", researcher_timeout_seconds=0.05)
    svc = ResearchService(settings, SlowEngine())
    result = asyncio.run(svc.run(ResearchRequest(query="q")))
    assert result.status.value == "timed_out"
    assert result.error


def test_failure_returns_failed_not_fake_success() -> None:
    class BrokenEngine(MockEngine):
        async def conduct(self, query: str, report_type: str = "research_report"):
            raise RuntimeError("boom")

    settings = Settings(researcher_mode="mock")
    svc = ResearchService(settings, BrokenEngine())
    result = asyncio.run(svc.run(ResearchRequest(query="q")))
    assert result.status.value == "failed"
    assert "boom" in (result.error or "")
    assert result.sources == []


def test_coerce_source_preserves_explicit_snapshot_fields() -> None:
    raw = {
        "title": "合成快照标题",
        "url": "https://example.invalid/notice",
        "snippet": "检索摘要与原文分开保留",
        "source_id": "synthetic-snapshot-20261022-1",
        "content": "  合成网页原文\n保留换行、空白及引号‘原文’。  ",
        "fetched_at": "2026-10-22T10:11:12+08:00",
        "published_date": "2026-10-20",
    }
    before = deepcopy(raw)
    source = _coerce_source(raw)
    assert source is not None
    assert source.title == raw["title"]
    assert source.url == raw["url"]
    assert source.snippet == raw["snippet"]
    assert source.source_id == raw["source_id"]
    assert source.content == raw["content"]
    assert source.fetched_at == datetime.fromisoformat(raw["fetched_at"])
    assert source.published_date == date.fromisoformat(raw["published_date"])
    assert raw == before


def test_coerce_legacy_source_does_not_invent_snapshot_data() -> None:
    source = _coerce_source({
        "title": "旧来源标题",
        "url": "https://example.invalid/legacy",
        "snippet": "只有检索摘要，未提供网页正文",
    })
    assert source is not None
    assert source.snippet == "只有检索摘要，未提供网页正文"
    assert source.source_id is None
    assert source.content is None
    assert source.fetched_at is None
    assert source.published_date is None


def test_coerce_summary_remains_snippet_and_cannot_become_source_body() -> None:
    summary = "模型或检索生成的摘要不等于网页原文"
    source = _coerce_source({
        "title": "只有摘要的来源",
        "url": "https://example.invalid/summary",
        "summary": summary,
    })
    assert source is not None
    assert source.snippet == summary
    assert source.content is None
    assert source.source_id is None
    assert source.fetched_at is None
