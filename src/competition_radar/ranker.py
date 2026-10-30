"""Explainable grouping and stable ranking of B-verified field values."""

from copy import deepcopy
from datetime import date, datetime

from .eligibility import assess_eligibility
from .normalization import normalize_text
from .registration import assess_registration
from .schemas import (
    CandidateContest, ExpandedEvidence, RecommendationItem, RecommendationResponse,
    ResolvedField, SourceDocument, UserProfile, VerificationResult,
)
from .validation import (
    ContractError, selected_claim, validate_evidence, validate_verification,
)


FIELD_LABELS = {
    "name": "赛事名称", "organizer": "主办方", "edition": "届次",
    "track": "赛道", "stage": "报名阶段", "tags": "兴趣标签",
    "eligibility": "参赛资格", "registration_start": "报名开始时间",
    "registration_deadline": "报名截止时间", "official_url": "官方页面",
    "registration_url": "报名入口",
}


def recommend(
    task_id: str,
    profile: UserProfile,
    sources: list[SourceDocument],
    candidates: list[CandidateContest],
    verifications: list[VerificationResult],
    as_of: datetime,
) -> RecommendationResponse:
    """Validate the complete snapshot, then classify without merging or searching."""
    if not isinstance(as_of, datetime) or as_of.utcoffset() is None:
        raise ContractError("as_of 必须为带 UTC 偏移的 datetime")
    issues = validate_evidence(candidates, sources)
    if issues:
        raise ContractError("来源与证据校验失败：" + "；".join(i.message for i in issues), issues)
    verification_by_id = {}
    for verification in verifications:
        if verification.record_id in verification_by_id:
            raise ContractError(f"核验结果重复：{verification.record_id}")
        verification_by_id[verification.record_id] = verification
    if set(verification_by_id) != {candidate.record_id for candidate in candidates}:
        raise ContractError("每个候选赛事必须恰有一份核验结果，且不能包含其他赛事的核验结果")
    for candidate in candidates:
        validate_verification(candidate, verification_by_id[candidate.record_id])

    source_by_id = {source.source_id: source for source in sources}
    groups = {"recommended": [], "pending": [], "excluded": []}
    for candidate in candidates:
        verification = verification_by_id[candidate.record_id]
        eligibility = assess_eligibility(profile, candidate, verification)
        registration = assess_registration(candidate, verification, as_of)
        pending_items = [*eligibility.pending_items, *registration.pending_items]
        fields = []
        for decision in verification.fields:
            claim = selected_claim(candidate, verification, decision.field)
            fields.append(ResolvedField(
                field=decision.field, status=decision.status, reason=decision.reason,
                value=deepcopy(claim.value) if claim is not None else None,
                claim_id=claim.claim_id if claim is not None else None,
                evidence=[ExpandedEvidence(
                    source_id=evidence.source_id,
                    url=source_by_id[evidence.source_id].url,
                    quote=evidence.quote,
                ) for evidence in claim.evidence] if claim is not None else [],
            ))
            if decision.status != "verified":
                pending_items.append(f"{FIELD_LABELS[decision.field]}：{decision.reason}")

        tag_claim = selected_claim(candidate, verification, "tags")
        tags = {normalize_text(t) for t in tag_claim.value} if tag_claim is not None else set()
        matched_interests, seen = [], set()
        for interest in profile.interests:
            normalized = normalize_text(interest)
            if normalized in tags and normalized not in seen:
                matched_interests.append(interest)
                seen.add(normalized)

        deadline_claim = selected_claim(candidate, verification, "registration_deadline")
        deadline = deadline_claim.value.date if deadline_claim is not None else None
        outside_range = deadline is not None and (
            (profile.deadline_from is not None and deadline < profile.deadline_from)
            or (profile.deadline_to is not None and deadline > profile.deadline_to)
        )
        needs_deadline = profile.deadline_from is not None or profile.deadline_to is not None
        range_unknown = needs_deadline and deadline is None
        if range_unknown:
            pending_items.append("报名截止日期未核验，无法判断是否在用户要求的日期范围内")
        has_name = selected_claim(candidate, verification, "name") is not None
        has_official_url = selected_claim(candidate, verification, "official_url") is not None

        reasons = [*eligibility.reasons, *registration.reasons]
        if eligibility.status == "ineligible" or registration.status == "closed" or outside_range:
            bucket = "excluded"
            if outside_range:
                reasons.append(f"报名截止日期 {deadline.isoformat()} 不在用户要求的日期范围内")
        elif (
            eligibility.status == "eligible" and registration.status == "open"
            and has_name and has_official_url and not range_unknown
        ):
            bucket = "recommended"
            reasons.append("资格符合、报名进行中，赛事名称和官方页面均已经 B 核验")
        else:
            bucket = "pending"
            reasons.append("尚不具备可立即报名推荐所需的全部已核验条件")
        if matched_interests:
            reasons.append("兴趣标签命中：" + "、".join(matched_interests))
        else:
            reasons.append("兴趣标签精确命中数为 0")
        item = RecommendationItem(
            record_id=candidate.record_id, fields=fields,
            eligibility_status=eligibility.status, eligibility_reasons=eligibility.reasons,
            registration_status=registration.status, registration_reasons=registration.reasons,
            verification_status=verification.verification_status, verified_at=verification.verified_at,
            matched_interests=matched_interests, interest_match_count=len(matched_interests),
            reasons=reasons, pending_items=list(dict.fromkeys(pending_items)),
        )
        groups[bucket].append((item, deadline))

    # Python's stable sort preserves source order for otherwise equal keys.
    sorted_groups = {}
    for bucket, entries in groups.items():
        entries.sort(key=lambda pair: (
            -pair[0].interest_match_count, pair[1] is None, pair[1] or date.max,
        ))
        sorted_groups[bucket] = [item for item, _ in entries]
    return RecommendationResponse(task_id=task_id, as_of=as_of, **sorted_groups)
