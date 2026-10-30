"""Pure B -> A query adapter; no cross-task cache or approval rewriting."""
from b_app.query_planner import plan_queries as b_plan_queries
from evidence_verifier import evaluate_candidates, _to_c_verification
from b_app.frozen import FIELD_MAP

_C_FIELD = {value: key for key, value in FIELD_MAP.items()}

def plan_queries(verification, *, competitions, sources, research_history):
    supplied = {item["record_id"]: item for item in verification}
    if len(supplied) != len(verification) or set(supplied) != {c["record_id"] for c in competitions}:
        raise ValueError("Query planning verification/candidate identity mismatch")
    prior = {item.get("query") for item in research_history}
    used_calls = sum(1 for item in research_history if item.get("round", 1) > 1)
    remaining_calls = max(0, 6 - used_calls)
    requests = []
    for candidate, reviewed, result, _ in evaluate_candidates(competitions, sources=sources):
        expected = _to_c_verification(candidate, result)
        if supplied[candidate["record_id"]]["fields"] != expected["fields"]:
            raise ValueError("Query planning received stale or changed B field decisions")
        for query in b_plan_queries(reviewed, result):
            if query.text in prior:
                continue
            requests.append({"action": "search", "contest_name": reviewed.name,
                             "target_fields": [_C_FIELD[query.field]], "query": query.text,
                             "reason": query.reason + f"（范围：{query.scope}）"})
    return requests[:min(3, remaining_calls)]
