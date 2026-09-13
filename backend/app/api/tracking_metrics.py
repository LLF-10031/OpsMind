"""跟踪指标 API（05 §四）：toggle / 停用删除 / 预览提取效果。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import TrackingMetric
from app.models.schemas import ok
from app.services import tracking
from app.services.metrics import preview_metric_from_last_run

router = APIRouter(prefix="/tracking-metrics", tags=["跟踪指标"])


async def _get_tm(session: AsyncSession, tm_id: int) -> TrackingMetric:
    tm = await session.get(TrackingMetric, tm_id)
    if not tm:
        raise HTTPException(status_code=404, detail="指标不存在")
    return tm


@router.put("/{tm_id}/toggle")
async def toggle_metric(tm_id: int, session: AsyncSession = Depends(get_session)):
    tm = await _get_tm(session, tm_id)
    tm.is_enabled = not tm.is_enabled
    return ok({**(tracking._to_dict(tm))})


@router.delete("/{tm_id}")
async def disable_metric(tm_id: int, session: AsyncSession = Depends(get_session)):
    """停用该指标（保留配置，不再参与提取/落 run.metrics）。"""
    tm = await _get_tm(session, tm_id)
    tm.is_enabled = False
    return ok({**(tracking._to_dict(tm))})


@router.post("/{tm_id}/preview")
async def preview_metric(tm_id: int, session: AsyncSession = Depends(get_session)):
    """用最近一次 run 的真实输出验证提取效果（不落库），供指标配置校验。"""
    tm = await _get_tm(session, tm_id)
    return ok(await preview_metric_from_last_run(session, tm))
