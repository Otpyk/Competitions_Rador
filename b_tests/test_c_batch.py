"""Transport and trust-boundary tests; fixtures are synthetic, not web research."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from b_app.c_batch import run_batch


class CBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "incoming"
        self.package.mkdir()
        self.output = self.root / "output"
        self.url = "https://contest.example/2026/notice"
        self.quote = "报名截止日期：2026-11-15"
        self.content = self.quote + "\n\n赛事名称：测试赛"
        self.candidate = {
            "id": "test-2026", "name": "测试赛", "edition": "2026", "scope": "global",
            "fields": {
                "registration_deadline": {"value": "2026-11-15", "evidence": [{
                    "id": "deadline-1", "value": "2026-11-15", "url": self.url,
                    "quote": self.quote, "edition": "2026", "scope": "global",
                }]},
                "awards": {"value": None, "evidence": []},
            },
        }
        self.batch = {"task_id": "test", "query": "测试", "sources": [{
            "source_id": "source-1", "url": self.url, "content": self.content,
            "fetched_at": "2026-10-22T10:00:00+08:00",
        }]}
        self.contexts = [{"contest_id": "test-2026", "source_ids": ["source-1"],
                          "context": {"school": "测试大学", "unit": "测试学院", "track": "软件组"}}]
        self.provenance = [{
            "contest_id": "test-2026", "evidence_id": "deadline-1",
            "field": "registration_deadline", "source_id": "source-1", "url": self.url,
            "edition": "2026", "scope": "global", "start_char": 0, "end_char": len(self.quote),
            "content_sha256": hashlib.sha256(self.content.encode()).hexdigest(),
        }]
        self.save()

    def write(self, name, value, *, outside=False):
        path = (self.root if outside else self.package) / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def save(self):
        self.write("c_to_b_contests.json", [self.candidate])
        self.write("research_batch.json", self.batch)
        self.write("candidate_contexts.json", self.contexts)
        self.write("evidence_provenance.json", self.provenance)
        self.write("核验条件_基础22字段.json", {"hard_constraints": [], "extra_required_fields": []})

    def result(self):
        return json.loads((self.output / "results/test-2026.json").read_text(encoding="utf-8"))

    def approval(self, *, outside=True):
        return self.write("b_approvals.json", {"approved_sources": [{
            "competition_id": "test-2026", "edition": "2026", "scope": "global",
            "url": self.url, "source_type": "official", "approved_by": "B-test-reviewer",
        }]}, outside=outside)

    def assert_invalid(self, match):
        with self.assertRaisesRegex(ValueError, match):
            run_batch(self.package, self.output)
        self.assertFalse(self.output.exists())

    def test_default_trust_is_none_and_sidecars_preserve_input(self):
        before = {p.name: p.read_bytes() for p in self.package.iterdir()}
        report = run_batch(self.package, self.output)
        result = self.result()
        self.assertEqual(set(result), {"data_kind", "notice", "verification", "requests", "source_reviews"})
        self.assertEqual(report["data_kind"], "real_candidate_interface_replay")
        self.assertEqual(report["source_approval_mode"], "none")
        self.assertEqual(report["source_verified_count"], 0)
        self.assertFalse(report["c_runtime_executed"])
        self.assertEqual(result["source_reviews"][0]["reasons"], ["source_not_approved"])
        self.assertNotIn("awards", result["verification"]["fields"])
        self.assertEqual(len(result["verification"]["required_fields"]), 22)
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["candidates"][0]["context_record"], self.contexts[0])
        self.assertEqual(manifest["candidates"][0]["provenance_records"], self.provenance)
        for name, content in before.items():
            self.assertEqual((self.package / name).read_bytes(), content)
            self.assertEqual((self.output / "inputs" / name).read_bytes(), content)

    def test_approval_must_be_explicit_external_and_real_review_runs(self):
        report = run_batch(self.package, self.output, self.approval())
        self.assertEqual(report["source_verified_count"], 1)
        check = self.result()["verification"]["fields"]["registration_deadline"]
        self.assertEqual(check["status"], "verified")
        self.assertEqual(check["verified_value"], "2026-11-15")

    def test_incoming_self_certification_cannot_grant_trust(self):
        evidence = self.candidate["fields"]["registration_deadline"]["evidence"][0]
        evidence.update(source_type="official", source_verified=True, support="supported",
                        reviewed_by="C", review_reasons=["C says verified"])
        self.batch["approved_sources"] = [{"url": self.url, "source_type": "official"}]
        self.save()
        report = run_batch(self.package, self.output)
        self.assertEqual(report["source_verified_count"], 0)
        review = self.result()["source_reviews"][0]
        self.assertFalse(review["source_verified"])
        self.assertEqual(review["support"], "unknown")
        self.assertNotIn("C says verified", review["reasons"])

    def test_incoming_approval_file_is_not_b_configuration(self):
        with self.assertRaisesRegex(ValueError, "outside C"):
            run_batch(self.package, self.output, self.approval(outside=False))
        self.assertFalse(self.output.exists())

    def test_demo_requirements_are_not_loaded(self):
        self.write("hard_constraints_demo.json", {"hard_constraints": [], "extra_required_fields": ["awards"]})
        report = run_batch(self.package, self.output)
        self.assertEqual(len(report["required_fields"]), 22)
        self.assertEqual(report["promoted_fields"], [])

    def test_global_query_does_not_inherit_campus_hint(self):
        report = run_batch(self.package, self.output)
        self.assertEqual(report["candidate_count"], 1)
        requests = self.result()["requests"]
        self.assertTrue(requests)
        for request in requests:
            self.assertNotIn("测试大学", request["query"])
            self.assertNotIn("测试学院", request["query"])
            self.assertIn("软件组", request["query"])

    def test_campus_query_preserves_unit_and_stage_hints(self):
        self.candidate["scope"] = "campus:测试大学"
        self.candidate["fields"]["registration_deadline"]["evidence"][0]["scope"] = "campus:测试大学"
        self.provenance[0]["scope"] = "campus:测试大学"
        self.contexts[0]["context"]["stage"] = "院赛"
        self.save()
        run_batch(self.package, self.output)
        requests = self.result()["requests"]
        self.assertTrue(any("测试学院" in r["query"] and "院赛" in r["query"] for r in requests))

    def test_provenance_mismatch_variants_all_fail_before_output(self):
        for field, value, message in [
            ("field", "eligibility", "field mismatch"),
            ("edition", "2025", "edition mismatch"),
            ("scope", "campus:Other", "scope mismatch"),
            ("url", "https://wrong.example/", "URL mismatch"),
            ("source_id", "unknown", "source reference"),
            ("content_sha256", "0" * 64, "SHA256 mismatch"),
            ("start_char", 1, "quote span"),
            ("end_char", True, "quote span"),
        ]:
            with self.subTest(field=field):
                changed = deepcopy(self.provenance)
                changed[0][field] = value
                self.write("evidence_provenance.json", changed)
                self.assert_invalid(message)

    def test_missing_or_duplicate_provenance_is_rejected(self):
        self.write("evidence_provenance.json", [])
        self.assert_invalid("exactly one provenance")
        self.write("evidence_provenance.json", self.provenance * 2)
        self.assert_invalid("duplicate provenance")

    def test_duplicate_candidates_are_rejected(self):
        self.write("c_to_b_contests.json", [self.candidate, self.candidate])
        self.assert_invalid("Duplicate candidate")

    def test_malicious_output_id_is_rejected(self):
        for name in ("../escape", "..\\escape", "CON", "test.", "C:escape", "/root"):
            with self.subTest(name=name):
                bad = deepcopy(self.candidate)
                bad["id"] = name
                self.write("c_to_b_contests.json", [bad])
                self.assert_invalid("Unsafe candidate ID")

    def test_duplicate_source_id_or_url_is_rejected(self):
        for mode in ("id", "url"):
            with self.subTest(mode=mode):
                extra = deepcopy(self.batch["sources"][0])
                extra["url" if mode == "id" else "source_id"] = "https://other.example/" if mode == "id" else "source-2"
                changed = deepcopy(self.batch)
                changed["sources"].append(extra)
                self.write("research_batch.json", changed)
                self.assert_invalid("Duplicate source")

    def test_context_source_reference_must_cover_evidence(self):
        self.contexts[0]["source_ids"] = []
        self.save()
        self.assert_invalid("source reference")

    def test_referenced_annotations_preserved_with_hashes(self):
        self.contexts[0]["annotation_file"] = "annotations/notes.md"
        annotation = self.package / "annotations/notes.md"
        annotation.parent.mkdir()
        content = "# C标注\n这是校内范围，不自动证明资格。\n".encode("utf-8")
        annotation.write_bytes(content)
        self.save()
        run_batch(self.package, self.output)
        self.assertEqual((self.output / "inputs/annotations/notes.md").read_bytes(), content)
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["input_annotations"][0]["sha256"], hashlib.sha256(content).hexdigest())

    def test_missing_or_escaping_annotation_rejected_before_output(self):
        for reference, message in (("annotations/missing.md", "Missing"), ("../outside.md", "Unsafe")):
            with self.subTest(reference=reference):
                self.contexts[0]["annotation_file"] = reference
                self.save()
                self.assert_invalid(message)

    def test_output_inside_package_or_existing_output_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            run_batch(self.package, self.package / "out")
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("do not replace")
        with self.assertRaisesRegex(ValueError, "already exists"):
            run_batch(self.package, self.output)
        self.assertEqual(sentinel.read_text(), "do not replace")

    def test_hold_routes_ambiguity_without_changing_scope_or_value(self):
        # This holds an evidence-free field that would otherwise produce a search.
        self.candidate["fields"]["organizer"] = {"value": None, "evidence": []}
        self.save()
        holds = [{"competition_id": "test-2026", "field": "organizer", "reason": "先确认全国还是校内主办方"}]
        path = self.write("holds.json", holds, outside=True)
        report = run_batch(self.package, self.output, context_holds_path=path)
        self.assertEqual(report["context_hold_count"], 1)
        result = self.result()
        check = result["verification"]["fields"]["organizer"]
        self.assertEqual(check["next_action"], "clarify_context")
        self.assertEqual(check["scope"], "global")
        self.assertEqual(check["status"], "pending")
        self.assertIsNone(check["original_value"])
        self.assertFalse(any("organizer" in request["target_fields"] for request in result["requests"]))
        self.assertEqual((self.output / "inputs/b_context_holds.json").read_bytes(), path.read_bytes())

    def test_hold_cannot_silently_downgrade_verified_field(self):
        path = self.write("holds.json", {"context_holds": [{
            "competition_id": "test-2026", "field": "registration_deadline", "reason": "review scope",
        }]}, outside=True)
        with self.assertRaisesRegex(ValueError, "unresolved field"):
            run_batch(self.package, self.output, self.approval(), path)
        self.assertFalse(self.output.exists())

    def test_cli_produces_parseable_report(self):
        proc = subprocess.run([sys.executable, "-m", "b_app.c_batch_cli", str(self.package),
                               "--output-dir", str(self.output)], capture_output=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["contract_checks_passed"], 1)


if __name__ == "__main__":
    unittest.main()
