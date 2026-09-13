"""评估 API（O7/D48）：案例 CRUD + 运行评估 + 结果/雷达图。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import EvalCase, EvalResult
from app.models.schemas import fail, ok
from app.services.evaluation import compute_aggregate, run_evaluation

router = APIRouter(prefix="/eval", tags=["评估"])


@router.get("/cases")
async def list_cases(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(EvalCase).where(EvalCase.is_deleted.is_(False)))).scalars().all()
    return ok([{"id": c.id, "title": c.title, "expected_level": c.expected_level, "tags": c.tags} for c in rows])


@router.post("/cases")
async def create_case(body: dict, session: AsyncSession = Depends(get_session)):
    case = EvalCase(
        title=body["title"],
        description=body.get("description"),
        script_content=body.get("script_content", ""),
        expected_level=body.get("expected_level", "ok"),
        expected_report_type=body.get("expected_report_type", "success"),
        ground_truth=body.get("ground_truth"),
        tags=body.get("tags"),
    )
    session.add(case)
    await session.flush()
    return ok({"case_id": case.id})


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(EvalCase, case_id)
    if not c:
        return fail("NOT_FOUND", "案例不存在")
    c.is_deleted = True
    return ok(True)


@router.post("/run")
async def run_eval(body: dict, session: AsyncSession = Depends(get_session)):
    case_ids = body.get("case_ids")
    results = await run_evaluation(session, case_ids)
    agg = compute_aggregate(results)
    return ok({"results": results, "aggregate": agg})


@router.get("/results")
async def list_results(session: AsyncSession = Depends(get_session), limit: int = 100):
    rows = (await session.execute(select(EvalResult).order_by(EvalResult.id.desc()).limit(limit))).scalars().all()
    return ok(
        [
            {
                "id": r.id,
                "run_id": r.run_id,
                "case_id": r.case_id,
                "actual_level": r.actual_level,
                "actual_report_type": r.actual_report_type,
                "level_hit": r.level_hit,
                "report_type_hit": r.report_type_hit,
                "score": r.score,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    )


@router.get("/results/{result_id}")
async def result_detail(result_id: int, session: AsyncSession = Depends(get_session)):
    r = await session.get(EvalResult, result_id)
    if not r:
        return fail("NOT_FOUND", "结果不存在")
    group = (await session.execute(select(EvalResult).where(EvalResult.run_id == r.run_id))).scalars().all()
    agg = {
        "total": len(group),
        "level_hit": sum(1 for x in group if x.level_hit) / max(len(group), 1),
        "report_type_hit": sum(1 for x in group if x.report_type_hit) / max(len(group), 1),
        "average_score": sum(x.score for x in group) / max(len(group), 1),
    }
    return ok(
        {
            "id": r.id,
            "run_id": r.run_id,
            "case_id": r.case_id,
            "actual_level": r.actual_level,
            "actual_report_type": r.actual_report_type,
            "level_hit": r.level_hit,
            "report_type_hit": r.report_type_hit,
            "score": r.score,
            "detail": r.detail,
            "created_at": r.created_at,
            "aggregate": agg,
            "radar": {
                "dimensions": ["命中率", "误报率", "报告质量"],
                "values": [agg["level_hit"], 1 - agg["report_type_hit"], agg["average_score"]],
            },
        }
    )