"""Small DeepSeek JSON client; credentials never enter logs or run receipts."""

from dataclasses import dataclass, field
from http.client import HTTPException
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .validation import ContractError


@dataclass
class DeepSeekCompletion:
    api_key: str = field(repr=False)
    model: str = "deepseek-flash"
    timeout: float = 180
    calls: list[dict] = field(default_factory=list, init=False)

    def __post_init__(self):
        if not self.api_key.strip():
            raise ValueError("缺少 DEEPSEEK_API_KEY")

    def __call__(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model, "messages": messages,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}, "temperature": 0,
            "max_tokens": 12000, "stream": False,
        }
        request = Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key.strip(),
                     "Content-Type": "application/json"}, method="POST",
        )
        started = time.monotonic()
        entry = {"provider": "deepseek", "requested_model": self.model,
                 "thinking_enabled": False, "status": "failed", "usage": None, "cost": None,
                 "retryable": False}
        self.calls.append(entry)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            if not isinstance(raw, dict):
                raise ContractError("DeepSeek API 响应结构无效")
            choices = raw.get("choices", [])
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ContractError("DeepSeek API 响应结构无效")
            entry.update(response_id=raw.get("id"), returned_model=raw.get("model"),
                         usage=raw.get("usage"), finish_reason=choices[0].get("finish_reason"))
            if choices[0].get("finish_reason") != "stop":
                raise ContractError("DeepSeek 未完整生成结果，不能采用截断或中止的JSON")
            message = choices[0].get("message", {})
            if not isinstance(message, dict):
                raise ContractError("DeepSeek API 响应结构无效")
            content = message.get("content")
            if message.get("tool_calls") or not isinstance(content, str) or not content.strip():
                raise ContractError("DeepSeek 未返回非空JSON文本")
            entry["status"] = "success"
            return content
        except HTTPError as exc:
            entry["http_status"] = exc.code
            entry["retryable"] = exc.code == 429 or 500 <= exc.code < 600
            raise ContractError(f"DeepSeek API HTTP {exc.code}；请检查账户、模型和凭据配置") from None
        except (URLError, TimeoutError, OSError, HTTPException):
            entry["retryable"] = True
            raise ContractError("DeepSeek 网络连接失败或超时；未采用任何抽取结果") from None
        except ContractError:
            raise
        except (ValueError, KeyError, TypeError):
            raise ContractError("DeepSeek API 响应结构无效") from None
        finally:
            entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
