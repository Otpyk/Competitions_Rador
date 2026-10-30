"""Shared data contracts for evidence, verification, and rule results."""

import re
from datetime import date as Date
from datetime import datetime as DateTime
from datetime import time as Time
from typing import Annotated, Literal, Self, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)


FIELD_NAMES = (
    "name", "organizer", "edition", "track", "stage", "tags", "eligibility",
    "registration_start", "registration_deadline", "official_url", "registration_url",
)
IDENTITY_FIELDS = ("name", "organizer", "edition", "track", "stage")
FieldName: TypeAlias = Literal[
    "name", "organizer", "edition", "track", "stage", "tags", "eligibility",
    "registration_start", "registration_deadline", "official_url", "registration_url",
]
FieldStatus: TypeAlias = Literal["verified", "unverified", "missing", "conflict"]
VerificationStatus: TypeAlias = Literal["verified", "partial", "conflict", "pending"]
EligibilityStatus: TypeAlias = Literal["eligible", "ineligible", "unknown"]
RegistrationStatus: TypeAlias = Literal["open", "upcoming", "closed", "unknown"]


def _nonempty(value: str) -> str:
    if not value.strip():
        raise ValueError("must contain a non-whitespace character")
    return value


NonEmptyStr: TypeAlias = Annotated[str, Field(strict=True), AfterValidator(_nonempty)]
PositiveInt: TypeAlias = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt: TypeAlias = Annotated[int, Field(strict=True, ge=0)]
_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def _http_url(value: str) -> str:
    if any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("URL must not contain whitespace or control characters")
    _URL_ADAPTER.validate_python(value)
    return value


HttpUrlString: TypeAlias = Annotated[NonEmptyStr, AfterValidator(_http_url)]


def _date(value: object) -> Date:
    if type(value) is Date:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return Date.fromisoformat(value)
    raise ValueError("date must be a complete YYYY-MM-DD date")


def _timestamp(value: object) -> DateTime:
    if isinstance(value, str):
        try:
            value = DateTime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("timestamp must contain a UTC offset") from error
    if not isinstance(value, DateTime) or value.utcoffset() is None:
        raise ValueError("timestamp must contain a UTC offset")
    return value


def _clock(value: str) -> str:
    if not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value):
        raise ValueError("time must retain HH:MM or HH:MM:SS precision")
    Time.fromisoformat(value)
    return value


def _timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("timezone must be an existing IANA timezone") from error
    return value


CompleteDate: TypeAlias = Annotated[Date, BeforeValidator(_date)]
AwareTimestamp: TypeAlias = Annotated[DateTime, BeforeValidator(_timestamp)]
RegistrationClock: TypeAlias = Annotated[NonEmptyStr, AfterValidator(_clock)]
IanaTimezone: TypeAlias = Annotated[NonEmptyStr, AfterValidator(_timezone)]


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UserProfile(ContractModel):
    education_level: NonEmptyStr | None
    major: NonEmptyStr | None
    grade: PositiveInt | None
    team_size: PositiveInt | None
    interests: list[NonEmptyStr]
    deadline_from: CompleteDate | None
    deadline_to: CompleteDate | None

    @model_validator(mode="after")
    def deadline_order(self) -> Self:
        if self.deadline_from is not None and self.deadline_to is not None:
            if self.deadline_from > self.deadline_to:
                raise ValueError("deadline_from must not be later than deadline_to")
        return self


class SourceDocument(ContractModel):
    source_id: NonEmptyStr
    url: HttpUrlString
    title: NonEmptyStr | None
    content: NonEmptyStr
    fetched_at: AwareTimestamp
    published_date: CompleteDate | None


class ResearchBatch(ContractModel):
    task_id: NonEmptyStr
    query: NonEmptyStr
    sources: list[SourceDocument]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        _unique([source.source_id for source in self.sources], "source_id values")
        return self


class EvidenceRef(ContractModel):
    source_id: NonEmptyStr
    quote: NonEmptyStr


