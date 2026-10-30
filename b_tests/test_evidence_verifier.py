"""Legacy three-field regression checks; all contests are fictional.

The student profile remains the production default. Historical fixtures opt
into legacy_minimal explicitly so their original behavioral assertions survive.
"""

import copy
import unittest
from dataclasses import replace

from b_app.b_contracts import Competition, Evidence, VerificationPolicy
from b_app.evidence_verifier import verify_competition as _verify_competition
from b_app.field_catalog import LEGACY_MINIMAL_FIELDS as REQUIRED_FIELDS, build_policy


def verify_competition(competition, policy=None):
    if policy is None:
        policy = build_policy(profile="legacy_minimal")
    return _verify_competition(competition, policy)


VALUES = {
    "registration_deadline": "2026-10-31",
    "eligibility": "全国普通高校在读本科生均可参加。",
    "registration_url": "https://contest.example.invalid/register",
}


def evidence(field="registration_deadline", value=None, **changes):
    item = Evidence(
        id=f"official-{field}",
        field=field,
        value=VALUES[field] if value is None else value,
        url="https://contest.example.invalid/2026/notice",
        quote=f"虚构测试赛事 2026 届：{VALUES[field] if value is None else value}",
        edition="2026",
        source_type="official",
        source_verified=True,
        support="supported",
        reviewed_by="human:fixture-reviewer",
        scope="global",
    )
    return replace(item, **changes)


def competition(items=(), **changes):
    item = Competition(
        id="fictional-contest-2026",
        name="虚构大学生创新赛",
        edition="2026",
        fields=dict(VALUES),
        evidence=list(items),
    )
    return replace(item, **changes)


def all_evidence():
    return [evidence(field) for field in REQUIRED_FIELDS]


