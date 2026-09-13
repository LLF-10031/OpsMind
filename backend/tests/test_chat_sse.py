"""chat SSE 流式回答（P3.6）：事件序列与降级兜底。"""
from __future__ import annotations

from app.main import app
from starlette.testclient import TestClient


def _parse_sse(raw: str) -> list[tuple[str, str]]:
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        if event:
            events.append((event, data))
    return events


def test_chat_sse_empty_message():
    with TestClient(app) as client:
        r = client.post("/chat", json={"message": ""})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        events = _parse_sse(r.text)
        assert events and events[0][0] == "error"


def test_chat_sse_unselected_kb():
    """未勾选文档：search_kb 返回提示 → LLM 不上场 → done 回显提示。"""
    with TestClient(app) as client:
        r = client.post("/chat", json={"message": "你好"})
        assert r.status_code == 200
        events = _parse_sse(r.text)
        names = [e for e, _ in events]
        assert "start" in names
        assert "kb_ready" in names
        assert names[-1] == "done"
        done = [d for n, d in events if n == "done"]
        assert done and "reply" in done[0]
