"""上下文压缩（D43 终稿）：预算 / 触发 / 摘要生成与持久化。

模型：同一会话内，喂给 LLM 的内容 = 系统提示(恒定) + 对话摘要 + 最近 N 轮 + 本轮。
预算 = ctx − max_output(本次) − reserved；reserved = min(10000, ctx×20%)。
触发：组装完本轮完整输入后 估算 ≥ 预算×80% → 先压缩；≥ 预算 → 必须压缩。
摘要由"轻任务模型"生成；固定分区 + 增量压缩；summary_cap = clamp(预算×20%, 800, 4000)。
usage 校准由调用方读取 usage.prompt_tokens 回写。
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable

from app.configs.settings import get_settings
from app.core.llm import get_light_llm
from app.core.logging import logger

# embedding 函数注入（避免循环导入）：embed_query_fn(query)->list[float]
embed_query_fn: Callable[[str], list[float]] | None = None

# summary 持久化回调：save_summary(session_id, summary_text) 替换 DB 读写
summary_store: dict[str, str] = {}


def budget_of(context_len: int, max_output: int) -> tuple[int, int]:
    """返回 (budget, reserved)。ctx_len 来自能力表（默认 32k）。"""
    s = get_settings()
    reserved = min(s.context_reserved, int(context_len * 0.2))
    return context_len - max_output - reserved, reserved


def should_trigger(est_tokens: int, budget: int) -> bool:
    s = get_settings()
    return est_tokens >= int(budget * s.context_trigger_ratio)


def _estimate_tokens(text: str) -> int:
    """字符粗估（D43：usage 校准在回包后校准，这里只求够准）。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 1.5 + (len(text) - cjk) * 0.3)


async def generate_summary(
    system_prompt: str,
    summary_before: str,
    recent_turns: list[str],
) -> str:
    """轻模型生成/更新摘要（固定分区：用户目标/关键事实/已给结论/悬而未决）。"""
    llm = get_light_llm()
    prompt = f"""请把对话压缩为结构化摘要，保留关键信息。

分区要求：
- 用户目标/需求（进行中）
- 关键事实/参数/数字
- 已给出的答案/结论（含引用来源）
- 悬而未决事项（待确认/未解）

【之前的摘要】
{summary_before or "（无）"}

【新增对话轮次】
{chr(10).join(recent_turns[-10:])}

只输出压缩摘要正文，不要额外说明。"""
    try:
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        cap = _summary_cap()
        if len(text) > cap:
            text = text[:cap]  # 简易截断；真超限走"摘要再压缩"
        return str(text).strip()
    except Exception as exc:
        logger.warning(f"摘要生成失败: {exc}")
        return summary_before or ""


def _summary_cap() -> int:
    s = get_settings()
    budget, _ = budget_of(32000, 4096)
    cap = int(budget * 0.2)
    return max(s.summary_cap_min, min(cap, s.summary_cap_max))


def assemble_context(
    system_prompt: str,
    summary: str,
    recent_turns: list[str],
    new_message: str,
    max_output: int = 4096,
) -> dict[str, Any]:
    """组装本轮输入 + token 估算。返回 {context_text, est_tokens, budget, trigger}。"""
    ctx_len = 32000  # 能力表查取；此处先固定默认，切模型时由调用方重建
    budget, _ = budget_of(ctx_len, max_output)
    parts = [system_prompt, summary, *recent_turns[-10:], new_message]
    context_text = "\n\n".join(parts)
    est = _estimate_tokens(context_text)
    return {
        "context_text": context_text,
        "est_tokens": est,
        "budget": budget,
        "trigger": should_trigger(est, budget),
        "summary": summary,
    }


async def compact_session(system_prompt: str, summary: str, recent_turns: list[str]) -> str:
    """压缩：把旧轮生成/更新摘要，返回新摘要。"""
    new_sum = await generate_summary(system_prompt, summary, recent_turns)
    return new_sum