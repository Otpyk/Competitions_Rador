"""Versioned B -> C wire format and a standalone reference receiver.

The receiver checks schema, summary consistency, and links back to C's input.
It does not rerun B's decision algorithm or authenticate a webpage. A passing
receipt is an interface check, never a certificate that a contest is genuine.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json
from math import isclose, isfinite
from pathlib import Path

from .b_contracts import Competition
from .b_io import competition_from_dict
from .evidence_verifier import normalized_claim, normalized_value
from .field_catalog import FIELD_SPECS, expected_scope


CONTRACT_VERSION = "b-c-return-v1"
SCHEMA_PATH = Path(__file__).resolve().parent / "contracts" / "b_return_v1.schema.json"
_OWNERS = {"search": "A", "fetch_source": "A", "repair_extraction": "C",
           "human_review": "B", "clarify_context": "A/C"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _schema_check(value, schema, root, path="$",):
    """Validate precisely the JSON Schema keywords used in our bundled schema.

    This small validator is intentionally not a general JSON Schema library.
    Unsupported assertions fail closed if a later schema introduces one.
    """
    known = {"$schema", "$id", "$defs", "$ref", "title", "description", "type",
             "enum", "const", "anyOf", "properties", "additionalProperties",
             "propertyNames", "required", "items", "minItems", "uniqueItems",
             "minimum", "maximum", "exclusiveMinimum", "minLength"}
    _require(not set(schema) - known, f"{path}: unsupported schema keyword")
    if "$ref" in schema:
        ref = schema["$ref"]
        _require(ref.startswith("#/$defs/"), f"{path}: unsupported schema reference")
        _schema_check(value, root["$defs"][ref[len("#/$defs/"):]], root, path)
        return
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                _schema_check(value, branch, root, path)
                break
            except ValueError:
                pass
        else:
            raise ValueError(f"{path}: value does not match any allowed type")
    types = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
             "string": lambda x: isinstance(x, str), "null": lambda x: x is None,
             "boolean": lambda x: type(x) is bool, "integer": lambda x: type(x) is int,
             "number": lambda x: type(x) in (int, float) and isfinite(x)}
    if "type" in schema:
        _require(types[schema["type"]](value), f"{path}: expected {schema['type']}")
    if "enum" in schema:
        _require(value in schema["enum"], f"{path}: value outside enum")
    if "const" in schema:
        _require(value == schema["const"], f"{path}: incorrect constant")
    if isinstance(value, dict):
        _require(all(isinstance(key, str) for key in value), f"{path}: keys must be strings")
        _require(set(schema.get("required", [])) <= value.keys(), f"{path}: missing required keys")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if "propertyNames" in schema:
                _schema_check(key, schema["propertyNames"], root, f"{path}.<key>")
            if key in properties:
                _schema_check(item, properties[key], root, f"{path}.{key}")
            elif extra is False:
                raise ValueError(f"{path}.{key}: unexpected key")
            elif isinstance(extra, dict):
                _schema_check(item, extra, root, f"{path}.{key}")
    if isinstance(value, list):
        _require(len(value) >= schema.get("minItems", 0), f"{path}: too few items")
        if schema.get("uniqueItems"):
            tokens = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            _require(len(tokens) == len(set(tokens)), f"{path}: duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                _schema_check(item, schema["items"], root, f"{path}[{index}]")
    if isinstance(value, str):
        _require(len(value) >= schema.get("minLength", 0), f"{path}: empty string")
    if type(value) in (int, float):
        _require(isfinite(value), f"{path}: nonfinite number")
        for keyword, comparator in (("minimum", lambda a, b: a >= b),
                                    ("maximum", lambda a, b: a <= b),
                                    ("exclusiveMinimum", lambda a, b: a > b)):
            if keyword in schema:
                _require(comparator(value, schema[keyword]), f"{path}: outside {keyword}")


def build_return(competition, verification, reviews, queries, *, data_kind, notice):
    """Serialize the actual B conclusions, preserving all rejection diagnostics."""
    payload = {
        "data_kind": data_kind, "notice": notice,
        "verification": verification.to_dict(),
        "requests": [{"action": "search", "competition_id": query.competition_id,
                      "contest_name": competition.name, "edition": competition.edition,
                      "target_fields": [query.field], "scope": query.scope,
                      "query": query.text, "reason": query.reason, "round": 1}
                     for query in queries],
        "source_reviews": [{"evidence_id": item.evidence.id,
                            "source_verified": item.evidence.source_verified,
                            "support": item.evidence.support, "reasons": list(item.reasons)}
                           for item in reviews],
    }
    validate_return(payload, competition)
    return payload


def validate_return(payload, candidate_raw_or_Competition=None):
    """Reject malformed or mislinked returns; return a diagnostic-preserving receipt.

    Supply C's original candidate for the full check. Without it, source review
    IDs and internal summaries are checked but the receipt explicitly records
    that candidate links were not checked. No input is mutated.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _schema_check(payload, schema, schema)
    candidate = candidate_raw_or_Competition
    if candidate is not None:
        candidate = competition_from_dict(asdict(candidate) if isinstance(candidate, Competition) else candidate)
    result = payload["verification"]
    checks = result["fields"]
    required = result["required_fields"]
    _require(set(required) <= checks.keys(), "required_fields references missing decisions")
    _require(set(result["promoted_fields"]) <= set(required), "promoted_fields must be required")
    try:
        timestamp = datetime.fromisoformat(result["verified_at"])
        _require(timestamp.utcoffset() is not None, "verified_at must include a timezone")
    except (ValueError, OverflowError) as exc:
        raise ValueError("verified_at must be an ISO datetime with timezone") from exc

    reviews = {item["evidence_id"]: item for item in payload["source_reviews"]}
    _require(len(reviews) == len(payload["source_reviews"]), "duplicate source review IDs")
    evidence = {}
    if candidate is not None:
        _require(result["competition_id"] == candidate.id, "competition_id differs from candidate")
        for item in candidate.evidence:
            _require(item.id.strip() and item.id not in evidence, "candidate evidence IDs must be nonempty and unique")
            evidence[item.id] = item
        _require(set(reviews) == set(evidence), "missing or foreign source reviews")
        expected_unknown = sorted((set(candidate.fields) | {item.field for item in candidate.evidence}) - set(FIELD_SPECS) - set(required))
        _require(result["unrecognized_fields"] == expected_unknown, "unrecognized_fields differs from candidate")
        # Contract v1 inspects every populated/evidenced catalogue extension;
        # a receiver must not accept a return that silently drops its problems.
        present = {name for name, value in candidate.fields.items()
                   if value is not None and not (isinstance(value, str) and not value.strip())}
        present |= {item.field for item in candidate.evidence}
        _require(set(checks) == set(required) | (present & set(FIELD_SPECS)),
                 "field decisions omit or invent inspected candidate fields")

    def linked(ref, field=None, *, supported=False):
        _require(ref in reviews, f"unknown evidence reference: {ref}")
        review = reviews[ref]
        if supported:
            _require(review["source_verified"] and review["support"] == "supported",
                     f"evidence {ref} lacks a positive B source review")
        if candidate is not None:
            item = evidence[ref]
            _require(field is None or item.field == field, f"evidence {ref} belongs to another field")
            if supported:
                _require(item.edition == candidate.edition and item.scope == expected_scope(candidate, item.field),
                         f"evidence {ref} has wrong edition or scope")
            return item
        return None

    for name, check in checks.items():
        _require(check["field"] == name, f"fields.{name}: field key mismatch")
        _require(check["required"] == (name in required), f"fields.{name}: required flag mismatch")
        for ref in check["rejected_evidence"]:
            linked(ref, name)
        for ref in check["evidence_ids"]:
            linked(ref, name, supported=True)
        if candidate is not None:
            _require(check["original_value"] == candidate.fields.get(name), f"fields.{name}: original_value changed")
            _require(check["scope"] == expected_scope(candidate, name), f"fields.{name}: scope changed")
            urls = list(dict.fromkeys(item.url for item in candidate.evidence
                                     if item.field == name and normalized_value("url", item.url) is not None))
            _require(set(check["source_urls"]) == set(urls), f"fields.{name}: source_urls differ from candidate")
            candidate_refs = {item.id for item in candidate.evidence if item.field == name}
            _require(set(check["evidence_ids"]) | set(check["rejected_evidence"]) == candidate_refs,
                     f"fields.{name}: evidence is missing its accepted or rejected disposition")
        if check["status"] != "verified":
            _require(check["verified_value"] is None and check["confirmed_statement"] is None
                     and check["value_kind"] is None, f"fields.{name}: unresolved field exposes a verified value")
            _require(check["next_action"] != "none", f"fields.{name}: unresolved field has no action")
            if check["status"] == "pending":
                _require(not check["evidence_ids"] and not check["conflicting_values"],
                         f"fields.{name}: pending field claims accepted/conflicting evidence")
        else:
            _require(check["evidence_ids"] and check["next_action"] == "none"
                     and not check["conflicting_values"], f"fields.{name}: invalid verified conclusion")
            _require(not set(check["evidence_ids"]) & set(check["rejected_evidence"]),
                     f"fields.{name}: verified evidence is also rejected")
            if check["value_kind"] == "value":
                value = check["verified_value"]
                _require(value is not None and normalized_value(name, value) == value
                         and check["confirmed_statement"] is None, f"fields.{name}: invalid canonical value")
                claim = ("value", value)
            else:
                _require(check["value_kind"] == "not_applicable" and check["verified_value"] is None
                         and bool(check["confirmed_statement"]), f"fields.{name}: invalid N/A conclusion")
                claim = ("not_applicable", check["confirmed_statement"])
            if candidate is not None:
                _require(all(normalized_claim(evidence[ref]) == claim for ref in check["evidence_ids"]),
                         f"fields.{name}: verified value is not supported by referenced claims")
        if check["status"] == "conflict":
            _require(check["evidence_ids"], f"fields.{name}: conflict without evidence")
            if check["conflicting_values"] and candidate is not None:
                claims = {normalized_claim(evidence[ref]) for ref in check["evidence_ids"]}
                _require(None not in claims and len(claims) > 1, f"fields.{name}: conflict lacks differing claims")
                expected = sorted("不适用：" + value if kind == "not_applicable" else value for kind, value in claims)
                _require(check["conflicting_values"] == expected, f"fields.{name}: conflict values differ from evidence")

    def same_list(key, expected):
        _require(set(result[key]) == set(expected), f"{key} does not agree with field decisions")

    unresolved = [name for name in required if checks[name]["status"] != "verified"]
    same_list("unresolved_fields", unresolved)
    same_list("missing_fields", [name for name, check in checks.items() if check["original_value"] is None
                                or isinstance(check["original_value"], str) and not check["original_value"].strip()])
    same_list("optional_unresolved_fields", [name for name, check in checks.items() if not check["required"] and check["status"] != "verified"])
    same_list("optional_conflict_fields", [name for name, check in checks.items() if not check["required"] and check["status"] == "conflict"])
    status = "conflict" if any(checks[name]["status"] == "conflict" for name in required) else ("pending" if unresolved else "verified")
    _require(result["status"] == status, "overall status disagrees with required fields")
    coverage = (len(required) - len(unresolved)) / len(required)
    _require(isclose(result["coverage"], coverage, rel_tol=0, abs_tol=1e-12), "coverage disagrees with required fields")
    _require(result["verified_fields"] == {name: check["verified_value"] for name, check in checks.items()
                                           if check["status"] == "verified" and check["value_kind"] == "value"}, "verified_fields summary mismatch")
    _require(result["not_applicable_fields"] == {name: check["confirmed_statement"] for name, check in checks.items()
                                                if check["status"] == "verified" and check["value_kind"] == "not_applicable"}, "not_applicable_fields summary mismatch")

    issue_fields = set()
    for issue in result["consistency_issues"]:
        names = issue["fields"]
        allowed_pairs = {
            "registration_start_after_deadline": [{"registration_start", "registration_deadline"}],
            "individual_only_vs_team_participation": [{"team_rules", "participation_mode"}],
            "online_only_vs_required_onsite": [{"venue", "attendance_mode"}, {"venue", "schedule"}],
        }
        _require(set(names) in allowed_pairs[issue["code"]], "consistency issue code does not match its fields")
        _require(set(names) <= checks.keys() and set(issue["values"]) == set(names), "consistency issue field/value mismatch")
        _require(all(checks[name]["status"] == "conflict" and issue["code"] in checks[name]["reasons"] for name in names),
                 "consistency issue lacks matching conflict decisions")
        expected_refs = list(dict.fromkeys(ref for name in names for ref in checks[name]["evidence_ids"]))
        _require(issue["evidence_ids"] == expected_refs, "consistency issue evidence IDs mismatch")
        _require(len({checks[name]["scope"] for name in names}) == 1, "consistency issue mixes scopes")
        for ref in issue["evidence_ids"]:
            item = linked(ref, supported=True)
            if item is not None:
                claim = normalized_claim(item)
                _require(claim is not None and claim[1] == issue["values"][item.field], "consistency issue value differs from evidence")
        issue_fields.update(names)
    for name, check in checks.items():
        if check["status"] == "conflict" and not check["conflicting_values"]:
            _require(name in issue_fields, f"fields.{name}: conflict lacks values or a consistency issue")

    actions = result["action_items"]
    action_names = [item["field"] for item in actions]
    _require(len(action_names) == len(set(action_names)) and set(action_names) == set(unresolved),
             "action_items must cover each unresolved required field exactly once")
    for action in actions:
        check = checks[action["field"]]
        for action_key, field_key in (("action", "next_action"), ("reason", "action_reason"),
                                      ("scope", "scope"), ("evidence_ids", "evidence_ids"), ("source_urls", "source_urls")):
            _require(action[action_key] == check[field_key], f"action_items.{action['field']}: {action_key} mismatch")
        _require(action["owner"] == _OWNERS[check["next_action"]], "action owner mismatch")
        _require(action["candidate_evidence_refs"] == list(check["rejected_evidence"]), "action candidate evidence refs mismatch")

    requested = []
    for request in payload["requests"]:
        _require(request["competition_id"] == result["competition_id"], "search request competition ID mismatch")
        for name in request["target_fields"]:
            _require(name in unresolved and checks[name]["next_action"] == "search", "request targets a resolved or non-search field")
            _require(request["scope"] == checks[name]["scope"], "search request scope mismatch")
            requested.append(name)
        if candidate is not None:
            _require(request["contest_name"] == candidate.name and request["edition"] == candidate.edition,
                     "search request contest name or edition mismatch")
            _require(candidate.name.strip() in request["query"] and candidate.edition.strip() in request["query"],
                     "search text omits contest identity")
            if request["scope"] != "global":
                _require(request["scope"] in request["query"], "search text omits target scope")
    expected_search = [name for name in unresolved if checks[name]["next_action"] == "search"]
    _require(len(requested) == len(set(requested)) and set(requested) == set(expected_search),
             "requests must cover the planned search fields exactly once")

    return {"contract_version": CONTRACT_VERSION, "accepted": True,
            "candidate_links_checked": candidate is not None,
            "competition_id": result["competition_id"], "status": status,
            "field_count": len(checks), "source_review_count": len(reviews),
            "request_count": len(payload["requests"]),
            "rejected_evidence_count": sum(len(check["rejected_evidence"]) for check in checks.values()),
            "consistency_issue_count": len(result["consistency_issues"]),
            "notice": "接口校验通过不代表已独立核验网页真实性；这是 C 可复用的参考接收器。",
            "received_payload": deepcopy(payload)}
