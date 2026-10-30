"""Compare verified registration boundaries while preserving their precision."""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Literal, cast
from zoneinfo import ZoneInfo

from .schemas import (
    CandidateContest,
    RegistrationAssessment,
    RegistrationTime,
    VerificationResult,
)
from .validation import ContractError, selected_claim, validate_verification


@dataclass(frozen=True)
class _Boundary:
    value: RegistrationTime
    zone: ZoneInfo
    lower: datetime | None
    upper: datetime | None
    precision: Literal["day", "minute", "second"]
    issue: str | None


def _unique_utc(local: datetime, zone: ZoneInfo) -> tuple[datetime | None, str | None]:
    """Round trips distinguish a normal wall time from a gap or two DST folds."""
    instants: set[datetime] = set()
    for fold in (0, 1):
        try:
            instant = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if instant.astimezone(zone).replace(tzinfo=None) == local:
                instants.add(instant)
        except OverflowError:
            return None, "该本地时刻超出运行时可表示的 UTC 日期范围"
    if not instants:
        return None, "该本地时刻因时区时钟变更而不存在"
    if len(instants) != 1:
        return None, "该本地时刻因时区时钟回拨而对应多个瞬间"
    return instants.pop(), None


def _build_boundary(value: RegistrationTime, zone: ZoneInfo) -> _Boundary:
    if value.time is None:
        # These bounds represent possible instants, never an imputed event time.
        lower, _ = _unique_utc(datetime.combine(value.date, time.min), zone)
        upper, _ = _unique_utc(datetime.combine(value.date, time.max), zone)
        issue = "该日期的边界无法在指定时区定位" if lower is None and upper is None else None
        return _Boundary(value, zone, lower, upper, "day", issue)

    local = datetime.combine(value.date, time.fromisoformat(value.time))
    lower, issue = _unique_utc(local, zone)
    if len(value.time) == 8:
        return _Boundary(value, zone, lower, lower, "second", issue)

    local_upper = local.replace(second=59, microsecond=999999)
    upper, upper_issue = _unique_utc(local_upper, zone)
    return _Boundary(value, zone, lower, upper, "minute", issue or upper_issue)


def _description(boundary: _Boundary) -> str:
    value = boundary.value
    clock = f" {value.time}" if value.time is not None else "（日精度）"
    return f"{value.date.isoformat()}{clock}，时区 {value.timezone}"


def _relation(
    boundary: _Boundary, as_of: datetime
) -> Literal["before", "at", "after", "unknown"]:
    if boundary.issue is not None:
        return "unknown"
    if boundary.precision == "day":
        if boundary.lower is not None and as_of < boundary.lower:
            return "before"
        if boundary.upper is not None and as_of > boundary.upper:
            return "after"
        try:
            local_date = as_of.astimezone(boundary.zone).date()
        except OverflowError:
            return "unknown"
        if local_date < boundary.value.date:
            return "before"
        if local_date > boundary.value.date:
            return "after"
        return "unknown"

    if boundary.lower is None or boundary.upper is None:
        return "unknown"
    if as_of < boundary.lower:
        return "before"
    if as_of > boundary.upper:
        return "after"
    if boundary.precision == "second":
        return "at"
    return "unknown"


def assess_registration(
    candidate: CandidateContest,
    verification: VerificationResult,
    as_of: datetime,
) -> RegistrationAssessment:
    """Prove closed, upcoming or open; otherwise retain an unknown status."""
    validate_verification(candidate, verification)
    if not isinstance(as_of, datetime) or as_of.utcoffset() is None:
        raise ContractError("as_of 必须是带 UTC 偏移的 datetime。")

    boundaries: dict[str, _Boundary | None] = {}
    relations: dict[str, str] = {}
    reasons: list[str] = []
    pending: list[str] = []
    for field, label in (
        ("registration_start", "报名开始"),
        ("registration_deadline", "报名截止"),
    ):
        claim = selected_claim(candidate, verification, field)
        if claim is None:
            decision = next(item for item in verification.fields if item.field == field)
            reason = f"{label}字段尚未经 B 核验（{decision.status}）：{decision.reason}"
            boundaries[field] = None
            relations[field] = "unknown"
            reasons.append(reason)
            pending.append(reason)
            continue

        value = cast(RegistrationTime, claim.value)
        if value.timezone is None:
            reason = f"已核验{label}缺少明确时区，不能确定对应报名边界。"
            boundaries[field] = None
            relations[field] = "unknown"
            reasons.append(reason)
            pending.append(reason)
            continue

        boundary = _build_boundary(value, ZoneInfo(value.timezone))
        boundaries[field] = boundary
        relation = _relation(boundary, as_of)
        relations[field] = relation
        description = _description(boundary)
        if boundary.issue is not None:
            reason = f"{label}（{description}）无法唯一定位：{boundary.issue}，需确认具体 UTC 偏移。"
            pending.append(reason)
        elif relation == "unknown":
            precision = "日" if boundary.precision == "day" else "分钟"
            reason = f"{label}仅有{precision}精度（{description}），当前无法确定该边界状态。"
            pending.append(reason)
        elif relation == "before":
            reason = f"当前时刻尚未到已核验{label}边界（{description}）。"
        elif relation == "after":
            reason = f"当前时刻已晚于已核验{label}边界（{description}）。"
        else:
            reason = f"当前时刻恰为已核验{label}端点（{description}），按包含端点处理。"
        reasons.append(reason)

    start = boundaries["registration_start"]
    deadline = boundaries["registration_deadline"]
    if (
        start is not None
        and deadline is not None
        and start.issue is None
        and deadline.issue is None
        and start.lower is not None
        and deadline.upper is not None
        and start.lower > deadline.upper
    ):
        raise ContractError(
            "已核验报名开始的最早可能时刻晚于报名截止的最晚可能时刻："
            f"开始 {_description(start)}；截止 {_description(deadline)}。"
        )

    if start is not None and deadline is not None:
        incomplete_day = any(
            boundary.precision == "day"
            and (boundary.lower is None or boundary.upper is None)
            for boundary in (start, deadline)
        )
        ordered = (
            start.issue is None
            and deadline.issue is None
            and start.upper is not None
            and deadline.lower is not None
            and start.upper <= deadline.lower
        )
        if incomplete_day and not ordered:
            reason = "日精度区间端点无法在指定时区完整定位，尚不能排除报名开始与截止边界矛盾。"
            reasons.append(reason)
            pending.append(reason)
            return RegistrationAssessment(status="unknown", reasons=reasons, pending_items=pending)

    if relations["registration_deadline"] == "after":
        status = "closed"
        reasons.append("已能证明报名截止边界已过。")
    elif start is not None and relations["registration_start"] == "before":
        status = "upcoming"
        reasons.append("已能证明报名开始边界尚未到。")
        pending.append(f"等待已核验报名开始时间：{_description(start)}。")
    elif relations["registration_start"] in ("at", "after") and relations[
        "registration_deadline"
    ] in ("before", "at"):
        status = "open"
        reasons.append("已能证明当前位于已核验报名区间内（包含精确端点）。")
    else:
        status = "unknown"
        reasons.append("现有已核验信息不足以证明报名已截止、尚未开始或正在进行。")

    return RegistrationAssessment(status=status, reasons=reasons, pending_items=pending)
