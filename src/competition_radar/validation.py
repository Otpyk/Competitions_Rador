"""Mechanical evidence and decision checks; authority is decided by B."""

from dataclasses import dataclass

from .schemas import CandidateContest, FieldClaim, SourceDocument, VerificationResult


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


class ContractError(ValueError):
    def __init__(self, message: str, issues: list[ValidationIssue] | None = None):
        self.issues = issues if issues is not None else [ValidationIssue("contract_error", "input", message)]
        super().__init__(message)


def validate_evidence(
    candidates: list[CandidateContest], sources: list[SourceDocument]
) -> list[ValidationIssue]:
    """Return structural problems, without interpreting what a quote proves."""
    issues = []
    source_by_id = {}
    for index, source in enumerate(sources):
        if source.source_id in source_by_id:
            issues.append(ValidationIssue(
                "duplicate_source_id", f"sources[{index}].source_id",
                f"来源 ID 重复：{source.source_id}",
            ))
        source_by_id[source.source_id] = source

    record_ids, member_ids, claim_ids = set(), set(), set()
    for index, candidate in enumerate(candidates):
        path = f"candidates[{index}]"
        if candidate.record_id in record_ids:
            issues.append(ValidationIssue(
                "duplicate_record_id", f"{path}.record_id", "赛事记录 ID 重复",
            ))
        record_ids.add(candidate.record_id)
        for member_id in candidate.member_ids:
            if member_id in member_ids:
                issues.append(ValidationIssue(
                    "overlapping_members", f"{path}.member_ids",
                    f"原始赛事记录重复出现在多个记录中：{member_id}",
                ))
            member_ids.add(member_id)
        for claim_index, claim in enumerate(candidate.claims):
            claim_path = f"{path}.claims[{claim_index}]"
            if claim.claim_id in claim_ids:
                issues.append(ValidationIssue(
                    "duplicate_claim_id", f"{claim_path}.claim_id", "候选 ID 在批次内重复",
                ))
            claim_ids.add(claim.claim_id)
            for evidence_index, evidence in enumerate(claim.evidence):
                evidence_path = f"{claim_path}.evidence[{evidence_index}]"
                source = source_by_id.get(evidence.source_id)
                if source is None:
                    issues.append(ValidationIssue(
                        "unknown_source", f"{evidence_path}.source_id",
                        f"找不到来源快照：{evidence.source_id}",
                    ))
                elif evidence.quote not in source.content:
                    issues.append(ValidationIssue(
                        "quote_not_found", f"{evidence_path}.quote", "证据片段未逐字出现在来源正文中",
                    ))
    return issues


def validate_verification(
    candidate: CandidateContest, verification: VerificationResult
) -> None:
    """Check B's references against the provided candidate; do not redo B's judgment."""
    issues = []
    if candidate.record_id != verification.record_id:
        issues.append(ValidationIssue(
            "record_mismatch", "verification.record_id", "核验结果与候选赛事 ID 不一致",
        ))
    claim_by_id = {claim.claim_id: claim for claim in candidate.claims}
    for decision in verification.fields:
        path = f"verification.fields.{decision.field}"
        exists = any(claim.field == decision.field for claim in candidate.claims)
        if decision.status == "missing" and exists:
            issues.append(ValidationIssue(
                "unexpected_claim", path, "missing 字段仍有候选值",
            ))
        elif decision.status != "missing" and not exists:
            issues.append(ValidationIssue(
                "missing_claim", path, "非 missing 字段必须有候选值",
            ))
        if decision.status == "verified":
            claim = claim_by_id.get(decision.selected_claim_id)
            if claim is None or claim.field != decision.field:
                issues.append(ValidationIssue(
                    "invalid_selection", f"{path}.selected_claim_id",
                    "选用候选必须属于当前赛事和对应字段",
                ))
    if issues:
        raise ContractError("核验引用校验失败：" + "；".join(i.message for i in issues), issues)


def selected_claim(
    candidate: CandidateContest, verification: VerificationResult, field: str
) -> FieldClaim | None:
    """Return only a B-selected claim. The caller must validate references first."""
    decision = next(d for d in verification.fields if d.field == field)
    if decision.status != "verified":
        return None
    return next(c for c in candidate.claims if c.claim_id == decision.selected_claim_id)
