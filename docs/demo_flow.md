# 端到端演示流程（A 视角）

本文件说明如何用最小步骤跑通「输入需求 → 研究 → 返回报告与来源」的链路，
并演示 A 负责的补充搜索执行。全程使用 `mock` 引擎，无需外部 API。

## 0. 前置

```bash
# 在项目根目录执行
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q          # 预期全部通过
```

## 1. 启动服务

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 即成功。

## 2. 健康检查

```bash
curl http://127.0.0.1:8000/health
```

预期：`{"status":"ok","engine":"mock","version":"0.1.0"}`。

## 3. 一次初始研究（正常案例）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/research `
  -H "Content-Type: application/json" `
  -d '{\"query\":\"大学生 人工智能 创新竞赛 官方报名\"}'
```

预期返回 `status: "success"`，`report` 有正文，`sources` 至少一条，`error: null`。

## 4. 补充搜索（B 决策 → A 执行）

模拟 B 发现「报名截止日期缺失」后发出的补充查询：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/research/supplementary `
  -H "Content-Type: application/json" `
  -d '{\"action\":\"search\",\"task_id\":\"task-123\",\"contest_name\":\"某项竞赛\",\"target_fields\":[\"registration_deadline\"],\"query\":\"某项竞赛 官方 报名截止时间\",\"reason\":\"报名截止日期缺失\",\"round\":2}'
```

预期返回与初始搜索同构的结果，且 `round: 2`。

## 5. 端到端链路

```bash
curl -X POST http://127.0.0.1:8000/api/v1/search `
  -H "Content-Type: application/json" `
  -d '{\"query\":\"数学建模竞赛\",\"profile\":{\"major\":\"数学\"}}'
```

预期：`status: "completed"`，`stages` 中 `research` 为 `success`，其余阶段为
`not_integrated`（待 B/C 模块接入后自动变为 `ran`）。

## 6. 失败路径演示

把 `RESEARCHER_MODE` 改为 `gpt_researcher` 但**不安装** `gpt-researcher`，重启后调用
`/api/v1/research`，观察返回 `status: "failed"` 与明确的 `error` 提示，而不是伪装成功。

（或在代码里用一个抛异常的引擎替换 `MockEngine`，运行 `tests/test_research_service.py`
的 `test_failure_returns_failed_not_fake_success` 观察结构化失败。）

## 7. 离线样例交接

C 可直接读取 `examples/research_result_sample.json` 作为固定输入，独立联调抽取模块，
无需启动服务或访问外部网络。