class TeamSize(ContractModel):
    min: PositiveInt | None
    max: PositiveInt | None

    @model_validator(mode="after")
    def bounds_order(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("team_size min must not be greater than max")
        return self


class EligibilityRules(ContractModel):
    allowed_education_levels: list[NonEmptyStr] | None
    allowed_majors: list[NonEmptyStr] | None
    allowed_grades: list[PositiveInt] | None
    team_size: TeamSize | None
    other_requirements: list[NonEmptyStr] | None


class RegistrationTime(ContractModel):
    date: CompleteDate
    time: RegistrationClock | None
    timezone: IanaTimezone | None


class ClaimBase(ContractModel):
    claim_id: NonEmptyStr
    evidence: Annotated[list[EvidenceRef], Field(min_length=1)]


class TextClaim(ClaimBase):
    field: Literal["name", "organizer", "edition", "track", "stage"]
    value: NonEmptyStr


class TagsClaim(ClaimBase):
    field: Literal["tags"]
    value: list[NonEmptyStr]


class EligibilityClaim(ClaimBase):
    field: Literal["eligibility"]
    value: EligibilityRules


class RegistrationTimeClaim(ClaimBase):
    field: Literal["registration_start", "registration_deadline"]
    value: RegistrationTime


class UrlClaim(ClaimBase):
    field: Literal["official_url", "registration_url"]
    value: HttpUrlString


FieldClaim: TypeAlias = Annotated[
    TextClaim | TagsClaim | EligibilityClaim | RegistrationTimeClaim | UrlClaim,
    Field(discriminator="field"),
]


class CandidateContest(ContractModel):
    record_id: NonEmptyStr
    member_ids: Annotated[list[NonEmptyStr], Field(min_length=1)]
    claims: list[FieldClaim]

    @model_validator(mode="after")
    def local_identifiers(self) -> Self:
        _unique(self.member_ids, "member_ids")
        _unique([claim.claim_id for claim in self.claims], "claim_id values")
        if self.record_id not in self.member_ids:
            raise ValueError("member_ids must contain record_id")
        return self


class FieldDecision(ContractModel):
    field: FieldName
    status: FieldStatus
    selected_claim_id: NonEmptyStr | None
    reason: NonEmptyStr

    @model_validator(mode="after")
    def selection_status(self) -> Self:
        if (self.status == "verified") != (self.selected_claim_id is not None):
            raise ValueError("only verified fields must select a claim")
        return self


def _complete_fields(names: list[str]) -> None:
    if len(names) != len(FIELD_NAMES) or set(names) != set(FIELD_NAMES):
        raise ValueError("fields must contain every supported field exactly once")


class VerificationResult(ContractModel):
    record_id: NonEmptyStr
    fields: list[FieldDecision]
    verification_status: VerificationStatus
    verified_at: AwareTimestamp

    @model_validator(mode="after")
    def all_field_decisions(self) -> Self:
        _complete_fields([field.field for field in self.fields])
        return self


Reasons: TypeAlias = Annotated[list[NonEmptyStr], Field(min_length=1)]


class EligibilityAssessment(ContractModel):
    status: EligibilityStatus
    reasons: Reasons
    pending_items: list[NonEmptyStr]


class RegistrationAssessment(ContractModel):
    status: RegistrationStatus
    reasons: Reasons
    pending_items: list[NonEmptyStr]


class ExpandedEvidence(EvidenceRef):
    url: HttpUrlString


ResolvedValue: TypeAlias = (
    NonEmptyStr | list[NonEmptyStr] | EligibilityRules | RegistrationTime | None
)


class ResolvedField(ContractModel):
    field: FieldName
    status: FieldStatus
    reason: NonEmptyStr
    value: ResolvedValue
    claim_id: NonEmptyStr | None
    evidence: list[ExpandedEvidence]

    @model_validator(mode="after")
    def resolved_status_and_type(self) -> Self:
        if self.status != "verified":
            if self.value is not None or self.claim_id is not None or self.evidence:
                raise ValueError("unresolved fields must have null value/claim_id and no evidence")
            return self
        if self.value is None or self.claim_id is None or not self.evidence:
            raise ValueError("verified fields require a value, claim_id, and evidence")
        if self.field == "eligibility":
            valid = isinstance(self.value, EligibilityRules)
        elif self.field in ("registration_start", "registration_deadline"):
            valid = isinstance(self.value, RegistrationTime)
        elif self.field == "tags":
            valid = isinstance(self.value, list)
        else:
            valid = isinstance(self.value, str)
            if valid and self.field in ("official_url", "registration_url"):
                _http_url(self.value)
        if not valid:
            raise ValueError("resolved value must have the type required by its field")
        return self


class RecommendationItem(ContractModel):
    record_id: NonEmptyStr
    fields: list[ResolvedField]
    eligibility_status: EligibilityStatus
    eligibility_reasons: Reasons
    registration_status: RegistrationStatus
    registration_reasons: Reasons
    verification_status: VerificationStatus
    verified_at: AwareTimestamp
    matched_interests: list[NonEmptyStr]
    interest_match_count: NonNegativeInt
    reasons: Reasons
    pending_items: list[NonEmptyStr]

    @model_validator(mode="after")
    def complete_item(self) -> Self:
        _complete_fields([field.field for field in self.fields])
        _unique(self.matched_interests, "matched_interests")
        if self.interest_match_count != len(self.matched_interests):
            raise ValueError("interest_match_count must equal the matched_interests length")
        return self


class RecommendationResponse(ContractModel):
    task_id: NonEmptyStr
    as_of: AwareTimestamp
    recommended: list[RecommendationItem]
    pending: list[RecommendationItem]
    excluded: list[RecommendationItem]

    @model_validator(mode="after")
    def unique_results(self) -> Self:
        _unique(
            [item.record_id for item in self.recommended + self.pending + self.excluded],
            "result record_id values",
        )
        return self
