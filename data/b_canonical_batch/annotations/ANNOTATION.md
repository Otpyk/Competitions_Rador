# 川大产业赛道交接样本标注说明

本文件与 `curated_scu_industry.json` 是依据 A 已交付快照手工整理的字段交接材料，日期为 2026-10-22。没有运行正文抽取器、研究服务或模型 API，没有联网重新抓取或批准页面。候选值、原文定位和结构检查不构成 B 的核验结论，也不代表可以报名或符合个人资格。

## 目标与范围 sidecar

以下上下文单独保存，不能当作 B v3 顶层新增字段发送。

```json
{
  "record_id": "curated-scu-icnc-2026-industry-enterprise",
  "competition_name": "中国国际大学生创新大赛（2026）",
  "competition_edition": "2026",
  "parent_track_in_body": "产业赛道",
  "parent_track_in_title": "产业命题赛道",
  "target_group": "企业命题组",
  "campus": "四川大学",
  "target_stage": "四川大学校赛产业赛道补报名及校内推荐",
  "global_date_stage": "全国大学生创业服务网产业赛道报名系统开放期",
  "campus_date_stage": "四川大学纸质报名表提交、校赛系统报名与学院审核",
  "source_id": "real-icnc-scu-2026-0828",
  "annotation_method": "manual_from_A_snapshot",
  "verification": "not_performed"
}
```

`track.value` 只取原文字面“企业命题组”。标题的“产业命题赛道”和正文的“产业赛道”分别保留在本 sidecar，没有自动将名称合成为一个官方赛道名。全国日期与校内日期属于两个报名环节；校内评审后择优推荐参加省赛，不能把这条通知当作全国全阶段规则。

顶层 `scope` 为 `global`，具体校内字段通过 `field_scopes` 指向 `campus:四川大学`，包括 `school_recognition` 的缺失目标。字段中每条证据的 scope 均与其字段目标一致。全国网报事实来自这份学校通知，是等待 B 审查的候选；不能因候选 scope 为 global 就把学校通知当成已获全国批准的官方来源。学校规则不能自动推广到其他高校。

## 日期与阶段

| 字段 | 本样本值 | 原文范围与限制 |
| --- | --- | --- |
| `registration_start` | `2026-08-27` | 全国系统原句“产业赛道报名系统开放起止时间为北京时间2026年8月27日—9月25日。”，同一句完整区间明确年份；按日精度保留 |
| `registration_deadline` | `2026-09-25` | 同一全国系统区间的终点；没有写截止时分，不补 23:59:59；“北京时间”原样保留在证据中 |
| `campus_deadline` | `null` | 纸件提交、校赛系统报名、学院审核均写 9 月 2 日 12:00 左右，完整相关句没有明确年份；分别保留四条原文证据，不从标题或发布日期补 2026 |
| `submission_deadline` | `null` | 没有可确认的作品提交截止；全国平台和校内报名环节中出现 PPT，不能据此把报名截止复制为作品截止 |

本包使用 B v3 日期字符串，未扩展字段为 C v0.1 的 `RegistrationTime` 对象。全国日期的时区线索保留在原文中，没有增加模型外的 time/timezone 键。未来若映射回 v0.1，需保留日精度，并单独处理时区证据。校内时间原文同时存在全角“12：00”和半角“12:00”，quote 均原样保存，没有统一标点。

## 字段取舍和待确认原文

