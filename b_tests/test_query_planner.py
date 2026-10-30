"""Legacy three-field plans remain deterministic and never execute a search."""

import copy
import unittest

from b_app.b_contracts import Competition, Evidence, VerificationPolicy
from b_app.evidence_verifier import verify_competition as _verify_competition
from b_app.field_catalog import LEGACY_MINIMAL_FIELDS as REQUIRED_FIELDS, build_policy
from b_app.query_planner import plan_queries


def verify_competition(competition, policy=None):
    """Keep these historical fixtures on the explicit legacy profile."""
    if policy is None:
        policy = build_policy(profile="legacy_minimal")
    return _verify_competition(competition, policy)


VALUES = {
    "registration_deadline": "2026-10-31",
    "eligibility": "全国普通高校在读本科生均可参加。",
    "registration_url": "https://contest.example.invalid/register",
}


def candidate(evidence_fields=(), **changes):
    item = Competition(
        id="fictional-contest-2026",
        name="虚构大学生创新赛",
        edition="2026",
        fields=dict(VALUES),
        evidence=[Evidence(
            id=f"evidence-{field}", field=field, value=VALUES[field],
            url="https://contest.example.invalid/2026/notice",
            quote=f"2026 届虚构赛事：{VALUES[field]}", edition="2026",
            source_type="official", source_verified=True,
            support="supported", reviewed_by="human:fixture-reviewer",
        ) for field in evidence_fields],
    )
    for key, value in changes.items():
        setattr(item, key, value)
    return item


class QueryPlannerTests(unittest.TestCase):
    def test_all_unverified_fields_generate_specific_queries_in_required_order(self):
        item = candidate()
        queries = plan_queries(item, verify_competition(item))

        self.assertEqual([query.field for query in queries], list(REQUIRED_FIELDS))
        terms = {
            "registration_deadline": ("截止",),
            "eligibility": ("资格", "参赛对象", "参赛条件"),
            "registration_url": ("报名",),
        }
        for query in queries:
            self.assertEqual(query.competition_id, item.id)
            self.assertIn(item.name, query.text)
            self.assertIn(item.edition, query.text)
            self.assertTrue(any(term in query.text for term in terms[query.field]))
            self.assertTrue(query.reason.strip())

    def test_fully_verified_candidate_needs_no_queries(self):
        item = candidate(REQUIRED_FIELDS)

        self.assertEqual(plan_queries(item, verify_competition(item)), [])

    def test_only_missing_deadline_is_targeted_when_other_fields_are_verified(self):
        item = candidate(("eligibility", "registration_url"))
        item.fields["registration_deadline"] = None
        queries = plan_queries(item, verify_competition(item))

        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0].field, "registration_deadline")
        self.assertTrue(queries[0].reason)

    def test_original_missing_value_does_not_trigger_query_if_evidence_verifies_it(self):
        item = candidate(REQUIRED_FIELDS)
        item.fields["registration_deadline"] = None
        verification = verify_competition(item)

        self.assertEqual(verification.missing_fields, ["registration_deadline"])
        self.assertEqual(plan_queries(item, verification), [])

    def test_conflict_triggers_followup_for_the_disputed_field(self):
        item = candidate(REQUIRED_FIELDS)
        item.evidence.append(Evidence(
            id="conflicting-deadline", field="registration_deadline", value="2026-11-01",
            url="https://contest.example.invalid/2026/second-notice",
            quote="2026 届虚构赛事报名截止日期为 2026-11-01。", edition="2026",
            source_type="official", source_verified=True,
            support="supported", reviewed_by="human:fixture-reviewer",
        ))
        verification = verify_competition(item)
        queries = plan_queries(item, verification)

        self.assertEqual(verification.status, "conflict")
        self.assertEqual([query.field for query in queries], ["registration_deadline"])
        self.assertTrue(queries[0].reason)

    def test_custom_required_order_is_preserved(self):
        item = candidate()
        policy = VerificationPolicy(required_fields=("registration_url", "eligibility"))
        queries = plan_queries(item, verify_competition(item, policy))

        self.assertEqual([query.field for query in queries], ["registration_url", "eligibility"])

    def test_campus_scope_is_included_in_queries(self):
        item = candidate(scope="campus:示例大学")
        queries = plan_queries(item, verify_competition(item))

        self.assertTrue(queries)
        for query in queries:
            self.assertIn("示例大学", query.text)

    def test_a_result_for_a_different_competition_is_rejected(self):
        first = candidate(id="first-contest")
        second = candidate(id="second-contest")

        with self.assertRaises(ValueError):
            plan_queries(second, verify_competition(first))

    def test_planning_is_repeatable_and_does_not_mutate_inputs(self):
        item = candidate(("eligibility",))
        verification = verify_competition(item)
        before = copy.deepcopy((item, verification))

        first = plan_queries(item, verification)
        second = plan_queries(item, verification)

        self.assertEqual(first, second)
        self.assertEqual((item, verification), before)


if __name__ == "__main__":
    unittest.main()
