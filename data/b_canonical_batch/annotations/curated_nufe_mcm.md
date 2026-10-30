# 南京财经大学数学建模真实快照标注

本文件说明 `curated_nufe_mcm.json` 的人工字段整理依据。仅使用 A 已提供的 `real-mcm-nufe-2026-0707` 快照，没有联网、调用模型、核验来源权威性或作出资格与报名结论。所有候选等待 B 核验。

## 目标与适用范围

- 赛事为全国大学生数学建模竞赛，届次为 2026；本通知的目标组别为本科组。
- 记录目标为南京财经大学本科组的暑期培训报名、培训后正式报名组织及参赛安排。默认范围 `campus:南京财经大学`；赛事名称、届次、全国主办、全国竞赛论文阶段的方式/作品/时间说明、奖项和竞赛期间交流规则通过 `field_scopes` 标明 global 候选范围，仍等待 B 判断来源效力。
- “主要面向大二、大三、大四的在校本科生”中的“主要”原样保留，没有改成绝对排除其他年级。鼓励跨学院、跨专业组队没有被改成允许跨学校组队。
- 本记录与黑龙江大学候选分开，不能将另一学校的免报名费、导师条件、报名邮箱和截止套用到南京财经大学。

## 日期与阶段

| 字段 | 候选值 | 依据与限制 |
| --- | --- | --- |
| `registration_start` | null，保留原文 | “2026年7月10日——2026年7月19日”结合下一段只说明线上报名参加暑期培训；正式比赛由培训结束后教练组统一报名，开始日未给出 |
| `registration_deadline` | null，保留原文 | 7 月 19 日是本通知培训报名窗口终点，不当作全国比赛报名截止 |
| `campus_deadline` | null，保留原文 | 校内暑期培训报名窗口已知，但本候选没有校内正式竞赛报名/推荐截止；保留两段阶段证据，不将培训截止冒充竞赛截止 |
| `submission_deadline` | null，保留原文 | 正文只说“规定时间内通过指定网站提交论文”，没有给出实际提交截止；竞赛结束时刻不能直接复制过来 |

已取得的培训窗口不是因为缺年份而留空，而是其阶段与上述竞赛报名日期字段不同。培训计划“2026年7月10日至7月20日，线上培训”保留在 `preparation_resources`，不能将培训结束后的统一报名推成 7 月 20 日当天正式报名。

全国比赛时间段“2026年9月10日（周四）18时至9月13日（周日）20时”作为完整原文留在 `schedule`；题目发布另有“2026年9月10日晚上6：00”。没有补偏移时区，没有将赛事时刻当作论文上传截止。

## 字段取舍

- 全国主办 `organizer` 候选“中国工业与应用数学学会”有正文明确句子支持，范围为 global。校内组织机构另为“主办单位：南京财经大学教务处”“承办单位：南京财经大学应用数学学院”；此处记录两者区别，没有把校内组织或文末署名替换成全国主办。
- `official_url` 使用 A 快照的南京财经大学通知地址，范围为 campus。完整标题作为 quote，URL 来源为 A 元数据，并未字面出现在正文；这是待 B 审查的通知候选地址。正文中的 `www.mcm.edu.cn` 被说明为赛题发布官网，但没有协议且不是报名入口，不补 `https://` 写进 `registration_url`。
- `eligibility`、`team_rules` 保留完整“参赛对象”和“报名要求”两段，涵盖本科组、3 人一队、主要面向年级、数学基础、至少一名队员熟练掌握编程、鼓励跨学院跨专业等条件。没有自动生成结构化资格结论或跨校许可。
- `participation_mode` 用正文“全国大学生数学建模竞赛为团队竞赛”；`track` 为本校通知明确的“本科组”，不把本校只组织本科组推断为全国仅有本科组。
- `task_description` 保存模型、程序、论文及人员专业背景要求的原段，仅说明工作形式；实际赛题到开赛时才公布，未补具体主题。`technical_requirements` 也保留该段的知识/编程要求，未由此推断无硬件、设备清单或软件许可条件。
- `deliverables` 为正文明确的完成并网上提交论文原句；它不同于报名材料，仍不是完整论文格式、附件清单或支撑材料规则。`registration_materials` 未取得，保持 null。
- `attendance_mode` 保留全国竞赛论文阶段的网上发布题目、下载、写作和网站提交说明，不能据此保证所有必须阶段全程线上、无地点限制或后续无答辩。校内暑期培训明确线上，但其阶段另外保存在准备资源中；`venue` 保持 null。
- `registration_method` 与 `institutional_requirements` 保留“线上报名参加暑期培训”“培训结束后教练组统一组织正式报名”的整个段落，不能将 QQ 群号当正式报名 URL；`registration_url` 保持 null。
- `registration_fee` 为每队 300 元且学生自付的完整原句；`expense_details` 同样只记录已知报名费，不补总费用。通知没有取得其他必缴费用、补助、住宿、交通等信息，`mandatory_fees` 为 null，不写免费。
- `awards` 保留江苏省赛区一、二、三等奖及省一等奖中选拔参加国家级评定、国家一等奖二等奖的整段；“按照一定规则”的具体规则未知，不虚构比例、奖金或人人获奖。`school_recognition` 保持 null，校内组织参赛不等于已确认学分、综测或保研认可。
- `work_rules` 保留可使用图书馆/网络资料、不得与本队以外任何人讨论的完整句子，不据此推断 AI 工具、代码开源或重复作品许可。`judging_criteria` 未因存在评奖段就补为完整评分标准。
- `preparation_resources` 和 `contacts` 分别保存暑期培训计划、QQ 群以及校内负责人原段。附件培训计划正文未在快照中取得，没有补造附件链接或课程细目。

