"""Synthetic protocol branch tests against C's actual receiver; no real facts."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from b_app.b_io import competition_from_dict
from b_app.evidence_verifier import verify_competition
from b_app.field_catalog import FIELD_SPECS, NOT_APPLICABLE_STATEMENTS
from b_app.frozen import load_policy
from b_app.query_planner import plan_queries
from b_app.return_contract import build_return, validate_return
from b_app.source_review import ApprovedSource, SourceSnapshot, review_competition
from competition_radar.b_handoff import BContest
from competition_radar.b_return import consume_b_return
from competition_radar.schemas import SourceDocument


def case(kind):
    policy = load_policy()
    raw = {"id": "synthetic-" + kind, "name": "虚构接口测试赛", "edition": "2026", "scope": "global",
           "field_scopes": {}, "fields": {f: {"value": None, "evidence": []} for f in policy.required_fields}}
    sources, approvals = [], []

    def add(field, value, quote, value_kind="value"):
        number = len(sources)
        url, sid = f"https://fixture.example.invalid/{number}", f"fixture-{number}"
        eid = f"{field}-{number}"
        sources.append({"source_id": sid, "url": url, "title": "虚构接口测试",
                        "content": quote, "fetched_at": "2026-10-28T00:00:00+00:00", "published_date": None})
        evidence = {"id": eid, "value": value, "url": url, "quote": quote, "edition": "2026",
                    "scope": "global", "value_kind": value_kind, "source_id": sid}
        raw["fields"][field]["evidence"].append(evidence)
        if value_kind == "value":
            raw["fields"][field]["value"] = value
        approvals.append(ApprovedSource(raw["id"], "2026", "global", url, "official", "B:synthetic-fixture"))

    if kind in ("verified", "unknown", "unsupported", "conflict"):
        add("eligibility", "任何人均可参赛。" if kind == "unsupported" else "全国高校在读本科生。",
            "参赛资格：全国高校在读本科生。")
        if kind == "unknown":
            approvals.clear()
        if kind == "conflict":
            add("eligibility", "仅限研究生。", "参赛资格：仅限研究生。")
    elif kind == "not_applicable":
        statement = NOT_APPLICABLE_STATEMENTS["track"][0]
        add("track", statement, FIELD_SPECS["track"].labels[0] + "：" + statement, "not_applicable")
    elif kind == "cross_field_conflict":
        for f, v in (("registration_start", "2026-12-01"), ("registration_deadline", "2026-11-01")):
            add(f, v, FIELD_SPECS[f].labels[0] + "：" + v)
    else:
        raise ValueError(kind)
    comp = competition_from_dict(raw)
    reviewed, notes = review_competition(comp, approved_sources=approvals,
                                       snapshots=[SourceSnapshot(s["url"], s["content"], s["fetched_at"], s["source_id"]) for s in sources])
    verification = verify_competition(reviewed, policy)
    payload = build_return(reviewed, verification, notes, plan_queries(reviewed, verification),
                           data_kind="synthetic_protocol_test", notice="虚构协议测试，不是真实赛事裁决。")
    validate_return(payload, raw)
    consumed = consume_b_return(payload, BContest.model_validate(raw),
                                [SourceDocument.model_validate(s) for s in sources], required_fields=policy.required_fields)
    return raw, sources, payload, consumed


def run(output_dir=None):
    out = Path(output_dir) if output_dir else ROOT / "outputs/b_protocol_variants"
    out.mkdir(parents=True, exist_ok=True)
    receipts = []
    for kind in ("verified", "unknown", "unsupported", "conflict", "not_applicable", "cross_field_conflict"):
        raw, sources, payload, consumed = case(kind)
        (out / (kind + ".json")).write_text(json.dumps({"candidate": raw, "sources": sources, "b_return": payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append({"case": kind, "c_actual_consumer_accepted": True,
                         "verified_fields": consumed.verified_values, "status": payload["verification"]["status"]})
    report = {"data_kind": "synthetic_protocol_test", "c_actual_consumer_executed": True, "receipts": receipts}
    (out / "receipts.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(), ensure_ascii=False, indent=2))
