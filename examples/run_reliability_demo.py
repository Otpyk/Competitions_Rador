"""Replay the concrete v3 failure cases. All pages and approvals are fictional."""

import json
from pathlib import Path
import sys

from b_app.adaptive_search import run_adaptive_search
from b_app.b_contracts import Competition, Evidence, SearchBatch
from b_app.b_io import review_bundle_from_dict
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import CATALOG_VERSION
from b_app.source_review import review_competition
from .run_student_demo import make_bundle


def reviewed(bundle):
    competition, approvals, snapshots = review_bundle_from_dict(bundle)
    return review_competition(competition, approved_sources=approvals, snapshots=snapshots)[0]


def replace_field(bundle, name, value, quote, kind="value"):
    field = bundle["competition"]["fields"][name]
    record = field["evidence"][0]
    bundle["snapshots"][0]["text"] = bundle["snapshots"][0]["text"].replace(record["quote"], quote)
    field["value"] = None if kind == "not_applicable" else value
    record.update(value=value, quote=quote, value_kind=kind)


def run_examples():
    records = []

    def add(case, explanation, result, passed):
        records.append({"case": case, "explanation": explanation, "passed": passed, "result": result})

    bundle = make_bundle()
    bundle["snapshots"][0]["text"] = bundle["snapshots"][0]["text"].replace("届次年份：2026", "届次年份：2025")
    result = verify_competition(reviewed(bundle))
    add("错届页面", "页面明确是2025届，不能证明2026届的资格、日期或入口。", result.to_dict(),
        result.coverage == 0 and result.fields["eligibility"].next_action == "search")

    bundle = make_bundle()
    bundle["snapshots"][0]["text"] += "\n\n附加参赛条件：仅限计算机专业。"
    result = verify_competition(reviewed(bundle))
    add("资格摘录漏条件", "原文另有限制专业的段落，交回C补完整摘录。", result.to_dict(),
        result.fields["eligibility"].next_action == "repair_extraction" and result.status == "pending")

    bundle = make_bundle()
    replace_field(bundle, "registration_start", "2026-12-01", "报名开始日期：2026-12-01")
    result = verify_competition(reviewed(bundle))
    add("报名时间倒置", "开始晚于截止，两项都不能继续作为已核验日期输出。", result.to_dict(),
        result.status == "conflict" and "registration_deadline" not in result.verified_fields)

    bundle = make_bundle()
    statement = "本赛事仅接受个人参赛，无需组队。"
    replace_field(bundle, "team_rules", statement, "组队规则：" + statement, "not_applicable")
    result = verify_competition(reviewed(bundle))
    add("个人与团队冲突", "同一范围同时要求团队参赛和仅个人参赛，保留冲突。", result.to_dict(),
        any(item["code"] == "individual_only_vs_team_participation" for item in result.consistency_issues))

    bundle = make_bundle()
    replace_field(bundle, "attendance_mode", "决赛必须线下到场。", "参赛方式：决赛必须线下到场。")
    result = verify_competition(reviewed(bundle))
    add("线上与到场冲突", "全程线上且无需到场，与决赛必须线下到场不能同时成立。", result.to_dict(),
        any(item["code"] == "online_only_vs_required_onsite" for item in result.consistency_issues))

    def unexpected_search(*_):
        raise AssertionError("This scenario has a handoff task, not a search task")

    bundle = make_bundle()
    bundle["approved_sources"] = []
    outcome = run_adaptive_search(reviewed(bundle), unexpected_search)
    add("已有来源待B审查", "已有资料但未批准来源，列出B的审查任务，不反复搜索。", outcome.to_dict(),
        outcome.calls == 0 and outcome.stop_reason == "handoff_required" and outcome.verification.status == "pending")

    bundle = make_bundle()
    bundle["snapshots"] = []
    outcome = run_adaptive_search(reviewed(bundle), unexpected_search)
    add("已有链接缺原文", "把具体链接交给A抓取原文，不浪费搜索次数。", outcome.to_dict(),
        outcome.calls == 0 and all(item.next_action == "fetch_source" for item in outcome.verification.fields.values()))

    candidate = Competition("fairness", "虚构竞赛", "2026")

    def search(query, _):
        evidence = []
        if query.field == "organizer":
            evidence = [Evidence("org", "organizer", "虚构大学", "https://contest.example.invalid/notice",
                                 "主办方：虚构大学", "2026", source_type="official", source_verified=True,
                                 support="supported", reviewed_by="fixture:trusted-manual-replay")]
        return SearchBatch(evidence=evidence, cost=0)

    outcome = run_adaptive_search(candidate, search)
    add("前三项无结果仍查后续", "前三次没有结果，仍在原6次预算内查询其他字段，第4项有收获。", outcome.to_dict(),
        outcome.calls == 6 and outcome.verification.fields["organizer"].status == "verified"
        and len({event.query.field for event in outcome.events}) == 6)
    return {"catalog_version": CATALOG_VERSION, "data_kind": "synthetic_offline_replay", "real_search_connected": False,
            "cases": records, "passed": sum(item["passed"] for item in records), "total": len(records)}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    result = run_examples()
    (root / "outputs" / "reliability_demo_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["B 第三版行为演示（全部为虚构离线案例）", ""]
    for record in result["cases"]:
        lines.extend([record["case"] + ("：通过" if record["passed"] else "：失败"), record["explanation"], ""])
    lines.append(f"共 {result['total']} 个场景，{result['passed']} 个通过。这不是真实赛事准确率。")
    (root / "outputs" / "B_v3行为演示.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[-1])
    if result["passed"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
