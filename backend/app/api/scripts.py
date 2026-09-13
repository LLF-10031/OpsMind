"""脚本库 API：脚本生命周期 + 试跑/判定预览 + 跟踪指标 + 趋势（05 API）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import JudgmentFailure
from app.core.limiter import limiter
from app.models import Run, Script
from app.models.schemas import fail, ok
from app.services import execution, tracking
from app.services.report import mask_sensitive

router = APIRouter(prefix="/scripts", tags=["脚本库"])


@router.get("")
async def list_scripts(
    session: AsyncSession = Depends(get_session),
    is_builtin: bool | None = Query(None),
    is_enabled: bool | None = Query(None),
):
    stmt = select(Script).where(Script.is_deleted.is_(False))
    if is_builtin is not None:
        stmt = stmt.where(Script.is_builtin.is_(is_builtin))
    if is_enabled is not None:
        stmt = stmt.where(Script.is_enabled.is_(is_enabled))
    rows = await session.execute(stmt)
    return ok(
        [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "is_builtin": s.is_builtin,
                "is_enabled": s.is_enabled,
                "version": s.version,
            }
            for s in rows.scalars().all()
        ]
    )


@router.post("")
async def create_script(body: dict, session: AsyncSession = Depends(get_session)):
    name = body.get("name")
    content = body.get("content")
    if not name or not content:
        return fail("BAD_REQUEST", "name/content 必填")
    s = Script(
        name=name,
        description=body.get("description"),
        content=content,
        shell=body.get("shell", "bash"),
        interpreter=body.get("interpreter", "bash"),
        timeout=body.get("timeout", 30),
        llm_rule_text=body.get("llm_rule_text"),
        is_builtin=body.get("is_builtin", False),
    )
    session.add(s)
    await session.flush()
    return ok({"script_id": s.id})


async def _get_script(session: AsyncSession, script_id: int) -> Script:
    s = await session.get(Script, script_id)
    if not s or s.is_deleted:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return s


@router.get("/{script_id}")
async def get_script(script_id: int, session: AsyncSession = Depends(get_session)):
    s = await _get_script(session, script_id)
    return ok(
        {
            "id": s.id,
            "name": s.name,
            "content": s.content,
            "llm_rule_text": s.llm_rule_text,
            "interpreter": s.interpreter,
            "timeout": s.timeout,
            "version": s.version,
        }
    )


@router.put("/{script_id}")
async def update_script(script_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    s = await _get_script(session, script_id)
    fields = ("description", "content", "shell", "interpreter", "timeout", "llm_rule_text", "is_enabled")
    for k in fields:
        if k in body:
            setattr(s, k, body[k])
    s.version += 1
    return ok({"script_id": s.id, "version": s.version})


@router.delete("/{script_id}")
async def delete_script(script_id: int, session: AsyncSession = Depends(get_session)):
    s = await session.get(Script, script_id)
    if not s:
        return ok(False)
    s.is_deleted = True
    return ok(True)


@router.post("/{script_id}/run")
async def run_script(script_id: int, host_id: int = Query(...), session: AsyncSession = Depends(get_session)):
    """试跑：对该脚本在指定 host 上真实执行一次（trigger=test），落库供跟踪提取复用。"""
    await _get_script(session, script_id)
    result = await execution.execute_script_test(script_id, host_id)
    if not result["ok"]:
        return fail("SCRIPT_UNAVAILABLE", result["error"])
    return ok(
        {
            "task_run_id": result["task_run_id"],
            "run_id": result["run_id"],
            "report_type": result["report_type"],
            "level": result["level"],
            "metrics": result["metrics"],
        }
    )


@router.post("/{script_id}/preview-llm")
async def preview_llm(script_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    """判定规则预览（不落库）：用脚本内容+规则（可临时改）/样例输出跑第二关，返回 level/reason/metrics。"""
    s = await _get_script(session, script_id)
    rule = body.get("llm_rule_text") or s.llm_rule_text
    sample = body.get("sample_output")
    if not sample:
        row = (
            await session.execute(
                select(Run).where(Run.script_id == script_id).order_by(Run.created_at.desc()).limit(1)
            )
        ).scalars().first()
        sample = row.stdout_preview if row else ""
    try:
        from app.services.judgment import second_gate_llm

        result = await second_gate_llm(
            s.content,
            rule,
            sample,
            {"host": body.get("context_host"), **(body.get("context") or {})} if body.get("context") else None,
        )
    except JudgmentFailure as exc:
        return fail("LLM_FAILED", str(exc))
    return ok(
        {
            "level": result.get("level", "unknown"),
            "reason": result.get("reason", ""),
            "metrics": result.get("metrics") or {},
            "sample_output": sample[:2000],
        }
    )


@router.get("/{script_id}/tracking-metrics")
async def list_tracking_metrics(script_id: int, session: AsyncSession = Depends(get_session)):
    await _get_script(session, script_id)
    rows = await tracking.list_script_metrics(session, script_id)
    return ok([tracking._to_dict(tm) for tm in rows])


@router.post("/{script_id}/tracking-metrics")
async def create_tracking_metric(script_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    await _get_script(session, script_id)
    name = body.get("name")
    if not name:
        return fail("BAD_REQUEST", "name 必填")
    tm = await tracking.create_metric(
        session,
        script_id,
        name,
        regex_pattern=body.get("regex_pattern"),
        extraction_mode=body.get("extraction_mode", "llm_regex"),
        unit=body.get("unit"),
    )
    return ok({"tracking_metric_id": tm.id, **(tracking._to_dict(tm))})


@router.get("/{script_id}/trend")
async def script_trend(
    script_id: int,
    tracking_metric: str | None = Query(None),
    window: int = Query(30, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """指标趋势：历史 run 的 level/report_type 列 + 各指标序列（可指定 tracking_metric 过滤）。"""
    data = await tracking.get_trend(session, script_id, metric_key=tracking_metric, window=window)
    return ok(data)


@router.post("/{script_id}/trend-summary")
async def trend_summary(
    script_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    """趋势总结（按需 LLM）：把最近 window 次的 level/指标序列交给 LLM 产出趋势判断。"""
    window = int(body.get("window", 30))
    metric = body.get("tracking_metric")
    data = await tracking.get_trend(session, script_id, metric_key=metric, window=window)
    snippet = {
        "history": [
            {"started_at": str(h["started_at"]), "level": h["level"], "report_type": h["report_type"]}
            for h in data["history"]
        ],
        "series": {
            k: [{"ts": str(p["ts"]), "value": p["value"], "source": p["source"]} for p in v]
            for k, v in data["series"].items()
        },
    }
    prompt = (
        "你是运维趋势分析师。以下是一个巡检脚本最近若干次运行的 level/report_type 列与按指标拆分的序列。\n"
        "请给出：整体态势、是否恶化、可疑指标、建议动作（3-5 条要点）。\n"
        f"【数据】{snippet}\n"
    )
    if not limiter.try_acquire_llm():
        return fail("LIMITED", "限流繁忙")
    try:
        from app.core.llm import get_default_llm

        llm = get_default_llm()
        resp = await llm.ainvoke(prompt)
        limiter.llm_success()
        summary = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:  # noqa: BLE001
        limiter.llm_failure()
        return fail("LLM_FAILED", f"趋势总结失败: {exc}")
    finally:
        limiter.release_llm()
    return ok({"summary": mask_sensitive(str(summary))})
