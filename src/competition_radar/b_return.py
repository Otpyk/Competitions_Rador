"""Strict consumer for B/C return v1; no B judgment or action execution."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Annotated, Literal
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from pydantic import AfterValidator, Field

from .b_handoff import (
    BContest, BFieldName, BScope, B_NA_FIELDS, B_REQUIRED_FIELDS, validate_b_evidence,
)
from .schemas import ContractModel, HttpUrlString, NonEmptyStr, PositiveInt, SourceDocument
from .validation import ContractError


BAction = Literal["search", "fetch_source", "repair_extraction", "human_review", "clarify_context", "none"]
_OWNERS = {
    "search": "A", "fetch_source": "A", "repair_extraction": "C",
    "human_review": "B", "clarify_context": "A/C",
}
_UNKNOWN = {
    "unknown", "pending", "missing", "null", "none", "n/a", "tbd",
    "待确认", "待核验", "待定", "未知", "暂无", "不详", "未公布", "暂未公布",
    "另行通知", "待通知", "待公布", "详见后续通知",
}
_NA_STATEMENTS = {
    "track": "本届不分赛道。",
    "team_rules": "本赛事仅接受个人参赛，无需组队。",
    "campus_deadline": "本赛事由个人直接报名，无校内报名环节。",
    "submission_deadline": "本赛事无需提交作品。",
    "venue": "本赛事全程线上，无需到场。",
    "registration_url": "本赛事仅由学校统一报名，无个人公开报名入口。",
    "institutional_requirements": "本赛事无需学校推荐、审核、签字或盖章，无校内名额限制，无需指导教师确认。",
}


def _wire_timestamp(value: str) -> str:
    if datetime.fromisoformat(value).utcoffset() is None:
        raise ValueError("verified_at must include a timezone")
    return value


class BFieldDecision(ContractModel):
    field: BFieldName
    status: Literal["verified", "pending", "conflict"]
    original_value: str | None
    verified_value: str | None
    reasons: list[str]
    evidence_ids: list[NonEmptyStr]
    conflicting_values: list[str]
    rejected_evidence: dict[NonEmptyStr, Annotated[list[NonEmptyStr], Field(min_length=1)]]
    required: bool
    requirement_reasons: list[str]
    value_kind: Literal["value", "not_applicable"] | None
    confirmed_statement: str | None
    scope: BScope
    next_action: BAction
    action_reason: str
    source_urls: list[HttpUrlString]


class BActionItem(ContractModel):
    field: BFieldName
    label: str
    action: BAction
    action_label: str
    owner: Literal["A", "B", "C", "A/C"]
    reason: str
    scope: BScope
    evidence_ids: list[NonEmptyStr]
    source_urls: list[HttpUrlString]
    candidate_evidence_refs: list[NonEmptyStr]


class BSearchRequest(ContractModel):
    action: Literal["search"]
    competition_id: NonEmptyStr
    contest_name: NonEmptyStr
    edition: NonEmptyStr | None
    target_fields: list[BFieldName]
    scope: BScope
    query: NonEmptyStr
    reason: str
    round: PositiveInt


class BSourceReview(ContractModel):
    evidence_id: NonEmptyStr
    source_verified: bool
    support: Literal["supported", "unknown", "unsupported"]
    reasons: list[str]


class BConsistencyIssue(ContractModel):
    code: Literal[
        "registration_start_after_deadline", "individual_only_vs_team_participation",
        "online_only_vs_required_onsite",
    ]
    fields: Annotated[list[BFieldName], Field(min_length=2)]
    message: NonEmptyStr
    evidence_ids: Annotated[list[NonEmptyStr], Field(min_length=2)]
    values: dict[BFieldName, NonEmptyStr]


class BVerification(ContractModel):
    competition_id: NonEmptyStr
    status: Literal["verified", "pending", "conflict"]
    fields: dict[BFieldName, BFieldDecision]
    missing_fields: list[BFieldName]
    unresolved_fields: list[BFieldName]
    coverage: float = Field(ge=0, le=1)
    required_fields: list[BFieldName]
    promoted_fields: list[BFieldName]
    optional_unresolved_fields: list[BFieldName]
    optional_conflict_fields: list[BFieldName]
    unrecognized_fields: list[NonEmptyStr]
    verified_at: Annotated[NonEmptyStr, AfterValidator(_wire_timestamp)]
    consistency_issues: list[BConsistencyIssue]
    verified_fields: dict[BFieldName, NonEmptyStr]
    not_applicable_fields: dict[BFieldName, NonEmptyStr]
    status_scope: Literal["required_fields_only"]
    action_items: list[BActionItem]


class BReturn(ContractModel):
    data_kind: NonEmptyStr
    notice: str
    verification: BVerification
    requests: list[BSearchRequest]
    source_reviews: list[BSourceReview]


@dataclass(frozen=True)
class ConsumedBReturn:
    """Detached snapshots; B's required-only status does not approve omitted fields."""

    candidate: BContest
    response: BReturn
    verified_values: dict[BFieldName, str]
    not_applicable_statements: dict[BFieldName, str]
    unresolved: dict[BFieldName, BFieldDecision]
    unreported_fields: tuple[BFieldName, ...]
    actions_by_owner: dict[str, list[BFieldDecision]]
    search_requests: list[BSearchRequest]
    required_fields: tuple[BFieldName, ...]


