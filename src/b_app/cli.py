"""Local verification CLI. Reads data and creates a plan; never calls a service."""

import argparse
import json
import sys
from pathlib import Path

from .b_io import review_bundle_from_dict
from .evidence_verifier import verify_competition
from .query_planner import plan_queries
from .source_review import review_competition
from .field_catalog import CATALOG_VERSION, build_policy


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="B 模块：核验证据并生成补查请求（不联网）")
    parser.add_argument("input", type=Path, help="C 提供的赛事 JSON")
    parser.add_argument("--output", type=Path, help="另存 JSON 结果")
    parser.add_argument("--pre-reviewed", action="store_true", help="仅用于 B 已审查的可信标注样本；跳过原文规则审查")
    parser.add_argument("--profile", choices=("student", "legacy_minimal"), default="student", help="默认学生清单；legacy_minimal仅旧3字段回归")
    parser.add_argument("--requirements", type=Path, help="A/C确认的用户硬条件JSON，不接受抽取器推定的匹配结论")
    args = parser.parse_args()
    try:
        requirements = json.loads(args.requirements.read_text(encoding="utf-8-sig")) if args.requirements else {}
        if not isinstance(requirements, dict) or set(requirements) - {"hard_constraints", "extra_required_fields"}:
            raise ValueError("Requirements must contain only hard_constraints and extra_required_fields")
        for key, value in requirements.items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{key} must be a list of strings")
        policy = build_policy(profile=args.profile, **requirements)
        competition, approved_sources, snapshots = review_bundle_from_dict(json.loads(args.input.read_text(encoding="utf-8-sig")))
        reviews = []
        if not args.pre_reviewed:
            competition, reviews = review_competition(competition, approved_sources=approved_sources, snapshots=snapshots)
        verification = verify_competition(competition, policy)
        queries = plan_queries(competition, verification)
        result = {
            "mode": "verification_and_planning_only",
            "catalog_version": CATALOG_VERSION,
            "policy_profile": args.profile,
            "review_mode": "trusted_pre_reviewed" if args.pre_reviewed else "conservative_literal_rules",
            "source_reviews": [{"evidence_id": item.evidence.id, "source_verified": item.evidence.source_verified,
                                "support": item.evidence.support, "reasons": item.reasons} for item in reviews],
            "verification": verification.to_dict(),
            "requests": [{
                "action": "search", "competition_id": query.competition_id,
                "contest_name": competition.name, "edition": competition.edition,
                "target_fields": [query.field], "query": query.text,
                "reason": query.reason, "scope": query.scope, "round": 1,
            } for query in queries],
            "note": "这里仅生成初次补查建议；实际循环和预算交给 run_adaptive_search。",
        }
        output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        print(output)
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(2, f"输入或输出失败：{exc}\n")


if __name__ == "__main__":
    main()
