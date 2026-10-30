"""Conservative C results for the 31-field B protocol, without text inference."""

from datetime import date, datetime, timezone
import re
from typing import Literal

from .b_handoff import BContest
from .b_return import BReturn, ConsumedBReturn, consume_b_return
from .registration import assess_registration
from .schemas import (
    AwareTimestamp, CandidateContest, ContractModel, EligibilityAssessment,
    EvidenceRef, FIELD_NAMES, FieldDecision, NonEmptyStr, RegistrationAssessment,
    RegistrationTime, RegistrationTimeClaim, SourceDocument, UserProfile,
    VerificationResult,
)
from .validation import ContractError


class BRecommendationItem(ContractModel):
    record_id: NonEmptyStr
    candidate: BContest
    b_return: BReturn
    context: dict[str, str]
    context_status: Literal["unverified_search_hint"] = "unverified_search_hint"
    eligibility: EligibilityAssessment
    registration: RegistrationAssessment
    reasons: list[NonEmptyStr]
    pending_items: list[NonEmptyStr]


class BRecommendationResponse(ContractModel):
    task_id: NonEmptyStr
    as_of: AwareTimestamp
    ordering: Literal["input_order"] = "input_order"
    interest_matching: Literal["unavailable_no_verified_tags"] = "unavailable_no_verified_tags"
    recommended: list[BRecommendationItem]
    pending: list[BRecommendationItem]
    excluded: list[BRecommendationItem]


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?P<seconds>:\d{2})?"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)


def _selected_evidence(result: ConsumedBReturn, field: str):
    decision = result.response.verification.fields[field]
    selected = set(decision.evidence_ids)
    return [item for item in result.candidate.fields[field].evidence if item.id in selected]


def _registration_time(result: ConsumedBReturn, field: str) -> RegistrationTime | None:
    value = result.verified_values.get(field)
    if value is None:
        return None
    if _DATE.fullmatch(value):
        # A calendar date does not establish a timezone or a deadline hour.
        return RegistrationTime(date=value, time=None, timezone=None)
    parsed = []
    for item in _selected_evidence(result, field):
        match = _TIME.fullmatch(item.value)
        if match is None:
            return None
        moment = datetime.fromisoformat(item.value)
        if moment.utcoffset() is None or moment.microsecond:
            return None
        parsed.append((match, moment))
    if not parsed:
        return None
    # B normalizes equivalent instants to UTC and adds seconds. Keep the
    # coarsest original precision so HH:MM never becomes an exact second.
    minute_precision = any(match.group("seconds") is None for match, _ in parsed)
    moment = datetime.fromisoformat(value).astimezone(timezone.utc)
    return RegistrationTime(
        date=moment.date(), time=moment.strftime("%H:%M" if minute_precision else "%H:%M:%S"),
        timezone="UTC",
    )


def _registration(result: ConsumedBReturn, sources: list[SourceDocument], as_of: datetime):
    fields = ("registration_start", "registration_deadline")
    verified = [field for field in fields if field in result.verified_values]
    if len(verified) == 2 and len({result.response.verification.fields[field].scope for field in fields}) != 1:
        reason = "已核验报名开始与截止的适用范围不同，不能拼接为同一报名区间。"
        return RegistrationAssessment(status="unknown", reasons=[reason], pending_items=[reason])
    claims, decisions = [], []
    for field in FIELD_NAMES:
        value = _registration_time(result, field) if field in fields else None
        claim_id = f"{result.candidate.id}:{field}" if value is not None else None
        reason = "非报名时间投影字段。"
        if field in fields:
            decision = result.response.verification.fields[field]
            reason = ("采用 B 已核验时间并保留原始精度。" if value is not None else
                      "B 未核验该时间，或时间精度尚不能安全用于报名判断。")
            if value is not None:
                evidence = []
                for item in _selected_evidence(result, field):
                    source = next(source for source in sources if (
                        source.source_id == item.source_id if item.source_id is not None else
                        source.url == item.url and item.quote in source.content
                    ))
                    evidence.append(EvidenceRef(source_id=source.source_id, quote=item.quote))
                claims.append(RegistrationTimeClaim(
                    claim_id=claim_id, field=field, value=value, evidence=evidence,
                ))
            else:
                reason += " " + "；".join(decision.reasons)
        decisions.append(FieldDecision(
            field=field, status="verified" if value is not None else "missing",
            selected_claim_id=claim_id, reason=reason,
        ))
    candidate = CandidateContest(record_id=result.candidate.id, member_ids=[result.candidate.id], claims=claims)
    verification = VerificationResult(
        record_id=candidate.record_id, fields=decisions,
        verification_status=result.response.verification.status,
        verified_at=result.response.verification.verified_at,
    )
    return assess_registration(candidate, verification, as_of)


