"""Embedding 服务（D41）。

主：DashScope text-embedding-v3，OpenAI 兼容（POST /embeddings）。
降级链：embedding 不可用 → TF-IDF/关键词顶替（声明级，D41）。
接入：给 search.py 的 hybrid_search 提供 embed_query_fn；indexer 提供 embed_texts。
"""
from __future__ import annotations

from typing import Callable

from app.configs.settings import get_settings
from app.core.logging import logger

_embed_cache: dict[str, list[float]] = {}


async def dashscope_embed(texts: list[str]) -> list[list[float]]:
    """调 DashScope embeddings（OpenAI 兼容）。失败抛异常→上层降级。

    注意：单次 batch ≤10，超限需分批（DashScope 服务端硬限制）。
    """
    s = get_settings()
    api_key = s.embedding_api_key or s.openai_api_key
    base_url = s.embedding_base_url or s.openai_base_url
    if not api_key:
        raise RuntimeError("未配置 API key，无法生成 embedding")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    out: list[list[float]] = []
    for i in range(0, len(texts), 10):
        batch = texts[i : i + 10]
        resp = await client.embeddings.create(
            model=s.embedding_model,
            input=batch,
            dimensions=s.embedding_dim,
        )
        out.extend(item.embedding for item in resp.data)
    return out


async def embed_query(query: str) -> list[float]:
    """search 注入用：query → embedding（内存缓存避免重复调）。"""
    if query in _embed_cache:
        return _embed_cache[query]
    vec = (await dashscope_embed([query]))[0]
    _embed_cache[query] = vec
    return vec


def embed_query_fn_factory() -> Callable[[str], list[float]]:
    """给 knowledge.search.hybrid_search 用的同步 callable 适配器。

    在已运行 event loop（uvicorn/TestClient）内直接用 asyncio.run 会冲突，
    因此在独立线程中执行 async 嵌入；失败则返回 []（降级 BM25，D41）。
    """
    import asyncio
    import threading

    def _safe(query: str) -> list[float]:
        result: dict = {"v": None, "exc": None}
        def _run():
            try:
                result["v"] = asyncio.run(embed_query(query))
            except Exception as exc:  # noqa: BLE001
                result["exc"] = exc
        t = threading.Thread(target=_run)
        t.start()
        t.join(timeout=15)
        if result.get("exc") or result.get("v") is None:
            logger.warning(f"embed_query 降级(BM25): {result.get('exc') or 'timeout'}")
            return []
        return result["v"]

    return _safe


class LocalTFIDF:
    """TF-IDF 降级（D41 声明级）：K 词向量代替，供无 API 时保底检索。"""

    def __init__(self):
        self.vocab: dict[str, int] = {}
        self.docs: list[str] = []

    def fit(self, texts: list[str]) -> None:
        import jieba

        for t in texts:
            self.docs.append(t)
            for w in jieba.cut(t):
                if w.strip():
                    self.vocab.setdefault(w, len(self.vocab))

    def embed(self, text: str) -> list[float]:
        import jieba

        vec = [0.0] * len(self.vocab)
        for w in jieba.cut(text):
            if w in self.vocab:
                vec[self.vocab[w]] += 1.0
        return vec