"""巡检任务 API（归属单台主机；立即执行；历史列表）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Task, TaskScript
from app.models.schemas import fail, ok
from app.services import task as task_svc

router = APIRouter(prefix="/tasks", tags=["巡检任务"])


def normalize_schedule(schedule):
    """规范调度配置（D17/A3）：空→仅手动；interval(分钟)/cron；非法抛 ValueError。"""
    if schedule in (None, "", {}, []):
        return None
    if isinstance(schedule, str):
        import json

        try:
            schedule = json.loads(schedule)
        except (ValueError, TypeError):
            raise ValueError("调度配置需为 JSON：{type: 'interval'|'cron', value}")
    if not isinstance(schedule, dict):
        raise ValueError("调度配置格式不正确")
    stype = schedule.get("type")
    value = schedule.get("value")
    if stype == "interval":
        try:
            mins = int(value)
        except (TypeError, ValueError):
            raise ValueError("interval 的 value 需为分钟数（整数）")
        if mins <= 0:
            raise ValueError("interval 需为正整数分钟")
        return {"type": "interval", "value": mins}
    if stype == "cron":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("cron 的 value 需为 cron 表达式字符串")
        return {"type": "cron", "value": value.strip()}
    raise ValueError("调度 type 仅支持 interval / cron（留空=仅手动执行）")


def _sync_job(task_id: int, schedule_json, is_enabled: bool) -> None:
    """任务变更时同步 APScheduler 定时作业（失败不影响主流程）。"""
    try:
        from app.services.task_scheduler import sync_task_job

        sync_task_job(task_id, schedule_json, is_enabled)
    except Exception:  # noqa: BLE001
        pass


def _remove_job(task_id: int) -> None:
    try:
        from app.services.task_scheduler import remove_task_job

        remove_task_job(task_id)
    except Exception:  # noqa: BLE001
        pass


@router.post("")
async def create_task(body: dict, session: AsyncSession = Depends(get_session)):
    """建任务（归属单台主机）。body: {host_id, name, schedule_json?, script_ids?}"""
    host_id = body.get("host_id")
    name = body.get("name")
    if not host_id or not name:
        return fail("BAD_REQUEST", "host_id/name 必填")
    try:
        schedule = normalize_schedule(body.get("schedule_json"))
    except ValueError as exc:
        return fail("BAD_REQUEST", str(exc))
    t = Task(
        host_id=host_id,
        name=name,
        description=body.get("description"),
        schedule_json=schedule,
        is_enabled=body.get("is_enabled", True),
    )
    session.add(t)
    await session.flush()
    # 绑定脚本
    for sid in body.get("script_ids", []) or []:
        session.add(
            TaskScript(
                task_id=t.id,
                script_id=sid,
            )
        )
    await session.flush()
    _sync_job(t.id, t.schedule_json, t.is_enabled)
    return ok({"task_id": t.id})


async def _get_task(session: AsyncSession, task_id: int) -> Task:
    t = await session.get(Task, task_id)
    if not t or t.is_deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


@router.get("/{task_id}")
async def get_task(task_id: int, session: AsyncSession = Depends(get_session)):
    t = await _get_task(session, task_id)
    ts_rows = await session.execute(
        select(TaskScript.script_id).where(TaskScript.task_id == t.id)
    )
    script_ids = [row[0] for row in ts_rows]
    return ok(
        {
            "id": t.id,
            "host_id": t.host_id,
            "template_id": t.template_id,
            "name": t.name,
            "description": t.description,
            "schedule_json": t.schedule_json,
            "is_enabled": t.is_enabled,
            "script_ids": script_ids,
        }
    )


@router.put("/{task_id}")
async def update_task(task_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    t = await _get_task(session, task_id)
    if "schedule_json" in body:
        try:
            t.schedule_json = normalize_schedule(body.get("schedule_json"))
        except ValueError as exc:
            return fail("BAD_REQUEST", str(exc))
    for k in ("name", "description", "is_enabled"):
        if k in body:
            setattr(t, k, body[k])
    if "script_ids" in body:
        await session.execute(sqlalchemy_delete(TaskScript).where(TaskScript.task_id == t.id))
        for sid in body.get("script_ids") or []:
            session.add(TaskScript(task_id=t.id, script_id=sid))
    await session.flush()
    _sync_job(t.id, t.schedule_json, t.is_enabled)
    return ok({"task_id": t.id})


@router.delete("/{task_id}")
async def delete_task(task_id: int, session: AsyncSession = Depends(get_session)):
    t = await _get_task(session, task_id)
    t.is_deleted = True
    _remove_job(task_id)
    return ok(True)


@router.post("/{task_id}/run")
async def run_task(task_id: int, session: AsyncSession = Depends(get_session)):
    tr_id = await task_svc.trigger_run(session, task_id)
    if not tr_id:
        raise HTTPException(status_code=404, detail="任务不存在或已删除")
    return ok({"task_run_id": tr_id})


@router.get("/{task_id}/runs")
async def task_runs(task_id: int, session: AsyncSession = Depends(get_session)):
    rows = await task_svc.list_runs(session, task_id)
    return ok([{ "id": r.id, "status": r.status, "trigger": r.trigger, "started_at": r.started_at } for r in rows])


@router.put("/{task_id}/toggle")
async def toggle_task(task_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    t = await session.get(Task, task_id)
    if not t or t.is_deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    t.is_enabled = body.get("is_enabled", t.is_enabled)
    _sync_job(t.id, t.schedule_json, t.is_enabled)
    return ok(t.is_enabled)