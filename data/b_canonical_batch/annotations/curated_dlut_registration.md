# 大连理工大学真实通知的离线候选说明

这是 C 根据 A 已提供的真实快照手工整理的交接候选，不是自动模型结果，也不是 B 的通过结论。没有联网补抓或调用模型。

## 目标范围

- 来源 ID：`real-icnc-dlut-2026-0827`。
- 通知 URL：https://chuangxin.dlut.edu.cn/info/1018/16747.htm。
- 赛事：`中国国际大学生创新大赛（2026）`；目标阶段是大连理工大学本轮报名及校内选拔结果确认，范围为 `campus:大连理工大学`。
- 正文是全赛道报名通知，不是产业赛道专页。`track` 主值为 null，保留报名对象整段。不得把它归并成四川大学的产业赛道／企业命题组候选，或擅自选择高教主赛道国际项目。
- 正文把一般大创网报名和高教主赛道国际项目入口分开。目标组别尚未确定，所以 `registration_url` 主值为 null，分别保留两条入口及各自条件。`https://www.pilcchina.org/` 是通知给出的站点和入口名称，并不是已抓取确认的具体表单地址。
- `global` 仅用于赛事名称、届次及未知的全国事项；校内规则逐字段覆盖。学校通知能否独立支持相关全国事实仍须 B 审查。

## 保留的疑难和缺失

1. 报名窗口原文为“8月27日至9月4日12:00”，没有明确年份，也没有时区。不得从发布日期、标题届次或抓取时间补造完整日期。`registration_start`、`campus_deadline` 保持 null 并保留原文；`registration_deadline` 未填，因为这是校内报名窗口，不是已证明的全国截止。`submission_deadline` 也保持 null。
2. 资格引用完整连续的“二、报名对象”和“三、报名要求”，保留国际项目入口例外、一项目一赛道、学生单赛道最多一项目、负责人唯一性、3–15 人、报名失败无证书、评审开始后变更无效等限制。正文没有提供完整学历、毕业年限、专业或指导教师条件，不能据此判定个人符合资格。
3. `participation_mode` 只整理为“团队”，`team_rules` 和 `work_rules` 保留完整六条要求。跨校、指导教师人数、AI／开源使用没有说明，不补写。
4. “根据《教育部关于举办……的通知》”不等于页面明确列出全国主办方。`organizer` 保持 null，保留引言供 B 判断。
5. `official_url` 来自 A 的来源 URL 元数据，正文标题作为定位原句；该链接未逐字出现在正文中。这是通知链接候选，不能自动证明其官方性或 B 已批准。
6. 未成功报名无法生成获奖证书、多个赛道获奖只保留一项奖励等规则均被保留。它们没有给出完整奖项、数量或金额，因此 `awards` 主值留空并保留六条要求。
7. 报名材料没有列明；阅读“学生操作手册”不能推导上传材料清单。`registration_materials` 留空并保留提示。附件名 `学生操作手册2026.pdf` 可作为准备参考，未补造附件下载 URL。
8. 报名费、后续必缴费、交通住宿补助均未提及，留空，不标免费或 N/A。线上报名不等于全程线上比赛；到场、地点、比赛任务、最终作品、提交截止、赛程、评分标准、本校认可、技术设备要求及具体学校审核／盖章手续均未补造。
9. 联系渠道保留官方微信公众号、学信网及校内通知（推荐）渠道的完整措辞；没有编造姓名、电话、群号或邮箱。

## 机械验收

31 个字段；10 个有候选值，7 个留空但附疑难证据，14 个留空且无证据；共 19 条证据。所有 `quote` 逐字存在于指定 A 快照 `content`，不使用摘要或标题元数据代替正文。所有证据为普通 `value`，没有虚构不适用声明、来源审批或字段通过状态。

- 正文 SHA-256：`05ba82149b9dbbdca28acab79977639b1db1cd48e17a6f1472573b5d1e3c01c7`。
- 字符位置为 Python Unicode 字符下标，区间左闭右开，基于未修改的 A 正文。

| 证据 ID | 字段 | start_char | end_char |
| --- | --- | ---: | ---: |
| `dlut-2026-competition_name-1` | `competition_name` | 0 | 30 |
| `dlut-2026-competition_edition-1` | `competition_edition` | 0 | 30 |
| `dlut-2026-track-1` | `track` | 196 | 379 |
| `dlut-2026-organizer-1` | `organizer` | 62 | 170 |
| `dlut-2026-official_url-1` | `official_url` | 0 | 30 |
| `dlut-2026-eligibility-1` | `eligibility` | 196 | 610 |
| `dlut-2026-participation_mode-1` | `participation_mode` | 381 | 610 |
| `dlut-2026-team_rules-1` | `team_rules` | 381 | 610 |
| `dlut-2026-registration_start-1` | `registration_start` | 172 | 194 |
| `dlut-2026-campus_deadline-1` | `campus_deadline` | 172 | 194 |
| `dlut-2026-registration_method-1` | `registration_method` | 196 | 379 |
| `dlut-2026-registration_url-1` | `registration_url` | 203 | 273 |
| `dlut-2026-registration_url-2` | `registration_url` | 274 | 351 |
| `dlut-2026-registration_materials-1` | `registration_materials` | 352 | 379 |
| `dlut-2026-awards-1` | `awards` | 381 | 610 |
| `dlut-2026-work_rules-1` | `work_rules` | 381 | 610 |
| `dlut-2026-preparation_resources-1` | `preparation_resources` | 352 | 379 |
| `dlut-2026-preparation_resources-2` | `preparation_resources` | 741 | 757 |
| `dlut-2026-contacts-1` | `contacts` | 612 | 739 |

B 应单独给出来源批准、语义支持及字段裁决。报名状态与个人资格状态目前不能由候选值推导。
