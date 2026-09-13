"""数据库访问（SQLAlchemy async + pgvector 一体）。

- 业务元数据 + 向量都在同一 PG（D4/D41：pgvector 一体）。
- 控制端单实例，连接数保持小池。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.configs.settings import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.async_db_url,
    echo=False,
    poolclass=NullPool,  # 单机小规模：每次新连接，规避 asyncpg 跨事件循环复用报错（测试/脚本/uvicorn 都稳）
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """建表（开发期简单用 metadata.create_all；生产建议 Alembic）。"""
    from app.models import register_models  # noqa: F401 触发导入注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每次请求一个会话，自动提交/回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    await engine.dispose()