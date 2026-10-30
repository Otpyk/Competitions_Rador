"""Replay legacy three-field synthetic evidence; never real performance claims."""

import argparse
from copy import deepcopy
from dataclasses import replace
import json
import sys
from pathlib import Path

from b_app.adaptive_search import run_adaptive_search
from b_app.b_contracts import Evidence, SearchBatch, SearchBudget
from b_app.b_io import competition_from_dict, review_bundle_from_dict
from b_app.field_catalog import build_policy
from b_app.source_review import ApprovedSource, SourceSnapshot, review_competition, review_evidence


def deadline_evidence(**changes) -> Evidence:
    return replace(Evidence(
        id="deadline-2026", field="registration_deadline", value="2026-11-10",
        url="https://contest.example.invalid/2026/notice",
        quote="虚构校园 AI 创意赛 2026 届报名截止日期为 2026 年 11 月 10 日。",
        edition="2026", source_type="official", source_verified=True,
        support="supported", reviewed_by="fixture:synthetic-annotation-not-a-real-source",
    ), **changes)


def run_examples() -> dict:
    raw = json.loads(Path(__file__).with_name("input_missing_deadline.json").read_text(encoding="utf-8"))
    missing = competition_from_dict(raw)
    full = deepcopy(missing)
    full.evidence.append(deadline_evidence())
    old = deepcopy(missing)
    old.evidence.append(deadline_evidence(id="deadline-2024", edition="2024", value="2024-11-10"))
    conflict = deepcopy(full)
    conflict.evidence.append(deadline_evidence(
        id="second-deadline", value="2026-11-15",
        quote="虚构 2026 届另一份官方通知：报名截止日期为 2026 年 11 月 15 日。",
    ))
    campus = deepcopy(full)
    campus.evidence.append(deadline_evidence(
        id="campus-deadline", value="2026-11-01", source_type="school",
        scope="campus:虚构大学", quote="虚构大学校内截止日期为 2026-11-01。",
    ))
    past = deepcopy(full)
    past.edition = "2020"
    past.evidence = [replace(item, edition="2020") for item in past.evidence]
    past.evidence[-1] = deadline_evidence(
        edition="2020", value="2020-11-10", quote="虚构 2020 届报名于 2020-11-10 截止。",
    )

    def found(query, remaining):
        return SearchBatch(evidence=[deadline_evidence()] if query.field == "registration_deadline" else [], cost=0.0)

    def absent(query, remaining):
        return SearchBatch(cost=0.0)

    def failed(query, remaining):
        raise TimeoutError("虚构回放：模拟搜索超时")

    cases = [
        ("already_complete", "证据齐全，直接停止", full, absent, {}, "verified", "complete"),
        ("missing_then_found", "缺日期，补查获得证据", missing, found, {}, "verified", "complete"),
        ("missing_stays_unknown", "补查无结果，日期仍待确认", missing, absent, {}, "pending", "no_new_evidence"),
        ("old_edition", "往年证据不能核验当届", old, absent, {}, "pending", "no_new_evidence"),
        ("source_conflict", "不同可靠日期保留冲突", conflict, absent, {}, "conflict", "unresolved_conflict"),
        ("campus_scope", "校内截止不覆盖全国截止", campus, absent, {}, "verified", "complete"),
        ("zero_budget", "没有调用额度就停止", missing, found, {"budget": SearchBudget(max_calls=0)}, "pending", "max_calls"),
        ("ablation_disabled", "关闭自适应搜索的消融配置", missing, found, {"enabled": False}, "pending", "adaptive_disabled"),
        ("search_failure", "搜索失败有记录，费用未知", missing, failed, {}, "pending", "search_error"),
        ("past_deadline", "过期事实可核验，但B不判断可报名", past, absent, {}, "verified", "complete"),
    ]
    bundle = json.loads(Path(__file__).with_name("review_bundle.json").read_text(encoding="utf-8"))
    raw_candidate, approvals, snapshots = review_bundle_from_dict(bundle)
    reviewed_candidate, initial_reviews = review_competition(
        raw_candidate, approved_sources=approvals, snapshots=snapshots,
    )

    def found_and_reviewed_by_b(query, remaining):
        # A would fetch the snapshot; C would extract this raw record. The
        # trusted approval list belongs to B and is never supplied by C's model.
        raw_evidence = Evidence(
            id="deadline-raw", field="registration_deadline", value="2026-11-10",
            url="https://contest.example.invalid/2026/notice",
            quote="报名截止日期：2026年11月10日。", edition="2026",
        )
        approval = ApprovedSource(
            competition_id=raw_candidate.id, edition="2026", scope="global",
            url=raw_evidence.url, source_type="official",
            approved_by="fixture:B-reviewed-fictional-source",
        )
        snapshot = SourceSnapshot(url=raw_evidence.url, text="虚构 2026 届通知\n\n" + raw_evidence.quote)
        reviewed = review_evidence(
            raw_candidate, raw_evidence, approved_sources=[approval], snapshots=[snapshot],
        )
        return SearchBatch(evidence=[reviewed.evidence], cost=0.0)

    cases.append((
        "raw_text_review_then_search", "B从原文审查，补查后再次审查并核验",
        reviewed_candidate, found_and_reviewed_by_b, {}, "verified", "complete",
    ))
    records = []
    for case_id, description, candidate, callback, options, expected_status, expected_stop in cases:
        outcome = run_adaptive_search(
            candidate, callback, policy=build_policy(profile="legacy_minimal"), **options,
        )
        records.append({
            "case_id": case_id,
            "description": description,
            "expected_status": expected_status,
            "expected_stop_reason": expected_stop,
            "matches_expectation": outcome.verification.status == expected_status and outcome.stop_reason == expected_stop,
            "result": outcome.to_dict(),
        })
    return {
        "data_kind": "synthetic_offline_replay",
        "policy_profile": "legacy_minimal",
        "notice": "旧三字段策略回归：全部赛事、网页地址、审查标注和补查响应均为虚构。0费用仅表示未调用服务；这些结果不是22项学生清单的完整验收，也不是联网效果或竞赛推荐准确率。",
        "cases": records,
        "initial_literal_reviews": [{"evidence_id": review.evidence.id, "support": review.evidence.support,
                                    "reasons": review.reasons} for review in initial_reviews],
    }


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="B模块旧三字段策略离线回归回放")
    parser.add_argument("--output", type=Path, default=Path("outputs/demo_results.json"))
    args = parser.parse_args()
    results = run_examples()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for case in results["cases"]:
        outcome = case["result"]
        print(f"{case['case_id']}: {outcome['verification']['status']} / {outcome['stop_reason']} / calls={outcome['calls']} / expected={case['matches_expectation']}")
    print(f"离线回放记录已保存：{args.output.resolve()}")
    if not all(case["matches_expectation"] for case in results["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
