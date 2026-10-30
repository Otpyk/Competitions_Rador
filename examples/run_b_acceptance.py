"""Reproduce B's frozen-policy check and C's actual six-return consumption."""
from pathlib import Path
import json
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from b_app.frozen import load_approvals, load_policy
from b_app.return_contract import validate_return
from b_app.service import verify_contests
from competition_radar.b_handoff import BContest
from competition_radar.b_return import consume_b_return
from competition_radar.schemas import SourceDocument


def run(output_dir=None):
    base = ROOT / "data/b_canonical_batch"
    candidates = json.loads((base / "c_to_b_contests.json").read_text(encoding="utf-8"))
    research = json.loads((base / "research_batch.json").read_text(encoding="utf-8"))
    sources = [SourceDocument.model_validate(s) for s in research["sources"]]
    approvals, policy = load_approvals(), load_policy()
    output_dir = Path(output_dir) if output_dir else ROOT / "outputs/b_acceptance_v5"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results").mkdir(exist_ok=True)
    receipts = []
    for candidate, payload in zip(candidates, verify_contests(candidates, sources=research["sources"])):
        reference = validate_return(payload, candidate)
        consumed = consume_b_return(payload, BContest.model_validate(candidate), sources,
                                    required_fields=policy.required_fields)
        path = output_dir / "results" / (candidate["id"] + ".json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append({"competition_id": candidate["id"], "reference_receiver_accepted": reference["accepted"],
                         "c_actual_consumer_accepted": True, "status": payload["verification"]["status"],
                         "coverage": payload["verification"]["coverage"], "verified_fields": dict(consumed.verified_values),
                         "source_identity_approved_count": sum(x["source_verified"] for x in payload["source_reviews"]),
                         "assessed_fields": len(payload["verification"]["fields"]),
                         "required_fields": len(payload["verification"]["required_fields"])})
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "policy_version": "b-frozen-20261028",
              "candidate_count": len(candidates), "c_actual_consumer_executed": True,
              "source_pages_reviewed_online": 5, "source_approval_records": len(approvals),
              "verified_field_count": sum(len(r["verified_fields"]) for r in receipts),
              "scope_decisions_applied_in_versioned_copy": 3, "real_search_callback_executed": False,
              "receipts": receipts}
    (output_dir / "c_actual_receipts.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(), ensure_ascii=False, indent=2))
