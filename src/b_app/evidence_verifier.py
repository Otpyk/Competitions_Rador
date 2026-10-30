"""Conservative evidence-policy checks; no network or model calls.

Source identity and direct textual support require B's source_review stage.
This module checks that those annotations exist and are consistent; it cannot
independently prove a web page authentic or infer arbitrary textual entailment.
"""

from collections import Counter
from datetime import date, datetime, timezone
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .b_contracts import (
    Competition, Evidence, FieldCheck, VerificationPolicy, VerificationResult,
)
from .field_catalog import DATE_FIELDS, FIELD_SPECS, NOT_APPLICABLE_STATEMENTS, expected_scope
from .consistency_checks import detect_consistency_issues
from .next_steps import classify_next_action

_UNKNOWN = {
    "unknown", "pending", "missing", "null", "none", "n/a", "tbd",
    "待确认", "待核验", "待定", "未知", "暂无", "不详",
    "未公布", "暂未公布", "另行通知", "待通知", "待公布", "详见后续通知",
}


def _text(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()) if isinstance(value, str) else ""


def normalized_value(field: str, value: object) -> str | None:
    """Accept C's explicit canonical values, never guess a year or timezone."""
    if not isinstance(field, str):
        return None
    if field.endswith("_url") or field == "url":
        # URLs are opaque beyond their scheme/host. NFKC would change token,
        # path or query semantics (for example full-width characters).
        if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f]", value):
            return None
        text = value
        try:
            parsed = urlsplit(text)
            if (
                parsed.scheme.lower() not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or re.search(r"\s", text)
            ):
                return None
            _ = parsed.port
            return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
                               parsed.query, parsed.fragment))
        except ValueError:
            return None
    text = _text(value)
    if not text or text.casefold() in _UNKNOWN:
        return None
    if field in DATE_FIELDS:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                return date.fromisoformat(text).isoformat()
            if not re.match(r"^\d{4}-\d{2}-\d{2}T", text):
                return None
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is None or moment.utcoffset() is None:
                return None
            return moment.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            return None
    return text


def normalized_claim(evidence: Evidence) -> tuple[str, str] | None:
    """A supported N/A statement is a claim, never a fake date or URL."""
    if evidence.value_kind == "not_applicable":
        if evidence.value not in NOT_APPLICABLE_STATEMENTS.get(evidence.field, ()):
            return None
        return ("not_applicable", evidence.value)
    if evidence.value_kind != "value":
        return None
    value = normalized_value(evidence.field, evidence.value)
    return ("value", value) if value is not None else None


def _accepted_sources(competition: Competition, name: str, policy: VerificationPolicy) -> tuple[str, ...]:
    scope = expected_scope(competition, name)
    if name == "school_recognition":
        # A contest organizer cannot establish a particular university's policy.
        return ("school",)
    if name in policy.school_accepted_fields and scope.startswith("campus:") and normalized_value("scope", scope[7:]) is not None:
        return tuple(dict.fromkeys((*policy.accepted_source_types, "school")))
    return policy.accepted_source_types


def _base_rejections(evidence: Evidence, competition: Competition) -> list[str]:
    reasons: list[str] = []
    if not _text(evidence.id):
        reasons.append("missing_evidence_id")
    if not _text(evidence.field):
        reasons.append("missing_field")
    if normalized_claim(evidence) is None:
        reasons.append("invalid_claim_value")
    if evidence.field == "competition_edition" and _text(evidence.value) != _text(competition.edition):
        reasons.append("edition_value_mismatch")
    if evidence.field == "competition_name" and _text(evidence.value) != _text(competition.name):
        reasons.append("name_value_mismatch")
    if normalized_value("url", evidence.url) is None:
        reasons.append("invalid_source_url")
    if not _text(evidence.quote):
        reasons.append("missing_quote")
    if any(not _text(value) or _text(value).casefold() in _UNKNOWN
           for value in (competition.edition, evidence.edition)):
        reasons.append("unknown_edition")
    elif _text(evidence.edition) != _text(competition.edition):
        reasons.append("edition_mismatch")
    target_scope = expected_scope(competition, evidence.field)
    if any(not _text(value) or _text(value).casefold() in _UNKNOWN
           for value in (target_scope, evidence.scope)):
        reasons.append("unknown_scope")
    elif _text(evidence.scope) != _text(target_scope):
        reasons.append("scope_mismatch")
    spec = FIELD_SPECS.get(evidence.field)
    campus_is_specific = target_scope.startswith("campus:") and normalized_value("scope", target_scope[7:]) is not None
    if spec and spec.campus_only and not campus_is_specific:
        reasons.append("specific_campus_scope_required")
    if evidence.field == "campus_deadline" and evidence.value_kind == "value" and not campus_is_specific:
        reasons.append("specific_campus_scope_required")
    if evidence.source_verified is not True:
        reasons.append("source_not_reviewed")
    if evidence.support != "supported":
        reasons.append("direct_support_not_confirmed")
    if evidence.support != "supported" or evidence.source_verified is not True:
        reasons.extend(reason for reason in evidence.review_reasons if reason not in reasons)
    if not _text(evidence.reviewed_by):
        reasons.append("missing_reviewer")
    if evidence.source_type not in ("official", "school", "third_party"):
        reasons.append("unknown_source_type")
    return reasons


