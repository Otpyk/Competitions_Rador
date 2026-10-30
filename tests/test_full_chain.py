"""31 字段全链路闭环测试：真实快照+规范候选 → B 核验 → C 消费 → 补全推荐。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")


def _profile():
    return {
        "education_level": "本科", "major": "数学", "grade": 2, "team_size": 3,
        "interests": ["数学建模"], "deadline_from": None, "deadline_to": None,
    }


def test_full_chain_runs_and_groups():
    from full_chain import run_full_chain

    result = run_full_chain(_profile(), use_domestic_extraction=False)
    assert result["candidate_count"] == 6
    assert result["stages"]["extract"] == "curated"
    assert result["stages"]["verify"] == "ran" and result["stages"]["consume"] == "ran"
    total = len(result["recommended"]) + len(result["pending"]) + len(result["excluded"])
    assert total == 6
    for item in result["pending"] + result["recommended"] + result["excluded"]:
        assert {"record_id", "name", "eligibility_status", "registration_status", "verification_status"} <= set(item)


def test_recommend_full_eligibility_parsing():
    from recommend_full import assess_eligibility

    # 明确约束 → 符合
    status, _ = assess_eligibility("竞赛为本科组，3人为一队进行报名，主要面向大二、大三、大四的在校本科生。", _profile())
    assert status == "eligible"
    # 学历不符 → 排除
    status, _ = assess_eligibility("面向研究生。", _profile())
    assert status == "ineligible"
    # 无结构化约束 → 未知
    status, _ = assess_eligibility("详情见官方章程。", _profile())
    assert status == "unknown"


def test_recommend_full_interest_match():
    from recommend_full import interest_match

    assert interest_match("全国大学生数学建模竞赛", None, ["数学建模"]) == ["数学建模"]
    assert interest_match("蓝桥杯全国软件和信息技术专业人才大赛", None, ["编程"]) == ["编程"]


def test_deepseek_extract_requires_key():
    from config import Settings
    from domestic_extract import extract_via_deepseek
    from full_chain import load_snapshots

    settings = Settings(_env_file=None, deepseek_api_key="")
    with pytest.raises(ValueError):
        extract_via_deepseek(load_snapshots(), settings)


def test_school_scope_filter_excludes_other_schools():
    from recommend_full import is_participable

    assert is_participable("global", "华南师范大学") == (True, "")
    assert is_participable("campus:华南师范大学", "华南师范大学") == (True, "")
    ok, reason = is_participable("campus:黑龙江大学", "华南师范大学")
    assert ok is False and "黑龙江大学" in reason
