"""Synthetic A/B/C integration; no web, model, or real contest verification."""

import asyncio
from copy import deepcopy
from datetime import datetime
import importlib
import json
import sys
from types import ModuleType

import pytest

from api_models import ResearchResult, SearchRequest, Source
from competition_radar.schemas import FIELD_NAMES
from pydantic import ValidationError


AS_OF = datetime.fromisoformat("2026-10-22T12:00:00+08:00")
PROFILE = {
    "education_level": "本科", "major": "计算机科学与技术", "grade": 2,
    "team_size": 3, "interests": ["编程"], "deadline_from": None,
    "deadline_to": None,
}


def synthetic_result(record_id, *, task_id="task-shared", status="success"):
    values = {
        "name": "合成挑战赛", "organizer": "合成主办方", "edition": "2026届",
        "track": "编程", "stage": "正式报名", "tags": ["编程"],
        "eligibility": {
            "allowed_education_levels": ["本科"], "allowed_majors": [],
            "allowed_grades": [], "team_size": {"min": 2, "max": 3},
            "other_requirements": [],
        },
        "registration_start": {"date": "2026-10-20", "time": "09:00:00", "timezone": "Asia/Shanghai"},
        "registration_deadline": {"date": "2026-10-24", "time": "18:00:00", "timezone": "Asia/Shanghai"},
        "official_url": "https://example.invalid/contest",
        "registration_url": "https://example.invalid/register",
    }
    claims = []
    for field, value in values.items():
        quote = f"{record_id} {field}={json.dumps(value, ensure_ascii=False)}"
        claims.append({
            "claim_id": f"{record_id}-{field}", "field": field, "value": value,
            "evidence": [{"source_id": f"source-{record_id}", "quote": quote}],
        })
    source = {
        "source_id": f"source-{record_id}", "url": f"https://example.invalid/{record_id}",
        "title": "合成正文快照", "snippet": "这只是摘要，不用于字段证据。",
        "content": "\n".join(item["evidence"][0]["quote"] for item in claims),
        "fetched_at": "2026-10-22T11:00:00+08:00", "published_date": None,
    }
    result = ResearchResult(
        task_id=task_id, query=record_id, status=status,
        report="生成的报告不作为正文证据。", sources=[source] if status == "success" else [],
        error=None if status == "success" else "合成搜索失败", engine="synthetic",
    )
    return result, {"record_id": record_id, "member_ids": [record_id], "claims": claims}


@pytest.fixture
def backend(monkeypatch):
    # Do not load the uploaded package's .env, including during module import.
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    config = importlib.import_module("config")
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None, researcher_mode="mock"))
    module = importlib.import_module("main")
    for name in ("extractor", "evidence_verifier", "query_planner"):
        monkeypatch.setitem(sys.modules, name, None)
    return module


def hook(monkeypatch, module_name, attr_name, function):
    module = ModuleType(module_name)
    setattr(module, attr_name, function)
    monkeypatch.setitem(sys.modules, module_name, module)


class SyntheticService:
    def __init__(self, initial, supplementary=()):
        self.initial = initial
        self.results = list(supplementary)
        self.requests = []

    async def run(self, request):
        return self.initial.model_copy(deep=True)

    async def supplementary(self, request):
        self.requests.append(request)
        result = self.results.pop(0).model_copy(deep=True)
        result.round = request.round
        return result


def install_extractor(monkeypatch, candidates, seen_batches=None):
    def extract(batch):
        if seen_batches is not None:
            seen_batches.append(deepcopy(batch))
        return deepcopy(candidates.get(batch["query"], []))
    hook(monkeypatch, "extractor", "extract_competitions", extract)


def install_verifier(monkeypatch, calls):
    def verify(candidates, *, sources):
        calls.append(deepcopy((candidates, sources)))
        results = []
        for candidate in candidates:
            selected = {claim["field"]: claim["claim_id"] for claim in candidate["claims"]}
            results.append({
                "record_id": candidate["record_id"],
                "fields": [{
                    "field": field, "status": "verified" if field in selected else "missing",
                    "selected_claim_id": selected.get(field), "reason": "合成 B 裁决，仅用于联调",
                } for field in FIELD_NAMES],
                "verification_status": "verified", "verified_at": "2026-10-22T11:30:00+08:00",
            })
        return results
    hook(monkeypatch, "evidence_verifier", "verify", verify)


