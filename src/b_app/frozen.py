"""B's explicitly frozen policy, identities, and source approvals (2026-10-28)."""
import json
from pathlib import Path
from .b_contracts import VerificationPolicy
from .field_catalog import MANDATORY_FIELDS, FIELD_SPECS
from .source_review import ApprovedSource

DATA = Path(__file__).resolve().parents[2] / "data"
FIELD_MAP = {
    "name": "competition_name", "organizer": "organizer",
    "edition": "competition_edition", "track": "track", "eligibility": "eligibility",
    "registration_start": "registration_start", "registration_deadline": "registration_deadline",
    "official_url": "official_url", "registration_url": "registration_url",
}

def load_policy(profile="student_22", *, data_dir=None):
    raw = json.loads(((data_dir or DATA) / "b_policy.json").read_text(encoding="utf-8"))
    required = raw["profiles"][profile]["required_fields"]
    expected = list(MANDATORY_FIELDS) if profile == "student_22" else list(FIELD_MAP.values())
    if required != expected or any(f not in FIELD_SPECS for f in raw["school_accepted_fields"]):
        raise ValueError("Frozen B field policy differs from declared interface")
    if raw["accepted_source_types"] != ["official"] or raw["conflict_source_types"] != ["official", "school"]:
        raise ValueError("Frozen B source policy must not silently accept schools globally")
    return VerificationPolicy(required_fields=tuple(required),
                              accepted_source_types=tuple(raw["accepted_source_types"]),
                              conflict_source_types=tuple(raw["conflict_source_types"]),
                              school_accepted_fields=tuple(raw["school_accepted_fields"]),
                              inspect_optional=True)

def load_approvals(*, data_dir=None):
    raw = json.loads(((data_dir or DATA) / "approved_sources.json").read_text(encoding="utf-8"))
    records = raw["approved_sources"] if isinstance(raw, dict) else raw
    approvals = [ApprovedSource(**record) for record in records]
    keys = [(a.competition_id, a.edition, a.scope, a.url) for a in approvals]
    if len(keys) != len(set(keys)) or any("demo" in a.approved_by or not a.approved_by.strip() for a in approvals):
        raise ValueError("Duplicate or draft approval in frozen B configuration")
    return approvals

def load_contexts(*, data_dir=None):
    return json.loads(((data_dir or DATA) / "b_target_contexts.json").read_text(encoding="utf-8"))
