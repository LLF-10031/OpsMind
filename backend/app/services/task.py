"""任务服务：触发一次执行（建 TaskRun + 后台执行引擎）。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskRun


async def trigger_run(session: AsyncSession, task_id: int) -> int | None:
    task = await session.get(Task, task_id)
    if not task or task.is_deleted or not task.is_enabled:
        return None
    tr = TaskRun(
        task_id=task_id,
        trigger="manual",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.flush()

    async def _bg():
        from app.services.execution import execute_task_run

        await execute_task_run(tr.id)

    t = asyncio.create_task(_bg())  # 后台执行；SSE 通过 task_run 状态/详情轮询
    from app.services.execution import register_running

    register_running(tr.id, t)
    return tr.id


async def list_runs(session: AsyncSession, task_id: int):
    rows = await session.execute(
        select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.started_at.desc()).limit(50)
    )
    return list(rows.scalars().all())


async def mark_run_done(session: AsyncSession, tr_id: int, summary: dict) -> None:
    tr = await session.get(TaskRun, tr_id)
    if not tr:
        return
    tr.status = "DONE"
    tr.finished_at = datetime.now(timezone.utc)
    tr.summary_json = summary