class EvidenceVerifierTests(unittest.TestCase):
    def test_complete_reviewed_evidence_verifies_every_required_field(self):
        result = verify_competition(competition(all_evidence()))

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.coverage, 1.0)
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.unresolved_fields, [])
        self.assertEqual(result.verified_fields, VALUES)

    def test_nonempty_original_fields_without_evidence_stay_pending(self):
        result = verify_competition(competition())

        self.assertEqual(result.status, "pending")
        self.assertEqual(result.coverage, 0.0)
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.unresolved_fields, list(REQUIRED_FIELDS))
        self.assertEqual(result.verified_fields, {})
        for check in result.fields.values():
            self.assertIsNone(check.verified_value)
            self.assertTrue(check.reasons)

    def test_original_missing_and_unresolved_are_different(self):
        fields = dict(VALUES, registration_deadline=None)
        result = verify_competition(competition(all_evidence(), fields=fields))

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.missing_fields, ["registration_deadline"])
        self.assertEqual(result.unresolved_fields, [])
        self.assertIsNone(result.fields["registration_deadline"].original_value)
        self.assertEqual(result.verified_fields["registration_deadline"], "2026-10-31")

    def test_original_unsubstantiated_guess_is_preserved_but_not_promoted(self):
        fields = dict(VALUES, registration_deadline="2026-11-30")
        result = verify_competition(competition(all_evidence(), fields=fields))

        check = result.fields["registration_deadline"]
        self.assertEqual(check.status, "verified")
        self.assertEqual(check.original_value, "2026-11-30")
        self.assertEqual(check.verified_value, "2026-10-31")

    def test_missing_deadline_remains_missing_when_no_reliable_claim_exists(self):
        fields = dict(VALUES, registration_deadline=None)
        items = [evidence(field) for field in REQUIRED_FIELDS if field != "registration_deadline"]
        result = verify_competition(competition(items, fields=fields))

        self.assertEqual(result.status, "pending")
        self.assertEqual(result.missing_fields, ["registration_deadline"])
        self.assertEqual(result.unresolved_fields, ["registration_deadline"])
        self.assertAlmostEqual(result.coverage, 2 / 3)
        self.assertIsNone(result.fields["registration_deadline"].verified_value)

    def test_metadata_rejections_are_explained_and_do_not_verify(self):
        variants = [
            {"url": ""},
            {"url": "https://"},
            {"url": "file:///tmp/notice.html"},
            {"quote": "   "},
            {"edition": "2025"},
            {"edition": ""},
            {"scope": "campus:某大学"},
            {"source_type": "unknown"},
            {"source_verified": False},
            {"source_verified": 1},
            {"support": "unknown"},
            {"support": "unsupported"},
            {"reviewed_by": None},
            {"reviewed_by": "  "},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                item = evidence(**changes)
                result = verify_competition(competition([item]))
                check = result.fields["registration_deadline"]
                self.assertEqual(check.status, "pending")
                self.assertIsNone(check.verified_value)
                self.assertTrue(check.rejected_evidence.get(item.id))

    def test_invalid_or_ambiguous_deadline_is_not_verified(self):
        values = [
            "2026-02-30", "2026-1-1", "20261031", "10月31日", "待确认",
            "2026-10-31T18:00:00", "2026-10-31T99:00:00+08:00",
            "2026-10-31T18:00:00+08:00junk",
        ]
        for value in values:
            with self.subTest(value=value):
                item = evidence(value=value)
                check = verify_competition(competition([item])).fields["registration_deadline"]
                self.assertEqual(check.status, "pending")
                self.assertIsNone(check.verified_value)
                self.assertTrue(check.rejected_evidence.get(item.id))

    def test_equivalent_timezone_timestamps_are_not_a_conflict(self):
        items = [
            evidence(value="2026-10-31T10:00:00+08:00", id="deadline-cn"),
            evidence(value="2026-10-31T02:00:00Z", id="deadline-utc"),
        ]
        check = verify_competition(competition(items)).fields["registration_deadline"]

        self.assertEqual(check.status, "verified")
        self.assertIsNotNone(check.verified_value)
        self.assertEqual(check.conflicting_values, [])

    def test_date_only_and_timestamp_are_not_silently_equated(self):
        items = [
            evidence(value="2026-10-31", id="date"),
            evidence(value="2026-10-31T23:59:00+08:00", id="timestamp"),
        ]
        check = verify_competition(competition(items)).fields["registration_deadline"]

        self.assertEqual(check.status, "conflict")
        self.assertIsNone(check.verified_value)

    def test_invalid_registration_link_or_empty_eligibility_is_not_verified(self):
        cases = [
            ("registration_url", "not-a-url"),
            ("registration_url", "javascript:alert(1)"),
            ("registration_url", "https://"),
            ("eligibility", ""),
            ("eligibility", "   "),
            ("eligibility", "待确认"),
            ("eligibility", "unknown"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                item = evidence(field, value)
                check = verify_competition(competition([item])).fields[field]
                self.assertEqual(check.status, "pending")
                self.assertIsNone(check.verified_value)

    def test_school_or_third_party_alone_cannot_verify_by_default(self):
        for source_type in ("school", "third_party"):
            with self.subTest(source_type=source_type):
                check = verify_competition(competition([
                    evidence(source_type=source_type),
                ])).fields["registration_deadline"]
                self.assertEqual(check.status, "pending")
                self.assertIsNone(check.verified_value)

    def test_policy_can_allow_school_evidence(self):
        policy = VerificationPolicy(
            required_fields=REQUIRED_FIELDS, accepted_source_types=("official", "school"),
        )
        result = verify_competition(competition([
            evidence(field, source_type="school") for field in REQUIRED_FIELDS
        ]), policy)

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.coverage, 1.0)

    def test_trusted_same_scope_school_contradiction_blocks_official_claim(self):
        items = all_evidence() + [evidence(
            value="2026-11-01", id="school-contradiction", source_type="school",
        )]
        result = verify_competition(competition(items))
        check = result.fields["registration_deadline"]

        self.assertEqual(result.status, "conflict")
        self.assertEqual(check.status, "conflict")
        self.assertIsNone(check.verified_value)
        self.assertEqual(set(check.conflicting_values), {"2026-10-31", "2026-11-01"})
        self.assertIn("school-contradiction", check.evidence_ids)
        self.assertNotIn("registration_deadline", result.verified_fields)

    def test_old_edition_other_scope_and_third_party_do_not_create_false_conflicts(self):
        variants = [
            {"edition": "2025"},
            {"scope": "campus:某大学", "source_type": "school"},
            {"source_type": "third_party"},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                item = evidence(value="2026-11-01", id="unusable-contradiction", **changes)
                result = verify_competition(competition(all_evidence() + [item]))
                self.assertEqual(result.status, "verified")
                self.assertEqual(result.verified_fields["registration_deadline"], "2026-10-31")

    def test_official_conflicts_preserve_both_claims_regardless_of_order(self):
        items = all_evidence() + [evidence(value="2026-11-01", id="second-official")]
        for sequence in (items, list(reversed(items))):
            with self.subTest(order=[item.id for item in sequence]):
                result = verify_competition(competition(sequence))
                check = result.fields["registration_deadline"]
                self.assertEqual(result.status, "conflict")
                self.assertEqual(set(check.conflicting_values), {"2026-10-31", "2026-11-01"})
                self.assertIsNone(check.verified_value)
                self.assertAlmostEqual(result.coverage, 2 / 3)

    def test_independent_agreeing_sources_do_not_create_conflicts_or_extra_coverage(self):
        items = all_evidence() + [evidence(id="second-agreeing-source")]
        result = verify_competition(competition(items))

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.coverage, 1.0)
        self.assertEqual(result.fields["registration_deadline"].conflicting_values, [])

    def test_duplicate_evidence_ids_cannot_silently_verify(self):
        for second_value in ("2026-10-31", "2026-11-01"):
            with self.subTest(second_value=second_value):
                items = all_evidence() + [evidence(value=second_value)]
                check = verify_competition(competition(items)).fields["registration_deadline"]
                self.assertNotEqual(check.status, "verified")
                self.assertIsNone(check.verified_value)
                self.assertTrue(check.reasons or check.rejected_evidence)

    def test_unique_extra_evidence_does_not_hide_an_id_collision_in_same_field(self):
        items = all_evidence() + [
            evidence(value="2026-11-01"),
            evidence(id="third-clean-reference"),
        ]
        check = verify_competition(competition(items)).fields["registration_deadline"]

        self.assertNotEqual(check.status, "verified")
        self.assertIsNone(check.verified_value)
        self.assertTrue(check.rejected_evidence)

    def test_unknown_target_and_evidence_edition_cannot_verify_each_other(self):
        for edition in ("", "unknown", "待确认"):
            with self.subTest(edition=edition):
                items = [replace(item, edition=edition) for item in all_evidence()]
                result = verify_competition(competition(items, edition=edition))

                self.assertEqual(result.status, "pending")
                self.assertEqual(result.coverage, 0.0)
                self.assertEqual(result.verified_fields, {})

    def test_future_edition_is_compared_to_candidate_not_wall_clock_year(self):
        items = [replace(item, edition="2030") for item in all_evidence()]
        items[0] = replace(items[0], value="2030-10-31", quote="2030 届截止日期为 2030-10-31。")
        result = verify_competition(competition(items, edition="2030"))

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.verified_fields["registration_deadline"], "2030-10-31")

    def test_past_deadline_can_be_verified_without_claiming_user_is_eligible(self):
        item = evidence(value="2020-10-31", edition="2020")
        result = verify_competition(competition([item], edition="2020"))

        self.assertEqual(result.fields["registration_deadline"].status, "verified")
        self.assertEqual(result.fields["registration_deadline"].verified_value, "2020-10-31")

    def test_custom_required_fields_determine_order_and_coverage(self):
        policy = VerificationPolicy(
            required_fields=("eligibility", "registration_deadline"), inspect_optional=False,
        )
        result = verify_competition(competition([evidence("eligibility")]), policy)

        self.assertEqual(list(result.fields), ["eligibility", "registration_deadline"])
        self.assertEqual(result.unresolved_fields, ["registration_deadline"])
        self.assertEqual(result.coverage, 0.5)

    def test_verifier_does_not_mutate_candidate_or_evidence(self):
        candidate = competition(all_evidence())
        original = copy.deepcopy(candidate)

        verify_competition(candidate)

        self.assertEqual(candidate, original)


if __name__ == "__main__":
    unittest.main()