- `competition_name` 与 `competition_edition` 来自完整通知标题。顶层 name 用于寻找赛事，不能替代 `fields.competition_name` 的证据。
- `official_url` 是 A 快照的具体四川大学通知地址，范围为 `campus:四川大学`。quote 保留通知完整标题；该 URL 来自快照元数据，未出现在正文里。这不能满足要求 URL 必须字面出现在正文中的核验规则，需交 B 审查，不能改写正文补上“官方通知链接”标签，也不能把这条校内通知当作全国官方章程。
- `organizer` 留空。文末“教务处”只作为原文署名保存，没有据此填写全国主办方。通知引用的附件和上级文件正文未交付，不能凭文件名称补齐主办单位或全国资格。
- `eligibility` 保留“一、报名安排”与“二、报名须知”的完整连续原文，以免漏掉后续的审核、项目唯一性、转报及成员限制。这里包含已知的报名条件，但没有宣布资格已经完整；学历、学籍范围、年级、专业、团队人数上下限和跨校规则仍未从此来源取得。没有将“师生团队”自动改成允许所有学历、允许跨校或允许导师作为学生成员。
- `team_rules` 保留完整原段，包括每人同赛道最多 2 项、每项指导教师原则上不超过 3 名、每位教师指导当年项目仅限 1 项及括号中的主赛道国际项目例外。“原则上”没有删掉，也没有把教师人数当作参赛队伍人数。其他资格段仍保留在 `eligibility` 中。
- 原文同段同时介绍企业命题组和成果转化组，相关 quote 保留整段。本记录只选择企业命题组，不把“成果转化组不需要对接命题”套用到本组，也不从“需要对接企业命题”推断具体企业题目或比赛任务。
- `task_description`、`deliverables` 只保留相关报名段的证据，主值仍为 null。PPT 是原文明示的网上报名材料，实际任务、完整作品要求及附件 1 的企业命题正文没有取得；没有把报名材料推断成最终作品清单。
- `registration_materials` 与 `institutional_requirements` 保留完整连续段，包含签字盖章、扫描留存、纸件、全国网报成功截图、PPT、顺序一致、学院审核推荐、报名后原则上不能更改等条件。`registration_method` 保留整个“一、报名安排”，避免只记全国平台漏掉校内手续。校内系统没有可用 URL，不凭系统名称生成链接；`registration_url` 只填原文明示的大创网 URL。
- `attendance_mode` 和 `schedule` 只记录四川大学校内“网络评审和现场答辩评审，择优推荐项目参加省赛”的完整段。它没有说明决赛城市、所有晋级阶段都必须到场、具体现场安排或全国全程线上；`venue` 保持 null。
- `judging_criteria` 的主值为 null，证据保存上述评审段。这里只取得评审形式和晋级方向，没有评分维度或权重，不能写成完整评分标准。
- `awards` 仅保留校内“不再授予校级奖励。”，不能据此断言全国没有奖励或本校不认可。`school_recognition` 指向四川大学但保持 null，没有填综测、学分或保研待遇。
- `work_rules` 只记录校内转报、再次报名时更新项目名称的完整段，没有由此推断允许重复投稿、允许已有作品、开源或 AI 使用规则。
- `contacts` 保存完整校内交流渠道段，没有用系统技术联系人替代全国竞赛咨询人。`preparation_resources` 未因“附件/指南”名称出现就补造下载地址或培训资料。
- 报名费、其他必缴费用、预算、技术设备等未提及的字段保持 null；没有把未提及写成免费、无要求或不适用。本样本没有任何 `value_kind: not_applicable`。

## 未知、证据与 B 的后续边界

完全缺值且无相关证据的字段为 `organizer`、`submission_deadline`、`venue`、`registration_fee`、`mandatory_fees`、`school_recognition`、`technical_requirements`、`preparation_resources`、`expense_details`。

保留疑难证据但主值为 null 的字段为 `campus_deadline`、`task_description`、`deliverables`、`judging_criteria`。证据 value 保存完整相关原文，不将不完整日期字符串当成通过核验的日期。

全部 31 个字段显式存在。每条 evidence 使用 B v3 规定的 `id`、`value`、`url`、`quote`、`edition`、`scope`、`value_kind`，并附内部 `source_id` 定位到 A 快照。对外导出给 B 时由交接代码剥离 `source_id`；原始内部样本不删除它。样本没有 `source_verified`、`support`、`reviewed_by` 等来源批准或审查标记。B 的 literal-v3 可能因缺少预期标签、URL 未字面出现、复杂资格段或学校来源未批准而保持待确认，这些不是应当通过改写网页来消除的问题。

本轮不生成 B 核验结果，也不把未取得的用户学校、预算、考试日、已有作品或其他硬条件填入本赛事文件。用户硬条件由根目录另行交接；没有真实用户画像时需明确标为未知。

## 来源与定位

- A 文件为 `Competition_Radar_A/examples/research_result_real_batch.json`，JSON Pointer `/sources/4`，定位时仍以 source_id 为准，不依赖数组下标稳定。
- source_id 为 `real-icnc-scu-2026-0828`。
- URL 为 https://jwc.scu.edu.cn/info/1069/10764.htm 。
- A 提供的抓取时间为 `2026-10-22T15:19:50+08:00`，发布日期为 `2026-08-28`；这里记录元数据，不用发布日期填报名年份或开始日期。
- A 批次 engine 为 `manual-web-fetch`。本次整理没有重新访问该页面，也没有独立鉴定网页真实性。
- source.content UTF-8 SHA-256 为 `8f2b38d447cba71ff9c69329f5439dceb7f0161998e799435265de369120fe2c`。

下表用 Python 字符串索引，起点包含、终点不包含；不是 UTF-8 字节偏移。所有位置基于下方完整 source.content，换行和全角标点均保留。每条 quote 都已机械检查为该正文的逐字连续子串。

