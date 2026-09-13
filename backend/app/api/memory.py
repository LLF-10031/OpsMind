"""记忆 API（D44）：列表/删除/查询。优先走 PG，DB 不可用降级内存版。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.memory import episodic
from app.models.schemas import fail, ok

router = APIRouter(prefix="/memory", tags=["记忆管理"])


@router.post("")
async def save_memory(body: dict, session: AsyncSession = Depends(get_session)):
    """手动保存片段为 Episodic（D44 手动保存按钮）。"""
    topic = body.get("topic", "")
    summary = body.get("summary", "")
    session_id = body.get("session_id", "s1")
    if not topic or not summary:
        return fail("BAD_REQUEST", "topic/summary 必填")
    try:
        ep = await episodic.save_episode_db(session, topic, summary, session_id, manually_saved=True)
    except Exception:  # noqa: BLE001 DB 降级
        ep = episodic.save_episode(topic, summary, session_id, manually_saved=True)
    if not ep:
        return fail("FILTERED", "空/寒暄内容未保存")
    return ok({"id": ep.id, "topic": ep.topic})


@router.get("")
async def list_memory(session: AsyncSession = Depends(get_session), type: str = "episodic"):
    if type == "semantic":
        try:
            from app.memory.semantic import list_semantic_db

            rows = await list_semantic_db(session)
        except Exception:  # noqa: BLE001 DB 降级
            rows = []
        return ok([{"id": r.id, "pattern": r.pattern, "trigger_condition": r.trigger_condition, "confidence": r.confidence} for r in rows])
    try:
        items = await episodic.list_episodes_db(session)
    except Exception:  # noqa: BLE001 DB 降级
        items = episodic.list_episodes()
    return ok([{"id": e.id, "topic": e.topic, "summary": e.summary, "session_id": e.session_id} for e in items])


@router.put("/{type}/{ep_id}")
async def edit_memory(type: str, ep_id: str, body: dict, session: AsyncSession = Depends(get_session)):
    """编辑记忆片段（D50）：episodic 改 topic/summary，semantic 改 pattern/trigger_condition/confidence。"""
    if type == "semantic":
        try:
            from app.memory.semantic import edit_semantic_db

            edited = await edit_semantic_db(session, int(ep_id), body)
        except ValueError:
            edited = False
        return ok(True) if edited else fail("NOT_FOUND", "记忆不存在")
    try:
        edited = await episodic.edit_episode_db(session, int(ep_id), body.get("topic"), body.get("summary"))
    except (ValueError, Exception):  # noqa: BLE001
        edited = None
    if edited:
        return ok({"id": edited.id, "topic": edited.topic})
    return fail("NOT_FOUND", "记忆不存在")


@router.delete("/{type}/{ep_id}")
async def delete_memory(type: str, ep_id: str, session: AsyncSession = Depends(get_session)):
    if type == "semantic":
        try:
            from app.memory.semantic import delete_semantic_db

            deleted = await delete_semantic_db(session, int(ep_id))
        except (ValueError, Exception):  # noqa: BLE001
            deleted = False
        return ok(True) if deleted else fail("NOT_FOUND", "记忆不存在")
    try:
        deleted = await episodic.delete_episode_db(session, int(ep_id))
    except (ValueError, Exception):  # noqa: BLE001 DB 降级内存
        deleted = episodic.delete_episode(ep_id)
    return ok(True) if deleted else fail("NOT_FOUND", "记忆不存在")


@router.post("/query")
async def query_memory(body: dict, session: AsyncSession = Depends(get_session)):
    q = body.get("query", "")
    typ = body.get("type", "episodic")
    k = body.get("k", 3)
    if typ == "semantic":
        return ok({"type": "semantic", "items": []})
    try:
        items = await episodic.search_episodes_db(session, q, limit=k)
    except Exception:  # noqa: BLE001
        items = episodic.search_episodes(q, limit=k)
    return ok([{"id": e.id, "topic": e.topic, "summary": e.summary} for e in items])