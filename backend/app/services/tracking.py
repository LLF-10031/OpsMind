"""跟踪指标服务（03 2.4）：CRUD + 趋势（D49 tracking 落地）。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Run, TrackingMetric


async def list_script_metrics(session: AsyncSession, script_id: int):
    rows = await session.execute(
        select(TrackingMetric).where(TrackingMetric.script_id == script_id).order_by(TrackingMetric.id)
    )
    return list(rows.scalars().all())


async def create_metric(
    session: AsyncSession,
    script_id: int,
    name: str,
    regex_pattern: str | None = None,
    extraction_mode: str = "llm_regex",
    unit: str | None = None,
) -> TrackingMetric:
    tm = TrackingMetric(
        script_id=script_id,
        name=name,
        extraction_mode=extraction_mode,
        regex_pattern=regex_pattern,
        unit=unit,
        is_enabled=True,
    )
    session.add(tm)
    await session.flush()
    return tm


async def get_metric(session: AsyncSession, tm_id: int) -> TrackingMetric | None:
    return await session.get(TrackingMetric, tm_id)


def _to_dict(tm: TrackingMetric) -> dict:
    return {
        "id": tm.id,
        "script_id": tm.script_id,
        "name": tm.name,
        "extraction_mode": tm.extraction_mode,
        "regex_pattern": tm.regex_pattern,
        "unit": tm.unit,
        "is_enabled": tm.is_enabled,
    }


async def recent_runs(session: AsyncSession, script_id: int, window: int = 30) -> list[Run]:
    """最近 N 次 run（时间升序，趋势图用）。"""
    rows = await session.execute(
        select(Run)
        .where(Run.script_id == script_id)
        .order_by(Run.created_at.desc())
        .limit(window)
    )
    return list(reversed(list(rows.scalars().all())))


async def get_trend(session: AsyncSession, script_id: int, metric_key: str | None = None, window: int = 30) -> dict:
    """趋势：run 列（level/report_type 时间线）+ 指标序列（按 metric_key 过滤可选）。"""
    from app.models import TaskRun

    runs = await recent_runs(session, script_id, window)
    history: list[dict[str, Any]] = []
    series: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        ts = str(r.task_run_id) if r.task_run_id else ""
        started = None
        if r.task_run_id:
            tr = await session.get(TaskRun, r.task_run_id)
            started = tr.started_at if tr else r.created_at
        else:
            started = r.created_at
        history.append(
            {
                "task_run_id": r.task_run_id,
                "started_at": started,
                "level": r.level,
                "report_type": r.report_type,
            }
        )
        for k, info in (r.metrics or {}).items():
            if metric_key and k != metric_key:
                continue
            series.setdefault(k, []).append(
                {
                    "ts": started,
                    "value": info.get("value"),
                    "source": info.get("source"),
                    "unit": info.get("unit"),
                }
            )
    return {"history": history, "series": series, "window": window}
