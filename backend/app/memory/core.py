"""三层记忆（D44）。

- Working：当前会话（由 context.py / session 表管理）
- Episodic：片段闭合沉淀（D44：压缩闭合/闲置10min/手动保存）→ 去杂去重
- Semantic：累计≥30 Episodic → 轻模型提炼 → 跨会话证据校验

去重/去杂管道（双层，D44）：
  代码硬杀（空/寒暄→丢）+ 代码召回（候选池）+ LLM 判断 + 代码收尾（校验引用/合并范围）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


@dataclass
class Episode:
    id: str
    topic: str
    summary: str
    session_id: str
    keywords: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    manually_saved: bool = False


class EpisodicStore:
    """内存版本（无 PG 时先用）；正式落 PG 用表 episodic。"""

    def __init__(self):
        self._items: list[Episode] = []

    def add(self, ep: Episode) -> None:
        self._items.append(ep)

    def list(self) -> list[Episode]:
        return list(self._items)

    def search_by_keyword(self, q: str, limit: int = 3) -> list[Episode]:
        toks = set(q.split())
        scored = []
        for ep in self._items:
            hit = sum(1 for kw in ep.keywords if any(t in kw for t in toks))
            if hit:
                scored.append((hit, ep))
        scored.sort(key=lambda kv: kv[0], reverse=True)
        return [e for _, e in scored[:limit]]


def code_hard_filter(topic: str, summary: str) -> bool:
    """代码硬杀：空/寒暄丢弃。判断权留给 LLM 更细的语义，这里硬规则兜底。"""
    if not topic.strip() or not summary.strip():
        return False
    low = (topic + summary).lower()
    greetings = {"你好", "hi", "hello", "谢谢", "bye", "ok", "嗯", "hmm"}
    if any(g in low for g in greetings):
        return False
    return True