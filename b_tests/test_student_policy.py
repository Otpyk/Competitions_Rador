"""Student-facing decisions for v2; fixtures never represent real contests."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import unittest

from b_app.adaptive_search import run_adaptive_search
from b_app.b_contracts import Competition, Evidence, SearchBatch, SearchBudget, VerificationPolicy
from b_app.b_io import competition_from_dict
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import CATALOG, EXTENSION_FIELDS, MANDATORY_FIELDS, build_policy
from b_app.query_planner import plan_queries
from examples.run_student_demo import make_bundle, reviewed_bundle, run_examples


def trusted(field, value, **kwargs):
    return Evidence(id=f"trusted-{field}", field=field, value=value, edition="2026",
                    url="https://contest.example.invalid/2026/notice", quote=f"人工审查虚构样例：{value}",
                    source_type="official", source_verified=True, support="supported",
                    reviewed_by="fixture:human", **kwargs)


class StudentPolicyTests(unittest.TestCase):
    def test_default_is_all_22_mandatory_fields(self):
        self.assertEqual(len(MANDATORY_FIELDS), 22)
        self.assertEqual(len(EXTENSION_FIELDS), 9)
        self.assertEqual(VerificationPolicy().required_fields, MANDATORY_FIELDS)
        self.assertEqual({item.group for item in CATALOG}, {f"M{i:02}" for i in range(1, 11)} | {f"E{i:02}" for i in range(1, 9)})

    def test_full_unreviewed_table_cannot_pass(self):
        raw = competition_from_dict(make_bundle()["competition"])
        self.assertEqual(verify_competition(raw).coverage, 0)
        self.assertEqual(len(verify_competition(raw).unresolved_fields), 22)

    def test_full_bundle_passes_source_review_and_verification(self):
        result = verify_competition(reviewed_bundle())
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.coverage, 1)
        self.assertIsNone(result.fields["campus_deadline"].verified_value)
        self.assertIn("campus_deadline", result.to_dict()["not_applicable_fields"])
        self.assertNotIn("campus_deadline", result.verified_fields)

    def test_optional_conflict_is_visible_without_blocking_core(self):
        item = reviewed_bundle()
        item.evidence.extend([trusted("awards", "一等奖3队。"), replace(trusted("awards", "一等奖5队。"), id="another")])
        result = verify_competition(item)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.coverage, 1)
        self.assertEqual(result.optional_conflict_fields, ["awards"])
        self.assertEqual(plan_queries(item, result), [])
        self.assertEqual(run_adaptive_search(item, lambda *_: self.fail("Optional conflict must not consume searches")).stop_reason, "complete")

    def test_optional_evidence_without_original_value_is_checked(self):
        item = reviewed_bundle()
        item.evidence.append(trusted("awards", "一等奖3队。"))
        result = verify_competition(item)
        self.assertEqual(result.fields["awards"].status, "verified")
        self.assertFalse(result.fields["awards"].required)
        self.assertEqual(result.verified_fields["awards"], "一等奖3队。")

    def test_empty_extension_template_does_not_create_fake_unrecognized_fields(self):
        item = reviewed_bundle()
        item.fields["awards"] = None
        result = verify_competition(item)
        self.assertNotIn("awards", result.fields)
        self.assertEqual(result.optional_unresolved_fields, [])
        self.assertEqual(result.unrecognized_fields, [])

    def test_promoting_optional_conflict_blocks_completion(self):
        item = reviewed_bundle()
        item.evidence.extend([trusted("awards", "一等奖3队。"), replace(trusted("awards", "一等奖5队。"), id="another")])
        result = verify_competition(item, build_policy(extra_required_fields=["awards"]))
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.unresolved_fields, ["awards"])
        self.assertEqual(result.optional_conflict_fields, [])

    def test_all_user_flags_promote_expected_fields_without_duplicates(self):
        policy = build_policy(hard_constraints=["school_recognition_required", "existing_work_only", "no_hardware",
                                                 "avoid_exam_dates", "total_budget_limit", "online_only", "cross_school_team"])
        for name in ("school_recognition", "work_rules", "technical_requirements", "schedule", "expense_details"):
            self.assertIn(name, policy.required_fields)
            self.assertIn(name, policy.promoted_fields)
        self.assertEqual(len(policy.required_fields), len(set(policy.required_fields)))

    def test_user_constraints_are_prioritized_and_not_a_match_conclusion(self):
        item = Competition("test", "虚构赛", "2026")
        result = verify_competition(item, build_policy(hard_constraints=["existing_work_only"]))
        self.assertEqual(plan_queries(item, result)[0].field, "work_rules")
        self.assertEqual(result.fields["work_rules"].status, "pending")
        self.assertNotIn("eligibility_status", result.to_dict())

    def test_conflicts_prioritized_within_same_priority(self):
        item = Competition("test", "虚构赛", "2026", evidence=[trusted("registration_fee", "每队0元。"),
                     replace(trusted("registration_fee", "每队100元。"), id="other")])
        result = verify_competition(item)
        self.assertEqual(plan_queries(item, result)[0].field, "registration_fee")

    def test_unknown_hard_constraints_do_not_silently_fall_back(self):
        with self.assertRaises(ValueError):
            build_policy(hard_constraints=["onlne_only"])
        with self.assertRaises(ValueError):
            build_policy(extra_required_fields=["random_key"])

    def test_plain_na_or_null_does_not_exempt_missing_date(self):
        for raw in (None, "N/A", {"value": None, "applicability": "not_applicable", "status": "verified"}):
            item = competition_from_dict({"id": "test", "name": "虚构赛", "edition": "2026", "fields": {"campus_deadline": raw}})
            result = verify_competition(item, VerificationPolicy(required_fields=("campus_deadline",)))
            self.assertEqual(result.status, "pending")

    def test_na_conflicts_with_concrete_date_in_same_scope(self):
        item = Competition("test", "虚构赛", "2026", field_scopes={"campus_deadline": "campus:学校甲"})
        item.evidence = [trusted("campus_deadline", "本赛事由个人直接报名，无校内报名环节。",
                                 value_kind="not_applicable", scope="campus:学校甲"),
                         replace(trusted("campus_deadline", "2026-11-02", scope="campus:学校甲"), id="concrete")]
        self.assertEqual(verify_competition(item, VerificationPolicy(required_fields=("campus_deadline",))).status, "conflict")

    def test_school_and_national_dates_remain_distinct(self):
        item = Competition("test", "虚构赛", "2026", field_scopes={"campus_deadline": "campus:学校甲"})
        item.evidence = [trusted("registration_deadline", "2026-11-10"),
                         replace(trusted("campus_deadline", "2026-11-02", scope="campus:学校甲"), source_type="school")]
        result = verify_competition(item, VerificationPolicy(required_fields=("registration_deadline", "campus_deadline")))
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.verified_fields, {"registration_deadline": "2026-11-10", "campus_deadline": "2026-11-02"})

    def test_different_school_cannot_fill_target_school_date(self):
        item = Competition("test", "虚构赛", "2026", field_scopes={"campus_deadline": "campus:学校甲"},
                           evidence=[trusted("campus_deadline", "2026-11-02", scope="campus:学校乙")])
        result = verify_competition(item, VerificationPolicy(required_fields=("campus_deadline",)))
        self.assertEqual(result.status, "pending")
        query = plan_queries(item, result)[0]
        self.assertIn("学校甲", query.text)
        self.assertNotIn("学校乙", query.text)
        self.assertEqual(query.scope, "campus:学校甲")

    def test_campus_date_requires_specific_school_but_universal_na_can_pass(self):
        item = Competition("test", "虚构赛", "2026", evidence=[trusted("campus_deadline", "2026-11-02")])
        policy = VerificationPolicy(required_fields=("campus_deadline",))
        self.assertEqual(verify_competition(item, policy).status, "pending")
        item.evidence = [trusted("campus_deadline", "本赛事由个人直接报名，无校内报名环节。", value_kind="not_applicable")]
        self.assertEqual(verify_competition(item, policy).status, "verified")

    def test_school_recognition_cannot_be_global_or_from_another_school(self):
        policy = VerificationPolicy(required_fields=("school_recognition",))
        item = Competition("test", "虚构赛", "2026", evidence=[trusted("school_recognition", "学校甲认定。")])
        self.assertEqual(verify_competition(item, policy).status, "pending")
        item.field_scopes = {"school_recognition": "campus:学校甲"}
        item.evidence = [replace(item.evidence[0], scope="campus:学校甲", source_type="school")]
        self.assertEqual(verify_competition(item, policy).status, "verified")

    def test_organizer_cannot_self_certify_school_recognition(self):
        item = Competition("test", "虚构赛", "2026", field_scopes={"school_recognition": "campus:学校甲"},
                           evidence=[trusted("school_recognition", "学校甲认定。", scope="campus:学校甲")])
        result = verify_competition(item, VerificationPolicy(required_fields=("school_recognition",)))
        self.assertEqual(result.status, "pending")

    def test_track_mismatch_stays_pending(self):
        item = Competition("test", "虚构赛", "2026", scope="track:软件组",
                           evidence=[trusted("eligibility", "本科生。", scope="track:硬件组")])
        self.assertEqual(verify_competition(item, VerificationPolicy(required_fields=("eligibility",))).status, "pending")

    def test_identity_metadata_does_not_prove_name_or_edition(self):
        item = Competition("test", "虚构赛", "2026")
        policy = VerificationPolicy(required_fields=("competition_name", "competition_edition"))
        self.assertEqual(verify_competition(item, policy).coverage, 0)
        item.evidence = [trusted("competition_edition", "2025"), trusted("competition_name", "另一个比赛")]
        self.assertEqual(verify_competition(item, policy).coverage, 0)

    def test_queries_do_not_inject_a_hardcoded_year(self):
        item = Competition("test", "虚构赛", "2027")
        for query in plan_queries(item, verify_competition(item)):
            self.assertIn("2027", query.text)
            self.assertNotIn("2026", query.text)

    def test_conditional_deadlines_do_not_become_dates(self):
        for value in ("名额满截止", "滚动报名", "长期开放", "待定"):
            item = Competition("test", "虚构赛", "2026", evidence=[trusted("registration_deadline", value)])
            result = verify_competition(item, VerificationPolicy(required_fields=("registration_deadline",)))
            self.assertEqual(result.status, "pending")
            self.assertIsNone(result.fields["registration_deadline"].verified_value)

    def test_other_date_fields_are_validated_and_timezone_is_not_inferred(self):
        for value in ("2026-02-30", "11月2日", "2026-11-02T23:59:00"):
            item = Competition("test", "虚构赛", "2026", evidence=[trusted("submission_deadline", value)])
            self.assertEqual(verify_competition(item, VerificationPolicy(required_fields=("submission_deadline",))).status, "pending")

    def test_unrecognized_fields_are_reported_and_inputs_unchanged(self):
        item = reviewed_bundle()
        item.fields["registraton_fee"] = "misspelled"
        original = deepcopy(item)
        result = verify_competition(item)
        self.assertIn("registraton_fee", result.unrecognized_fields)
        self.assertEqual(item, original)

    def test_budget_exhaustion_does_not_mark_promoted_field_verified(self):
        result = run_adaptive_search(reviewed_bundle(), lambda *_: SearchBatch(cost=0),
                                     policy=build_policy(hard_constraints=["total_budget_limit"]),
                                     budget=SearchBudget(max_calls=1))
        self.assertEqual(result.stop_reason, "max_calls")
        self.assertEqual(result.verification.fields["expense_details"].status, "pending")

    def test_replays_all_match_expected_behaviour(self):
        result = run_examples()
        self.assertEqual(result["passed"], result["total"])

    def test_default_cli_uses_student_profile(self):
        path = Path(__file__).parents[1] / "examples" / "review_bundle.json"
        output = subprocess.run([sys.executable, "-m", "b_app.cli", str(path)], cwd=path.parents[1],
                                check=True, capture_output=True, encoding="utf-8")
        result = json.loads(output.stdout)
        self.assertEqual(result["policy_profile"], "student")
        self.assertEqual(len(result["verification"]["required_fields"]), 22)
        self.assertEqual(result["verification"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
