"""跟踪指标提取与合并（03 2.4 / 2.10；D49 tracking 落地）。

- second_gate_llm 返回 {level, reason, metrics?} → llm 指标直存 run.metrics（source=llm）；
- script 级 TrackingMetric 配置 regex → 对 stdout 提取合并（source=regex）；
- tracking-metrics preview 复用同一套提取逻辑（拿最近一次 run 的真实输出）。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrackingMetric


def extract_regex_value(pattern: str, text: str) -> Any:
    """正则提取单个指标：优先取第一个捕获组；解析失败返回原串；无匹配返回 None。"""
    try:
        m = re.search(pattern, text)
    except re.error:
        return None
    if not m:
        return None
    raw = m.group(1) if m.lastindex else m.group(0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return raw


async def extract_regex_metrics(session: AsyncSession, script_id: int, text: str) -> dict:
    """对文本应用该脚本启用的 regex 类指标，返回 {name: {value, source, unit?}}。"""
    rows = await session.execute(
        select(TrackingMetric).where(
            TrackingMetric.script_id == script_id,
            TrackingMetric.is_enabled.is_(True),
        )
    )
    out: dict[str, Any] = {}
    for tm in rows.scalars().all():
        mode = (tm.extraction_mode or "").lower()
        if "regex" not in mode:
            continue
        if not tm.regex_pattern:
            continue
        val = extract_regex_value(tm.regex_pattern, text or "")
        if val is None:
            continue
        metric: dict[str, Any] = {"value": val, "source": "regex"}
        if tm.unit:
            metric["unit"] = tm.unit
        out[tm.name or f"m{tm.id}"] = metric
    return out


async def build_run_metrics(
    session: AsyncSession,
    script_id: int,
    stdout: str,
    llm_judgment: dict | None,
) -> dict:
    """合并 llm metrics + regex 提取 → run.metrics（03 2.10）。"""
    out: dict[str, Any] = {}
    lm = (llm_judgment or {}).get("metrics") or {}
    for k, v in lm.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = {"value": v, "source": "llm"}
    out.update(await extract_regex_metrics(session, script_id, stdout or ""))
    return out


async def preview_metric_from_last_run(session: AsyncSession, tm: TrackingMetric) -> dict:
    """tracking-metrics preview：用最近一次 run 的真实输出验证提取效果。"""
    from app.models import Run

    row = (
        await session.execute(
            select(Run).where(Run.script_id == tm.script_id).order_by(Run.created_at.desc()).limit(1)
        )
    ).scalars().first()

    llm_metrics = {}
    if row and row.llm_judgment:
        llm_metrics = (row.llm_judgment or {}).get("metrics") or {}

    mode = (tm.extraction_mode or "").lower()
    result: dict[str, Any] = {"metric": tm.name, "matched": False}
    if row is None:
        result.update({"value": None, "source": None, "sample": "", "llm_metrics": llm_metrics})
        return result

    text = ""
    if row.output_path:
        try:
            text = open(row.output_path, encoding="utf-8").read()
        except OSError:  # noqa: BLE001
            text = ""
    text = text or row.stdout_preview or ""
    result["sample"] = text[:2000]

    if "regex" in mode and tm.regex_pattern:
        val = extract_regex_value(tm.regex_pattern, text)
        if val is not None:
            result.update({"value": val, "source": "regex", "matched": True})
    if "llm" in mode and tm.name in llm_metrics:
        result.update({"value": llm_metrics[tm.name], "source": "llm", "matched": True})
    result["llm_metrics"] = llm_metrics
    return result
