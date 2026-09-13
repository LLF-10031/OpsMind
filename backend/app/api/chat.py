"""AI 助手对话 API（D21/D47）——SSE 流式回答。

- 对话图（LangGraph 骨架）+ 工具循环（search_kb，勾选才查 D48）
- 回答生成：检索结果 + 用户问题 → 真实 LLM（qwen-turbo）流式组织回答；LLM 失败降级回显检索结果
- SSE 事件集（chat，参考 task-run 流事件风格）：
    start / kb_ready / token / done / error
"""
from __future__ import annotations

import json

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.configs.settings import get_settings
from app.core.db import get_session, session_scope
from app.core.limiter import limiter
from app.core.llm import get_default_llm
from app.graph.conversation import ChatState
from app.knowledge.search import format_search_result, hybrid_search
from app.models import Message, Session
from app.services.audit import audit_tool_call
from app.services.embedding import embed_query_fn_factory
from app.services.report import mask_sensitive

router = APIRouter(prefix="/chat", tags=["AI 助手"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _extract_kb_text(tool_results: list) -> str:
    for r in tool_results:
        if isinstance(r, dict) and r.get("tool") == "search_kb":
            return str(r.get("result", ""))
    return ""


def _llm_prompt(user_message: str, kb_text: str) -> str:
    return (
        f"你是 OpsMind 运维助手。请基于下面的知识库检索结果，用中文回答用户的问题。\n\n"
        f"【用户问题】{user_message}\n\n【知识库候选】\n{kb_text[:3000]}\n\n"
        f"请给出简洁、引用了知识库依据的回答；如果知识库与问题无关，请说明无法判断。"
    )


async def _llm_answer_stream(user_message: str, kb_text: str):
    """流式生成回答（逐块打码后透出）；失败返回降级全文块。"""
    if not kb_text:
        yield "（未检索到相关知识，暂无法回答）"
        return
    if not limiter.try_acquire_llm():
        yield kb_text  # 限流降级：回显检索结果
        return
    try:
        llm = get_default_llm()
        async for chunk in llm.astream(_llm_prompt(user_message, kb_text)):
            text = getattr(chunk, "content", None)
            if text:
                yield mask_sensitive(str(text))  # D48
        limiter.llm_success()
    except Exception as exc:  # noqa: BLE001
        limiter.llm_failure()
        from app.core.logging import logger

        logger.warning(f"chat LLM 回答失败，降级回显: {exc}")
        yield kb_text
    finally:
        limiter.release_llm()


def _bind_retriever(session, doc_ids, s, emb):
    async def retriever(query: str) -> str:
        if not doc_ids:
            return "（未勾选知识库文档，本次未检索）"
        results = await hybrid_search(
            session, query, emb, doc_ids=doc_ids, top_k=s.kb_top_k,
            allow_full_library=False,
        )
        return format_search_result(results) if results else "（检索无结果）"

    return retriever


@router.post("")
async def chat(body: dict, session: AsyncSession = Depends(get_session)):
    message = body.get("message", "")
    if not message:
        return StreamingResponse(
            (x for x in [_sse("error", {"message": "请先输入问题"})]),
            media_type="text/event-stream",
        )
    doc_ids = body.get("document_ids")
    s = get_settings()
    emb = embed_query_fn_factory()

    sid = body.get("session_id")
    async with session_scope() as db:
        db_session_tab = None
        if isinstance(sid, int):
            db_session_tab = await db.get(Session, sid)
            if db_session_tab and db_session_tab.is_deleted:
                db_session_tab = None
        if db_session_tab is None:
            db_session_tab = Session(
                title=(message[:40] + ("…" if len(message) > 40 else "")),
                model_snapshot=s.openai_model,
            )
            db.add(db_session_tab)
            await db.flush()
    session_id = db_session_tab.id

    async def gen():
        # 1. 组装 context（D43，骨架）
        from app.services.context import assemble_context

        ctx = assemble_context(
            body.get("system_prompt") or "你是 OpsMind 运维助手，可检索知识库、调用只读工具。",
            "", [], message,
        )
        state = ChatState(
            session_id=str(session_id),
            user_message=message,
            context_text=ctx["context_text"],
            est_tokens=ctx["est_tokens"],
        )
        # 2.5 落 user 消息（会话历史可回溯）
        session.add(Message(session_id=session_id, role="user", content=message))
        await session.flush()
        # 2. 工具循环：search_kb（勾选才查 D48）
        from app.graph.conversation import _default_runner_with_kb, set_retriever

        set_retriever(_bind_retriever(session, doc_ids, s, emb))
        try:
            tr = _default_runner_with_kb(state, "assistant_loop", {"message": message})
            if hasattr(tr, "__await__"):
                tr = await tr
        except Exception as exc:  # noqa: BLE001
            tr = {"tool": "search_kb", "error": str(exc), "result": "（检索失败）"}
        state.tool_results.append(tr or {})
        kb_text = await _extract_kb_text(state.tool_results)
        audit_tool_call(
            "chat", "search_kb", {"message": message, "document_ids": doc_ids},
            ok="error" not in (tr or {}), note=kb_text[:200],
        )
        yield _sse("start", {"session_id": session_id})
        yield _sse("kb_ready", {"found": bool(kb_text)})
        # 3. 流式回答（每块已打码 D48）
        collected = []
        try:
            async for piece in _llm_answer_stream(message, kb_text):
                yield _sse("token", {"text": piece})
                collected.append(piece)
            reply = "".join(collected)
            # 4. O4 校验 + 输出打码兜底
            from app.services.validation import run_pipeline

            state.reply = mask_sensitive(reply)
            state.annotations = run_pipeline(state.reply, "ok", has_error_keyword=False, enabled=None)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})
            return
        # 4.5 落 assistant 消息 + 更新会话活跃时间（D50）
        session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content=state.reply,
                tool_calls=[
                    {"name": t.get("tool"), "result": str(t.get("result", ""))[:500]}
                    for t in state.tool_results if isinstance(t, dict)
                ],
            )
        )
        db_session = await session.get(Session, session_id)
        if db_session:
            db_session.last_active_at = datetime.now(timezone.utc)
        await session.commit()
        yield _sse("done", {"reply": state.reply, "session_id": session_id})

    return StreamingResponse(gen(), media_type="text/event-stream")