"""chat 会话管理 API（05 §十一 / D50）：sessions CRUD + 消息历史 + 手动存记忆。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.memory import episodic
from app.models import Message, Session
from app.models.schemas import fail, ok

router = APIRouter(prefix="/chat/sessions", tags=["AI 助手"])


@router.get("")
async def list_sessions(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Session)
        .where(Session.is_deleted.is_(False))
        .order_by(Session.last_active_at.desc())
        .limit(100)
    )
    return ok(
        [
            {
                "id": s.id,
                "title": s.title,
                "model_snapshot": s.model_snapshot,
                "last_active_at": s.last_active_at,
                "created_at": s.created_at,
            }
            for s in rows.scalars().all()
        ]
    )


@router.post("")
async def create_session(body: dict, session: AsyncSession = Depends(get_session)):
    s = Session(
        title=body.get("title") or "新会话",
        model_snapshot=body.get("model_snapshot"),
    )
    session.add(s)
    await session.flush()
    return ok({"session_id": s.id, "title": s.title})


async def _get_session(session: AsyncSession, session_id: int) -> Session:
    s = await session.get(Session, session_id)
    if not s or s.is_deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


@router.put("/{session_id}")
async def update_session(session_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    s = await _get_session(session, session_id)
    if "title" in body:
        s.title = body["title"]
    return ok({"session_id": s.id, "title": s.title})


@router.delete("/{session_id}")
async def delete_session(session_id: int, session: AsyncSession = Depends(get_session)):
    s = await _get_session(session, session_id)
    s.is_deleted = True
    return ok(True)


@router.get("/{session_id}/messages")
async def session_messages(
    session_id: int,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None),
):
    await _get_session(session, session_id)
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    rows = (await session.execute(stmt)).scalars().all()
    msgs = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "citations": m.citations,
            "usage": m.usage,
            "created_at": m.created_at,
        }
        for m in sorted(rows, key=lambda x: x.id)
    ]
    return ok({"total": len(msgs), "items": msgs})


@router.post("/{session_id}/save-memory")
async def save_session_memory(session_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    """手动把当前片段保存为 Episodic（D44 手动保存按钮）。"""
    await _get_session(session, session_id)
    topic = body.get("topic") or body.get("summary") or ""
    summary = body.get("summary") or ""
    if not topic or not summary:
        return fail("BAD_REQUEST", "summary 必填")
    try:
        ep = await episodic.save_episode_db(
            session, topic, summary, f"chat:{session_id}", manually_saved=True
        )
    except Exception:  # noqa: BLE001 DB 降级
        ep = episodic.save_episode(topic, summary, f"chat:{session_id}", manually_saved=True)
    if not ep:
        return fail("FILTERED", "空/寒暄内容未保存")
    return ok({"id": ep.id, "topic": ep.topic})
