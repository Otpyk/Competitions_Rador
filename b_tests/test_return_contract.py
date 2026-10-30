"""Independent receiving checks using synthetic candidates and deliberate damage."""

from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest

from b_app.b_contracts import Competition, Evidence, VerificationPolicy
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import NOT_APPLICABLE_STATEMENTS
from b_app.query_planner import plan_queries
from b_app.return_contract import build_return, validate_return, SCHEMA_PATH
from b_app.source_review import ReviewResult


def claim(field, value, evidence_id="e1", **changes):
    base = Evidence(evidence_id, field, value, "https://contest.example.invalid/notice",
                    "虚构人工审查原文：" + value, "2026", source_type="official",
                    source_verified=True, support="supported", reviewed_by="B:synthetic-test")
    return replace(base, **changes)


def emit(candidate, required=("registration_deadline",)):
    result = verify_competition(candidate, VerificationPolicy(required_fields=required))
    reviews = [ReviewResult(item, list(item.review_reasons) or ["synthetic_test_review"]) for item in candidate.evidence]
    return build_return(candidate, result, reviews, plan_queries(candidate, result),
                        data_kind="synthetic_test", notice="虚构接口测试，不是真实竞赛证据。")


def protocol_fixtures():
    """Reusable C interoperability fixtures, all explicitly synthetic.

    Each entry contains a raw candidate and its full B return. Incoming trust
    flags are cleared: only the separate B source_reviews carry the test review.
    """
    base = Competition("fixture", "虚构比赛", "2026",
                       fields={"registration_deadline": "2026-11-15"},
                       evidence=[claim("registration_deadline", "2026-11-15")])
    variants = {"verified": (base, ("registration_deadline",))}
    for support in ("unknown", "unsupported"):
        candidate = deepcopy(base)
        candidate.evidence = [replace(candidate.evidence[0], support=support,
                                       source_verified=support == "unsupported",
                                       review_reasons=("source_not_approved" if support == "unknown" else "claim_value_mismatch",))]
        variants[support] = (candidate, ("registration_deadline",))
    conflict = deepcopy(base)
    conflict.evidence.append(claim("registration_deadline", "2026-11-16", "e2"))
    variants["conflict"] = (conflict, ("registration_deadline",))
    statement = next(iter(NOT_APPLICABLE_STATEMENTS["venue"]))
    variants["not_applicable"] = (Competition("fixture", "虚构比赛", "2026", fields={"venue": None},
                                             evidence=[claim("venue", statement, value_kind="not_applicable")]), ("venue",))
    cross = deepcopy(base)
    cross.fields["registration_start"] = "2026-11-16"
    cross.evidence.append(claim("registration_start", "2026-11-16", "e2"))
    variants["cross_field_conflict"] = (cross, ("registration_start", "registration_deadline"))
    unknown = deepcopy(base)
    unknown.fields["unagreed_field"] = "等待双方对齐"
    variants["unrecognized_field"] = (unknown, ("registration_deadline",))
    result = {}
    for name, (candidate, required) in variants.items():
        payload = emit(candidate, required)
        raw = deepcopy(candidate)
        raw.evidence = [replace(item, source_verified=False, support="unknown", reviewed_by=None, review_reasons=())
                        for item in candidate.evidence]
        result[name] = {"candidate": asdict(raw), "b_return": payload}
    return result


