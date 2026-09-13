"""模板/通用任务方案库 API（05 五）：CRUD + apply 到主机生成任务。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Task, TaskScript, Template, TemplateScript
from app.models.schemas import fail, ok

router = APIRouter(prefix="/templates", tags=["模板"])


async def _get(session: AsyncSession, template_id: int) -> Template:
    t = await session.get(Template, template_id)
    if not t or t.is_deleted:
        raise HTTPException(status_code=404, detail="模板不存在")
    return t


@router.get("")
async def list_templates(session: AsyncSession = Depends(get_session)):
    rows = (
        (await session.execute(select(Template).where(Template.is_deleted.is_(False))))
        .scalars()
        .all()
    )
    return ok([
        {"id": t.id, "name": t.name, "description": t.description,
         "schedule_json": t.schedule_json, "is_builtin": t.is_builtin}
        for t in rows
    ])


@router.post("")
async def create_template(body: dict, session: AsyncSession = Depends(get_session)):
    name = body.get("name")
    if not name:
        return fail("BAD_REQUEST", "name 必填")
    t = Template(
        name=name,
        description=body.get("description"),
        schedule_json=body.get("schedule_json"),
        is_builtin=body.get("is_builtin", False),
    )
    session.add(t)
    await session.flush()
    for sid in body.get("script_ids", []) or []:
        session.add(TemplateScript(template_id=t.id, script_id=sid))
    return ok({"template_id": t.id})


@router.get("/{template_id}")
async def get_template(template_id: int, session: AsyncSession = Depends(get_session)):
    t = await _get(session, template_id)
    rows = (
        (await session.execute(
            select(TemplateScript).where(TemplateScript.template_id == template_id)
        ))
        .scalars()
        .all()
    )
    return ok({
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "schedule_json": t.schedule_json,
        "scripts": [
            {"script_id": r.script_id, "script_version_at_bind": r.script_version_at_bind,
             "params_override": r.params_override, "is_enabled": r.is_enabled}
            for r in rows
        ],
    })


@router.put("/{template_id}")
async def update_template(template_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    t = await _get(session, template_id)
    if "name" in body:
        t.name = body["name"]
    if "description" in body:
        t.description = body.get("description")
    if "schedule_json" in body:
        t.schedule_json = body.get("schedule_json")
    # 显式传 script_ids 时整体替换脚本关联
    if "script_ids" in body:
        old = (await session.execute(
            select(TemplateScript).where(TemplateScript.template_id == template_id)
        )).scalars().all()
        for r in old:
            await session.delete(r)
        for sid in body.get("script_ids", []) or []:
            session.add(TemplateScript(template_id=t.id, script_id=sid))
    return ok(t.id)


@router.delete("/{template_id}")
async def delete_template(template_id: int, session: AsyncSession = Depends(get_session)):
    t = await _get(session, template_id)
    t.is_deleted = True
    return ok(t.id)


@router.post("/{template_id}/apply")
async def apply_template(template_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    """套用到主机生成任务。body: {host_id, task_name?, task_description?}"""
    host_id = body.get("host_id")
    if not host_id:
        return fail("BAD_REQUEST", "host_id 必填")
    t = await _get(session, template_id)
    rows = (
        (await session.execute(
            select(TemplateScript).where(
                TemplateScript.template_id == template_id, TemplateScript.is_enabled.is_(True)
            )
        ))
        .scalars()
        .all()
    )
    task = Task(
        host_id=host_id,
        template_id=t.id,
        name=body.get("task_name", t.name),
        description=body.get("task_description", t.description),
        schedule_json=t.schedule_json,
    )
    session.add(task)
    await session.flush()
    for r in rows:
        session.add(TaskScript(
            task_id=task.id,
            script_id=r.script_id,
            script_version_at_bind=r.script_version_at_bind,
            params_override=r.params_override,
        ))
    await session.flush()
    try:
        from app.services.task_scheduler import sync_task_job

        sync_task_job(task.id, task.schedule_json, task.is_enabled)
    except Exception:  # noqa: BLE001
        pass
    return ok({"task_id": task.id})
