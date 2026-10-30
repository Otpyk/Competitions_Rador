"""Bounded, evidence-aware follow-up search for the B-side prototype.

The callback is A's search and C's extraction adapter. It receives the remaining
budget, including the call about to happen. A monetary ceiling is a *hard* ceiling
only when that adapter enforces the supplied per-call allowance: this controller
cannot undo charges and otherwise detects an overspend after the callback.

Progress means a new accepted (required field, normalized value) claim. New IDs,
URLs, quotations or retrieval timestamps for an existing claim are not progress.
Previously untried executable queries take precedence over retries. An empty
three-query round does not imply that the remaining required fields were tried;
no-progress early stopping applies once all currently executable queries have
had an opportunity. Round and call budgets still cap exploration.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from math import isfinite
from time import perf_counter
from typing import Callable

from .b_contracts import (
    AdaptiveResult,
    Competition,
    Evidence,
    SearchBatch,
    SearchBudget,
    SearchEvent,
    SearchQuery,
    VerificationPolicy,
)
from .b_io import evidence_from_dict
from .evidence_verifier import (
    evidence_rejection_reasons,
    normalized_claim,
    verify_competition,
)
from .query_planner import plan_queries


SearchCallback = Callable[[SearchQuery, SearchBudget], SearchBatch]


def _query_key(query: SearchQuery) -> tuple[str, str, str]:
    return query.field, query.scope, query.text


def _valid_claims(
    competition: Competition, policy: VerificationPolicy
) -> set[tuple[str, tuple[str, str]]]:
    claims = set()
    for evidence in competition.evidence:
        if evidence.field not in policy.required_fields:
            continue
        if evidence_rejection_reasons(evidence, competition, policy):
            continue
        value = normalized_claim(evidence)
        if value is not None:
            claims.add((evidence.field, value))
    return claims


def _payload(evidence: Evidence) -> dict:
    """IDs identify records; equality of their contents detects exact copies."""
    payload = asdict(evidence)
    payload.pop("id")
    return payload


def _append_evidence(competition: Competition, incoming: list[Evidence]) -> int:
    """Retain distinct records, preserving conflicting contents on ID collisions."""
    ids = {record.id for record in competition.evidence}
    payloads = [_payload(record) for record in competition.evidence]
    appended = 0
    for original in incoming:
        payload = _payload(original)
        if payload in payloads:
            continue
        record = deepcopy(original)
        if record.id in ids:
            suffix = 2
            while f"{record.id}#{suffix}" in ids:
                suffix += 1
            record = replace(record, id=f"{record.id}#{suffix}")
        competition.evidence.append(record)
        ids.add(record.id)
        payloads.append(payload)
        appended += 1
    return appended


def run_adaptive_search(
    competition: Competition,
    search_callback: SearchCallback,
    *,
    policy: VerificationPolicy | None = None,
    budget: SearchBudget | None = None,
    enabled: bool = True,
) -> AdaptiveResult:
    """Verify a private copy and issue only bounded, targeted follow-up calls.

    ``enabled=False`` is the ablation path: verification is identical, but there
    are no follow-up searches. An already verified result always stops complete.

    Every invoked callback produces an event, including failed calls. Unknown
    cost is never treated as zero: it marks ``cost_complete=False`` and, if a
    monetary budget exists, stops immediately. Exceptions stop with search_error
    because retrying could incur additional unreported costs.
    """
    current = deepcopy(competition)
    policy = policy or VerificationPolicy()
    budget = budget or SearchBudget()
    verification = verify_competition(current, policy)
    events: list[SearchEvent] = []
    calls = 0
    rounds = 0
    known_cost = 0.0
    cost_complete = True
    no_progress_rounds = 0
    attempt_counts: dict[tuple[str, str, str], int] = {}

    def finish(reason: str) -> AdaptiveResult:
        return AdaptiveResult(
            competition=current,
            verification=verification,
            stop_reason=reason,
            rounds=rounds,
            calls=calls,
            known_cost=known_cost,
            cost_complete=cost_complete,
            events=events,
        )

    def stalled_reason() -> str:
        if verification.status == "conflict":
            return "unresolved_conflict"
        return "no_new_evidence"

    if verification.status == "verified":
        return finish("complete")
    if not enabled:
        return finish("adaptive_disabled")

    while rounds < budget.max_rounds:
        round_number = rounds + 1
        round_start_claims = _valid_claims(current, policy)
        round_calls = 0
        attempted: set[tuple[str, str, str]] = set()

        while round_calls < budget.max_queries_per_round:
            if calls >= budget.max_calls:
                return finish("max_calls")
            if budget.max_cost is not None and known_cost >= budget.max_cost:
                return finish("max_cost")

            # Re-plan after each response. Preserve the planner's priority among
            # equally attempted queries, while giving untouched fields a chance
            # before repeating a failed query from an earlier round.
            planned = plan_queries(current, verification)
            if not planned:
                return finish("handoff_required")
            query = min(
                (item for item in planned if _query_key(item) not in attempted),
                key=lambda item: attempt_counts.get(_query_key(item), 0),
                default=None,
            )
            if query is None:
                break
            key = _query_key(query)
            attempted.add(key)
            attempt_counts[key] = attempt_counts.get(key, 0) + 1
            remaining = SearchBudget(
                max_rounds=budget.max_rounds - round_number + 1,
                max_calls=budget.max_calls - calls,
                max_queries_per_round=budget.max_queries_per_round - round_calls,
                max_cost=(
                    None if budget.max_cost is None else budget.max_cost - known_cost
                ),
                max_no_progress_rounds=(
                    budget.max_no_progress_rounds - no_progress_rounds
                ),
            )

            before_status = verification.status
            before_coverage = verification.coverage
            before_verified = {
                name for name, check in verification.fields.items()
                if check.status == "verified"
            }
            before_claims = _valid_claims(current, policy)
            started = perf_counter()
            cost = None
            error = None
            added = 0
            calls += 1
            round_calls += 1
            rounds = round_number

            try:
                batch = search_callback(query, remaining)
                if not isinstance(batch, SearchBatch):
                    raise TypeError("search_callback must return SearchBatch")
                if batch.cost is not None:
                    if (
                        isinstance(batch.cost, bool)
                        or not isinstance(batch.cost, (int, float))
                        or not isfinite(batch.cost)
                        or batch.cost < 0
                    ):
                        raise ValueError("SearchBatch.cost must be finite and nonnegative")
                    cost = float(batch.cost)
                if not isinstance(batch.evidence, list) or not all(
                    isinstance(item, Evidence) for item in batch.evidence
                ):
                    raise TypeError("SearchBatch.evidence must be a list of Evidence")
                # Dataclass type annotations are not runtime validation. Validate
                # the whole batch before merging any record, so malformed adapter
                # output cannot corrupt existing evidence or escape event logging.
                validated_evidence = [evidence_from_dict(asdict(item)) for item in batch.evidence]
                added = _append_evidence(current, validated_evidence)
                if batch.error is not None:
                    error = str(batch.error) or "search callback reported an error"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            elapsed = perf_counter() - started
            if cost is None:
                cost_complete = False
            else:
                known_cost += cost
            verification = verify_competition(current, policy)
            new_claims = _valid_claims(current, policy) - before_claims
            events.append(
                SearchEvent(
                    round=round_number,
                    query=query,
                    before_status=before_status,
                    after_status=verification.status,
                    new_evidence_count=added,
                    new_valid_evidence_count=len(new_claims),
                    cost=cost,
                    elapsed_seconds=elapsed,
                    error=error,
                    newly_verified_fields=[
                        name for name, check in verification.fields.items()
                        if check.status == "verified" and name not in before_verified
                    ],
                    coverage_before=before_coverage,
                    coverage_after=verification.coverage,
                )
            )

            # Report failures and budget incidents even if partial evidence also
            # happened to complete verification during the failed/overpaid call.
            if error is not None:
                return finish("search_error")
            if budget.max_cost is not None:
                if cost is None:
                    return finish("unknown_cost")
                if known_cost > budget.max_cost:
                    return finish("max_cost")
            if verification.status == "verified":
                return finish("complete")
            if calls >= budget.max_calls:
                return finish("max_calls")
            if budget.max_cost is not None and known_cost >= budget.max_cost:
                return finish("max_cost")

        if round_calls == 0:
            return finish(stalled_reason())
        remaining_queries = plan_queries(current, verification)
        if not remaining_queries:
            return finish("handoff_required")
        if _valid_claims(current, policy) - round_start_claims:
            no_progress_rounds = 0
        elif any(attempt_counts.get(_query_key(item), 0) == 0 for item in remaining_queries):
            # The next bounded round can explore untouched requirements. Do not
            # consume retry patience before those queries have ever been tried.
            no_progress_rounds = 0
        else:
            no_progress_rounds += 1
            if no_progress_rounds >= budget.max_no_progress_rounds:
                return finish(stalled_reason())

    return finish("max_rounds")
