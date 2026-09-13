"""黑板契约（D38）：多 Agent 诊断的共享状态（各写各格子）。

约定（契约）：
- Planner 只写 hypothesis[]
- 三个 Executor 各自只写自己的 evidence 格子：
    log -> evidence_logs[] · metric -> evidence_metrics[] · change -> evidence_changes[]
- Reviewer 只写 conclusions[]
- 任何角色可追加 flags[] / degradation_notes[]

`validate_contract()` 用确定性规则校验"写入合规"，供测试与运行期自检。
"""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field


def merge_lists(a: list | None, b: list | None) -> list:
    """LangGraph reducer：多节点并发写同一列表字段时合并而非互斥。"""
    return (a or []) + (b or [])

# 证据槽位 → 事件/Executor 名，供契约校验与 Reviewer 汇总
EVIDENCE_SLOT: dict[str, str] = {
    "log": "evidence_logs",
    "metric": "evidence_metrics",
    "change": "evidence_changes",
}
EVIDENCE_FIELDS = tuple(EVIDENCE_SLOT.values())


class DiagnosticState(BaseModel):
    """诊断黑板（D38 状态契约）。"""

    task_run_id: int = 0
    host_id: int = 0
    endpoint: str = ""          # 目标机 MCP endpoint（Executor 采集用）
    auth_key: str = ""
    context: dict[str, Any] = Field(default_factory=dict)  # 背景包（主机/被检应用）

    hypothesis: list[dict] = Field(default_factory=list)      # Planner
    evidence_logs: list[dict] = Field(default_factory=list)   # log executor
    evidence_metrics: list[dict] = Field(default_factory=list)  # metric executor
    evidence_changes: list[dict] = Field(default_factory=list)  # change executor
    conclusions: list[dict] = Field(default_factory=list)     # Reviewer

    flags: Annotated[list[str], merge_lists] = Field(default_factory=list)
    degradation_notes: Annotated[list[dict], merge_lists] = Field(default_factory=list)
    error: str | None = None


def slot_for(executor: str) -> str:
    """executor 名 → 其唯一允许写入的 evidence 字段。"""
    return EVIDENCE_SLOT[executor]


def all_evidence_empty(state: DiagnosticState) -> bool:
    """三格证据是否全空（全空 → Reviewer 不得出结论，只标'证据不足'）。"""
    return not (state.evidence_logs or state.evidence_metrics or state.evidence_changes)


def evidence_count(state: DiagnosticState) -> int:
    return len(state.evidence_logs) + len(state.evidence_metrics) + len(state.evidence_changes)


def validate_contract(state: DiagnosticState) -> list[str]:
    """契约自检：返回违规说明列表（空 = 合规）。

    规则：
    - conclusions 非空时，必须有证据（否则违反"无证据不出结论"）；
    - hypothesis 的 kind 必须是 log|metric|change（否则 Planner 越界）。
    """
    problems: list[str] = []
    if state.conclusions and all_evidence_empty(state):
        problems.append("conclusions 非空但无任何证据（违反：无证据不出结论）")
    for h in state.hypothesis:
        kind = str(h.get("kind", ""))
        if kind and kind not in EVIDENCE_SLOT:
            problems.append(f"hypothesis.kind 非法: {kind}")
    return problems
