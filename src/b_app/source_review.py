"""B-owned, conservative literal source review without a language model.

ApprovedSource records are a human-managed B trust list; C must not manufacture
them. Snapshots must be supplied by A's actual retrieval adapter or by explicitly
labelled offline fixtures. This module does not fetch or authenticate web pages.

Quotes must cover a whole blank-line-delimited paragraph or the whole snapshot.
Eligibility may quote a contiguous span of complete paragraphs so explicitly
labelled additional conditions can be retained together with the main rule.
The supported grammar is deliberately narrow: catalogued field labels followed
by a complete literal value, explicit date-only values, exact URLs, and explicitly
allowed not-applicable statements. Date-times, inferred dates, paraphrases and
partial qualifications remain unknown or unsupported. Explicit competition-name
or edition labels that contradict the target invalidate the page for every
field; unrelated dates in prose do not establish its identity. Multiple different
same-field statements on one page never permit selecting a convenient paragraph.
An approved notice URL may identify its own source page, but still requires a
whole quote from the retrieved snapshot. Ambiguous source contexts remain
unknown. A four-digit edition paired with a
different deadline year also requires human review (including legitimate
cross-year registration). These rules are evidence checks, not an NLP engine.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date
import re

from .b_contracts import Competition, Evidence
from .evidence_verifier import normalized_value
from .field_catalog import FIELD_SPECS, NOT_APPLICABLE_STATEMENTS, expected_scope


REVIEW_RULE_VERSION = "literal-v3"
_SOURCE_TYPES = {"official", "school", "third_party"}
_DATE_BODY = re.compile(
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[。.]?"
)
# These explicit warning phrases can negate a standalone-looking quoted block
# elsewhere on the page. Do not infer a current claim from such a snapshot.
_UNSAFE_CONTEXT = re.compile(
    r"往年通知|历史通知|旧版通知|已作废|已经作废|非本届|不是本届|并非本届|"
    r"不是报名截止|并非报名截止|尚未确定|暂定|拟定|预计|仅供参考"
)
_UNRESOLVED_VALUE = re.compile(r"未公布|另行通知|待通知|待公布|待补充|待确定|待确认|待定")
_ELIGIBILITY_EXTRA = re.compile(
    r"(?:附加参赛条件|补充参赛条件|额外参赛条件|参赛限制|资格限制|"
    r"附加资格要求|补充资格要求|参赛资格补充说明)\s*[：:]\s*(?P<value>.*)"
)


@dataclass(frozen=True)
class ApprovedSource:
    competition_id: str
    edition: str
    scope: str
    url: str
    source_type: str
    approved_by: str


@dataclass(frozen=True)
class SourceSnapshot:
    url: str
    text: str
    retrieved_at: str | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    evidence: Evidence
    reasons: list[str]

    def __post_init__(self) -> None:
        # Every return path carries B's actual review result downstream. A
        # source record supplied by C cannot retain self-reported reasons.
        object.__setattr__(self, "evidence", replace(
            self.evidence, review_reasons=tuple(self.reasons),
        ))


def _text(value: object) -> str:
    """Fold layout whitespace, without changing Unicode URL/token semantics."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [_text(item) for item in re.split(r"\n(?:[ \t]*\n)+", text) if _text(item)]


def _quote_paragraphs(quote: str, snapshot_text: str) -> list[str] | None:
    """Find an exact contiguous span of complete source paragraphs."""
    paragraphs = _paragraphs(snapshot_text)
    for start, first in enumerate(paragraphs):
        if not quote.startswith(first):
            continue
        block = []
        for paragraph in paragraphs[start:]:
            block.append(paragraph)
            joined = " ".join(block)
            if joined == quote:
                return block
            if not quote.startswith(joined):
                break
    return None