def evidence_rejection_reasons(
    evidence: Evidence,
    competition: Competition,
    policy: VerificationPolicy | None = None,
    *, allow_optional: bool = False,
) -> list[str]:
    """Reasons a record cannot independently verify a required field.

    A reviewed school notice may still participate in conflict detection; it
    does not independently verify a field under the default official-only policy.
    """
    policy = policy or VerificationPolicy()
    reasons = _base_rejections(evidence, competition)
    if evidence.field not in policy.required_fields and not allow_optional:
        reasons.append("not_required_field")
    if evidence.source_type not in _accepted_sources(competition, evidence.field, policy):
        reasons.append("insufficient_source_type")
    if sum(item.id == evidence.id for item in competition.evidence) > 1:
        reasons.append("duplicate_evidence_id")
    return reasons


def verify_competition(
    competition: Competition,
    policy: VerificationPolicy | None = None,
) -> VerificationResult:
    policy = policy or VerificationPolicy()
    if not _text(competition.id) or not _text(competition.name):
        raise ValueError("Competition id and name are required")
    checks: dict[str, FieldCheck] = {}
    counts = Counter(item.id for item in competition.evidence)
    missing_fields: list[str] = []
    inspected = list(policy.required_fields)
    if policy.inspect_optional:
        present = {name for name, value in competition.fields.items()
                   if value is not None and not (isinstance(value, str) and not value.strip())}
        present |= {item.field for item in competition.evidence}
        inspected.extend(name for name in FIELD_SPECS if name in present and name not in inspected)
    for name in inspected:
        required = name in policy.required_fields
        original = competition.fields.get(name)
        if original is None or (isinstance(original, str) and not original.strip()):
            missing_fields.append(name)
        check = FieldCheck(field=name, status="pending", original_value=original,
                           required=required, scope=expected_scope(competition, name),
                           requirement_reasons=list(policy.requirement_reasons.get(name, ("基础必须项" if required else "拓展项",))))
        candidates = [item for item in competition.evidence if item.field == name]
        check.source_urls = list(dict.fromkeys(item.url for item in candidates if normalized_value("url", item.url) is not None))
        accepted: dict[tuple[str, str], list[str]] = {}
        credible: dict[tuple[str, str], list[str]] = {}
        for index, evidence in enumerate(candidates):
            rejections = evidence_rejection_reasons(evidence, competition, policy, allow_optional=True)
            reference = evidence.id if counts[evidence.id] == 1 and evidence.id else f"{evidence.id or 'missing-id'}#{index}"
            if rejections:
                check.rejected_evidence[reference] = rejections
            value = normalized_claim(evidence)
            if not rejections and value is not None:
                accepted.setdefault(value, []).append(reference)
            # A different credible value blocks automatic resolution even when a
            # school notice is insufficient to establish a value by itself.
            if (
                not _base_rejections(evidence, competition)
                and counts[evidence.id] == 1
                and evidence.source_type in set(policy.conflict_source_types + _accepted_sources(competition, name, policy))
                and value is not None
            ):
                credible.setdefault(value, []).append(reference)

        if len(credible) > 1:
            check.status = "conflict"
            check.reasons = ["conflicting_supported_claims"]
            check.conflicting_values = sorted(("不适用：" + value) if kind == "not_applicable" else value for kind, value in credible)
            check.evidence_ids = sorted(ref for refs in credible.values() for ref in refs)
        elif any(counts[item.id] > 1 for item in candidates):
            check.reasons = ["duplicate_evidence_id"]
        elif accepted:
            check.status = "verified"
            claim = next(iter(accepted))
            check.value_kind = claim[0]
            if check.value_kind == "not_applicable":
                check.confirmed_statement = claim[1]
            else:
                check.verified_value = claim[1]
            check.evidence_ids = sorted(accepted[claim])
            check.reasons = ["evidence_policy_satisfied"]
            if original is not None and normalized_value(name, original) != check.verified_value:
                check.reasons.append("original_value_differs_from_evidence")
        else:
            if name in missing_fields:
                check.reasons.append("missing_value")
            if not candidates:
                check.reasons.append("missing_evidence")
            else:
                check.reasons.append("no_sufficient_evidence")
            if original is not None and normalized_value(name, original) is None:
                check.reasons.append("invalid_original_value")
        checks[name] = check

    consistency_issues = detect_consistency_issues(checks)
    for issue in consistency_issues:
        for name in issue["fields"]:
            check = checks[name]
            check.status = "conflict"
            check.verified_value = None
            check.confirmed_statement = None
            check.value_kind = None
            check.reasons.append(issue["code"])
    for name, check in checks.items():
        check.next_action, check.action_reason = classify_next_action(
            competition, check, [item for item in competition.evidence if item.field == name])

    unresolved = [name for name in policy.required_fields if checks[name].status != "verified"]
    status = "conflict" if any(checks[name].status == "conflict" for name in policy.required_fields) else (
        "pending" if unresolved else "verified"
    )
    return VerificationResult(
        competition_id=competition.id,
        status=status,
        fields=checks,
        missing_fields=missing_fields,
        unresolved_fields=unresolved,
        coverage=(len(policy.required_fields) - len(unresolved)) / len(policy.required_fields),
        required_fields=list(policy.required_fields),
        promoted_fields=list(policy.promoted_fields),
        optional_unresolved_fields=[name for name in inspected if name not in policy.required_fields and checks[name].status != "verified"],
        optional_conflict_fields=[name for name in inspected if name not in policy.required_fields and checks[name].status == "conflict"],
        unrecognized_fields=sorted((set(competition.fields) | {item.field for item in competition.evidence}) - set(FIELD_SPECS) - set(policy.required_fields)),
        consistency_issues=consistency_issues,
    )
