"""完整链路冒烟：A 编排 + 抽取 + B 适配核验/补搜 + C 推荐。"""
import asyncio
import json
import os
import sys

os.environ["RESEARCHER_MODE"] = "fixture"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path.insert(0, r"C:\X\黑客松")

import config  # noqa: E402
config.Settings.model_config["env_file"] = None
config.get_settings.cache_clear()

from api_models import SearchRequest  # noqa: E402
import main  # noqa: E402


async def run():
    profile = {
        "education_level": "本科", "major": "数学", "grade": 2, "team_size": 3,
        "interests": ["数学建模"], "deadline_from": None, "deadline_to": None,
    }
    resp = await main.run_pipeline(SearchRequest(query="全国大学生学科竞赛 2026", profile=profile, max_rounds=1))
    data = resp.model_dump(mode="json")
    print("task_id:", data["task_id"], "status:", data["status"])
    print("engine:", data["research"]["engine"], "sources:", len(data["research"]["sources"]))
    print("stages:", [(s["name"], s["status"]) for s in data["stages"]])
    print("history rounds:", [h["round"] for h in data["research_history"]], "len:", len(data["research_history"]))
    print("candidates:", len(data["competitions"]))
    for c in data["competitions"]:
        print("  -", c["record_id"], len(c["claims"]), "claims")
    rec = data["recommendations"]
    if rec:
        print("recommendations as_of:", rec["as_of"])
        print("  recommended:", len(rec["recommended"]), "pending:", len(rec["pending"]), "excluded:", len(rec["excluded"]))
        for item in rec["pending"]:
            fields = {f["field"]: f["status"] for f in item["fields"]}
            print("   pending item:", item["record_id"], "elig:", item["eligibility_status"], "reg:", item["registration_status"], "ver:", item["verification_status"])
    else:
        print("recommendations: null")
    # 补搜日志
    stage = next(s for s in data["stages"] if s["name"] == "verify_and_supplement")
    logs = stage.get("detail") or []
    events = [e for e in logs if e.get("event") in ("supplemented", "supplementary_limit_reached", "no_more_queries", "verified")]
    for e in events:
        print("   loop:", {k: (str(v)[:60] if isinstance(v, str) else v) for k, v in e.items() if k in ("event", "round", "status", "error", "candidate_count", "source_count", "completed_rounds")})


asyncio.run(run())
