"""审计（D48 横切点）：助手对话 / 报告分析 / 异常联动诊断 的工具调用+降级+注入拦截 记录。

单实例下落到结构化日志；生产可扩展为审计表。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.logging import logger


def audit(
    scope: str,          # "chat" | "report" | "diagnosis"
    action: str,         # "tool_call" | "degradation" | "injection_blocked"
    detail: dict[str, Any] | None = None,
) -> None:
    """写一条审计记录（D48）。"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "action": action,
        "detail": detail or {},
    }
    try:
        logger.info(f"AUDIT {scope}/{action} {json.dumps(entry, ensure_ascii=False)}")
    except Exception:  # noqa: BLE001
        logger.info(f"AUDIT {scope}/{action} {detail!r}")


def audit_tool_call(scope: str, tool: str, args: dict, ok: bool, note: str | None = None) -> None:
    audit(scope, "tool_call", {"tool": tool, "args": _sanitize(args), "ok": ok, "note": note})


def audit_degradation(scope: str, tool_or_step: str, reason: str, degraded_to: str) -> None:
    audit(scope, "degradation", {"step": tool_or_step, "why": reason, "degraded_to": degraded_to})


def audit_injection_blocked(scope: str, source: str, detail: str | None = None) -> None:
    audit(scope, "injection_blocked", {"source": source, "detail": detail})


def _sanitize(args: dict) -> dict:
    """脱敏：避免 key/password 入审计。"""
    out = dict(args)
    for k in ("api_key", "password", "auth_key", "token"):
        if k in out:
            out[k] = "****"
    return out