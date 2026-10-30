"""Legacy-profile controller regressions; all search adapters are local fakes."""

from copy import deepcopy
from dataclasses import replace
import unittest

from b_app.adaptive_search import run_adaptive_search as _run_adaptive_search
from b_app.b_contracts import (
    Competition,
    Evidence,
    SearchBatch,
    SearchBudget,
    VerificationPolicy,
)
from b_app.field_catalog import build_policy


def run_adaptive_search(competition, callback, *, policy=None, **options):
    """Use the historical three-field policy without changing production defaults."""
    if policy is None:
        policy = build_policy(profile="legacy_minimal")
    return _run_adaptive_search(competition, callback, policy=policy, **options)


DEADLINE = "registration_deadline"
ELIGIBILITY = "eligibility"
REGISTRATION_URL = "registration_url"
VALUES = {
    DEADLINE: "2026-11-10",
    ELIGIBILITY: "在校本科生",
    REGISTRATION_URL: "https://example.org/2026/register",
}


def evidence(field=DEADLINE, value=None, **changes):
    values = {
        "id": f"e-{field}",
        "field": field,
        "value": VALUES[field] if value is None else value,
        "url": "https://example.org/2026/rules",
        "quote": f"{field}: {VALUES[field] if value is None else value}",
        "edition": "2026",
        "source_type": "official",
        "source_verified": True,
        "support": "supported",
        "reviewed_by": "test-human-reviewer",
    }
    values.update(changes)
    return Evidence(**values)


def candidate(records=()):
    return Competition(
        id="demo",
        name="校园 AI 创意赛",
        edition="2026",
        fields={name: None for name in VALUES},
        evidence=list(records),
    )


class AdaptiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.deadline_policy = VerificationPolicy(required_fields=(DEADLINE,))

    def test_complete_initial_candidate_never_calls_search(self):
        def fail(*_):
            self.fail("A verified candidate must not be searched")

        result = run_adaptive_search(
            candidate([evidence()]),
            fail,
            policy=self.deadline_policy,
            budget=SearchBudget(max_rounds=0, max_calls=0, max_cost=0),
        )
        self.assertEqual(result.stop_reason, "complete")
        self.assertEqual((result.calls, result.rounds), (0, 0))
        self.assertEqual(result.events, [])

    def test_input_is_not_mutated_and_one_response_can_finish_all_fields(self):
        original = candidate()
        original.fields["metadata"] = {"tags": ["original"]}
        snapshot = deepcopy(original)
        invoked = []

        def search(query, remaining):
            invoked.append((query, remaining))
            return SearchBatch(evidence=[evidence(field) for field in VALUES], cost=0.2)

        result = run_adaptive_search(original, search)
        self.assertEqual(result.stop_reason, "complete")
        self.assertEqual(result.calls, 1)
        self.assertEqual(len(invoked), 1)
        self.assertEqual(result.events[0].new_valid_evidence_count, 3)
        self.assertEqual(original, snapshot)
        result.competition.fields["extra"] = "private"
        result.competition.fields["metadata"]["tags"].append("private")
        self.assertNotIn("extra", original.fields)
        self.assertEqual(original.fields["metadata"]["tags"], ["original"])

    def test_ablation_verifies_but_never_searches(self):
        def fail(*_):
            self.fail("Disabled adaptive search cannot invoke the adapter")

        result = run_adaptive_search(candidate(), fail, enabled=False)
        self.assertEqual(result.stop_reason, "adaptive_disabled")
        self.assertEqual(result.verification.status, "pending")
        self.assertEqual(result.calls, 0)

    def test_zero_limits_never_invoke_adapter(self):
        def fail(*_):
            self.fail("Zero budget cannot invoke the adapter")

        for budget, expected in (
            (SearchBudget(max_rounds=0), "max_rounds"),
            (SearchBudget(max_calls=0), "max_calls"),
            (SearchBudget(max_cost=0), "max_cost"),
        ):
            with self.subTest(expected=expected):
                result = run_adaptive_search(candidate(), fail, budget=budget)
                self.assertEqual(result.stop_reason, expected)
                self.assertEqual((result.calls, result.rounds), (0, 0))

    def test_round_and_query_limits_are_enforced(self):
        def search(query, remaining):
            return SearchBatch(evidence=[evidence(query.field)], cost=0)

        result = run_adaptive_search(
            candidate(),
            search,
            budget=SearchBudget(max_rounds=2, max_calls=10, max_queries_per_round=1),
        )
        self.assertEqual(result.stop_reason, "max_rounds")
        self.assertEqual((result.calls, result.rounds), (2, 2))
        self.assertEqual([event.round for event in result.events], [1, 2])

    def test_call_limit_is_enforced(self):
        result = run_adaptive_search(
            candidate(),
            lambda query, _: SearchBatch(evidence=[evidence(query.field)], cost=0),
            budget=SearchBudget(max_rounds=10, max_calls=1),
        )
        self.assertEqual(result.stop_reason, "max_calls")
        self.assertEqual(result.calls, 1)

    def test_remaining_budget_is_passed_to_each_callback(self):
        budgets = []

        def search(query, remaining):
            budgets.append(remaining)
            return SearchBatch(evidence=[evidence(query.field)], cost=0.25)

        result = run_adaptive_search(
            candidate(), search,
            budget=SearchBudget(max_rounds=3, max_calls=4, max_queries_per_round=2, max_cost=1),
        )
        self.assertEqual(result.stop_reason, "complete")
        self.assertEqual([b.max_calls for b in budgets], [4, 3, 2])
        self.assertEqual([b.max_cost for b in budgets], [1, 0.75, 0.5])
        self.assertEqual([b.max_queries_per_round for b in budgets], [2, 1, 2])
        self.assertEqual([b.max_rounds for b in budgets], [3, 3, 2])
        self.assertEqual(result.known_cost, 0.75)

    def test_exact_cost_limit_prevents_a_further_call(self):
        result = run_adaptive_search(
            candidate(),
            lambda query, _: SearchBatch(evidence=[evidence(query.field)], cost=0.5),
            budget=SearchBudget(max_cost=0.5),
        )
        self.assertEqual(result.stop_reason, "max_cost")
        self.assertEqual(result.calls, 1)

    def test_overspend_is_visible_even_if_result_is_now_complete(self):
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(evidence=[evidence()], cost=1.5),
            policy=self.deadline_policy, budget=SearchBudget(max_cost=1),
        )
        self.assertEqual(result.stop_reason, "max_cost")
        self.assertEqual(result.verification.status, "verified")
        self.assertEqual(result.known_cost, 1.5)
        self.assertEqual(result.calls, 1)

    def test_completion_at_exact_cost_ceiling_is_allowed(self):
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(evidence=[evidence()], cost=1),
            policy=self.deadline_policy, budget=SearchBudget(max_cost=1),
        )
        self.assertEqual(result.stop_reason, "complete")

    def test_unknown_cost_with_amount_limit_stops_immediately(self):
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(evidence=[evidence()], cost=None),
            budget=SearchBudget(max_cost=1),
        )
        self.assertEqual(result.stop_reason, "unknown_cost")
        self.assertFalse(result.cost_complete)
        self.assertEqual(result.known_cost, 0)
        self.assertEqual(result.calls, 1)
        self.assertIsNone(result.events[0].cost)

    def test_unknown_cost_without_amount_limit_is_not_reported_as_free(self):
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(evidence=[evidence()], cost=None),
            policy=self.deadline_policy,
        )
        self.assertEqual(result.stop_reason, "complete")
        self.assertFalse(result.cost_complete)

    def test_unknown_later_cost_retains_the_known_subtotal(self):
        calls = []

        def search(query, _):
            calls.append(query)
            return SearchBatch(
                evidence=[evidence(query.field)],
                cost=0.25 if len(calls) == 1 else None,
            )

        result = run_adaptive_search(candidate(), search, budget=SearchBudget(max_cost=1))
        self.assertEqual(result.stop_reason, "unknown_cost")
        self.assertEqual(result.calls, 2)
        self.assertEqual(result.known_cost, 0.25)
        self.assertFalse(result.cost_complete)

    def test_exception_is_counted_logged_and_stops_without_retry(self):
        def search(*_):
            raise RuntimeError("local adapter failed")

        result = run_adaptive_search(candidate(), search)
        self.assertEqual(result.stop_reason, "search_error")
        self.assertEqual((result.calls, result.rounds), (1, 1))
        self.assertEqual(len(result.events), 1)
        self.assertIn("RuntimeError", result.events[0].error)
        self.assertGreaterEqual(result.events[0].elapsed_seconds, 0)
        self.assertFalse(result.cost_complete)

    def test_reported_failure_keeps_partial_evidence_and_known_cost(self):
        result = run_adaptive_search(
            candidate(),
            lambda *_: SearchBatch(evidence=[evidence()], cost=0.4, error="partial extraction"),
            policy=self.deadline_policy,
        )
        self.assertEqual(result.stop_reason, "search_error")
        self.assertEqual(result.verification.status, "verified")
        self.assertEqual(result.known_cost, 0.4)
        self.assertEqual(result.events[0].error, "partial extraction")

    def test_malformed_adapter_response_stops_with_logged_error(self):
        for response in (
            None,
            SearchBatch(cost=-1),
            SearchBatch(cost=float("nan")),
            SearchBatch(cost=float("inf")),
            SearchBatch(cost=True),
            SearchBatch(evidence=["not evidence"], cost=0.25),
        ):
            with self.subTest(response=response):
                result = run_adaptive_search(candidate(), lambda *_: response)
                self.assertEqual(result.stop_reason, "search_error")
                self.assertEqual(result.calls, 1)
                self.assertIsNotNone(result.events[0].error)

    def test_malformed_evidence_rejects_the_entire_batch_and_keeps_reported_cost(self):
        original = candidate([evidence(REGISTRATION_URL)])
        before = deepcopy(original)
        malformed = replace(evidence(ELIGIBILITY), review_reasons=None)
        result = run_adaptive_search(
            original,
            lambda *_: SearchBatch(evidence=[evidence(), malformed], cost=0.35),
        )
        self.assertEqual(result.stop_reason, "search_error")
        self.assertEqual(result.competition, before)
        self.assertEqual(original, before)
        self.assertEqual(result.known_cost, 0.35)
        self.assertTrue(result.cost_complete)
        self.assertEqual(result.calls, 1)
        self.assertEqual(result.events[0].new_evidence_count, 0)
        self.assertEqual(result.events[0].new_valid_evidence_count, 0)
        self.assertIn("review_reasons", result.events[0].error)

    def test_unhashable_evidence_id_is_logged_instead_of_crashing_verification(self):
        original = candidate()
        malformed = replace(evidence(), id=["invalid-id"])
        result = run_adaptive_search(
            original, lambda *_: SearchBatch(evidence=[malformed], cost=None),
        )
        self.assertEqual(result.stop_reason, "search_error")
        self.assertEqual(result.competition.evidence, [])
        self.assertEqual(original.evidence, [])
        self.assertEqual(result.calls, 1)
        self.assertFalse(result.cost_complete)
        self.assertIsNone(result.events[0].cost)
        self.assertIn("Evidence.id", result.events[0].error)

    def test_empty_search_result_stops_after_default_no_progress_round(self):
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(cost=0),
            policy=self.deadline_policy,
            budget=SearchBudget(max_rounds=10, max_calls=20),
        )
        self.assertEqual(result.stop_reason, "no_new_evidence")
        self.assertEqual((result.calls, result.rounds), (1, 1))

    def test_invalid_and_nonrequired_claims_do_not_extend_search(self):
        for record, expected_stop in (
            (evidence(edition="2024"), "no_new_evidence"),
            (evidence(source_verified=False), "handoff_required"),
            (evidence(support="unknown"), "handoff_required"),
            (evidence(ELIGIBILITY), "no_new_evidence"),
        ):
            with self.subTest(record=record):
                result = run_adaptive_search(
                    candidate(), lambda *_: SearchBatch(evidence=[record], cost=0),
                    policy=self.deadline_policy,
                    budget=SearchBudget(max_rounds=10, max_calls=20),
                )
                self.assertEqual(result.stop_reason, expected_stop)
                self.assertEqual(result.rounds, 1)
                self.assertEqual(result.events[0].new_valid_evidence_count, 0)

    def test_duplicate_claims_do_not_extend_search(self):
        existing = evidence()
        for duplicate in (
            existing,
            replace(existing, id="new-id"),
            replace(existing, retrieved_at="2026-10-22T12:00:00Z"),
            replace(existing, url="https://example.org/2026/other-rules"),
        ):
            with self.subTest(duplicate=duplicate):
                result = run_adaptive_search(
                    candidate([existing]),
                    lambda *_: SearchBatch(evidence=[duplicate], cost=0),
                    budget=SearchBudget(max_rounds=10, max_calls=20),
                )
                self.assertEqual(result.stop_reason, "no_new_evidence")
                self.assertEqual(result.rounds, 1)
                self.assertTrue(all(event.new_valid_evidence_count == 0 for event in result.events))

    def test_equivalent_normalized_values_do_not_count_as_progress(self):
        existing = evidence(value="2026-11-10T12:00:00+08:00")
        duplicate = evidence(value="2026-11-10T04:00:00+00:00", id="utc-copy")
        result = run_adaptive_search(
            candidate([existing]),
            lambda *_: SearchBatch(evidence=[duplicate], cost=0),
            budget=SearchBudget(max_rounds=10, max_calls=20),
        )
        self.assertEqual(result.stop_reason, "no_new_evidence")
        self.assertEqual(result.rounds, 1)
        self.assertTrue(all(event.new_valid_evidence_count == 0 for event in result.events))

    def test_credible_but_insufficient_conflicting_source_does_not_extend_search(self):
        original = evidence()
        school_notice = evidence(
            value="2026-11-11", id="school-notice", source_type="school",
        )
        result = run_adaptive_search(
            candidate([original]),
            lambda *_: SearchBatch(evidence=[school_notice], cost=0),
            budget=SearchBudget(max_rounds=10, max_calls=20),
        )
        self.assertEqual(result.stop_reason, "unresolved_conflict")
        self.assertEqual(result.rounds, 1)
        self.assertEqual(result.verification.fields[DEADLINE].status, "conflict")
        self.assertTrue(all(event.new_valid_evidence_count == 0 for event in result.events))

    def test_conflicting_id_collision_preserves_both_records(self):
        first = evidence(value="2026-11-10")
        conflicting = evidence(value="2026-11-11")
        result = run_adaptive_search(
            candidate([first]), lambda *_: SearchBatch(evidence=[conflicting], cost=0),
            budget=SearchBudget(max_rounds=10, max_calls=20),
        )
        self.assertEqual(result.verification.status, "conflict")
        self.assertEqual(result.stop_reason, "unresolved_conflict")
        records = result.competition.evidence
        self.assertEqual({record.value for record in records}, {"2026-11-10", "2026-11-11"})
        self.assertEqual(len({record.id for record in records}), 2)
        self.assertEqual(len(records), 2)

    def test_existing_conflict_without_new_claims_stops_unresolved(self):
        records = [evidence(), evidence(value="2026-11-11", id="other")]
        result = run_adaptive_search(
            candidate(records), lambda *_: SearchBatch(evidence=records, cost=0),
            policy=self.deadline_policy,
        )
        self.assertEqual(result.stop_reason, "unresolved_conflict")
        self.assertEqual(result.rounds, 1)
        self.assertEqual(result.events[0].new_valid_evidence_count, 0)

    def test_query_can_repeat_in_later_round_when_patience_allows(self):
        queries = []

        def search(query, _):
            queries.append(query.text)
            records = [] if len(queries) == 1 else [evidence()]
            return SearchBatch(evidence=records, cost=0)

        result = run_adaptive_search(
            candidate(), search, policy=self.deadline_policy,
            budget=SearchBudget(max_rounds=3, max_no_progress_rounds=2),
        )
        self.assertEqual(result.stop_reason, "complete")
        self.assertEqual((result.calls, result.rounds), (2, 2))
        self.assertEqual(queries[0], queries[1])


if __name__ == "__main__":
    unittest.main()
