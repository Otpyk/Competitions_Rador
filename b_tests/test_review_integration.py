"""Legacy three-field C -> B review and CLI regression checks."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

from b_app.b_io import review_bundle_from_dict
from b_app.evidence_verifier import verify_competition as _verify_competition
from b_app.field_catalog import build_policy
from b_app.source_review import review_competition

ROOT = Path(__file__).resolve().parents[1]


def verify_competition(competition, policy=None):
    if policy is None:
        policy = build_policy(profile="legacy_minimal")
    return _verify_competition(competition, policy)


class ReviewIntegrationTests(unittest.TestCase):
    def test_raw_bundle_is_reviewed_by_b_without_c_supplying_pass_flags(self):
        raw = json.loads((ROOT / "examples/review_bundle.json").read_text(encoding="utf-8"))
        candidate, approvals, snapshots = review_bundle_from_dict(raw)
        self.assertTrue(all(not item.source_verified for item in candidate.evidence))
        reviewed, reviews = review_competition(candidate, approved_sources=approvals, snapshots=snapshots)
        outcome = verify_competition(reviewed)
        self.assertEqual(outcome.unresolved_fields, ["registration_deadline"])
        self.assertTrue(all(item.evidence.support == "supported" for item in reviews))
        self.assertTrue(all(not item.source_verified for item in candidate.evidence))

    def test_raw_input_cannot_self_assert_trust_without_b_approvals(self):
        # This fixture has synthetic pass flags. The default B review must clear
        # them when no approved pages or actual snapshots have been supplied.
        raw = json.loads((ROOT / "examples/input_missing_deadline.json").read_text(encoding="utf-8"))
        candidate, approvals, snapshots = review_bundle_from_dict(raw)
        reviewed, _ = review_competition(candidate, approved_sources=approvals, snapshots=snapshots)
        outcome = verify_competition(reviewed)
        self.assertEqual(outcome.coverage, 0.0)
        self.assertEqual(outcome.verified_fields, {})

    def test_cli_bundle_generates_one_executable_deadline_request(self):
        process = subprocess.run(
            [sys.executable, "-m", "b_app.cli", "examples/review_bundle.json", "--profile", "legacy_minimal"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output["review_mode"], "conservative_literal_rules")
        self.assertEqual(len(output["requests"]), 1)
        request = output["requests"][0]
        self.assertEqual(request["action"], "search")
        self.assertEqual(request["target_fields"], ["registration_deadline"])
        self.assertIn("2026", request["query"])
        self.assertIn("报名截止", request["query"])

    def test_cli_default_does_not_trust_synthetic_pass_flags(self):
        process = subprocess.run(
            [sys.executable, "-m", "b_app.cli", "examples/input_missing_deadline.json", "--profile", "legacy_minimal"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output["verification"]["coverage"], 0.0)

    def test_explicit_trusted_history_mode_keeps_existing_manual_fixture_supported(self):
        process = subprocess.run(
            [sys.executable, "-m", "b_app.cli", "examples/input_missing_deadline.json", "--pre-reviewed", "--profile", "legacy_minimal"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output["review_mode"], "trusted_pre_reviewed")
        self.assertEqual(output["verification"]["unresolved_fields"], ["registration_deadline"])

    def test_approval_configuration_rejects_wrong_types(self):
        raw = json.loads((ROOT / "examples/review_bundle.json").read_text(encoding="utf-8"))
        raw["approved_sources"][0]["edition"] = 2026
        with self.assertRaises(ValueError):
            review_bundle_from_dict(raw)


if __name__ == "__main__":
    unittest.main()