def run(backend, profile=PROFILE, max_rounds=1):
    return asyncio.run(backend.run_pipeline(
        SearchRequest(query="合成检索", profile=deepcopy(profile), max_rounds=max_rounds), as_of=AS_OF,
    ))


def stage(response, name):
    return next(item for item in response.stages if item.name == name)


def test_explicit_snapshot_and_verification_context_reaches_real_c_rules(backend, monkeypatch):
    result, candidate = synthetic_result("r1")
    monkeypatch.setattr(backend, "service", SyntheticService(result))
    batches, calls = [], []
    install_extractor(monkeypatch, {"r1": [candidate]}, batches)
    install_verifier(monkeypatch, calls)
    response = run(backend)
    assert response.task_id == response.research.task_id == "task-shared"
    assert batches[0]["task_id"] == "task-shared"
    assert "report" not in batches[0] and "snippet" not in batches[0]["sources"][0]
    assert calls[0][1][0]["content"] == result.sources[0].content
    assert response.recommendations["as_of"] == AS_OF.isoformat()
    item = response.recommendations["recommended"][0]
    assert item["record_id"] == "r1"
    assert all(field["claim_id"].startswith("r1-") for field in item["fields"])
    assert stage(response, "rank").status == "ran"
    assert stage(response, "plan_queries").status == "not_integrated"


def test_legacy_report_and_snippet_are_not_substituted_for_snapshot(backend, monkeypatch):
    result, candidate = synthetic_result("r1")
    result.sources[0].source_id = None
    result.sources[0].content = None
    result.sources[0].fetched_at = None
    monkeypatch.setattr(backend, "service", SyntheticService(result))
    batches = []
    install_extractor(monkeypatch, {"r1": [candidate]}, batches)
    response = run(backend)
    assert not batches and response.recommendations is None
    assert stage(response, "extract").status == "blocked"
    assert stage(response, "extract").detail["issues"]
    assert response.research.sources[0].snippet


def test_without_b_never_runs_recommendation(backend, monkeypatch):
    result, candidate = synthetic_result("r1")
    monkeypatch.setattr(backend, "service", SyntheticService(result))
    install_extractor(monkeypatch, {"r1": [candidate]})
    response = run(backend)
    assert response.competitions and response.recommendations is None
    assert stage(response, "verify_and_supplement").status == "not_integrated"
    assert stage(response, "rank").status == "blocked"


@pytest.mark.parametrize("profile", [None, {"major": "计算机", "grade": "大三"}, {**PROFILE, "grade": "大三"}])
def test_incomplete_or_unmapped_profile_blocks_rank(backend, monkeypatch, profile):
    result, candidate = synthetic_result("r1")
    monkeypatch.setattr(backend, "service", SyntheticService(result))
    install_extractor(monkeypatch, {"r1": [candidate]})
    install_verifier(monkeypatch, [])
    response = run(backend, profile=profile)
    assert response.recommendations is None
    assert stage(response, "rank").status == "blocked"


