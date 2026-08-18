"""错误码与业务异常（docs 03 §2.3 分段：400xx 请求 / 401xx 认证 / 403xx 权限 /
404xx 未找到 / 500xx 服务器 / 600xx Agent 运行时）。

0 成功；业务错误一般 HTTP 200 + envelope code；401xx/403xx 同时映射到对应 HTTP 状态（前端 http.ts 两者都处理）。
"""
from __future__ import annotations

# ---- 请求 400xx ----
ERR_PARAM_MISSING = 40001
ERR_FILE_TOO_LARGE = 40011
ERR_ATTACH_TYPE_UNSUPPORTED = 40012
ERR_DOCUMENT_TYPE_UNSUPPORTED = 40012  # KB 文档类型不受支持（与附件 40012 同码，别名语义）
ERR_DOMAIN_NOT_ALLOWED = 40013
ERR_INPUT_TOO_LONG = 40014

# ---- 进化闭环候选区 400xx（docs 03 §5.13）----
ERR_CANDIDATE_STATE_INVALID = 40020      # 状态迁移不允许
ERR_CANDIDATE_CARRIER_UNSUPPORTED = 40021  # 非 prompt 载体未实现
ERR_CANDIDATE_NO_CASES = 40022           # 无验证用例
ERR_AGENT_ROLLBACK_UNAVAILABLE = 40023   # 无可回滚版本

# ---- 认证 401xx ----
ERR_UNAUTHORIZED = 40101
ERR_TOKEN_EXPIRED = 40102
ERR_HOOK_TOKEN = 40103  # webhook x-hook-token 缺失/不匹配（docs 03 §5.10）

# ---- 权限 403xx ----
ERR_FORBIDDEN = 40301

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
ERR_PROVIDER_NOT_FOUND = 40418  # LLM Provider 不存在（docs 02 /settings）

# ---- 冲突 409xx ----
ERR_TASK_RUNNING = 40901
ERR_STATE_NOT_CANCELLABLE = 40902
ERR_TOOL_NAME_CONFLICT = 40903
ERR_MCP_NAME_CONFLICT = 40904
ERR_COLLECTION_NAME_CONFLICT = 40905
ERR_USERNAME_CONFLICT = 40906

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


class AppError(Exception):
    """业务错误：全局异常处理器统一转成 {code, message, data, trace_id} 信封。"""

    def __init__(self, code: int, message: str, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


def http_status_for(code: int) -> int:
    """401xx→401，403xx→403，其余业务错误→HTTP 200（信封承载 code）。"""
    if 40100 <= code < 40200:
        return 401
    if 40300 <= code < 40400:
        return 403
    return 200
