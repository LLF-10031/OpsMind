"""控制端 MCP client（经 SSH 隧道连目标机执行服务）。

D13：控制端经隧道访问 localhost:8003 -> 目标机 FastMCP 执行服务。
D38：工具调用统一走"入参校验/重试/降级/透明"闭环（此处为执行服务的直接调用）。

实现选择：直接走 streamable-http JSON-RPC（协议级），
避免为"自建执行服务"引入 langchain-mcp-adapters 的进程/双端复杂度；
单机 + 隧道环境下可控性更好。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import ToolExecError
from app.core.logging import logger


async def call_host(
    endpoint: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    auth_key: str = "",
    timeout: float = 60.0,
    retries: int = 3,
) -> dict:
    """调用目标机执行服务工具，带有限重试（仅对幂等操作安全）。

    - retries：3 次指数退避（1s/2s/4s），只用于 ping/get_runtime_info 等只读幂等调用。
    - run_script 为一次性快照，重试需由上层（静默重试 O1b）控制，本函数默认 1 次。
    """
    arguments = arguments or {}
    actual_retries = retries if tool != "run_script" else 1
    last_err: Exception | None = None
    for attempt in range(1, actual_retries + 1):
        try:
            return await _call_host_once(endpoint, tool, arguments, auth_key, timeout)
        except ToolExecError as exc:
            last_err = exc
            logger.warning(f"{tool} 第 {attempt}/{actual_retries} 次失败: {exc}")
            if attempt < actual_retries:
                import asyncio

                await asyncio.sleep(2 ** attempt)
    raise ToolExecError(f"目标机工具 {tool} 调用失败（重试 {actual_retries} 次）: {last_err}")


def _mcp_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/mcp"):
        base = base[: -len("/mcp")]
    return base + "/mcp"  # FastMCP streamable-http 挂载点


def _parse_sse(text: str) -> dict:
    """解析 streamable-http 的 SSE 响应体（event/data 行）。"""
    import json

    data_lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        raise ValueError("SSE 响应中无 data 帧")
    return json.loads("\n".join(data_lines))


async def _call_host_once(
    endpoint: str,
    tool: str,
    arguments: dict[str, Any],
    auth_key: str,
    timeout: float,
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"
    url = _mcp_url(endpoint)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            # 1) 握手：initialize -> 拿会话 id
            init = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "opsmind-controller", "version": "0.1.0"},
                },
                "id": 1,
            }
            handshake = await c.post(url, json=init, headers=headers)
            handshake.raise_for_status()
            sid = handshake.headers.get("mcp-session-id")
            if not sid:
                raise ValueError("initialize 未返回 mcp-session-id")

            session_headers = dict(headers)
            session_headers["Mcp-Session-Id"] = sid
            # 2) 工具调用
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
                "id": 2,
            }
            call = await c.post(url, json=payload, headers=session_headers)
            call.raise_for_status()
            data = _parse_sse(call.text)
            # 3) 释放会话
            try:
                await c.delete(url, headers=session_headers)
            except Exception:
                pass
    except Exception as exc:
        raise ToolExecError(f"目标机连接/执行网络失败: {exc}") from exc

    if "error" in data:
        raise ToolExecError(f"目标机工具 {tool} 返回错误: {data['error']}")

    # 解析 content[] -> 文本聚合
    result = data.get("result", {})
    content = result.get("content", [])
    if result.get("isError"):
        raise ToolExecError(f"目标机工具 {tool} 执行出错: {content}")
    text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    text = "\n".join(text_parts)
    try:
        import json

        return json.loads(text)  # 执行服务返回结构化 JSON
    except Exception:
        return {"raw": text}