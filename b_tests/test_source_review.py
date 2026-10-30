"""Trust-boundary and literal-content checks using offline source snapshots."""

from copy import deepcopy
from dataclasses import replace
import unittest

from b_app.b_contracts import Competition, Evidence
from b_app.source_review import (
    ApprovedSource, SourceSnapshot, review_competition, review_evidence,
)


URL = "https://example.org/2026/rules?edition=2026"
DEADLINE = "报名截止日期：2026-11-10。"


def evidence(**changes):
    values = dict(
        id="deadline", field="registration_deadline", value="2026-11-10",
        url=URL, quote=DEADLINE, edition="2026",
    )
    values.update(changes)
    return Evidence(**values)


def competition(records=()):
    return Competition(
        id="demo", name="校园 AI 创意赛", edition="2026",
        fields={"registration_deadline": None, "notes": {"tags": ["original"]}},
        evidence=list(records),
    )


def approval(**changes):
    values = dict(
        competition_id="demo", edition="2026", scope="global", url=URL,
        source_type="official", approved_by="B:human-reviewer",
    )
    values.update(changes)
    return ApprovedSource(**values)


class SourceReviewTests(unittest.TestCase):
    def review(self, item=None, text=None, approvals=None, snapshots=None, target=None):
        item = item or evidence()
        return review_evidence(
            target or competition(), item,
            approved_sources=[approval()] if approvals is None else approvals,
            snapshots=(
                [SourceSnapshot(URL, item.quote if text is None else text, "2026-10-22T00:00:00Z")]
                if snapshots is None else snapshots
            ),
        )

    def test_explicit_iso_date_is_supported_after_b_review(self):
        result = self.review()
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "supported")
        self.assertEqual(result.evidence.source_type, "official")
        self.assertEqual(result.evidence.reviewed_by, "literal-v3:B:human-reviewer")
        self.assertEqual(result.evidence.retrieved_at, "2026-10-22T00:00:00Z")

    def test_explicit_chinese_date_is_supported(self):
        result = self.review(evidence(quote="报名截止时间为2026年11月10日。"))
        self.assertEqual(result.evidence.support, "supported")

    def test_c_cannot_self_certify_an_unapproved_source(self):
        forged = evidence(
            source_type="official", source_verified=True, support="supported",
            reviewed_by="C-model", retrieved_at="forged-timestamp",
        )
        result = self.review(forged, approvals=[])
        self.assertFalse(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.evidence.source_type, "unknown")
        self.assertIsNone(result.evidence.reviewed_by)
        self.assertIsNone(result.evidence.retrieved_at)
        self.assertTrue(forged.source_verified)

    def test_input_annotations_are_overwritten_even_for_an_approved_url(self):
        forged = evidence(
            quote="报名详情另行通知。", source_verified=True,
            support="supported", reviewed_by="C-model", source_type="third_party",
        )
        result = self.review(forged)
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.source_type, "official")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertNotEqual(result.evidence.reviewed_by, "C-model")

    def test_source_approval_is_exact_in_competition_edition_scope_and_url(self):
        for changed in (
            approval(competition_id="another-competition"),
            approval(edition="2024"),
            approval(scope="campus:某校"),
            approval(url="https://example.org/2026/other-rules?edition=2026"),
            approval(url="https://example.org/2026/rules?edition=2024"),
            approval(source_type="model_guessed"),
            approval(approved_by=" "),
        ):
            with self.subTest(changed=changed):
                result = self.review(approvals=[changed])
                self.assertFalse(result.evidence.source_verified)
                self.assertEqual(result.evidence.support, "unknown")

    def test_evidence_context_cannot_be_silently_repaired(self):
        for changed in (evidence(edition="2024"), evidence(scope="campus:某校")):
            with self.subTest(changed=changed):
                result = self.review(changed)
                self.assertFalse(result.evidence.source_verified)
                self.assertEqual(result.reasons, ["evidence_context_mismatch"])
                self.assertEqual(result.evidence.edition, changed.edition)
                self.assertEqual(result.evidence.scope, changed.scope)

    def test_missing_snapshot_cannot_verify_a_source(self):
        result = self.review(snapshots=[])
        self.assertFalse(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["source_snapshot_missing"])

    def test_snapshot_at_another_url_cannot_be_used(self):
        result = self.review(snapshots=[SourceSnapshot("https://example.org/other", DEADLINE)])
        self.assertFalse(result.evidence.source_verified)

    def test_quote_absent_from_snapshot_is_unsupported(self):
        result = self.review(text="报名截止日期：2026-11-12。")
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "unsupported")
        self.assertEqual(result.reasons, ["quote_not_found"])

    def test_date_substring_cannot_escape_negation_in_its_paragraph(self):
        for text in (
            "这不是报名截止日期：2026-11-10。",
            "请勿误解：报名截止日期：2026-11-10。这是错误信息。",
        ):
            with self.subTest(text=text):
                result = self.review(text=text)
                self.assertEqual(result.evidence.support, "unknown")
                self.assertEqual(result.reasons, ["quote_not_complete_paragraph"])

    def test_separate_old_notice_warning_blocks_literal_claim(self):
        result = self.review(text=f"以下为往年通知，仅供参考。\n\n{DEADLINE}")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["ambiguous_source_context"])

    def test_full_independent_paragraph_is_allowed_in_multi_paragraph_page(self):
        result = self.review(text=f"2026 年赛事通知\n\n{DEADLINE}\n\n主办方联系方式见官网。")
        self.assertEqual(result.evidence.support, "supported")

    def test_line_wrapping_inside_a_paragraph_is_normalized(self):
        result = self.review(
            evidence(quote="报名截止日期： 2026-11-10。"),
            text="2026 年通知\n\n报名截止日期：\n2026-11-10。\n\n其他说明。",
        )
        self.assertEqual(result.evidence.support, "supported")

    def test_dates_with_ambiguity_negation_or_multiple_dates_are_unknown(self):
        for quote in (
            "报名截止日期暂定为2026-11-10。",
            "报名截止日期不是2026-11-10。",
            "原报名截止日期：2026-11-10。",
            "报名截止日期：2026-11-10或2026-11-11。",
            "报名截止日期：2026-11-10，具体以通知为准。",
            "报名截止时间：2026-11-10T12:00:00+08:00。",
        ):
            with self.subTest(quote=quote):
                self.assertEqual(self.review(evidence(quote=quote)).evidence.support, "unknown")

    def test_invalid_or_different_literal_date_is_unsupported(self):
        for quote in ("报名截止日期：2026-02-30。", "报名截止日期：2026-11-11。"):
            with self.subTest(quote=quote):
                self.assertEqual(self.review(evidence(quote=quote)).evidence.support, "unsupported")

    def test_cross_year_date_requires_human_review(self):
        result = self.review(evidence(value="2025-11-10", quote="报名截止日期：2025-11-10。"))
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["deadline_year_requires_human_review"])

    def test_multiple_explicit_deadlines_in_separate_paragraphs_remain_unknown(self):
        result = self.review(text=f"{DEADLINE}\n\n报名截止日期：2026-11-11。")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["multiple_deadline_values_in_snapshot"])

    def test_eligibility_requires_the_entire_qualification(self):
        full = "全日制在校本科生，须为本校大三学生，且每队必须有一名指导教师"
        quote = f"参赛资格：{full}。"
        result = self.review(evidence(field="eligibility", value=full, quote=quote))
        self.assertEqual(result.evidence.support, "supported")
        for partial in ("本科生", "全日制在校本科生", "本校大三学生"):
            with self.subTest(partial=partial):
                result = self.review(evidence(field="eligibility", value=partial, quote=quote))
                self.assertEqual(result.evidence.support, "unsupported")

    def test_truncated_eligibility_paragraph_is_not_supported(self):
        item = evidence(field="eligibility", value="本科生", quote="参赛对象：本科生")
        result = self.review(item, text="参赛对象：本科生，但仅限本校大三学生，且须导师推荐。")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["quote_not_complete_paragraph"])

    def test_eligibility_keeps_explicit_exclusion_as_part_of_complete_value(self):
        value = "本科生可以参加，但不接受已毕业学生报名"
        result = self.review(evidence(field="eligibility", value=value, quote=f"参赛对象：{value}。"))
        self.assertEqual(result.evidence.support, "supported")

    def test_official_registration_url_requires_exact_path_and_query(self):
        link = "https://example.org/2026/register?token=AbC&track=ai"
        for punctuation in ("", "。", "."):
            with self.subTest(punctuation=punctuation):
                result = self.review(evidence(field="registration_url", value=link,
                    quote=f"官方报名入口：{link}{punctuation}"))
                self.assertEqual(result.evidence.support, "supported")
        for changed in (link.replace("AbC", "abc"), link.replace("/register", "/Register")):
            with self.subTest(changed=changed):
                result = self.review(evidence(field="registration_url", value=changed,
                    quote=f"官方报名入口：{link}"))
                self.assertEqual(result.evidence.support, "unsupported")

    def test_registration_url_unicode_token_is_not_compatibility_normalized(self):
        link = "https://example.org/register?token=Ａ"
        result = self.review(evidence(field="registration_url", value=link.replace("Ａ", "A"),
            quote=f"官方报名入口：{link}"))
        self.assertEqual(result.evidence.support, "unsupported")

    def test_chinese_sentence_period_is_not_accepted_as_a_url_component(self):
        result = self.review(evidence(field="registration_url",
            value="https://example.org/register。",
            quote="官方报名入口：https://example.org/register。"))
        self.assertEqual(result.evidence.support, "unsupported")

    def test_control_characters_in_source_or_claim_urls_are_rejected(self):
        for marker in ("\n", "\t", "\x00", "\x7f"):
            with self.subTest(marker=repr(marker)):
                result = self.review(evidence(url=URL + marker))
                self.assertFalse(result.evidence.source_verified)
                result = self.review(evidence(field="registration_url",
                    value="https://example.org/register" + marker,
                    quote="官方报名入口：https://example.org/register"))
                self.assertNotEqual(result.evidence.support, "supported")

    def test_conflicting_snapshots_are_not_cherry_picked(self):
        result = self.review(snapshots=[
            SourceSnapshot(URL, DEADLINE),
            SourceSnapshot(URL, "报名截止日期：2026-11-11。"),
        ])
        self.assertFalse(result.evidence.source_verified)
        self.assertEqual(result.reasons, ["ambiguous_source_snapshot"])

    def test_snapshot_paragraph_boundaries_are_not_discarded_for_equality(self):
        result = self.review(snapshots=[
            SourceSnapshot(URL, DEADLINE + "\n\n其他说明。"),
            SourceSnapshot(URL, DEADLINE + "\n其他说明。"),
        ])
        self.assertFalse(result.evidence.source_verified)
        self.assertEqual(result.reasons, ["ambiguous_source_snapshot"])

    def test_conflicting_approval_types_are_not_cherry_picked(self):
        result = self.review(approvals=[approval(), approval(source_type="school")])
        self.assertFalse(result.evidence.source_verified)
        self.assertEqual(result.reasons, ["ambiguous_source_approval"])

    def test_school_source_type_comes_from_b_approval(self):
        result = self.review(evidence(source_type="official"), approvals=[approval(source_type="school")])
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.source_type, "school")
        self.assertEqual(result.evidence.support, "supported")

    def test_review_competition_returns_a_deep_copy_and_preserves_raw_fields(self):
        original = competition([evidence()])
        before = deepcopy(original)
        reviewed, results = review_competition(
            original, approved_sources=[approval()], snapshots=[SourceSnapshot(URL, DEADLINE)],
        )
        self.assertEqual(original, before)
        self.assertIsNone(reviewed.fields["registration_deadline"])
        self.assertEqual(reviewed.evidence[0].support, "supported")
        self.assertEqual(reviewed.evidence[0], results[0].evidence)
        reviewed.fields["notes"]["tags"].append("new")
        self.assertEqual(original.fields["notes"]["tags"], ["original"])


if __name__ == "__main__":
    unittest.main()
