"""Competition Radar C: grounded data contracts and deterministic matching."""

from .a_handoff import research_batch_from_a
from .b_handoff import (
    BContest, BEvidence, BField, export_b_contest, required_b_fields, validate_b_evidence,
)
from .b_return import ConsumedBReturn, consume_b_return
from .b_recommend import BRecommendationItem, BRecommendationResponse, recommend_b_returns
from .eligibility import assess_eligibility
from .extraction import ExtractionResult, ExtractionTarget, extract_b_contests
from .normalization import merge_candidates, normalize_text
from .ranker import recommend
from .registration import assess_registration
from .schemas import (
    CandidateContest, EligibilityRules, EvidenceRef, FieldClaim, FieldDecision,
    RecommendationResponse, RegistrationTime, ResearchBatch, SourceDocument,
    TeamSize, UserProfile, VerificationResult,
)
from .validation import ContractError, ValidationIssue, validate_evidence, validate_verification

__all__ = [
    "BContest", "BEvidence", "BField", "export_b_contest", "required_b_fields", "validate_b_evidence",
    "ConsumedBReturn", "consume_b_return",
    "BRecommendationItem", "BRecommendationResponse", "recommend_b_returns",
    "ExtractionResult", "ExtractionTarget", "extract_b_contests",
    "CandidateContest", "ContractError", "EligibilityRules", "EvidenceRef", "FieldClaim",
    "FieldDecision", "RecommendationResponse", "RegistrationTime", "ResearchBatch",
    "SourceDocument", "TeamSize", "UserProfile", "ValidationIssue", "VerificationResult",
    "assess_eligibility", "assess_registration", "merge_candidates", "normalize_text",
    "recommend", "research_batch_from_a", "validate_evidence", "validate_verification",
]
