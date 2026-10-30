"""Small, explicit cross-field checks over already verified conclusions.

This is deliberately not general semantic reasoning. A rule runs only when all
participating facts are verified and have the exact same nonempty scope. It
returns independent issue records; the caller decides how to revise statuses.
"""

from datetime import date, datetime
import re

from .b_contracts import FieldCheck


_INDIVIDUAL_ONLY = {
    "本赛事仅接受个人参赛，无需组队",
    "本赛事仅接受个人参赛无需组队",
    "仅接受个人参赛，无需组队",
    "仅接受个人参赛无需组队",
}
_TEAM_MODES = {
    "团队",
    "团队赛",
    "团队参赛",
    "仅限团队参赛",
    "仅接受团队参赛",
    "本赛事仅接受团队参赛",
    "以团队形式参赛",
    "仅限组队参赛",
}
_ONLINE_VENUE = {
    "本赛事全程线上，无需到场",
    "本赛事全程线上无需到场",
    "全程线上，无需到场",
    "全程线上无需到场",
}
_STAGE = r"(?:本赛事|本比赛|初赛|复赛|决赛|答辩|决赛答辩)(?:阶段)?"
_OFFLINE_REQUIRED = re.compile(
    rf"(?:{_STAGE})?"
    r"(?:(?:所有|全体)?(?:参赛者|参赛选手|参赛队员))?"
    r"(?:必须|须|需要|需)"
    r"(?:线下到场|到现场(?:参赛|参加比赛|参加答辩|答辩))"
)
_ONLINE_STAGE = re.compile(
    r"(?:初赛|复赛|决赛|答辩|决赛答辩)(?:阶段)?"
    r"(?:线上|在线上)(?:进行|举行|完成)?"
)


def _conclusion(check: FieldCheck) -> str | None:
    if check.value_kind == "not_applicable":
        return check.confirmed_statement
    return check.verified_value


def _sentence(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(value.split())
    return text[:-1] if text.endswith(("。", ".")) else text


def _same_verified_scope(*checks: FieldCheck | None) -> bool:
    return bool(checks) and all(
        check is not None
        and check.status == "verified"
        and isinstance(check.scope, str)
        and bool(check.scope.strip())
        and check.scope == checks[0].scope
        for check in checks
    )


def _moment(value: str | None) -> tuple[str, date | datetime] | None:
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return "date", date.fromisoformat(value)
        if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T", value):
            return None
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None or moment.utcoffset() is None:
            return None
        return "datetime", moment
    except (ValueError, OverflowError):
        return None


def _requires_offline(value: str | None) -> bool:
    """Accept a tiny complete statement grammar, never substring matching.

    A list may contain known online-stage clauses and explicit mandatory onsite
    clauses. Any unrecognised clause (including options, negations, conditions,
    qualifications or quotations) makes this rule abstain for the whole value.
    """
    if not isinstance(value, str):
        return False
    clauses = [
        "".join(item.split())
        for item in re.split(r"[，,；;。.\r\n]+", value)
        if item.strip()
    ]
    if not clauses:
        return False
    matched_offline = False
    for clause in clauses:
        if _OFFLINE_REQUIRED.fullmatch(clause):
            matched_offline = True
        elif not _ONLINE_STAGE.fullmatch(clause):
            return False
    return matched_offline


def _issue(code: str, fields: list[str], checks: dict[str, FieldCheck], message: str) -> dict:
    return {
        "code": code,
        "fields": list(fields),
        "message": message,
        "evidence_ids": list(dict.fromkeys(
            evidence_id
            for name in fields
            for evidence_id in checks[name].evidence_ids
        )),
        "values": {name: _conclusion(checks[name]) for name in fields},
    }


def detect_consistency_issues(checks: dict[str, FieldCheck]) -> list[dict]:
    """Return explicit contradictions without mutating input or guessing facts."""
    issues: list[dict] = []
    start = checks.get("registration_start")
    deadline = checks.get("registration_deadline")
    if _same_verified_scope(start, deadline):
        start_at = _moment(_conclusion(start))
        end_at = _moment(_conclusion(deadline))
        if start_at and end_at and start_at[0] == end_at[0] and start_at[1] > end_at[1]:
            issues.append(_issue(
                "registration_start_after_deadline",
                ["registration_start", "registration_deadline"],
                checks,
                "同一范围内，已核验的报名开始时间晚于报名截止时间，需要核对来源。",
            ))

    team_rules = checks.get("team_rules")
    participation = checks.get("participation_mode")
    if (
        _same_verified_scope(team_rules, participation)
        and team_rules.value_kind == "not_applicable"
        and _sentence(team_rules.confirmed_statement) in _INDIVIDUAL_ONLY
        and participation.value_kind != "not_applicable"
        and _sentence(participation.verified_value) in _TEAM_MODES
    ):
        issues.append(_issue(
            "individual_only_vs_team_participation",
            ["team_rules", "participation_mode"],
            checks,
            "同一范围内，一项结论明确仅接受个人参赛且无需组队，另一项明确要求团队参赛。",
        ))

    venue = checks.get("venue")
    if (
        venue is not None
        and venue.status == "verified"
        and venue.value_kind == "not_applicable"
        and _sentence(venue.confirmed_statement) in _ONLINE_VENUE
    ):
        for name in ("attendance_mode", "schedule"):
            other = checks.get(name)
            if (
                _same_verified_scope(venue, other)
                and other.value_kind != "not_applicable"
                and _requires_offline(other.verified_value)
            ):
                issues.append(_issue(
                    "online_only_vs_required_onsite",
                    ["venue", name],
                    checks,
                    "同一范围内，场地结论明确全程线上且无需到场，另一项明确要求某阶段线下到场。",
                ))
    return issues
