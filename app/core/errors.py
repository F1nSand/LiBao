"""错误码与业务异常（《02》接口契约 §2.3 分段：400xx 请求 / 401xx 认证 / 403xx 权限 /
404xx 未找到 / 500xx 服务器 / 600xx Agent 运行时）。

0 成功；业务错误一般 HTTP 200 + envelope code；401xx/403xx 同时映射到对应 HTTP 状态（前端 http.ts 两者都处理）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

# ---- 请求 400xx ----
ERR_PARAM_MISSING = 40001
ERR_FILE_TOO_LARGE = 40011
ERR_ATTACH_TYPE_UNSUPPORTED = 40012
ERR_DOCUMENT_TYPE_UNSUPPORTED = 40012  # KB 文档类型不受支持（与附件 40012 同码，别名语义）
ERR_DOMAIN_NOT_ALLOWED = 40013
ERR_INPUT_TOO_LONG = 40014
ERR_WORKSPACE_FILE_REF_INVALID = 40015  # 工作区文件引用非法或不可读取（不泄露路径状态）

# ---- 进化闭环候选区 400xx（《02》接口契约 §5.13）----
ERR_CANDIDATE_STATE_INVALID = 40020      # 状态迁移不允许
ERR_CANDIDATE_CARRIER_UNSUPPORTED = 40021  # 非 prompt 载体未实现
ERR_CANDIDATE_NO_CASES = 40022           # 无验证用例
ERR_AGENT_ROLLBACK_UNAVAILABLE = 40023   # 无可回滚版本
ERR_SKILL_INVALID = 40024                # SKILL.md 格式非法（缺 frontmatter/name/description）

# ---- 认证 401xx ----
ERR_UNAUTHORIZED = 40101
ERR_TOKEN_EXPIRED = 40102
ERR_HOOK_TOKEN = 40103  # webhook x-hook-token 缺失/不匹配（《02》接口契约 §5.10）

# ---- 权限 403xx ----
ERR_FORBIDDEN = 40301
ERR_WORKSPACE_PATH_FORBIDDEN = 40302  # 路径越出工作区范围（《02》后端设计 §7.8）

# ---- 未找到 404xx ----
ERR_CONVERSATION_NOT_FOUND = 40401
ERR_TASK_NOT_FOUND = 40402
ERR_ATTACHMENT_NOT_FOUND = 40403
ERR_AGENT_NOT_FOUND = 40404
ERR_TOOL_NOT_FOUND = 40405
ERR_MCP_SERVER_NOT_FOUND = 40406
ERR_COLLECTION_NOT_FOUND = 40407
ERR_DOCUMENT_NOT_FOUND = 40408
ERR_MEMORY_NOT_FOUND = 40409
ERR_NOTIFICATION_NOT_FOUND = 40410
ERR_USER_NOT_FOUND = 40411
ERR_EVAL_SET_NOT_FOUND = 40412
ERR_EVAL_CASE_NOT_FOUND = 40413
ERR_EVAL_RUN_NOT_FOUND = 40414
ERR_WORKSPACE_NOT_FOUND = 40416
ERR_PROVIDER_NOT_FOUND = 40418  # LLM Provider 不存在（《02》前端设计 /settings）

# ---- 冲突 409xx ----
ERR_TASK_RUNNING = 40901
ERR_STATE_NOT_CANCELLABLE = 40902
ERR_TOOL_NAME_CONFLICT = 40903
ERR_MCP_NAME_CONFLICT = 40904
ERR_COLLECTION_NAME_CONFLICT = 40905
ERR_USERNAME_CONFLICT = 40906
ERR_WORKSPACE_NAME_CONFLICT = 40908
ERR_CONVERSATION_WORKSPACE_CONFLICT = 40909

# ---- 限流 429xx ----
ERR_RATE_LIMITED = 42901

# ---- 服务器 500xx ----
ERR_INTERNAL = 50001
ERR_ATTACH_STORAGE_FAILURE = 50002
ERR_MCP_CONNECT = 50201

# ---- Agent 运行时 600xx ----
ERR_LLM_FAILURE = 60001
ERR_TOOL_FAILURE = 60002
ERR_CIRCUIT_BREAK = 60003
ERR_ATTACH_ANALYSIS_FAILURE = 60004
ERR_MULTIMODAL_UNSUPPORTED = 60005  # 当前 endpoint 明确拒绝图片输入
ERR_SANDBOX_UNAVAILABLE = 60006  # 选择的 shell/docker 后端不可用
ERR_CHECKPOINT_INVALID = 60007  # 断点损坏或无法安全解码
ERR_LLM_TRANSPORT = 60008  # 模型流式连接中断，可从失败节点恢复
ERR_TASK_PROCESS_INTERRUPTED = 60009  # 服务进程重启导致任务中断


class LLMFailureKind(StrEnum):
    """模型边界错误分类；只有 transport 允许节点级恢复。"""

    TRANSPORT = "llm_transport"
    CONTEXT_LENGTH = "context_length"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN = "unknown"


class AppError(Exception):
    """业务错误：全局异常处理器统一转成 {code, message, data, trace_id} 信封。"""

    def __init__(
        self,
        code: int,
        message: str,
        retryable: bool = False,
        *,
        kind: str | None = None,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.kind = kind
        self.recoverable = recoverable
        self.details = details or {}
        super().__init__(message)


class LLMTransportError(AppError):
    """模型流式连接中断；只允许在 agent_execute 节点边界重跑。"""

    def __init__(self, *, model: str, details: dict[str, Any] | None = None) -> None:
        safe_details = _safe_llm_details(model=model, details=details or {})
        super().__init__(
            ERR_LLM_TRANSPORT,
            "模型流式连接中断，可从最近断点继续",
            retryable=True,
            kind=LLMFailureKind.TRANSPORT.value,
            recoverable=True,
            details=safe_details,
        )


_TRANSPORT_TEXT = (
    "incomplete chunked read",
    "peer closed",
    "no streaming chunk received",
    "remote protocol",
    "read timed out",
    "connection reset",
    "connection aborted",
)
_CONTEXT_TEXT = (
    "maximum context",
    "context length",
    "too many tokens",
    "prompt is too long",
    "上下文长度",
    "上下文超限",
)


def classify_llm_exception(exc: Exception) -> LLMFailureKind:
    """以异常链、状态码和稳定关键词分类，不把任意 5xx/文本当作可恢复传输错误。"""

    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__

    statuses: list[int] = []
    for item in chain:
        response = getattr(item, "response", None)
        for candidate in (getattr(item, "status_code", None), getattr(response, "status_code", None)):
            if isinstance(candidate, int):
                statuses.append(candidate)
    if any(status in (401, 403) for status in statuses):
        return LLMFailureKind.AUTHENTICATION
    if 429 in statuses:
        return LLMFailureKind.RATE_LIMIT

    names = " ".join(type(item).__name__.lower() for item in chain)
    text = " ".join(str(item).lower()[:4000] for item in chain)
    if any(marker in text for marker in _CONTEXT_TEXT):
        return LLMFailureKind.CONTEXT_LENGTH
    if any(marker in names for marker in ("authentication", "permission", "unauthorized")):
        return LLMFailureKind.AUTHENTICATION
    if any(marker in text for marker in ("invalid request", "invalid_parameter", "bad request", "参数有误")):
        return LLMFailureKind.INVALID_REQUEST
    if any(marker in text for marker in _TRANSPORT_TEXT) or any(
        marker in names for marker in ("remoteprotocol", "readtimeout", "connecterror", "apiconnection", "apitimeout")
    ):
        return LLMFailureKind.TRANSPORT
    return LLMFailureKind.UNKNOWN


def _safe_llm_details(*, model: str, details: dict[str, Any]) -> dict[str, Any]:
    """只保留可观测数字/枚举字段，避免错误载荷携带请求正文或凭证。"""

    allowed = {
        "chunks_received",
        "text_chars",
        "reasoning_chars",
        "attempt",
        "max_attempts",
        "idle_seconds",
        "last_chunk_age_ms",
        "elapsed_ms",
        "context_metrics",
    }
    safe: dict[str, Any] = {"model": str(model)[:128]}
    for key in allowed:
        value = details.get(key)
        if key == "context_metrics" and isinstance(value, dict):
            safe[key] = {
                name: value[name]
                for name in (
                    "message_count",
                    "text_chars",
                    "tool_schema_chars",
                    "image_count",
                    "document_chars",
                    "estimated_prompt_tokens",
                    "estimated",
                    "estimate_method",
                )
                if name in value
            }
        elif isinstance(value, (int, float, bool, str)):
            safe[key] = value
    return safe


def normalize_llm_exception(
    exc: Exception,
    *,
    model: str,
    context_metrics: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> AppError:
    """将底层异常转换为不泄露原始响应的业务错误。"""

    kind = classify_llm_exception(exc)
    safe_details = _safe_llm_details(model=model, details={**(details or {}), "context_metrics": context_metrics or {}})
    if kind is LLMFailureKind.TRANSPORT:
        return LLMTransportError(model=model, details=safe_details)
    message = {
        LLMFailureKind.CONTEXT_LENGTH: "模型请求超过接口上下文限制",
        LLMFailureKind.AUTHENTICATION: "模型接口认证失败",
        LLMFailureKind.RATE_LIMIT: "模型接口触发限流",
        LLMFailureKind.INVALID_REQUEST: "模型接口拒绝了请求参数",
    }.get(kind, "模型调用失败")
    return AppError(
        ERR_LLM_FAILURE,
        message,
        retryable=False,
        kind=kind.value,
        recoverable=False,
        details=safe_details,
    )


def http_status_for(code: int) -> int:
    """401xx→401，403xx→403，其余业务错误→HTTP 200（信封承载 code）。"""
    if 40100 <= code < 40200:
        return 401
    if 40300 <= code < 40400:
        return 403
    return 200
