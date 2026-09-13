"""P5.2 验收 e2e：真实 PG + 真实 executor MCP 服务。

覆盖：host_svc.create_host（建主机即 MCP ping 探活）、ping_host、软删除清理。
"""
import asyncio
import sys
import time

sys.path.insert(0, r"D:\IdeaDocs\myproject\OpsMind\backend")

from app.core.db import session_scope
from app.services import host as host_svc


async def main() -> None:
    async with session_scope() as session:
        h = await host_svc.create_host(
            session, f"e2e-smoke-host-{int(time.time())}", "http://localhost:8003", description="P5.2 e2e smoke"
        )
        await session.commit()
        print("create_host -> id:", h.id, "| connected:", bool(h.last_ping_at))

        ok = await host_svc.ping_host(h)
        await session.commit()
        print("ping_host ->", ok, "| last_ping_at:", h.last_ping_at)

        await host_svc.soft_delete_host(session, h.id)
        await session.commit()
        print("soft_delete ->", h.is_deleted)


asyncio.run(main())
