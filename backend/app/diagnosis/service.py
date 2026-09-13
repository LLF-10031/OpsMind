"""诊断服务：批次级异常联动诊断（D36/D38/D47）。

触发语义（D47）：批次中出现 crit/error/timeout/host_unreachable → 跑一次联动诊断。
- 幂等：同一 task_run 的 diagnosis_json 已存在则跳过（含并发/重入）。
- 限流：diagnostic_concurrency 信号量 + diagnostic_total_timeout 总超时。
- 事件/审计：diag_started / diagnostic_done / diag_failed + audit(scope="diagnosis")。
- 诚实降级：失败不写 diagnosis_json（保留 None，允许后续重试），只发事件+审计。
"""
from __future__ import annotations

import asyncio
import time

from app.configs.settings import get_settings
from app.core.logging import logger
from app.diagnosis.blackboard import DiagnosticState, validate_contract
from app.diagnosis.graph import get_graph
from app.models import Host, TaskRun
from app.services import events as event_svc
from app.services.audit import audit, audit_degradation

_ANOMALY_REPORT_TYPES = ("error", "timeout", "host_unreachable")
_diag_sem = asyncio.Semaphore(get_settings().diagnostic_concurrency)


def _session_factory():
    # 懒取：共享 execution 的会话工厂（测试可替换 execution.SESSION_FACTORY）
    from app.services.execution import SESSION_FACTORY

    return SESSION_FACTORY


def is_anomalous(pairs: list[tuple[str, str]]) -> bool:
    """pairs = [(report_type, level), ...]；crit 或 error/timeout/host_unreachable → 需诊断。"""
    for report_type, level in pairs:
        if level == "crit" or report_type in _ANOMALY_REPORT_TYPES:
            return True
    return False


async def diagnose_task_run(task_run_id: int, host_id: int) -> dict | None:
    """在批次执行内联调用：跑诊断→落库→发事件。返回 payload；跳过/失败返回 None。"""
    async with _diag_sem:
        factory = _session_factory()
        # 幂等前置检查
        async with factory() as session:
            tr = await session.get(TaskRun, task_run_id)
            host = await session.get(Host, host_id)
            if not tr or not host:
                return None
            if tr.diagnosis_json is not None:
                return None
            endpoint, auth_key = host.mcp_endpoint, host.auth_key or ""
            context = tr.context_snapshot or {}

        started = time.monotonic()
        await _safe_publish(task_run_id, "diag_started", {"task_run_id": task_run_id})
        try:
            state = DiagnosticState(
                task_run_id=task_run_id, host_id=host_id,
                endpoint=endpoint, auth_key=auth_key, context=context,
            )
            timeout = get_settings().diagnostic_total_timeout
            raw = await asyncio.wait_for(get_graph().ainvoke(state), timeout=timeout)
            final = DiagnosticState(**raw) if isinstance(raw, dict) else raw
            problems = validate_contract(final)
            payload = _to_payload(final, problems, int((time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"诊断失败 task_run={task_run_id}: {exc}")
            audit_degradation("diagnosis", "run", str(exc), "skip")
            await _safe_publish(task_run_id, "diag_failed", {"task_run_id": task_run_id, "why": str(exc)})
            return None

        # 落库（再次校验幂等，避免并发重复写）
        async with factory() as session:
            tr = await session.get(TaskRun, task_run_id)
            if tr and tr.diagnosis_json is None:
                tr.diagnosis_json = payload
                await session.commit()
        audit("diagnosis", "conclusion", {
            "task_run_id": task_run_id,
            "conclusions": len(payload["conclusions"]),
            "evidence": _evidence_counts(payload),
            "contract_problems": problems,
            "elapsed_ms": payload["elapsed_ms"],
        })
        await _safe_publish(task_run_id, "diagnostic_done", {
            "task_run_id": task_run_id,
            "conclusions": payload["conclusions"],
            "flags": payload["flags"],
        })
        logger.info(f"诊断完成 task_run={task_run_id}，结论 {len(payload['conclusions'])} 条")
        return payload


def _to_payload(state: DiagnosticState, problems: list[str], elapsed_ms: int) -> dict:
    return {
        "status": "done",
        "task_run_id": state.task_run_id,
        "host_id": state.host_id,
        "hypothesis": state.hypothesis,
        "evidence": {
            "logs": state.evidence_logs,
            "metrics": state.evidence_metrics,
            "changes": state.evidence_changes,
        },
        "conclusions": state.conclusions,
        "flags": state.flags,
        "degradation_notes": state.degradation_notes,
        "contract_ok": not problems,
        "contract_problems": problems,
        "elapsed_ms": elapsed_ms,
    }


def _evidence_counts(payload: dict) -> dict:
    ev = payload["evidence"]
    return {k: len(v) for k, v in ev.items()}


async def _safe_publish(tr_id: int, event: str, data: dict) -> None:
    try:
        await event_svc.publish(tr_id, event, data)
    except Exception:  # noqa: BLE001 事件失败不影响诊断
        pass
