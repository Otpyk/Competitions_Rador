"""Read C's proposed field-level JSON without trusting incoming status labels."""

from dataclasses import fields as dataclass_fields
from typing import Any

from .b_contracts import Competition, Evidence

_META = {"id", "name", "edition", "scope", "field_scopes", "fields", "evidence", "verification_status", "last_verified_at"}


def evidence_from_dict(data: dict[str, Any], field_name: str | None = None) -> Evidence:
    if not isinstance(data, dict):
        raise ValueError("Each evidence record must be an object")
    payload = dict(data)
    if field_name is not None:
        if payload.get("field", field_name) != field_name:
            raise ValueError("Evidence field does not match its containing field")
        payload["field"] = field_name
    allowed = {item.name for item in dataclass_fields(Evidence)}
    # Reject misspelled annotation keys rather than silently weakening checks.
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Unknown evidence keys: {', '.join(sorted(unknown))}")
    for key in ("id", "field", "value", "url", "quote", "edition"):
        if not isinstance(payload.get(key), str):
            raise ValueError(f"Evidence.{key} must be a string (use an empty string for unknown text)")
    for key in ("source_type", "support", "scope", "value_kind"):
        if key in payload and not isinstance(payload[key], str):
            raise ValueError(f"Evidence.{key} must be a string")
    for key in ("reviewed_by", "retrieved_at", "source_id"):
        if key in payload and payload[key] is not None and not isinstance(payload[key], str):
            raise ValueError(f"Evidence.{key} must be a string or null")
    if "source_verified" in payload and type(payload["source_verified"]) is not bool:
        raise ValueError("Evidence.source_verified must be a JSON boolean")
    if payload.get("value_kind", "value") not in ("value", "not_applicable"):
        raise ValueError("Evidence.value_kind must be value or not_applicable")
    if "review_reasons" in payload:
        if not isinstance(payload["review_reasons"], (list, tuple)) or not all(isinstance(item, str) for item in payload["review_reasons"]):
            raise ValueError("Evidence.review_reasons must be a list of strings")
        payload["review_reasons"] = tuple(payload["review_reasons"])
    return Evidence(**payload)


def competition_from_dict(data: dict[str, Any]) -> Competition:
    """Accept either top-level business fields or an explicit ``fields`` object.

    Each field may be a raw value or {value, evidence, status}. ``status`` is
    deliberately ignored. Global evidence may be a list or field-keyed lists.
    No source review or direct support flags are synthesized by this adapter.
    """
    if not isinstance(data, dict):
        raise ValueError("Competition must be a JSON object")
    for key in ("id", "name", "edition"):
        if not isinstance(data.get(key), str):
            raise ValueError(f"Competition.{key} must be a string; edition may be empty if unknown")
    if not data["id"].strip() or not data["name"].strip():
        raise ValueError("Competition id and name must not be empty")
    if not isinstance(data.get("scope", "global"), str):
        raise ValueError("Competition.scope must be a string")
    field_scopes = data.get("field_scopes", {})
    if not isinstance(field_scopes, dict) or any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in field_scopes.items()):
        raise ValueError("Competition.field_scopes must map field names to nonempty scope strings")
    if "fields" in data:
        if not isinstance(data["fields"], dict):
            raise ValueError("Competition.fields must be an object")
        outer_fields = set(data) - _META
        if outer_fields:
            raise ValueError("Use either top-level business fields or fields, not both")
        raw_fields = data["fields"]
    else:
        raw_fields = {key: value for key, value in data.items() if key not in _META}
    values: dict[str, Any] = {}
    evidence: list[Evidence] = []
    for name, raw in raw_fields.items():
        if isinstance(raw, dict) and "value" in raw:
            values[name] = raw["value"]
            records = raw.get("evidence", [])
            if not isinstance(records, list):
                raise ValueError(f"{name}.evidence must be a list")
            evidence.extend(evidence_from_dict(item, name) for item in records)
        else:
            values[name] = raw
    global_evidence = data.get("evidence", [])
    if isinstance(global_evidence, list):
        evidence.extend(evidence_from_dict(item) for item in global_evidence)
    elif isinstance(global_evidence, dict):
        for name, records in global_evidence.items():
            if not isinstance(records, list):
                raise ValueError(f"evidence.{name} must be a list")
            evidence.extend(evidence_from_dict(item, name) for item in records)
    else:
        raise ValueError("Competition.evidence must be a list or field-keyed object")
    return Competition(
        id=data["id"], name=data["name"], edition=data["edition"],
        fields=values, evidence=evidence, scope=data.get("scope", "global"), field_scopes=dict(field_scopes),
    )


def review_bundle_from_dict(data: dict[str, Any]):
    """Load a B-maintained review bundle, or C's raw competition alone.

    The approved_sources section is trusted B configuration. A public UI must
    not accept that section as a user-supplied declaration of official sources.
    """
    from .source_review import ApprovedSource, SourceSnapshot

    if not isinstance(data, dict):
        raise ValueError("Review input must be an object")
    if "competition" not in data:
        return competition_from_dict(data), [], []
    candidate = competition_from_dict(data["competition"])
    approved = data.get("approved_sources", [])
    snapshots = data.get("snapshots", [])
    if not isinstance(approved, list) or not isinstance(snapshots, list):
        raise ValueError("approved_sources and snapshots must be lists")
    for record in approved:
        if not isinstance(record, dict) or not all(isinstance(value, str) for value in record.values()):
            raise ValueError("Approved source records must contain string fields")
    for record in snapshots:
        if not isinstance(record, dict) or not isinstance(record.get("url"), str) or not isinstance(record.get("text"), str):
            raise ValueError("Source snapshot url and text must be strings")
        if record.get("retrieved_at") is not None and not isinstance(record["retrieved_at"], str):
            raise ValueError("Snapshot retrieved_at must be a string or null")
    try:
        return candidate, [ApprovedSource(**item) for item in approved], [SourceSnapshot(**item) for item in snapshots]
    except TypeError as exc:
        raise ValueError(f"Invalid review configuration: {exc}") from exc
