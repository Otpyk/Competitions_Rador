"""演示抽取器（A 临时提供，补 C 自动抽取器缺口）。

把 ResearchBatch（A 的六键来源快照）按规则抽取为 C v0.1 的 11 字段候选
（CandidateContest JSON）。约束：

- 每条 claim 的 evidence.quote 一律取**整段原文**（空行分隔），逐字取自来源正文；
  整段引用既通过 C 的逐字校验，也给 B 的 literal-v3 段落审查完整上下文。
- 日期缺失年份时不做年份推断，不生成该字段候选（保持缺失）。
- 无法可靠解析的内容保留完整原文到 other_requirements / 不生成候选。
- 本抽取器是演示实现（规则 + 有限词典），不是 C 承诺的正式抽取器。
"""
from __future__ import annotations

import re
from typing import Any

FIELDS = (
    "name", "organizer", "edition", "track", "stage", "tags", "eligibility",
    "registration_start", "registration_deadline", "official_url", "registration_url",
)

_NAME_PATTERNS = [
    "全国大学生数学建模竞赛",
    "中国国际大学生创新大赛",
    "蓝桥杯全国大学生软件和信息技术大赛",
    "全国大学生程序设计竞赛",
    "全国大学生人工智能创新大赛",
]

_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_MONTH_DAY_RE = re.compile(r"\d{1,2}月\d{1,2}日")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
_URL_RE = re.compile(r"https?://[^\s，。；、）)）\u3000]+")

_EDU_MAP = [("研究生", "研究生"), ("硕士", "研究生"), ("博士", "研究生"), ("专科生", "专科"),
            ("大专", "专科"), ("本科生", "本科")]
_GRADE_MAP = [("大一", 1), ("大二", 2), ("大三", 3), ("大四", 4), ("大五", 5)]
_TEAM_RE = re.compile(r"(\d+)\s*[-—至~]\s*(\d+)\s*人|(\d+)\s*人为一队|每队\s*(\d+)\s*人|(\d+)\s*人一队")


def _paragraphs(content: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]


def _find_paragraph(content: str, *keywords: str) -> str | None:
    for p in _paragraphs(content):
        if any(k in p for k in keywords):
            return p
    return None


def _para_of(content: str, token: str) -> str | None:
    for p in _paragraphs(content):
        if token in p:
            return p
    return None


def _claim(claim_id: str, field: str, value: Any, source_id: str, quote: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "field": field,
        "value": value,
        "evidence": [{"source_id": source_id, "quote": quote}],
    }


def _extract_name(content: str, title: str | None) -> tuple[str, str] | None:
    for pattern in _NAME_PATTERNS:
        para = _para_of(content, pattern)
        if para:
            return pattern, para
    first_para = _paragraphs(content)[0] if _paragraphs(content) else ""
    if title and title in content:
        return title, _para_of(content, title) or first_para
    if first_para:
        return first_para.splitlines()[0].strip(), first_para
    return None


def _extract_edition(content: str) -> tuple[str, str] | None:
    m = _DATE_RE.search(content)
    if m:
        return m.group(1), _para_of(content, m.group(0)) or m.group(0)
    m = re.search(r"（(\d{4})）", content)
    if m:
        return m.group(1), _para_of(content, m.group(0)) or m.group(0)
    m = re.search(r"第([一二三四五六七八九十百]+)届", content)
    if m:
        return f"第{m.group(1)}届", _para_of(content, m.group(0)) or m.group(0)
    return None


def _extract_organizer(content: str) -> tuple[str, str] | None:
    for p in _paragraphs(content):
        if "主办" not in p:
            continue
        m = re.search(r"主办单位\s*[:：]\s*([^\s，。；]+)", p)
        if m:
            return m.group(1), p
        m = re.search(r"由([^，。；]{2,20}?)主办", p)
        if m:
            return m.group(1), p
    return None


def _extract_track(content: str) -> tuple[str, str] | None:
    for pattern in ("产业命题赛道", "企业命题组", "成果转化组", "高教主赛道", "主赛道", "红旅赛道", "产业赛道"):
        if pattern in content:
            return pattern, _para_of(content, pattern) or pattern
    return None


def _extract_stage(content: str) -> tuple[str, str] | None:
    for pattern in ("正式报名", "报名"):
        if pattern in content:
            return pattern, _para_of(content, pattern) or pattern
    return None


_RANGE_RE = re.compile(
    r"报名时间(?:为|：|:)?\s*"
    r"(?P<start>\d{4}年\d{1,2}月\d{1,2}日|即日(?:起)?)"
    r"\s*(?:至|——|—|-|到)\s*"
    r"(?P<end>\d{4}年\d{1,2}月\d{1,2}日)"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)?"
)
_DEADLINE_RE = re.compile(
    r"报名截止(?:日期|时间)?(?:为|：|:)?\s*(?P<d>\d{4}年\d{1,2}月\d{1,2}日)"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)?"
)
_OPEN_RE = re.compile(
    r"开放起止时间(?:为)?\s*(?:北京时间)?\s*(?P<start>\d{4}年\d{1,2}月\d{1,2}日)\s*(?:—|至|-)\s*\d{1,2}月\d{1,2}日"
)


def _cn_date(s: str) -> str | None:
    m = _DATE_RE.search(s)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _cn_time(s: str) -> str | None:
    m = _TIME_RE.search(s or "")
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def _reg_time_value(date_str: str, time_str: str | None, timezone: str | None) -> dict:
    return {"date": date_str, "time": _cn_time(time_str), "timezone": timezone}


