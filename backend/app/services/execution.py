"""执行引擎：任务触发后的核心链路（D13/D17/D36/D47）。

一次 task_run 的执行流程：
  加载 task_script 列表（含脚本/主机/参数快照）
  → 逐脚本执行：MCP 下发 → 原始输出落磁盘(R-1) → 第一关(确定性) → (success)第二关 LLM 判定
  → 落 Run + Report 占位 + 汇总视图（增量）

降级/失败策略（D17/D38）：
  - host 不可达/执行失败 → Run 记 report_type(host_unreachable/timeout/error) + degradation_notes
  - 第二关 LLM 失败 → level=unknown + 模板兜底（不阻塞报告）
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.exceptions import OpsMindError
from app.core.logging import logger
from app.models import Host, Report, Run, Script, Task, TaskRun, TaskScript
from app.services import events as event_svc
from app.services.judgment import first_gate, second_gate_llm
from app.services.metrics import build_run_metrics

# 运行时注入执行函数，便于测试/雾化（默认走 mcp_client）：
#   exec_runner(endpoint, tool, args, auth_key, timeout) -> dict
async def _default_exec_runner(endpoint: str, tool: str, args: dict, auth_key: str, timeout: float) -> dict:
    from app.executor.mcp_client import call_host

    return await call_host(endpoint, tool, args, auth_key, timeout)


EXEC_RUNNER: Callable[..., Any] = _default_exec_runner

SESSION_FACTORY = session_scope  # 测试可替换为内存库会话工厂

# 运行态注册表（单实例内存，与 events.py 一致）：tr_id -> asyncio.Task / 取消标志
_running_tasks: dict[int, asyncio.Task] = {}
_cancel_flags: dict[int, bool] = {}


def register_running(tr_id: int, task: asyncio.Task) -> None:
    """登记后台执行任务，便于 cancel 查找。"""
    _running_tasks[tr_id] = task
    task.add_done_callback(lambda _t: _running_tasks.pop(tr_id, None))


def request_cancel(tr_id: int) -> bool:
    """请求协作式取消（脚本间断点生效）；返回是否在运行中。"""
    if tr_id in _running_tasks:
        _cancel_flags[tr_id] = True
        return True
    return False


def is_cancelled(tr_id: int) -> bool:
    return _cancel_flags.get(tr_id, False)


def clear_cancel(tr_id: int) -> None:
    _cancel_flags.pop(tr_id, None)


def _write_output(run_id: int, stdout: str, stderr: str, task_run_id: int) -> tuple[str, int]:
    """R-1：原始输出落磁盘，返回 (output_path, size)。"""
    from app.configs.settings import settings

    dir_ = settings.outputs_dir / str(task_run_id)
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{run_id}.out"
    content = f"# stdout\n{stdout}\n# stderr\n{stderr}\n"
    path.write_text(content, encoding="utf-8")
    return str(path), len(content.encode("utf-8"))


async def _run_one(session: AsyncSession, tr: TaskRun, script: Script, host: Host, ts: TaskScript | None = None) -> Run:
    """执行单个脚本：下发→判定→落 Run + Report 占位。

    ts 为空时按脚本本体执行（试跑 trigger=test 场景，无参数覆盖）。
    """
    run = Run(
        task_run_id=tr.id,
        script_id=script.id,
        host_id=host.id,
        report_type="host_unreachable",
        level="unknown",
    )
    session.add(run)
    await session.flush()

    timeout = ts.params_override.get("timeout") if ts and ts.params_override else None
    timeout = timeout or script.timeout
    result_payload: dict | None = None
    try:
        result_payload = await EXEC_RUNNER(
            host.mcp_endpoint,
            "run_script",
            {
                "script_id": str(script.id),
                "content": script.content,
                "timeout": timeout,
                "shell": script.interpreter or script.shell,
            },
            host.auth_key or "",
            timeout + 10,
        )
    except OpsMindError as exc:
        logger.warning(f"主机执行失败 script={script.id}: {exc}")
        run.degradation_notes = [{"tool": "run_script", "why": str(exc), "degraded_to": "skip"}]
        run.exit_code = None
        run.level = "unknown"

    # 归一化执行结果
    exit_code = None
    timed_out = False
    stdout = stderr = ""
    if result_payload:
        exit_code = result_payload.get("exit_code")
        timed_out = bool(result_payload.get("timed_out"))
        stdout = result_payload.get("stdout", "") or ""
        stderr = result_payload.get("stderr", "") or ""
    run.exit_code = exit_code
    run.duration_ms = result_payload.get("duration_ms") if result_payload else None
    run.output_path, run.output_size = _write_output(run.id, stdout, stderr, tr.id)
    run.stdout_preview = stdout[:500]

    # 第一关（确定性短路）
    report_type, should_llm = first_gate(exit_code, timed_out, bool(stdout.strip()))
    run.report_type = report_type

    # 第二关：仅 success 且有效输出；失败则 unknown+备注（不阻塞）
    if should_llm:
        ctx_bundle = tr.context_snapshot or {}
        try:
            judgment = await second_gate_llm(
                script.content,
                script.llm_rule_text,
                stdout,
                {"host": host.name, **ctx_bundle},
            )
            run.llm_judgment = judgment
            run.level = judgment.get("level", "unknown")
        except OpsMindError as exc:
            logger.warning(f"第二关判定失败 script={script.id}: {exc}")
            run.llm_judgment = {"level": "unknown", "reason": f"判定失败: {exc}"}
            run.level = "unknown"
            run.degradation_notes = (run.degradation_notes or []) + [
                {"tool": "llm", "why": str(exc), "degraded_to": "template"}
            ]

    # 跟踪指标合并（03 2.10）：llm metrics + regex 提取
    try:
        run.metrics = await build_run_metrics(session, script.id, stdout, run.llm_judgment)
    except Exception:  # noqa: BLE001 指标提取失败不阻塞主链路
        run.metrics = {}

    # Report 占位（1:1 run）
    _ensure_report(session, run)
    await session.flush()
    # D47：逐 run 完成即推送 run_result（②表格可边跑边亮）
    try:
        await event_svc.publish(
            tr.id,
            "run_result",
            {"run_id": run.id, "script_id": run.script_id, "report_type": run.report_type, "level": run.level},
        )
    except Exception:  # noqa: BLE001 事件推送失败不影响主体
        pass
    return run


def _ensure_report(session: AsyncSession, run: Run) -> Report:
    rep = Report(
        run_id=run.id,
        report_type=run.report_type,
        meta={
            "script_id": run.script_id,
            "host_id": run.host_id,
            "exit_code": run.exit_code,
            "duration_ms": run.duration_ms,
            "level": run.level,
        },
        ai_source="none",
        ai_status="none",
    )
    session.add(rep)
    return rep


async def execute_task_run(tr_id: int) -> dict:
    """执行一个 task_run（供后台任务/测试调用）。"""
    async with SESSION_FACTORY() as session:
        tr = await session.get(TaskRun, tr_id)
        if not tr:
            return {"ok": False, "error": "task_run not found"}
        task = await session.get(Task, tr.task_id)
        host = await session.get(Host, task.host_id) if task else None
        if not task or not host:
            tr.status = "FAILED"
            return {"ok": False, "error": "task/host missing"}

        ts_rows = await session.execute(
            select(TaskScript).where(TaskScript.task_id == tr.task_id, TaskScript.is_enabled.is_(True))
        )
        scripts = []
        for ts in ts_rows.scalars().all():
            sc = await session.get(Script, ts.script_id)
            if sc and sc.is_enabled and not sc.is_deleted:
                scripts.append((ts, sc))
        if not scripts:
            tr.status = "DONE"
            await session.flush()
            return {"ok": True, "runs": 0}

        tr.context_snapshot = {"host": host.name, "host_id": host.id}
        count = 0
        for ts, sc in scripts:
            if is_cancelled(tr_id):
                break
            await _run_one(session, tr, sc, host, ts)
            count += 1

        cancelled = is_cancelled(tr_id)
        # 批次汇总（简版）
        runs = (
            await session.execute(select(Run).where(Run.task_run_id == tr_id))
        ).scalars().all()
        summary = {}
        for r in runs:
            summary[r.report_type] = summary.get(r.report_type, 0) + 1
        tr.summary_json = summary
        tr.status = "CANCELLED" if cancelled else "DONE"
        tr.finished_at = datetime.now(timezone.utc)
        await session.commit()  # 显式提交（SESSION_FACTORY 可能是非自动提交的会话）
        clear_cancel(tr_id)
        try:
            await event_svc.publish(tr_id, "batch_ready", {"summary": summary})
            await event_svc.publish(tr_id, "done", {"task_run_id": tr_id, "cancelled": cancelled})
        except Exception:  # noqa: BLE001
            pass
        logger.info(f"task_run {tr_id} {'已取消' if cancelled else '完成'}，run 数={count}")
        return {"ok": True, "runs": count, "summary": summary, "cancelled": cancelled}


async def execute_script_test(script_id: int, host_id: int, context: dict | None = None) -> dict:
    """试跑（trigger=test）：建 task_id 可空的 TaskRun，直接对该脚本跑一次真执行。

    供 POST /scripts/{id}/run 调用；落 Run + Report，tracking-metrics 可用其真实输出。
    """
    async with SESSION_FACTORY() as session:
        script = await session.get(Script, script_id)
        host = await session.get(Host, host_id)
        if not script or not host or script.is_deleted or not script.is_enabled:
            return {"ok": False, "error": "script/host 不存在或已停用"}

        tr = TaskRun(
            task_id=None,
            trigger="test",
            status="RUNNING",
            context_snapshot={"host": host.name, "host_id": host.id, **(context or {})},
        )
        session.add(tr)
        await session.flush()

        run = await _run_one(session, tr, script, host, None)
        tr.summary_json = {run.report_type: 1}
        tr.status = "DONE"
        tr.finished_at = datetime.now(timezone.utc)
        await session.commit()
        try:
            await event_svc.publish(tr.id, "done", {"task_run_id": tr.id})
        except Exception:  # noqa: BLE001
            pass
        logger.info(f"试跑完成 script={script_id} task_run={tr.id} run={run.id}")
        return {
            "ok": True,
            "task_run_id": tr.id,
            "run_id": run.id,
            "report_type": run.report_type,
            "level": run.level,
            "metrics": run.metrics,
        }