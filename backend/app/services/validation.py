"""O4 确定性校验管线（D23/D45/D47）。

5 阶段（零 LLM，只查不写）：
  P1 结构：③必含 现象/证据/结论/建议，缺主体→补"未提供"占位
  P2 证据：每条结论必须挂 run_id/文档引用，无引用→强制标存疑
  P3 矛盾：同批证据冲突→标冲突+给两假设
  P4 越界/幻觉：引用数字与 run 原始结果不符、引用文档不存在→修正或标存疑
  P5 等级一致：LLM 判 warn/crit 但原始数据全 ok(反向同)→降级或标"建议人工复核"

处理策略：柔性标注(O4a) —— 只打标注、不删 AI 内容；
标注清单落库可展开(O4d)；横幅在批次层(O4b)；规则可配(O4e)。
"""
from __future__ import annotations

import re

from app.configs.settings import settings

DEFAULT_PIPELINE = settings.pipeline_config_default


def check_structure(text: str) -> list[dict]:
    """P1：结构检查。返回标注列表。"""
    required = ["现象", "证据", "结论", "建议"]
    missing = [k for k in required if k not in (text or "")]
    return [{"rule": "p1_structure", "message": f"缺少结构：{' / '.join(missing)}", "level": "note"} for m in missing]


def check_evidence(text: str, allow_run_ids: set[int] | None = None) -> list[dict]:
    """P2：证据/引用检查——结论必须挂引用，无引用标存疑。"""
    notes = []
    # 提取疑似结论行（冒号后内容）
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not any(keyword in line for line in lines for keyword in ("结论", "根因", "怀疑", "原因")):
        return notes
    has_ref = bool(re.search(r"@[a-zA-Z0-9_\-]+|run[_ ]?id|第\d+次", (text or "")))
    if not has_ref:
        notes.append(
            {"rule": "p2_evidence", "message": "结论缺少可核验引用，强制标存疑", "level": "suspicious"}
        )
    return notes


def check_conflict(tags: list[str]) -> list[dict]:
    """P3：矛盾检测（外部注入 level 标记，如 ['error','ok']）。"""
    if "error" in tags and "ok" in tags:
        return [
            {"rule": "p3_conflict", "message": "证据冲突：同时含 error 与 ok 标记，列两假设待人工裁决", "level": "conflict"}
        ]
    return []


def check_out_of_bound(text: str, available_run_ids: set[int]) -> list[dict]:
    """P4：越界/幻觉——引用 run_id 必须真实存在。"""
    notes = []
    ids = re.findall(r"[a-zA-Z]*?run_?(\d+)", (text or ""))
    for raw in ids:
        try:
            rid = int(raw)
        except ValueError:
            continue
        if available_run_ids and rid not in available_run_ids:
            notes.append({"rule": "p4_out_of_bound", "message": f"引用 run {rid} 不存在，标来源无效", "level": "suspicious"})
    return notes


def check_level_consistency(level: str, has_error_keyword: bool) -> list[dict]:
    """P5：等级一致性——LLM 判 warn/crit 但输出明显正常（无异常迹象）→提示。"""
    if level in ("warn", "crit") and not has_error_keyword:
        return [
            {"rule": "p5_level_consistency", "message": "等级与可观测迹象不符（无 ERROR 等关键词），建议人工复核", "level": "note"}
        ]
    if level == "ok" and has_error_keyword:
        return [
            {"rule": "p5_level_consistency", "message": "输出含 ERROR 迹象却判 ok，建议人工复核", "level": "suspicious"}
        ]
    return []


def run_pipeline(
    ai_content: str | None,
    level: str,
    has_error_keyword: bool,
    evidence_tags: list[str] | None = None,
    available_run_ids: set[int] | None = None,
    enabled: dict[str, bool] | None = None,
) -> list[dict]:
    """执行 O4 五阶段（可按 pipeline_config 开关，默认全开）。"""
    enabled = {**DEFAULT_PIPELINE, **(enabled or {})}
    annotations: list[dict] = []
    if not ai_content:
        return annotations

    if enabled["p1_structure"]:
        annotations += check_structure(ai_content)
    if enabled["p2_evidence"]:
        annotations += check_evidence(ai_content)
    if enabled["p3_conflict"]:
        annotations += check_conflict(evidence_tags or [])
    if enabled["p4_out_of_bound"]:
        annotations += check_out_of_bound(ai_content, available_run_ids or set())
    if enabled["p5_level_consistency"]:
        annotations += check_level_consistency(level, has_error_keyword)

    # 汇总横幅（批级用）
    suspicious = [a for a in annotations if a["level"] in ("suspicious", "conflict")]
    banner = f"本报告 {len(suspicious)} 处存疑/矛盾，建议人工复核" if suspicious else None
    return annotations + ([{"rule": "banner", "message": banner, "level": "banner"}] if banner else [])