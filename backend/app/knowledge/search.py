"""知识库检索（D41/D48）：向量 + BM25 → RRF 融合 → topK 候选 → LLM 在候选内选。

- 默认"勾选才查"：search_kb 只检索勾选文档集；全量 = 显式开关（D48）。
- BM25：PG tsvector（key_text）精确词命中。
- 向量：KeyIndex.embedding（text-embedding-v3），embedding 降级则退化为 BM25-only。
- 返回候选带 parent_context + 来源，供 LLM 裁决。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.configs.settings import get_settings
from app.models import Document, KeyIndex, Unit


def rrf_fuse(
    ranked_lists: list[list[tuple[int, int]]],
    k: int = 60,
) -> list[tuple[int, float]]:
    """RRF：score = Σ 1/(k + rank)，输入每路 [(key_index_id, rank)]。"""
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for kid, rank in lst:
            scores[kid] = scores.get(kid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


async def _bm25_candidates(
    session: AsyncSession, q: str, doc_ids: list[int] | None, limit: int
) -> list[tuple[int, int]]:
    """BM25 精确词：对中文 query 用 jieba 分词，任一 token 命中即召回（top 相关）。"""
    tokens = _tokenize_query(q)
    if not tokens:
        return []

    from sqlalchemy import or_

    base = select(KeyIndex.id).where(or_(*[KeyIndex.key_text.contains(tok) for tok in tokens[:10]]))
    if doc_ids:
        base = base.join(Unit).where(Unit.document_id.in_(doc_ids))
    rows = (await session.execute(base.limit(limit))).scalars().all()
    return [(int(r), i) for i, r in enumerate(rows)]


def _tokenize_query(q: str) -> list[str]:
    """中文分词（jieba），失败则退回按空白/标点切。"""
    try:
        import jieba

        seg = [w.strip() for w in jieba.cut(q) if w.strip() and len(w.strip()) >= 2]
    except Exception:  # noqa: BLE001
        seg = [w.strip() for w in q.replace(",", " ").replace("，", " ").split() if w.strip()]
    if not seg and q.strip():
        seg = [q.strip()]
    # 去重保序
    seen = set()
    return [w for w in seg if not (w in seen or seen.add(w))]


async def _vector_candidates(
    session: AsyncSession, emb: list[float], doc_ids: list[int] | None, limit: int
) -> list[tuple[int, int]]:
    """向量检索（HNSW，按 embedding 距离）。返回 [(key_index_id, rank)]。"""
    if not emb:
        return []
    base = (
        select(KeyIndex.id)
        .order_by(KeyIndex.embedding.cosine_distance(emb))
        .limit(limit)
    )
    if doc_ids:
        base = base.join(Unit).where(Unit.document_id.in_(doc_ids))
    rows = (await session.execute(base)).scalars().all()
    return [(r, i) for i, r in enumerate(rows)]


async def hybrid_search(
    session: AsyncSession,
    query: str,
    embeddings,
    doc_ids: list[int] | None = None,
    top_k: int = 6,
    allow_full_library: bool = False,
) -> list[dict[str, Any]]:
    """RRF 混合检索。

    embeddings: 提供 embed_query(query)->list[float] 的可调用；None/异常则退化 BM25。
    doc_ids: 勾选文档集（search_kb 限定）；None+allow_full_library=False 视为不检索。
    """
    s = get_settings()
    if not doc_ids and not allow_full_library:
        return []  # 默认"勾选才查"，未勾选不查（D48）

    v_ranked: list[tuple[int, int]] = []
    if embeddings is not None:
        try:
            emb = embeddings(query)
            v_ranked = await _vector_candidates(session, emb, doc_ids, top_k * 2)
        except Exception:  # noqa: BLE001 嵌入失败→退化 BM25
            v_ranked = []

    b_ranked = await _bm25_candidates(session, query, doc_ids, top_k * 2)
    ranked = rrf_fuse([v_ranked, b_ranked], k=s.kb_rrf_k)
    top_ids = [kid for kid, _ in ranked[:top_k]]

    if not top_ids:
        return []
    rows = (
        await session.execute(
            select(KeyIndex, Unit, Document)
            .join(Unit, KeyIndex.unit_id == Unit.id)
            .join(Document, Unit.document_id == Document.id)
            .where(KeyIndex.id.in_(top_ids))
        )
    ).all()
    results = []
    for kidx, unit, doc in rows:
        results.append(
            {
                "key_index_id": kidx.id,
                "key_text": kidx.key_text,
                "unit_id": unit.id,
                "value": unit.value,
                "parent_context": unit.parent_context,
                "path": unit.path,
                "doc_id": doc.id,
                "doc_name": doc.name,
            }
        )
    return results


def format_search_result(results: list[dict[str, Any]]) -> str:
    """候选 → 带引用的上下文块（LLM 可读，来源可溯源）。"""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(
            f"[候选{i}] {r['doc_name']} / {r['parent_context'] or '（无标题）'}\n"
            f">{r['value']}\n"
            f"来源: doc#{r['doc_id']} unit#{r['unit_id']}"
        )
    return "\n\n".join(parts)