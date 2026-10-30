"""B-owned nine-field compatibility bridge; canonical assessment uses 22.

No mutable inter-request cache. No automatic approvals or lost evidence refs.
Structured eligibility stays JSON; dates with unknown timezones stay unknown.
"""
from datetime import datetime, time, timezone
import json
from zoneinfo import ZoneInfo
from b_app.b_contracts import Competition, Evidence
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import expected_scope
from b_app.frozen import FIELD_MAP, load_approvals, load_contexts, load_policy
from b_app.source_review import SourceSnapshot, review_competition

FIELDS = ("name", "organizer", "edition", "track", "stage", "tags", "eligibility",
          "registration_start", "registration_deadline", "official_url", "registration_url")
_FIELD_MAP = FIELD_MAP

def _stringify(value, field):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "date" in value:
        date_part, time_part, tz = value.get("date"), value.get("time"), value.get("timezone")
        if time_part:
            if not tz:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            try:
                return datetime.combine(datetime.fromisoformat(date_part).date(),
                                        time.fromisoformat(time_part), ZoneInfo(tz)).isoformat()
            except (ValueError, TypeError, KeyError):
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(date_part or "")
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

def _identity(candidate, field):
    values = {claim["value"] for claim in candidate["claims"]
              if claim["field"] == field and isinstance(claim["value"], str) and claim["value"].strip()}
    return next(iter(values)) if len(values) == 1 else ""

def _to_b_competition(candidate, sources_by_id, contexts=None):
    contexts = load_contexts() if contexts is None else contexts
    context = contexts.get(candidate["record_id"], {})
    edition = _identity(candidate, "edition")
    name = _identity(candidate, "name") or candidate["record_id"]
    comp = Competition(candidate["record_id"], name, edition,
                       scope=context.get("scope", "unknown"),
                       field_scopes=dict(context.get("field_scopes", {})))
    values = {}
    for claim in candidate["claims"]:
        mapped = FIELD_MAP.get(claim["field"])
        if not mapped:
            continue
        value = _stringify(claim["value"], claim["field"])
        values.setdefault(mapped, []).append(value)
        for index, ref in enumerate(claim.get("evidence", [])):
            source = sources_by_id.get(ref.get("source_id"), {})
            comp.evidence.append(Evidence(
                id=f"{claim['claim_id']}::e{index}", field=mapped, value=value,
                url=source.get("url", ""), quote=ref.get("quote", ""),
                edition=edition, scope=expected_scope(comp, mapped), source_id=ref.get("source_id")))
    comp.fields = {field: items[0] if len(set(items)) == 1 else None for field, items in values.items()}
    return comp

def evaluate_candidates(competitions, *, sources):
    policy, approvals, contexts = load_policy("legacy_11_bridge"), load_approvals(), load_contexts()
    sources_by_id = {source["source_id"]: source for source in sources}
    if len(sources_by_id) != len(sources):
        raise ValueError("Duplicate source IDs")
    snapshots = [SourceSnapshot(s["url"], s.get("content", ""), s.get("fetched_at"), s["source_id"]) for s in sources]
    evaluated = []
    for candidate in competitions:
        comp = _to_b_competition(candidate, sources_by_id, contexts)
        context = contexts.get(candidate["record_id"], {})
        matching_identity = (comp.name == context.get("expected_name")
                             and comp.edition == context.get("expected_edition"))
        reviewed, notes = review_competition(comp, approved_sources=approvals if matching_identity else [], snapshots=snapshots)
        result = verify_competition(reviewed, policy)
        for field, reason in context.get("context_holds", {}).items():
            if field in result.fields and result.fields[field].status != "verified":
                result.fields[field].next_action = "clarify_context"
                result.fields[field].action_reason = reason
        evaluated.append((candidate, reviewed, result, notes))
    return evaluated

def _to_c_verification(candidate, result):
    claim_fields = {claim["field"] for claim in candidate["claims"]}
    origin = {f"{claim['claim_id']}::e{i}": claim["claim_id"]
              for claim in candidate["claims"] for i, _ in enumerate(claim.get("evidence", []))}
    decisions = []
    for field in FIELDS:
        mapped = FIELD_MAP.get(field)
        check = result.fields.get(mapped) if mapped else None
        status = "unverified" if field in claim_fields else "missing"
        selected = None
        reason = "B 冻结映射不覆盖 stage/tags；保持待确认，不用于已核验兴趣/阶段结论。"
        if check is not None:
            reason = "; ".join(check.reasons + [check.action_reason])
            if check.status == "verified":
                status, selected = "verified", origin[check.evidence_ids[0]]
            elif check.status == "conflict":
                status = "conflict"
                reason += "; " + " | ".join(check.conflicting_values)
        decisions.append({"field": field, "status": status, "selected_claim_id": selected, "reason": reason})
    statuses = {item["status"] for item in decisions}
    overall = "conflict" if "conflict" in statuses else ("partial" if "verified" in statuses else "pending")
    return {"record_id": candidate["record_id"], "fields": decisions,
            "verification_status": overall, "verified_at": datetime.now(timezone.utc).isoformat()}

def verify(competitions, *, sources):
    return [_to_c_verification(candidate, result)
            for candidate, _, result, _ in evaluate_candidates(competitions, sources=sources)]
