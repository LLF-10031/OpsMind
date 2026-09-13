"""任务执行历史与报告 API（D18/D47）：报告详情、read_run_output、task-run 详情。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Report, Run, TaskRun
from app.models.schemas import fail, ok
from app.services import events

router = APIRouter(prefix="/task-runs", tags=["任务历史与报告"])


@router.get("/{task_run_id}/stream")
async def task_run_stream(task_run_id: int):
    """SSE 实时通道（D18/D47）：
    run_result / batch_ready / ai_done / diagnostic_done / done / error
    """
    async def gen():
        try:
            async for chunk in events.stream_events(task_run_id):
                yield chunk
        except Exception:  # noqa: BLE001
            yield "event: error\ndata: {\"message\": \"stream closed\"}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{task_run_id}")
async def task_run_detail(task_run_id: int, session: AsyncSession = Depends(get_session)):
    tr = await session.get(TaskRun, task_run_id)
    if not tr:
        raise HTTPException(status_code=404, detail="不存在")
    runs = (await session.execute(select(Run).where(Run.task_run_id == task_run_id))).scalars().all()
    return ok(
        {
            "task_run_id": tr.id,
            "status": tr.status,
            "trigger": tr.trigger,
            "started_at": tr.started_at,
            "summary_json": tr.summary_json,
            "run_count": len(runs),
        }
    )


@router.get("/{task_run_id}/diagnosis")
async def task_run_diagnosis(task_run_id: int, session: AsyncSession = Depends(get_session)):
    """联动诊断结果（D38）。未触发/失败未落库 → diagnosed=false。"""
    tr = await session.get(TaskRun, task_run_id)
    if not tr:
        raise HTTPException(status_code=404, detail="不存在")
    if not tr.diagnosis_json:
        return ok({"task_run_id": task_run_id, "diagnosed": False})
    return ok({"task_run_id": task_run_id, "diagnosed": True, **tr.diagnosis_json})


@router.get("/{task_run_id}/runs")
async def runs_of(task_run_id: int, session: AsyncSession = Depends(get_session)):
    from app.models import Script

    rows = (
        await session.execute(select(Run).where(Run.task_run_id == task_run_id))
    ).scalars().all()
    # 脚本名映射
    script_ids = [r.script_id for r in rows if r.script_id]
    name_map: dict[int, str] = {}
    if script_ids:
        sc_rows = await session.execute(select(Script).where(Script.id.in_(script_ids)))
        name_map = {s.id: s.name for s in sc_rows.scalars().all()}
    # 报告预览映射
    rep_map: dict[int, Report] = {}
    run_ids = [r.id for r in rows]
    if run_ids:
        rep_rows = await session.execute(select(Report).where(Report.run_id.in_(run_ids)))
        rep_map = {rep.run_id: rep for rep in rep_rows.scalars().all()}
    items = []
    for r in rows:
        rep = rep_map.get(r.id)
        items.append(
            {
                "run_id": r.id,
                "script_id": r.script_id,
                "script_name": name_map.get(r.script_id),
                "report_type": r.report_type,
                "level": r.level,
                "ai_source": rep.ai_source if rep else None,
                "ai_preview": (rep.ai_content or "")[:200] if rep else None,
                "banner": rep.banner if rep else None,
            }
        )
    return ok(items)


@router.post("/{task_run_id}/cancel")
async def cancel_task_run(task_run_id: int, session: AsyncSession = Depends(get_session)):
    """协作式取消：置标志，执行引擎在下一脚本间断点停止。"""
    from app.services.execution import request_cancel

    tr = await session.get(TaskRun, task_run_id)
    if not tr:
        raise HTTPException(status_code=404, detail="不存在")
    if tr.status not in ("PENDING", "RUNNING"):
        return fail("NOT_RUNNING", "任务不在运行中")
    if not request_cancel(task_run_id):
        return fail("NOT_RUNNING", "任务不在运行中（无后台句柄）")
    return ok({"task_run_id": task_run_id, "cancelling": True})