"""统一异常体系（D38/D48：错误分级，便于降级与审计）。"""
from __future__ import annotations


class OpsMindError(Exception):
    code = "OPSMIND_ERROR"
    message = "未知错误"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message


# --- 应用层 ---
class ConfigError(OpsMindError):
    code = "CONFIG_ERROR"


# --- 执行/工具层（D38） ---
class ToolCallInvalid(OpsMindError):
    code = "TOOL_CALL_INVALID"     # 入参校验失败（LLM 自纠后仍超限）


class ToolExecError(OpsMindError):
    code = "TOOL_EXEC_ERROR"       # 工具执行失败（重试后仍失败）


class ToolBlocked(OpsMindError):
    code = "TOOL_BLOCKED"          # 安全级别拒绝（只读等）


class DegradedExecution(OpsMindError):
    """整步降级（如目标机不可达），调用方按 report_type 处理。"""

    code = "DEGRADED_EXECUTION"


# --- 依赖层 ---
class DependencyUnavailable(OpsMindError):
    code = "DEP_UNAVAILABLE"


class LLMRateLimited(OpsMindError):
    code = "LLM_RATE_LIMITED"


# --- 判定/报告层 ---
class JudgmentFailure(OpsMindError):
    code = "JUDGMENT_FAILURE"


class ReportStageError(OpsMindError):
    code = "REPORT_STAGE_ERROR"