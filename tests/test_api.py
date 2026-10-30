"""后端 API 的最小接口测试（通过 TestClient，使用 mock 引擎）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["engine"] == "mock"


def test_research_endpoint() -> None:
    r = client.post("/api/v1/research", json={"query": "大学生 人工智能 竞赛"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["sources"]
    assert data["task_id"]
    assert data["error"] is None


def test_supplementary_endpoint() -> None:
    payload = {
        "action": "search",
        "task_id": "task-123",
        "contest_name": "某项竞赛",
        "target_fields": ["registration_deadline"],
        "query": "某项竞赛 官方 报名截止时间",
        "reason": "报名截止日期缺失",
        "round": 2,
    }
    r = client.post("/api/v1/research/supplementary", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["round"] == 2


def test_research_rejects_empty_query() -> None:
    r = client.post("/api/v1/research", json={"query": ""})
    assert r.status_code == 422


def test_search_endpoint_pipeline() -> None:
    r = client.post("/api/v1/search", json={"query": "数学建模竞赛"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["research"]["status"] == "success"
    # 跨轮历史保留初始研究结果
    assert data["research_history"] and len(data["research_history"]) == 1
    stage_names = [s["name"] for s in data["stages"]]
    assert "research" in stage_names
    # mock 引擎只产生摘要级来源（无六键正文），证据契约会如实阻断抽取阶段，
    # 而不是伪装成已抽取/已核验。
    extract = next(s for s in data["stages"] if s["name"] == "extract")
    assert extract["status"] == "blocked"
    assert extract["detail"] and extract["detail"].get("issues")
    assert data["recommendations"] is None
