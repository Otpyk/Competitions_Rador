"""Canonical 31-field seam for A/C; frozen policy and B-only source approvals."""
from copy import deepcopy
from dataclasses import replace

from .b_io import competition_from_dict
from .evidence_verifier import verify_competition
from .field_catalog import build_policy
from .frozen import load_approvals, load_policy, load_contexts
from .query_planner import plan_queries
from .return_contract import build_return, validate_return
from .source_review import SourceSnapshot, review_competition


def verify_contests(contests, *, sources, hard_constraints=(), extra_required_fields=()):
    """Return b-c-return-v1 envelopes; never accepts C-supplied approvals.

    Unknown C edition null is an empty internal identity, not an inferred year.
    A/C still own extraction target construction and source/quote provenance.
    """
    policy = load_policy()
    if hard_constraints or extra_required_fields:
        required = build_policy(hard_constraints=hard_constraints, extra_required_fields=extra_required_fields)
        policy = replace(policy, required_fields=required.required_fields, promoted_fields=required.promoted_fields,
                         requirement_reasons=required.requirement_reasons)
    approvals = load_approvals()
    contexts = load_contexts()
    ids = [source["source_id"] for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source snapshot IDs")
    snapshots = [SourceSnapshot(s["url"], s["content"], s.get("fetched_at"), s["source_id"]) for s in sources]
    outputs, seen = [], set()
    for raw in contests:
        candidate = deepcopy(raw)
        if candidate.get("edition") is None:
            candidate["edition"] = ""
        for field in candidate.get("fields", {}).values():
            if isinstance(field, dict):
                for ev in field.get("evidence", []):
                    if ev.get("edition") is None:
                        ev["edition"] = ""
        comp = competition_from_dict(candidate)
        if comp.id in seen:
            raise ValueError("Duplicate competition ID")
        seen.add(comp.id)
        target = contexts.get(comp.id, {})
        matching_identity = (comp.name == target.get("expected_name")
                             and comp.edition == target.get("expected_edition"))
        reviewed, notes = review_competition(comp, approved_sources=approvals if matching_identity else [], snapshots=snapshots)
        result = verify_competition(reviewed, policy)
        payload = build_return(reviewed, result, notes, plan_queries(reviewed, result),
                               data_kind="real_candidate_frozen_policy_verification",
                               notice="B正式策略与来源审批；无法由保守原文规则确认的内容保留待确认。未执行补搜。")
        validate_return(payload, candidate)
        outputs.append(payload)
    return outputs
