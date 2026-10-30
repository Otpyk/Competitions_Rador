"""应用配置：通过环境变量 / .env 管理，绝不把真实密钥写入代码。

成员 A 负责统一配置入口。真实 GPT Researcher 引擎会直接读取进程环境变量里的
``OPENAI_API_KEY`` / ``TAVILY_API_KEY`` 等凭证，因此这里先 ``load_dotenv()``
把 ``.env`` 内容注入 ``os.environ``，让第三方库也能读到。
"""
from __future__ import annotations

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# 把 .env 的内容载入进程环境变量（幂等；真实环境变量优先级更高）。
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 研究服务 ----
    # auto：安装了 gpt-researcher 且配置了 LLM Key 时用真实引擎，否则回退 mock。
    # mock：离线样例，不访问外部服务。
    # gpt_researcher：强制使用真实引擎（未安装/未配置会明确报错）。
    researcher_mode: str = "auto"
    researcher_report_type: str = "research_report"
    researcher_timeout_seconds: float = 300.0
    max_search_rounds: int = 2

    # ---- 运行与日志 ----
    app_name: str = "Competition Radar"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # ---- 真实 GPT Researcher 需要的凭证（占位；不填则回退 mock）----
    openai_api_key: str = ""
    tavily_api_key: str = ""
    llm_provider: str = "openai"

    # ---- 国产模型（全链路国产化；填 key 即切换真实抽取，不填走离线规则/规范候选）----
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com/chat/completions"
    # 是否用 DeepSeek 真实抽取（模型日期推断等质量问题会触发 C 的严格校验而回退规范候选）
    use_real_extraction: bool = False

    # ---- 联网搜索（抓正文已可用；搜索后端需 key）----
    # bocha（国产，推荐）/ tavily / duckduckgo（免 key 但较脆弱）
    search_provider: str = "bocha"
    bocha_api_key: str = ""
    tavily_api_key: str = ""
    search_max_results: int = 5

    # ---- 用户身份（用于过滤外校校赛：只推荐本校可参加的比赛）----
    user_school: str = "华南师范大学"

    @property
    def search_api_key(self) -> str:
        """按 search_provider 取对应搜索 key。"""
        return self.tavily_api_key if self.search_provider == "tavily" else self.bocha_api_key

    @property
    def has_llm_key(self) -> bool:
        """是否配置了可供真实引擎使用的 LLM 凭证。"""
        return bool(self.openai_api_key.strip() or self.deepseek_api_key.strip())

    @property
    def has_domestic_key(self) -> bool:
        """是否配置了国产模型凭证（用于真实 31 字段抽取）。"""
        return bool(self.deepseek_api_key.strip())

    @property
    def use_mock(self) -> bool:
        return self.researcher_mode.lower() == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