def _deadline_date(result: ConsumedBReturn) -> date | None:
    value = result.verified_values.get("registration_deadline")
    if value is None:
        return None
    if _DATE.fullmatch(value):
        return date.fromisoformat(value)
    # Date filters concern the source's stated calendar date. UTC normalization
    # can cross midnight; differing source-local dates need clarification.
    selected = _selected_evidence(result, "registration_deadline")
    if any(_TIME.fullmatch(item.value) is None for item in selected):
        return None
    dates = {datetime.fromisoformat(item.value).date() for item in selected}
    return dates.pop() if len(dates) == 1 else None


def recommend_b_returns(
    task_id: str, profile: UserProfile, sources: list[SourceDocument],
    returns: list[ConsumedBReturn], as_of: datetime,
    *, contexts: dict[str, dict[str, str]] | None = None,
) -> BRecommendationResponse:
    """Preserve B's judgments and group results using only supported C rules.

    The 31-field protocol supplies eligibility text, not EligibilityRules.
    This entry point therefore keeps personal eligibility unknown. It can
    exclude verified closed/out-of-range records; other records remain pending.
    Context is retained as an unverified hint, never as an eligibility fact.
    """
    if not isinstance(as_of, datetime) or as_of.utcoffset() is None:
        raise ContractError("as_of 必须为带 UTC 偏移的 datetime")
    identifiers = [item.candidate.id for item in returns]
    if len(set(identifiers)) != len(identifiers):
        raise ContractError("B 返回赛事 ID 重复")
    contexts = contexts or {}
    if set(contexts) - set(identifiers):
        raise ContractError("上下文引用了本批次之外的赛事")
    groups = {"recommended": [], "pending": [], "excluded": []}
    for received in returns:
        # ConsumedBReturn contains mutable models; recheck the authoritative
        # candidate/envelope instead of trusting cached derived dictionaries.
        result = consume_b_return(
            received.response, received.candidate, sources,
            required_fields=received.required_fields,
        )
        reason = ("已核验资格仍为原文，尚未转为已确认的学历、专业、年级和团队人数规则；"
                  "不能据此自动认定用户符合或不符合。" if "eligibility" in result.verified_values else
                  "参赛资格尚未经 B 核验，无法判断用户资格。")
        eligibility = EligibilityAssessment(status="unknown", reasons=[reason], pending_items=[reason])
        registration = _registration(result, sources, as_of)
        pending = [*eligibility.pending_items, *registration.pending_items]
        reasons = [*eligibility.reasons, *registration.reasons]
        deadline = _deadline_date(result)
        outside_range = deadline is not None and (
            profile.deadline_from is not None and deadline < profile.deadline_from
            or profile.deadline_to is not None and deadline > profile.deadline_to
        )
        if deadline is None and (profile.deadline_from is not None or profile.deadline_to is not None):
            pending.append("缺少可采用的报名截止日历日期，无法核对用户要求的日期范围。")
        if outside_range:
            reasons.append(f"已核验报名截止日期 {deadline.isoformat()} 不在用户要求的日期范围内。")
        bucket = "excluded" if registration.status == "closed" or outside_range else "pending"
        if bucket == "pending":
            reasons.append("尚不具备资格已确认且报名进行中的推荐条件。")
        reasons.append("31字段协议没有已核验兴趣标签，本接口不计算兴趣命中或分数。")
        for field, decision in result.unresolved.items():
            pending.append(f"{field}（{decision.scope}）：{decision.action_reason}")
        groups[bucket].append(BRecommendationItem(
            record_id=result.candidate.id, candidate=result.candidate, b_return=result.response,
            context=contexts.get(result.candidate.id, {}), eligibility=eligibility,
            registration=registration, reasons=reasons, pending_items=list(dict.fromkeys(pending)),
        ))
    return BRecommendationResponse(task_id=task_id, as_of=as_of, **groups)
