"""助手对话图（LangGraph，D47/D42/D44）。

节点：注入检测 → 组装上下文(context.py) → 工具循环(ToolRegistry + D38 闭环+降级透明)
     → 生成回答(SSE) → 输出敏感打码(D48) → O4 校验 → 落库/记忆挂钩。

骨架版：先实现"组装→工具循环(纯函数)→生成→校验"的可跑图；
真实 LLM/工具由 service 层注入，避免重依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.context import assemble_context
from app.services.validation import run_pipeline


@dataclass
class ChatState:
    session_id: str = ""
    system_prompt: str = ""
    summary: str = ""
    recent_turns: list[str] = field(default_factory=list)
    user_message: str = ""
    context_text: str = ""
    est_tokens: int = 0
    tool_results: list[dict] = field(default_factory=list)
    reply: str = ""
    annotations: list[dict] = field(default_factory=list)
    ok: bool = True


def build_graph(
    tool_runner: Callable[[ChatState, str, dict], Any],
    answer_generator: Callable[[ChatState], str] | None = None,
) -> Callable[[ChatState], ChatState]:
    """构造可用的对话函数（简单顺序编排，LangGraph StateGraph 由实配版接入）。

    - tool_runner：工具循环（支持 async/同步），回调可加；无则走骨架 echo
    - answer_generator：可选，基于 state 生成最终回答（如 LLM + 检索结果）
    """
    async def run(state: ChatState) -> ChatState:
        # 1. 组装上下文（D43）
        ctx = assemble_context(
            state.system_prompt,
            state.summary,
            state.recent_turns,
            state.user_message,
        )
        state.context_text = ctx["context_text"]
        state.est_tokens = ctx["est_tokens"]

        # 2. 工具循环（支持 async tool_runner；同步亦兼容）
        try:
            tool_result = tool_runner(state, "assistant_loop", {"message": state.user_message})
            if hasattr(tool_result, "__await__"):
                tool_result = await tool_result
        except Exception as exc:  # noqa: BLE001
            tool_result = {"error": str(exc)}
        state.tool_results.append(tool_result or {})

        # 3. 生成回答（优先 answer_generator；否则回显工具结果；骨架用 tool_result）
        try:
            if answer_generator is not None:
                gen = answer_generator(state)
                if hasattr(gen, "__await__"):
                    gen = await gen
                state.reply = str(gen) if gen else "（骨架）"
            else:
                state.reply = str(tool_result) if tool_result else "（骨架）"
        except Exception as exc:  # noqa: BLE001
            state.reply = f"（回答生成失败: {exc}）"

        # 4. 输出敏感打码 + O4 校验（D48/D45）
        from app.services.report import mask_sensitive

        state.reply = mask_sensitive(state.reply)
        state.annotations = run_pipeline(
            state.reply, "ok", has_error_keyword=False, enabled=None
        )
        return state

    return lambda state: run(state)


# 可注入的检索器：query -> str | Awaitable[str]（供对话图默认接 search_kb）
RETRIEVER: Callable[[str], Any] | None = None


def set_retriever(fn: Callable[[str], Any]) -> None:
    """注入 search_kb 检索器（实际接 knowledge.search）。"""
    global RETRIEVER
    RETRIEVER = fn


async def _default_runner_with_kb(state: ChatState, tool: str, args: dict) -> Any:
    """默认工具循环：有检索器则总是走 KB 检索（勾选才查由 retriever 内判断）。"""
    message = str(args.get("message", state.user_message))
    if RETRIEVER is not None:
        try:
            res = RETRIEVER(message)
            if hasattr(res, "__await__"):
                res = await res
            return {"tool": "search_kb", "result": res}
        except Exception as exc:  # noqa: BLE001
            return {"tool": "search_kb", "error": str(exc), "result": "（检索失败）"}
    return {"tool": "assistant_loop", "echo": message}


def create_assistant_graph():
    """轻量工厂：返回 run-assistant 可调用（默认接 KB 检索，未注入则 echo）。"""
    return build_graph(_default_runner_with_kb)