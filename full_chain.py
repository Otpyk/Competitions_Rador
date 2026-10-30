"""全链路闭环：真实快照 + 规范候选 → B 核验 → C 消费 → 补全推荐。

离线默认用 C 人工整理的 6 条规范候选（真实 31 字段 + 136 条逐字证据）；
配置 DEEPSEEK_API_KEY 后切换为 DeepSeek 真实抽取（见 domestic_extract.py）。
裁决全部来自 B 的冻结策略与正式审批；资格/排序/归并由 recommend_full 补全。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from b_app.service import verify_contests
from competition_radar.b_handoff import B_REQUIRED_FIELDS
from competition_radar import BContest, SourceDocument, consume_b_return
from recommend_full import recommend_full

_ROOT = Path(__file__).resolve().parent


def load_snapshots() -> list[SourceDocument]:
    raw = json.loads((_ROOT / "examples" / "research_result_real_batch.json").read_text(encoding="utf-8"))
    return [SourceDocument.model_validate(s) for s in raw["sources"]]


def load_candidates() -> list[BContest]:
    raw = json.loads((_ROOT / "data" / "b_canonical_batch" / "c_to_b_contests.json").read_text(encoding="utf-8"))
    return [BContest.model_validate(c) for c in raw]


def run_full_chain(profile: dict, *, use_domestic_extraction: bool = False) -> dict[str, Any]:
    """执行 31 字段全链路，返回 {recommended, pending, excluded, stages, note}。

    use_domestic_extraction=True 且配置了 DeepSeek + 搜索 key 时，先联网搜索命中竞赛、
    抓正文、DeepSeek 抽取；失败则回退规范候选（离线）。"""
    from config import get_settings

    settings = get_settings()
    stages: dict[str, str] = {}
    sources = load_snapshots()
    candidates = None

    if use_domestic_extraction and settings.has_domestic_key and settings.search_api_key:
        import domestic_extract

        try:
            candidates, sources = domestic_extract.search_and_extract(profile, settings)
            stages["extract"] = "web+deepseek"
        except Exception as exc:  # 模型日期推断等质量问题触发 C 严格校验 → 回退规范候选
            candidates = None
            stages["extract"] = "curated"
            stages["extract_note"] = f"联网抽取失败，回退规范候选：{str(exc)[:120]}"
    if candidates is None:
        candidates = load_candidates()
        stages.setdefault("extract", "curated")

    sources_json = [s.model_dump(mode="json") for s in sources]
    contests_json = [c.model_dump(mode="json") for c in candidates]
    returns = verify_contests(contests_json, sources=sources_json)
    stages["verify"] = "ran"

    consumed = [
        consume_b_return(ret, cand, sources, required_fields=B_REQUIRED_FIELDS)
        for ret, cand in zip(returns, candidates)
    ]
    stages["consume"] = "ran"

    as_of = datetime.now(timezone.utc)
    result = recommend_full(consumed, profile, as_of, user_school=settings.user_school)
    result["stages"] = stages
    result["candidate_count"] = len(candidates)
    result["verified_source_count"] = len(sources)
    result["user_school"] = settings.user_school
    return result
