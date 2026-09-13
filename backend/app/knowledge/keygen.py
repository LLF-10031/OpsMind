"""key 生成（D41/D43）：对 unit 用轻任务模型生成检索 key（问法/别名/错误码锚词）。

- 一个 unit 多个 key，key 打平行（key_index）。
- 主路径：`agenerate_keys(unit)` —— async，直接 await LLM（避免线程+asyncio.run 的组合坑）。
- 同步兜底：`light_keygen(unit)` 保留，但仅作非 async 环境降级；`kb_service` 应改走 async。
- 失败降级：标题/首句切片（保底可检索）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from app.core.logging import logger

KEYGEN_FN: Callable[..., Any] | None = None  # 可注入：fn(unit) -> list[str] | Awaitable[list[str]]


def set_keygen(fn: Callable[..., Any]) -> None:
    """注入 keygen: fn(unit) -> list[str] | Awaitable[list[str]]"""
    global KEYGEN_FN
    KEYGEN_FN = fn


def fallback_keys(value: str, parent_context: str) -> list[str]:
    """降级：无 LLM 时用"标题 + 首句"作 key，保底可检索。"""
    keys = []
    heading = parent_context.split(" → ")[-1] if parent_context else ""
    if heading:
        keys.append(heading)
    first_line = value.strip().splitlines()[0][:50] if value.strip() else ""
    if first_line and first_line not in keys:
        keys.append(first_line)
    cleaned = [re.sub(r"[\s：#*]+", "", k).strip() for k in keys]
    return [k for k in cleaned if k][:5]


def _extract_keys_from_text(text: str) -> list[str]:
    """健壮地从 LLM 文本提取 JSON 列表。

    - ```json ... ```  代码块
    - 以 '[' 开头的 JSON 列表
    - 逐行 `- xxx` 或 `"xxx",` 或 `xxx、` 拆分
    """
    if not text:
        return []
    raw = text.strip()
    # 1) ```json ... ```
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    # 2) 找到 [ ... ]
    s, e = raw.find("["), raw.rfind("]")
    if 0 <= s < e:
        try:
            parsed = json.loads(raw[s : e + 1])
            if isinstance(parsed, list):
                return [str(k).strip() for k in parsed if str(k).strip()]
        except Exception:  # noqa: BLE001
            pass
    # 3) 逐行拆分（兼容 LLM 输出为分行文本）
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-#*•　").strip()
        line = re.sub(r"^[\"']|[\"']$", "", line)
        line = re.sub(r"[,，。;；]+$", "", line)
        if line and line not in out:
            out.append(line)
    return out[:5]


async def _light_keygen_async(unit: dict[str, Any]) -> list[str]:
    """用轻任务模型为 unit 生成检索 key。输出最多 5 个；失败/无结果返回 []。"""
    from app.core.llm import get_light_llm

    value = unit.get("value", "")[:1500]
    parent = unit.get("parent_context", "")
    llm = get_light_llm()
    prompt = (
        f"这是一个运维知识片段。请生成 1~5 个用户/AI 可能用来检索它的短问句或关键词（含错误码、别名），用于向量/关键词检索。\n"
        f"【所在章节】{parent}\n【内容】{value}\n"
        f"只输出一个 JSON 字符串数组，如 [\"cpu 高怎么办\",\"cpu85\",\"高cpu处理\"]，不要任何额外解释或前言。"
    )
    try:
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        keys = _extract_keys_from_text(str(text))
        if not keys:
            logger.warning(f"keygen 提取为空，原文: {str(text)[:300]}")
        return keys
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"LLM keygen 调用失败: {exc}")
        return []


async def agenerate_keys(unit: dict[str, Any]) -> list[str]:
    """async 主路径：await KEYGEN_FN 或走内置轻模型。失败降级 fallback。"""
    if KEYGEN_FN is not None:
        try:
            out = KEYGEN_FN(unit)
            if isinstance(out, Awaitable):
                out = await out
            if isinstance(out, list) and out:
                return [str(k).strip() for k in out if str(k).strip()][:5]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"key 生成失败，走降级: {exc}")
        # KEYGEN 存在但失败 → 空，继续走内置轻模型再兜底
    try:
        out = await _light_keygen_async(unit)
        if out:
            return out
    except Exception:  # noqa: BLE001
        pass
    return fallback_keys(unit.get("value", ""), unit.get("parent_context", ""))


def light_keygen(unit: dict[str, Any]) -> list[str]:
    """同步 wrapper（非 async 环境降级用）。kb_service 优先走 agenerate_keys。"""
    import asyncio

    try:
        return asyncio.run(agenerate_keys(unit))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"light_keygen sync 失败: {exc}")
    return fallback_keys(unit.get("value", ""), unit.get("parent_context", ""))


def auto_setup_keygen() -> None:
    """若配置了 API key，则启用 LLM keygen（否则维持 fallback）。

    注入 async 函数（`_light_keygen_async`），供 `agenerate_keys` await 调用；
    `light_keygen`(sync) 仅在无 async 环境下作最后兜底，不注入。
    """
    try:
        from app.configs.settings import settings

        if settings.openai_api_key or settings.docproc_api_key:
            set_keygen(_light_keygen_async)
            logger.info("keygen：已启用 LLM 生成（轻任务模型）")
        else:
            KEYGEN_FN = None
            logger.info("keygen：未配置 API key，使用 fallback")
    except Exception:  # noqa: BLE001
        pass