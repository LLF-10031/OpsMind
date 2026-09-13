"""unit 切分（D40/D41）：读 normalized_md 的 `<!-- UNIT ... -->` 注释 → 结构化 unit。

产出：list[unit]，unit = {
  kind, intent, value(原文保真), parent_context, path,
  media/step, original_range, section_id
}
同 key 跨单元不物理合并；检索候选带 parent_context 由 LLM 裁决（D41）。
"""
from __future__ import annotations

import re
from typing import Any

UNIT_RE = re.compile(r"<!--\s*UNIT\s+(.*?)\s*-->\s*\n(.*?)", re.DOTALL)


def parse_unit_md(normalized_md: str) -> list[dict[str, Any]]:
    """从规范化 md 中切出单元。"""
    units = []
    raw = re.findall(r"<!--\s*UNIT\s+(.*?)\s*-->(.*?)(?=<!--\s*UNIT\s+|$)", normalized_md, re.DOTALL)
    for idx, (meta_raw, body) in enumerate(raw):
        meta = dict(re.findall(r"(\w+)=(\"[^\"]*\"|[^\s\"]+)", meta_raw))
        kind = meta.get("kind", "manual").strip('"')
        intent = meta.get("intent", "").strip('"')
        body = body.strip()
        units.append(
            {
                "section_id": f"u{idx + 1}",
                "kind": kind,
                "intent": intent,
                "value": body,  # 原文保真
                "parent_context": "",  # 由调用方填标题链
                "path": "",
                "media": [],
            }
        )
    return units


def append_parent_context(units: list[dict[str, Any]], headings: list[str]) -> list[dict[str, Any]]:
    """为每个 unit 填充父级上下文（标题链 + 最近一级标题），防断章取义（D41）。"""
    for u in units:
        u["path"] = " → ".join(headings[-3:]) if headings else ""
        u["parent_context"] = u["path"]
    return units