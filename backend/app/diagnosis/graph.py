"""多 Agent 诊断图（D38 最简版，真用 LangGraph StateGraph）。

拓扑：
    START → planner
          → {exec_log, exec_metric, exec_change}  （并行 superstep）
          → reviewer → END

角色：
- Planner：基于背景包产出假设（只写 hypothesis[]）。
- Executor ×3：各自下发只读探针，只写自己的 evidence 格子（并行不互踩）。
- Reviewer：汇总证据出结论（只写 conclusions[]）；无证据则不出结论。

LLM / 采集函数均可注入，便于测试离线运行（PLANNER_FN / REVIEWER_FN / COLLECT_FN）。
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.core.limiter import limiter
from app.core.llm import get_default_llm
from app.core.logging import logger
from app.diagnosis.blackboard import DiagnosticState, all_evidence_empty, slot_for
from app.diagnosis.executors import default_collect
from app.utils.safe_json import extract_json_from_text

# --- 可注入依赖（测试替换为离线桩） ---
PLANNER_FN: Callable[[DiagnosticState], Awaitable[list[dict]]] | None = None
REVIEWER_FN: Callable[[DiagnosticState], Awaitable[list[dict]]] | None = None
COLLECT_FN: Callable[[str, str, str, float], Awaitable[dict]] | None = None

_VALID_KINDS = ("log", "metric", "change")


async def _llm_json(prompt: str, *, scope: str) -> Any:
    """限流内调用 LLM 并解析 JSON（失败抛异常，由调用方降级）。"""
    if not limiter.try_acquire_llm():
        raise RuntimeError(f"LLM 限流器繁忙（{scope}）")
    try:
        resp = await get_default_llm().ainvoke(prompt)
        limiter.llm_success()
        text = resp.content if hasattr(resp, "content") else str(resp)
        return extract_json_from_text(text)
    except Exception:
        limiter.llm_failure()
        raise
    finally:
        limiter.release_llm()


def _fallback_hypotheses() -> list[dict]:
    """Planner 降级：覆盖三类证据的通用假设（确定性，保证诊断仍可跑）。"""
    return [
        {"text": "应用日志存在异常/报错", "kind": "log"},
        {"text": "主机资源（CPU/内存/磁盘）紧张", "kind": "metric"},
        {"text": "近期有配置/镜像/文件变更", "kind": "change"},
    ]


async def _default_plan(state: DiagnosticState) -> list[dict]:
    prompt = f"""你是运维故障诊断的 Planner。根据背景，列出最多 {{n}} 条待验证假设。
每条假设必须归属一类核查方向 kind ∈ {list(_VALID_KINDS)}（log=日志, metric=指标, change=变更）。

【背景包】
{json.dumps(state.context or {}, ensure_ascii=False)}

只输出 JSON 数组：[{{"text": "假设描述", "kind": "log|metric|change"}}]
"""
    from app.configs.settings import get_settings

    prompt = prompt.replace("{n}", str(get_settings().hypothesis_max))
    try:
        parsed = await _llm_json(prompt, scope="diagnosis.planner")
        items = parsed if isinstance(parsed, list) else parsed.get("hypotheses", [])
        out: list[dict] = []
        for h in items:
            kind = str(h.get("kind", "")).lower()
            text = str(h.get("text", "")).strip()
            if text and kind in _VALID_KINDS:
                out.append({"text": text, "kind": kind})
        return out or _fallback_hypotheses()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Planner 降级（{exc}）")
        return _fallback_hypotheses()


async def _default_review(state: DiagnosticState) -> list[dict]:
    if all_evidence_empty(state):
        return []
    evidence = {
        "logs": state.evidence_logs,
        "metrics": state.evidence_metrics,
        "changes": state.evidence_changes,
    }
    prompt = f"""你是运维故障诊断的 Reviewer。基于证据与被验证假设，给出结论。
若证据不足以支撑，宁可不给结论。confidence 取 0~1。

【假设】
{json.dumps(state.hypothesis, ensure_ascii=False)}

【证据】
{json.dumps(evidence, ensure_ascii=False)[:6000]}

只输出 JSON 数组：[{{"text": "结论", "confidence": 0.0, "evidence_refs": ["logs|metrics|changes"]}}]
"""
    try:
        parsed = await _llm_json(prompt, scope="diagnosis.reviewer")
        items = parsed if isinstance(parsed, list) else parsed.get("conclusions", [])
        out: list[dict] = []
        for c in items:
            text = str(c.get("text", "")).strip()
            if not text:
                continue
            try:
                conf = float(c.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            refs = [r for r in (c.get("evidence_refs") or []) if r in ("logs", "metrics", "changes")]
            out.append({"text": text, "confidence": max(0.0, min(1.0, conf)), "evidence_refs": refs})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Reviewer 降级（{exc}）")
        return _rule_based_conclusion(state)


def _rule_based_conclusion(state: DiagnosticState) -> list[dict]:
    """Reviewer 降级：仅按"哪类证据非空"给低置信度结论（不无中生有）。"""
    refs = []
    if state.evidence_logs:
        refs.append("logs")
    if state.evidence_metrics:
        refs.append("metrics")
    if state.evidence_changes:
        refs.append("changes")
    if not refs:
        return []
    return [{"text": "已采集到 " + "/".join(refs) + " 证据，需人工进一步研判", "confidence": 0.3, "evidence_refs": refs}]


# --- 图节点 ---
async def planner_node(state: DiagnosticState) -> dict:
    plan = await (PLANNER_FN or _default_plan)(state)
    return {"hypothesis": plan}


def _make_executor(executor: str):
    async def _node(state: DiagnosticState) -> dict:
        collect = COLLECT_FN or default_collect
        item = await collect(executor, state.endpoint, state.auth_key, 20.0)
        if item.get("error"):
            # 采集失败：不写证据格（保持空），只记降级说明
            return {"degradation_notes": [{"agent": executor, "why": item["error"], "degraded_to": "empty"}]}
        return {slot_for(executor): [item]}

    return _node


async def reviewer_node(state: DiagnosticState) -> dict:
    conclusions = await (REVIEWER_FN or _default_review)(state)
    # 契约兜底：无证据不得有结论
    if all_evidence_empty(state):
        conclusions = []
    updates: dict[str, Any] = {"conclusions": conclusions}
    if all_evidence_empty(state):
        updates["flags"] = ["证据不足"]
    return updates


def build_diagnosis_graph():
    g = StateGraph(DiagnosticState)
    g.add_node("planner", planner_node)
    for name in ("log", "metric", "change"):
        g.add_node(f"exec_{name}", _make_executor(name))
    g.add_node("reviewer", reviewer_node)

    g.add_edge(START, "planner")
    for name in ("log", "metric", "change"):
        g.add_edge("planner", f"exec_{name}")
        g.add_edge(f"exec_{name}", "reviewer")
    g.add_edge("reviewer", END)
    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_diagnosis_graph()
    return _GRAPH
