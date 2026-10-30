"""Legacy three-field input and replay regression checks."""

import copy
import json
from pathlib import Path
import unittest

from b_app.b_io import competition_from_dict
from b_app.evidence_verifier import normalized_value, verify_competition as _verify_competition
from b_app.field_catalog import build_policy
from examples.run_demo import run_examples


def verify_competition(competition, policy=None):
    if policy is None:
        policy = build_policy(profile="legacy_minimal")
    return _verify_competition(competition, policy)


class IntegrationTests(unittest.TestCase):
    def test_url_normalization_preserves_path_query_and_fragment(self):
        value = "HTTPS://CONTEST.EXAMPLE.INVALID/注册/Ａ?code=Ａ#Ｂ"
        self.assertEqual(normalized_value("registration_url", value),
                         "https://contest.example.invalid/注册/Ａ?code=Ａ#Ｂ")
        self.assertNotEqual(normalized_value("registration_url", "https://contest.example.invalid/?code=Ａ"),
                            normalized_value("registration_url", "https://contest.example.invalid/?code=A"))

    def test_control_characters_in_urls_are_rejected(self):
        for value in ("https://exa\x00mple.invalid/register", "https://example.invalid/\nregister", "https://example.invalid/\t"):
            with self.subTest(value=value):
                self.assertIsNone(normalized_value("url", value))

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "input_missing_deadline.json"
        self.raw = json.loads(path.read_text(encoding="utf-8"))

    def test_field_level_input_produces_only_deadline_gap(self):
        candidate = competition_from_dict(self.raw)
        result = verify_competition(candidate)
        self.assertEqual(result.unresolved_fields, ["registration_deadline"])
        self.assertEqual(result.coverage, 2 / 3)

    def test_incoming_status_cannot_promote_missing_evidence(self):
        self.raw["registration_deadline"]["status"] = "verified"
        self.raw["registration_deadline"]["value"] = "2026-11-10"
        self.raw["verification_status"] = "verified"
        result = verify_competition(competition_from_dict(self.raw))
        self.assertEqual(result.fields["registration_deadline"].status, "pending")

    def test_absent_review_annotations_are_not_invented(self):
        item = self.raw["eligibility"]["evidence"][0]
        for key in ("support", "source_verified", "reviewed_by"):
            item.pop(key)
        result = verify_competition(competition_from_dict(self.raw))
        self.assertEqual(result.fields["eligibility"].status, "pending")

    def test_containing_field_and_claim_field_must_match(self):
        self.raw["eligibility"]["evidence"][0]["field"] = "registration_deadline"
        with self.assertRaisesRegex(ValueError, "does not match"):
            competition_from_dict(self.raw)

    def test_boolean_strings_and_numeric_booleans_are_rejected(self):
        for invalid in ("true", 1, None):
            with self.subTest(invalid=invalid):
                self.raw["eligibility"]["evidence"][0]["source_verified"] = invalid
                with self.assertRaises(ValueError):
                    competition_from_dict(self.raw)

    def test_malformed_metadata_is_rejected_without_traceback(self):
        for update in ({"id": None}, {"edition": 2026}, {"evidence": 42}, {"scope": []}):
            with self.subTest(update=update):
                raw = {**self.raw, **update}
                with self.assertRaises(ValueError):
                    competition_from_dict(raw)

    def test_nested_fields_shape_and_flat_shape_agree(self):
        metadata = {key: self.raw[key] for key in ("id", "name", "edition", "scope")}
        nested = {**metadata, "fields": {key: value for key, value in self.raw.items() if key not in metadata}}
        self.assertEqual(competition_from_dict(nested), competition_from_dict(self.raw))

    def test_top_level_field_mapped_evidence_is_supported(self):
        raw = copy.deepcopy(self.raw)
        records = raw["eligibility"]["evidence"]
        raw["eligibility"] = raw["eligibility"]["value"]
        raw["evidence"] = {"eligibility": records}
        parsed = competition_from_dict(raw)
        original = competition_from_dict(self.raw)
        self.assertEqual(verify_competition(parsed), verify_competition(original))
        self.assertEqual(set(parsed.evidence), set(original.evidence))

    def test_parser_does_not_mutate_source_data(self):
        before = copy.deepcopy(self.raw)
        competition_from_dict(self.raw)
        self.assertEqual(self.raw, before)

    def test_all_offline_acceptance_scenarios_match(self):
        results = run_examples()
        self.assertEqual(results["data_kind"], "synthetic_offline_replay")
        self.assertEqual(len(results["cases"]), 11)
        for case in results["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertTrue(case["matches_expectation"])
        recovered = next(case for case in results["cases"] if case["case_id"] == "missing_then_found")["result"]
        self.assertIsNone(recovered["competition"]["fields"]["registration_deadline"])
        self.assertEqual(recovered["verification"]["verified_fields"]["registration_deadline"], "2026-11-10")


if __name__ == "__main__":
    unittest.main()
