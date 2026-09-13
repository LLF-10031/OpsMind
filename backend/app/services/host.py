"""主机服务：CRUD + MCP 连通性探测（D30/D13）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.exceptions import OpsMindError
from app.executor.mcp_client import call_host
from app.models import Host


async def list_hosts(session: AsyncSession) -> list[Host]:
    rows = await session.execute(select(Host).where(Host.is_deleted.is_(False)))
    return list(rows.scalars().all())


async def get_host(session: AsyncSession, host_id: int) -> Host | None:
    return await session.get(Host, host_id)


async def create_host(
    session: AsyncSession,
    name: str,
    mcp_endpoint: str,
    auth_key: str | None = None,
    description: str | None = None,
) -> Host:
    # 加主机即做连通性探测
    try:
        info = await call_host(mcp_endpoint, "ping", {}, auth_key or "")
        connected = bool(info)
    except OpsMindError:
        connected = False
    host = Host(
        name=name,
        mcp_endpoint=mcp_endpoint,
        auth_key=auth_key,
        description=description,
        last_ping_at=datetime.now(timezone.utc) if connected else None,
    )
    session.add(host)
    await session.flush()
    return host


async def update_host(session: AsyncSession, host_id: int, **fields) -> Host | None:
    host = await session.get(Host, host_id)
    if not host or host.is_deleted:
        return None
    for k, v in fields.items():
        if hasattr(host, k):
            setattr(host, k, v)
    return host


async def soft_delete_host(session: AsyncSession, host_id: int) -> bool:
    host = await session.get(Host, host_id)
    if not host:
        return False
    host.is_deleted = True
    return True


async def ping_host(host: Host) -> bool:
    try:
        await call_host(host.mcp_endpoint, "ping", {}, host.auth_key or "")
        host.last_ping_at = datetime.now(timezone.utc)
        return True
    except OpsMindError:
        return False