"""知识库文档 API（D40/D41）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.knowledge import normalizer, splitter
from app.knowledge.indexer import create_document_record, write_units
from app.models import Document, Unit
from app.models.schemas import fail, ok

router = APIRouter(prefix="/documents", tags=["知识库"])

_embed_adaptor = None  # 惰性注入 embedding


def _get_embed_query_fn():
    global _embed_adaptor
    if _embed_adaptor is None:
        from app.services.embedding import embed_query_fn_factory

        _embed_adaptor = embed_query_fn_factory()
    return _embed_adaptor


@router.post("/search")
async def search_kb(body: dict, session: AsyncSession = Depends(get_session)):
    """知识库检索（D41/D48）：RRF 融合 + topK 候选；默认只搜勾选文档集。"""
    from app.knowledge.search import format_search_result, hybrid_search

    q = body.get("query", "")
    doc_ids = body.get("document_ids")  # 勾选文档集
    if not doc_ids:
        # 默认不查（勾选才查，D48）；全量为显式开关
        if not body.get("full_library"):
            return ok({"results": [], "format": "（未勾选文档集，不检索）"})
        doc_ids = None
    try:
        results = await hybrid_search(
            session, q, _get_embed_query_fn(), doc_ids=doc_ids, top_k=body.get("k", 6),
            allow_full_library=not doc_ids,
        )
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("opsmind.api").exception("search 失败")
        return fail("SEARCH_FAILED", f"{type(exc).__name__}: {exc}")
    return ok({"results": results, "format": format_search_result(results)})


@router.get("")
async def list_docs(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(Document).where(Document.is_deleted.is_(False)))
    return ok([{"id": d.id, "name": d.name, "file_type": d.file_type} for d in rows.scalars().all()])


@router.post("")
async def upload_doc(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    """上传并规范化入库（D40/D41）：三步保位 → unit → key → 向量。"""
    name = file.filename or "unnamed"
    ftype = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
    if ftype not in ("md", "txt", "pdf"):
        return fail("BAD_REQUEST", "仅支持 md/txt/pdf")
    content = await file.read()
    try:
        from app.knowledge.kb_service import ingest_document

        result = await ingest_document(session, name, ftype, content)
    except ValueError as exc:
        return fail("BAD_REQUEST", str(exc))
    return ok(result)


@router.get("/{doc_id}")
async def doc_detail(doc_id: int, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    unit_count = (
        await session.execute(select(Unit).where(Unit.document_id == doc_id))
    ).scalars().all()
    return ok(
        {
            "id": doc.id,
            "name": doc.name,
            "file_type": doc.file_type,
            "unit_count": len(unit_count),
            "normalized_md": doc.normalized_md or "",
            "created_at": doc.created_at,
        }
    )


@router.get("/{doc_id}/content")
async def doc_content(doc_id: int, session: AsyncSession = Depends(get_session)):
    """在线浏览完整原文（G3）：返回原始全文 + 规范化全文，均不截断。"""
    doc = await session.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    return ok(
        {
            "id": doc.id,
            "name": doc.name,
            "file_type": doc.file_type,
            "raw_content": doc.raw_content or "",
            "normalized_md": doc.normalized_md or "",
        }
    )


@router.post("/{doc_id}/preview")
async def doc_preview(doc_id: int, session: AsyncSession = Depends(get_session), limit: int = 20):
    """按保位顺序预览该文档的知识单元（不落库）。"""
    doc = await session.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    rows = await session.execute(
        select(Unit).where(Unit.document_id == doc_id).limit(limit)
    )
    return ok(
        [
            {"unit_id": u.id, "kind": u.kind, "path": u.path, "step_no": u.step_no, "value": u.value[:2000]}
            for u in rows.scalars().all()
        ]
    )


@router.delete("/{doc_id}")
async def delete_doc(doc_id: int, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if not doc:
        return ok(False)
    doc.is_deleted = True
    # 级联删 unit（向量由 DB 外键 ON DELETE 处理/或此处显式删）——骨架先软删
    return ok(True)