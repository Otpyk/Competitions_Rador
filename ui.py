"""
Competition Radar - Streamlit 前端 (D 负责)
两种模式：
1) 学院推荐竞赛库（按兴趣匹配 71 个推荐竞赛，真实快照补充详情）
2) 全链路深度核验（真实快照+规范候选 → B 核验 → C 消费 → 补全推荐，国产模型可选）

运行: pip install -r requirements-frontend.txt && streamlit run ui.py
原则: 前端只渲染后端结果；查不到就标「待查询/待确认」，不编造。
"""
# Streamlit is required at runtime; suppress the editor's missing-module warning
# in environments where the dependency has not been installed yet.
import streamlit as st  # type: ignore[import-not-found]

API = "http://127.0.0.1:8000"

LEVEL_LABELS = {"A": "A类·国家级", "B": "B类·国家级", "C": "C类·省级", "D": "D类·校内"}
GROUP_LABELS = {"recommended": "✅ 推荐（资格符合、报名进行中）", "pending": "⏳ 待确认", "excluded": "🚫 已排除"}
ELIG_LABELS = {"eligible": "符合", "ineligible": "不符合", "unknown": "无法判断"}
REG_LABELS = {"open": "🟢 报名中", "closed": "🔴 已截止", "unknown": "❓ 未知"}


def fetch_library(interests):
    import requests

    return requests.post(f"{API}/api/v1/library/recommend", json={"interests": list(interests)}, timeout=60).json()


def fetch_full(profile):
    import requests

    return requests.post(f"{API}/api/v1/search/full", json={"query": "全国大学生学科竞赛 2026", "profile": profile}, timeout=60).json()


st.set_page_config(page_title="Competition Radar 大学生竞赛雷达", layout="wide")
st.title("🎯 Competition Radar 大学生竞赛雷达")
st.caption("信息有证据、资格能筛选、缺失会追问、不确定不编造 · 全链路国产模型")

with st.sidebar:
    st.header("我的条件")
    mode = st.radio("模式", ["学院推荐竞赛库", "全链路深度核验"], index=0)
    interests = st.multiselect(
        "兴趣方向",
        ["人工智能", "数学建模", "数学", "编程", "信息安全", "机器人", "电子硬件", "计算机", "创新创业", "科研", "教育"],
        default=["人工智能"],
    )
    education = st.selectbox("学历", ["本科", "研究生"], index=0)
    grade = st.number_input("年级", 1, 5, 2)
    team_size = st.number_input("团队人数", 1, 10, 3)
    search = st.button("🔍 开始", type="primary", use_container_width=True)
    st.divider()
    st.caption("数据源：华南师范大学人工智能学院推荐竞赛列表 + 5 份真实通知快照")

if search:
    if mode == "学院推荐竞赛库":
        try:
            data = fetch_library(interests)
        except Exception as exc:
            st.error(f"请求后端失败（{API}）：{exc}")
            data = {}
        matches = data.get("matches") or []
        st.subheader(f"为你匹配到 {data.get('matched_count', len(matches))} 个竞赛（库内共 {data.get('library_count', '?')} 个）")
        st.caption(data.get("note", ""))
        for r in matches:
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"### {r['name']}")
                    awards = r.get("awards") or {}
                    award_text = " · ".join(f"{k}:{v}" for k, v in (("一级", awards.get("first")), ("二级", awards.get("second")), ("三级", awards.get("third"))) if v)
                    st.write(f"**级别:** {LEVEL_LABELS.get(r.get('level'), r.get('level'))}  |  兴趣命中: {'、'.join(r.get('matched_interests', []))}")
                    if award_text:
                        st.write(f"**获奖等级:** {award_text}")
                    st.write(f"**报名截止:** {r.get('deadline') or '⏳ 待查询'}")
                    st.write(f"**参赛资格:** {r.get('eligibility') or '待查询'}")
                    links = [l for l in ([f"[官网]({r['official_url']})"] if r.get('official_url') else []) + ([f"[报名]({r['registration_url']})"] if r.get('registration_url') else [])]
                    if links:
                        st.write(" · ".join(links))
                    st.caption("🔍 详情待查询" if r.get("detail_status") == "待查询" else f"📄 {r.get('detail_status')}")
                with c2:
                    st.metric("命中", r.get("match_score", 0))
    else:
        profile = {"education_level": education, "major": "计算机", "grade": int(grade), "team_size": int(team_size),
                   "interests": list(interests), "deadline_from": None, "deadline_to": None}
        try:
            data = fetch_full(profile)
        except Exception as exc:
            st.error(f"请求后端失败（{API}/api/v1/search/full）：{exc}")
            data = {}
        stages = data.get("stages", {})
        st.subheader(f"全链路结果：推荐 {len(data.get('recommended', []))} / 待确认 {len(data.get('pending', []))} / 排除 {len(data.get('excluded', []))}")
        st.caption(f"阶段: 抽取={stages.get('extract')} 核验={stages.get('verify')} 消费={stages.get('consume')} ｜ {data.get('note', '')}")
        for group in ("recommended", "pending", "excluded"):
            for r in data.get(group, []):
                with st.container(border=True):
                    st.markdown(f"### {r['name']}  `{GROUP_LABELS[group]}`")
                    st.write(f"届次: {r.get('edition') or '—'}  |  范围: {r.get('scope')}")
                    st.write(f"资格: {ELIG_LABELS.get(r['eligibility_status'])}  |  报名: {REG_LABELS.get(r['registration_status'])}  |  核验: {r['verification_status']}")
                    st.write(f"兴趣命中: {'、'.join(r.get('matched_interests')) or '无'}")
                    st.write(f"报名截止: {r.get('deadline') or '⏳ 待确认'}")
                    if r.get('official_url'):
                        st.write(f"[官网]({r['official_url']})")
                    for reason in r.get("reasons", []):
                        st.caption(f"· {reason}")
                    if r.get("unresolved_fields"):
                        st.caption(f"待确认字段: {'、'.join(r['unresolved_fields'])}")
else:
    st.write("在左侧填写条件，点击开始。")


# 直接运行 `python ui.py` 时，自动交给 streamlit 启动（避免记命令）
if __name__ == "__main__":
    if not st.runtime.exists():
        import subprocess
        import sys

        subprocess.run([sys.executable, "-m", "streamlit", "run", __file__])
