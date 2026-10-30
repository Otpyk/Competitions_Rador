"""比赛信息库推荐（学院推荐名单 + 兴趣匹配 + 真实通知详情补充）。

数据来源：`data/competition_library.json`（华南师范大学人工智能学院推荐竞赛表，只含表内事实）。
缺失字段（截止/资格/官网/主办方）留空标“待查询”，由真实快照补充；查不到保持待查询，不编造。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent

# 兴趣 → 名称关键词（用于匹配；命中名称或标签即算命中）
INTEREST_KEYWORDS: dict[str, list[str]] = {
    "人工智能": ["人工智能", "算法精英", "AI"],
    "数学建模": ["数学建模", "数模"],
    "数学": ["数学竞赛", "数学"],
    "编程": ["程序设计", "ICPC", "CCPC", "蓝桥", "天梯", "百度之星", "软件杯", "软件设计", "软件开源", "工业软件"],
    "信息安全": ["信息安全", "网安", "网鼎杯", "强网杯", "X-NUCA", "对抗技术", "网络安全"],
    "机器人": ["机器人", "RoboCup", "RoboMaster", "RoboCon", "RAICOM", "睿抗", "智能汽车"],
    "电子硬件": ["电子设计", "嵌入式", "芯片", "物联网", "超级计算机", "ASC"],
    "计算机": ["计算机系统", "计算机设计", "计算机大赛", "大数据", "移动应用", "网络技术", "华为ICT"],
    "创新创业": ["创新大赛", "创业", "挑战杯", "职业规划", "iTeach", "数字化教育"],
    "科研": ["挑战杯", "学术科技"],
    "教育": ["师范", "教学技能"],
}

_LEVEL_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def load_library() -> dict[str, Any]:
    return json.loads((_ROOT / "data" / "competition_library.json").read_text(encoding="utf-8"))


def matched_interests(name: str, tags: list[str], interests: list[str]) -> list[str]:
    hits = []
    for interest in interests:
        kws = INTEREST_KEYWORDS.get(interest, [interest])
        if interest in tags or any(k in name for k in kws):
            hits.append(interest)
    return hits


def recommend_from_library(profile: dict) -> tuple[list[dict], int]:
    """按兴趣匹配学院推荐名单，返回排序后的命中列表与库总数。"""
    library = load_library()
    interests = list(profile.get("interests") or [])
    results: list[dict] = []
    for comp in library["competitions"]:
        hits = matched_interests(comp["name"], comp["tags"], interests)
        if hits:
            item = dict(comp)
            item["matched_interests"] = hits
            item["match_score"] = len(hits)
            results.append(item)
    results.sort(key=lambda c: (-c["match_score"], _LEVEL_ORDER.get(c["level"], 9), c["name"]))
    return results, library["count"]


# 真实快照 → 库内竞赛的详情补充（搜索层“查到就填”的最小闭环）
# 必须按来源精确映射到具体竞赛，避免张冠李戴。
_SOURCE_CONTEST: dict[str, tuple[list[str], str]] = {
    "real-mcm-hlju-2026-0831": (["全国大学生数学建模竞赛"], "全国大学生数学建模竞赛"),
    "real-mcm-nufe-2026-0707": (["全国大学生数学建模竞赛"], "全国大学生数学建模竞赛"),
    "real-icnc-dlut-2026-0827": (["中国国际大学生创新大赛"], "中国国际大学生创新大赛"),
    "real-icnc-scu-2026-0828": (["中国国际大学生创新大赛"], "中国国际大学生创新大赛"),
    "real-lanqiao-zqu-2026-1013": (["蓝桥杯"], "蓝桥杯全国软件和信息技术专业人才大赛"),
}


def enrich_with_real_snapshots(matches: list[dict]) -> list[dict]:
    """对库内命中的竞赛，用五份真实通知快照的抽取结果补充截止/资格/官网（标“待核验”）。"""
    from extractor import extract_competitions

    batch_path = _ROOT / "examples" / "research_result_real_batch.json"
    if not batch_path.exists():
        return matches
    raw = json.loads(batch_path.read_text(encoding="utf-8"))
    batch = {"task_id": raw["task_id"], "query": raw["query"], "sources": raw["sources"]}
    candidates = extract_competitions(batch)

    # 每个来源 -> 抽取的字段值
    detail_by_source: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        source_id = next(
            (e["source_id"] for c in cand["claims"] for e in c["evidence"] if e.get("source_id")), None
        )
        if not source_id:
            continue
        detail: dict[str, Any] = {}
        for claim in cand["claims"]:
            f, v = claim["field"], claim["value"]
            if f == "registration_deadline":
                detail["deadline"] = _regtime(v)
            elif f == "registration_start":
                detail["registration_start"] = _regtime(v)
            elif f == "official_url":
                detail["official_url"] = v
            elif f == "registration_url":
                detail["registration_url"] = v
            elif f == "organizer":
                detail["organizer"] = v
            elif f == "eligibility":
                detail["eligibility"] = _elig(v)
        detail_by_source[source_id] = detail

    for item in matches:
        for source_id, (kws, _contest) in _SOURCE_CONTEST.items():
            if any(k in item["name"] for k in kws):
                detail = detail_by_source.get(source_id) or {}
                for field in ("deadline", "registration_start", "official_url", "registration_url", "organizer", "eligibility"):
                    if detail.get(field):
                        item[field] = detail[field]
                item["detail_status"] = "已从真实通知抽取（待B核验）" if detail else "待查询"
                break
    return matches


def _regtime(value: Any) -> str | None:
    if not isinstance(value, dict):
        return str(value) if value else None
    date = value.get("date")
    if not date:
        return None
    text = str(date)
    if value.get("time"):
        text += " " + str(value["time"])
    return text


def enrich_with_web_search(matches: list[dict], settings: Any, max_enrich: int = 3) -> list[dict]:
    """对命中的库内竞赛，实时联网搜索最新通知并抓正文，补充截止/资格/官网（标“待B核验”）。

    只补充与库内竞赛名称匹配的抽取结果；搜到的是外校校赛/校内通知时不覆盖，
    由后续学校过滤与 B 核验把关。搜索失败或抓取失败时保持“待查询”，不编造。
    """
    from extractor import extract_competitions
    from web_search import build_snapshots

    for item in matches[:max_enrich]:
        query = f"{item['name']} 2026 报名 官方通知"
        try:
            snaps = build_snapshots(
                query,
                provider=settings.search_provider,
                key=settings.search_api_key,
                max_results=min(settings.search_max_results, 3),
            )
        except Exception:
            snaps = []
        if not snaps:
            continue
        batch = {"task_id": "web", "query": query, "sources": snaps}
        try:
            candidates = extract_competitions(batch)
        except Exception:
            candidates = []
        detail: dict[str, Any] = {}
        for c in candidates:
            cname = next((cl["value"] for cl in c["claims"] if cl["field"] == "name"), "") or ""
            if any(k in item["name"] or k in cname for k in _name_tokens(item["name"])):
                for cl in c["claims"]:
                    f, v = cl["field"], cl["value"]
                    if f == "registration_deadline":
                        detail["deadline"] = _regtime(v)
                    elif f == "registration_start":
                        detail["registration_start"] = _regtime(v)
                    elif f == "official_url":
                        detail["official_url"] = v
                    elif f == "registration_url":
                        detail["registration_url"] = v
                    elif f == "organizer":
                        detail["organizer"] = v
                    elif f == "eligibility":
                        detail["eligibility"] = _elig(v)
                break
        if detail:
            for field, value in detail.items():
                if value:
                    item[field] = value
            item["detail_status"] = "已联网查询（待B核验）"
            item["web_source"] = snaps[0]["url"]
        else:
            item.setdefault("detail_status", "待查询")
    return matches


def _name_tokens(name: str) -> list[str]:
    """从库内竞赛名提取用于匹配的关键词（避免外校校赛误匹配）。"""
    tokens = []
    for kw in ("数学建模", "创新大赛", "挑战杯", "蓝桥杯", "程序设计", "电子设计", "信息安全", "数学竞赛",
               "机器人大赛", "人工智能", "物联网", "计算机设计", "智能汽车", "软件杯", "百度之星",
               "天梯", "ICPC", "CCPC", "ASC", "RAICOM", "华为ICT", "嵌入式", "职业规划"):
        if kw in name:
            tokens.append(kw)
    return tokens or [name]


def _elig(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        if value.get("allowed_education_levels"):
            parts.append("学历：" + "、".join(map(str, value["allowed_education_levels"])))
        if value.get("allowed_grades"):
            parts.append("年级：" + "、".join(map(str, value["allowed_grades"])))
        team = value.get("team_size") or {}
        if team.get("min") is not None and team.get("max") is not None:
            parts.append("每队" + (str(team["min"]) if team["min"] == team["max"] else f"{team['min']}-{team['max']}") + "人")
        return "；".join(parts) or None
    return str(value)
