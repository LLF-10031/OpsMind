"""目标机「脚本执行服务」：FastMCP Server（D13/D3）。

暴露 3 工具：ping / run_script / get_runtime_info。
- 解释器白名单：bash / python3
- 危险命令黑名单、超时 kill、受限账号（需宿主配合 sudoers）
- 只服务 localhost/内网（部署层保证；本文件不主动绑公网）
输出返回：{exit_code, stdout, stderr, duration}
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time

from fastmcp import FastMCP

mcp = FastMCP("opsmind-executor")

ALLOWED_INTERPRETERS = {
    "bash": ["/bin/bash", "bash"],
    "python3": ["/usr/bin/python3", "python3"],
}

DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bdd\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\b:\(\s*\|\s*&\s*curl\b"),  # fork-bomb-like pipe
    re.compile(r"\bmv\s+/\s"),
]
MAX_OUTPUT_BYTES = 2_000_000  # 2MB 截断上限（落盘由控制端决定，这里防内存爆）


def _check_dangerous(script: str) -> None:
    for pat in DANGEROUS_PATTERNS:
        if pat.search(script):
            raise PermissionError(f"脚本命中危险命令黑名单: {pat.pattern}")


def _run_blocking(shell: str, script: str, timeout: int) -> dict:
    if shell not in ALLOWED_INTERPRETERS:
        raise ValueError(f"不支持的解释器: {shell}（白名单: {list(ALLOWED_INTERPRETERS)}）")
    _check_dangerous(script)
    # 参数以 stdin 传入，避免拼接注入；解释器取候选路径中首个存在的
    candidates = ALLOWED_INTERPRETERS[shell]
    interp = next(p for p in candidates if os.path.exists(p))
    cmd = [interp]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout[:MAX_OUTPUT_BYTES]
        stderr = proc.stderr[:MAX_OUTPUT_BYTES]
        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": -1,
            "stdout": (exc.stdout or "")[:MAX_OUTPUT_BYTES],
            "stderr": (exc.stderr or "") + "\n[timeout] 执行超时被 kill",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "timed_out": True,
        }


@mcp.tool()
async def ping() -> dict:
    """连通性探测。"""
    return {"ok": True, "version": "0.1.0", "hostname": os.uname().nodename}


@mcp.tool()
async def run_script(
    script_id: str,
    content: str,
    timeout: int = 30,
    shell: str = "bash",
    env: dict | None = None,
) -> dict:
    """执行一段脚本（一次性快照），返回 {exit_code, stdout, stderr, duration_ms, timed_out}。

    入参：script_id 仅作审计标识；content 为脚本内容（每次下发不落盘）；
    shell 限制为 bash|python3；timeout 秒。返回结果由控制端判定。
    """
    # 兼容 Windows/无 os.uname 的开发环境
    return await asyncio.to_thread(_run_blocking, shell, content, timeout)


@mcp.tool()
async def get_runtime_info() -> dict:
    """目标机基础信息，供 AI 分析背景包。"""
    import platform

    info = {
        "hostname": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }
    try:
        uname = os.uname()
        info["uname"] = {
            "sysname": uname.sysname,
            "release": uname.release,
            "machine": uname.machine,
        }
    except Exception:
        pass
    return info


def main() -> None:  # pragma: no cover
    host = os.environ.get("OPSMIND_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("OPSMIND_PORT", "8003"))
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()