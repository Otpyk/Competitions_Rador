# A 交付包与 C v0.1 的对齐

依据当前 `Competition_Radar_A/` 与用户已确认的 C 协议。2026-10-22 用户进一步确认：网页正文快照及元数据由 A 补交，C 不新增网页抓取。

## 本轮调整

| A 原有接口／行为 | 当前对齐方式 |
| --- | --- |
| 来源仅有 title、url、snippet | A 的 Source 可携带 source_id、content、fetched_at、published_date；研究引擎显式返回这些字段时予以保留，缺少时不编造 |
| 报告和摘要可直接交给抽取器 | C 适配器只消费完整来源快照，report 与 snippet 保留在 A 历史中，不能替代原始正文 |
| A 端到端任务另建 ID | 沿用初始研究 task_id，补搜贯穿同一任务 |
| 补搜替换上一轮赛事列表 | 保存每次研究结果并累积来源和原始候选；同 ID 同内容复用，同 ID 内容变化报错，要求新 ID |
| verifier 与 planner 必须同时存在才核验 | B 核验可独立运行，缺规划器时仅使用当前资料 |
| 最后一次补搜后可能直接退出 | 最终候选重新交 B 核验后才能排序；达到预算也不跳过这次核验 |
| rank 只接收赛事与画像 | 直接调用 C `recommend`，传入来源、逐字段裁决、任务与明确判断时刻 |

本轮没有实现实际抽取器或 B 模块，也没有修改原始 mock 来源使其看起来具备真实证据。

## A → C 来源快照

C 的 `research_batch_from_a(result)` 接受 A 成功研究结果的 JSON 对象，输出 `ResearchBatch`。每个来源必须显式具备：

```json
{
  "source_id": "synthetic-snapshot-001",
  "url": "https://example.invalid/notice",
  "title": "合成通知标题",
  "content": "这里必须是对应来源的原始可用正文。此段仅为接口示例。",
  "fetched_at": "2026-10-22T11:00:00+08:00",
  "published_date": null
}
```

这不是实际网页快照。A 应记录实际获取时刻，不用请求结束时刻冒充抓取时刻。新抓取形成新快照 ID；同一 URL 可对应多个不同快照。title 未取得时，C 协议允许显式 null。published_date 只有能确认完整日期时才填写。

A 的 Source 仍允许旧研究接口只返回标题、链接和摘要；这些来源可以展示，但不能通过 C 的正文证据输入校验。原 `Competition_Radar_A/examples/research_result_sample.json` 正是这种情况，保留原样作为缺口检查用例。

## 接缝签名

抽取器待实现。A 在模块存在时调用以下 v0.1 签名：

```python
# extractor.py，C 后续提供；本轮没有该模块
def extract_competitions(batch: dict) -> list[dict]:
    # 输入 ResearchBatch JSON；输出 CandidateContest JSON 数组
    ...

# evidence_verifier.py，B 提供
def verify(competitions: list[dict], *, sources: list[dict]) -> list[dict]:
    # 归并后候选 + SourceDocument JSON 数组 → VerificationResult JSON 数组
    ...

# query_planner.py，B 提供；缺少时只核验，不执行补搜
def plan_queries(
    verification: list[dict], *, competitions: list[dict],
    sources: list[dict], research_history: list[dict],
) -> list[dict]:
    # 返回 SupplementarySearchRequest JSON 数组；空数组表示不补搜
    ...
```

上面只说明外部待提供的函数，不是已实现代码。候选结构见 `C_CONTRACT_DRAFT.md` 和合成输入。B 对每个赛事恰好给出一份包含 11 个字段裁决的结果，不能只返回整体“已验证”。A 给 B 全部当前来源，以便裁决跨轮累积的候选。查询规划同时收到赛事候选、快照和研究历史，能取得名称、届次、候选值及此前查询与失败信息，无需依赖 B 私有状态。查询规划中的 task_id 和 round 由 A 统一设置；max_rounds 表示最多补搜轮数，不含初始研究，每轮可有多个查询。

推荐函数已经实现，不再等待顶层 `ranker.rank`：

```python
competition_radar.recommend(
    task_id, profile, sources, merged_candidates, verifications, as_of,
)
```

A 在排序时记录一次带偏移的当前时刻并传给 C。测试可向 `run_pipeline(req, as_of=...)` 注入固定时刻。C 不读取当前时间。

## 画像和旧字段的差异

进入推荐阶段的 profile 必须包含全部七个键，例如：

```json
{
  "education_level": "本科",
  "major": "计算机科学与技术",
  "grade": 3,
  "team_size": null,
  "interests": ["人工智能"],
  "deadline_from": null,
  "deadline_to": null
}
```

专业和学历标签需上游对齐。旧画像的“计算机”“大三”不会由 C 猜测转换。缺少信息使用 null；兴趣列表需明确传入，不把缺省当作无偏好。

A 原说明中的 category、资格字符串、team_size 字符串与笼统 verification_status 不直接映射成已核验字段。C 使用 tags、EligibilityRules、带精度的 RegistrationTime 与逐字段 FieldDecision，既保留候选也保留 B 选中的依据。

## D 应读取的结果与状态

- `research`：初始研究结果，保留原接口。
- `research_history`：初始与历次补搜结果，包括失败或超时，供回溯原报告、来源和日志。
- `competitions`：累积、校验、归并后的候选；存在候选不表示已经核验。
- `recommendations`：C 的 `RecommendationResponse`，含 recommended、pending、excluded 三组；没有有效最终裁决或画像不合法时为 null。
- `stages`：逐阶段状态与问题。not_integrated 表示模块尚未提供，blocked 表示输入或前置条件不满足，failed 表示执行异常。顶层 completed 只表示编排返回，不能用来宣称已经推荐成功。

补搜失败仍保留历史，并可对已有有效资料重新核验和推荐；如果新资料的输入、引用或裁决不合法，则阻断推荐并展示问题。

## 本地复核

在项目根目录先运行 C 的规则检查，再进入 A 目录运行研究接口和编排检查：

```bash
uv run --locked pytest -q
cd Competition_Radar_A
uv run --project .. --locked --group integration python -m pytest -q
```

A 的测试配置禁用 .env 文件读取，强制 mock；新增集成用例使用显式合成正文、测试抽取器与测试 B 裁决。它们检验接缝和多轮流程，不证明真实 GPT Researcher 能提供所需快照，也不证明实际抽取或核验正确。

待 A 补交真实正文样例、C 确认并实现抽取器、B 提供实际模块后，才能进行真实端到端验收。
