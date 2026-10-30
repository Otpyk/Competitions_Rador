"""B/C alignment proposal v2: collection fields, query terms and user priorities.

This is an adapter catalog, not C's canonical schema or a factual contest dataset.
"""

from dataclasses import asdict, dataclass


CATALOG_VERSION = "bc-alignment-v3"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    required: bool
    description: str
    query_terms: str
    kind: str = "text"
    labels: tuple[str, ...] = ()
    campus_only: bool = False


def _f(key, label, group, required, description, terms, kind="text", labels=(), campus=False):
    return FieldSpec(key, label, group, required, description, terms, kind, labels or (label,), campus)


CATALOG = (
    _f("competition_name", "赛事名称", "M01", True, "官方完整名称；顶层 name 仅用于寻找赛事", "官方 赛事名称"),
    _f("competition_edition", "届次年份", "M01", True, "确认本届，不用往年资料替代", "本届 届次 年份"),
    _f("track", "赛道组别", "M01", True, "记录目标赛道；不分赛道也需明确依据", "赛道 组别 官方章程"),
    _f("organizer", "主办方", "M02", True, "区分主办、承办、协办", "主办单位 官方通知", labels=("主办方", "主办单位")),
    _f("official_url", "官方通知链接", "M02", True, "当届通知或章程，不只放网站首页", "本届 官方通知 竞赛章程", "url"),
    _f("eligibility", "参赛资格", "M03", True, "学历、学籍、年级、专业、学校、地区等完整限制", "参赛资格 参赛对象 官方章程", labels=("参赛资格", "参赛对象")),
    _f("participation_mode", "参赛形式", "M04", True, "个人或团队", "个人 团队 参赛形式"),
    _f("team_rules", "组队规则", "M04", True, "人数上下限、跨校、队长、指导教师等完整条件", "组队人数 跨校 指导教师 队长"),
    _f("registration_start", "报名开始日期", "M05", True, "未公布就留空；不按往年推算", "报名 开始日期 官方通知", "date", ("报名开始日期", "报名开始时间")),
    _f("registration_deadline", "报名截止日期", "M05", True, "赛事层面截止；保留明确时分时区", "报名截止日期 报名时间 官方通知", "date", ("报名截止日期", "报名截止时间")),
    _f("campus_deadline", "校内截止日期", "M05", True, "校内推荐、报名、选拔截止，与全国截止分开", "校内 报名 推荐 选拔 截止", "date", ("校内截止日期", "校内报名截止日期")),
    _f("task_description", "比赛任务", "M06", True, "学生实际要完成什么", "竞赛任务 赛题 要求"),
    _f("deliverables", "提交成果", "M06", True, "代码、论文、视频、方案、实物等必要成果", "提交 作品 材料 成果"),
    _f("submission_deadline", "作品提交截止日期", "M06", True, "与报名截止分开；分阶段需保持范围", "作品 提交 截止日期", "date", ("作品提交截止日期", "提交截止日期")),
    _f("attendance_mode", "参赛方式", "M07", True, "各必需阶段线上、线下或混合；初赛线上不代表全程线上", "初赛 决赛 答辩 线上 线下 到场"),
    _f("venue", "比赛地点", "M07", True, "必须到场的阶段和城市；全程线上需明确依据", "比赛地点 决赛城市 到场"),
    _f("registration_fee", "报名费用", "M08", True, "金额、币种、每人或每队；没写不等于免费", "报名费 收费标准 每人 每队"),
    _f("mandatory_fees", "后续必缴费用", "M08", True, "赛事要求的其他必缴费用；未提及不等于没有", "复赛 决赛 必缴 费用 收费"),
    _f("registration_method", "报名方式", "M09", True, "个人、队长、学校统一报名或推荐", "报名方式 学校推荐 统一报名"),
    _f("registration_url", "官方报名入口", "M09", True, "当届真实入口；无公开入口须有报名方式证据", "官方报名入口 报名系统", "url"),
    _f("registration_materials", "报名材料", "M10", True, "身份、学籍、作品或团队信息等必要材料", "报名材料 提交 清单"),
    _f("institutional_requirements", "学校及教师手续", "M10", True, "审核、推荐、签字、盖章、校内名额；不要求也需依据", "学校审核 导师 签字 盖章 名额"),
    _f("schedule", "详细赛程", "E01", False, "初赛、复赛、决赛、答辩及晋级机制", "详细赛程 初赛 复赛 决赛 答辩"),
    _f("judging_criteria", "评分标准", "E02", False, "维度、权重、评审方式", "评分标准 评审 权重"),
    _f("awards", "奖项奖励", "E03", False, "奖项、数量、奖金、证书、个人或团队权益", "奖项 奖金 证书 权益"),
    _f("school_recognition", "本校认可情况", "E04", False, "具体学校/学院、年份、赛道及奖级政策；不推断含金量", "学校 竞赛认定 综测 学分 保研", campus=True),
    _f("technical_requirements", "技术与设备要求", "E05", False, "硬件、软件、数据、算力、实物限制", "硬件 软件 数据 算力 设备 实物"),
    _f("work_rules", "作品使用规则", "E05", False, "已有作品、重复投稿、获奖作品、开源、AI使用限制", "已有作品 重复投稿 开源 AI 使用规则"),
    _f("preparation_resources", "准备参考与支持", "E06", False, "往届题目作品、培训、指导及答疑", "历届 赛题 优秀作品 培训 答疑"),
    _f("expense_details", "详细投入与补助", "E07", False, "材料算力交通住宿及补助；估算与官方事实分开", "材料 算力 差旅 住宿 补助 费用"),
    _f("contacts", "联系与答疑渠道", "E08", False, "官方咨询及适用校内联系人", "官方 联系方式 咨询 答疑"),
)

