"""Budget fairness, explicit handoff and multi-field search event regressions."""

from unittest import TestCase
from unittest.mock import patch

from b_app.adaptive_search import run_adaptive_search
from b_app.b_contracts import Competition, Evidence, SearchBatch, SearchBudget, VerificationPolicy
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import MANDATORY_FIELDS
from b_app.query_planner import plan_queries


def candidate():
    return Competition(id="demo", name="Example Contest", edition="2026")


def reviewed(field, value):
    return Evidence(
        id=f"local-{field}", field=field, value=value,
        url="https://example.org/2026/rules", quote=f"{field}: {value}", edition="2026",
        source_type="official", source_verified=True, support="supported",
        reviewed_by="B:offline-review",
    )


class SearchRoutingTests(TestCase):
    def test_empty_first_batch_does_not_starve_a_useful_fourth_field(self):
        def search(query, _):
            records = [reviewed("organizer", "Example University")] if query.field == "organizer" else []
            return SearchBatch(evidence=records, cost=0)

        result = run_adaptive_search(candidate(), search)
        queried = [event.query.field for event in result.events]
        self.assertEqual(result.calls, 6)
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.stop_reason, "max_calls")
        self.assertEqual(queried, list(MANDATORY_FIELDS[:6]))
        self.assertEqual(result.verification.fields["organizer"].status, "verified")

    def test_incidental_progress_does_not_repeat_the_same_first_three_queries(self):
        calls = []

        def search(query, _):
            calls.append(query.field)
            records = [reviewed("deliverables", "Source code and report")] if len(calls) == 1 else []
            if query.field == "organizer":
                records.append(reviewed("organizer", "Example University"))
            return SearchBatch(evidence=records, cost=0)

        result = run_adaptive_search(candidate(), search)
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(set(calls)), 6)
        self.assertEqual(calls, list(MANDATORY_FIELDS[:6]))
        self.assertEqual(result.verification.fields["deliverables"].status, "verified")
        self.assertEqual(result.verification.fields["organizer"].status, "verified")

    def test_user_priority_is_preserved_among_equally_untried_queries(self):
        policy = VerificationPolicy(
            required_fields=("organizer", "eligibility", "registration_fee", "contacts"),
            requirement_reasons={"contacts": ("用户明确要求核查",)},
        )
        result = run_adaptive_search(candidate(), lambda *_: SearchBatch(cost=0), policy=policy)
        queried = [event.query.field for event in result.events]
        self.assertEqual(queried[:4], ["contacts", "organizer", "eligibility", "registration_fee"])
        self.assertEqual(result.calls, 6)
        self.assertEqual(result.stop_reason, "max_calls")

    def test_fairness_does_not_raise_the_default_or_explicit_budget(self):
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(cost=0),
            budget=SearchBudget(max_rounds=2, max_calls=4, max_queries_per_round=3),
        )
        self.assertEqual(result.calls, 4)
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.stop_reason, "max_calls")

    def test_no_progress_still_stops_when_all_executable_queries_were_tried(self):
        policy = VerificationPolicy(required_fields=("organizer", "eligibility"))
        result = run_adaptive_search(candidate(), lambda *_: SearchBatch(cost=0), policy=policy)
        self.assertEqual(result.stop_reason, "no_new_evidence")
        self.assertEqual((result.calls, result.rounds), (2, 1))

    def test_retries_remain_possible_after_every_query_had_a_turn(self):
        calls = []

        def search(query, _):
            calls.append(query.text)
            return SearchBatch(
                evidence=[reviewed("organizer", "Example University")] if len(calls) == 2 else [],
                cost=0,
            )

        result = run_adaptive_search(
            candidate(), search, policy=VerificationPolicy(required_fields=("organizer",)),
            budget=SearchBudget(max_no_progress_rounds=2),
        )
        self.assertEqual(result.stop_reason, "complete")
        self.assertEqual(result.calls, 2)
        self.assertEqual(calls[0], calls[1])

    def test_planner_emits_only_explicit_search_actions(self):
        policy = VerificationPolicy(required_fields=(
            "organizer", "eligibility", "registration_fee", "contacts", "registration_url",
        ))
        current = candidate()
        verification = verify_competition(current, policy)
        for name, action in (
            ("organizer", "human_review"), ("eligibility", "fetch_source"),
            ("registration_fee", "repair_extraction"), ("contacts", "clarify_context"),
        ):
            verification.fields[name].next_action = action
        queries = plan_queries(current, verification)
        self.assertEqual([item.field for item in queries], ["registration_url"])

    def test_all_unresolved_handoff_actions_stop_without_invoking_search(self):
        for action in ("human_review", "fetch_source", "repair_extraction", "clarify_context"):
            with self.subTest(action=action):
                current = candidate()
                policy = VerificationPolicy(required_fields=("organizer",))
                verification = verify_competition(current, policy)
                verification.fields["organizer"].next_action = action

                def fail(*_):
                    self.fail("A non-search next action cannot invoke the search adapter")

                with patch("b_app.adaptive_search.verify_competition", return_value=verification):
                    result = run_adaptive_search(current, fail, policy=policy)
                self.assertEqual(result.stop_reason, "handoff_required")
                self.assertEqual((result.calls, result.rounds), (0, 0))
                self.assertEqual(result.events, [])

    def test_one_blocked_field_does_not_prevent_other_fields_from_being_searched(self):
        policy = VerificationPolicy(required_fields=("organizer", "eligibility"))

        def routed_verify(current, rules):
            verification = verify_competition(current, rules)
            verification.fields["organizer"].next_action = "human_review"
            return verification

        queried = []

        def search(query, _):
            queried.append(query.field)
            return SearchBatch(evidence=[reviewed("eligibility", "Enrolled undergraduates")], cost=0)

        with patch("b_app.adaptive_search.verify_competition", side_effect=routed_verify):
            result = run_adaptive_search(candidate(), search, policy=policy)
        self.assertEqual(queried, ["eligibility"])
        self.assertEqual(result.stop_reason, "handoff_required")
        self.assertEqual(result.verification.fields["eligibility"].status, "verified")

    def test_a_returned_review_task_stops_after_the_current_callback(self):
        current = candidate()
        policy = VerificationPolicy(required_fields=("organizer",))
        before = verify_competition(current, policy)
        after = verify_competition(current, policy)
        after.fields["organizer"].next_action = "human_review"
        with patch("b_app.adaptive_search.verify_competition", side_effect=[before, after]):
            result = run_adaptive_search(current, lambda *_: SearchBatch(cost=0), policy=policy)
        self.assertEqual(result.calls, 1)
        self.assertEqual(result.stop_reason, "handoff_required")

    def test_multifield_event_identifies_improvements_even_while_overall_pending(self):
        policy = VerificationPolicy(required_fields=("organizer", "eligibility", "registration_fee"))
        records = [
            reviewed("eligibility", "Enrolled undergraduates"),
            reviewed("registration_fee", "100 CNY per team"),
        ]
        result = run_adaptive_search(
            candidate(), lambda *_: SearchBatch(evidence=records, cost=0), policy=policy,
        )
        event = result.events[0]
        self.assertEqual(event.query.field, "organizer")
        self.assertEqual((event.before_status, event.after_status), ("pending", "pending"))
        self.assertEqual(event.newly_verified_fields, ["eligibility", "registration_fee"])
        self.assertEqual(event.coverage_before, 0)
        self.assertAlmostEqual(event.coverage_after, 2 / 3)
        self.assertEqual(event.new_valid_evidence_count, 2)

    def test_newly_resolved_fields_are_removed_from_subsequent_queries(self):
        policy = VerificationPolicy(required_fields=("organizer", "eligibility", "registration_fee"))
        queried = []

        def search(query, _):
            queried.append(query.field)
            return SearchBatch(evidence=[reviewed("eligibility", "Enrolled undergraduates")], cost=0)

        result = run_adaptive_search(candidate(), search, policy=policy)
        self.assertNotIn("eligibility", queried)
        self.assertEqual(result.verification.fields["eligibility"].status, "verified")

