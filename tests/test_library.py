"""比赛信息库推荐测试：库完整性、兴趣匹配、真实快照详情补充。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from library_recommend import enrich_with_real_snapshots, load_library, recommend_from_library

ROOT = Path(__file__).resolve().parents[1]


def test_library_has_expected_competitions():
    library = load_library()
    assert library["count"] == 71
    names = [c["name"] for c in library["competitions"]]
    assert "全国大学生数学建模竞赛（国赛）" in names
    assert "中国国际大学生创新大赛（仅高教主赛道）" in names
    assert "蓝桥杯全国软件和信息技术专业人才大赛（国赛）" in names
    # D类（校内）也已收录
    assert any("华南师范大学" in n for n in names)
    # 表内未提供的字段必须为 null（不编造）
    for c in library["competitions"]:
        assert c["deadline"] is None and c["eligibility"] is None and c["official_url"] is None


def test_interest_matching():
    matches, _ = recommend_from_library({"interests": ["数学建模"]})
    names = [m["name"] for m in matches]
    assert any("数学建模" in n for n in names)
    assert any("美国大学生数学建模" in n for n in names)
    assert all(m["match_score"] >= 1 for m in matches)


def test_matching_ordered_by_score_then_level():
    matches, _ = recommend_from_library({"interests": ["编程", "人工智能"]})
    scores = [m["match_score"] for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_enrich_fills_details_from_real_snapshots():
    matches, _ = recommend_from_library({"interests": ["数学建模", "创新创业"]})
    enriched = enrich_with_real_snapshots(matches)
    by_name = {m["name"]: m for m in enriched}
    # 蓝桥杯有真实快照：截止日期应从真实通知抽取（2026-11-16）
    lanqiao = next((m for m in enriched if "蓝桥杯" in m["name"]), None)
    if lanqiao:
        assert lanqiao["detail_status"] != "待查询"
        assert lanqiao.get("deadline") == "2026-11-16"
    # 库内其它竞赛保持待查询
    others = [m for m in enriched if "蓝桥杯" not in m["name"] and "数学建模" not in m["name"] and "创新大赛" not in m["name"]]
    for m in others:
        assert m["deadline"] is None


def test_no_fabrication_without_interest():
    matches, _ = recommend_from_library({"interests": []})
    assert matches == []
