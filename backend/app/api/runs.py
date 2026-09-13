"""Run / 报告 API：报告详情、read_run_output（R-1 磁盘存档）、重新分析（D21 切模型）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.configs.settings import settings
from app.core.db import get_session
from app.models import Report, Run
from app.models.schemas import ok

router = APIRouter(prefix="/runs", tags=["run 与报告"])


@router.get("")
async def list_runs(
    session: AsyncSession = Depends(get_session),
    level: str | None = Query(None),
    report_type: str | None = Query(None),
    script_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = select(Run).order_by(Run.created_at.desc()).limit(limit).offset(offset)
    if level:
        stmt = stmt.where(Run.level == level)
    if report_type:
        stmt = stmt.where(Run.report_type == report_type)
    if script_id:
        stmt = stmt.where(Run.script_id == script_id)
    rows = (await session.execute(stmt)).scalars().all()
    run_ids = [r.id for r in rows]
    reports_map = {}
    if run_ids:
        rep_rows = await session.execute(select(Report).where(Report.run_id.in_(run_ids)))
        for rep in rep_rows.scalars().all():
            reports_map[rep.run_id] = rep
    items = []
    for r in rows:
        rep = reports_map.get(r.id)
        ai_preview = (rep.ai_content or "")[:200] if rep else None
        items.append(
            {
                "id": r.id,
                "script_id": r.script_id,
                "host_id": r.host_id,
                "level": r.level,
                "report_type": r.report_type,
                "exit_code": r.exit_code,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at,
                "ai_content_preview": ai_preview,
                "banner": rep.banner if rep else None,
            }
        )
    return ok({"items": items, "total": len(items)})


@router.get("/{run_id}")
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)):
    r = await session.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run 不存在")
    return ok(
        {
            "run_id": r.id,
            "script_id": r.script_id,
            "host_id": r.host_id,
            "report_type": r.report_type,
            "level": r.level,
            "exit_code": r.exit_code,
            "duration_ms": r.duration_ms,
            "output_path": r.output_path,
            "degradation_notes": r.degradation_notes,
        }
    )


@router.get("/{run_id}/report")
async def get_report(run_id: int, session: AsyncSession = Depends(get_session)):
    rep = (
        await session.execute(select(Report).where(Report.run_id == run_id))
    ).scalars().first()
    if not rep:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ok(
        {
            "report_type": rep.report_type,
            "meta": rep.meta,
            "ai_content": rep.ai_content,
            "ai_source": rep.ai_source,
            "ai_status": rep.ai_status,
            "annotations": rep.annotations,
            "banner": rep.banner,
        }
    )


@router.get("/{run_id}/output")
async def read_output(
    run_id: int,
    start: int | None = Query(default=None),
    end: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    """R-1：读 run 原始输出（磁盘），行区间/关键词/行数上限；路径由后端解析防穿越。"""
    r = await session.get(Run, run_id)
    if not r or not r.output_path:
        raise HTTPException(status_code=404, detail="无输出文件")
    # 防御：确保输出路径在 outputs 目录内（防穿越）
    p = Path(r.output_path).resolve()
    base = settings.outputs_dir.resolve()
    if not str(p).startswith(str(base)):
        raise HTTPException(status_code=403, detail="非法路径")
    if not p.exists():
        raise HTTPException(status_code=404, detail="输出文件丢失")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if start is not None:
        lines = lines[start - 1 :] if start >= 1 else lines
    if end is not None:
        lines = lines[: end - (start or 1) + 1]
    if keyword:
        lines = [ln for ln in lines if keyword in ln]
    body = "".join(lines[:limit])
    return ok({"run_id": run_id, "lines": len(body.splitlines()), "content": body})


@router.post("/{run_id}/reanalyze")
async def reanalyze(run_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    from app.services.report import analyze_run

    r = await session.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run 不存在")
    from app.models import Script

    sc = (await session.get(Script, r.script_id)) if r.script_id else None
    await analyze_run(r.id, (sc.content if sc else ""), (sc.llm_rule_text if sc else None), r.stdout_preview or "", {})
    return ok({"run_id": run_id, "model": body.get("model")})