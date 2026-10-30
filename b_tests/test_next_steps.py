"""Full-chain checks for actionable uncertainty; all sources are synthetic."""

from dataclasses import replace
import unittest

from b_app.adaptive_search import run_adaptive_search
from b_app.b_contracts import Competition, Evidence, VerificationPolicy
from b_app.b_io import evidence_from_dict
from b_app.evidence_verifier import verify_competition
from b_app.query_planner import plan_queries
from b_app.source_review import ApprovedSource, SourceSnapshot, review_competition
from examples.run_student_demo import make_bundle, reviewed_bundle


URL = "https://contest.example.invalid/2026/notice"
QUOTE = "参赛资格：全国高校在读本科生。"
POLICY = VerificationPolicy(required_fields=("eligibility",))


class NextStepsTests(unittest.TestCase):
    def review(self, *, quote=QUOTE, text=QUOTE, approved=True, snapshot=True, value="全国高校在读本科生。"):
        item = Evidence("eligibility-raw", "eligibility", value, URL, quote, "2026")
        competition = Competition("test", "虚构赛", "2026", evidence=[item])
        approvals = [ApprovedSource("test", "2026", "global", URL, "official", "B:fixture")] if approved else []
        snapshots = [SourceSnapshot(URL, text)] if snapshot else []
        reviewed, _ = review_competition(competition, approved_sources=approvals, snapshots=snapshots)
        return reviewed, verify_competition(reviewed, POLICY)

    def test_unapproved_existing_source_is_handed_to_b_without_search(self):
        item, result = self.review(approved=False)
        self.assertEqual(result.fields["eligibility"].next_action, "human_review")
        self.assertEqual(plan_queries(item, result), [])
        outcome = run_adaptive_search(item, lambda *_: self.fail("Review is not a search"), policy=POLICY)
        self.assertEqual(outcome.stop_reason, "handoff_required")
        self.assertEqual(outcome.calls, 0)
        self.assertEqual(outcome.verification.status, "pending")
        action = outcome.to_dict()["verification"]["action_items"][0]
        self.assertEqual(action["owner"], "B")
        self.assertEqual(action["source_urls"], [URL])

    def test_missing_snapshot_requests_fetch_of_existing_url(self):
        item, result = self.review(snapshot=False)
        check = result.fields["eligibility"]
        self.assertEqual(check.next_action, "fetch_source")
        self.assertEqual(check.source_urls, [URL])
        self.assertIn("source_snapshot_missing", check.rejected_evidence["eligibility-raw"])
        self.assertEqual(plan_queries(item, result), [])

    def test_quote_not_in_source_routes_to_extraction_repair(self):
        _, result = self.review(quote="参赛资格：任何人都可以参加。")
        self.assertEqual(result.fields["eligibility"].next_action, "repair_extraction")
        self.assertEqual(result.to_dict()["action_items"][0]["owner"], "C")

    def test_partial_qualification_routes_to_c_instead_of_another_search(self):
        item, result = self.review(text=QUOTE + "\n\n附加参赛条件：仅限计算机专业。")
        self.assertEqual(result.fields["eligibility"].status, "pending")
        self.assertEqual(result.fields["eligibility"].next_action, "repair_extraction")
        self.assertEqual(plan_queries(item, result), [])

    def test_source_other_edition_routes_to_a_for_correct_notice(self):
        item, result = self.review(text="届次年份：2025。\n\n" + QUOTE)
        self.assertEqual(result.fields["eligibility"].next_action, "search")
        query = plan_queries(item, result)[0]
        self.assertIn("2026", query.text)
        self.assertEqual(result.coverage, 0)

    def test_unhandled_approved_prose_needs_human_review(self):
        prose = "欢迎全国高校在读本科生报名本赛事。"
        _, result = self.review(quote=prose, text=prose)
        self.assertEqual(result.fields["eligibility"].next_action, "human_review")
        self.assertEqual(result.status, "pending")

    def test_missing_school_requests_context_not_an_arbitrary_school_search(self):
        competition = Competition("test", "虚构赛", "2026")
        policy = VerificationPolicy(required_fields=("school_recognition",))
        result = verify_competition(competition, policy)
        self.assertEqual(result.fields["school_recognition"].next_action, "clarify_context")
        self.assertEqual(result.to_dict()["action_items"][0]["owner"], "A/C")
        self.assertEqual(plan_queries(competition, result), [])

    def test_missing_edition_blocks_broad_search(self):
        competition = Competition("test", "虚构赛", "未知")
        result = verify_competition(competition, POLICY)
        self.assertEqual(result.fields["eligibility"].next_action, "clarify_context")
        self.assertEqual(plan_queries(competition, result), [])

    def test_unknown_fact_without_a_candidate_remains_a_search_gap(self):
        competition = Competition("test", "虚构赛", "2026")
        result = verify_competition(competition, POLICY)
        self.assertEqual(result.fields["eligibility"].next_action, "search")
        self.assertEqual(len(plan_queries(competition, result)), 1)

    def test_verified_fields_do_not_generate_action_items(self):
        _, result = self.review()
        self.assertEqual(result.fields["eligibility"].next_action, "none")
        self.assertEqual(result.to_dict()["action_items"], [])

    def test_review_reasons_roundtrip_and_validation(self):
        data = {"id": "e", "field": "eligibility", "value": "本科生", "url": URL,
                "quote": QUOTE, "edition": "2026", "review_reasons": ["source_not_approved"]}
        self.assertEqual(evidence_from_dict(data).review_reasons, ("source_not_approved",))
        with self.assertRaises(ValueError):
            evidence_from_dict(dict(data, review_reasons="source_not_approved"))

    def test_reversed_dates_are_withheld_from_verified_output(self):
        bundle = make_bundle()
        field = bundle["competition"]["fields"]["registration_start"]
        old_quote = field["evidence"][0]["quote"]
        field["value"] = field["evidence"][0]["value"] = "2026-12-01"
        field["evidence"][0]["quote"] = "报名开始日期：2026-12-01"
        bundle["snapshots"][0]["text"] = bundle["snapshots"][0]["text"].replace(old_quote, field["evidence"][0]["quote"])
        item = reviewed_bundle(bundle)
        result = verify_competition(item)
        self.assertEqual(result.status, "conflict")
        self.assertNotIn("registration_start", result.verified_fields)
        self.assertNotIn("registration_deadline", result.verified_fields)
        issue = result.consistency_issues[0]
        self.assertEqual(issue["code"], "registration_start_after_deadline")
        self.assertEqual(issue["values"]["registration_start"], "2026-12-01")
        self.assertEqual(result.fields["registration_deadline"].next_action, "search")

    def test_required_online_vs_optional_schedule_conflict_cannot_hide(self):
        item = reviewed_bundle()
        template = next(record for record in item.evidence if record.field == "attendance_mode")
        item.evidence.append(replace(template, id="onsite-schedule", field="schedule", value="决赛必须线下到场。",
                                     quote="详细赛程：决赛必须线下到场。"))
        result = verify_competition(item)
        self.assertEqual(result.status, "conflict")
        self.assertIn("venue", result.unresolved_fields)
        self.assertIn("schedule", result.optional_conflict_fields)
        self.assertNotIn("venue", result.to_dict()["not_applicable_fields"])
        self.assertTrue(result.consistency_issues)

    def test_duplicate_evidence_is_repaired_instead_of_searched(self):
        item, _ = self.review()
        item.evidence.append(item.evidence[0])
        result = verify_competition(item, POLICY)
        self.assertEqual(result.fields["eligibility"].next_action, "repair_extraction")


if __name__ == "__main__":
    unittest.main()
