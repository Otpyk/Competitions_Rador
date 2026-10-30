"""Distinguish search gaps from work that belongs to A, B, C or the user.

Decisions preserve uncertainty: routing a field for review never verifies it.
"""

from .b_contracts import Competition, Evidence, FieldCheck
from .field_catalog import FIELD_SPECS


ACTION_OWNERS = {
    "search": "A", "fetch_source": "A", "repair_extraction": "C",
    # Keep machine owner codes separate from the explanatory UI label.
    "human_review": "B", "clarify_context": "A/C", "none": None,
}
ACTION_LABELS = {
    "search": "补充搜索", "fetch_source": "抓取或核对已有来源原文",
    "repair_extraction": "修正抽取结果", "human_review": "人工审查证据",
    "clarify_context": "补齐目标学校或赛事范围", "none": "已解决",
}
_UNKNOWN = {"unknown", "未知", "待确认", "待定", "none", "null", "n/a", "pending"}


def _known(value: str) -> bool:
    return bool(value.strip()) and value.strip().casefold() not in _UNKNOWN


def classify_next_action(competition: Competition, check: FieldCheck, candidates: list[Evidence]) -> tuple[str, str]:
    if check.status == "verified":
        return "none", "已有符合规则的证据。"
    if not all(_known(value) for value in (competition.name, competition.edition, check.scope)):
        return "clarify_context", "先明确目标赛事、届次和适用范围，不能用未明确的目标发起补查。"
    spec = FIELD_SPECS.get(check.field)
    campus_specific = check.scope.startswith("campus:") and _known(check.scope[7:])
    possible_global_exemption = any(item.value_kind == "not_applicable" for item in candidates)
    if (spec and spec.campus_only or check.field == "campus_deadline" and not possible_global_exemption) and not campus_specific:
        return "clarify_context", "该项需要具体学校；先补充目标学校，不能把任意学校的政策套用。"
    if check.status == "conflict":
        return "search", "证据存在冲突，需核对当届更正或补充通知；不能自动选择其中一个。"
    if "duplicate_evidence_id" in check.reasons:
        return "repair_extraction", "证据编号重复，先由 C 修正编号及对应原文，避免关联错位。"
    relevant = [item for item in candidates if item.edition == competition.edition and item.scope == check.scope]
    if not relevant:
        return "search", "缺少本届、目标范围的证据，需要补查具体赛事通知。"
    reasons = {reason for item in relevant for reason in item.review_reasons}
    if reasons & {"source_identity_mismatch", "source_identity_ambiguous", "source_context_identity_mismatch", "source_name_mismatch", "source_edition_mismatch"}:
        return "search", "已找到的页面身份与目标赛事或届次不符，需要寻找正确的当届通知。"
    # An existing validly reviewed but non-authoritative source cannot establish
    # the field; finding the correct authority is useful here.
    if all(item.source_verified and item.support == "supported" for item in relevant):
        if all("insufficient_source_type" in notes for notes in check.rejected_evidence.values()) and check.rejected_evidence:
            return "search", "现有来源无权独立证明这项结论，需要补查官方或对应学校的原始政策。"
    if reasons & {"source_snapshot_missing", "ambiguous_source_snapshot"}:
        return "fetch_source", "已有来源地址，但缺少可用原文或同一地址快照不一致；A 应先抓取并核对原文。"
    if reasons & {"quote_not_found", "quote_not_complete_paragraph", "claim_value_mismatch", "additional_eligibility_context", "eligibility_context_incomplete", "eligibility_conditions_omitted"}:
        return "repair_extraction", "已有资料，但摘录不完整、与原文不一致或遗漏限制；C 应依据同一页面重新抽取。"
    if reasons & {"source_not_approved", "ambiguous_source_approval"} or any(not item.source_verified for item in relevant):
        return "human_review", "已有候选来源，B 应先确认页面归属及适用范围；继续搜索不能替代来源审查。"
    if any(item.support != "supported" for item in relevant):
        return "human_review", "来源已有原文，但保守规则无法确认含义；交给 B 审查，保持待确认。"
    if check.rejected_evidence:
        return "repair_extraction", "现有证据的值或元信息不符合约定，先修正输入后重新核验。"
    return "search", "仍缺少可用证据，需要补查。"


def action_items(fields: dict[str, FieldCheck]) -> list[dict]:
    return [{"field": name, "label": FIELD_SPECS[name].label if name in FIELD_SPECS else name,
             "action": check.next_action, "action_label": ACTION_LABELS[check.next_action],
             "owner": ACTION_OWNERS[check.next_action], "reason": check.action_reason,
             "scope": check.scope, "evidence_ids": check.evidence_ids,
             "source_urls": check.source_urls,
             "candidate_evidence_refs": list(check.rejected_evidence)}
            for name, check in fields.items() if check.required and check.status != "verified"]
