"""B ownership, bridge safety, and actual C receiver regressions."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from b_app.b_contracts import Competition, Evidence
from b_app.evidence_verifier import verify_competition
from b_app.frozen import load_approvals, load_policy, FIELD_MAP
from b_app.source_review import ApprovedSource, SourceSnapshot, review_evidence
from evidence_verifier import verify, _to_b_competition, _stringify
from extractor import extract_competitions
from query_planner import plan_queries

ROOT = Path(__file__).resolve().parents[1]
BATCH = json.loads((ROOT / "examples/research_result_real_batch.json").read_text(encoding="utf-8"))


def test_formal_policy_has_explicit_distinct_22_and_9_profiles():
    assert len(load_policy().required_fields) == 22
    assert tuple(FIELD_MAP.values()) == load_policy("legacy_11_bridge").required_fields
    assert load_policy().accepted_source_types == ("official",)


def test_formal_approvals_exact_id_edition_scope_and_url_no_demo():
    rows = load_approvals()
    assert len(rows) == 22
    assert {r.source_type for r in rows} == {"school"}
    assert all("demo" not in r.approved_by for r in rows)
    assert any(r.edition == "第十八届" for r in rows)


def test_school_can_verify_own_notice_but_not_global_rules():
    url = "https://school.example.invalid/notice"
    for scope, expected in [("campus:学校甲", "verified"), ("global", "pending")]:
        item = Competition("fixture", "虚构赛", "2026", scope=scope,
                           evidence=[Evidence("e", "official_url", url, url, "标题", "2026",
                                              source_type="school", source_verified=True, support="supported", scope=scope,
                                              reviewed_by="B:fixture")])
        assert verify_competition(item, load_policy()).fields["official_url"].status == expected


def test_bridge_edition_independent_of_claim_order_and_all_refs_kept():
    c = extract_competitions(BATCH)[0]
    c["claims"] = list(reversed(c["claims"]))
    c["claims"][0]["evidence"].append(deepcopy(c["claims"][0]["evidence"][0]))
    comp = _to_b_competition(c, {s["source_id"]: s for s in BATCH["sources"]})
    assert comp.edition == "2026"
    assert all(e.edition == "2026" for e in comp.evidence)
    assert len(comp.evidence) == sum(len(x["evidence"]) for x in c["claims"] if x["field"] in FIELD_MAP)


def test_unknown_timezone_does_not_turn_into_a_whole_day():
    text = _stringify({"date": "2026-09-05", "time": "23:00", "timezone": None}, "registration_deadline")
    assert text != "2026-09-05"
    assert "23:00" in text


def test_structured_eligibility_keeps_major_and_every_condition():
    value = {"allowed_majors": ["数学"], "allowed_grades": [2], "other_requirements": ["未参加过往届"]}
    assert json.loads(_stringify(value, "eligibility")) == value


def test_draft_cannot_approve_other_record_or_edition_or_name():
    candidates = extract_competitions(BATCH)
    for changed in ("record_id", "edition", "name"):
        c = deepcopy(candidates[0])
        if changed == "record_id":
            c["record_id"] = "not-approved"
        else:
            next(claim for claim in c["claims"] if claim["field"] == changed)["value"] = "另一个赛事" if changed == "name" else "2025"
        result = verify([c], sources=BATCH["sources"])[0]
        assert not any(x["status"] == "verified" for x in result["fields"])


def test_current_old_chain_can_verify_notice_links_only_and_keeps_stage_tags_unknown():
    results = verify(extract_competitions(BATCH), sources=BATCH["sources"])
    assert sum(x["status"] == "verified" for r in results for x in r["fields"]) >= 1
    for r in results:
        assert all(x["status"] != "verified" for x in r["fields"] if x["field"] in ("stage", "tags"))


def test_planning_is_stateless_rejects_stale_results_and_obeys_call_limit():
    candidates = extract_competitions(BATCH)
    decisions = verify(candidates, sources=BATCH["sources"])
    verify([], sources=[])
    queries = plan_queries(decisions, competitions=candidates, sources=BATCH["sources"], research_history=[])
    assert 0 < len(queries) <= 3
    assert all(set(q["target_fields"]) <= FIELD_MAP.keys() for q in queries)
    assert plan_queries(decisions, competitions=candidates, sources=BATCH["sources"], research_history=[{"round": 2}]*6) == []
    bad = deepcopy(decisions)
    bad[0]["fields"][0]["reason"] = "changed"
    with pytest.raises(ValueError):
        plan_queries(bad, competitions=candidates, sources=BATCH["sources"], research_history=[])


def test_snapshot_id_selects_exact_page_revision():
    url = "https://contest.example.invalid/notice"
    comp = Competition("x", "虚构赛", "2026")
    ev = Evidence("e", "official_url", url, url, "标题", "2026", source_id="new")
    result = review_evidence(comp, ev, approved_sources=[ApprovedSource("x", "2026", "global", url, "official", "B:test")],
                             snapshots=[SourceSnapshot(url, "标题", source_id="old"), SourceSnapshot(url, "标题", source_id="new")])
    assert result.evidence.support == "supported"
    missing = review_evidence(comp, ev, approved_sources=[ApprovedSource("x", "2026", "global", url, "official", "B:test")],
                              snapshots=[SourceSnapshot(url, "标题", source_id="old")])
    assert not missing.evidence.source_verified


def test_actual_c_consumer_accepts_all_six_with_frozen_policy(tmp_path):
    from examples.run_b_acceptance import run
    report = run(tmp_path / "actual")
    assert report["candidate_count"] == 6 and report["c_actual_consumer_executed"]
    assert all(r["c_actual_consumer_accepted"] for r in report["receipts"])
    assert report["verified_field_count"] >= 1


def test_actual_c_consumer_rejects_forged_verified_value(tmp_path):
    from examples.run_b_acceptance import run
    from competition_radar.b_handoff import BContest
    from competition_radar.b_return import consume_b_return
    from competition_radar.schemas import SourceDocument
    run(tmp_path)
    candidates = json.loads((ROOT / "data/b_canonical_batch/c_to_b_contests.json").read_text(encoding="utf-8"))
    candidate = next(c for c in candidates if "nufe" in c["id"])
    payload = json.loads((tmp_path / "results" / (candidate["id"] + ".json")).read_text(encoding="utf-8"))
    payload["verification"]["fields"]["official_url"]["verified_value"] = "https://forged.example.invalid"
    with pytest.raises(ValueError):
        consume_b_return(payload, BContest.model_validate(candidate), [SourceDocument.model_validate(s) for s in BATCH["sources"]],
                         required_fields=load_policy().required_fields)


def test_c_null_edition_stays_unknown_and_is_accepted_by_actual_receiver():
    from b_app.service import verify_contests
    from competition_radar.b_handoff import BContest
    from competition_radar.b_return import consume_b_return
    raw = {"id": "unknown-target", "name": "届次未知的赛事", "edition": None, "scope": "global",
           "field_scopes": {}, "fields": {f: {"value": None, "evidence": []} for f in load_policy().required_fields}}
    before = deepcopy(raw)
    payload = verify_contests([raw], sources=[])[0]
    assert payload["requests"] == [] and raw == before
    consume_b_return(payload, BContest.model_validate(raw), [], required_fields=load_policy().required_fields)


def test_canonical_approval_does_not_follow_a_renamed_target():
    from b_app.service import verify_contests
    candidates = json.loads((ROOT / "data/b_canonical_batch/c_to_b_contests.json").read_text(encoding="utf-8"))
    raw = next(c for c in candidates if "nufe" in c["id"])
    raw["name"] = "错误赛事名称"
    raw["fields"]["competition_name"]["value"] = None
    raw["fields"]["competition_name"]["evidence"] = []
    payload = verify_contests([raw], sources=BATCH["sources"])[0]
    assert not any(x["source_verified"] for x in payload["source_reviews"])
    assert payload["verification"]["verified_fields"] == {}


@pytest.mark.parametrize("kind", ["verified", "unknown", "unsupported", "conflict", "not_applicable", "cross_field_conflict"])
def test_actual_c_receiver_accepts_all_protocol_branches(kind):
    from examples.check_b_protocol_variants import case
    raw, sources, payload, consumed = case(kind)
    assert payload["data_kind"] == "synthetic_protocol_test"
    if kind == "unknown":
        assert all(x["support"] == "unknown" for x in payload["source_reviews"])
    elif kind == "unsupported":
        assert any(x["support"] == "unsupported" for x in payload["source_reviews"])
    elif kind.endswith("conflict"):
        assert payload["verification"]["status"] == "conflict"
    elif kind == "not_applicable":
        assert payload["verification"]["not_applicable_fields"]["track"]