def _claim_value(field: str, value: str) -> str | None:
    """Mirror the frozen wire normalization, retaining URLs' path/query bytes."""
    if field.endswith("_url"):
        try:
            parts = urlsplit(value)
            if (re.search(r"[\x00-\x20\x7f]|\s", value) or parts.scheme.lower() not in {"http", "https"}
                    or not parts.hostname or parts.username is not None or parts.password is not None):
                return None
            _ = parts.port
            return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                               parts.query, parts.fragment))
        except ValueError:
            return None
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if not value or value.casefold() in _UNKNOWN:
        return None
    if field in {"registration_start", "registration_deadline", "campus_deadline", "submission_deadline"}:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return datetime.fromisoformat(value).date().isoformat()
            if re.match(r"^\d{4}-\d{2}-\d{2}T", value):
                moment = datetime.fromisoformat(value)
                if moment.utcoffset() is not None:
                    return moment.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            pass
        return None
    return value


def consume_b_return(
    payload: dict | BReturn, candidate: BContest, sources: list[SourceDocument],
    *, required_fields: tuple[BFieldName, ...],
) -> ConsumedBReturn:
    """Validate B's references and partition its result without executing any action.

    The caller supplies required fields from the actual hard-constraint context.
    Accepted and rejected evidence stay separate. Only positive source reviews
    can support usable values; receiving a pending result does not approve it.
    """
    from .b_handoff import B_FIELD_NAMES

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ContractError("B 返回交接校验失败：" + message)

    response = BReturn.model_validate(payload.model_dump() if isinstance(payload, BReturn) else payload)
    candidate = BContest.model_validate(candidate.model_dump()).model_copy(deep=True)
    tracing = validate_b_evidence([candidate], sources)
    if tracing:
        raise ContractError("B 返回所关联的 C/A 候选证据校验失败", tracing)
    verification = response.verification
    require(verification.competition_id == candidate.id, "赛事 ID 不一致")
    expected = set(required_fields)
    require(len(expected) == len(required_fields), "调用方必须字段重复")
    require(set(B_REQUIRED_FIELDS) <= expected <= set(B_FIELD_NAMES), "调用方必须字段不完整或未知")

    def same_fields(actual: list[str], expected_fields: set[str], label: str) -> None:
        require(len(actual) == len(set(actual)) and set(actual) == expected_fields, label + "不一致或重复")

    same_fields(verification.required_fields, expected, "required_fields")
    same_fields(verification.promoted_fields, expected - set(B_REQUIRED_FIELDS), "promoted_fields")
    require(expected <= verification.fields.keys(), "缺少必须字段裁决")
    active = {key for key, field in candidate.fields.items() if field.value is not None or field.evidence}
    require(verification.fields.keys() == expected | active, "必须字段及有值或证据的拓展字段裁决不一致")
    require(len(verification.unrecognized_fields) == len(set(verification.unrecognized_fields)),
            "unrecognized_fields 重复")
    require(not set(verification.unrecognized_fields) & set(B_FIELD_NAMES),
            "unrecognized_fields 包含已知字段")

    evidence = {
        item.id: (key, item)
        for key, field in candidate.fields.items() for item in field.evidence
    }
    reviews = {item.evidence_id: item for item in response.source_reviews}
    require(len(reviews) == len(response.source_reviews), "source_reviews 引用重复")
    require(reviews.keys() == evidence.keys(), "source_reviews 缺失或引用了无关联证据")
    verified_values, not_applicable, unresolved, actions = {}, {}, {}, {}
    checked_values = candidate.model_dump()
    for key, decision in verification.fields.items():
        original = candidate.fields.get(key)
        require(decision.field == key, "字段字典键与 field 不一致")
        require(decision.original_value == (original.value if original else None), key + "原候选值被改写")
        require(decision.scope == candidate.field_scopes.get(key, candidate.scope), key + "范围不一致")
        require(decision.required == (key in expected), key + "必须项标记不一致")
        require(len(decision.evidence_ids) == len(set(decision.evidence_ids)), key + "证据 ID 重复")
        require(len(decision.conflicting_values) == len(set(decision.conflicting_values)), key + "冲突值重复")
        selected = []
        for evidence_id in decision.evidence_ids:
            require(evidence_id in evidence, key + "引用无关联证据")
            source_field, item = evidence[evidence_id]
            require(source_field == key, key + "引用其他字段证据")
            review = reviews[evidence_id]
            require(review.source_verified and review.support == "supported", key + "采纳证据未获 B 来源和支持双重确认")
            if item.value_kind == "not_applicable":
                require(item.value == _NA_STATEMENTS.get(key), key + "采纳证据不是协议允许的不适用声明")
            selected.append(item)
        for evidence_id in decision.rejected_evidence:
            require(evidence_id in evidence and evidence[evidence_id][0] == key, key + "拒绝列表引用无关联或其他字段证据")
        candidate_evidence = {item.id for item in original.evidence} if original else set()
        require(set(decision.evidence_ids) | decision.rejected_evidence.keys() == candidate_evidence,
                key + "候选证据缺少采纳或拒绝说明")
        require(len(decision.source_urls) == len(set(decision.source_urls)), key + "来源 URL 重复")
        candidate_urls = {item.url for item in original.evidence} if original else set()
        require(set(decision.source_urls) == candidate_urls, key + "来源 URL 与候选证据不一致")
        if decision.status == "verified":
            require(bool(selected), key + "已核验结论缺少候选证据")
            require(all(item.id in reviews for item in selected), key + "已核验证据缺少 B source_reviews")
            require(decision.next_action == "none" and not decision.conflicting_values,
                    key + "已核验字段仍有动作或冲突")
            require(not set(decision.evidence_ids) & decision.rejected_evidence.keys(), key + "已核验证据同时被拒绝")
            require(all(item.value_kind == decision.value_kind for item in selected), key + "证据种类不一致")
            if decision.value_kind == "value":
                require(decision.verified_value is not None and decision.confirmed_statement is None,
                        key + "普通事实值/不适用声明不一致")
                require(bool(decision.verified_value) and decision.verified_value == _claim_value(key, decision.verified_value)
                        and all(decision.verified_value == _claim_value(key, item.value) for item in selected),
                        key + "已核验值与候选证据的协议归一结果不一致")
                verified_values[key] = decision.verified_value
                checked_values["fields"].setdefault(key, {"value": None, "evidence": []})["value"] = decision.verified_value
            else:
                require(key in B_NA_FIELDS and decision.value_kind == "not_applicable",
                        key + "不支持该不适用种类")
                require(decision.verified_value is None and decision.confirmed_statement is not None,
                        key + "不适用声明须与普通值分开")
                require(all(decision.confirmed_statement == item.value
                            for item in selected), key + "不适用声明与候选证据不一致")
                not_applicable[key] = decision.confirmed_statement
        else:
            require(decision.verified_value is None and decision.confirmed_statement is None
                    and decision.value_kind is None, key + "未核验值泄漏到可采用结果")
            require(decision.next_action != "none", key + "未解决字段缺少下一步动作")
            if decision.status == "pending":
                require(not selected and not decision.conflicting_values, key + "待确认字段包含采纳证据或冲突值")
            else:
                require(bool(selected), key + "冲突字段缺少采纳证据")
                if decision.conflicting_values:
                    claims = {(item.value_kind, _claim_value(key, item.value)) for item in selected}
                    require(all(value is not None for _, value in claims), key + "冲突证据含无效值")
                    expected_values = sorted("不适用：" + value if kind == "not_applicable" else value
                                             for kind, value in claims)
                    require(len(claims) > 1 and decision.conflicting_values == expected_values,
                            key + "冲突值与采纳证据不一致")
            unresolved[key] = decision
            actions.setdefault(_OWNERS[decision.next_action], []).append(decision)
    # Apply only existing BContest's value-type checks, not its semantic evidence judgments.
    BContest.model_validate(checked_values)
    require(verification.verified_fields == verified_values, "verified_fields 与逐字段裁决不一致")
    require(verification.not_applicable_fields == not_applicable, "not_applicable_fields 与逐字段裁决不一致")
    same_fields(verification.missing_fields,
                {key for key, item in verification.fields.items() if item.original_value is None}, "missing_fields")
    same_fields(verification.unresolved_fields, set(unresolved) & expected, "unresolved_fields")
    same_fields(verification.optional_unresolved_fields, set(unresolved) - expected, "optional_unresolved_fields")
    same_fields(verification.optional_conflict_fields,
                {key for key in unresolved if key not in expected and unresolved[key].status == "conflict"},
                "optional_conflict_fields")
    expected_status = "conflict" if any(unresolved[key].status == "conflict" for key in expected & unresolved.keys()) else (
        "pending" if expected & unresolved.keys() else "verified"
    )
    require(verification.status == expected_status, "required_fields_only 总状态与必须项裁决不一致")
    coverage = (len(expected) - len(expected & unresolved.keys())) / len(expected)
    require(abs(verification.coverage - coverage) < 1e-12, "必须项覆盖度不一致")

    issue_fields = set()
    allowed_pairs = {
        "registration_start_after_deadline": [{"registration_start", "registration_deadline"}],
        "individual_only_vs_team_participation": [{"team_rules", "participation_mode"}],
        "online_only_vs_required_onsite": [{"venue", "attendance_mode"}, {"venue", "schedule"}],
    }
    for issue in verification.consistency_issues:
        require(len(issue.fields) == len(set(issue.fields)) and set(issue.fields) in allowed_pairs[issue.code],
                "跨字段冲突代码与字段不一致")
        require(set(issue.fields) <= verification.fields.keys() and set(issue.values) == set(issue.fields),
                "跨字段冲突引用缺失字段或值")
        decisions = [verification.fields[key] for key in issue.fields]
        require(all(item.status == "conflict" and issue.code in item.reasons for item in decisions),
                "跨字段冲突缺少对应冲突裁决")
        refs = list(dict.fromkeys(ref for item in decisions for ref in item.evidence_ids))
        require(issue.evidence_ids == refs, "跨字段冲突证据与裁决不一致")
        require(len({item.scope for item in decisions}) == 1, "跨字段冲突混用范围")
        for evidence_id in issue.evidence_ids:
            key, item = evidence[evidence_id]
            require(_claim_value(key, item.value) == issue.values[key], "跨字段冲突值与证据不一致")
        issue_fields.update(issue.fields)
    require(all(item.conflicting_values or key in issue_fields for key, item in unresolved.items()
                if item.status == "conflict"), "冲突字段缺少不同值或跨字段冲突说明")

    item_fields = []
    for item in verification.action_items:
        require(item.field in unresolved and item.field in expected, "action_items 引用了已解决或非必须字段")
        decision = unresolved[item.field]
        require(item.action == decision.next_action and item.owner == _OWNERS[item.action], "动作或负责人不一致")
        require(item.scope == decision.scope and item.reason == decision.action_reason, "动作范围或原因不一致")
        require(item.evidence_ids == decision.evidence_ids and item.source_urls == decision.source_urls,
                "动作证据引用与字段裁决不一致")
        require(item.candidate_evidence_refs == list(decision.rejected_evidence), "动作候选证据与拒绝证据不一致")
        item_fields.append(item.field)
    same_fields(item_fields, expected & unresolved.keys(), "action_items 字段")
    searched = []
    for request in response.requests:
        require(request.competition_id == candidate.id and request.contest_name == candidate.name
                and request.edition == candidate.edition, "搜索请求赛事/届次不一致")
        require(bool(request.target_fields), "搜索请求无目标字段")
        for key in request.target_fields:
            require(key in expected and key in unresolved and unresolved[key].next_action == "search",
                    "只有标为 search 的未解决必须字段能生成补搜请求")
            require(request.scope == unresolved[key].scope, "搜索请求范围不一致")
            searched.append(key)
        require(candidate.name in request.query and candidate.edition is not None and candidate.edition in request.query,
                "搜索正文缺少赛事名称或届次")
        require(request.scope == "global" or request.scope in request.query, "搜索正文缺少目标范围")
    same_fields(searched, {key for key in expected & unresolved.keys()
                           if unresolved[key].next_action == "search"}, "requests 目标字段")
    return ConsumedBReturn(
        candidate, response, verified_values, not_applicable, unresolved,
        tuple(key for key in B_FIELD_NAMES if key not in verification.fields), actions, response.requests,
        tuple(required_fields),
    )
