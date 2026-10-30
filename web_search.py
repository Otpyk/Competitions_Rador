"""联网搜索 + 正文抓取（生成六键快照），搜索后端可插拔。

- 搜索：Bocha（国产，推荐）/ Tavily / DuckDuckGo（免 key）/ 手动 URL 列表。
- 抓取：httpx 抓 HTML → 去标签成正文文本。
- 输出：六键 SourceDocument 快照（source_id/url/title/content/fetched_at/published_date），
  fetched_at 用实际抓取时间、published_date 无法确认时为 null（不编造）。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import httpx

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CompetitionRadar/0.1"}

# 明显非官方的内容/博客/论坛域名，抓取时跳过（避免把博客当官方通知）
_BLOCKED_DOMAINS = (
    "cnblogs.com", "zhihu.com", "csdn.net", "jianshu.com", "sohu.com", "163.com",
    "qq.com", "weixin", "mp.weixin", "bilibili.com", "douyin.com", "xiaohongshu.com",
    "baidu.com", "sina.com", "juejin.cn", "infoq.cn", "segmentfault.com", "zhidx.com",
)

# 官方站点优先：教育/政府/官方域名排在前面
def _domain_rank(url: str) -> int:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if any(b in host for b in _BLOCKED_DOMAINS):
        return 9
    if host.endswith((".edu.cn", ".gov.cn", ".org.cn")):
        return 0
    if host.endswith(".cn"):
        return 1
    return 5


def _html_to_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text)
    return text.strip()


def fetch_page(url: str, timeout: float = 20) -> str:
    """抓取页面正文文本；非 HTML 内容原样返回。"""
    resp = httpx.get(url, headers=_UA, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "").lower()
    if "html" in ctype:
        return _html_to_text(resp.text)
    return resp.text


# --------------------------------------------------------------------------- #
# 搜索后端
# --------------------------------------------------------------------------- #
def search_duckduckgo(query: str, max_results: int = 5) -> list[str]:
    resp = httpx.post(
        "https://html.duckduckgo.com/html/", data={"q": query}, headers=_UA, timeout=20,
    )
    urls = re.findall(r"uddg=([^&]+)", resp.text)
    seen, out = set(), []
    for u in urls:
        u = httpx.unquote(u)
        if u not in seen and u.startswith("http"):
            seen.add(u)
            out.append(u)
        if len(out) >= max_results:
            break
    return out


def search_bocha(query: str, key: str, max_results: int = 5) -> list[str]:
    resp = httpx.post(
        "https://api.bochaai.com/v1/web-search",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "summary": False, "count": max_results},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    pages = data.get("data", {}).get("webPages", {}).get("value", []) if isinstance(data, dict) else []
    return [p.get("url") for p in pages if p.get("url")][:max_results]


def search_tavily(query: str, key: str, max_results: int = 5) -> list[str]:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": max_results},
        timeout=30,
    )
    resp.raise_for_status()
    return [r.get("url") for r in resp.json().get("results", []) if r.get("url")][:max_results]


def search_web(query: str, provider: str = "duckduckgo", key: str = "", max_results: int = 5) -> list[str]:
    provider = (provider or "duckduckgo").lower()
    if provider == "bocha":
        return search_bocha(query, key, max_results)
    if provider == "tavily":
        return search_tavily(query, key, max_results)
    return search_duckduckgo(query, max_results)


# --------------------------------------------------------------------------- #
# 快照生成
# --------------------------------------------------------------------------- #
def build_snapshots(
    query: str,
    provider: str = "duckduckgo",
    key: str = "",
    max_results: int = 5,
    urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    """搜索 → 抓取 → 生成六键快照。抓取失败跳过，不伪造正文。"""
    target_urls = urls or search_web(query, provider=provider, key=key, max_results=max_results)
    # 官方站点优先、跳过博客/论坛
    target_urls = sorted(target_urls, key=_domain_rank)
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat()
    snapshots: list[dict[str, Any]] = []
    for url in target_urls:
        if _domain_rank(url) == 9:  # 博客/论坛等非官方来源跳过
            continue
        try:
            content = fetch_page(url)
            if not content.strip():
                continue
            source_id = "web-" + hashlib.sha256((url + content[:200]).encode("utf-8")).hexdigest()[:16]
            snapshots.append({
                "source_id": source_id,
                "url": url,
                "title": None,  # 未可靠取得标题时显式 null
                "content": content[:20000],
                "fetched_at": fetched_at,
                "published_date": None,  # 无法确认完整日期时为 null，不编造
            })
        except Exception:
            continue
    return snapshots
