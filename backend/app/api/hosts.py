"""主机管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Task, TaskScript
from app.models.schemas import fail, ok
from app.services import host as host_svc

router = APIRouter(prefix="/hosts", tags=["主机管理"])


@router.get("")
async def list_hosts(session: AsyncSession = Depends(get_session)):
    rows = await host_svc.list_hosts(session)
    return ok([{"id": h.id, "name": h.name, "mcp_endpoint": h.mcp_endpoint, "last_ping_at": h.last_ping_at} for h in rows])


@router.post("")
async def create_host(body: dict, session: AsyncSession = Depends(get_session)):
    name = body.get("name")
    endpoint = body.get("mcp_endpoint")
    if not name or not endpoint:
        return fail("BAD_REQUEST", "name/mcp_endpoint 必填")
    host = await host_svc.create_host(
        session, name, endpoint, auth_key=body.get("auth_key"), description=body.get("description")
    )
    return ok({
        "host_id": host.id,
        "status": "connected" if host.last_ping_at else "failed",
    })


@router.get("/{host_id}")
async def get_host(host_id: int, session: AsyncSession = Depends(get_session)):
    h = await host_svc.get_host(session, host_id)
    if not h or h.is_deleted:
        raise HTTPException(status_code=404, detail="主机不存在")
    return ok({"id": h.id, "name": h.name, "mcp_endpoint": h.mcp_endpoint, "description": h.description})


@router.put("/{host_id}")
async def update_host(host_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    h = await host_svc.update_host(session, host_id, **{k: v for k, v in body.items() if k in ("name", "mcp_endpoint", "auth_key", "description")})
    if not h:
        raise HTTPException(status_code=404, detail="主机不存在")
    return ok(h.id)


@router.delete("/{host_id}")
async def delete_host(host_id: int, session: AsyncSession = Depends(get_session)):
    return ok(await host_svc.soft_delete_host(session, host_id))


@router.get("/{host_id}/tasks")
async def host_tasks(host_id: int, session: AsyncSession = Depends(get_session)):
    h = await host_svc.get_host(session, host_id)
    if not h or h.is_deleted:
        raise HTTPException(status_code=404, detail="主机不存在")
    rows = await session.execute(
        select(Task).where(Task.host_id == host_id, Task.is_deleted.is_(False))
    )
    return ok(
        [
            {
                "id": t.id,
                "template_id": t.template_id,
                "name": t.name,
                "description": t.description,
                "schedule_json": t.schedule_json,
                "is_enabled": t.is_enabled,
            }
            for t in rows.scalars().all()
        ]
    )


@router.post("/{host_id}/tasks")
async def host_create_task(host_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    h = await host_svc.get_host(session, host_id)
    if not h or h.is_deleted:
        raise HTTPException(status_code=404, detail="主机不存在")
    name = body.get("name")
    if not name:
        return fail("BAD_REQUEST", "name 必填")
    from app.api.tasks import normalize_schedule
    from app.services.task_scheduler import sync_task_job

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
    # 绑定脚本（与 POST /tasks 对齐）
    for sid in body.get("script_ids", []) or []:
        session.add(TaskScript(task_id=t.id, script_id=sid))
    await session.flush()
    try:
        sync_task_job(t.id, t.schedule_json, t.is_enabled)
    except Exception:  # noqa: BLE001
        pass
    return ok({"task_id": t.id, "host_id": host_id})


@router.post("/{host_id}/ping")
async def ping_host(host_id: int, session: AsyncSession = Depends(get_session)):
    h = await host_svc.get_host(session, host_id)
    if not h or h.is_deleted:
        raise HTTPException(status_code=404, detail="主机不存在")
    ok_flag = await host_svc.ping_host(h)
    return ok({"connected": ok_flag})