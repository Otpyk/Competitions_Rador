"""31 字段全链路推荐（A 补 C 的资格/排序/归并缺口，裁决仍全部来自 B）。

- C-2 资格：从 B 已核验的 eligibility 原文，按保守规则解析学历/年级/团队人数并与画像比对；
  解析不出则保持 unknown，不编造。
- C-3 排序：兴趣命中（名称 + 资格原文关键词）+ 已核验截止升序 + 三组分组。
- C-4 归并：同 (name, edition) 的多个候选（不同学校/来源）合并展示，保留各自证据来源。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

# 学历/年级/团队关键词（保守：只在原文明确出现才解析）
_EDU = [("研究生", "研究生"), ("硕士", "研究生"), ("博士", "研究生"), ("专科生", "专科"),
        ("大专", "专科"), ("本科生", "本科")]
_GRADE = [("大一", 1), ("大二", 2), ("大三", 3), ("大四", 4), ("大五", 5)]
_TEAM = re.compile(r"(\d+)\s*[-—至~]\s*(\d+)\s*人|(\d+)\s*人为一队|每队\s*(\d+)\s*人|(\d+)\s*人一队")

INTEREST_KEYWORDS = {
    "人工智能": ["人工智能", "算法精英", "AI"],
    "数学建模": ["数学建模", "数模"],
    "数学": ["数学竞赛", "数学"],
    "编程": ["程序设计", "ICPC", "CCPC", "蓝桥", "天梯", "百度之星", "软件杯", "软件设计", "软件开源", "工业软件"],
    "信息安全": ["信息安全", "网安", "网鼎杯", "强网杯", "X-NUCA", "对抗技术", "网络安全"],
    "机器人": ["机器人", "RoboCup", "RoboMaster", "RoboCon", "RAICOM", "睿抗", "智能汽车"],
    "电子硬件": ["电子设计", "嵌入式", "芯片", "物联网", "超级计算机", "ASC"],
    "计算机": ["计算机系统", "计算机设计", "计算机大赛", "大数据", "移动应用", "网络技术", "华为ICT"],
    "创新创业": ["创新大赛", "创业", "挑战杯", "职业规划", "iTeach", "数字化教育"],
    "科研": ["挑战杯", "学术科技"],
    "教育": ["师范", "教学技能"],
}


def _parse_eligibility(text: str) -> dict[str, Any]:
    """从资格原文保守解析学历/年级/团队人数；解析不出返回空。"""
    edu = [label for token, label in _EDU if token in text]
    grades = [g for token, g in _GRADE if token in text]
    team = None
    m = _TEAM.search(text)
    if m:
        if m.group(1) and m.group(2):
            team = {"min": int(m.group(1)), "max": int(m.group(2))}
        elif m.group(3):
            team = {"min": int(m.group(3)), "max": int(m.group(3))}
        elif m.group(4):
            team = {"min": int(m.group(4)), "max": int(m.group(4))}
        elif m.group(5):
            team = {"min": int(m.group(5)), "max": int(m.group(5))}
    return {"education_levels": edu, "grades": grades, "team": team}


def assess_eligibility(text: str | None, profile: dict) -> tuple[str, list[str]]:
    """返回 (eligible/ineligible/unknown, reasons)。仅凭明确解析到的约束判断，缺失即 unknown。"""
    if not text or not text.strip():
        return "unknown", ["参赛资格原文未核验，无法判断用户资格。"]
    parsed = _parse_eligibility(text)
    reasons: list[str] = []
    matched_any = False

    edu = parsed["education_levels"]
    if edu:
        matched_any = True
        if profile.get("education_level") and profile["education_level"] not in edu:
            return "ineligible", [f"资格要求学历为：{'、'.join(edu)}；用户为 {profile['education_level']}。"]

    grades = parsed["grades"]
    if grades:
        matched_any = True
        if profile.get("grade") and profile["grade"] not in grades:
            return "ineligible", [f"资格限定年级：{'、'.join(map(str, grades))}；用户为 {profile['grade']} 年级。"]

    team = parsed["team"]
    if team:
        matched_any = True
        ts = profile.get("team_size")
        if ts and not (team["min"] <= ts <= team["max"]):
            return "ineligible", [f"资格限定每队 {team['min']}-{team['max']} 人；用户为 {ts} 人。"]

    if not matched_any:
        return "unknown", ["资格原文未能解析出可判定的学历/年级/团队人数约束，保守保持未知。"]
    reasons.append("已按资格原文中明确出现的学历/年级/团队人数约束判断。")
    return "eligible", reasons


def interest_match(name: str, eligibility: str | None, interests: list[str]) -> list[str]:
    hay = (name or "") + " " + (eligibility or "")
    hits = []
    for interest in interests:
        kws = INTEREST_KEYWORDS.get(interest, [interest])
        if any(k in hay for k in kws):
            hits.append(interest)
    return hits


def _deadline(verified_values: dict) -> date | None:
    raw = verified_values.get("registration_deadline")
    if not raw:
        return None
    m = re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw)
    if m:
        return date.fromisoformat(raw)
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).date()
    except (ValueError, TypeError):
        return None


def is_participable(scope: str | None, user_school: str) -> tuple[bool, str]:
    """判断本校学生能否参加：global=全国/省级可参加；campus:本校=可参加；campus:外校=排除。"""
    if not scope or scope == "global":
        return True, ""
    if scope.startswith("campus:"):
        school = scope[len("campus:"):]
        if school == user_school:
            return True, ""
        return False, f"该通知为「{school}」的校内报名/选拔，非本校学生无法参加。"
    return True, ""


def recommend_full(consumed: list, profile: dict, as_of: datetime, user_school: str = "华南师范大学") -> dict:
    """consumed: ConsumedBReturn 列表。返回 {recommended,pending,excluded,merged,note}。"""
    interests = list(profile.get("interests") or [])
    groups: dict[str, list[dict]] = {"recommended": [], "pending": [], "excluded": []}

    for r in consumed:
        name = r.verified_values.get("competition_name") or r.candidate.name
        edition = r.verified_values.get("competition_edition") or r.candidate.edition or ""
        eligibility_text = r.verified_values.get("eligibility")
        elig_status, elig_reasons = assess_eligibility(eligibility_text, profile)
        deadline = _deadline(r.verified_values)
        matched = interest_match(name, eligibility_text, interests)
        participable, scope_reason = is_participable(r.candidate.scope, user_school)

        # 报名状态：用已核验 deadline 相对 as_of 判断
        reg_status = "unknown"
        if deadline is not None:
            reg_status = "closed" if deadline < as_of.date() else "open"

        # 用户截止范围
        d_from = profile.get("deadline_from")
        d_to = profile.get("deadline_to")
        outside_range = deadline is not None and (
            (d_from is not None and deadline < date.fromisoformat(d_from))
            or (d_to is not None and deadline > date.fromisoformat(d_to))
        )

        record = {
            "record_id": r.candidate.id,
            "name": name,
            "edition": edition,
            "scope": r.candidate.scope,
            "participable": participable,
            "eligibility_status": elig_status,
            "registration_status": reg_status,
            "verification_status": r.response.verification.status,
            "deadline": deadline.isoformat() if deadline else None,
            "matched_interests": matched,
            "match_score": len(matched),
            "eligibility_text": (eligibility_text or "")[:200],
            "official_url": r.verified_values.get("official_url"),
            "registration_url": r.verified_values.get("registration_url"),
            "organizer": r.verified_values.get("organizer"),
            "reasons": list(dict.fromkeys(elig_reasons + ([scope_reason] if scope_reason else []))),
            "verified_fields": sorted(r.verified_values.keys()),
            "unresolved_fields": sorted(r.unresolved.keys()),
        }

        if not participable:
            bucket = "excluded"
        elif elig_status == "ineligible" or reg_status == "closed" or outside_range:
            bucket = "excluded"
        elif elig_status == "eligible" and reg_status == "open" and not outside_range:
            bucket = "recommended"
        else:
            bucket = "pending"
        groups[bucket].append(record)

    # C-3 排序：兴趣命中降序 → 截止升序 → 名称
    for bucket in groups:
        groups[bucket].sort(key=lambda x: (-x["match_score"], x["deadline"] or "9999-12-31", x["name"]))

    # C-4 归并：同 name+edition 的多候选，保留第一个，其余合并为 evidence_sources 备注
    merged: dict[str, list[str]] = {}
    for bucket in groups:
        for item in groups[bucket]:
            key = (item["name"], item["edition"])
            merged.setdefault(key, []).append(item["record_id"])

    note = ("资格仅依据资格原文中明确出现的学历/年级/团队人数约束；解析不出则未知，不编造。"
            "报名状态按已核验截止日期相对当前时间判断。")
    return {
        "recommended": groups["recommended"],
        "pending": groups["pending"],
        "excluded": groups["excluded"],
        "as_of": as_of.isoformat(),
        "merged_groups": {f"{k[0]}·{k[1]}": v for k, v in merged.items() if len(v) > 1},
        "note": note,
    }