def test_last_allowed_round_retains_every_source_and_claim_then_verifies(backend, monkeypatch):
    first, first_candidate = synthetic_result("r1")
    second, second_candidate = synthetic_result("r2")
    third, _ = synthetic_result("r3")
    service = SyntheticService(first, [second, third])
    monkeypatch.setattr(backend, "service", service)
    install_extractor(monkeypatch, {"r1": [first_candidate], "r2": [second_candidate], "r3": []})
    calls = []
    install_verifier(monkeypatch, calls)
    hook(monkeypatch, "query_planner", "plan_queries", lambda verified, **context: [
        {"contest_name": "合成挑战赛", "query": "补查一"},
        {"contest_name": "合成挑战赛", "query": "补查二"},
    ])
    response = run(backend, max_rounds=1)
    assert len(calls) == 2
    assert len(calls[0][1]) == 1 and len(calls[-1][1]) == 3
    assert len(calls[-1][0]) == 1
    assert calls[-1][0][0]["member_ids"] == ["r1", "r2"]
    assert len(calls[-1][0][0]["claims"]) == 22
    assert [item.round for item in response.research_history] == [1, 2, 2]
    assert all(request.task_id == "task-shared" and request.round == 2 for request in service.requests)
    assert len(response.competitions[0]["claims"]) == 22
    fields = response.recommendations["recommended"][0]["fields"]
    assert all(item["claim_id"].startswith("r2-") for item in fields)
    assert {e["source_id"] for item in fields for e in item["evidence"]} == {"source-r2"}


def test_source_only_supplement_also_invalidates_and_rechecks_b(backend, monkeypatch):
    initial, candidate = synthetic_result("r1")
    extra, _ = synthetic_result("extra")
    monkeypatch.setattr(backend, "service", SyntheticService(initial, [extra]))
    install_extractor(monkeypatch, {"r1": [candidate], "extra": []})
    calls = []
    install_verifier(monkeypatch, calls)
    hook(monkeypatch, "query_planner", "plan_queries", lambda verified, **context: [{"contest_name": "合成挑战赛", "query": "补查"}])
    response = run(backend)
    assert len(calls) == 2 and len(calls[-1][1]) == 2
    assert response.recommendations["recommended"]


def test_planner_receives_json_context_and_failed_history_without_mutating_a_pools(backend, monkeypatch):
    initial, candidate = synthetic_result("r1")
    failed, _ = synthetic_result("failed", status="failed")
    monkeypatch.setattr(backend, "service", SyntheticService(initial, [failed]))
    install_extractor(monkeypatch, {"r1": [candidate]})
    install_verifier(monkeypatch, [])
    seen = []

    def plan(verification, *, competitions, sources, research_history):
        seen.append(deepcopy((verification, competitions, sources, research_history)))
        json.dumps([verification, competitions, sources, research_history])
        verification[0]["fields"][0]["selected_claim_id"] = "mutated-outside-a"
        competitions[0]["claims"][0]["value"] = "mutated-outside-a"
        sources[0]["content"] = "mutated-outside-a"
        research_history[0]["query"] = "mutated-outside-a"
        if len(seen) == 1:
            return [{"contest_name": "合成挑战赛", "query": "补查"}]
        return []

    hook(monkeypatch, "query_planner", "plan_queries", plan)
    response = run(backend, max_rounds=2)
    assert len(seen) == 2
    assert seen[0][1][0] == candidate
    assert seen[0][2][0]["source_id"] == "source-r1"
    assert seen[0][3][0]["task_id"] == "task-shared"
    assert seen[1][1][0] == candidate
    assert seen[1][2][0]["content"] == initial.sources[0].content
    assert seen[1][3][-1]["status"] == "failed"
    assert seen[1][3][-1]["query"] == "failed"
    assert seen[1][3][-1]["round"] == 2 and seen[1][3][-1]["error"]
    assert response.research.query == "r1"
    assert response.competitions[0] == candidate
    assert response.recommendations["recommended"][0]["fields"][0]["claim_id"] == "r1-name"


def test_explicit_unknown_title_survives_a_result_to_c_adapter(backend, monkeypatch):
    initial, candidate = synthetic_result("r1")
    initial.sources[0] = Source.model_validate({**initial.sources[0].model_dump(), "title": None})
    monkeypatch.setattr(backend, "service", SyntheticService(initial))
    batches = []
    install_extractor(monkeypatch, {"r1": [candidate]}, batches)
    install_verifier(monkeypatch, [])
    response = run(backend)
    assert batches[0]["sources"][0]["title"] is None
    assert response.research.sources[0].title is None
    assert response.recommendations["recommended"]


