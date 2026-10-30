"""Synthetic v2 student-field replay. No network, real contest or measured gain."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from b_app.adaptive_search import run_adaptive_search
from b_app.b_contracts import SearchBatch, SearchBudget
from b_app.b_io import review_bundle_from_dict
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import FIELD_SPECS, MANDATORY_FIELDS, build_policy
from b_app.query_planner import plan_queries
from b_app.source_review import review_competition


VALUES = {
    "competition_name": "虚构学生创意赛",
    "competition_edition": "2026",
    "track": "软件创意组",
    "organizer": "虚构竞赛组委会",
    "official_url": "https://contest.example.invalid/2026/notice",
    "eligibility": "全国高校在读本科生；不接受研究生参赛。",
    "participation_mode": "团队参赛。",
    "team_rules": "每队2至4人，可跨校，须指定队长1名，无需指导教师。",
    "registration_start": "2026-10-20",
    "registration_deadline": "2026-11-10",
    "campus_deadline": None,
    "task_description": "制作一款帮助学生规划学习的应用。",
    "deliverables": "提交源代码、说明文档和3分钟演示视频。",
    "submission_deadline": "2026-11-20",
    "attendance_mode": "报名、初赛、决赛和答辩均在线上完成。",
    "venue": None,
    "registration_fee": "每队0元人民币。",
    "mandatory_fees": "赛事各阶段均不收取其他必缴费用。",
    "registration_method": "队长在线注册并填写全队信息。",
    "registration_url": "https://contest.example.invalid/2026/register",
    "registration_materials": "全体队员学籍证明和队长联系方式。",
    "institutional_requirements": None,
}
NA = {
    "campus_deadline": "本赛事由个人直接报名，无校内报名环节。",
    "venue": "本赛事全程线上，无需到场。",
    "institutional_requirements": "本赛事无需学校推荐、审核、签字或盖章，无校内名额限制，无需指导教师确认。",
}


def make_bundle():
    """A complete, intentionally simple fictional source for literal-rule tests."""
    url = VALUES["official_url"]
    fields, paragraphs = {}, ["离线虚构示例，不对应真实赛事。"]
    for name in MANDATORY_FIELDS:
        statement = NA.get(name, VALUES[name])
        quote = f"{FIELD_SPECS[name].label}：{statement}"
        paragraphs.append(quote)
        fields[name] = {"value": VALUES[name], "evidence": [{
            "id": f"fixture-{name}", "value": statement, "url": url,
            "quote": quote, "edition": "2026", "scope": "global",
            "value_kind": "not_applicable" if name in NA else "value",
        }]}
    return {
        "competition": {"id": "fictional-student-v2", "name": VALUES["competition_name"],
                        "edition": "2026", "scope": "global", "field_scopes": {}, "fields": fields},
        "approved_sources": [{"competition_id": "fictional-student-v2", "edition": "2026",
                              "scope": "global", "url": url, "source_type": "official",
                              "approved_by": "fixture:B-synthetic-approval-not-real"}],
        "snapshots": [{"url": url, "text": "\n\n".join(paragraphs),
                       "retrieved_at": "2026-10-22T12:00:00+08:00"}],
    }


def reviewed_bundle(bundle=None):
    raw, approvals, snapshots = review_bundle_from_dict(bundle or make_bundle())
    return review_competition(raw, approved_sources=approvals, snapshots=snapshots)[0]


def run_examples():
    complete = reviewed_bundle()
    policy = build_policy()
    full = verify_competition(complete, policy)
    missing = deepcopy(complete)
    missing.evidence = [item for item in missing.evidence if item.field != "registration_fee"]
    missing.fields["registration_fee"] = None
    fee = next(item for item in complete.evidence if item.field == "registration_fee")
    recovered = run_adaptive_search(missing, lambda query, budget: SearchBatch(evidence=[fee], cost=0), policy=policy)
    constrained = verify_competition(complete, build_policy(hard_constraints=["online_only"]))
    unknown_budget = run_adaptive_search(complete, lambda query, budget: SearchBatch(cost=0),
                                        policy=build_policy(hard_constraints=["total_budget_limit"]),
                                        budget=SearchBudget(max_calls=1))
    optional_conflict = deepcopy(complete)
    for number, value in enumerate(("一等奖3队。", "一等奖5队。")):
        optional_conflict.evidence.append(replace(fee, id=f"fixture-award-{number}", field="awards",
                                                   value=value, quote=f"奖项奖励：{value}"))
    optional_result = verify_competition(optional_conflict, policy)
    records = [
        {"case": "full_22_fields", "description": "22必须项通过；不适用有证据，日期不伪造",
         "passed": full.status == "verified" and full.coverage == 1 and full.fields["campus_deadline"].verified_value is None,
         "verification": full.to_dict()},
        {"case": "missing_fee_then_found", "description": "费用未说明时补查；得到官方零费用后通过",
         "passed": recovered.stop_reason == "complete" and recovered.calls == 1,
         "result": recovered.to_dict()},
        {"case": "online_requires_schedule", "description": "全程线上硬条件升级详细赛程，缺证据保留待确认",
         "passed": constrained.status == "pending" and "schedule" in constrained.unresolved_fields,
         "queries": [vars(item) for item in plan_queries(complete, constrained)], "verification": constrained.to_dict()},
        {"case": "budget_unknown_stays_pending", "description": "总预算要求升级投入信息，达到搜索预算仍待确认",
         "passed": unknown_budget.stop_reason == "max_calls" and unknown_budget.verification.status == "pending",
         "result": unknown_budget.to_dict()},
        {"case": "optional_conflict_visible", "description": "可信人工标注回放：奖励冲突可见但不阻断核心字段",
         "passed": optional_result.status == "verified" and optional_result.optional_conflict_fields == ["awards"],
         "verification": optional_result.to_dict()},
    ]
    return {"data_kind": "synthetic_offline_replay", "policy_profile": "student", "real_search_connected": False,
            "cases": records, "passed": sum(item["passed"] for item in records), "total": len(records)}


def main():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    (root / "examples" / "student_review_bundle.json").write_text(
        json.dumps(make_bundle(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = run_examples()
    (root / "outputs").mkdir(exist_ok=True)
    (root / "outputs" / "student_demo_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"学生清单离线示例：{result['passed']}/{result['total']} 通过；全部为虚构数据。")
    if result["passed"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
