"""key 生成 + 向量化 + 落 key_index（D41）。

- 一个 unit 可有多个 key（问法/别名/错误码锚词），key 打平行（key_index 表）。
- value 原文保真、不重写；LLM 只生成 key 标签（pointer 指向 value span）。
- 向量 = embedding(unit 的 intent/key 文本)；embedding 不可用→TF-IDF 声明降级。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KeyIndex, Unit, Document


async def create_document_record(session: AsyncSession, name: str, file_type: str, raw_content: str, normalized_md: str) -> int:
    doc = Document(name=name, file_type=file_type, raw_content=raw_content, normalized_md=normalized_md)
    session.add(doc)
    await session.flush()
    return doc.id


async def write_units(session: AsyncSession, doc_id: int, units: list[dict[str, Any]]) -> list[int]:
    ids = []
    for u in units:
        unit = Unit(
            document_id=doc_id,
            kind=u.get("kind", "manual"),
            value=u.get("value", ""),
            parent_context=u.get("parent_context", ""),
            path=u.get("path", ""),
            original_range=u.get("original_range"),
            section_id=u.get("section_id"),
        )
        session.add(unit)
        await session.flush()
        ids.append(unit.id)
    return ids


async def write_key_index(session: AsyncSession, unit_id: int, keys: list[str], embeddings: list[list[float]] | None = None) -> None:
    """key 打平行：每个 key 一行，embedding 可选。"""
    embs = embeddings or [None] * len(keys)
    for k, emb in zip(keys, embs):
        idx = KeyIndex(unit_id=unit_id, key_text=k)
        if emb is not None:
            try:
                idx.embedding = emb  # vector 类型由 pgvector 处理
            except Exception:  # noqa: BLE001
                pass
        session.add(idx)
    await session.flush()


async def build_session_index(
    session: AsyncSession,
    doc_id: int,
    units: list[dict[str, Any]],
    keys_per_unit: list[list[str]],
) -> dict:
    """索引一条文档：写 unit + key_index（embedding 由上层向量化器填充）。"""
    unit_ids = await write_units(session, doc_id, units)
    for uid, keys in zip(unit_ids, keys_per_unit):
        await write_key_index(session, uid, keys)
    return {"doc_id": doc_id, "units": len(unit_ids)}


async def list_key_index(session: AsyncSession, unit_id: int):
    rows = await session.execute(select(KeyIndex).where(KeyIndex.unit_id == unit_id))
    return list(rows.scalars().all())