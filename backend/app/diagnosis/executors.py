"""诊断 Executor：确定性只读探针采集（D47 调整点#2）。

三个 Executor 各下发一段"只读探针脚本"到目标机执行，采集证据写各自格子。
用 run_script 通道实现，无需给执行服务新增专用工具；探针均为只读、幂等。
"""
from __future__ import annotations

from typing import Any, Callable

from app.core.logging import logger

# 只读探针（bash）；不含危险命令（执行服务有黑名单）
LOG_PROBE = r"""
echo "== 最近日志中的异常关键字 =="
grep -iErE 'error|fail|refused|timeout|exception|panic' /var/log 2>/dev/null | tail -20
echo "== /var/log 最近文件 =="
ls -lt /var/log 2>/dev/null | head -5
"""

METRIC_PROBE = r"""
echo "== uptime =="; uptime 2>/dev/null
echo "== memory =="; free -m 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -5
echo "== disk =="; df -h 2>/dev/null
echo "== top cpu =="; ps -eo pid,pcpu,pmem,comm --sort=-pcpu 2>/dev/null | head -8
"""

CHANGE_PROBE = r"""
echo "== containers =="; docker ps --format '{{.Names}} {{.Status}} {{.Image}} {{.CreatedAt}}' 2>/dev/null
echo "== recently modified files(2h) =="; find /etc /opt /app -maxdepth 2 -type f -mmin -120 2>/dev/null | head -20
"""

PROBES: dict[str, str] = {
    "log": LOG_PROBE,
    "metric": METRIC_PROBE,
    "change": CHANGE_PROBE,
}

# 采集函数可注入（测试替换）：collect(executor, endpoint, auth_key, timeout) -> dict 证据
CollectFn = Callable[[str, str, str, float], Any]


async def default_collect(executor: str, endpoint: str, auth_key: str, timeout: float = 20.0) -> dict:
    """默认采集：经 MCP run_script 下发只读探针，返回结构化证据。"""
    from app.executor.mcp_client import call_host

    content = PROBES[executor]
    try:
        res = await call_host(
            endpoint,
            "run_script",
            {"script_id": f"diag:{executor}", "content": content, "timeout": int(timeout), "shell": "bash"},
            auth_key,
            timeout + 10,
        )
        return {
            "executor": executor,
            "exit_code": res.get("exit_code"),
            "stdout": (res.get("stdout") or "")[:4000],
            "stderr": (res.get("stderr") or "")[:1000],
            "duration_ms": res.get("duration_ms"),
        }
    except Exception as exc:  # noqa: BLE001 采集失败 → 降级为空证据（透明记录）
        logger.warning(f"诊断采集失败 {executor}: {exc}")
        return {"executor": executor, "error": str(exc)}
