"""Evaluate only eligibility claims selected by B."""

from typing import cast

from .normalization import normalize_text
from .schemas import (
    CandidateContest,
    EligibilityAssessment,
    EligibilityRules,
    UserProfile,
    VerificationResult,
)
from .validation import selected_claim, validate_verification


def assess_eligibility(
    profile: UserProfile,
    candidate: CandidateContest,
    verification: VerificationResult,
) -> EligibilityAssessment:
    """Apply independent restrictions without inferring unknown conditions."""
    validate_verification(candidate, verification)
    claim = selected_claim(candidate, verification, "eligibility")
    if claim is None:
        decision = next(item for item in verification.fields if item.field == "eligibility")
        reason = f"资格条件尚未经 B 核验（{decision.status}）：{decision.reason}"
        return EligibilityAssessment(status="unknown", reasons=[reason], pending_items=[reason])

    rules = cast(EligibilityRules, claim.value)
    reasons: list[str] = []
    pending: list[str] = []
    failed = False
    dimensions = (
        ("在读学历", rules.allowed_education_levels, profile.education_level),
        ("专业", rules.allowed_majors, profile.major),
        ("年级", rules.allowed_grades, profile.grade),
    )
    for label, allowed, actual in dimensions:
        if allowed is None:
            reason = f"{label}限制未知。"
            reasons.append(reason)
            pending.append(reason)
        elif not allowed:
            reasons.append(f"已核验{label}明确不限，无需提供该项用户信息。")
        elif actual is None:
            reason = f"赛事限制{label}，但用户尚未提供该项信息。"
            reasons.append(reason)
            pending.append(reason)
        else:
            normalized_actual = normalize_text(actual) if isinstance(actual, str) else actual
            normalized_allowed = [
                normalize_text(value) if isinstance(value, str) else value for value in allowed
            ]
            if normalized_actual in normalized_allowed:
                reasons.append(f"用户{label}“{actual}”符合已核验允许列表。")
            else:
                failed = True
                rendered_allowed = "、".join(str(value) for value in allowed)
                reasons.append(
                    f"用户{label}“{actual}”不在已核验允许列表“{rendered_allowed}”中。"
                )

    team_rule = rules.team_size
    if team_rule is None:
        reason = "团队人数限制未知。"
        reasons.append(reason)
        pending.append(reason)
    elif team_rule.min is None and team_rule.max is None:
        reasons.append("已核验团队人数明确不限，无需提供团队人数。")
    elif profile.team_size is None:
        reason = "赛事限制团队人数，但用户尚未提供团队人数。"
        reasons.append(reason)
        pending.append(reason)
    elif (
        team_rule.min is not None and profile.team_size < team_rule.min
    ) or (
        team_rule.max is not None and profile.team_size > team_rule.max
    ):
        failed = True
        lower = str(team_rule.min) if team_rule.min is not None else "无下界"
        upper = str(team_rule.max) if team_rule.max is not None else "无上界"
        reasons.append(
            f"用户团队人数 {profile.team_size} 不符合已核验人数范围（下界 {lower}，上界 {upper}）。"
        )
    else:
        reasons.append(f"用户团队人数 {profile.team_size} 符合已核验人数范围（包含端点）。")

    if rules.other_requirements is None:
        reason = "是否存在其他参赛资格条款尚未明确。"
        reasons.append(reason)
        pending.append(reason)
    elif rules.other_requirements:
        for requirement in rules.other_requirements:
            reason = f"以下资格条款尚不能自动判断，需人工确认：{requirement}"
            reasons.append(reason)
            pending.append(reason)
    else:
        reasons.append("已核验无其他参赛资格条款。")

    status = "ineligible" if failed else "unknown" if pending else "eligible"
    return EligibilityAssessment(status=status, reasons=reasons, pending_items=pending)