FIELD_SPECS = {item.key: item for item in CATALOG}
MANDATORY_FIELDS = tuple(item.key for item in CATALOG if item.required)
EXTENSION_FIELDS = tuple(item.key for item in CATALOG if not item.required)
LEGACY_MINIMAL_FIELDS = ("registration_deadline", "eligibility", "registration_url")
DATE_FIELDS = frozenset(item.key for item in CATALOG if item.kind == "date")

# These exact statements are deliberately narrow; arbitrary N/A flags never pass.
NOT_APPLICABLE_STATEMENTS = {
    "track": ("本届不分赛道。",),
    "team_rules": ("本赛事仅接受个人参赛，无需组队。",),
    "campus_deadline": ("本赛事由个人直接报名，无校内报名环节。",),
    "submission_deadline": ("本赛事无需提交作品。",),
    "venue": ("本赛事全程线上，无需到场。",),
    "registration_url": ("本赛事仅由学校统一报名，无个人公开报名入口。",),
    "institutional_requirements": ("本赛事无需学校推荐、审核、签字或盖章，无校内名额限制，无需指导教师确认。",),
}

# These flags express user requirements, never evidence that a contest meets them.
HARD_CONSTRAINT_FIELDS = {
    "school_recognition_required": ("school_recognition",),
    "existing_work_only": ("work_rules",),
    "no_hardware": ("technical_requirements", "deliverables"),
    "avoid_exam_dates": ("schedule", "attendance_mode"),
    "total_budget_limit": ("expense_details", "registration_fee", "mandatory_fees"),
    "online_only": ("attendance_mode", "venue", "schedule"),
    "cross_school_team": ("team_rules",),
}


def expected_scope(competition, field_name: str) -> str:
    return competition.field_scopes.get(field_name, competition.scope)


def build_policy(*, hard_constraints=(), extra_required_fields=(), profile="student"):
    """Build B's deterministic requirements; unknown flags fail visibly."""
    from .b_contracts import VerificationPolicy
    if profile not in ("student", "legacy_minimal"):
        raise ValueError("Unknown policy profile")
    if isinstance(hard_constraints, str) or isinstance(extra_required_fields, str):
        raise ValueError("Requirements must be lists, not strings")
    required = list(MANDATORY_FIELDS if profile == "student" else LEGACY_MINIMAL_FIELDS)
    promoted = []
    reasons = {name: ["基础必须项"] for name in required}
    for constraint in hard_constraints:
        if constraint not in HARD_CONSTRAINT_FIELDS:
            raise ValueError(f"Unknown hard constraint: {constraint}")
        for name in HARD_CONSTRAINT_FIELDS[constraint]:
            if name not in required:
                required.append(name)
                promoted.append(name)
            reasons.setdefault(name, []).append(f"用户硬条件：{constraint}")
    for name in extra_required_fields:
        if name not in FIELD_SPECS:
            raise ValueError(f"Unknown extra required field: {name}")
        if name not in required:
            required.append(name)
            promoted.append(name)
        reasons.setdefault(name, []).append("用户明确要求核查")
    return VerificationPolicy(required_fields=tuple(required), promoted_fields=tuple(promoted),
                              requirement_reasons={name: tuple(values) for name, values in reasons.items()})


def catalog_as_dict():
    return {"version": CATALOG_VERSION, "status": "proposal_for_B_C_alignment",
            "fields": [asdict(item) for item in CATALOG],
            "hard_constraint_fields": HARD_CONSTRAINT_FIELDS,
            "not_applicable_statements": NOT_APPLICABLE_STATEMENTS}
