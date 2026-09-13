"""pytest 公共 fixture：异步 sqlite 内存会话（测试专用，不触真实 PG）。"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """每个测试独立的内存 sqlite + 全新 schema；返回绑定该引擎的 AsyncSession。

    注意：execution 内部使用 session_scope()（全局 engine），无法共享本内存库。
    因此该 fixture 仅用于"模型/导航"类测试；若测试执行引擎，
    需 monkeypatch app.services.execution 的会话工厂 → 指向本引擎。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    TestSession = async_sessionmaker(engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
    await engine.dispose()