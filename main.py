"""FastAPI 后端入口与流程编排（成员 A 的 P0 交付物）。

负责：
- 提供用户搜索任务的 API 入口；
- 校验请求参数；
- 调用研究服务取得原始结果；
- 按统一接口把结果交给 C 的抽取模块、B 的核验/补充搜索决策流程、C 的排序模块；
- 组织补充搜索循环、异常、超时和最终响应；
- 返回前端可消费的数据或明确的任务状态。

边界：证据判断、抽取算法、推荐规则分别由 B/C 负责，A 只负责把模块接上。
B/C 模块尚未就位时，对应阶段会标记为 ``not_integrated``，链路仍可运行并返回
研究结果（基线可演示），而不是静默伪造"已核验/已推荐"。
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api_models import (
    ApiError,
    HealthResponse,
    LibraryRecommendRequest,
    LibraryRecommendResponse,
    PipelineStage,
    ResearchRequest,
    ResearchResult,
    SearchRequest,
    SearchResponse,
    SupplementarySearchRequest,
)
from config import get_settings
from research_service import ResearchService

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("competition_radar")

service = ResearchService(settings)

app = FastAPI(title=settings.app_name, version=settings.app_version)


# --------------------------------------------------------------------------- #
# 通用：统一错误响应
# --------------------------------------------------------------------------- #
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ApiError(code="internal_error", message="服务内部错误，请查看日志。", detail=str(exc)).model_dump(),
    )


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", engine=service.engine.name, version=settings.app_version)


# --------------------------------------------------------------------------- #
# 初始研究
# --------------------------------------------------------------------------- #
@app.post("/api/v1/research", response_model=ResearchResult)
async def research(req: ResearchRequest) -> ResearchResult:
    """发起一次初始研究任务，返回统一研究结果（报告 + 来源 + 状态）。"""
    logger.info("初始研究请求 query=%s", req.query)
    return await service.run(req)


# --------------------------------------------------------------------------- #
# 补充搜索（B 决策，A 执行）
# --------------------------------------------------------------------------- #
@app.post("/api/v1/research/supplementary", response_model=ResearchResult)
async def supplementary(req: SupplementarySearchRequest) -> ResearchResult:
    """执行 B 产生的补充搜索请求，返回与初始搜索兼容的结果结构。"""
    logger.info(
        "补充搜索 task_id=%s round=%s target_fields=%s",
        req.task_id,
        req.round,
        req.target_fields,
    )
    return await service.supplementary(req)


# --------------------------------------------------------------------------- #
# 端到端搜索链路
# --------------------------------------------------------------------------- #
@app.post("/api/v1/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """完整链路：研究 → 抽取 → 核验/补充搜索 → 排序。

    抽取/核验/排序模块由 C/B 实现；未集成时对应阶段标记为 not_integrated，
    链路仍返回研究结果。
    """
    logger.info("端到端搜索请求 query=%s", req.query)
    return await run_pipeline(req)


# --------------------------------------------------------------------------- #
# 比赛信息库推荐（学院推荐名单 + 兴趣匹配 + 真实快照详情补充）
# --------------------------------------------------------------------------- #
@app.post("/api/v1/library/recommend", response_model=LibraryRecommendResponse)
async def library_recommend(req: LibraryRecommendRequest) -> LibraryRecommendResponse:
    """按兴趣匹配学院推荐竞赛表；命中者用真实通知快照补充截止/资格/官网。"""
    import library_recommend

    matches, total = library_recommend.recommend_from_library({"interests": req.interests})
    # 配置了搜索 key 则实时联网补充最新详情；否则用离线真实快照补充
    if settings.search_api_key:
        matches = library_recommend.enrich_with_web_search(matches, settings)
    else:
        matches = library_recommend.enrich_with_real_snapshots(matches)
    return LibraryRecommendResponse(
        matches=matches,
        library_count=total,
        matched_count=len(matches),
        note="数据来自华南师范大学人工智能学院推荐竞赛表；截止/资格/官网查不到即标“待查询”，不编造；外校校赛已过滤。",
    )


# --------------------------------------------------------------------------- #
# 31 字段全链路（A→B→C→D 闭环）
# --------------------------------------------------------------------------- #
@app.post("/api/v1/search/full")
async def search_full(req: SearchRequest) -> dict:
    """全链路：真实快照 →（国产模型/规范候选）抽取 → B 核验 → C 消费 → 补全推荐。

    配置 DEEPSEEK_API_KEY 时用 DeepSeek 真实抽取；否则用 C 人工整理的规范候选（离线）。
    """
    import full_chain

    profile = req.profile or {}
    return full_chain.run_full_chain(
        profile,
        use_domestic_extraction=settings.use_real_extraction,
    )


def _load_module_attr(module_name: str, attr_name: str) -> Optional[Callable[..., Any]]:
    """Only an absent requested module is optional; broken imports stay visible."""
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None
        raise
    attr = getattr(module, attr_name, None)
    return attr if callable(attr) else None


def _error_detail(error: Exception) -> dict[str, Any]:
    detail: dict[str, Any] = {"error": str(error)}
    if hasattr(error, "issues"):
        detail["issues"] = [asdict(issue) for issue in error.issues]
    return detail


def _append_unique(existing: list, incoming: list, key: str, c: Any) -> list:
    """Reuse identical snapshots/records; never overwrite an existing identifier."""
    result = list(existing)
    by_id = {getattr(item, key): item for item in existing}
    for item in incoming:
        identifier = getattr(item, key)
        if identifier in by_id:
            if by_id[identifier] != item:
                raise c.ContractError(f"同一 {key} 的内容发生变化：{identifier}；请提供新的 ID 并保留历史")
        else:
            by_id[identifier] = item
            result.append(item)
    return result


def _integrate_research(result, extractor, adapter, sources, raw_candidates, c):
    batch = adapter(result.model_dump(mode="json"))
    next_sources = _append_unique(sources, batch.sources, "source_id", c)
    extracted = extractor(batch.model_dump(mode="json"))
    if not isinstance(extracted, list):
        raise c.ContractError("extract_competitions 必须返回 CandidateContest JSON 数组")
    incoming = [c.CandidateContest.model_validate(item) for item in extracted]
    next_raw = _append_unique(raw_candidates, incoming, "record_id", c)
    issues = c.validate_evidence(next_raw, next_sources)
    if issues:
        raise c.ContractError("候选证据引用校验失败", issues)
    return next_sources, next_raw, c.merge_candidates(next_raw)


def _verify_candidates(verifier, candidates, sources, c):
    raw = verifier(
        [item.model_dump(mode="json") for item in candidates],
        sources=[source.model_dump(mode="json") for source in sources],
    )
    if not isinstance(raw, list):
        raise c.ContractError("verify 必须返回 VerificationResult JSON 数组")
    results = [c.VerificationResult.model_validate(item) for item in raw]
    by_id = {item.record_id: item for item in results}
    if len(by_id) != len(results) or set(by_id) != {item.record_id for item in candidates}:
        raise c.ContractError("每个候选必须恰有一份核验结果，且不能包含其他赛事")
    for candidate in candidates:
        c.validate_verification(candidate, by_id[candidate.record_id])
    return results


async def run_pipeline(req: SearchRequest, *, as_of: datetime | None = None) -> SearchResponse:
    """Accumulate evidence, verify the latest candidates, then run C's strict rules.

    max_rounds is the maximum number of supplementary rounds. Initial research is
    round 1; supplementary rounds start at 2. A does not generate B's queries.
    """
    stages: list[PipelineStage] = []
    history: list[ResearchResult] = []
    sources, raw_candidates, candidates = [], [], []
    recommendations = None
    research_result = await service.run(ResearchRequest(query=req.query, profile=req.profile))
    task_id = research_result.task_id
    history.append(research_result)

    def finish(status="completed"):
        return SearchResponse(
            task_id=task_id, status=status, research=research_result,
            research_history=history,
            competitions=[item.model_dump(mode="json") for item in candidates],
            recommendations=recommendations, stages=stages,
        )

    def stop_after_extract(status, detail=None):
        stages.extend([
            PipelineStage(name="extract", status=status, detail=detail),
            PipelineStage(name="verify_and_supplement", status="not_integrated" if status == "not_integrated" else "blocked"),
            PipelineStage(name="rank", status="not_integrated" if status == "not_integrated" else "blocked"),
        ])
        return finish()

    stages.append(PipelineStage(name="research", status=research_result.status.value, detail={"engine": research_result.engine}))
    if research_result.status.value != "success":
        return finish("research_failed")

    try:
        extractor = _load_module_attr("extractor", "extract_competitions")
    except Exception as exc:
        return stop_after_extract("failed", _error_detail(exc))
    if extractor is None:
        return stop_after_extract("not_integrated")
    try:
        c = importlib.import_module("competition_radar")
        adapter = importlib.import_module("competition_radar.a_handoff").research_batch_from_a
    except ModuleNotFoundError as exc:
        status = "not_integrated" if exc.name == "competition_radar" else "failed"
        return stop_after_extract(status, _error_detail(exc))
    except Exception as exc:
        return stop_after_extract("failed", _error_detail(exc))

    try:
        sources, raw_candidates, candidates = _integrate_research(
            research_result, extractor, adapter, sources, raw_candidates, c,
        )
    except Exception as exc:
        status = "blocked" if isinstance(exc, c.ContractError) else "failed"
        return stop_after_extract(status, _error_detail(exc))
    stages.append(PipelineStage(name="extract", status="ran", detail={"count": len(candidates)}))

    try:
        verifier = _load_module_attr("evidence_verifier", "verify")
    except Exception as exc:
        stages.append(PipelineStage(name="verify_and_supplement", status="failed", detail=_error_detail(exc)))
        stages.append(PipelineStage(name="rank", status="blocked", detail="核验模块加载失败"))
        return finish()
    if verifier is None:
        stages.append(PipelineStage(name="verify_and_supplement", status="not_integrated"))
        stages.append(PipelineStage(name="rank", status="blocked", detail="缺少 B 的逐字段核验结果"))
        return finish()
    try:
        planner = _load_module_attr("query_planner", "plan_queries")
    except Exception as exc:
        stages.append(PipelineStage(name="plan_queries", status="failed", detail=_error_detail(exc)))
        stages.append(PipelineStage(name="verify_and_supplement", status="failed", detail="查询规划模块加载失败"))
        stages.append(PipelineStage(name="rank", status="blocked", detail="查询规划模块加载失败"))
        return finish()
    if planner is None:
        stages.append(PipelineStage(name="plan_queries", status="not_integrated", detail="只核验当前资料，不执行补搜"))

    max_rounds = req.max_rounds or settings.max_search_rounds
    completed_rounds = 0
    verification = None
    loop_status = "ran"
    loop_logs = [{"event": "supplementary_budget", "max_supplementary_rounds": max_rounds}]
    while True:
        try:
            # This also runs after the last allowed supplementary round.
            verification = _verify_candidates(verifier, candidates, sources, c)
            loop_logs.append({"event": "verified", "candidate_count": len(candidates), "source_count": len(sources)})
            if planner is None:
                break
            if completed_rounds >= max_rounds:
                loop_logs.append({"event": "supplementary_limit_reached", "completed_rounds": completed_rounds})
                break
            queries = planner(
                [item.model_dump(mode="json") for item in verification],
                competitions=[item.model_dump(mode="json") for item in candidates],
                sources=[source.model_dump(mode="json") for source in sources],
                research_history=[result.model_dump(mode="json") for result in history],
            )
            if not isinstance(queries, list):
                raise c.ContractError("plan_queries 必须返回查询请求数组")
            if not queries:
                loop_logs.append({"event": "no_more_queries"})
                break
            round_no = completed_rounds + 2
            requests = [SupplementarySearchRequest.model_validate({
                **query, "task_id": task_id, "round": round_no,
            }) for query in queries]
            for request in requests:
                supp = await service.supplementary(request)
                history.append(supp)
                loop_logs.append({"round": round_no, "event": "supplemented", "status": supp.status.value, "error": supp.error})
                if supp.task_id != task_id:
                    raise c.ContractError("补搜结果 task_id 与初始研究不一致")
                if supp.status.value != "success":
                    loop_status = "failed"
                    continue
                sources, raw_candidates, candidates = _integrate_research(
                    supp, extractor, adapter, sources, raw_candidates, c,
                )
                verification = None
            completed_rounds += 1
        except Exception as exc:
            verification = None
            loop_status = "blocked" if isinstance(exc, c.ContractError) else "failed"
            loop_logs.append({"event": "pipeline_failed", **_error_detail(exc)})
            break
    stages.append(PipelineStage(name="verify_and_supplement", status=loop_status, detail=loop_logs))

    if verification is None:
        stages.append(PipelineStage(name="rank", status="blocked", detail="最终候选尚未取得有效 B 裁决"))
        return finish()
    try:
        profile = c.UserProfile.model_validate(req.profile)
        evaluated_at = as_of if as_of is not None else datetime.now(UTC)
        recommendations = c.recommend(
            task_id, profile, sources, candidates, verification, evaluated_at,
        ).model_dump(mode="json")
        stages.append(PipelineStage(name="rank", status="ran"))
    except Exception as exc:
        stages.append(PipelineStage(name="rank", status="blocked", detail=_error_detail(exc)))
    return finish()


# 直接运行 `python main.py` 即启动后端
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
