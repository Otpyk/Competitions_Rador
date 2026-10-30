"""国产模型真实抽取（A 补 C-1 的联网抽取闭环；需 DEEPSEEK_API_KEY，key 缺失会明确报错）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from competition_radar.b_handoff import BContest
from competition_radar.deepseek import DeepSeekCompletion
from competition_radar.extraction import ExtractionTarget, extract_b_contests
from competition_radar.schemas import ResearchBatch, SourceDocument

_ROOT = Path(__file__).resolve().parent


def extract_via_deepseek(sources: list[SourceDocument], settings: Any) -> list[BContest]:
    """对每份快照按 b_target_contexts 身份构造抽取目标，调用 DeepSeek 做 31 字段抽取。"""
    contexts = json.loads((_ROOT / "data" / "b_target_contexts.json").read_text(encoding="utf-8"))
    batch = ResearchBatch(task_id="full-chain", query="全国大学生学科竞赛 2026", sources=sources)
    targets = []
    for source in sources:
        rec_id = f"{source.source_id}-rec"
        ctx = contexts.get(rec_id, {})
        name = ctx.get("expected_name") or (source.title or source.source_id)
        targets.append(ExtractionTarget(
            id=rec_id,
            name=name,
            edition=ctx.get("expected_edition"),
            scope=ctx.get("scope", "global"),
            field_scopes=ctx.get("field_scopes", {}),
            source_ids=[source.source_id],
            context={k: v for k, v in ctx.items() if isinstance(v, str)},
        ))
    completion = DeepSeekCompletion(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
    )
    # 注：DeepSeekCompletion 端点硬编码 api.deepseek.com；换厂商见 .env.example（改 deepseek.py 的 URL）。
    result = extract_b_contests(batch, targets, completion)
    return result.contests


def search_and_extract(profile: dict, settings: Any) -> tuple[list[BContest], list[SourceDocument]]:
    """联网搜索命中竞赛 → 抓快照 → DeepSeek 31 字段抽取；失败抛异常由调用方回退。"""
    from library_recommend import recommend_from_library
    from web_search import build_snapshots

    matched, _ = recommend_from_library(profile)
    if not matched:
        raise RuntimeError("兴趣未命中任何库内竞赛，无法发起联网抽取")
    snapshots = []
    for m in matched[:3]:
        snaps = build_snapshots(
            f"{m['name']} 2026 报名 官方通知",
            provider=settings.search_provider,
            key=settings.search_api_key,
            max_results=2,
        )
        snapshots.extend(snaps)
    if not snapshots:
        raise RuntimeError("联网搜索未取得任何正文快照")
    sources, seen = [], set()
    for s in snapshots:
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        sources.append(SourceDocument.model_validate(s))
    targets = [
        ExtractionTarget(
            id=f"web-{m['id']}",
            name=m["name"],
            edition="2026",
            scope="global",
            field_scopes={},
            source_ids=[s.source_id for s in sources],
            context={},
        )
        for m in matched[:3]
    ]
    completion = DeepSeekCompletion(api_key=settings.deepseek_api_key, model=settings.deepseek_model)
    batch = ResearchBatch(task_id="web", query="、".join(m["name"] for m in matched[:3]), sources=sources)
    result = extract_b_contests(batch, targets, completion)
    return result.contests, sources
