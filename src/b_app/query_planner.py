"""Generate targeted search text from unresolved evidence requirements."""

from .b_contracts import Competition, SearchQuery, VerificationResult
from .field_catalog import FIELD_SPECS


FIELD_TERMS = {
    "registration_deadline": "报名截止日期 报名时间 官方通知",
    "eligibility": "参赛资格 参赛对象 官方竞赛章程",
    "registration_url": "官方报名入口 报名系统",
    "official_url": "主办方 官方网站 当届竞赛通知",
    "team_size": "组队人数 团队要求 官方章程",
    "organizer": "主办单位 官方竞赛通知",
}
FIELD_TERMS.update({name: spec.query_terms for name, spec in FIELD_SPECS.items()})


def plan_queries(competition: Competition, verification: VerificationResult) -> list[SearchQuery]:
    if verification.competition_id != competition.id:
        raise ValueError("Verification result belongs to a different competition")
    identity = " ".join(str(part).strip() for part in (competition.name, competition.edition) if str(part).strip())
    queries: list[SearchQuery] = []
    # User hard constraints and disputes have priority within a small budget.
    # Ties retain the requested field order.
    names = [name for name in verification.unresolved_fields
             if verification.fields[name].next_action == "search"]
    names.sort(key=lambda name: (
        0 if any(reason.startswith("用户") for reason in verification.fields[name].requirement_reasons) else 1,
        0 if verification.fields[name].status == "conflict" else 1,
    ))
    for name in names:
        check = verification.fields[name]
        scoped_identity = identity + (f" {check.scope}" if check.scope != "global" else "")
        target = FIELD_TERMS.get(name, f"{name} 官方说明")
        if check.status == "conflict":
            target += " 最新更正 延期说明 差异核实"
        queries.append(SearchQuery(
            competition_id=competition.id,
            field=name,
            text=f"{scoped_identity} {target}",
            reason="; ".join(check.requirement_reasons + check.reasons),
            scope=check.scope,
        ))
    return queries
