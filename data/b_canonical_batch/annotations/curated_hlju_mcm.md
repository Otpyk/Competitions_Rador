# 黑龙江大学数学建模真实快照标注

本文件说明 `curated_hlju_mcm.json` 的人工字段整理依据。仅使用 A 已提供的 `real-mcm-hlju-2026-0831` 快照，没有联网、调用模型、核验来源权威性或作出资格与报名结论。所有候选等待 B 核验。

## 目标与适用范围

- 赛事为全国大学生数学建模竞赛，届次为 2026；具体组别在此通知中未取得，`track` 为 null。
- 记录目标为黑龙江大学校内资格审查、统一报名及参赛管理，默认范围 `campus:黑龙江大学`。只有赛事名称、届次和全国竞赛时间说明使用 global 字段范围；global 仅表达候选事实的目标范围，不批准该学校通知为全国规则来源。
- 本记录与南京财经大学候选分开保存。黑龙江大学的免报名费条件、报名方式、导师资质、违纪和弃赛处罚不能推广到南京财经大学或其他学校。
- 原文包含全国管理系统、校内邮箱报名、学院统一导入及学生首次激活等不同环节，不能把管理系统 URL 当作学生绕过校内审查的直接报名入口。

## 日期与阶段

| 字段 | 候选值 | 依据与限制 |
| --- | --- | --- |
| `registration_start` | `2026-08-31` | 校内报名段明确完整年月日；范围为黑龙江大学校内邮箱报名，不能当作全国开放日期 |
| `registration_deadline` | null，无证据 | 全国统一报名截止未取得；不重复放置校内截止冒充全国截止 |
| `campus_deadline` | null，保留原文 | 原文为“2026年9月5日23:00时”，已含完整年份和时刻，但没有时区。B 日期模型要求带偏移时间，不补 `+08:00`，也不截断为整日而丢弃 23:00 |
| `submission_deadline` | null，保留相关原文 | 违纪段涉及论文和支撑材料上传失败，但没有作品提交截止，不能复制报名截止或竞赛结束时间 |

全国竞赛时间原文为“2026年全国大学生数学建模竞赛，将于9月10日（周四）18:00至9月13日（周日）20:00进行”。`schedule` 的主值仅保留这句全国竞赛时间，quote 保留整段上下文；校内主办和组织开展机构未放入 global 字段主值。没有把缺少偏移的竞赛时刻写成带时区日期。`2026年9月6日20：00时后` 属于首名队员系统激活时间，保留在报名方式和校内手续段中，不当作报名开始日期。

## 字段取舍

- `organizer` 为 null。正文明确校内“由创新创业教育学院主办，数学与统计学院组织开展”，以 campus 证据保存，没有将其填成全国赛事主办，也没有从文末署名推定全国主办。
- `official_url` 使用 A 快照的黑龙江大学通知地址，证据为完整标题。这一 URL 来自快照元数据，并未字面出现在正文，等待 B 判断其来源与用途，不能据此宣称通过官方来源审查。
- `eligibility` 连续保留资格审查至群管理及未尽事宜的完整原文，避免漏掉重新组队、获奖免报名费、导师资质、违纪或弃赛处罚等后段条件。正文没有明确参赛学历、年级、队伍人数上下限或跨校许可，不用其他学校的本科组三人规则补齐。
- `participation_mode` 候选为“参赛队”，只据正文按参赛队办理的措辞提取，不补三人一队。`team_rules` 保留整个组队和指导教师资质段，包括建议性质、挂名限制、教师赛前辅导、竞赛期间参与属违纪以及非本院教师资质。
- `registration_fee` 和 `expense_details` 保留完整条件段，区分原队获奖免收费、重新组队时至少两人获奖免收费、其他队伍 300 元且不退费。`expense_details` 另保留弃赛等情形需补交报名费的候选证据；它不代表已取得交通、住宿、材料、算力等总投入。`mandatory_fees` 为 null，未把未提及的其他费用写成免费或不适用。
- `registration_method`、`registration_materials` 与 `institutional_requirements` 保留邮箱、电子表格、规范命名、学院统一导入、首名队员激活和校内违规处理等原文。报名表是报名材料，不当作最终作品要求。
- `registration_url` 为原文明示的 `https://cumcm.cnki.net`，在该校报名流程下使用。系统账号密码说明原样保留在原文证据，未生成任何实际账号或凭据。
- `deliverables` 主值为 null，保留违纪段作为相关证据。该段提到电子版论文、纸质版论文、MD5 码、论文和支撑材料，但不是完整交付物/格式条款，所引用的论文规范正文尚未取得。
- `attendance_mode` 主值为 null，保留管理系统说明。网上报名或使用线上管理系统不能证明全国各阶段全程线上，`venue` 也保持 null。
- `work_rules` 保留完整违纪与弃赛段，并另附未尽事宜所指的政策文件说明。没有把“AI生成式论文等作弊行为”改写成全面禁止所有 AI 工具，也没有自行推定允许范围；完整 AI 使用规定仍未取得。
- `preparation_resources` 保存赛前讲座、微信群和相关政策文件提及，既没有补造二维码图片/群链接，也没有虚构讲座时间地点或政策附件正文。`contacts` 保留竞赛微信群说明及邮箱报名段作为不同用途的候选，邮箱是报名接收邮箱，未称其为全国咨询联系人。
- `task_description`、`judging_criteria`、`awards`、`school_recognition`、`technical_requirements` 没有取得足以填值的条款。不能因为通知提到“获省级三等奖”免报名费就将其当作本届完整奖项方案，不能把“MD5码不一致”推定为完整技术要求。

