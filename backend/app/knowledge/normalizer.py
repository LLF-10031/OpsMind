"""文档规范化管线（D40）：原文 → 规范化 md → unit → key_index。

三步保位：
  1. 加载：md 透传 / txt 包装 / pdf 抽文本层
  2. 图/表位置补丁：图片→原位"图片#n 解析"+序号（可选多模态）
  3. 结构化骨架：标题树不动，每 section 一次小LLM生成 intent → 写 UNIT 注释

产物：normalized_md（含 `<!-- UNIT id kind intent -->` 注释）。
后续 splitter 从注释切 unit；indexer 生成 key 并向量化。
"""
from __future__ import annotations

import re
from typing import Any

from app.core.logging import logger


class NormalizerResult:
    def __init__(self, normalized_md: str, units_count: int, warnings: list[str]):
        self.normalized_md = normalized_md
        self.units_count = units_count
        self.warnings = warnings


def load_text(file_type: str, content: bytes, filename: str) -> str:
    """1. 加载：按类型抽取文本。"""
    if file_type == "md":
        return content.decode("utf-8", errors="replace")
    if file_type == "txt":
        return content.decode("utf-8", errors="replace")
    if file_type == "pdf":
        # 文本层抽取（扫描页降级标注，OCR=演进点）
        try:
            from pypdf import PdfReader
            from io import BytesIO

            reader = PdfReader(BytesIO(content))
            pages = []
            for i, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if not text.strip():
                    text = f"\n> [第 {i} 页为扫描/无文本层，OCR=演进点]\n"
                pages.append(text)
            return "\n\n".join(pages)
        except Exception as exc:  # pragma: no cover
            logger.error(f"pdf 抽取失败 {filename}: {exc}")
            return "\n> [pdf 文本层抽取失败，需人工处理]\n"
    raise ValueError(f"不支持的 file_type: {file_type}")


def patch_images(md: str, image_markers: list[dict[str, Any]]) -> str:
    """2. 图片位置补丁：把图片占位替换为 `[图片#n]` + 说明（可选多模态）。"""
    for idx, marker in enumerate(sorted(image_markers, key=lambda m: m.get("pos", 0)), 1):
        alt = marker.get("alt", "")
        desc = marker.get("ai_description")
        note = f"[图片#{idx} 解析] " + (desc or "（图片，需人工查看）")
        placeholder = f"![{alt or 'image'}]({marker.get('url', '#')})"
        # 若占位存在则替换；否则在原位置插入; 简化：找不到就追加到尾
        if placeholder in md:
            md = md.replace(placeholder, f"{note}\n{placeholder}")
        else:
            md += f"\n\n{note}\n{placeholder}\n"
    return md


def build_unit_md(sections: list[dict[str, Any]]) -> str:
    """3. 结构化骨架：在标题前插入 `<!-- UNIT kind intent -->` 注释（intent 由外部 LLM 填）。"""
    lines = []
    for sec in sections:
        intent = sec.get("intent") or ""
        kind = sec.get("kind") or "manual"
        lines.append(f"<!-- UNIT kind={kind} intent=\"{intent}\" -->\n{sec.get('text', '')}")
    return "\n\n".join(lines)


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def split_sections(md: str) -> list[dict[str, Any]]:
    """按标题树粗分 section（供生成 UNIT）。"""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in md.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if current:
                sections.append(current)
            current = {"heading": line, "level": len(m.group(1)), "body": []}
        elif current is not None:
            current["body"].append(line)
        else:
            sections.append({"heading": "", "level": 0, "body": [line]})
    if current:
        sections.append(current)
    for sec in sections:
        sec["text"] = sec["heading"] + "\n" + "\n".join(sec["body"])
    return sections