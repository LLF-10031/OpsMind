"""SSE 事件存储（内存、按 task_run_id 订阅）。

D18/D47：一次执行 = "一个动作 + 一条 SSE 通道"。
事件：run_result / batch_ready / ai_done / diag_started /
      diagnostic_done / diag_failed / done / error
单实例内存队列即可（D30 单机）；重启后丢失仅影响"实时推送"，报告仍可查。
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

_lock = asyncio.Lock()
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


async def subscribe(tr_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    async with _lock:
        _subscribers[tr_id].add(q)
    return q


async def unsubscribe(tr_id: int, q: asyncio.Queue) -> None:
    async with _lock:
        _subscribers[tr_id].discard(q)
        if not _subscribers[tr_id]:
            _subscribers.pop(tr_id, None)


async def publish(tr_id: int, event: str, data: Any) -> None:
    async with _lock:
        qs = list(_subscribers.get(tr_id, set()))
    payload = f"data: {data}\n\n"
    for q in qs:
        try:
            q.put_nowait((event, payload))
        except asyncio.QueueFull:
            pass  # 订阅端消费慢则丢事件（不影响报告主体）


async def stream_events(tr_id: int):
    """async generator 给 SSE endpoint 用。"""
    q = await subscribe(tr_id)
    try:
        while True:
            try:
                event, payload = await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                yield "event: heartbeat\ndata: ping\n\n"
                continue
            yield f"event: {event}\n{payload}"
            if event == "done":
                break
    finally:
        await unsubscribe(tr_id, q)