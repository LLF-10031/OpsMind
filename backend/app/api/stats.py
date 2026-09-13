"""概览统计 API：只读聚合，供仪表盘首页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Document, Host, Run, Script, Task, TaskRun
from app.models.schemas import ok

router = APIRouter(prefix="/stats", tags=["概览"])


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session)):
    """仪表盘聚合：资源计数 + 近期 task_run + 近期告警 + level 分布。"""
    hosts_total = await session.scalar(
        select(func.count(Host.id)).where(Host.is_deleted.is_(False))
    ) or 0
    hosts_reachable = await session.scalar(
        select(func.count(Host.id)).where(
            Host.is_deleted.is_(False), Host.last_ping_at.is_not(None)
        )
    ) or 0
    tasks_enabled = await session.scalar(
        select(func.count(Task.id)).where(
            Task.is_deleted.is_(False), Task.is_enabled.is_(True)
        )
    ) or 0
    scripts_enabled = await session.scalar(
        select(func.count(Script.id)).where(
            Script.is_deleted.is_(False), Script.is_enabled.is_(True)
        )
    ) or 0
    docs_total = await session.scalar(
        select(func.count(Document.id)).where(Document.is_deleted.is_(False))
    ) or 0

    tr_rows = (
        await session.execute(
            select(TaskRun).order_by(TaskRun.started_at.desc()).limit(10)
        )
    ).scalars().all()
    recent_task_runs = [
        {
            "id": t.id,
            "task_id": t.task_id,
            "trigger": t.trigger,
            "status": t.status,
            "started_at": t.started_at,
            "finished_at": t.finished_at,
            "summary_json": t.summary_json or {},
        }
        for t in tr_rows
    ]

    alert_rows = (
        await session.execute(
            select(Run)
            .where(Run.level.in_(["crit", "warn"]))
            .order_by(Run.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    recent_alerts = [
        {
            "id": r.id,
            "task_run_id": r.task_run_id,
            "script_id": r.script_id,
            "level": r.level,
            "report_type": r.report_type,
            "created_at": r.created_at,
        }
        for r in alert_rows
    ]

    dist_rows = (
        await session.execute(
            select(Run.level, func.count(Run.id)).group_by(Run.level)
        )
    ).all()
    level_dist = {lvl or "unknown": cnt for lvl, cnt in dist_rows}

    return ok(
        {
            "hosts": {"total": hosts_total, "reachable": hosts_reachable},
            "tasks_enabled": tasks_enabled,
            "scripts_enabled": scripts_enabled,
            "docs_total": docs_total,
            "recent_task_runs": recent_task_runs,
            "recent_alerts": recent_alerts,
            "level_dist": level_dist,
        }
    )