## 未解决项与交接边界

下一步由 B 判断这些全国/校内候选的证据支持度。尚缺正式竞赛报名窗口和完整报名方式、校内正式推荐截止、作品格式/支撑材料和提交截止、各阶段到场/地点、完整资格、全国官方规则、评分细则、AI 使用规则、学校认可及总体投入。现有 A 真实快照已经到位，这些只是该通知正文尚未覆盖的具体问题。

JSON 明示全部 31 个字段；不把未知内容写成 `not_applicable`，不包含来源批准、字段通过、报名或资格判定。证据使用南京财经大学专属前缀与原 `source_id`，对外 B 导出由统一 exporter 剥离内部 `source_id`。

## 来源、统计与逐字定位

- A source_id 为 `real-mcm-nufe-2026-0707`，URL 为 https://jwc.nufe.edu.cn/info/1031/18284.htm 。
- A 抓取时间 `2026-10-22T15:19:50+08:00`，发布日期 `2026-07-07`；不用于补全正文日期或判定当前仍可报名。
- source.content UTF-8 SHA-256 为 `ea363789b5176fe03d809a472c2692934e414beda8561b082c839f75ab0fccab`。
- 31 个字段中 21 个有候选主值，4 个主值 null 但保留相关证据，6 个 null 且无证据；共 30 条证据。

下表为 Python 字符串索引，起点包含、终点不包含；不是 UTF-8 字节偏移。逐字正文与哈希以 A JSON 快照为准。

| Evidence ID | 字段 | 起点 | 终点 |
| --- | --- | --- | --- |
| `nufe-2026-competition_name-1` | `competition_name` | 0 | 29 |
| `nufe-2026-competition_edition-1` | `competition_edition` | 0 | 29 |
| `nufe-2026-track-1` | `track` | 588 | 631 |
| `nufe-2026-organizer-1` | `organizer` | 36 | 293 |
| `nufe-2026-official_url-1` | `official_url` | 0 | 29 |
| `nufe-2026-eligibility-1` | `eligibility` | 588 | 762 |
| `nufe-2026-participation_mode-1` | `participation_mode` | 633 | 762 |
| `nufe-2026-team_rules-1` | `team_rules` | 588 | 762 |
| `nufe-2026-registration_start-1` | `registration_start` | 764 | 798 |
| `nufe-2026-registration_start-2` | `registration_start` | 800 | 910 |
| `nufe-2026-registration_deadline-1` | `registration_deadline` | 764 | 798 |
| `nufe-2026-registration_deadline-2` | `registration_deadline` | 800 | 910 |
| `nufe-2026-campus_deadline-1` | `campus_deadline` | 764 | 798 |
| `nufe-2026-campus_deadline-2` | `campus_deadline` | 800 | 910 |
| `nufe-2026-task_description-1` | `task_description` | 633 | 762 |
| `nufe-2026-deliverables-1` | `deliverables` | 336 | 586 |
| `nufe-2026-submission_deadline-1` | `submission_deadline` | 336 | 586 |
| `nufe-2026-attendance_mode-1` | `attendance_mode` | 336 | 586 |
| `nufe-2026-registration_fee-1` | `registration_fee` | 800 | 910 |
| `nufe-2026-registration_method-1` | `registration_method` | 800 | 910 |
| `nufe-2026-institutional_requirements-1` | `institutional_requirements` | 800 | 910 |
| `nufe-2026-schedule-1` | `schedule` | 336 | 586 |
| `nufe-2026-awards-1` | `awards` | 912 | 992 |
| `nufe-2026-technical_requirements-1` | `technical_requirements` | 633 | 762 |
| `nufe-2026-work_rules-1` | `work_rules` | 336 | 586 |
| `nufe-2026-preparation_resources-1` | `preparation_resources` | 994 | 1070 |
| `nufe-2026-preparation_resources-2` | `preparation_resources` | 800 | 910 |
| `nufe-2026-expense_details-1` | `expense_details` | 800 | 910 |
| `nufe-2026-contacts-1` | `contacts` | 994 | 1070 |
| `nufe-2026-contacts-2` | `contacts` | 800 | 910 |
