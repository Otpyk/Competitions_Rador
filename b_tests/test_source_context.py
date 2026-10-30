"""B's literal-v3 identity and complete-qualification safeguards.

Every source and approval is a local fixture. These checks make no network call.
"""

from copy import deepcopy
from dataclasses import replace
import unittest

from b_app.b_contracts import Competition, Evidence
from b_app.source_review import (
    ApprovedSource, ReviewResult, SourceSnapshot, review_competition, review_evidence,
)


URL = "https://contest.example.invalid/2026/notice"
NAME = "校园 AI 创意赛"
ELIGIBILITY = "全国普通高校在读本科生"
BASE_QUOTE = f"参赛资格：{ELIGIBILITY}。"
EXTRA_QUOTE = "附加参赛条件：仅限计算机专业。"


def candidate(records=()):
    return Competition(id="target", name=NAME, edition="2026", evidence=list(records))


def record(**changes):
    values = dict(
        id="qualification", field="eligibility", value=ELIGIBILITY,
        quote=BASE_QUOTE, url=URL, edition="2026",
    )
    values.update(changes)
    return Evidence(**values)


def approved_source():
    return ApprovedSource(
        competition_id="target", edition="2026", scope="global", url=URL,
        source_type="official", approved_by="fixture:B-reviewer",
    )