def _date_value(raw: str) -> str | None:
    try:
        if "年" in raw:
            parts = re.fullmatch(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日", raw)
            if parts is None:
                return None
            return date(*(int(part) for part in parts.groups())).isoformat()
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _without_final_period(text: str) -> str:
    return text[:-1].rstrip() if text.endswith(("。", ".")) else text


def _label_pattern(field: str) -> re.Pattern:
    spec = FIELD_SPECS[field]
    labels = "|".join(re.escape(label) for label in spec.labels)
    separator = r"(?:[：:]|为)" if spec.kind == "date" else r"[：:]"
    return re.compile(rf"(?:{labels})\s*{separator}\s*(?P<value>.+)")


def _identity_rejections(competition: Competition, snapshot_text: str) -> list[str]:
    """Check explicit identity labels, never arbitrary years or name substrings.

    Recognize Chinese-period-delimited statements and explicitly labelled
    identity entries separated by layout whitespace. A wrapped label/value is
    normalized with its whole paragraph. No free-form sentence is mined for a
    year or a possible competition-name substring.
    """
    units = set()
    for paragraph in _paragraphs(snapshot_text):
        for sentence in re.split(r"(?<=。)\s*", paragraph):
            units.update(part.strip() for part in re.split(
                r"(?<=\s)(?=(?:赛事名称|届次年份)\s*[：:])", sentence,
            ) if part.strip())
    reasons = []
    for field, expected, mismatch in (
        ("competition_name", competition.name, "source_name_mismatch"),
        ("competition_edition", competition.edition, "source_edition_mismatch"),
    ):
        pattern = _label_pattern(field)
        for unit in sorted(units):
            match = pattern.fullmatch(unit)
            if match is None:
                continue
            body = _without_final_period(match.group("value"))
            stated = normalized_value(field, body)
            target = normalized_value(field, expected)
            if stated is None or _UNRESOLVED_VALUE.search(body):
                reason = "source_identity_unresolved"
            else:
                # Only normalize a year suffix inside the explicitly labelled
                # edition value. Do not mine years from other source prose.
                if field == "competition_edition":
                    stated = re.sub(r"^([0-9]{4})年(?:度)?$", r"\1", stated)
                    target = re.sub(r"^([0-9]{4})年(?:度)?$", r"\1", target or "")
                reason = mismatch if stated != target else None
            if reason and reason not in reasons:
                reasons.append(reason)
    return reasons


def _eligibility_context_rejection(quote: str, snapshot_text: str) -> str | None:
    """Require all explicitly labelled supplemental conditions in the quote.

    These are a small declared grammar, not a claim to identify every possible
    qualification in natural language. Complementary restrictions are incomplete
    context when omitted, not contradictory sources.
    """
    supplements = [paragraph for paragraph in _paragraphs(snapshot_text)
                   if _ELIGIBILITY_EXTRA.fullmatch(paragraph)]
    if not supplements:
        return None
    quoted = _quote_paragraphs(quote, snapshot_text)
    if quoted is None or any(paragraph not in quoted for paragraph in supplements):
        return "eligibility_conditions_omitted"
    for paragraph in supplements:
        body = _ELIGIBILITY_EXTRA.fullmatch(paragraph).group("value")
        if normalized_value("eligibility", _without_final_period(body)) is None:
            return "eligibility_conditions_unresolved"
    return None


def _statement_key(field: str, body: str) -> tuple[str, str]:
    """Compare complete same-field paragraphs without guessing their meaning."""
    if body in NOT_APPLICABLE_STATEMENTS.get(field, ()):
        return "not_applicable", body
    kind = FIELD_SPECS[field].kind
    if kind == "date":
        match = _DATE_BODY.fullmatch(body)
        if match is not None and (parsed := _date_value(match.group("date"))) is not None:
            return "value", parsed
    elif kind == "url":
        # Preserve an ASCII URL period, which can be part of its path/query.
        raw = body[:-1] if body.endswith("。") else body
        if (value := normalized_value(field, raw)) is not None:
            return "value", value
    else:
        if (value := normalized_value(field, _without_final_period(body))) is not None:
            return "value", value
    return "unresolved", body


def _has_different_statements(field: str, snapshot_text: str) -> bool:
    pattern = _label_pattern(field)
    statements = set()
    for paragraph in _paragraphs(snapshot_text):
        match = pattern.fullmatch(paragraph)
        if match is not None:
            statements.add(_statement_key(field, match.group("value")))
    return len(statements) > 1


def _url_support(evidence: Evidence, body: str) -> tuple[str, str]:
    proposed = normalized_value(evidence.field, evidence.value)
    if not body or re.search(r"\s", body):
        return "unknown", "unsupported_registration_url_sentence" if evidence.field == "registration_url" else "unsupported_url_sentence"
    # Chinese sentence punctuation is never part of this grammar. An ASCII
    # period is removed only if the exact original URL did not match C's value.
    alternatives = [body[:-1]] if body.endswith("。") else [body]
    if body.endswith("."):
        alternatives.append(body[:-1])
    for option in alternatives:
        stated = normalized_value(evidence.field, option)
        if stated is not None and proposed is not None and stated == proposed:
            reason = "literal_registration_url_supported" if evidence.field == "registration_url" else "literal_url_supported"
            return "supported", reason
    return "unsupported", "claim_value_mismatch"


def _literal_support(evidence: Evidence, quote: str, snapshot_text: str) -> tuple[str, str]:
    """Return support classification and a stable explanation code."""
    if _UNSAFE_CONTEXT.search(_text(snapshot_text)):
        return "unknown", "ambiguous_source_context"
    spec = FIELD_SPECS.get(evidence.field)
    if spec is None:
        return "unknown", "field_has_no_literal_rule"
    if evidence.value_kind not in ("value", "not_applicable"):
        return "unknown", "unknown_value_kind"
    if evidence.field == "eligibility":
        rejection = _eligibility_context_rejection(quote, snapshot_text)
        if rejection is not None:
            return "unknown", rejection
    if _has_different_statements(evidence.field, snapshot_text):
        reason = "multiple_deadline_values_in_snapshot" if evidence.field == "registration_deadline" else "multiple_field_values_in_snapshot"
        return "unknown", reason
    match = _label_pattern(evidence.field).fullmatch(quote)

    if evidence.value_kind == "not_applicable":
        if match is None:
            return "unknown", "not_applicable_label_missing"
        statement = match.group("value")
        if statement not in NOT_APPLICABLE_STATEMENTS.get(evidence.field, ()):
            return "unknown", "not_applicable_statement_not_allowed"
        if _text(evidence.value) != statement:
            return "unsupported", "claim_value_mismatch"
        return "supported", "literal_not_applicable_supported"

    # B already approved this exact page as belonging to this competition,
    # edition and scope; the surrounding pipeline also checked that the quote
    # is complete and actually occurs in its retrieved snapshot.
    if evidence.field == "official_url":
        proposed = normalized_value(evidence.field, evidence.value)
        if proposed is not None and proposed == normalized_value("url", evidence.url):
            return "supported", "approved_notice_page_supported"

    if match is None:
        reason = {
            "registration_deadline": "unsupported_deadline_sentence",
            "registration_url": "unsupported_registration_url_sentence",
            "eligibility": "unsupported_eligibility_sentence",
        }.get(evidence.field, "unsupported_field_sentence")
        return "unknown", reason
    body = match.group("value")
    if body in NOT_APPLICABLE_STATEMENTS.get(evidence.field, ()):
        return "unknown", "not_applicable_value_kind_required"
    if _UNRESOLVED_VALUE.search(body):
        return "unknown", "field_value_not_announced"
    if _without_final_period(body).casefold() in {"不适用", "n/a", "na"}:
        return "unknown", "generic_not_applicable_statement"

    if spec.kind == "date":
        date_match = _DATE_BODY.fullmatch(body)
        if date_match is None:
            return "unknown", "unsupported_deadline_sentence" if evidence.field == "registration_deadline" else "unsupported_date_sentence"
        stated = _date_value(date_match.group("date"))
        if stated is None:
            return "unsupported", "invalid_literal_date"
        proposed = normalized_value(evidence.field, evidence.value)
        if proposed is None or proposed != stated:
            return "unsupported", "claim_value_mismatch"
        if re.fullmatch(r"[0-9]{4}", evidence.edition) and stated[:4] != evidence.edition:
            return "unknown", "deadline_year_requires_human_review"
        return "supported", "literal_date_supported"

    if spec.kind == "url":
        return _url_support(evidence, body)
    stated = normalized_value(evidence.field, _without_final_period(body))
    proposed = normalized_value(evidence.field, _without_final_period(_text(evidence.value)))
    if stated is None or proposed is None or proposed != stated:
        return "unsupported", "claim_value_mismatch"
    reason = "literal_eligibility_supported" if evidence.field == "eligibility" else "literal_text_supported"
    return "supported", reason


def review_evidence(
    competition: Competition,
    evidence: Evidence,
    *,
    approved_sources: list[ApprovedSource],
    snapshots: list[SourceSnapshot],
) -> ReviewResult:
    """Replace C's trust annotations with B's independent literal review.

    A trusted source match is exact in URL (except scheme/host case), competition
    ID, edition and scope. A quote that is absent is unsupported; an excerpt that
    omits the rest of its paragraph is unknown and cannot verify the claim.
    """
    reviewed = replace(
        evidence, source_type="unknown", source_verified=False,
        support="unknown", reviewed_by=None, retrieved_at=None, review_reasons=(),
    )
    url = normalized_value("url", evidence.url)
    if url is None:
        return ReviewResult(reviewed, ["invalid_source_url"])
    scope = expected_scope(competition, evidence.field)
    spec = FIELD_SPECS.get(evidence.field)
    needs_campus = spec is not None and (
        spec.campus_only
        or (evidence.field == "campus_deadline" and evidence.value_kind != "not_applicable")
    )
    if needs_campus and (
        not isinstance(scope, str) or not scope.startswith("campus:")
        or not normalized_value("scope", scope[len("campus:"):])
    ):
        return ReviewResult(reviewed, ["specific_campus_scope_required"])
    if (
        not normalized_value("id", competition.id)
        or not normalized_value("edition", competition.edition)
        or not normalized_value("scope", scope)
        or evidence.edition != competition.edition
        or evidence.scope != scope
    ):
        return ReviewResult(reviewed, ["evidence_context_mismatch"])

    approvals = [
        item for item in approved_sources
        if item.competition_id == competition.id
        and item.edition == competition.edition
        and item.scope == scope
        and normalized_value("url", item.url) == url
        and item.source_type in _SOURCE_TYPES
        and _text(item.approved_by)
    ]
    if not approvals:
        return ReviewResult(reviewed, ["source_not_approved"])
    if len({item.source_type for item in approvals}) != 1:
        return ReviewResult(reviewed, ["ambiguous_source_approval"])
    approved_by = ",".join(sorted({_text(item.approved_by) for item in approvals}))
    reviewed = replace(
        reviewed, source_type=approvals[0].source_type,
        reviewed_by=f"{REVIEW_RULE_VERSION}:{approved_by}",
    )

    matching_snapshots = [
        item for item in snapshots
        if normalized_value("url", item.url) == url and _text(item.text)
        and (evidence.source_id is None or item.source_id == evidence.source_id)
    ]
    if not matching_snapshots:
        return ReviewResult(reviewed, ["source_snapshot_missing"])
    if len({tuple(_paragraphs(item.text)) for item in matching_snapshots}) != 1:
        return ReviewResult(reviewed, ["ambiguous_source_snapshot"])
    snapshot = matching_snapshots[0]
    identity_rejections = _identity_rejections(competition, snapshot.text)
    if identity_rejections:
        return ReviewResult(reviewed, identity_rejections)
    reviewed = replace(reviewed, source_verified=True, retrieved_at=snapshot.retrieved_at)
    quote = _text(evidence.quote)
    full_text = _text(snapshot.text)
    if not quote or quote not in full_text:
        return ReviewResult(replace(reviewed, support="unsupported"), ["quote_not_found"])
    full_eligibility_span = evidence.field == "eligibility" and _quote_paragraphs(quote, snapshot.text) is not None
    if quote != full_text and quote not in _paragraphs(snapshot.text) and not full_eligibility_span:
        return ReviewResult(reviewed, ["quote_not_complete_paragraph"])

    support, reason = _literal_support(reviewed, quote, snapshot.text)
    return ReviewResult(replace(reviewed, support=support), [reason])


def review_competition(
    competition: Competition,
    *,
    approved_sources: list[ApprovedSource],
    snapshots: list[SourceSnapshot],
) -> tuple[Competition, list[ReviewResult]]:
    """Review every record on a deep copy, preserving C's original field values."""
    reviewed = deepcopy(competition)
    results = [
        review_evidence(
            reviewed, item, approved_sources=approved_sources, snapshots=snapshots,
        )
        for item in reviewed.evidence
    ]
    reviewed.evidence = [item.evidence for item in results]
    return reviewed, results
