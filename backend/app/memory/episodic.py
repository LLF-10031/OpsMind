"""Episodic 记忆（D44）：片段闭合触发 + 去杂去重。

触发：① 上下文压缩闭合 ② 闲置10min ③ 手动保存按钮（由上层调 save_episode）。
管道：代码硬杀 → LLM 判断（可注入）→ 代码收尾（校验/合并）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.core.logging import logger
from app.memory.core import Episode, EpisodicStore, code_hard_filter

# 全局内存store（无PG阶段先用；PG落地换DB实现）
_store: EpisodicStore = EpisodicStore()

# LLM 判断注入（值不值/同主题/合并or新增）；未注入则走"代码硬杀→直接存"
judge_fn: Callable[[str, str, list[Episode]], bool] | None = None


def set_judge(fn: Callable[[str, str, list[Episode]], bool]) -> None:
    global judge_fn
    judge_fn = fn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_episode(topic: str, summary: str, session_id: str, manually_saved: bool = False) -> Episode | None:
    """写一条 Episodic。

    流程：代码硬杀（空/寒暄丢）→ 候选召回（关键词）→（可选）LLM判断
          → 代码收尾（同主题合并 or 新增）。
    """
    if not code_hard_filter(topic, summary):
        return None
    candidates = _store.search_by_keyword(" ".join(topic.split()), limit=3)

    # 同主题合并：候选主题与本次高度相关 → 合并（更新summary）
    for c in candidates:
        overlap = len(set(c.topic) & set(topic)) / max(1, len(set(c.topic) | set(topic)))
        if overlap >= 0.5:
            c.summary = f"{c.summary}\n+{summary}"[:2000]
            c.manually_saved = c.manually_saved or manually_saved
            logger.info(f"合并 Episodic {c.id}")
            return c

    # LLM 判断（可选，注入后才有语义去重）
    if judge_fn is not None:
        try:
            keep = judge_fn(topic, summary, candidates)
            if not keep:
                return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"LLM 判断失败: {exc}")
            # 降级：LLM挂了也保底存

    ep = Episode(id=f"e{len(_store.list()) + 1}", topic=topic, summary=summary, session_id=session_id, manually_saved=manually_saved)
    _store.add(ep)
    return ep


def search_episodes(query: str, limit: int = 3) -> list[Episode]:
    return _store.search_by_keyword(query, limit=limit)


def list_episodes() -> list[Episode]:
    return _store.list()


def delete_episode(ep_id: str) -> bool:
    before = len(_store.list())
    _store._items = [e for e in _store._items if e.id != ep_id]
    return len(_store.list()) < before


# ---------------------------------------------------------------------------
# PG 版本（D44：记忆落库；API 用）。内存版本保留作降级兜底。
# ---------------------------------------------------------------------------


def _to_domain(row) -> Episode:
    return Episode(
        id=str(row.id),
        topic=row.topic,
        summary=row.summary,
        session_id=row.session_id,
        keywords=row.keywords or [],
        created_at=row.created_at,
        manually_saved=bool(row.manually_saved),
    )


async def save_episode_db(session, topic: str, summary: str, session_id: str, manually_saved: bool = False) -> Episode | None:
    """写一条 Episodic（PG 表）。D44 代码硬杀 → 同主题合并 → 新增。"""
    from sqlalchemy import select

    from app.models import Episodic as DB

    if not code_hard_filter(topic, summary):
        return None
    # 同主题合并：主题重叠≥0.5 → 追加 summary
    rows = (await session.execute(select(DB).where(DB.session_id == session_id))).scalars().all()
    for row in rows:
        o = len(set(row.topic) & set(topic)) / max(1, len(set(row.topic) | set(topic)))
        if o >= 0.5:
            row.summary = f"{row.summary}\n+{summary}"[:2000]
            row.manually_saved = row.manually_saved or manually_saved
            await session.flush()
            return _to_domain(row)
    new = DB(
        session_id=session_id,
        topic=topic,
        summary=summary,
        keywords=list(topic.split()),
        manually_saved=manually_saved,
    )
    session.add(new)
    await session.flush()
    return _to_domain(new)


async def search_episodes_db(session, query: str, limit: int = 3):
    """关键词检索 PG episodic。"""
    from sqlalchemy import select

    from app.models import Episodic as DB

    toks = [t for t in query.split() if t]
    rows = (await session.execute(select(DB).limit(limit))).scalars().all()
    scored = []
    for row in rows:
        key_pool = (row.keywords or []) + row.topic.split()
        hit = sum(1 for t in toks if any(t in k for k in key_pool))
        if hit:
            scored.append((hit, _to_domain(row)))
    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [e for _, e in scored[:limit]]


async def list_episodes_db(session):
    from sqlalchemy import select

    from app.models import Episodic as DB

    rows = (await session.execute(select(DB).order_by(DB.created_at.desc()).limit(200))).scalars().all()
    return [_to_domain(r) for r in rows]


async def delete_episode_db(session, ep_id: int) -> bool:
    from app.models import Episodic as DB

    row = await session.get(DB, int(ep_id))
    if not row:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def edit_episode_db(session, ep_id: int, topic: str | None = None, summary: str | None = None) -> Episode | None:
    """编辑已在库的片段（D50：PUT /memory/episodic/{id}）。"""
    from app.models import Episodic as DB

    row = await session.get(DB, int(ep_id))
    if not row:
        return None
    if topic:
        row.topic = topic
        row.keywords = list(topic.split())
    if summary:
        row.summary = summary
    await session.flush()
    return _to_domain(row)