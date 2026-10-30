# 肇庆学院蓝桥杯院赛选拔交接样本

本样本来自 A 已提供的真实批次，由 C 于 2026-10-22 离线手工整理。没有调用模型、联网重新抓取或代替 B 批准来源。结构和逐字证据校验通过不等于信息已核验、报名仍开放或个人符合资格。

## 目标、届次和学院范围

- 记录 ID 为 `curated-zqu-lanqiao-18-college-selection`，source_id 为 `real-lanqiao-zqu-2026-1013`。
- 标题明确“第十八届”，因此 edition 及 `competition_edition` 取“第十八届”。没有将快照发布日期 2026-10-13、截止日期年份或 source_id 自动改成赛事年度；赛事年度未知。
- 目标阶段是肇庆学院电子与电气工程学院报名、院赛选拔并择优推荐省赛。不能把本记录视为全国赛、省赛的完整规则。
- `scope` 为 `campus:肇庆学院`。现有 BScope 只表示学校，不能精确编码二级学院；本条规则只覆盖**电子与电气工程学院**，不覆盖肇庆学院所有学生或其他学院。这个学院限制完整保留在 `eligibility` 和本说明中，下游必须连同本说明保留。学院范围能力尚未冻结，B 如需结构化二级学院，应先对齐协议，不可静默扩大适用人群。
- `competition_name`、`competition_edition` 和正文给出的全国通知链接是 global 候选字段；未知的全国 `registration_deadline` 也明确指向 global，其余字段按本学院通知范围处理。global 不代表来源已经获准用于全国核验。
- 没有选定赛道或组别。联系方式要求备注“参赛项目”没有列出可选项目，不能从学院名称推断电子类、软件类或具体赛道。

## 日期与阶段取舍

| 字段 | 候选值 | 理由 |
| --- | --- | --- |
| `registration_start` | `null` | 原文为“即日起”，相对日期缺少独立明确起日。保留完整日期句作为疑难证据，不从 published_date 或 fetched_at 推算 |
| `registration_deadline` | `null` | B 定义为赛事层面截止；学院报名日期不能用作全国截止，没有复制校内日期 |
| `campus_deadline` | `2026-11-16` | 本通知报名截止完整到日；保留“逾期不接受报名”，不增补时刻或时区。范围仅为本学院报名选拔 |
| `submission_deadline` | `null` | 未取得作品提交截止；没有把报名截止当作作品截止 |

赛程原文同时包含“报名截止后”“具体时间另行通知”和“预计11月中”。完整句已保留在 `schedule`、学校手续与评分标准的疑难证据中；不将预计日期标准化，不推定院赛具体日期，也不自行消解它与 11 月 16 日报名截止之间的先后疑问。B 可以据原句判断是否需要澄清或进一步抓取。

## 字段证据与未知项

- `eligibility` 保留“电子与电气工程学院在读大二、大三学生且未参加过往届比赛”的整句，不能缩为“在校大学生”，也不丢掉往届参赛经历限制。原文没有明确学历、跨校、专业、团队和导师条件，均不据常识补齐。
- `official_url` 使用正文明确给出的 `https://dasai.lanqiao.cn/notices/3002`，这是通知链接候选，不是报名入口。该目标网页未在本批次内独立抓取；本条证据定位仍是 A 的肇庆学院快照，不伪造该全国 URL 的正文或来源批准。
- `registration_method` 保留“竞赛QQ群，进群填写在线报名文档，切勿在官方网站直接报名”整句。`registration_url` 留空并保留该句，不能把赛事官方网站当报名链接，也不能因无链接就断言全国没有公开报名入口。QQ群号码未出现在快照正文。
- `registration_materials` 留空，保留进群填写在线报名文档及备注姓名、班级、参赛项目的两句。这里只知道报名动作和进群备注，未取得报名文档内容或完整材料清单。
- `institutional_requirements` 只记录学院统一安排院赛、择优推荐省赛的原句；不推断导师确认、签字盖章、推荐名额或其他手续不存在。
- `schedule` 保留上述完整院赛选拔句。`judging_criteria` 留空并附该句，“择优”不足以构成评分维度或权重。
- `contacts` 只保存原文交流方式和进群备注要求；没有生成QQ群号码、二维码、姓名、电话或咨询网址。
- `organizer` 留空，学院安排院赛不等于它是全国赛主办方。个人或团队参赛形式、组队规则、实际任务、最终成果、线上线下、地点、报名费、后续必缴费、奖项、校内认可、设备要求、作品使用规则、准备资源及详细投入未取得，继续保持 null。未提及没有被改写为免费、无要求、允许已有作品、无需到场或明确不适用。
- 全部 31 字段显式存在；所有 evidence.value_kind 都为 `value`。无来源批准标记，无 B 裁决，无自动推荐结论。

## 来源与逐字定位

A 路径为 `Competition_Radar_A/examples/research_result_real_batch.json`，以 source_id 定位，不依赖数组位置。

- URL：`https://eee.zqu.edu.cn/info/1186/43132.htm`
- A 抓取时间：`2026-10-22T15:19:50+08:00`
- A 发布日期：`2026-10-13`
- source.content UTF-8 SHA-256：`2cf2c7c401637f59b69131f1f1111f083c4c58710e0a6ab63c79c7e42c2635e4`

下表偏移按 Python 字符串字符索引，起点包含、终点不包含。原始 A 快照是唯一逐字校验依据。字段重复引用同一原句时各保留独立 evidence_id。

| Evidence ID | 字段 | 起点 | 终点 |
| --- | --- | --- | --- |
| `zqu-18-competition_name-1` | `competition_name` | 0 | 28 |
| `zqu-18-competition_edition-1` | `competition_edition` | 0 | 28 |
| `zqu-18-official_url-1` | `official_url` | 30 | 74 |
| `zqu-18-eligibility-1` | `eligibility` | 76 | 112 |
| `zqu-18-registration_start-1` | `registration_start` | 114 | 143 |
| `zqu-18-campus_deadline-1` | `campus_deadline` | 114 | 143 |
| `zqu-18-registration_method-1` | `registration_method` | 145 | 179 |
| `zqu-18-registration_url-1` | `registration_url` | 145 | 179 |
| `zqu-18-registration_materials-1` | `registration_materials` | 145 | 179 |
| `zqu-18-registration_materials-2` | `registration_materials` | 229 | 258 |
| `zqu-18-institutional_requirements-1` | `institutional_requirements` | 181 | 227 |
| `zqu-18-schedule-1` | `schedule` | 181 | 227 |
| `zqu-18-judging_criteria-1` | `judging_criteria` | 181 | 227 |
| `zqu-18-contacts-1` | `contacts` | 229 | 258 |

## A 快照完整正文

原始正文无末尾换行；下方围栏关闭前的排版换行不属于原始 content。

```text
关于举办第十八届蓝桥杯全国大学生软件和信息技术大赛的通知

赛事官方网站：https://dasai.lanqiao.cn/notices/3002

报名对象：电子与电气工程学院在读大二、大三学生且未参加过往届比赛的同学。

报名时间：即日起至2026年11月16日（逾期不接受报名）

报名形式：竞赛QQ群，进群填写在线报名文档，切勿在官方网站直接报名。

竞赛形式：报名截止后，学院统一安排院赛（具体时间另行通知，预计11月中），择优推荐参加省赛。

联系方式：竞赛报名QQ群，进群备注（姓名、班级、参赛项目）
```
