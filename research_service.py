"""研究服务封装（成员 A 的 P0 交付物）。

职责：
- 接收统一格式的研究请求；
- 调用 GPT Researcher 或 mock 引擎完成搜索；
- 返回统一格式的报告与来源列表；
- 记录耗时、请求标识、状态和错误信息；
- 为补充搜索提供同一套调用入口；
- 外部服务异常时返回清晰、可处理的错误，不吞异常、不伪造成功结果。

边界：本层只返回研究资料与来源，不做资格判定、日期核验、推荐打分，
这些分别属于 C 和 B 的职责。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from api_models import (
    ResearchRequest,
    ResearchResult,
    ResearchStatus,
    Source,
    SupplementarySearchRequest,
)
from config import Settings

logger = logging.getLogger("competition_radar.research")


# --------------------------------------------------------------------------- #
# 引擎抽象
# --------------------------------------------------------------------------- #
class ResearchEngine(ABC):
    """研究引擎抽象。真实 GPT Researcher 与 mock 引擎实现同一接口。"""

    name: str = "base"

    @abstractmethod
    async def conduct(
        self, query: str, report_type: str = "research_report"
    ) -> tuple[str, list[Source]]:
        """执行一次研究，返回 (报告正文, 来源列表)。"""


def _coerce_source(item: Any) -> Optional[Source]:
    """把不同版本 GPT Researcher 返回的来源对象统一成 Source。"""
    if item is None:
        return None
    if isinstance(item, Source):
        return item
    if isinstance(item, dict):
        title = item.get("title") or item.get("name") or item.get("source")
        url = item.get("url") or item.get("link") or item.get("href") or ""
        snippet = item.get("snippet") or item.get("content") or item.get("summary")
        if not url and not title:
            return None
        snapshot = {
            key: item[key]
            for key in ("source_id", "content", "fetched_at", "published_date")
            if key in item
        }
        return Source(
            title=str(title) if title is not None else None,
            url=str(url), snippet=(str(snippet) if snippet else None),
            **snapshot,
        )
    # 纯字符串：当作 url 或标题
    text = str(item).strip()
    if text:
        return Source(title=text, url=text)
    return None


class GptResearcherEngine(ResearchEngine):
    """真实 GPT Researcher 引擎（可选安装）。"""

    name = "gpt_researcher"

    def __init__(self, report_type: str = "research_report") -> None:
        self._report_type = report_type
        try:
            import gpt_researcher  # noqa: F401
        except Exception as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "未安装 gpt-researcher。请先 `pip install -r requirements-researcher.txt`，"
                "或把 RESEARCHER_MODE 设为 mock。"
            ) from exc

    async def conduct(self, query: str, report_type: str = "research_report") -> tuple[str, list[Source]]:
        from gpt_researcher import GPTResearcher

        rt = report_type or self._report_type
        # 不同版本构造参数略有差异：优先关键字参数，失败再尝试位置参数。
        try:
            researcher = GPTResearcher(query=query, report_type=rt)
        except TypeError:
            researcher = GPTResearcher(query=query)  # type: ignore[call-arg]

        try:
            await researcher.conduct_research()
        except Exception:
            # 某些版本把 research 与 report 合并到 write_report，重试一次写报告路径。
            logger.debug("conduct_research 不可用，尝试直接 write_report", exc_info=True)
        report = await researcher.write_report()

        raw_sources = self._collect_sources(researcher)
        sources = [s for s in (_coerce_source(x) for x in raw_sources) if s]
        return (report or "", sources)

    @staticmethod
    def _collect_sources(researcher: Any) -> list[Any]:
        """兼容不同版本的来源访问方式。"""
        candidates: list[Any] = []
        for getter_name in ("get_research_sources", "get_source_urls", "get_sources"):
            getter = getattr(researcher, getter_name, None)
            if callable(getter):
                try:
                    value = getter()
                    if value:
                        candidates = list(value)
                        break
                except Exception:
                    continue
        if not candidates:
            for attr_name in ("sources", "source_urls", "research_sources"):
                value = getattr(researcher, attr_name, None)
                if value:
                    candidates = list(value)
                    break
        return candidates


# --------------------------------------------------------------------------- #
# mock 引擎（离线样例，可复现）
# --------------------------------------------------------------------------- #
# 以下均为演示用的固定样例数据，非真实赛事信息。
_MOCK_COMPETITIONS: list[dict[str, str]] = [
    {
        "keywords": ["人工智能", "ai", "机器学习", "算法"],
        "name": "全国大学生人工智能创新大赛（样例）",
        "organizer": "某高校人工智能学院（样例主办方）",
        "category": "人工智能",
        "eligibility": "在校本科生、研究生",
        "team_size": "1-4 人",
        "registration_deadline": "2026-11-30",
        "official_url": "https://example.org/ai-contest",
    },
    {
        "keywords": ["编程", "程序设计", "软件开发", "acm", "蓝桥"],
        "name": "全国大学生程序设计竞赛（样例）",
        "organizer": "某省计算机学会（样例主办方）",
        "category": "程序设计",
        "eligibility": "全日制在校生",
        "team_size": "1-3 人",
        "registration_deadline": "2026-12-15",
        "official_url": "https://example.org/programming-contest",
    },
    {
        "keywords": ["数学", "建模", "数模"],
        "name": "全国大学生数学建模竞赛（样例）",
        "organizer": "某数学建模组委会（样例主办方）",
        "category": "数学建模",
        "eligibility": "在校本科生、专科生",
        "team_size": "3 人",
        "registration_deadline": "2026-10-31",
        "official_url": "https://example.org/math-modeling",
    },
]

_DEFAULT_COMPETITION: dict[str, str] = {
    "keywords": [],
    "name": "大学生创新创业训练计划（样例）",
    "organizer": "某高校创新创业中心（样例主办方）",
    "category": "创新创业",
    "eligibility": "在校本科生",
    "team_size": "1-5 人",
    "registration_deadline": "2026-12-31",
    "official_url": "https://example.org/innovation-contest",
}

# 让 mock 结果具备确定性：对查询做哈希后固定选择，避免同一查询每次结果不同。
_SALT = "competition-radar-mock-v1"


def _pick_competition(query: str) -> dict[str, str]:
    lowered = query.lower()
    best: Optional[dict[str, str]] = None
    best_score = 0
    for comp in _MOCK_COMPETITIONS:
        score = sum(1 for kw in comp["keywords"] if kw in lowered)
        if score > best_score:
            best = comp
            best_score = score
    if best is None:
        best = _DEFAULT_COMPETITION
    # 若无关键词命中，用查询哈希在样例间选择，保证结果稳定可复现。
    if best_score == 0 and _MOCK_COMPETITIONS:
        digest = hashlib.md5((_SALT + query).encode("utf-8")).hexdigest()
        best = _MOCK_COMPETITIONS[int(digest, 16) % len(_MOCK_COMPETITIONS)]
    return best


def _build_mock_report(query: str) -> tuple[str, list[Source]]:
    comp = _pick_competition(query)
    report = (
        f"# 搜索结果（mock 样例，非真实赛事）\n\n"
        f"查询：{query}\n\n"
        f"- 赛事名称：{comp['name']}\n"
        f"- 主办方：{comp['organizer']}\n"
        f"- 类别：{comp['category']}\n"
        f"- 参赛资格：{comp['eligibility']}\n"
        f"- 团队规模：{comp['team_size']}\n"
        f"- 报名截止日期：{comp['registration_deadline']}\n"
        f"- 官方链接：{comp['official_url']}\n\n"
        f"> 说明：本结果为 mock 引擎生成的固定样例，仅用于离线联调与演示，"
        f"不代表真实赛事信息，请勿据此报名。"
    )
    sources = [
        Source(
            title=f"{comp['name']} - 官方页面（样例）",
            url=comp["official_url"],
            snippet="样例来源摘录：用于演示来源可追溯结构。",
        ),
        Source(
            title=f"{comp['name']} - 报名通知（样例）",
            url=f"{comp['official_url']}/notice",
            snippet="样例来源摘录：报名截止日期与参赛资格见官方通知。",
        ),
    ]
    return report, sources


class MockEngine(ResearchEngine):
    """离线 mock 引擎：不访问外部服务，返回可复现的样例结果。"""

    name = "mock"

    async def conduct(self, query: str, report_type: str = "research_report") -> tuple[str, list[Source]]:
        # 模拟一个极小延迟，使 elapsed_seconds 与日志结构更接近真实调用。
        await asyncio.sleep(0.01)
        return _build_mock_report(query)


class RealSnapshotEngine(ResearchEngine):
    """离线真实快照引擎：回放 examples/research_result_real_batch.json 的六键快照。

    不访问外部服务；来源为手动抓取的真实竞赛通知正文。用于离线联调与演示，
    让抽取/核验/补搜/推荐链路消费真实正文（引擎名明确标注 fixture，不冒充实时搜索）。
    """

    name = "fixture-real-snapshots"

    def __init__(self, fixture_path: str = "examples/research_result_real_batch.json") -> None:
        self._fixture_path = fixture_path

    def _load(self) -> tuple[str, list[Source]]:
        import json
        from pathlib import Path

        path = Path(self._fixture_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources = [Source.model_validate(item) for item in raw.get("sources", [])]
        return str(raw.get("report") or ""), sources

    async def conduct(self, query: str, report_type: str = "research_report") -> tuple[str, list[Source]]:
        await asyncio.sleep(0.01)
        return self._load()


class RealSearchEngine(ResearchEngine):
    """实时联网搜索引擎：Bocha/Tavily 搜索 + 抓正文，生成六键快照。

    需要 SEARCH_API_KEY（Bocha 等）；搜索失败或配额不足时返回空来源并在 report 说明，
    不伪造正文。fetch 抓取正文本身免 key。
    """

    name = "real-web-search"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def conduct(self, query: str, report_type: str = "research_report") -> tuple[str, list[Source]]:
        import json

        from web_search import build_snapshots

        try:
            snapshots = build_snapshots(
                query,
                provider=self._settings.search_provider,
                key=self._settings.search_api_key,
                max_results=self._settings.search_max_results,
            )
        except Exception as exc:  # 搜索失败/配额不足：如实说明，不伪造
            return f"联网搜索失败：{exc}", []
        report = f"联网搜索：{query}\n来源快照：{json.dumps([s['url'] for s in snapshots], ensure_ascii=False)}"
        sources = [Source.model_validate(s) for s in snapshots]
        return report, sources


# --------------------------------------------------------------------------- #
# 研究服务
# --------------------------------------------------------------------------- #
class ResearchService:
    """统一研究服务入口：初始搜索与补充搜索共用同一套执行逻辑。"""

    def __init__(self, settings: Settings, engine: Optional[ResearchEngine] = None) -> None:
        self.settings = settings
        self.engine = engine or self._build_engine(settings)

    def _build_engine(self, settings: Settings) -> ResearchEngine:
        mode = settings.researcher_mode.lower()
        if mode == "mock":
            return MockEngine()
        if mode == "fixture":
            return RealSnapshotEngine()
        if mode == "real":
            return RealSearchEngine(settings)
        if mode == "gpt_researcher":
            return GptResearcherEngine(settings.researcher_report_type)
        # auto：优先真实引擎，否则回退 mock（并记录原因）。
        if settings.has_llm_key:
            try:
                return GptResearcherEngine(settings.researcher_report_type)
            except RuntimeError as exc:
                logger.warning("auto 模式无法启用真实引擎：%s；回退到 mock。", exc)
        else:
            logger.warning("未配置 LLM 凭证，auto 模式回退到 mock 引擎。")
        return MockEngine()

    async def run(self, request: ResearchRequest) -> ResearchResult:
        """执行初始研究任务。"""
        task_id = uuid.uuid4().hex[:16]
        return await self._execute(
            task_id=task_id,
            query=request.query,
            round_no=1,
            report_type=request.report_type or self.settings.researcher_report_type,
        )

    async def supplementary(self, request: SupplementarySearchRequest) -> ResearchResult:
        """执行 B 产生的补充搜索请求（复用同一套执行逻辑）。"""
        return await self._execute(
            task_id=request.task_id,
            query=request.query,
            round_no=request.round,
            report_type=self.settings.researcher_report_type,
            context={
                "contest_name": request.contest_name,
                "target_fields": request.target_fields,
                "reason": request.reason,
            },
        )

    async def _execute(
        self,
        task_id: str,
        query: str,
        round_no: int,
        report_type: str,
        context: Optional[dict[str, Any]] = None,
    ) -> ResearchResult:
        start = time.perf_counter()
        logs: list[dict[str, Any]] = [
            {
                "event": "research_started",
                "engine": self.engine.name,
                "round": round_no,
                "report_type": report_type,
                **(context or {}),
            }
        ]
        try:
            report, sources = await asyncio.wait_for(
                self.engine.conduct(query, report_type),
                timeout=self.settings.researcher_timeout_seconds,
            )
            elapsed = time.perf_counter() - start
            logs.append(
                {
                    "event": "research_completed",
                    "elapsed_seconds": round(elapsed, 3),
                    "source_count": len(sources),
                }
            )
            return ResearchResult(
                task_id=task_id,
                status=ResearchStatus.success,
                query=query,
                report=report or "",
                sources=sources,
                elapsed_seconds=round(elapsed, 3),
                error=None,
                engine=self.engine.name,
                round=round_no,
                logs=logs,
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start
            logs.append({"event": "research_timed_out", "elapsed_seconds": round(elapsed, 3)})
            logger.error("研究任务超时 task_id=%s query=%s", task_id, query)
            return ResearchResult(
                task_id=task_id,
                status=ResearchStatus.timed_out,
                query=query,
                report="",
                sources=[],
                elapsed_seconds=round(elapsed, 3),
                error=f"研究任务超时（>{self.settings.researcher_timeout_seconds}s）",
                engine=self.engine.name,
                round=round_no,
                logs=logs,
            )
        except Exception as exc:  # noqa: BLE001 - 统一捕获并转换为结构化失败
            elapsed = time.perf_counter() - start
            logs.append({"event": "research_failed", "error": str(exc), "elapsed_seconds": round(elapsed, 3)})
            logger.exception("研究任务失败 task_id=%s query=%s", task_id, query)
            return ResearchResult(
                task_id=task_id,
                status=ResearchStatus.failed,
                query=query,
                report="",
                sources=[],
                elapsed_seconds=round(elapsed, 3),
                error=str(exc),
                engine=self.engine.name,
                round=round_no,
                logs=logs,
            )
