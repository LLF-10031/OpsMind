"""知识库编排（D40/D41）：上传→规范化→切分→key→向量→索引，一步到位。

embedding 失败自动降级（BM25-only，D41 声明级），不阻塞入库。
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.knowledge import normalizer, splitter
from app.knowledge.indexer import create_document_record, write_key_index, write_units
from app.services.embedding import dashscope_embed


async def ingest_document(
    session: AsyncSession,
    filename: str,
    file_type: str,
    content: bytes,
) -> dict[str, Any]:
    """完整入库流程；返回 {document_id, units, keys, embedded}。"""
    from app.knowledge.keygen import agenerate_keys, auto_setup_keygen

    auto_setup_keygen()  # 惰性启用 LLM keygen（幂等），任何入口都生效
    raw = normalizer.load_text(file_type, content, filename)
    sections = normalizer.split_sections(raw)

    # 3 步：规范化 md（含 UNIT 注释）→ 切 unit → 补父上下文
    normalized_md = normalizer.build_unit_md(sections)
    units = splitter.parse_unit_md(normalized_md)
    headings = [s["heading"].lstrip("# ").strip() for s in sections if s["heading"]]
    units = splitter.append_parent_context(units, headings)

    unique_name = await _ensure_unique_name(session, filename)
    doc_id = await create_document_record(session, unique_name, file_type, raw, normalized_md)
    unit_ids = await write_units(session, doc_id, units)

    # key 生成（async LLM 优先，失败逐 unit 降级 fallback）
    all_keys: list[list[str]] = []
    flat_keys: list[str] = []
    for u in units:
        keys = await agenerate_keys(u)
        all_keys.append(keys)
        flat_keys.extend(keys)

    # 向量化（失败降级 BM25-only）
    embeddings: list[list[float]] | None = None
    try:
        embeddings = await dashscope_embed(flat_keys)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"embedding 不可用，降级 BM25-only: {exc}")
        embeddings = None

    # key_index 打平行（每个 key 一行；embeddings 按 flat_keys 顺序对应）
    cursor = 0
    for uid, keys in zip(unit_ids, all_keys):
        row_embs = embeddings[cursor : cursor + len(keys)] if embeddings else None
        await write_key_index(session, uid, keys, row_embs)
        cursor += len(keys)

    await session.commit()  # 显式提交（调用方可能用非自动提交会话）
    return {
        "document_id": doc_id,
        "units": len(units),
        "keys": len(flat_keys),
        "embedded": embeddings is not None,
    }


def _dedupe_name(filename: str) -> str:
    """同名文档由 indexer.create_document_record 处理：这里仅占位返回原文件名。

    唯一冲突由 create_document_record 在 PG 层做"INSERT...ON CONFLICT 换名"或调用方传入 unique 名。
    """
    return filename


async def _ensure_unique_name(session, filename: str) -> str:
    """确保文档名唯一：已存在则追加时间戳后缀。"""
    from datetime import datetime

    from sqlalchemy import select

    from app.models import Document

    candidate = filename
    while True:
        exists = (
            await session.execute(select(Document.id).where(Document.name == candidate))
        ).scalars().first()
        if exists is None:
            return candidate
        stem, dot, ext = candidate.rpartition(".")
        candidate = f"{stem}_{datetime.now().strftime('%H%M%S')}{dot}{ext}"