## 未解决项与交接边界

需要 B 逐字段判断证据支持度、全国事实在学校通知中的效力和校内条款适用性。当前缺口包括完整竞赛章程、参赛须知、论文格式、AI 使用规定、全国主办与报名截止、参赛组别及学历/年级/人数/跨校条件、完整作品与提交截止、到场与地点、评分和奖项、学校认可及总体投入。它们是本候选的未知内容，不代表 A 未提供真实样本。

JSON 明示全部 31 个字段，未给未知内容添加 `not_applicable`；每条证据均带黑龙江大学专属前缀和原始 `source_id`。内部 `source_id` 供 C 溯源，对 B 导出时由统一 exporter 剥离。不包含任何来源批准、字段通过、报名状态或用户资格结论。

## 来源、统计与逐字定位

- A source_id 为 `real-mcm-hlju-2026-0831`，URL 为 https://math.hlju.edu.cn/info/1009/2406.htm 。
- A 抓取时间 `2026-10-22T15:19:50+08:00`，发布日期 `2026-08-31`；不用于补全正文日期或判定当前仍可报名。
- source.content UTF-8 SHA-256 为 `12a9d3509a1f9798a2c8feb48c67aa90ab5141fad54512ede4ad12c2f06aea91`。
- 31 个字段中 17 个有候选主值，5 个主值 null 但保留相关证据，9 个 null 且无证据；共 26 条证据。

下表为 Python 字符串索引，起点包含、终点不包含；不是 UTF-8 字节偏移。逐字正文与哈希以 A JSON 快照为准。

| Evidence ID | 字段 | 起点 | 终点 |
| --- | --- | --- | --- |
| `hlju-2026-competition_name-1` | `competition_name` | 0 | 20 |
| `hlju-2026-competition_edition-1` | `competition_edition` | 0 | 20 |
| `hlju-2026-organizer-1` | `organizer` | 47 | 238 |
| `hlju-2026-official_url-1` | `official_url` | 0 | 20 |
| `hlju-2026-eligibility-1` | `eligibility` | 240 | 1577 |
| `hlju-2026-participation_mode-1` | `participation_mode` | 240 | 451 |
| `hlju-2026-team_rules-1` | `team_rules` | 453 | 794 |
| `hlju-2026-registration_start-1` | `registration_start` | 796 | 1035 |
| `hlju-2026-campus_deadline-1` | `campus_deadline` | 796 | 1035 |
| `hlju-2026-deliverables-1` | `deliverables` | 1037 | 1352 |
| `hlju-2026-submission_deadline-1` | `submission_deadline` | 1037 | 1352 |
| `hlju-2026-attendance_mode-1` | `attendance_mode` | 47 | 238 |
| `hlju-2026-registration_fee-1` | `registration_fee` | 240 | 451 |
| `hlju-2026-registration_method-1` | `registration_method` | 796 | 1035 |
| `hlju-2026-registration_url-1` | `registration_url` | 47 | 238 |
| `hlju-2026-registration_materials-1` | `registration_materials` | 796 | 1035 |
| `hlju-2026-institutional_requirements-1` | `institutional_requirements` | 796 | 1352 |
| `hlju-2026-schedule-1` | `schedule` | 47 | 238 |
| `hlju-2026-work_rules-1` | `work_rules` | 1037 | 1352 |
| `hlju-2026-work_rules-2` | `work_rules` | 1503 | 1577 |
| `hlju-2026-preparation_resources-1` | `preparation_resources` | 453 | 794 |
| `hlju-2026-preparation_resources-2` | `preparation_resources` | 1354 | 1501 |
| `hlju-2026-expense_details-1` | `expense_details` | 240 | 451 |
| `hlju-2026-expense_details-2` | `expense_details` | 1037 | 1352 |
| `hlju-2026-contacts-1` | `contacts` | 1354 | 1501 |
| `hlju-2026-contacts-2` | `contacts` | 796 | 1035 |