class ReturnContractTests(unittest.TestCase):
    def setUp(self):
        self.candidate = Competition("fixture", "虚构比赛", "2026",
                                     fields={"registration_deadline": "2026-11-15"},
                                     evidence=[claim("registration_deadline", "2026-11-15")])

    def assert_rejected(self, mutate, candidate=None):
        candidate = candidate or self.candidate
        payload = emit(candidate)
        mutate(payload)
        with self.assertRaises(ValueError):
            validate_return(payload, candidate)

    def test_verified_roundtrip_preserves_full_payload_without_mutation(self):
        payload = emit(self.candidate)
        before = deepcopy(payload)
        receipt = validate_return(json.loads(json.dumps(payload)), asdict(self.candidate))
        self.assertTrue(receipt["accepted"])
        self.assertTrue(receipt["candidate_links_checked"])
        self.assertEqual(receipt["contract_version"], "b-c-return-v1")
        self.assertEqual(receipt["received_payload"], payload)
        receipt["received_payload"]["notice"] = "receiver-local edit"
        self.assertEqual(payload, before)
        self.assertEqual(set(payload), {"data_kind", "notice", "verification", "requests", "source_reviews"})

    def test_pending_unknown_and_unsupported_reviews_preserved(self):
        self.candidate.evidence = [replace(self.candidate.evidence[0], support="unknown", source_verified=False,
                                           review_reasons=("source_not_approved",)),
                                   claim("registration_deadline", "2026-11-15", "e2", support="unsupported",
                                         review_reasons=("claim_value_mismatch",))]
        payload = emit(self.candidate)
        receipt = validate_return(payload, self.candidate)
        self.assertEqual(receipt["status"], "pending")
        self.assertEqual(receipt["source_review_count"], 2)
        self.assertEqual(receipt["rejected_evidence_count"], 2)
        self.assertEqual({x["support"] for x in payload["source_reviews"]}, {"unknown", "unsupported"})
        self.assertIn("claim_value_mismatch", payload["verification"]["fields"]["registration_deadline"]["rejected_evidence"]["e2"])

    def test_null_candidate_can_be_recovered_from_reviewed_evidence(self):
        self.candidate.fields["registration_deadline"] = None
        payload = emit(self.candidate)
        check = payload["verification"]["fields"]["registration_deadline"]
        self.assertIsNone(check["original_value"])
        self.assertEqual(check["verified_value"], "2026-11-15")
        self.assertEqual(payload["verification"]["missing_fields"], ["registration_deadline"])
        validate_return(payload, self.candidate)

    def test_corrected_candidate_and_normalized_timezone_remain_supported(self):
        self.candidate.fields["registration_deadline"] = "2026-11-14"
        self.candidate.evidence = [claim("registration_deadline", "2026-11-15T08:00:00+08:00")]
        payload = emit(self.candidate)
        self.assertEqual(payload["verification"]["verified_fields"]["registration_deadline"], "2026-11-15T00:00:00+00:00")
        self.assertEqual(payload["verification"]["fields"]["registration_deadline"]["original_value"], "2026-11-14")

    def test_not_applicable_roundtrip(self):
        statement = next(iter(NOT_APPLICABLE_STATEMENTS["venue"]))
        candidate = Competition("fixture", "虚构比赛", "2026", fields={"venue": None},
                                evidence=[claim("venue", statement, value_kind="not_applicable")])
        payload = emit(candidate, ("venue",))
        self.assertEqual(payload["verification"]["not_applicable_fields"], {"venue": statement})
        self.assertEqual(payload["verification"]["verified_fields"], {})
        validate_return(payload, candidate)

    def test_conflicting_sources_roundtrip_preserves_both_claims(self):
        self.candidate.evidence.append(claim("registration_deadline", "2026-11-16", "e2"))
        payload = emit(self.candidate)
        self.assertEqual(payload["verification"]["status"], "conflict")
        self.assertEqual(payload["verification"]["fields"]["registration_deadline"]["conflicting_values"], ["2026-11-15", "2026-11-16"])
        self.assertEqual(len(payload["requests"]), 1)
        validate_return(payload, self.candidate)

    def test_cross_field_conflict_roundtrip_and_nonempty_diagnostics(self):
        self.candidate.fields["registration_start"] = "2026-11-16"
        self.candidate.evidence.append(claim("registration_start", "2026-11-16", "e2"))
        payload = emit(self.candidate, ("registration_start", "registration_deadline"))
        receipt = validate_return(payload, self.candidate)
        self.assertEqual(receipt["consistency_issue_count"], 1)
        issue = payload["verification"]["consistency_issues"][0]
        self.assertEqual(issue["values"], {"registration_start": "2026-11-16", "registration_deadline": "2026-11-15"})
        broken = deepcopy(payload)
        broken["verification"]["consistency_issues"][0]["values"]["registration_start"] = "2026-12-31"
        with self.assertRaises(ValueError):
            validate_return(broken, self.candidate)

    def test_unknown_field_diagnostic_is_retained(self):
        self.candidate.fields["unagreed_field"] = "保留，等待双方对齐"
        payload = emit(self.candidate)
        self.assertEqual(payload["verification"]["unrecognized_fields"], ["unagreed_field"])
        validate_return(payload, self.candidate)
        payload["verification"]["unrecognized_fields"] = []
        with self.assertRaises(ValueError):
            validate_return(payload, self.candidate)

    def test_populated_optional_field_cannot_be_silently_removed(self):
        self.candidate.fields["awards"] = "一等奖3队。"
        self.candidate.evidence.append(claim("awards", "一等奖3队。", "award", support="unknown"))
        payload = emit(self.candidate)
        del payload["verification"]["fields"]["awards"]
        payload["verification"]["optional_unresolved_fields"] = []
        with self.assertRaises(ValueError):
            validate_return(payload, self.candidate)

    def test_optional_rejection_diagnostic_cannot_be_silently_removed(self):
        self.candidate.fields["awards"] = "一等奖3队。"
        self.candidate.evidence.append(claim("awards", "一等奖3队。", "award", support="unknown"))
        payload = emit(self.candidate)
        payload["verification"]["fields"]["awards"]["rejected_evidence"] = {}
        with self.assertRaises(ValueError):
            validate_return(payload, self.candidate)

    def test_verified_evidence_cannot_also_be_rejected(self):
        self.assert_rejected(lambda p: p["verification"]["fields"]["registration_deadline"].update(
            rejected_evidence={"e1": ["direct_support_not_confirmed"]}))

    def test_conflict_may_include_school_evidence_insufficient_to_verify_alone(self):
        self.candidate.evidence.append(claim("registration_deadline", "2026-11-16", "e2", source_type="school"))
        payload = emit(self.candidate)
        check = payload["verification"]["fields"]["registration_deadline"]
        self.assertEqual(check["status"], "conflict")
        self.assertIn("e2", check["evidence_ids"])
        self.assertIn("insufficient_source_type", check["rejected_evidence"]["e2"])
        validate_return(payload, self.candidate)

    def test_no_candidate_receipt_discloses_limited_check(self):
        self.assertFalse(validate_return(emit(self.candidate))["candidate_links_checked"])

    def test_receiver_accepts_reordered_json_object_keys(self):
        self.candidate.fields["eligibility"] = None
        payload = emit(self.candidate, ("registration_deadline", "eligibility"))
        reordered = json.loads(json.dumps(payload, sort_keys=True))
        self.assertTrue(validate_return(reordered, self.candidate)["accepted"])

    def test_rejects_false_summary_and_unknown_root_key(self):
        mutations = [lambda p: p.update(contract_version="invented"),
                     lambda p: p["verification"].update(coverage=0),
                     lambda p: p["verification"].update(status="pending"),
                     lambda p: p["verification"].update(verified_fields={}),
                     lambda p: p["verification"].update(required_fields=[]),
                     lambda p: p["verification"].update(missing_fields=["registration_deadline"]),
                     lambda p: p["verification"].update(verified_at="2026-10-22T12:00:00")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_rejected(mutate)

    def test_rejects_missing_duplicate_or_foreign_source_reviews(self):
        for mutate in [lambda p: p.update(source_reviews=[]),
                       lambda p: p["source_reviews"].append(deepcopy(p["source_reviews"][0])),
                       lambda p: p["source_reviews"][0].update(evidence_id="foreign")]:
            with self.subTest(mutate=mutate):
                self.assert_rejected(mutate)

    def test_rejects_unreviewed_verified_evidence(self):
        self.assert_rejected(lambda p: p["source_reviews"][0].update(source_verified=False))
        self.assert_rejected(lambda p: p["source_reviews"][0].update(support="unknown"))

    def test_rejects_types_and_loose_diagnostics(self):
        mutations = [lambda p: p["source_reviews"][0].update(source_verified="true"),
                     lambda p: p["verification"].update(coverage=True),
                     lambda p: p["verification"].update(coverage=float("nan")),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(rejected_evidence={"e1": "bad"}),
                     lambda p: p["verification"].update(unrecognized_fields=[1]),
                     lambda p: p["verification"].update(consistency_issues=[{}])]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_rejected(mutate)

    def test_rejects_changed_identity_scope_original_and_fabricated_values(self):
        mutations = [lambda p: p["verification"].update(competition_id="other"),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(field="eligibility"),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(scope="campus:别校"),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(original_value=None),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(evidence_ids=["invented"]),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(source_urls=["https://invented.invalid/"]),
                     lambda p: p["verification"]["fields"]["registration_deadline"].update(verified_value="2026-12-31")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_rejected(mutate)

    def test_rejects_field_or_edition_swapped_evidence(self):
        payload = emit(self.candidate)
        for item in [replace(self.candidate.evidence[0], field="eligibility"),
                     replace(self.candidate.evidence[0], edition="2025"),
                     replace(self.candidate.evidence[0], scope="campus:别校")]:
            candidate = deepcopy(self.candidate)
            candidate.evidence = [item]
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_return(payload, candidate)

    def test_rejects_pending_or_conflict_with_filled_verified_value(self):
        for evidence in [[], [claim("registration_deadline", "2026-11-15"), claim("registration_deadline", "2026-11-16", "e2")]]:
            candidate = deepcopy(self.candidate)
            candidate.evidence = evidence
            with self.subTest(evidence=evidence):
                self.assert_rejected(lambda p: p["verification"]["fields"]["registration_deadline"].update(verified_value="2026-11-15"), candidate)

    def test_rejects_bad_query_and_action_links(self):
        candidate = deepcopy(self.candidate)
        candidate.evidence = []
        mutations = [lambda p: p["requests"][0].update(action="fetch_source"),
                     lambda p: p["requests"][0].update(edition="2025"),
                     lambda p: p["requests"][0].update(scope="campus:别校"),
                     lambda p: p["requests"][0].update(target_fields=["eligibility"]),
                     lambda p: p["requests"][0].update(round=True),
                     lambda p: p.update(requests=[]),
                     lambda p: p["verification"].update(action_items=[]),
                     lambda p: p["verification"]["action_items"][0].update(owner="C"),
                     lambda p: p["verification"]["action_items"][0].update(candidate_evidence_refs=[3])]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_rejected(mutate, candidate)

    def test_context_hold_is_allowed_without_rewriting_scope_or_values(self):
        candidate = deepcopy(self.candidate)
        candidate.evidence = []
        result = verify_competition(candidate, VerificationPolicy(required_fields=("registration_deadline",)))
        result.fields["registration_deadline"].next_action = "clarify_context"
        result.fields["registration_deadline"].action_reason = "先确认要查询全国还是本校的截止日期。"
        payload = build_return(candidate, result, [], plan_queries(candidate, result), data_kind="synthetic_test", notice="范围待确认")
        self.assertEqual(payload["requests"], [])
        self.assertEqual(payload["verification"]["action_items"][0]["owner"], "A/C")

    def test_schema_explicitly_covers_all_nonempty_diagnostics(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        defs = schema["$defs"]
        self.assertEqual(defs["SourceReview"]["properties"]["support"]["enum"], ["supported", "unsupported", "unknown"])
        self.assertEqual(defs["FieldDecision"]["properties"]["rejected_evidence"]["additionalProperties"]["items"]["type"], "string")
        self.assertEqual(defs["ActionItem"]["properties"]["candidate_evidence_refs"]["items"]["type"], "string")
        self.assertEqual(defs["Verification"]["properties"]["unrecognized_fields"]["items"]["type"], "string")

    def test_exportable_protocol_fixtures_roundtrip_against_raw_inputs(self):
        fixtures = protocol_fixtures()
        self.assertEqual(len(fixtures), 7)
        for name, fixture in fixtures.items():
            with self.subTest(name=name):
                receipt = validate_return(fixture["b_return"], fixture["candidate"])
                self.assertTrue(receipt["candidate_links_checked"])
                self.assertEqual(fixture["b_return"]["data_kind"], "synthetic_test")
                self.assertTrue(all(not item["source_verified"] for item in fixture["candidate"]["evidence"]))


if __name__ == "__main__":
    unittest.main()
