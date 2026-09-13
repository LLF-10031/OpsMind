"""判定两关模型（D20/D36/D47）。

第一关 · 确定性短路（永久不走 LLM）：
  exit≠0 → error · 超时 → timeout · 主机不可达 → host_unreachable · 空输出 → empty
  exit=0 且有效 → success → 进第二关
第二关 · LLM 判定（仅 success 有效时）：
  读 原始结果+规则文本 → {level: ok|warn|crit, reason}
report_type 与 level 正交：
  report_type 管渲染/AI介入方式；level 管严重度/颜色/是否触发深度诊断
"""
from __future__ import annotations

from typing import Any

from app.core.exceptions import JudgmentFailure
from app.core.limiter import limiter
from app.core.llm import get_default_llm
from app.core.logging import logger
from app.utils.safe_json import extract_json_from_text

REPORT_TYPES = ("success", "error", "timeout", "empty", "host_unreachable")
LEVELS = ("ok", "warn", "crit")


def first_gate(exit_code: int | None, timed_out: bool, has_output: bool) -> tuple[str, bool]:
    """第一关：返回 (report_type, 是否进入第二关)。

    - exit_code 非 0 / 超时 / 无输出 都在此短路（不调 LLM）。
    """
    if timed_out:
        return "timeout", False
    if exit_code is None:
        # 主机/执行服务不可达（外层标记 exit_code=None + timed_out=False 无法区分，
        # 由调用方在 run.attempts 里标 env_fail，这里保守归 success 会误判——
        # 因此约定：不可达时 exit_code 设为 None，本函数返回 host_unreachable）
        return "host_unreachable", False
    if exit_code != 0:
        return "error", False
    if not has_output:
        return "empty", False
    return "success", True


async def second_gate_llm(
    script_content: str,
    rule_text: str | None,
    raw_result: str,
    context_bundle: dict[str, Any] | None = None,
) -> dict:
    """第二关：LLM 判定 → {level, reason, metrics?}。

    仅 success 且有效输出时调用；受全局限流器约束。
    失败时抛 JudgmentFailure（上层降级 level=unknown + 模板兜底）。
    """
    rule = rule_text or "判断结果正常性：无明确规则时按输出是否健康判 ok/warn/crit"
    prompt = f"""你是运维巡检判定器。基于脚本输出判断严重程度。

【脚本/背景】
{context_bundle or {}}

【判定规则】
{rule}

【脚本原始输出（截断）】
{raw_result[:4000]}

只输出 JSON：{{"level": "ok|warn|crit", "reason": "一句话原因", "metrics": {{}}}}
metrics 为可选的键值数值（跟踪指标用），无则给空对象。
"""
    if not limiter.try_acquire_llm():
        raise JudgmentFailure("LLM 限流器繁忙，无法判定")
    try:
        llm = get_default_llm()
        resp = await llm.ainvoke(prompt)
        limiter.llm_success()
        text = resp.content if hasattr(resp, "content") else str(resp)
        parsed = extract_json_from_text(text)
        level = str(parsed.get("level", "unknown")).lower()
        if level not in LEVELS:
            level = "unknown"
        parsed["level"] = level
        return parsed
    except Exception as exc:
        limiter.llm_failure()
        logger.error(f"第二关判定失败: {exc}")
        raise JudgmentFailure(f"第二关判定失败: {exc}") from exc
    finally:
        limiter.release_llm()