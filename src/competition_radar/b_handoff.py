"""Offline B/C v3 alignment and snapshot tracing; no authority judgments."""

from datetime import date, datetime
import re
from typing import Annotated, Literal, Self, TypeAlias, get_args

from pydantic import AfterValidator, TypeAdapter, model_validator

from .schemas import ContractModel, HttpUrlString, NonEmptyStr, SourceDocument
from .validation import ContractError, ValidationIssue


BFieldName: TypeAlias = Literal[
    "competition_name", "competition_edition", "track", "organizer", "official_url",
    "eligibility", "participation_mode", "team_rules", "registration_start",
    "registration_deadline", "campus_deadline", "task_description", "deliverables",
    "submission_deadline", "attendance_mode", "venue", "registration_fee",
    "mandatory_fees", "registration_method", "registration_url",
    "registration_materials", "institutional_requirements", "schedule",
    "judging_criteria", "awards", "school_recognition", "technical_requirements",
    "work_rules", "preparation_resources", "expense_details", "contacts",
]
B_FIELD_NAMES: tuple[BFieldName, ...] = get_args(BFieldName)
B_REQUIRED_FIELDS = B_FIELD_NAMES[:22]
B_NA_FIELDS = frozenset({
    "track", "team_rules", "campus_deadline", "submission_deadline", "venue",
    "registration_url", "institutional_requirements",
})
B_HARD_CONSTRAINT_FIELDS = {
    "school_recognition_required": ("school_recognition",),
    "existing_work_only": ("work_rules",),
    "no_hardware": ("technical_requirements", "deliverables"),
    "avoid_exam_dates": ("schedule", "attendance_mode"),
    "total_budget_limit": ("expense_details", "registration_fee", "mandatory_fees"),
    "online_only": ("attendance_mode", "venue", "schedule"),
    "cross_school_team": ("team_rules",),
}
_DATE_FIELDS = {
    "registration_start", "registration_deadline", "campus_deadline", "submission_deadline",
}
_URL_FIELDS = {"official_url", "registration_url"}
_URL_ADAPTER = TypeAdapter(HttpUrlString)
_OFFSET_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})"
)


def _scope(value: str) -> str:
    if value == "global":
        return value
    school = value.removeprefix("campus:")
    if (
        not value.startswith("campus:") or not school.strip() or school != school.strip()
        or any(char in school for char in "\r\n\t")
    ):
        raise ValueError("scope must be global or campus: followed by a specific school")
    return value


BScope: TypeAlias = Annotated[NonEmptyStr, AfterValidator(_scope)]


class BEvidence(ContractModel):
    id: NonEmptyStr
    value: NonEmptyStr
    url: HttpUrlString
    quote: NonEmptyStr
    edition: NonEmptyStr | None
    scope: BScope
    value_kind: Literal["value", "not_applicable"]
    source_id: NonEmptyStr | None = None


class BField(ContractModel):
    value: NonEmptyStr | None
    evidence: list[BEvidence]


class BContest(ContractModel):
    id: NonEmptyStr
    name: NonEmptyStr
    edition: NonEmptyStr | None
    scope: BScope
    field_scopes: dict[BFieldName, BScope]
    fields: dict[BFieldName, BField]

    @model_validator(mode="after")
    def field_types_and_scopes(self) -> Self:
        missing = set(B_REQUIRED_FIELDS) - self.fields.keys()
        if missing:
            raise ValueError("missing core field objects: " + ", ".join(sorted(missing)))
        for name, field in self.fields.items():
            if name not in B_NA_FIELDS and any(
                item.value_kind == "not_applicable" for item in field.evidence
            ):
                raise ValueError(f"{name} does not support not_applicable evidence")
            if field.value is not None:
                if name in _DATE_FIELDS:
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", field.value):
                        date.fromisoformat(field.value)
                    elif _OFFSET_TIME.fullmatch(field.value):
                        datetime.fromisoformat(field.value)
                    else:
                        raise ValueError(f"{name} requires a complete date or ISO time with offset")
                elif name in _URL_FIELDS:
                    _URL_ADAPTER.validate_python(field.value)
            active = field.value is not None or bool(field.evidence)
            scope = self.field_scopes.get(name, self.scope)
            if active and (
                name == "school_recognition"
                or (name == "campus_deadline" and (
                    field.value is not None
                    or any(item.value_kind == "value" for item in field.evidence)
                ))
            ) and not scope.startswith("campus:"):
                raise ValueError(f"{name} requires a specific campus scope")
        return self


