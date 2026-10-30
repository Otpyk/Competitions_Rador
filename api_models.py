"""后端接口模型：请求、响应、错误与任务状态。

说明：这是 A 维护的「后端接口模型」。竞赛的结构化数据模型（赛事字段）由 C 的
``schemas.py`` 负责，这里不另建一套含义冲突的竞赛字段，只描述研究服务的输入输出。
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
import re
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field


def _snapshot_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("fetched_at must be a timestamp with a UTC offset")
    return value


def _snapshot_date(value: Any) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    raise ValueError("published_date must be a complete YYYY-MM-DD date")


class ResearchStatus(str, Enum):
    """研究任务状态。失败/超时不得伪装成成功。"""

    success = "success"
    failed = "failed"
    timed_out = "timed_out"


class Source(BaseModel):
    """可追溯来源。"""

    title: str | None
    url: str
    snippet: Optional[str] = None
    source_id: Optional[str] = None
    content: Optional[str] = None
    fetched_at: Annotated[datetime, BeforeValidator(_snapshot_timestamp)] | None = None
    published_date: Annotated[date, BeforeValidator(_snapshot_date)] | None = None


class ResearchRequest(BaseModel):
    """初始研究请求（用户需求）。"""

    query: str = Field(..., min_length=1, description="研究问题 / 搜索查询")
    profile: Optional[dict[str, Any]] = Field(
        default=None,
        description="用户画像：专业、年级、兴趣、时间条件等",
    )
    report_type: Optional[str] = Field(default=None, description="报告类型，默认 research_report")


class SupplementarySearchRequest(BaseModel):
    """补充搜索请求（由 B 产生，A 负责执行）。

    示例（来自任务说明书 3.4，仅为接口示例）::

        {
          "action": "search",
          "task_id": "task-123",
          "contest_name": "某项竞赛",
          "target_fields": ["registration_deadline"],
          "query": "某项竞赛 官方 报名截止时间",
          "reason": "报名截止日期缺失",
          "round": 2
        }
    """

    action: Literal["search"] = "search"
    task_id: str = Field(..., min_length=1, description="所属任务标识")
    contest_name: str = Field(..., min_length=1, description="待补充的赛事或主题")
    target_fields: list[str] = Field(default_factory=list, description="需要补充的关键字段")
    query: str = Field(..., min_length=1, description="实际查询语句")
    reason: str = Field(default="", description="本次补充搜索的原因")
    round: int = Field(default=1, ge=1, description="当前搜索轮次")


class ResearchResult(BaseModel):
    """统一研究结果：报告 + 来源 + 状态 + 日志。

    报告与来源分开保存，来源在传递过程中不得无故丢失；失败时通过 status/error
    表达，不伪装为成功。
    """

    task_id: str
    status: ResearchStatus
    query: str
    report: str = ""
    sources: list[Source] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    engine: str = "mock"
    round: int = 1
    logs: list[dict[str, Any]] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """端到端搜索请求：用户需求 → 完整链路。"""

    query: str = Field(..., min_length=1)
    profile: Optional[dict[str, Any]] = None
    max_rounds: Optional[int] = Field(default=None, ge=1, le=10)


class PipelineStage(BaseModel):
    """链路中某个阶段的执行状态。"""

    name: str
    status: str  # ran | skipped | blocked | failed | not_integrated
    detail: Optional[Any] = None


class SearchResponse(BaseModel):
    """端到端搜索结果。competitions/recommendations 由 C 的模块填充。"""

    task_id: str
    status: str
    research: ResearchResult
    research_history: list[ResearchResult] = Field(default_factory=list)
    competitions: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: Optional[Any] = None
    stages: list[PipelineStage] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    engine: str
    version: str


class LibraryRecommendRequest(BaseModel):
    """比赛信息库推荐请求：按兴趣匹配学院推荐名单。"""

    interests: list[str] = Field(default_factory=list, description="兴趣标签")


class LibraryRecommendResponse(BaseModel):
    """比赛信息库推荐结果：命中竞赛（含类别/奖项/标签/详情补充状态）。"""

    matches: list[dict[str, Any]] = Field(default_factory=list)
    library_count: int = 0
    matched_count: int = 0
    note: str = ""


class ApiError(BaseModel):
    """统一错误响应结构。"""

    code: str
    message: str
    detail: Optional[Any] = None
