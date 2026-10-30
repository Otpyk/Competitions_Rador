"""Literal review of the M01-M10 and E01-E08 field alignment proposal."""

import unittest

from b_app.b_contracts import Competition, Evidence
from b_app.field_catalog import DATE_FIELDS, FIELD_SPECS, NOT_APPLICABLE_STATEMENTS
from b_app.source_review import ApprovedSource, SourceSnapshot, review_evidence


URL = "https://contest.example.org/2026/notice?track=ai"
CAMPUS_SCOPE = "campus:测试大学"


class ExtendedSourceReviewTests(unittest.TestCase):
    def review(
        self, field, value, *, body=None, quote=None, text=None, value_kind="value",
        evidence_scope="global", field_scopes=None, approval_scope=None,
        source_type="official", approvals=None, snapshots=None,
    ):
        target = Competition(
            id="demo", name="校园 AI 创意赛", edition="2026",
            field_scopes={} if field_scopes is None else field_scopes,
        )
        if quote is None:
            quote = f"{FIELD_SPECS[field].labels[0]}：{value if body is None else body}"
        item = Evidence(
            id=f"e-{field}", field=field, value=value, url=URL,
            quote=quote, edition="2026", scope=evidence_scope, value_kind=value_kind,
        )
        approved = ApprovedSource(
            competition_id="demo", edition="2026", scope=approval_scope or evidence_scope,
            url=URL, source_type=source_type, approved_by="B:测试批准人",
        )
        return review_evidence(
            target, item,
            approved_sources=[approved] if approvals is None else approvals,
            snapshots=[SourceSnapshot(URL, quote if text is None else text)] if snapshots is None else snapshots,
        )

    def test_each_catalogued_text_field_accepts_a_complete_literal_statement(self):
        for field, spec in FIELD_SPECS.items():
            if spec.kind != "text":
                continue
            with self.subTest(field=field):
                scope = CAMPUS_SCOPE if spec.campus_only else "global"
                value = {
                    "competition_name": "校园 AI 创意赛",
                    "competition_edition": "2026",
                }.get(field, "完整官方说明，适用条件必须全部保留")
                result = self.review(
                    field, value, body=value + "。",
                    evidence_scope=scope, field_scopes={field: scope},
                    source_type="school" if spec.campus_only else "official",
                )
                self.assertEqual(result.evidence.support, "supported")
                self.assertTrue(result.evidence.source_verified)
                self.assertTrue(result.evidence.reviewed_by.startswith("literal-v3:"))

    def test_all_date_fields_accept_only_explicit_complete_dates(self):
        for field in DATE_FIELDS:
            for body in ("2026-11-10。", "2026年11月10日。"):
                with self.subTest(field=field, body=body):
                    scope = CAMPUS_SCOPE if field == "campus_deadline" else "global"
                    result = self.review(field, "2026-11-10", body=body,
                        evidence_scope=scope, field_scopes={field: scope})
                    self.assertEqual(result.evidence.support, "supported")

    def test_catalogued_label_aliases_are_supported(self):
        for field in ("organizer", "registration_start", "campus_deadline", "submission_deadline"):
            spec = FIELD_SPECS[field]
            for label in spec.labels:
                with self.subTest(field=field, label=label):
                    value = "2026-11-10" if spec.kind == "date" else "测试大学"
                    scope = CAMPUS_SCOPE if field == "campus_deadline" else "global"
                    result = self.review(field, value, quote=f"{label}：{value}。",
                        evidence_scope=scope, field_scopes={field: scope})
                    self.assertEqual(result.evidence.support, "supported")

    def test_wrong_label_does_not_verify_a_different_field(self):
        for field, quote in (
            ("organizer", "承办单位：测试大学。"),
            ("registration_start", "报名截止日期：2026-11-10。"),
            ("campus_deadline", "报名截止日期：2026-11-10。"),
            ("submission_deadline", "报名截止日期：2026-11-10。"),
            ("mandatory_fees", "报名费用：每队100元。"),
        ):
            with self.subTest(field=field):
                result = self.review(field, "2026-11-10" if field in DATE_FIELDS else "测试大学", quote=quote)
                self.assertEqual(result.evidence.support, "unknown")

    def test_partial_team_rules_are_not_supported(self):
        body = "每队3至5人，允许跨校，队长必须是本科生，且须一名指导教师。"
        result = self.review("team_rules", "每队3至5人", body=body)
        self.assertEqual(result.evidence.support, "unsupported")

    def test_single_online_stage_does_not_prove_all_stages_online(self):
        result = self.review("attendance_mode", "全程线上", body="初赛线上，决赛须到北京现场答辩。")
        self.assertEqual(result.evidence.support, "unsupported")

    def test_fee_amount_currency_and_per_team_basis_must_be_preserved(self):
        body = "每队人民币100元，晋级决赛另收每队200元。"
        result = self.review("registration_fee", "100元", body=body)
        self.assertEqual(result.evidence.support, "unsupported")

    def test_missing_fee_announcement_does_not_prove_free_registration(self):
        result = self.review("registration_fee", "免费", quote="报名方式：由队长在官网提交。")
        self.assertEqual(result.evidence.support, "unknown")

    def test_explicit_unannounced_text_does_not_count_as_a_known_field_value(self):
        for field in ("registration_fee", "team_rules", "awards", "schedule"):
            for value in ("暂未公布", "未公布", "后续另行通知", "待通知", "待补充"):
                with self.subTest(field=field, value=value):
                    result = self.review(field, value, body=value + "。")
                    self.assertEqual(result.evidence.support, "unknown")
                    self.assertEqual(result.reasons, ["field_value_not_announced"])

    def test_another_fields_missing_value_does_not_hide_a_known_field(self):
        quote = "主办方：测试大学。"
        result = self.review("organizer", "测试大学", quote=quote,
            text=f"{quote}\n\n报名费用：暂未公布。")
        self.assertEqual(result.evidence.support, "supported")

    def test_multiple_different_same_field_paragraphs_remain_unknown(self):
        for field, first, second in (
            ("team_rules", "每队3人。", "每队5人。"),
            ("registration_fee", "每队100元。", "每队200元。"),
            ("attendance_mode", "全程线上。", "决赛线下。"),
            ("registration_url", "https://example.org/a", "https://example.org/b"),
            ("registration_start", "2026-10-22。", "2026-10-23。"),
        ):
            label = FIELD_SPECS[field].labels[0]
            first_quote = f"{label}：{first}"
            text = f"{first_quote}\n\n{label}：{second}"
            with self.subTest(field=field):
                result = self.review(field, first.rstrip("。"), quote=first_quote, text=text)
                self.assertEqual(result.evidence.support, "unknown")
                self.assertEqual(result.reasons, ["multiple_field_values_in_snapshot"])

    def test_alias_labels_participate_in_same_field_ambiguity_checks(self):
        result = self.review("organizer", "测试大学", quote="主办方：测试大学。",
            text="主办方：测试大学。\n\n主办单位：另一个主办单位。")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["multiple_field_values_in_snapshot"])

    def test_same_value_repeated_with_layout_or_terminal_punctuation_is_not_conflict(self):
        quote = "主办方：测试大学。"
        result = self.review("organizer", "测试大学", quote=quote,
            text=f"{quote}\n\n主办单位： 测试大学")
        self.assertEqual(result.evidence.support, "supported")

    def test_new_text_field_cannot_use_an_incomplete_paragraph(self):
        result = self.review("deliverables", "代码", quote="提交成果：代码",
            text="提交成果：代码、论文和演示视频，缺一不可。")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["quote_not_complete_paragraph"])

    def test_every_explicit_not_applicable_whitelist_statement_is_supported(self):
        for field, statements in NOT_APPLICABLE_STATEMENTS.items():
            for statement in statements:
                with self.subTest(field=field):
                    result = self.review(field, statement, value_kind="not_applicable")
                    self.assertEqual(result.evidence.support, "supported")
                    self.assertEqual(result.evidence.value_kind, "not_applicable")
                    self.assertEqual(result.evidence.value, statement)

    def test_generic_not_applicable_cannot_pass_with_either_value_kind(self):
        for value_kind in ("value", "not_applicable"):
            for field in ("venue", "campus_deadline", "registration_fee", "registration_url"):
                with self.subTest(value_kind=value_kind, field=field):
                    result = self.review(field, "不适用", value_kind=value_kind)
                    self.assertEqual(result.evidence.support, "unknown")

    def test_not_applicable_requires_the_correct_label_and_full_statement(self):
        statement = NOT_APPLICABLE_STATEMENTS["venue"][0]
        for quote in (statement, f"比赛地点：{statement[:-1]}", f"参赛方式：{statement}"):
            with self.subTest(quote=quote):
                result = self.review("venue", statement, value_kind="not_applicable", quote=quote)
                self.assertEqual(result.evidence.support, "unknown")

    def test_not_applicable_claim_must_equal_the_authorized_statement(self):
        statement = NOT_APPLICABLE_STATEMENTS["venue"][0]
        result = self.review("venue", "无需到场", body=statement, value_kind="not_applicable")
        self.assertEqual(result.evidence.support, "unsupported")

    def test_not_applicable_cannot_borrow_another_fields_whitelist(self):
        statement = NOT_APPLICABLE_STATEMENTS["venue"][0]
        result = self.review("registration_fee", statement, value_kind="not_applicable")
        self.assertEqual(result.evidence.support, "unknown")

    def test_explicit_not_applicable_statement_requires_its_correct_value_kind(self):
        for field, statements in NOT_APPLICABLE_STATEMENTS.items():
            for statement in statements:
                with self.subTest(field=field):
                    scope = CAMPUS_SCOPE if field == "campus_deadline" else "global"
                    result = self.review(field, statement, value_kind="value",
                        evidence_scope=scope, field_scopes={field: scope})
                    self.assertEqual(result.evidence.support, "unknown")
                    self.assertEqual(result.reasons, ["not_applicable_value_kind_required"])

    def test_not_applicable_and_a_contrary_value_on_the_same_page_are_ambiguous(self):
        for field, contrary in (
            ("venue", "决赛须到北京现场答辩。"),
            ("campus_deadline", "2026-11-10。"),
            ("registration_url", "https://example.org/register"),
        ):
            statement = NOT_APPLICABLE_STATEMENTS[field][0]
            label = FIELD_SPECS[field].labels[0]
            quote = f"{label}：{statement}"
            text = f"{quote}\n\n{label}：{contrary}"
            with self.subTest(field=field):
                result = self.review(field, statement, value_kind="not_applicable", quote=quote, text=text)
                self.assertEqual(result.evidence.support, "unknown")

    def test_school_recognition_requires_a_specific_campus_scope(self):
        for scope in ("global", "campus:", "campus:未知", "campus: "):
            with self.subTest(scope=scope):
                result = self.review("school_recognition", "列入校级竞赛认定目录", evidence_scope=scope,
                    field_scopes={"school_recognition": scope}, source_type="school")
                self.assertFalse(result.evidence.source_verified)
                self.assertEqual(result.evidence.support, "unknown")
                self.assertEqual(result.reasons, ["specific_campus_scope_required"])

    def test_school_recognition_accepts_the_exact_approved_school_page(self):
        value = "测试大学2026年AI赛道一等奖计2学分，仅限本校在籍本科生"
        result = self.review("school_recognition", value, body=value + "。",
            evidence_scope=CAMPUS_SCOPE, field_scopes={"school_recognition": CAMPUS_SCOPE}, source_type="school")
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.source_type, "school")
        self.assertEqual(result.evidence.support, "supported")

    def test_another_schools_approval_cannot_verify_campus_recognition(self):
        result = self.review("school_recognition", "一等奖计2学分",
            evidence_scope=CAMPUS_SCOPE, field_scopes={"school_recognition": CAMPUS_SCOPE},
            approval_scope="campus:另一个大学", source_type="school")
        self.assertFalse(result.evidence.source_verified)

    def test_field_specific_campus_deadline_does_not_use_global_approval(self):
        result = self.review("campus_deadline", "2026-11-10",
            evidence_scope=CAMPUS_SCOPE, field_scopes={"campus_deadline": CAMPUS_SCOPE},
            approval_scope="global", source_type="school")
        self.assertFalse(result.evidence.source_verified)

    def test_ordinary_campus_deadline_requires_a_specific_campus(self):
        for scope in ("global", "campus:", "campus:未知"):
            with self.subTest(scope=scope):
                result = self.review("campus_deadline", "2026-11-10",
                    evidence_scope=scope, field_scopes={"campus_deadline": scope})
                self.assertFalse(result.evidence.source_verified)
                self.assertEqual(result.reasons, ["specific_campus_scope_required"])

    def test_explicit_no_campus_registration_is_allowed_at_global_scope(self):
        statement = NOT_APPLICABLE_STATEMENTS["campus_deadline"][0]
        result = self.review("campus_deadline", statement, value_kind="not_applicable")
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "supported")

    def test_global_registration_and_campus_deadlines_keep_distinct_scopes(self):
        result = self.review("registration_deadline", "2026-11-10",
            evidence_scope="global", field_scopes={"campus_deadline": CAMPUS_SCOPE})
        self.assertEqual(result.evidence.support, "supported")

    def test_approved_notice_url_can_identify_its_own_retrieved_notice_page(self):
        result = self.review("official_url", URL, quote="2026年校园AI创意赛正式通知。")
        self.assertTrue(result.evidence.source_verified)
        self.assertEqual(result.evidence.support, "supported")
        self.assertEqual(result.reasons, ["approved_notice_page_supported"])

    def test_notice_url_self_identity_still_requires_approval_snapshot_and_complete_quote(self):
        for changes in (
            {"approvals": []}, {"snapshots": []},
            {"text": "这是2026年校园AI创意赛正式通知。全文以主办方盖章版本为准。"},
        ):
            with self.subTest(changes=changes):
                result = self.review("official_url", URL, quote="2026年校园AI创意赛正式通知。", **changes)
                self.assertNotEqual(result.evidence.support, "supported")

    def test_notice_url_self_identity_cannot_claim_another_path_or_query(self):
        for value in (URL.replace("/notice", "/Notice"), URL.replace("track=ai", "track=other")):
            with self.subTest(value=value):
                result = self.review("official_url", value, quote="2026年校园AI创意赛正式通知。")
                self.assertEqual(result.evidence.support, "unknown")

    def test_notice_url_can_be_an_explicit_link_label(self):
        value = "https://contest.example.org/2026/charter?track=AI"
        result = self.review("official_url", value, body=value + "。")
        self.assertEqual(result.evidence.support, "supported")

    def test_rolling_and_partial_dates_remain_unknown(self):
        for field in DATE_FIELDS:
            for body in ("滚动报名，额满即止。", "11月10日。", "2026-11-10 18:00。", "2026-11-10T18:00:00+08:00。"):
                with self.subTest(field=field, body=body):
                    scope = CAMPUS_SCOPE if field == "campus_deadline" else "global"
                    result = self.review(field, "2026-11-10", body=body,
                        evidence_scope=scope, field_scopes={field: scope})
                    self.assertEqual(result.evidence.support, "unknown")

    def test_unrecognized_value_kind_cannot_self_declare_support(self):
        result = self.review("venue", "全程线上", value_kind="auto_verified")
        self.assertEqual(result.evidence.support, "unknown")
        self.assertEqual(result.reasons, ["unknown_value_kind"])


if __name__ == "__main__":
    unittest.main()
