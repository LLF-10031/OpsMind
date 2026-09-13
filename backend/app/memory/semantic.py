"""Semantic 记忆（D44）：从 Episodic 提炼长期经验规律。

触发：累计新增 Episodic ≥30 且新增 ≥2 才跑轻模型提炼。
提炼产物必须：证据真实 / 数量≥阈值 / 横跨≥2 会话；任一不过 → 丢弃。
无规律 → 输出空，不产生垃圾。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.core.logging import logger


@dataclass
class SemanticItem:
    pattern: str
    trigger_condition: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    id: str = ""


# 提炼注入：refine_fn(episodes)-> list[SemanticItem]；未注入则降级（不提炼）
refine_fn: Callable[[list], list[SemanticItem]] | None = None
MIN_EPISODES = 30
MIN_EVIDENCE = 2
MIN_SESSIONS = 2


def set_refine_fn(fn: Callable[[list], list[SemanticItem]]) -> None:
    global refine_fn
    refine_fn = fn


def _sessions_covered(episodes: list, evidence_ids: list[str]) -> int:
    """evidence 跨会话数（简化：按 episode 内 session_id 集合）。"""
    sessions = set()
    for ep in episodes:
        if getattr(ep, "id", None) in evidence_ids:
            sessions.add(getattr(ep, "session_id", "?"))
    return len(sessions)


def maybe_refine(episode_count: int, new_this_batch: int, episodes: list) -> list[SemanticItem]:
    """语义提炼触发与门槛（D44）：累计≥30 且新增≥2 → 调 refine_fn → 校验。"""
    if episode_count < MIN_EPISODES or new_this_batch < 2:
        return []
    if refine_fn is None:
        logger.info("Semantic：未配置 refine_fn，跳过提炼")
        return []

    try:
        items = refine_fn(episodes)
    except Exception as exc:
        logger.warning(f"Semantic 提炼失败: {exc}")
        return []
    validated = []
    for item in items:
        if len(item.evidence_ids) < MIN_EVIDENCE:
            continue
        if _sessions_covered(episodes, item.evidence_ids) < MIN_SESSIONS:
            continue
        validated.append(item)
    logger.info(f"Semantic 提炼：{len(items)} 条候选 → {len(validated)} 条有效")
    return validated


# ---------------------------------------------------------------------------
# PG 版本（D44：长期经验落库；API 用）。提炼仍由 refine_fn 注入；落库走 DB。
# ---------------------------------------------------------------------------


async def save_semantic_db(session, item: SemanticItem, embedding: list[float] | None = None) -> int:
    from app.models import SemanticItemModel as DB

    row = DB(
        pattern=item.pattern,
        trigger_condition=item.trigger_condition,
        evidence_ids=item.evidence_ids,
        confidence=item.confidence,
        embedding=embedding,
        is_enabled=True,
    )
    session.add(row)
    await session.flush()
    return row.id


async def list_semantic_db(session, limit: int = 100):
    from sqlalchemy import select

    from app.models import SemanticItemModel as DB

    rows = (await session.execute(select(DB).where(DB.is_enabled.is_(True)).order_by(DB.created_at.desc()).limit(limit))).scalars().all()
    return rows


async def delete_semantic_db(session, sem_id: int) -> bool:
    from app.models import SemanticItemModel as DB

    row = await session.get(DB, int(sem_id))
    if not row:
        return False
    row.is_enabled = False
    await session.flush()
    return True


async def edit_semantic_db(session, sem_id: int, body: dict) -> bool:
    """编辑长期经验（D50：PUT /memory/semantic/{id}）。"""
    from app.models import SemanticItemModel as DB

    row = await session.get(DB, int(sem_id))
    if not row or not row.is_enabled:
        return False
    for k in ("pattern", "trigger_condition", "confidence"):
        if k in body:
            setattr(row, k, body[k])
    await session.flush()
    return True