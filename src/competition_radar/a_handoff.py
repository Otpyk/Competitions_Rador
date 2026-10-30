"""Project A's transport envelope into C's strict evidence contract."""

from pydantic import ValidationError

from .schemas import ResearchBatch, SourceDocument
from .validation import ContractError, ValidationIssue


def research_batch_from_a(result: dict) -> ResearchBatch:
    """Require explicit snapshots. A report or snippet never supplies missing body text."""
    if result.get("status") != "success":
        raise ContractError("A 的研究未成功，不能转为可用来源批次", [
            ValidationIssue("research_not_successful", "status", "研究失败或超时必须由 A 处理"),
        ])
    raw_sources = result.get("sources")
    if not isinstance(raw_sources, list):
        raise ContractError("A 的研究结果缺少来源列表", [
            ValidationIssue("missing_sources", "sources", "需要显式来源列表"),
        ])
    projected_sources = []
    issues = []
    required = SourceDocument.model_fields
    for index, source in enumerate(raw_sources):
        path = f"sources[{index}]"
        if not isinstance(source, dict):
            issues.append(ValidationIssue("invalid_source", path, "来源必须为 JSON 对象"))
            continue
        missing = set(required) - source.keys()
        for field in required:
            if field in missing:
                issues.append(ValidationIssue(
                    "source_snapshot_required", f"{path}.{field}",
                    f"A 需显式提供 {field}；不从报告或摘要推断",
                ))
        if missing:
            continue
        projected_sources.append({field: source[field] for field in required})
    if issues:
        raise ContractError("A→C 来源交接不完整：需要正文快照和元数据", issues)
    try:
        return ResearchBatch.model_validate({
            "task_id": result.get("task_id"),
            "query": result.get("query"),
            "sources": projected_sources,
        })
    except ValidationError as error:
        issues = [ValidationIssue(
            "invalid_research_snapshot", ".".join(str(part) for part in item["loc"]), item["msg"],
        ) for item in error.errors(include_input=False, include_url=False)]
        raise ContractError("A→C 来源快照不符合 v0.1 协议", issues) from error