def required_b_fields(
    hard_constraints: list[str] | tuple[str, ...] = (),
    extra_required_fields: list[str] | tuple[str, ...] = (),
) -> tuple[BFieldName, ...]:
    """List required investigations, without asserting that constraints are met."""
    unknown = set(hard_constraints) - B_HARD_CONSTRAINT_FIELDS.keys()
    extra_unknown = set(extra_required_fields) - set(B_FIELD_NAMES)
    if unknown or extra_unknown:
        raise ContractError("未知硬条件或额外必须字段：" + ", ".join(sorted(unknown | extra_unknown)))
    required = set(B_REQUIRED_FIELDS) | set(extra_required_fields)
    for constraint in hard_constraints:
        required.update(B_HARD_CONSTRAINT_FIELDS[constraint])
    return tuple(name for name in B_FIELD_NAMES if name in required)


def validate_b_evidence(
    contests: list[BContest], sources: list[SourceDocument],
) -> list[ValidationIssue]:
    """Check IDs, scope, exact quotes and snapshot identity; never approve a source."""
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(ValidationIssue(code, path, message))

    source_by_id = {}
    for index, source in enumerate(sources):
        if source.source_id in source_by_id:
            add("duplicate_source_id", f"sources[{index}].source_id", "来源快照 ID 重复")
        source_by_id[source.source_id] = source
    contest_ids, evidence_ids = set(), set()
    for index, contest in enumerate(contests):
        path = f"contests[{index}]"
        if contest.id in contest_ids:
            add("duplicate_contest_id", f"{path}.id", "赛事 ID 重复")
        contest_ids.add(contest.id)
        for name, field in contest.fields.items():
            field_path = f"{path}.fields.{name}"
            if field.value is not None and not any(
                item.value_kind == "value" and item.value == field.value for item in field.evidence
            ):
                add("value_without_evidence", f"{field_path}.value", "字段值没有对应候选证据")
            if field.value is not None and any(
                item.value_kind == "not_applicable" for item in field.evidence
            ):
                add("not_applicable_value", f"{field_path}.value", "不适用声明须保留 null 字段值")
            target_scope = contest.field_scopes.get(name, contest.scope)
            for evidence_index, item in enumerate(field.evidence):
                evidence_path = f"{field_path}.evidence[{evidence_index}]"
                if item.id in evidence_ids:
                    add("duplicate_evidence_id", f"{evidence_path}.id", "证据 ID 在批次内重复")
                evidence_ids.add(item.id)
                if item.edition != contest.edition:
                    add("edition_mismatch", f"{evidence_path}.edition", "证据届次与目标届次不一致")
                if item.scope != target_scope:
                    add("scope_mismatch", f"{evidence_path}.scope", "证据范围与目标字段范围不一致")
                if item.source_id is not None:
                    source = source_by_id.get(item.source_id)
                    if source is None:
                        add("unknown_source", f"{evidence_path}.source_id", "找不到指定来源快照")
                    elif source.url != item.url:
                        add("source_url_mismatch", f"{evidence_path}.url", "证据 URL 与指定快照不一致")
                    elif item.quote not in source.content:
                        add("quote_not_found", f"{evidence_path}.quote", "证据片段未逐字出现在指定正文中")
                else:
                    matches = [source for source in sources if source.url == item.url]
                    exact = [source for source in matches if item.quote in source.content]
                    if not matches:
                        add("unknown_source_url", f"{evidence_path}.url", "没有该 URL 的独立正文快照")
                    elif not exact:
                        add("quote_not_found", f"{evidence_path}.quote", "证据片段未逐字出现在来源正文中")
                    elif len(exact) > 1:
                        add("ambiguous_snapshot", f"{evidence_path}.source_id", "多个快照包含同一片段，须指定 source_id")
    return issues


def export_b_contest(contest: BContest, sources: list[SourceDocument]) -> dict:
    """Export the 31-field B prototype only after mechanical tracing passes."""
    issues = validate_b_evidence([contest], sources)
    if issues:
        raise ContractError("B/C 交接证据校验失败", issues)
    result = contest.model_dump(mode="json")
    result["fields"] = {
        name: result["fields"].get(name, {"value": None, "evidence": []})
        for name in B_FIELD_NAMES
    }
    for field in result["fields"].values():
        for evidence in field["evidence"]:
            evidence.pop("source_id")
    return result
