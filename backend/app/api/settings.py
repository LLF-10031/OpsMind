"""系统设置 API（05 十二）：GET 合并默认+DB 覆盖；PUT 持久化并运行时生效。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.schemas import ok
from app.services import settings as settings_svc

router = APIRouter(prefix="/settings", tags=["系统设置"])


@router.get("")
async def get_settings(session: AsyncSession = Depends(get_session)):
    return ok(await settings_svc.get_all_settings(session))


@router.put("")
async def update_settings(body: dict, session: AsyncSession = Depends(get_session)):
    masked = await settings_svc.update_settings(session, body)
    await session.commit()
    return ok(masked)