def test_failed_supplement_keeps_prior_valid_context_and_error_history(backend, monkeypatch):
    initial, candidate = synthetic_result("r1")
    failed, _ = synthetic_result("failed", status="failed")
    monkeypatch.setattr(backend, "service", SyntheticService(initial, [failed]))
    install_extractor(monkeypatch, {"r1": [candidate]})
    calls = []
    install_verifier(monkeypatch, calls)
    hook(monkeypatch, "query_planner", "plan_queries", lambda verified, **context: [{"contest_name": "合成挑战赛", "query": "补查"}])
    response = run(backend)
    assert len(response.research_history) == 2
    assert response.research_history[-1].status.value == "failed"
    assert response.competitions[0]["claims"] == candidate["claims"]
    assert response.recommendations["recommended"]
    assert stage(response, "verify_and_supplement").status == "failed"


@pytest.mark.parametrize("corruption", ["source_id", "record_id", "quote", "b_selection"])
def test_corrupted_supplement_or_b_reference_blocks_rank(backend, monkeypatch, corruption):
    initial, candidate = synthetic_result("r1")
    extra, extra_candidate = synthetic_result("r2")
    if corruption == "source_id":
        extra.sources[0].source_id = "source-r1"
    elif corruption == "record_id":
        extra_candidate["record_id"] = "r1"
        extra_candidate["member_ids"] = ["r1"]
    elif corruption == "quote":
        extra_candidate["claims"][0]["evidence"][0]["quote"] = "不存在的正文"
    monkeypatch.setattr(backend, "service", SyntheticService(initial, [extra]))
    install_extractor(monkeypatch, {"r1": [candidate], "r2": [extra_candidate]})
    if corruption == "b_selection":
        def verify(candidates, *, sources):
            return [{
                "record_id": candidates[0]["record_id"],
                "fields": [{"field": field, "status": "verified", "selected_claim_id": "other-record-claim", "reason": "错误合成裁决"} for field in FIELD_NAMES],
                "verification_status": "verified", "verified_at": AS_OF.isoformat(),
            }]
        hook(monkeypatch, "evidence_verifier", "verify", verify)
    else:
        install_verifier(monkeypatch, [])
    hook(monkeypatch, "query_planner", "plan_queries", lambda verified, **context: [{"contest_name": "合成挑战赛", "query": "补查"}])
    response = run(backend)
    assert response.recommendations is None
    assert stage(response, "rank").status == "blocked"


def test_initial_research_failure_keeps_one_task_and_history(backend, monkeypatch):
    failed, _ = synthetic_result("failed", status="failed")
    monkeypatch.setattr(backend, "service", SyntheticService(failed))
    response = run(backend)
    assert response.status == "research_failed"
    assert response.task_id == response.research.task_id == "task-shared"
    assert len(response.research_history) == 1 and response.recommendations is None


@pytest.mark.parametrize("field,value", [
    ("fetched_at", 1792627200), ("fetched_at", True),
    ("fetched_at", "2026-10-22T12:00:00"),
    ("published_date", 1792627200), ("published_date", "2026-1-01"),
    ("published_date", "2026-10-22T00:00:00"),
])
def test_a_source_does_not_hide_invalid_snapshot_time_before_c_validation(field, value):
    with pytest.raises(ValidationError):
        Source.model_validate({"title": "合成来源", "url": "https://example.invalid", field: value})


def test_broken_hook_dependency_is_failed_instead_of_optional_absence(backend, monkeypatch):
    result, _ = synthetic_result("r1")
    monkeypatch.setattr(backend, "service", SyntheticService(result))
    actual_import = backend.importlib.import_module
    def broken_import(name):
        if name == "extractor":
            raise ModuleNotFoundError("missing extractor internal dependency", name="internal_dependency")
        return actual_import(name)
    monkeypatch.setattr(backend.importlib, "import_module", broken_import)
    response = run(backend)
    assert stage(response, "extract").status == "failed"
    assert "internal_dependency" in stage(response, "extract").detail["error"] or "dependency" in stage(response, "extract").detail["error"]