def _extract_registration(content: str) -> tuple[dict | None, str | None, dict | None, str | None]:
    """从“报名时间…至…”“报名截止…”精确抽取起止；缺年份不猜、不把段落内其它日期当截止。"""
    timezone = "Asia/Shanghai" if "北京时间" in content else None
    start = deadline = None
    start_quote = deadline_quote = None

    para = _find_paragraph(content, "报名时间", "起止时间")
    if para:
        m = _RANGE_RE.search(para)
        if m:
            if m.group("start") and not m.group("start").startswith("即日"):
                start = _reg_time_value(_cn_date(m.group("start")), None, timezone)
                start_quote = para
            if m.group("end"):
                deadline = _reg_time_value(_cn_date(m.group("end")), m.group("time"), timezone)
                deadline_quote = para
        else:
            m = _OPEN_RE.search(para)
            if m:
                start = _reg_time_value(_cn_date(m.group("start")), None, timezone)
                start_quote = para

    if deadline is None:
        para2 = _find_paragraph(content, "报名截止", "截止时间")
        if para2:
            m = _DEADLINE_RE.search(para2)
            if m:
                deadline = _reg_time_value(_cn_date(m.group("d")), m.group("time"), timezone)
                deadline_quote = para2
    return start, start_quote, deadline, deadline_quote


def _extract_urls(content: str, page_url: str) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    official = registration = None
    for m in _URL_RE.finditer(content):
        url = m.group(0)
        para = _para_of(content, url) or url
        if registration is None and any(k in para for k in ("报名系统", "报名入口", "报名网站", "网上报名", "完成报名", "管理系统", "登录系统")):
            registration = (url, para)
        elif official is None and "报名" not in para:
            official = (url, para)
    # 通知页面自证：B 的 literal-v3 允许已批准通知页面证明自身 URL 作为官方通知链接。
    if official is None and page_url:
        first = _paragraphs(content)[0] if _paragraphs(content) else page_url
        official = (page_url, first)
    return official, registration


def _extract_eligibility(content: str) -> tuple[dict, str] | None:
    para = _find_paragraph(content, "报名对象", "参赛对象", "团队人数", "参赛人员", "参赛资格")
    if not para:
        return None
    edu: list[str] = []
    for token, label in _EDU_MAP:
        if token in para and label not in edu:
            edu.append(label)
    grades: list[int] = []
    for token, g in _GRADE_MAP:
        if token in para and g not in grades:
            grades.append(g)
    team: dict[str, int] | None = None
    tm = _TEAM_RE.search(para)
    if tm:
        if tm.group(1) and tm.group(2):
            team = {"min": int(tm.group(1)), "max": int(tm.group(2))}
        elif tm.group(3):
            team = {"min": int(tm.group(3)), "max": int(tm.group(3))}
        elif tm.group(4):
            team = {"min": int(tm.group(4)), "max": int(tm.group(4))}
        elif tm.group(5):
            team = {"min": int(tm.group(5)), "max": int(tm.group(5))}
    value = {
        "allowed_education_levels": edu or None,
        "allowed_majors": None,
        "allowed_grades": grades or None,
        "team_size": team,
        "other_requirements": [para],
    }
    return value, para


def extract_competitions(batch: dict) -> list[dict]:
    """输入 ResearchBatch JSON；输出 CandidateContest JSON 数组（11 字段）。"""
    sources = batch.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError("batch.sources 必须为列表")
    candidates: list[dict] = []
    for source in sources:
        if not isinstance(source, dict) or not source.get("source_id"):
            continue
        content = source.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        source_id = source["source_id"]
        title = source.get("title") if isinstance(source.get("title"), str) else None
        claims: list[dict] = []

        found = _extract_name(content, title)
        if found:
            claims.append(_claim(f"{source_id}-name", "name", found[0], source_id, found[1]))
        found = _extract_edition(content)
        if found:
            claims.append(_claim(f"{source_id}-edition", "edition", found[0], source_id, found[1]))
        found = _extract_organizer(content)
        if found:
            claims.append(_claim(f"{source_id}-organizer", "organizer", found[0], source_id, found[1]))
        found = _extract_track(content)
        if found:
            claims.append(_claim(f"{source_id}-track", "track", found[0], source_id, found[1]))
        found = _extract_stage(content)
        if found:
            claims.append(_claim(f"{source_id}-stage", "stage", found[0], source_id, found[1]))
        found = _extract_eligibility(content)
        if found:
            claims.append(_claim(f"{source_id}-eligibility", "eligibility", found[0], source_id, found[1]))
        start, start_quote, deadline, deadline_quote = _extract_registration(content)
        if start and start_quote:
            claims.append(_claim(f"{source_id}-registration_start", "registration_start", start, source_id, start_quote))
        if deadline and deadline_quote:
            claims.append(_claim(f"{source_id}-registration_deadline", "registration_deadline", deadline, source_id,
                                 deadline_quote))
        official, registration = _extract_urls(content, str(source.get("url") or ""))
        if official:
            claims.append(_claim(f"{source_id}-official_url", "official_url", official[0], source_id, official[1]))
        if registration:
            claims.append(_claim(f"{source_id}-registration_url", "registration_url", registration[0], source_id,
                                 registration[1]))
        if not claims:
            continue
        record_id = f"{source_id}-rec"
        candidates.append({"record_id": record_id, "member_ids": [record_id], "claims": claims})
    return candidates
