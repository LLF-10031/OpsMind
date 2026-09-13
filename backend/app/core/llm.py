"""LLM 工厂（D35/D43）。

- 全局一份"默认模式" + 一个"轻任务模型"，由 settings / 前端设置动态重建。
- 改配置即时生效（内存缓存，配置版本变化后重建 client）。
"""
from __future__ import annotations

import threading
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.configs.settings import get_settings
from app.core.logging import logger

_lock = threading.Lock()


@lru_cache(maxsize=4)
def _build_chat(
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
) -> ChatOpenAI:
    if not api_key:
        logger.warning("未配置 api_key，LLM 将不可用（降级由调用方处理）")
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key or "not-set",
        temperature=temperature,
        streaming=True,
        max_retries=1,
    )


def get_default_llm() -> ChatOpenAI:
    s = get_settings()
    return _build_chat(s.openai_model, s.openai_base_url, s.openai_api_key, s.llm_temperature)


def get_light_llm() -> ChatOpenAI:
    """轻任务模型：压缩/摘要/记忆提炼（D43）。

    与文档处理同组，共用 docproc 凭据；为空回落对话默认。
    """
    s = get_settings()
    return _build_chat(
        s.light_model or s.docproc_model or s.openai_model,
        s.docproc_base_url or s.openai_base_url,
        s.docproc_api_key or s.openai_api_key,
        s.llm_temperature,
    )


def get_docproc_llm() -> ChatOpenAI:
    """文档处理模型：多模态/图片解析/意图提炼（D40）。

    key/base_url/model 各自可独立配置；为空时回落。
    """
    s = get_settings()
    return _build_chat(
        s.docproc_model or s.light_model,
        s.docproc_base_url or s.openai_base_url,
        s.docproc_api_key or s.openai_api_key,
        s.llm_temperature,
    )


def rebuild_llm(**overrides) -> ChatOpenAI:
    """按前端设置覆盖重建（不改 settings 全局，仅本次调用场景）。"""
    s = get_settings()
    return _build_chat(
        overrides.get("model", s.openai_model),
        overrides.get("base_url", s.openai_base_url),
        overrides.get("api_key", s.openai_api_key),
        overrides.get("temperature", s.llm_temperature),
    )


def invalidate_llm_cache() -> None:
    with _lock:
        _build_chat.cache_clear()