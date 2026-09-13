"""JSON 提取/修复工具（LLM 结构化输出解析）。"""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json_from_text(text: str) -> dict[str, Any]:
    """从 LLM 文本中提取 JSON 对象。

    按序尝试：① 直接 json.loads ② 代码块 ```json ... ``` ③ 首尾花括号切片。
    失败返回空 dict。
    """
    if not text:
        return {}
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass

    # ```json\n{...}\n```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass

    # 首尾花括号
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
    return {}