class SourceContextTests(unittest.TestCase):
    def review(self, text, item=None):
        return review_evidence(
            candidate(), item or record(), approved_sources=[approved_source()],
            snapshots=[SourceSnapshot(url=URL, text=text)],
        )

    def test_explicit_other_competition_name_blocks_qualification(self):
        result = self.review("赛事名称：其他赛事。\n\n" + BASE_QUOTE)

        self.assertEqual(result.evidence.support, "unknown")
        self.assertFalse(result.evidence.source_verified)
        self.assertIn("source_name_mismatch", result.reasons)

    def test_explicit_other_edition_blocks_every_claim_from_the_page(self):
        entries = [
            record(),
            record(id="deadline", field="registration_deadline", value="2026-11-01",
                   quote="报名截止日期：2026-11-01。"),
            record(id="notice", field="official_url", value=URL),
        ]
        text = "届次年份：2025。\n\n" + BASE_QUOTE + "\n\n" + entries[1].quote
        reviewed, results = review_competition(
            candidate(entries), approved_sources=[approved_source()],
            snapshots=[SourceSnapshot(url=URL, text=text)],
        )

        self.assertEqual(len(results), 3)
        for result, entry in zip(results, reviewed.evidence):
            with self.subTest(field=entry.field):
                self.assertFalse(entry.source_verified)
                self.assertEqual(entry.support, "unknown")
                self.assertIn("source_edition_mismatch", result.reasons)

    def test_matching_identity_statements_allow_the_independent_qualification(self):
        headers = [
            f"赛事名称：{NAME}。\n\n届次年份：2026。",
            f"赛事名称：{NAME}\n届次年份：2026",
            f"赛事名称：{NAME}。届次年份：2026。",
            f"赛事名称：\n{NAME}。\n\n届次年份：2026年。",
        ]
        for header in headers:
            with self.subTest(header=header):
                self.assertEqual(self.review(header + "\n\n" + BASE_QUOTE).evidence.support, "supported")

    def test_a_matching_identity_label_cannot_hide_a_second_conflicting_identity(self):
        for extra, reason in (
            ("赛事名称：另一赛事。", "source_name_mismatch"),
            ("届次年份：2025。", "source_edition_mismatch"),
        ):
            text = f"赛事名称：{NAME}。\n\n届次年份：2026。\n\n{extra}\n\n{BASE_QUOTE}"
            with self.subTest(extra=extra):
                result = self.review(text)
                self.assertEqual(result.evidence.support, "unknown")
                self.assertIn(reason, result.reasons)

    def test_unrelated_years_in_prose_are_not_treated_as_the_edition(self):
        text = "主办单位成立于1998年。\n\n页面技术更新日期：2025-12-01。\n\n" + BASE_QUOTE

        self.assertEqual(self.review(text).evidence.support, "supported")

    def test_explicit_unresolved_identity_does_not_pass_as_a_matching_identity(self):
        result = self.review("赛事名称：待确认。\n\n" + BASE_QUOTE)

        self.assertEqual(result.evidence.support, "unknown")
        self.assertIn("source_identity_unresolved", result.reasons)

    def test_qualification_omitting_a_separate_additional_condition_is_unknown(self):
        result = self.review(BASE_QUOTE + "\n\n" + EXTRA_QUOTE)

        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["eligibility_conditions_omitted"])

    def test_supported_additional_condition_labels_are_checked_for_omissions(self):
        for label in ("补充参赛条件", "额外参赛条件", "参赛限制", "资格限制",
                      "附加资格要求", "补充资格要求", "参赛资格补充说明"):
            with self.subTest(label=label):
                result = self.review(BASE_QUOTE + f"\n\n{label}：仅限计算机专业。")
                self.assertEqual(result.evidence.support, "unknown")
                self.assertEqual(result.reasons, ["eligibility_conditions_omitted"])

    def test_complete_contiguous_qualification_blocks_can_be_supported(self):
        quote = BASE_QUOTE + "\n\n" + EXTRA_QUOTE
        value = ELIGIBILITY + "。 " + EXTRA_QUOTE
        text = f"赛事名称：{NAME}。\n\n{quote}\n\n主办方：示例大学。"
        result = self.review(text, record(value=value, quote=quote))

        self.assertEqual(result.evidence.support, "supported")
        self.assertEqual(result.evidence.value, value)

    def test_complete_quote_cannot_support_a_value_that_drops_the_extra_condition(self):
        quote = BASE_QUOTE + "\n\n" + EXTRA_QUOTE
        result = self.review(quote, record(quote=quote, value=ELIGIBILITY))

        self.assertEqual(result.evidence.support, "unsupported")
        self.assertEqual(result.reasons, ["claim_value_mismatch"])

    def test_one_of_two_supplemental_conditions_cannot_be_omitted(self):
        quote = BASE_QUOTE + "\n\n" + EXTRA_QUOTE
        text = quote + "\n\n补充参赛条件：仅限本校大三学生。"
        result = self.review(text, record(quote=quote, value=ELIGIBILITY + "。 " + EXTRA_QUOTE))

        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["eligibility_conditions_omitted"])

    def test_every_complete_supplement_is_preserved_when_more_than_one_applies(self):
        quote = BASE_QUOTE + "\n\n" + EXTRA_QUOTE + "\n\n补充参赛条件：仅限本校大三学生。"
        value = ELIGIBILITY + "。 " + EXTRA_QUOTE + " 补充参赛条件：仅限本校大三学生。"
        result = self.review(quote, record(quote=quote, value=value))

        self.assertEqual(result.evidence.support, "supported")

    def test_unrelated_fee_paragraph_does_not_change_qualification_support(self):
        result = self.review(BASE_QUOTE + "\n\n报名费用：每队100元。")

        self.assertEqual(result.evidence.support, "supported")

    def test_truncated_supplement_cannot_pass_the_complete_paragraph_requirement(self):
        complete = BASE_QUOTE + "\n\n附加参赛条件：仅限计算机专业，且必须为大三学生。"
        partial = BASE_QUOTE + "\n\n附加参赛条件：仅限计算机专业"
        result = self.review(complete, record(quote=partial, value=ELIGIBILITY + "。 附加参赛条件：仅限计算机专业"))

        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["quote_not_complete_paragraph"])

    def test_empty_or_unknown_supplement_does_not_count_as_complete_conditions(self):
        for extra in ("附加参赛条件：", "附加参赛条件：待确认。"):
            quote = BASE_QUOTE + "\n\n" + extra
            with self.subTest(extra=extra):
                result = self.review(quote, record(quote=quote, value=ELIGIBILITY + "。 " + extra))
                self.assertEqual(result.evidence.support, "unknown")
                self.assertEqual(result.reasons, ["eligibility_conditions_unresolved"])

    def test_review_reasons_are_recomputed_on_success_and_early_rejection(self):
        forged = record(review_reasons=("C_claims_everything_is_supported",))
        original = deepcopy(forged)
        success = self.review(BASE_QUOTE, forged)
        rejected = review_evidence(candidate(), forged, approved_sources=[], snapshots=[])

        for result in (success, rejected):
            self.assertEqual(result.evidence.review_reasons, tuple(result.reasons))
            self.assertNotIn("C_claims_everything_is_supported", result.evidence.review_reasons)
        self.assertEqual(forged, original)

    def test_review_result_attaches_its_own_reason_codes_to_its_evidence(self):
        item = record(review_reasons=("stale",))
        result = ReviewResult(item, ["new_reason", "another_reason"])

        self.assertEqual(result.evidence.review_reasons, ("new_reason", "another_reason"))
        self.assertEqual(item.review_reasons, ("stale",))


if __name__ == "__main__":
    unittest.main()
