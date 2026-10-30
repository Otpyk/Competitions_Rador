"""Cross-field rule examples are synthetic; unknown language must not be guessed."""

from copy import deepcopy
from dataclasses import replace
import unittest

from b_app.b_contracts import FieldCheck
from b_app.consistency_checks import detect_consistency_issues


def checked(name, value=None, **changes):
    item = FieldCheck(
        field=name, status="verified", original_value=value, verified_value=value,
        value_kind="value", scope="global", evidence_ids=[f"source-{name}"],
    )
    return replace(item, **changes)


def na(name, statement, **changes):
    return checked(name, value_kind="not_applicable", confirmed_statement=statement, **changes)


class ConsistencyChecksTests(unittest.TestCase):
    def test_reversed_registration_dates_return_original_values_and_evidence(self):
        checks = {
            "registration_start": checked("registration_start", "2026-11-20", evidence_ids=["shared", "start"]),
            "registration_deadline": checked("registration_deadline", "2026-11-10", evidence_ids=["shared", "end"]),
        }
        result = detect_consistency_issues(checks)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "registration_start_after_deadline")
        self.assertEqual(result[0]["fields"], ["registration_start", "registration_deadline"])
        self.assertEqual(result[0]["values"], {"registration_start": "2026-11-20", "registration_deadline": "2026-11-10"})
        self.assertEqual(result[0]["evidence_ids"], ["shared", "start", "end"])
        self.assertTrue(result[0]["message"])

    def test_valid_or_equal_registration_dates_are_not_conflicts(self):
        for start in ("2026-11-09", "2026-11-10"):
            with self.subTest(start=start):
                self.assertEqual(detect_consistency_issues({
                    "registration_start": checked("registration_start", start),
                    "registration_deadline": checked("registration_deadline", "2026-11-10"),
                }), [])

    def test_aware_datetimes_use_actual_instants(self):
        for start, deadline, expected in (
            ("2026-11-10T11:00:00+08:00", "2026-11-10T02:00:00Z", 1),
            ("2026-11-10T10:00:00+08:00", "2026-11-10T02:00:00Z", 0),
            ("2026-11-10T10:00:00+08:00", "2026-11-10T03:00:00Z", 0),
        ):
            with self.subTest(start=start, deadline=deadline):
                result = detect_consistency_issues({
                    "registration_start": checked("registration_start", start),
                    "registration_deadline": checked("registration_deadline", deadline),
                })
                self.assertEqual(len(result), expected)

    def test_mixed_precision_naive_invalid_and_unknown_dates_abstain(self):
        for start, deadline in (
            ("2026-11-20", "2026-11-10T02:00:00Z"),
            ("2026-11-20T02:00:00Z", "2026-11-10"),
            ("2026-11-20T02:00:00", "2026-11-10T02:00:00Z"),
            ("2026-02-30", "2026-02-20"),
            ("2026-11-20T99:00:00Z", "2026-11-10T02:00:00Z"),
            ("额满即止", "2026-11-10"),
            (None, "2026-11-10"),
        ):
            with self.subTest(start=start, deadline=deadline):
                self.assertEqual(detect_consistency_issues({
                    "registration_start": checked("registration_start", start),
                    "registration_deadline": checked("registration_deadline", deadline),
                }), [])

    def test_registration_dates_require_exact_matching_nonempty_scope(self):
        for scope_a, scope_b in (("global", "campus:甲校"), ("campus:甲校", "campus:乙校"), ("global", "global "), ("", "")):
            with self.subTest(scopes=(scope_a, scope_b)):
                self.assertEqual(detect_consistency_issues({
                    "registration_start": checked("registration_start", "2026-11-20", scope=scope_a),
                    "registration_deadline": checked("registration_deadline", "2026-11-10", scope=scope_b),
                }), [])

    def test_submission_and_campus_deadlines_are_not_compared_to_registration(self):
        self.assertEqual(detect_consistency_issues({
            "submission_deadline": checked("submission_deadline", "2026-11-01"),
            "campus_deadline": checked("campus_deadline", "2026-12-01"),
            "registration_deadline": checked("registration_deadline", "2026-11-10"),
        }), [])

    def test_unverified_date_is_not_used(self):
        for status in ("pending", "conflict"):
            with self.subTest(status=status):
                self.assertEqual(detect_consistency_issues({
                    "registration_start": checked("registration_start", "2026-11-20", status=status),
                    "registration_deadline": checked("registration_deadline", "2026-11-10"),
                }), [])

    def test_individual_only_na_conflicts_with_explicit_team_mode(self):
        for value in ("团队参赛。", "仅接受团队参赛", "以团队形式参赛。"):
            with self.subTest(value=value):
                result = detect_consistency_issues({
                    "team_rules": na("team_rules", "本赛事仅接受个人参赛，无需组队。"),
                    "participation_mode": checked("participation_mode", value),
                })
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["code"], "individual_only_vs_team_participation")
                self.assertEqual(result[0]["values"]["team_rules"], "本赛事仅接受个人参赛，无需组队。")

    def test_team_optional_negated_or_unknown_modes_do_not_trigger(self):
        for value in ("个人或团队参赛。", "个人、团队均可。", "不接受团队参赛。", "可选团队参赛。", "团队参赛或个人参赛。", "团队参赛（也可个人）。", "参赛形式另行通知。", None):
            with self.subTest(value=value):
                self.assertEqual(detect_consistency_issues({
                    "team_rules": na("team_rules", "本赛事仅接受个人参赛，无需组队。"),
                    "participation_mode": checked("participation_mode", value),
                }), [])

    def test_team_rule_needs_confirmed_na_and_matching_scope(self):
        cases = (
            checked("team_rules", "本赛事仅接受个人参赛，无需组队。"),
            na("team_rules", "无需组队。"),
            na("team_rules", "本赛事仅接受个人参赛，无需组队。", scope="campus:甲校"),
            na("team_rules", "本赛事仅接受个人参赛，无需组队。", status="pending"),
        )
        for rules in cases:
            with self.subTest(rules=rules):
                self.assertEqual(detect_consistency_issues({
                    "team_rules": rules,
                    "participation_mode": checked("participation_mode", "团队参赛。"),
                }), [])

    def test_onsite_required_conflicts_with_online_venue_for_each_field(self):
        for name in ("attendance_mode", "schedule"):
            for value in ("决赛必须线下到场。", "答辩阶段须线下到场。", "初赛线上；决赛必须到现场参加比赛。", "初赛线上进行，决赛需线下到场。"):
                with self.subTest(name=name, value=value):
                    result = detect_consistency_issues({
                        "venue": na("venue", "本赛事全程线上，无需到场。"),
                        name: checked(name, value),
                    })
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0]["code"], "online_only_vs_required_onsite")
                    self.assertEqual(result[0]["fields"], ["venue", name])

    def test_negative_optional_conditional_and_quoted_onsite_clauses_abstain(self):
        for value in (
            "决赛无需线下到场。", "决赛不必线下到场。", "决赛不强制线下到场。",
            "决赛可选择线下到场。", "决赛可线上或线下参加。", "决赛不是必须线下到场。",
            "若晋级决赛则必须线下到场。", "决赛必须线下到场（可线上替代）。",
            "决赛必须线下到场；但允许线上参加。", "通知中的‘决赛必须线下到场’已取消。",
            "决赛线下举行。", "初赛线上；详细赛程另行通知。", "决赛必须线下到场或线上参加。",
            "仅工作人员必须线下到场。", "评委必须线下到场。", "全程线上。", None,
        ):
            with self.subTest(value=value):
                self.assertEqual(detect_consistency_issues({
                    "venue": na("venue", "本赛事全程线上，无需到场。"),
                    "schedule": checked("schedule", value),
                }), [])

    def test_onsite_check_requires_na_verified_and_exact_scope(self):
        variants = (
            checked("venue", "本赛事全程线上，无需到场。"),
            na("venue", "本赛事全程线上，无需到场。", status="conflict"),
            na("venue", "本赛事全程线上，无需到场。", scope="campus:甲校"),
            na("venue", "无需到场。"),
        )
        for venue in variants:
            with self.subTest(venue=venue):
                self.assertEqual(detect_consistency_issues({
                    "venue": venue,
                    "attendance_mode": checked("attendance_mode", "决赛必须线下到场。"),
                }), [])
        self.assertEqual(detect_consistency_issues({
            "venue": na("venue", "本赛事全程线上，无需到场。"),
            "schedule": checked("schedule", "决赛必须线下到场。", status="pending"),
        }), [])

    def test_two_onsite_fields_return_separate_issues(self):
        result = detect_consistency_issues({
            "venue": na("venue", "本赛事全程线上，无需到场。"),
            "attendance_mode": checked("attendance_mode", "决赛必须线下到场。"),
            "schedule": checked("schedule", "答辩须线下到场。"),
        })
        self.assertEqual(len(result), 2)
        self.assertEqual([item["fields"][1] for item in result], ["attendance_mode", "schedule"])

    def test_input_and_returned_containers_are_independent(self):
        checks = {
            "venue": na("venue", "本赛事全程线上，无需到场。"),
            "attendance_mode": checked("attendance_mode", "决赛必须线下到场。"),
        }
        before = deepcopy(checks)
        result = detect_consistency_issues(checks)
        self.assertEqual(checks, before)
        result[0]["evidence_ids"].append("not-an-input-id")
        result[0]["values"]["venue"] = "changed result only"
        result[0]["fields"].clear()
        self.assertEqual(checks, before)

    def test_empty_or_unrelated_fields_return_no_issues(self):
        self.assertEqual(detect_consistency_issues({}), [])
        self.assertEqual(detect_consistency_issues({"awards": checked("awards", "一等奖3队。")}), [])


if __name__ == "__main__":
    unittest.main()
