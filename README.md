# Competition Radar 大学生竞赛雷达

> 面向大学生的竞赛搜索与个性化推荐智能体 —— 输入画像，自动搜索并核验官方竞赛信息，给出「可报名 / 待确认 / 已排除」的诚实推荐。

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-green)
![Streamlit](https://img.shields.io/badge/Streamlit-frontend-red)
![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-orange)
![Bocha](https://img.shields.io/badge/Search-Bocha-purple)

## 项目简介

Competition Radar（竞赛雷达）是一个帮助大学生**发现、核验、筛选竞赛**的智能体。用户输入自己的专业、年级、兴趣和团队情况，系统会：

1. **联网搜索**官方竞赛通知（Bocha 搜索 + 抓正文）；
2. **抽取**结构化竞赛信息（DeepSeek 国产大模型）；
3. **核验**关键字段的证据（保守规则，逐字原文 + 官方来源）；
4. **补充搜索**缺失的关键字段（截止日期、资格等，缺失即追问）；
5. **过滤与排序**：排除外校校赛、资格不符、已截止的赛事，按兴趣命中与截止日期排序；
6. **诚实展示**：查不到就标「待确认」，绝不编造日期或资格。

核心原则：**信息有证据、资格能筛选、缺失会追问、效果可评测、不确定不编造。**

## 功能特性

- 🔍 即时联网搜索：Bocha（国产）+ Tavily + DuckDuckGo 多后端，抓取正文并生成六键来源快照
- 🤖 国产大模型抽取：DeepSeek（也可换 Qwen / GLM / Kimi 等 OpenAI 兼容端点）
- 🛡 证据感知核验：31 字段保守核验 + 来源审批 + 逐字引文检查 + 跨字段矛盾检测
- 🔁 自适应补充搜索：缺失字段定向补查，带轮次/次数/费用预算与停止条件
- 🏫 学校过滤：自动排除外校校赛（如「campus:其他学校」的校内通知）
- 📊 71 个学院推荐竞赛库（华南师范大学人工智能学院推荐名单，A/B/C/D 四类）
- 🖥 三入口：`/api/v1/library/recommend`、`/api/v1/search`、`/api/v1/search/full`

## 系统架构

```
┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐
│  用户画像    │──▶│  A 研究服务    │──▶│  C 抽取     │──▶│  B 证据核验   │──▶│  C 推荐/排序  │──▶ D 前端
│ 专业/年级/   │   │ 联网搜索+抓取 │   │ DeepSeek 31  │   │ 保守规则+审批 │   │ 资格/截止/兴趣│   │ Streamlit
│ 兴趣/团队    │   │ (Bocha)      │   │ 字段+逐字引用 │   │ +补搜规划     │   │ +三组分组     │
└─────────────┘   └──────────────┘   └─────────────┘   └──────────────┘   └─────────────┘
```

| 角色 | 职责 | 模块 |
|---|---|---|
| A | 系统负责人 / 研究服务 / 编排 | `main.py` `research_service.py` `web_search.py` |
| B | 证据核验 / 自适应搜索 | `src/b_app/`（`service.py` `source_review.py` `adaptive_search.py`） |
| C | 数据模型 / 抽取 / 推荐 | `src/competition_radar/`（`schemas.py` `extraction.py` `b_recommend.py`） |
| D | 前端 / 展示 | `ui.py`（Streamlit） |

## 快速开始

```powershell
# 1) 依赖（Python 3.12+）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -e .
pip install -r requirements-frontend.txt

# 2) 配置密钥（复制 .env.example 为 .env，填入 DeepSeek / Bocha key）
Copy-Item .env.example .env

# 3) 直接运行（无需记命令）
python main.py     # 后端 → http://127.0.0.1:8000/docs
python ui.py       # 前端 → http://localhost:8501
```

## 接口

| 接口 | 说明 |
|---|---|
| `POST /api/v1/library/recommend` | 71 个学院推荐竞赛按兴趣匹配 + 联网补详情 + 过滤外校校赛 |
| `POST /api/v1/search` | 11 字段证据链路（研究→抽取→核验→补搜→推荐） |
| `POST /api/v1/search/full` | 31 字段全链路（联网搜索→DeepSeek 抽取→核验→补全推荐） |

## 目录结构

```
main.py / research_service.py / api_models.py / config.py   # A：入口、研究服务、配置
extractor.py / domestic_extract.py / web_search.py          # 抽取（规则+DeepSeek）+ 联网搜索
evidence_verifier.py / query_planner.py                     # B 适配层
library_recommend.py / recommend_full.py / full_chain.py    # 库推荐 + 补全 + 全链路
ui.py                                                       # D 前端
data/    competition_library.json（71竞赛）· approved_sources · b_policy · b_canonical_batch
src/competition_radar/   # C：模型规则 + deepseek + extraction + b_recommend/b_return
src/b_app/               # B：核验/规划/自适应搜索 + frozen + service
examples/  tests/  b_tests/  docs/
```

## 测试

```powershell
python -m pytest -q                            # 74 项（A/C 集成 + 全链路 + 库 + 学校过滤）
python -m unittest discover -s b_tests -q     # B 269 项
```

## 技术栈

- **后端**：FastAPI + Uvicorn + Pydantic v2
- **前端**：Streamlit
- **大模型**：DeepSeek（`deepseek-flash`，OpenAI 兼容，可换 Qwen/GLM/Kimi）
- **搜索**：Bocha（国产）/ Tavily / DuckDuckGo
- **测试**：pytest + unittest

## 诚实边界（设计原则）

- 学校转载页（`school` 来源）不能独立证明**全国**资格/截止，系统会如实保持「待确认」，不猜测日期、不编造资格。
- 联网抓取的来源经**域名过滤**（`.edu.cn/.gov.cn/.org.cn` 优先、跳过博客论坛）+ **学校过滤**（排除外校校赛）双重把关，并标「待B核验」。
- 要得到「已核验可报名」正例，需官方（全国）章程/通知经审批为 `official` 来源。

## License

待定（请作者补充开源协议）。