| Evidence ID | 字段 | 起点 | 终点 |
| --- | --- | --- | --- |
| `scu-2026-competition_name-1` | `competition_name` | 0 | 34 |
| `scu-2026-competition_edition-1` | `competition_edition` | 0 | 34 |
| `scu-2026-track-1` | `track` | 190 | 380 |
| `scu-2026-official_url-1` | `official_url` | 0 | 34 |
| `scu-2026-eligibility-1` | `eligibility` | 183 | 1237 |
| `scu-2026-participation_mode-1` | `participation_mode` | 190 | 380 |
| `scu-2026-team_rules-1` | `team_rules` | 381 | 614 |
| `scu-2026-registration_start-1` | `registration_start` | 190 | 380 |
| `scu-2026-registration_deadline-1` | `registration_deadline` | 190 | 380 |
| `scu-2026-campus_deadline-1` | `campus_deadline` | 381 | 614 |
| `scu-2026-campus_deadline-2` | `campus_deadline` | 615 | 856 |
| `scu-2026-campus_deadline-3` | `campus_deadline` | 857 | 1025 |
| `scu-2026-campus_deadline-4` | `campus_deadline` | 1125 | 1204 |
| `scu-2026-task_description-1` | `task_description` | 190 | 380 |
| `scu-2026-deliverables-1` | `deliverables` | 190 | 380 |
| `scu-2026-attendance_mode-1` | `attendance_mode` | 1125 | 1204 |
| `scu-2026-registration_method-1` | `registration_method` | 183 | 1025 |
| `scu-2026-registration_url-1` | `registration_url` | 190 | 380 |
| `scu-2026-registration_materials-1` | `registration_materials` | 381 | 856 |
| `scu-2026-institutional_requirements-1` | `institutional_requirements` | 381 | 1025 |
| `scu-2026-schedule-1` | `schedule` | 1125 | 1204 |
| `scu-2026-judging_criteria-1` | `judging_criteria` | 1125 | 1204 |
| `scu-2026-awards-1` | `awards` | 1125 | 1204 |
| `scu-2026-work_rules-1` | `work_rules` | 1034 | 1124 |
| `scu-2026-contacts-1` | `contacts` | 1239 | 1439 |

## A 快照完整正文

下方保留 A 的 source.content 原文。原始正文没有末尾换行；关闭 Markdown 围栏前用于排版的分隔换行不属于原始正文。逐字检查与哈希均以 JSON 快照为准。

```text
关于中国国际大学生创新大赛（2026）四川大学产业命题赛道报名的通知
添加时间：2026-08-28

根据《关于举办中国国际大学生创新大赛（2026）四川大学校赛的通知》和《关于公布中国国际大学生创新大赛（2026）产业赛道入选企业命题的通知》（附件1），经学校研究决定，将进行中国国际大学生创新大赛（2026）四川大学校赛产业赛道报名，现将有关要求通知如下：

一、报名安排
1.全国大学生创业服务网报名。请补报产业赛道的团队负责人在全国大学生创业服务网https://cy.ncss.cn/完成报名（以下简称大创网），网上报名只需提交网评版PPT。产业赛道报名系统开放起止时间为北京时间2026年8月27日—9月25日。其中企业命题组需要对接企业命题，点击"产业赛道"-"企业命题组报名"；成果转化组不需要对接命题，点击"产业赛道"-"成果转化组报名"。
2.准备签字盖章报名表。参赛团队须填写《四川大学中国国际大学生创新大赛报名表》（见附件2），所有指导教师和参赛队员需在纸质版报名表上签字并加盖项目报送学院（负责人学籍所在学院）公章，拍照或扫描留存后，纸质版原件于9月2日12：00以前提交到项目负责人学籍所在学院审核。在校赛阶段，每名参赛人员在同赛道中参与不得超过2个项目，每个项目指导教师原则上不超过3名，每位指导教师指导当年项目仅限1个（含主赛道（不含国际项目）、红旅赛道、产业赛道），否则校赛系统无法成功报名。
3.四川大学中国国际大学生创新大赛管理系统报名。在大创网提交报名之后，请参赛团队指派一人在四川大学中国国际大学生创新大赛管理系统选择批次为"中国国际大学生创新大赛（2026）四川大学校赛产业赛道报名"填写项目报名信息（学生指南操作见附件3），并上传签字盖章的报名表、大创网报名成功截图、提交网评版PPT等。报名截止日期：9月2日12:00之前。请确保该系统填写的项目名称、赛道、组别、负责人、学号、学院、团队成员、指导教师信息（含姓名和顺序）同大创网和《报名表》的填报信息保持一致。
4.学院审核。请学院根据学生提交的签字盖章报名表于9月2日12:00之前登录四川大学中国国际大学生创新大赛管理系统审核并推荐报名项目(学院操作指南见附件3）。在大创网、校赛评审系统均报名成功且通过学院审核的项目方可进入校赛。校赛、省赛、国赛参赛项目负责人、团队成员、指导教师姓名及排序等信息，均以学院审核为准，一经报名，原则上不能更改。

二、报名须知
1.鼓励师生团队揭榜命题新报产业赛道，亦鼓励主赛道、红旅赛道转报产业赛道。为避免项目名称在校赛系统中冲突，影响后续评审，转报产业赛道和再次报名产业赛道的项目更新项目名称后方可提交。
2.9月2日12:00之前在四川大学中国国际大学生创新大赛管理系统报名者，报名结束后，学校组织网络评审和现场答辩评审，择优推荐项目参加省赛，不再授予校级奖励。
3.参加本次产业赛道报名的项目请加入QQ群1044704684。

三、竞赛信息交流渠道
中国国际大学生创新大赛（2026）四川大学校赛信息发布：四川大学教务处官网。
中国国际大学生创新大赛（2026）四川大学校赛官方QQ群号：239344010（学生1群）、972398755（学生2群），972772055（教师群）。
校赛联系人：王老师 85400031 邮箱cxcy@scu.edu.cn。
系统技术人员：李工18018038173，QQ：2880632006

教务处 2026年8月28日
```
